"""Версионные ТТК Ledger и атомарный набор доставки на станции."""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StoreRecipeVersion


KINDS = {"dish", "semi", "combo"}


def normalize_recipe(data: dict) -> dict:
    lines = []
    seen: set[str] = set()
    for source in data.get("lines") or []:
        item = str(source.get("item") or "").strip()
        name = str(source.get("name") or "").strip()
        unit = str(source.get("unit") or "").strip()
        try:
            qty = float(source.get("qty") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"Некорректное количество компонента {name or item}") from exc
        if not item or qty <= 0 or not unit:
            raise HTTPException(422, "У каждого компонента нужны UUID, количество больше нуля и единица")
        if item in seen:
            raise HTTPException(422, f"Компонент {item} указан в ТТК дважды")
        seen.add(item)
        lines.append({"item": item, "name": name, "qty": qty, "unit": unit})

    dish_uuid = str(data.get("dish_uuid") or data.get("dish") or "").strip()
    dish_name = str(data.get("dish_name") or data.get("name") or "").strip()
    kind = str(data.get("recipe_kind") or data.get("kind") or "dish").strip().lower()
    try:
        output = float(data.get("output_qty") or data.get("output") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"Некорректный выход ТТК {dish_name or dish_uuid}") from exc
    if not dish_uuid or not dish_name:
        raise HTTPException(422, "У ТТК нужны UUID и наименование блюда")
    if kind not in KINDS:
        raise HTTPException(422, f"Неизвестный вид ТТК: {kind}")
    if output <= 0:
        raise HTTPException(422, f"Выход ТТК «{dish_name}» должен быть больше нуля")
    output_unit = str(data.get("output_unit") or "шт").strip()
    if not output_unit:
        raise HTTPException(422, f"У ТТК «{dish_name}» не указана единица выхода")
    if not lines:
        raise HTTPException(422, f"В ТТК «{dish_name}» нет компонентов")
    return {
        "dish_uuid": dish_uuid, "dish_name": dish_name, "recipe_kind": kind,
        "output_qty": output, "output_unit": output_unit, "lines": lines,
    }


def validate_recipe_set(recipes: list[dict]) -> list[dict]:
    normalized = [normalize_recipe(recipe) for recipe in recipes]
    by_id: dict[str, dict] = {}
    for recipe in normalized:
        if recipe["dish_uuid"] in by_id:
            raise HTTPException(422, f"ТТК {recipe['dish_uuid']} встречается дважды")
        by_id[recipe["dish_uuid"]] = recipe

    state: dict[str, int] = {}

    def walk(recipe_id: str, path: list[str]) -> None:
        if state.get(recipe_id) == 1:
            cycle = " → ".join([*path, recipe_id])
            raise HTTPException(422, f"Цикл в ТТК: {cycle}")
        if state.get(recipe_id) == 2:
            return
        state[recipe_id] = 1
        for line in by_id[recipe_id]["lines"]:
            if line["item"] in by_id:
                walk(line["item"], [*path, recipe_id])
        state[recipe_id] = 2

    for recipe_id in by_id:
        walk(recipe_id, [])
    for recipe in normalized:
        for line in recipe["lines"]:
            nested = by_id.get(line["item"])
            if nested and line["unit"] != nested["output_unit"]:
                raise HTTPException(
                    422,
                    f"В ТТК «{recipe['dish_name']}» компонент «{nested['dish_name']}» "
                    f"задан в {line['unit']}, а его выход измеряется в {nested['output_unit']}",
                )
    return normalized


