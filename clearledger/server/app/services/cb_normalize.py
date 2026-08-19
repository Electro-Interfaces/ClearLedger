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
  doc_type_id=kind, source=канал источника, source_id=натуральный ключ,
  meta=структура смены+документа. recipe сохраняется отдельным DataEntry в
  контексте смены и разворачивает блюда retail в ингредиенты.

Чистый Python (без БД): персистенцию делает оркестратор канала. Read-only.
"""
from __future__ import annotations

import hashlib
from typing import Any

# kind → (category_id для DataEntry)
_CATEGORY = {
    "retail_sale_sidegoods": "retail",
    "purchase": "purchase",
    "production_release": "food",
    "return_purchase": "purchase",
    "return_sale": "retail",
    "inventory": "inventory",
    "gain": "inventory",
    "writeoff": "inventory",
    "transfer": "inventory",
    "ingredients_writeoff": "food",
}


# Документы, которые ЕСТЬ сама смена: их ключ обязан её включать. Выпуск блюд
# сюда не входит — он оформляется по факту готовки и так же попадает в пакет
# соседней смены (у 39 задвоенных выпусков ИсточникUUID один, а смены две).
_SHIFT_BOUND = {"retail_sale_sidegoods", "return_sale"}


def _shift_key(shift: dict) -> str:
    """Натуральный ключ смены: ОСЭ_Номер или НомерСмены (идемпотентность .epf)."""
    return str(shift.get("ОСЭНомер") or shift.get("НомерСмены") or "").strip()


def _shift_scope(shift: dict) -> str:
    """Ключ смены для записей, живущих В КОНТЕКСТЕ смены (ТТК).

    `НомерСмены` и `ОСЭНомер` кодируют дату, а не последовательность смен: у обеих
    смен одного дня они совпадают (18.08.2026 — `2082081808202601` и у 7080, и у
    7081). Для ТТК одного `_shift_key` мало — вторая смена дня перезаписывала
    рецептуры первой, и первая падала fail-closed «нет точной ТТК этой смены»,
    хотя блюда продавались и выпуск был. Документы смены это не задевало: у них в
    ключе есть собственный `ИсточникUUID`, а у ТТК он один на (блюдо, версия).

    Кассовый номер смены различает смены внутри дня — тот же различитель, что
    использует `_shift_identity` при поиске ТТК смены.
    """
    key = _shift_key(shift)
    internal = str(shift.get("НомерСменыВнутр") or "").strip()
    return f"{key}:{internal}" if internal else key


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


# Общепит ГИГ продаётся как сопутка: блюдо собирается из ингредиентов в момент
# продажи, счёт у товара и у сырья один (41.02). Поэтому контур — не счёт и не
# склад, а МЕТКА СТРОКИ: одна и та же карточка (бекон, молоко, стакан) бывает и
# товаром на полке, и сырьём кухни. Различает её накладная, а не справочник.
_ОБЩЕПИТ, _СОПУТКА = "Общепит", "Сопутка"
_МЕСТО_КАФЕ = {"cafe", "кафе", "общепит", "кухня"}

# kind → контур, известный без разбора строк
_KIND_CONTOUR = {"production_release": _ОБЩЕПИТ, "ingredients_writeoff": _ОБЩЕПИТ}


def _mark_contour(rows: list[dict], header: dict, ingredients: set[str],
                  forced: str = "") -> None:
    """Проставить строкам КлассSKU — тем же словарём, что у продаж.

    Приоритет: явное МестоОприходования (человек на станции знает, куда приехал
    товар) → позиция входит в чью-то ТТК → сопутка.
    """
    место_док = str(header.get("МестоОприходования") or "").strip().lower()
    for row in rows:
        if str(row.get("КлассSKU") or "").strip():
            continue                      # уже размечено источником — не спорим
        место = str(row.get("МестоОприходования") or "").strip().lower() or место_док
        if forced:
            row["КлассSKU"] = forced
        elif место:
            row["КлассSKU"] = _ОБЩЕПИТ if место in _МЕСТО_КАФЕ else _СОПУТКА
        else:
            row["КлассSKU"] = (_ОБЩЕПИТ if str(row.get("Номенклатура") or "") in ingredients
                               else _СОПУТКА)


def _sum(rows: list[dict], field: str = "Сумма") -> float:
    return round(sum(float(r.get(field, 0) or 0) for r in rows), 2)


def _build_sections(doc: dict, recipes: dict[str, list[dict]]) -> tuple[dict, bool]:
    """Разбить ОРП на ТИПИЗИРОВАННЫЕ секции (разное действие у каждой).

    Возврат: ({секция: {действие, строки, сумма,…}}, содержит_блюда).
    """
    soputka: list[dict] = []
    obshepit: list[dict] = []
    has_dish = False

    for ln in doc.get("Товары", []) or []:
        is_dish = bool(ln.get("ЭтоБлюдо")) or str(ln.get("КлассSKU", "")).strip() == "Общепит"
        if is_dish:
            has_dish = True
            ln = dict(ln)
            # ГИГ учитывает общепит по модели «выпуск по ТТК → продажа как
            # сопутствующего товара». Льготный входной НДС ингредиента не
            # переносится на готовое блюдо: его продажа всегда по 22%.
            ln["СтавкаНДС"] = "НДС22"
            ln["СуммаНДС"] = round(float(ln.get("Сумма") or 0) * 22 / 122, 2)
            ing = _expand_dish(ln, recipes)
            if ing:
                ln["Ингредиенты"] = ing
            obshepit.append(ln)
        else:
            soputka.append(ln)

    vozvraty = list(doc.get("ВозвращенныеТовары", []) or [])
    oplaty = list(doc.get("Оплаты", []) or [])

    sections: dict[str, Any] = {}
    if soputka:
        sections["продажа_сопутка"] = {
            "действие": "розн_продажа_товара",  # Кт 90.01.1 / Дт 90.02.1 Кт 41.02 (товар)
            "строки": soputka, "сумма": _sum(soputka), "сумма_ндс": _sum(soputka, "СуммаНДС"),
        }
    if obshepit:
        sections["продажа_общепит"] = {
            "действие": "розн_продажа_готового_блюда_НДС22",
            "строки": obshepit, "сумма": _sum(obshepit), "сумма_ндс": _sum(obshepit, "СуммаНДС"),
        }
    if vozvraty:
        sections["возвраты"] = {"действие": "сторно_продажи", "строки": vozvraty, "сумма": _sum(vozvraty)}
    if oplaty:
        sections["оплаты"] = {"действие": "разнесение_оплат", "строки": oplaty}
    return sections, has_dish


def normalize_shift_package(
    package: dict,
    source: str = "oneC",
    source_label: str = "ЦБ ЭЛСИ.АЗК",
    ingredients: set[str] | None = None,
) -> dict:
    """Пакет смены ЦБ → черновики DataEntry (L2 CLEAN).

    ingredients — UUID позиций, входящих в ТТК сети (из мастера). Нужны, чтобы
    разметить контур в приходах и списаниях: ТТК смены знают только те блюда,
    что продавались, а сырьё приезжает и в смены без общепита.

    Возврат: {shift_key, station, entries:[DataEntry-draft], skipped:[...]}.
    """
    shift = package.get("Смена", {}) or {}
    docs = package.get("Документы", []) or []
    skey = _shift_key(shift)
    station = str(shift.get("КодАЗС", "")).strip()
    recipes = _recipe_index(docs)
    сырьё = set(ingredients or ())
    for состав in recipes.values():
        сырьё |= {str(i.get("НоменклатураUUID") or i.get("Номенклатура") or "")
                  for i in состав}

    retail_uuid = next((str(d.get("ИсточникUUID")) for d in docs
                        if (d.get("Тип") or d.get("kind")) == "retail_sale_sidegoods"
                        and d.get("ИсточникUUID")), "")
    shift_meta = {
        # П1-фикс: переносим GUID смены (ОРП Ссылка) из пакета — уникальный ключ смены.
        "Смена": shift.get("Смена") or retail_uuid or package.get("ИдентификаторПакета"),
        "КодАЗС": station,
        "НомерСмены": shift.get("НомерСмены"),
        "НомерСменыВнутр": shift.get("НомерСменыВнутр"),
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
            # ТТК сохраняется в контексте конкретной смены. Одна глобальная
            # запись на блюдо уничтожала историю: повторный экспорт старой
            # смены мог получить уже новый состав.
            blyudo = str(d.get("БлюдоUUID") or d.get("Блюдо") or "").strip()
            if not blyudo:
                continue
            rec_doc = dict(d)
            rec_doc.setdefault("БлюдоUUID", blyudo)
            version_identity = "|".join((
                str(d.get("ВерсияНабораТТК") or ""),
                str(d.get("ВерсияТТК") or ""),
                str(d.get("ИсточникUUID") or ""),
            ))
            version_token = hashlib.sha256(version_identity.encode("utf-8")).hexdigest()[:16]
            entries.append({
                "title": f"ТТК блюда · {blyudo[:8]}",
                # category_id='retail' — как pull_cb_recipes_dev.py (30 существующих
                # recipe в БД), чтобы канальные и скриптовые ТТК были неотличимы.
                "category_id": "retail",
                "subcategory_id": "recipe",
                "doc_type_id": "recipe",
                "source": source,
                "source_label": source_label,
                "source_id": f"{_shift_scope(shift)}:recipe:{blyudo}:{version_token}",
                "layer": "clean",
                "status": "verified",
                "meta": {"Смена": shift_meta, "kind": "recipe", "Документ": rec_doc},
            })
            continue
        category = _CATEGORY.get(kind)
        if category is None:
            skipped.append(str(kind))
            continue

        doc_meta: dict[str, Any] = dict(d)
        src_uuid = str(d.get("ИсточникUUID", ""))
        title = f"{kind} · АЗС {station} · смена {shift.get('НомерСмены', '')}"
        meta: dict[str, Any] = {"Смена": shift_meta, "kind": kind}

        if kind == "retail_sale_sidegoods":
            # ОРП → типизированные СЕКЦИИ (разное действие у каждой)
            sections, has_dish = _build_sections(doc_meta, recipes)
            # шапка документа без построчных ТЧ (строки — в секциях)
            header = {k: v for k, v in doc_meta.items()
                      if k not in ("Товары", "ВозвращенныеТовары", "Оплаты")}
            meta["Документ"] = header
            meta["Секции"] = sections
            meta["СодержитБлюда"] = has_dish
        else:
            # одно-действийные документы (purchase/production_release/…) — без секций,
            # но с разметкой контура: приход сырья кухни и приход товара на полку
            # идут одной накладной и различимы только меткой строки.
            for тч in ("Товары", "ВыпускБлюд", "ВозвращенныеТовары"):
                if isinstance(doc_meta.get(тч), list):
                    _mark_contour(doc_meta[тч], doc_meta, сырьё,
                                  forced=_KIND_CONTOUR.get(kind, ""))
            meta["Документ"] = doc_meta

        entries.append({
            "title": title,
            "category_id": category,
            "subcategory_id": kind,
            "doc_type_id": kind,
            "source": source,
            "source_label": source_label,
            # натуральный ключ для идемпотентности (смена + kind + источник)
            # Ключ сменных документов включает смену, остальных — нет. Приёмка,
            # инвентаризация и списание живут сами по себе: агент кладёт их в
            # пакет той смены, что открыта в момент выгрузки, и один документ
            # 11.06 попал в обе смены дня — 161 задвоенный документ за период.
            "source_id": (f"{skey}:{kind}:{src_uuid}"
                          if kind in _SHIFT_BOUND or not src_uuid
                          else f"{kind}:{src_uuid}"),
            "layer": "clean",
            "status": "verified",
            "meta": meta,
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
    _selftest_contour()
    _selftest_keys()
    print(json.dumps(_selftest(), ensure_ascii=False, indent=2))


def _selftest_contour() -> None:
    """Контур строки: явное место → ТТК → сопутка. Одна карточка бывает и тем, и другим."""
    сырьё = {"uuid-milk"}
    строки = [
        {"Номенклатура": "uuid-milk"},                                  # ингредиент → кухня
        {"Номенклатура": "uuid-chips"},                                 # обычный товар
        {"Номенклатура": "uuid-milk", "МестоОприходования": "Магазин"},  # молоко на полку
        {"Номенклатура": "uuid-bacon", "МестоОприходования": "cafe"},    # бекон на кухню
        {"Номенклатура": "uuid-chips", "КлассSKU": "Общепит"},           # разметка источника
    ]
    _mark_contour(строки, {}, сырьё)
    assert [s["КлассSKU"] for s in строки] == [
        _ОБЩЕПИТ, _СОПУТКА, _СОПУТКА, _ОБЩЕПИТ, _ОБЩЕПИТ], строки

    # МестоОприходования из шапки накрывает все строки без своего
    шапка = [{"Номенклатура": "uuid-chips"}, {"Номенклатура": "uuid-x", "МестоОприходования": "Магазин"}]
    _mark_contour(шапка, {"МестоОприходования": "Кафе"}, set())
    assert [s["КлассSKU"] for s in шапка] == [_ОБЩЕПИТ, _СОПУТКА], шапка

    # выпуск блюд — общепит всегда, независимо от состава
    выпуск = [{"Номенклатура": "uuid-chips"}]
    _mark_contour(выпуск, {}, set(), forced=_KIND_CONTOUR["production_release"])
    assert выпуск[0]["КлассSKU"] == _ОБЩЕПИТ

    # приход в пакете размечается сквозь normalize_shift_package
    pkg = {"Смена": {"КодАЗС": "208", "НомерСмены": "1"}, "Документы": [
        {"Тип": "purchase", "ИсточникUUID": "u1", "Товары": [
            {"Номенклатура": "uuid-milk", "Количество": 1},
            {"Номенклатура": "uuid-chips", "Количество": 2}]}]}
    строки = normalize_shift_package(pkg, ingredients={"uuid-milk"})["entries"][0]["meta"]["Документ"]["Товары"]
    assert [s["КлассSKU"] for s in строки] == [_ОБЩЕПИТ, _СОПУТКА], строки


def _selftest_keys() -> None:
    """Ключ документа: смену включают только сменные, остальные — нет."""
    def ключи(смена: str) -> dict:
        pkg = {"Смена": {"КодАЗС": "208", "ОСЭНомер": смена}, "Документы": [
            {"Тип": "retail_sale_sidegoods", "ИсточникUUID": "orp-1", "Товары": []},
            {"Тип": "purchase", "ИсточникUUID": "ptu-1", "Товары": []},
            {"Тип": "production_release", "ИсточникUUID": "vyp-1", "ВыпускБлюд": []},
        ]}
        return {e["doc_type_id"]: e["source_id"]
                for e in normalize_shift_package(pkg)["entries"]}

    a, b = ключи("2082081106202601"), ключи("2082081106202602")
    # приёмка и выпуск блюд попадают в пакет той смены, что открыта в момент
    # выгрузки: один документ в двух сменах обязан дать ОДНУ запись
    assert a["purchase"] == b["purchase"], (a, b)
    assert a["production_release"] == b["production_release"], (a, b)
    # ОРП принадлежит смене — разные смены, разные документы
    assert a["retail_sale_sidegoods"] != b["retail_sale_sidegoods"], (a, b)
