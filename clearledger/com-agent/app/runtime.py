"""
COM Runtime для 1C V83.COMConnector.

Запускается ВНУТРИ FastAPI процесса (не subprocess), потому что:
- На Windows Server 2022 + pywin32 306 V83.COMConnector работает напрямую в 64-bit Python
- Если потребуется 32-bit fallback — запускать сам uvicorn через py -3.13-32

Хранит одну глобальную сессию IB (инфобазы 1С). Многопользовательский режим не нужен —
один агент = одно подключение к одной БП. Если нужны разные базы — несколько агентов
на разных портах.

Источник логики: server/app/services/onec/com_worker.py — переиспользована построчно.
"""
from __future__ import annotations

import threading
import time
from typing import Any

try:
    import pythoncom  # type: ignore[import-not-found]
    import win32com.client  # type: ignore[import-not-found]
except ImportError as exc:
    raise RuntimeError("pywin32 not installed. pip install pywin32") from exc


# Глобальное состояние агента
_IB: Any = None
_IB_LOCK = threading.Lock()
_LAST_USED = 0.0
_CONN_STRING: str | None = None


ENTITY_TYPE_PREFIX = {
    "Catalog_": "Справочник",
    "Document_": "Документ",
    "InformationRegister_": "РегистрСведений",
    "AccumulationRegister_": "РегистрНакопления",
    "AccountingRegister_": "РегистрБухгалтерии",
    "Constant_": "Константа",
    "Enum_": "Перечисление",
}


def _val(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (int, float, str, bool)):
        return obj
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    try:
        guid_obj = obj.УникальныйИдентификатор()
        return str(_IB.String(guid_obj))  # type: ignore[union-attr]
    except Exception:
        pass
    if callable(obj):
        try:
            inner = obj()
            return _val(inner) if inner is not obj else str(obj)
        except Exception:
            return None
    return str(obj)


def _resolve_entity(odata_name: str) -> str:
    for prefix, qualifier in ENTITY_TYPE_PREFIX.items():
        if odata_name.startswith(prefix):
            return f"{qualifier}.{odata_name[len(prefix):]}"
    raise ValueError(f"Неизвестный префикс OData-сущности: {odata_name}")


def _require_ib() -> Any:
    if _IB is None:
        raise RuntimeError("Соединение не открыто — сначала /connect")
    return _IB


ODATA_TO_QUERY_FIELDS: dict[str, str] = {
    "Ref_Key":            "Т.Ссылка",
    "Period":             "Т.Период",
    "Recorder_Key":       "Т.Регистратор",
    "DeletionMark":       "Т.ПометкаУдаления",
    "Posted":             "Т.Проведен",
    "Description":        "Т.Наименование",
    "Code":               "Т.Код",
    "Date":               "Т.Дата",
    "Number":             "Т.Номер",
    "Контрагент_Key":     "Т.Контрагент",
    "Организация_Key":    "Т.Организация",
    "Склад_Key":          "Т.Склад",
    "Договор_Key":        "Т.ДоговорКонтрагента",
    "НомерВходящегоДокумента": "Т.НомерВходящегоДокумента",
    "ДатаВходящегоДокумента":  "Т.ДатаВходящегоДокумента",
    "ВидОперации":        "Т.ВидОперации",
    "СуммаНДС":           "Т.СуммаНДС",
    "СуммаНаличных":      "Т.СуммаНаличных",
    "СуммаВключаетНДС":   "Т.СуммаВключаетНДС",
}


def _resolve_field(field: str) -> str:
    if field in ODATA_TO_QUERY_FIELDS:
        return ODATA_TO_QUERY_FIELDS[field]
    if field.endswith("_Key"):
        return f"Т.{field[:-4]}"
    return f"Т.{field}"