def content_hash(recipe: dict) -> str:
    raw = json.dumps(normalize_recipe(recipe), ensure_ascii=False,
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def row_dict(row: StoreRecipeVersion) -> dict:
    return {
        "id": str(row.id), "dish_uuid": row.dish_uuid, "dish_name": row.dish_name,
        "recipe_kind": row.recipe_kind, "version": row.version, "status": row.status,
        "output_qty": float(row.output_qty), "output_unit": row.output_unit,
        "lines": row.lines or [],
        "content_hash": row.content_hash, "valid_from": row.valid_from,
        "valid_to": row.valid_to, "activated_at": row.activated_at,
        "source": row.source, "source_station_id": row.source_station_id,
        "change_note": row.change_note, "source_bundle_id": row.source_bundle_id,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


async def active_versions(db: AsyncSession, company_id: uuid.UUID,
                          at: datetime | None = None) -> list[StoreRecipeVersion]:
    at = at or datetime.now(timezone.utc)
    return list((await db.execute(
        select(StoreRecipeVersion).where(
            StoreRecipeVersion.company_id == company_id,
            StoreRecipeVersion.status == "active",
            StoreRecipeVersion.valid_from <= at,
            or_(StoreRecipeVersion.valid_to.is_(None), StoreRecipeVersion.valid_to > at),
        ).order_by(StoreRecipeVersion.dish_name, StoreRecipeVersion.dish_uuid)
    )).scalars().all())


def build_bundle(rows: list[StoreRecipeVersion], generated_at: datetime | None = None) -> dict:
    if not rows:
        raise HTTPException(409, "Нет действующих версионных ТТК")
    generated_at = generated_at or datetime.now(timezone.utc)
    recipes = [{
        "dish": row.dish_uuid,
        "name": row.dish_name,
        "kind": row.recipe_kind,
        "version": row.version,
        "output": float(row.output_qty),
        "output_unit": row.output_unit,
        "valid_from": row.valid_from.isoformat() if row.valid_from else "",
        "lines": row.lines or [],
    } for row in rows]
    validate_recipe_set([{
        "dish_uuid": recipe["dish"], "dish_name": recipe["name"],
        "recipe_kind": recipe["kind"], "output_qty": recipe["output"],
        "output_unit": recipe["output_unit"],
        "lines": recipe["lines"],
    } for recipe in recipes])
    canonical = json.dumps(recipes, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    effective = max((row.valid_from for row in rows if row.valid_from), default=generated_at)
    return {
        "bundle_id": f"ttk-{digest[:16]}",
        "schema_version": 2,
        "generated_at": generated_at.isoformat(),
        "effective_from": effective.isoformat(),
        "content_hash": digest,
        "source": "center",
        "note": "Утверждено в центре",
        "recipes": recipes,
    }


async def bootstrap_legacy(db: AsyncSession, company_id: uuid.UUID,
                           user_id: uuid.UUID | None) -> int:
    existing = (await db.execute(select(func.count()).select_from(StoreRecipeVersion).where(
        StoreRecipeVersion.company_id == company_id))).scalar() or 0
    if existing:
        raise HTTPException(409, "Версионные ТТК уже заведены")
    rows = (await db.execute(text("""
        SELECT r.dish_uuid, r.output_qty,
               coalesce(d.name, '') AS dish_name,
               json_agg(json_build_object(
                   'item', l.item_uuid, 'qty', l.qty, 'unit', l.unit,
                   'name', coalesce(i.name, '')) ORDER BY l.item_uuid) AS lines
        FROM edge.recipe r
        JOIN edge.recipe_line l ON l.recipe_id = r.id
        LEFT JOIN edge.item d ON d.external_uuid = r.dish_uuid
        LEFT JOIN edge.item i ON i.external_uuid = l.item_uuid
        GROUP BY r.dish_uuid, r.output_qty, d.name
        ORDER BY d.name
    """))).mappings().all()
    if not rows:
        raise HTTPException(404, "В импортированном срезе нет ТТК")
    now = datetime.now(timezone.utc)
    recipes = validate_recipe_set([{
        "dish_uuid": str(row["dish_uuid"]), "dish_name": row["dish_name"],
        "recipe_kind": "dish", "output_qty": float(row["output_qty"] or 1),
        "lines": row["lines"] or [],
    } for row in rows])
    for recipe in recipes:
        db.add(StoreRecipeVersion(
            company_id=company_id, dish_uuid=recipe["dish_uuid"],
            dish_name=recipe["dish_name"], recipe_kind=recipe["recipe_kind"],
            version=1, status="active", output_qty=recipe["output_qty"],
            output_unit=recipe["output_unit"],
            lines=recipe["lines"], content_hash=content_hash(recipe),
            valid_from=now, activated_at=now, created_by=user_id,
            source="import", change_note="Перенесено из старого среза Edge",
        ))
    await db.commit()
    return len(recipes)


async def ingest_station_bundle(db: AsyncSession, company_id: uuid.UUID,
                                station_id: int, bundle: dict) -> dict:
    if not isinstance(bundle, dict):
        raise HTTPException(422, "Станция не передала набор ТТК")
    source_recipes = bundle.get("recipes") or []
    if not isinstance(source_recipes, list) or not source_recipes:
        raise HTTPException(422, "Станция передала пустой набор ТТК")
    recipes = validate_recipe_set(source_recipes)
    now = datetime.now(timezone.utc)
    bundle_id = str(bundle.get("bundle_id") or "")[:100]
    note = str(bundle.get("note") or "Изменено на станции")[:500]
    existing_count = (await db.execute(select(func.count()).select_from(
        StoreRecipeVersion).where(
            StoreRecipeVersion.company_id == company_id))).scalar() or 0
    initial = existing_count == 0
    created = 0
    unchanged = 0

    for source, recipe in zip(source_recipes, recipes, strict=True):
        digest = content_hash(recipe)
        same = (await db.execute(select(StoreRecipeVersion).where(
            StoreRecipeVersion.company_id == company_id,
            StoreRecipeVersion.dish_uuid == recipe["dish_uuid"],
            StoreRecipeVersion.content_hash == digest,
        ).limit(1))).scalar_one_or_none()
        if same is not None:
            unchanged += 1
            continue
        latest = (await db.execute(select(StoreRecipeVersion).where(
            StoreRecipeVersion.company_id == company_id,
            StoreRecipeVersion.dish_uuid == recipe["dish_uuid"],
        ).order_by(StoreRecipeVersion.version.desc()))).scalars().first()
        try:
            station_version = max(1, int(source.get("version") or 1))
        except (TypeError, ValueError):
            station_version = 1
        version = max(station_version, (latest.version + 1 if latest else 1))
        row = StoreRecipeVersion(
            company_id=company_id, dish_uuid=recipe["dish_uuid"],
            dish_name=recipe["dish_name"], recipe_kind=recipe["recipe_kind"],
            version=version, status="active" if initial else "draft",
            output_qty=recipe["output_qty"], output_unit=recipe["output_unit"],
            lines=recipe["lines"], content_hash=digest,
            valid_from=now if initial else None, activated_at=now if initial else None,
            source="station", source_station_id=station_id,
            change_note=note, source_bundle_id=bundle_id,
        )
        db.add(row)
        created += 1
    await db.commit()
    return {"created": created, "unchanged": unchanged, "initial": initial,
            "bundle_id": bundle_id, "recipes": len(recipes)}


async def create_draft(db: AsyncSession, company_id: uuid.UUID,
                       user_id: uuid.UUID | None, data: dict) -> StoreRecipeVersion:
    dish_uuid = str(data.get("dish_uuid") or "").strip()
    if not dish_uuid:
        raise HTTPException(422, "Не указан UUID блюда")
    current_draft = (await db.execute(select(StoreRecipeVersion).where(
        StoreRecipeVersion.company_id == company_id,
        StoreRecipeVersion.dish_uuid == dish_uuid,
        StoreRecipeVersion.status == "draft",
    ).order_by(StoreRecipeVersion.version.desc()))).scalars().first()
    if current_draft:
        return current_draft

    latest = (await db.execute(select(StoreRecipeVersion).where(
        StoreRecipeVersion.company_id == company_id,
        StoreRecipeVersion.dish_uuid == dish_uuid,
    ).order_by(StoreRecipeVersion.version.desc()))).scalars().first()
    source = data if data.get("lines") else (row_dict(latest) if latest else data)
    source["dish_uuid"] = dish_uuid
    recipe = normalize_recipe(source)
    row = StoreRecipeVersion(
        company_id=company_id, dish_uuid=dish_uuid, dish_name=recipe["dish_name"],
        recipe_kind=recipe["recipe_kind"], version=(latest.version + 1 if latest else 1),
        status="draft", output_qty=recipe["output_qty"], lines=recipe["lines"],
        output_unit=recipe["output_unit"],
        content_hash=content_hash(recipe), created_by=user_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_draft(db: AsyncSession, company_id: uuid.UUID,
                       version_id: uuid.UUID, data: dict) -> StoreRecipeVersion:
    row = (await db.execute(select(StoreRecipeVersion).where(
        StoreRecipeVersion.id == version_id,
        StoreRecipeVersion.company_id == company_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Версия ТТК не найдена")
    if row.status != "draft":
        raise HTTPException(409, "Действующую ТТК менять нельзя — создайте новую версию")
    recipe = normalize_recipe({
        "dish_uuid": row.dish_uuid,
        "dish_name": data.get("dish_name", row.dish_name),
        "recipe_kind": data.get("recipe_kind", row.recipe_kind),
        "output_qty": data.get("output_qty", row.output_qty),
        "output_unit": data.get("output_unit", row.output_unit),
        "lines": data.get("lines", row.lines),
    })
    row.dish_name = recipe["dish_name"]
    row.recipe_kind = recipe["recipe_kind"]
    row.output_qty = recipe["output_qty"]
    row.output_unit = recipe["output_unit"]
    row.lines = recipe["lines"]
    row.content_hash = content_hash(recipe)
    await db.commit()
    await db.refresh(row)
    return row


async def activate(db: AsyncSession, company_id: uuid.UUID, version_id: uuid.UUID,
                   valid_from: datetime | None = None) -> StoreRecipeVersion:
    row = (await db.execute(select(StoreRecipeVersion).where(
        StoreRecipeVersion.id == version_id,
        StoreRecipeVersion.company_id == company_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Версия ТТК не найдена")
    if row.status != "draft":
        raise HTTPException(409, "Активировать можно только черновик")
    when = valid_from or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    active = await active_versions(db, company_id)
    candidate = []
    for current in active:
        if current.dish_uuid == row.dish_uuid:
            continue
        candidate.append({
            "dish_uuid": current.dish_uuid, "dish_name": current.dish_name,
            "recipe_kind": current.recipe_kind, "output_qty": float(current.output_qty),
            "output_unit": current.output_unit,
            "lines": current.lines or [],
        })
    candidate.append({
        "dish_uuid": row.dish_uuid, "dish_name": row.dish_name,
        "recipe_kind": row.recipe_kind, "output_qty": float(row.output_qty),
        "output_unit": row.output_unit,
        "lines": row.lines or [],
    })
    validate_recipe_set(candidate)

    previous = (await db.execute(select(StoreRecipeVersion).where(
        StoreRecipeVersion.company_id == company_id,
        StoreRecipeVersion.dish_uuid == row.dish_uuid,
        StoreRecipeVersion.status == "active",
        StoreRecipeVersion.valid_to.is_(None),
    ))).scalars().all()
    for old in previous:
        old.valid_to = when
        if when <= datetime.now(timezone.utc):
            old.status = "archived"
    row.status = "active"
    row.valid_from = when
    row.activated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row
