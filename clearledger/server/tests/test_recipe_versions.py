import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Company, StoreRecipeVersion
from app.services.recipe_versions import (
    build_bundle, content_hash, ingest_station_bundle, validate_recipe_set,
)


def _recipes():
    return [
        {
            "dish_uuid": "semi-1", "dish_name": "Соус", "recipe_kind": "semi",
            "output_qty": 100, "output_unit": "г", "lines": [
                {"item": "raw-1", "name": "Основа", "qty": 80, "unit": "г"},
                {"item": "raw-2", "name": "Вода", "qty": 20, "unit": "мл"},
            ],
        },
        {
            "dish_uuid": "dish-1", "dish_name": "Хот-дог", "recipe_kind": "dish",
            "output_qty": 1, "output_unit": "шт", "lines": [
                {"item": "semi-1", "name": "Соус", "qty": 15, "unit": "г"},
                {"item": "raw-3", "name": "Булочка", "qty": 1, "unit": "шт"},
            ],
        },
        {
            "dish_uuid": "combo-1", "dish_name": "Хот-дог комбо", "recipe_kind": "combo",
            "output_qty": 1, "output_unit": "шт", "lines": [
                {"item": "dish-1", "name": "Хот-дог", "qty": 1, "unit": "шт"},
                {"item": "raw-4", "name": "Салфетка", "qty": 1, "unit": "шт"},
            ],
        },
    ]


def _rows():
    valid_from = datetime(2026, 8, 3, 8, tzinfo=timezone.utc)
    return [SimpleNamespace(
        dish_uuid=recipe["dish_uuid"], dish_name=recipe["dish_name"],
        recipe_kind=recipe["recipe_kind"], version=index + 1,
        output_qty=recipe["output_qty"], output_unit=recipe["output_unit"],
        lines=recipe["lines"], valid_from=valid_from,
    ) for index, recipe in enumerate(_recipes())]


def test_nested_semi_and_combo_form_one_valid_set():
    normalized = validate_recipe_set(_recipes())
    assert [recipe["recipe_kind"] for recipe in normalized] == ["semi", "dish", "combo"]


def test_cycle_rejected_before_bundle_delivery():
    recipes = _recipes()
    recipes[0]["lines"].append({"item": "combo-1", "name": "Обратная ссылка", "qty": 1, "unit": "шт"})

    with pytest.raises(HTTPException, match="Цикл в ТТК"):
        validate_recipe_set(recipes)


def test_nested_recipe_requires_same_output_unit():
    recipes = _recipes()
    recipes[1]["lines"][0]["unit"] = "мл"

    with pytest.raises(HTTPException, match="выход измеряется в г"):
        validate_recipe_set(recipes)


def test_bundle_identity_is_stable_and_changes_with_recipe():
    generated = datetime(2026, 8, 3, 9, tzinfo=timezone.utc)
    first = build_bundle(_rows(), generated)
    second = build_bundle(_rows(), generated)
    changed_rows = _rows()
    changed_rows[1].lines = [*changed_rows[1].lines]
    changed_rows[1].lines[1] = {**changed_rows[1].lines[1], "qty": 2}
    changed = build_bundle(changed_rows, generated)

    assert first["bundle_id"] == second["bundle_id"]
    assert first["content_hash"] == second["content_hash"]
    assert first["bundle_id"] != changed["bundle_id"]
    assert first["schema_version"] == 2


def test_recipe_hash_ignores_json_key_order_but_not_content():
    recipe = _recipes()[0]
    reordered = {
        "lines": recipe["lines"], "output_qty": 100, "output_unit": "г", "recipe_kind": "semi",
        "dish_name": "Соус", "dish_uuid": "semi-1",
    }
    changed = {**recipe, "output_qty": 101}

    assert content_hash(recipe) == content_hash(reordered)
    assert content_hash(recipe) != content_hash(changed)


@pytest.mark.asyncio(loop_scope="session")
async def test_station_bundle_bootstraps_registry_and_next_change_activates(db):
    """Второй набор со станции сразу действует, а прежний уходит в архив.

    Раньше проверка ждала черновика — по прежней модели, где карту со станции
    активировал человек в центре. Модель изменили осознанно: на станции карта
    УЖЕ применена, по ней продают и списывают сырьё, и черновик размыкал
    контур — путь в «active» был только через ручку активации, закрытую той же
    политикой, версии копились, а центр показывал канон, которого на станции
    нет. Проверка догоняет код: имя говорило обратное тому, что происходит.
    """
    company = Company(name="Тест ТТК станции", slug=f"recipe-{uuid.uuid4().hex[:10]}",
                      profile_id="gig")
    db.add(company)
    await db.commit()
    await db.refresh(company)
    try:
        first = await ingest_station_bundle(db, company.id, 208, {
            "bundle_id": "station-208-first", "note": "Исходный набор",
            "recipes": _recipes(),
        })
        assert first == {"created": 3, "unchanged": 0, "initial": True,
                         "bundle_id": "station-208-first", "recipes": 3}
        rows = list((await db.execute(select(StoreRecipeVersion).where(
            StoreRecipeVersion.company_id == company.id))).scalars().all())
        assert {row.status for row in rows} == {"active"}
        assert {row.source for row in rows} == {"station"}
        assert {row.source_station_id for row in rows} == {208}

        changed = _recipes()
        changed[1]["lines"][1]["qty"] = 2
        second = await ingest_station_bundle(db, company.id, 208, {
            "bundle_id": "station-208-second", "note": "Булочка крупнее",
            "recipes": changed,
        })
        assert second["created"] == 1
        assert second["unchanged"] == 2
        current = (await db.execute(select(StoreRecipeVersion).where(
            StoreRecipeVersion.company_id == company.id,
            StoreRecipeVersion.dish_uuid == "dish-1",
            StoreRecipeVersion.status == "active",
        ))).scalar_one()
        assert current.version == 2
        assert current.change_note == "Булочка крупнее"
        # Две действующие карты одного блюда — спор о том, что списывать:
        # прежняя обязана закрыться тем же ходом.
        archived = (await db.execute(select(StoreRecipeVersion).where(
            StoreRecipeVersion.company_id == company.id,
            StoreRecipeVersion.dish_uuid == "dish-1",
            StoreRecipeVersion.status == "archived",
        ))).scalar_one()
        assert archived.version == 1 and archived.valid_to is not None
    finally:
        await db.delete(company)
        await db.commit()