def _build_query_text(
    qualified_entity: str,
    select: list[str] | None,
    filter_expr: str | None,
    orderby: str | None,
    top: int | None,
    skip: int | None,
) -> str:
    fields = select if select else ["Ref_Key"]
    alias_pairs = []
    for f in fields:
        if f.startswith("RAW:"):
            alias_pairs.append(f[4:])
        else:
            alias_pairs.append(f"{_resolve_field(f)} КАК {f}")
    select_clause = ", ".join(alias_pairs)
    top_clause = f"ПЕРВЫЕ {top}" if top else ""
    where_clause = ""
    if filter_expr:
        import re
        converted = filter_expr
        for src, dst in ((" eq ", " = "), (" ne ", " <> "), (" ge ", " >= "),
                         (" le ", " <= "), (" gt ", " > "), (" lt ", " < ")):
            converted = converted.replace(src, dst)
        converted = re.sub(
            r"datetime'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})'",
            r"ДАТАВРЕМЯ(\1,\2,\3,\4,\5,\6)",
            converted,
        )
        converted = converted.replace("'", '"')
        where_clause = "ГДЕ " + converted
    order_clause = f"УПОРЯДОЧИТЬ ПО {orderby}" if orderby else ""
    return (
        f"ВЫБРАТЬ {top_clause} {select_clause} "
        f"ИЗ {qualified_entity} КАК Т "
        f"{where_clause} {order_clause}".strip()
    )


# ─── Operations ──────────────────────────────────────────────────────


def op_connect(conn_string: str) -> dict[str, Any]:
    """Открыть COM-соединение к ИБ."""
    global _IB, _CONN_STRING, _LAST_USED
    pythoncom.CoInitialize()
    with _IB_LOCK:
        conn = win32com.client.Dispatch("V83.COMConnector")
        _IB = conn.Connect(conn_string)
        _CONN_STRING = conn_string
        _LAST_USED = time.time()
        md = _IB.Метаданные
        return {
            "config_name": _val(md.Имя),
            "config_synonym": _val(md.Синоним),
            "config_version": _val(md.Версия),
        }


def op_disconnect() -> dict[str, Any]:
    global _IB, _CONN_STRING
    with _IB_LOCK:
        _IB = None
        _CONN_STRING = None
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
        return {"status": "disconnected"}


def op_ping() -> dict[str, Any]:
    return {"connected": _IB is not None, "last_used": _LAST_USED}


def op_metadata_catalogs() -> list[str]:
    ib = _require_ib()
    out: list[str] = []
    coll = ib.Метаданные.Справочники
    for i in range(coll.Количество()):
        out.append(f"Catalog_{_val(coll.Получить(i).Имя)}")
    return out


def op_metadata_registers(name_substring: str = "") -> list[str]:
    ib = _require_ib()
    out: list[str] = []
    coll = ib.Метаданные.РегистрыСведений
    ns = name_substring.lower()
    for i in range(coll.Количество()):
        nm = _val(coll.Получить(i).Имя) or ""
        if not ns or ns in str(nm).lower():
            out.append(f"InformationRegister_{nm}")
    return out


def op_describe_entity(entity: str) -> dict[str, list[str]]:
    ib = _require_ib()
    qualified = _resolve_entity(entity)
    qualifier, _, name = qualified.partition(".")
    md = ib.Метаданные
    coll_map = {
        "Справочник": "Справочники",
        "Документ": "Документы",
        "РегистрСведений": "РегистрыСведений",
        "РегистрНакопления": "РегистрыНакопления",
        "РегистрБухгалтерии": "РегистрыБухгалтерии",
        "Перечисление": "Перечисления",
        "Константа": "Константы",
    }
    coll_name = coll_map.get(qualifier)
    if not coll_name:
        raise ValueError(f"Не поддерживаемый квалификатор: {qualifier}")
    obj = getattr(md, coll_name).Найти(name)
    if obj is None:
        raise ValueError(f"Объект метаданных не найден: {qualified}")

    def _names(collection: Any) -> list[str]:
        out: list[str] = []
        try:
            n = int(collection.Количество())
        except Exception:
            return out
        for i in range(n):
            try:
                out.append(str(collection.Получить(i).Имя))
            except Exception:
                continue
        return out

    result: dict[str, list[str]] = {"dimensions": [], "resources": [], "attributes": []}
    for attr_name, key in (("Измерения", "dimensions"), ("Ресурсы", "resources"), ("Реквизиты", "attributes")):
        try:
            result[key] = _names(getattr(obj, attr_name))
        except AttributeError:
            result[key] = []
    return result


