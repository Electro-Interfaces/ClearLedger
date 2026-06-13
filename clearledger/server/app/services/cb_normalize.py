"""
Нормализация пакета смены ЦБ ЭЛСИ.АЗК (сопутка + общепит) → записи L2 (DataEntry).

Вход — пакет «одна смена одной АЗС» (контракт .epf TL_ЭкспортБП v2):
  {ВерсияФормата, Смена{КодАЗС,НомерСмены,ОСЭНомер,Открытие,Закрытие,Склад,
   Организация,Касса,Оператор}, Документы[], НСИ[]}
  Документы[] по kind: retail_sale_sidegoods | purchase | production_release |
  recipe | return_purchase. Строка retail: {Номенклатура,Количество,Цена,
  Сумма(с НДС),СтавкаНДС,СуммаНДС,КлассSKU(Сопутка/Общепит),ЭтоБлюдо}.

Выход — список черновиков DataEntry (документная грана L2, решение 13.06):
  layer='clean', status='verified', category_id ∈ {retail|purchase|food},
  doc_type_id=kind, source='oneC', source_id=натуральный ключ (идемпотентность),
  meta=структура смены+документа. recipe — НЕ свой DataEntry: разворачивает
  блюда retail в ингредиенты (модель B, §project_obshepit_model).

Чистый Python (без БД): персистенцию делает оркестратор канала. Read-only.
"""
from __future__ import annotations

from typing import Any

# kind → (category_id для DataEntry)
_CATEGORY = {
    "retail_sale_sidegoods": "retail",
    "purchase": "purchase",
    "production_release": "food",
    "return_purchase": "purchase",
}


def _shift_key(shift: dict) -> str:
    """Натуральный ключ смены: ОСЭ_Номер или НомерСмены (идемпотентность .epf)."""
    return str(shift.get("ОСЭНомер") or shift.get("НомерСмены") or "").strip()


def _recipe_index(docs: list[dict]) -> dict[str, list[dict]]:
    """{БлюдоUUID: [{НоменклатураUUID, Количество=Брутто}]} из kind=recipe."""
    idx: dict[str, list[dict]] = {}
    for d in docs:
        if d.get("Тип") == "recipe" or d.get("kind") == "recipe":
            blyudo = d.get("БлюдоUUID") or d.get("Блюдо")
            if blyudo:
                idx[str(blyudo)] = d.get("Ингредиенты", []) or []
    return idx


def _expand_dish(line: dict, recipes: dict[str, list[dict]]) -> list[dict]:
    """Развернуть блюдо в ингредиенты: брутто-на-порцию × количество порций."""
    blyudo = str(line.get("Номенклатура", ""))
    qty = float(line.get("Количество", 0) or 0)
    out = []
    for ing in recipes.get(blyudo, []):
        brutto = float(ing.get("Количество", 0) or 0)
        out.append({
            "Номенклатура": ing.get("НоменклатураUUID") or ing.get("Номенклатура"),
            "Количество": round(brutto * qty, 6),
            "ИзБлюда": blyudo,
        })
    return out


def normalize_shift_package(package: dict) -> dict:
    """Пакет смены ЦБ → черновики DataEntry (L2 CLEAN).

    Возврат: {shift_key, station, entries:[DataEntry-draft], skipped:[...]}.
    """
    shift = package.get("Смена", {}) or {}
    docs = package.get("Документы", []) or []
    skey = _shift_key(shift)
    station = str(shift.get("КодАЗС", "")).strip()
    recipes = _recipe_index(docs)

    shift_meta = {
        "КодАЗС": station,
        "НомерСмены": shift.get("НомерСмены"),
        "ОСЭНомер": shift.get("ОСЭНомер"),
        "Открытие": shift.get("Открытие"),
        "Закрытие": shift.get("Закрытие"),
        "Склад": shift.get("Склад") or shift.get("СкладUUID"),
        "Организация": shift.get("Организация") or shift.get("ОрганизацияUUID"),
        "Касса": shift.get("Касса"),
        "Оператор": shift.get("Оператор"),
    }

    entries: list[dict] = []
    skipped: list[str] = []

    for d in docs:
        kind = d.get("Тип") or d.get("kind")
        if kind == "recipe":
            continue  # справочный поток: используется для разворота блюд
        category = _CATEGORY.get(kind)
        if category is None:
            skipped.append(str(kind))
            continue

        doc_meta: dict[str, Any] = dict(d)

        # Разворот блюд для розничной продажи (модель B)
        has_dish = False
        if kind == "retail_sale_sidegoods":
            for ln in doc_meta.get("Товары", []) or []:
                if ln.get("ЭтоБлюдо") or str(ln.get("КлассSKU", "")).strip() == "Общепит":
                    has_dish = True
                    ing = _expand_dish(ln, recipes)
                    if ing:
                        ln["Ингредиенты"] = ing

        src_uuid = str(d.get("ИсточникUUID", ""))
        title = f"{kind} · АЗС {station} · смена {shift.get('НомерСмены', '')}"

        entries.append({
            "title": title,
            "category_id": category,
            "subcategory_id": kind,
            "doc_type_id": kind,
            "source": "oneC",
            "source_label": "ЦБ ЭЛСИ.АЗК",
            # натуральный ключ для идемпотентности (смена + kind + источник)
            "source_id": f"{skey}:{kind}:{src_uuid}",
            "layer": "clean",
            "status": "verified",
            "meta": {
                "Смена": shift_meta,
                "kind": kind,
                "СодержитБлюда": has_dish,
                "Документ": doc_meta,
            },
        })

    return {"shift_key": skey, "station": station, "entries": entries, "skipped": skipped}


# ---------------------------------------------------------------------------
# Само-тест на синтетическом пакете (форма контракта .epf v2)
# ---------------------------------------------------------------------------
def _selftest() -> dict:
    pkg = {
        "ВерсияФормата": "2",
        "Смена": {"КодАЗС": "208", "НомерСмены": "7009", "ОСЭНомер": "208…01",
                  "Открытие": "2026-06-01T08:00:00+03:00", "Закрытие": "2026-06-01T20:00:00+03:00",
                  "Склад": "uuid-sklad", "Организация": "uuid-gig", "Касса": "АЗС №208"},
        "Документы": [
            {"Тип": "recipe", "БлюдоUUID": "uuid-cappuccino",
             "Ингредиенты": [{"НоменклатураUUID": "uuid-milk", "Количество": 0.15},
                              {"НоменклатураUUID": "uuid-coffee", "Количество": 0.011}]},
            {"Тип": "retail_sale_sidegoods", "ИсточникUUID": "uuid-orp", "Номер": "208…01",
             "СуммаДокумента": 1200.0,
             "Товары": [
                 {"Номенклатура": "uuid-chips", "Количество": 3, "Сумма": 300.0, "КлассSKU": "Сопутка", "ЭтоБлюдо": False},
                 {"Номенклатура": "uuid-cappuccino", "Количество": 5, "Сумма": 900.0, "КлассSKU": "Общепит", "ЭтоБлюдо": True},
             ]},
            {"Тип": "purchase", "ИсточникУUID": "uuid-ptu", "ИсточникUUID": "uuid-ptu"},
        ],
    }
    return normalize_shift_package(pkg)


if __name__ == "__main__":
    import json
    print(json.dumps(_selftest(), ensure_ascii=False, indent=2))