def op_fetch_entity(
    entity: str,
    select: list[str] | None = None,
    filter: str | None = None,
    orderby: str | None = None,
    top: int | None = None,
    skip: int | None = None,
) -> list[dict[str, Any]]:
    ib = _require_ib()
    qualified = _resolve_entity(entity)
    effective_top = top
    if skip and top:
        effective_top = top + skip
    elif skip and not top:
        effective_top = None
    text = _build_query_text(qualified, select, filter, orderby, effective_top, skip)
    q = ib.NewObject("Запрос")
    q.Текст = text
    sel = q.Выполнить().Выбрать()
    if skip:
        for _ in range(skip):
            if not sel.Следующий():
                return []

    fields = select if select else ["Ref_Key"]
    import re
    field_to_attr: list[tuple[str, str]] = []
    for f in fields:
        if f.startswith("RAW:"):
            body = f[4:].strip()
            m = re.search(r"\s+КАК\s+([A-Za-zА-Яа-я_][A-Za-zА-Яа-я0-9_]*)\s*$", body, re.IGNORECASE)
            if m:
                alias = m.group(1)
                field_to_attr.append((alias, alias))
        else:
            field_to_attr.append((f, f))
    rows: list[dict[str, Any]] = []
    while sel.Следующий():
        row: dict[str, Any] = {}
        for out_key, attr in field_to_attr:
            row[out_key] = _val(getattr(sel, attr))
        rows.append(row)
    return rows


def op_count_entity(entity: str, filter: str | None = None) -> int:
    ib = _require_ib()
    qualified = _resolve_entity(entity)
    where = ""
    if filter:
        import re
        converted = filter
        for src, dst in ((" eq ", " = "), (" ne ", " <> "), (" ge ", " >= "),
                         (" le ", " <= "), (" gt ", " > "), (" lt ", " < ")):
            converted = converted.replace(src, dst)
        converted = re.sub(
            r"datetime'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})'",
            r"ДАТАВРЕМЯ(\1,\2,\3,\4,\5,\6)",
            converted,
        )
        converted = converted.replace("'", '"')
        where = "ГДЕ " + converted
    q = ib.NewObject("Запрос")
    q.Текст = f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК cnt ИЗ {qualified} КАК Т {where}"
    sel = q.Выполнить().Выбрать()
    sel.Следующий()
    return int(sel.cnt or 0)


def op_fetch_doc_lines(
    doc_type: str,
    doc_ref: str,
    tabular_name: str,
    select: list[str] | None = None,
) -> list[dict[str, Any]]:
    ib = _require_ib()
    doc_manager = getattr(ib.Documents, doc_type)
    uid_obj = ib.NewObject("УникальныйИдентификатор", doc_ref)
    doc_ref_obj = doc_manager.GetRef(uid_obj)
    if doc_ref_obj is None:
        return []
    doc_obj = doc_ref_obj.GetObject()
    if doc_obj is None:
        return []
    tab = getattr(doc_obj, tabular_name)
    fields = select or []
    rows: list[dict[str, Any]] = []
    for i in range(int(tab.Count())):
        row = tab.Get(i)
        out: dict[str, Any] = {"LineNumber": i + 1}
        for f in fields:
            try:
                out[f] = _val(getattr(row, f))
            except Exception:
                out[f] = None
        rows.append(out)
    return rows


def op_find_docs_by_nomenclature(nomenclature_ref: str, limit: int = 50) -> list[dict[str, Any]]:
    ib = _require_ib()
    q = ib.NewObject("Запрос")
    q.Текст = (
        f"ВЫБРАТЬ ПЕРВЫЕ {int(limit)} "
        "Т.Ссылка.Ссылка КАК Ссылка, Т.Ссылка.Номер КАК Номер, "
        "Т.Ссылка.Дата КАК Дата, Т.Ссылка.Контрагент.Наименование КАК КонтрагентИмя, "
        "Т.Ссылка.Контрагент.ИНН КАК ИНН, Т.Ссылка.Организация.Наименование КАК ОрганизацияИмя, "
        "Т.Ссылка.СуммаДокумента КАК СуммаДок, Т.Количество КАК Количество, "
        "Т.Цена КАК Цена, Т.Сумма КАК Сумма, \"ПТУ\" КАК ТипДок "
        "ИЗ Документ.ПоступлениеТоваровУслуг.Товары КАК Т "
        "ГДЕ Т.Номенклатура = &Ном УПОРЯДОЧИТЬ ПО Дата УБЫВ"
    )
    uid_obj = ib.NewObject("УникальныйИдентификатор", nomenclature_ref)
    nom_ref = ib.Catalogs.Номенклатура.GetRef(uid_obj)
    q.УстановитьПараметр("Ном", nom_ref)
    sel = q.Выполнить().Выбрать()
    rows: list[dict[str, Any]] = []
    while sel.Следующий():
        rows.append({
            "external_id": _val(sel.Ссылка),
            "number": _val(sel.Номер),
            "date": _val(sel.Дата),
            "counterparty_name": _val(sel.КонтрагентИмя) or "",
            "counterparty_inn": _val(sel.ИНН),
            "organization_name": _val(sel.ОрганизацияИмя),
            "amount": float(_val(sel.СуммаДок) or 0),
            "line_quantity": float(_val(sel.Количество) or 0),
            "line_price": float(_val(sel.Цена) or 0),
            "line_sum": float(_val(sel.Сумма) or 0),
            "doc_type": _val(sel.ТипДок),
        })
    return rows


def op_fetch_postings(doc_type: str, doc_ref: str) -> list[dict[str, Any]]:
    """Проводки документа из РегистрБухгалтерии.Хозрасчетный по регистратору."""
    ib = _require_ib()
    doc_manager = getattr(ib.Documents, doc_type)
    uid_obj = ib.NewObject("УникальныйИдентификатор", doc_ref)
    doc_ref_obj = doc_manager.GetRef(uid_obj)
    if doc_ref_obj is None:
        return []
    q = ib.NewObject("Запрос")
    q.Текст = (
        "ВЫБРАТЬ Т.СчетДт КАК AccountDt, Т.СчетКт КАК AccountCt, Т.Сумма КАК Amount "
        "ИЗ РегистрБухгалтерии.Хозрасчетный КАК Т "
        "ГДЕ Т.Регистратор = &Рег УПОРЯДОЧИТЬ ПО Т.НомерСтроки"
    )
    q.УстановитьПараметр("Рег", doc_ref_obj)
    sel = q.Выполнить().Выбрать()
    out: list[dict[str, Any]] = []
    while sel.Следующий():
        out.append({
            "AccountDt": _val(sel.AccountDt),
            "AccountCt": _val(sel.AccountCt),
            "Amount": float(_val(sel.Amount) or 0),
        })
    return out


def op_enrich_nomenclature(refs: list[str]) -> dict[str, dict[str, Any]]:
    ib = _require_ib()
    if not refs:
        return {}
    arr = ib.NewObject("Array")
    cat_mgr = ib.Catalogs.Номенклатура
    for guid_str in refs:
        try:
            uid = ib.NewObject("УникальныйИдентификатор", guid_str)
            arr.Add(cat_mgr.GetRef(uid))
        except Exception:
            continue
    q = ib.NewObject("Запрос")
    q.Текст = (
        "ВЫБРАТЬ Т.Ссылка КАК Ref, Т.Наименование КАК Name, "
        "ПРЕДСТАВЛЕНИЕ(Т.ЕдиницаИзмерения) КАК Unit, Т.Артикул КАК Article "
        "ИЗ Справочник.Номенклатура КАК Т ГДЕ Т.Ссылка В (&Список)"
    )
    q.УстановитьПараметр("Список", arr)
    sel = q.Выполнить().Выбрать()
    out: dict[str, dict[str, Any]] = {}
    while sel.Следующий():
        ref = _val(sel.Ref)
        out[str(ref)] = {
            "name": _val(sel.Name),
            "unit": _val(sel.Unit),
            "article": _val(sel.Article),
        }
    return out
