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

import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import pythoncom  # type: ignore[import-not-found]
    import win32com.client  # type: ignore[import-not-found]
except ImportError as exc:
    raise RuntimeError("pywin32 not installed. pip install pywin32") from exc


# Стенные часы 1С — московские; метку зоны от pywin32 игнорируем (см. _val).
_MSK = timezone(timedelta(hours=3))

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


_RU_DT = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})(?:[ T](\d{2}):(\d{2}):(\d{2}))?$")


def _iso_if_ru_date(s: str) -> str:
    """«28.07.2026 23:43:53» → «2026-07-28T23:43:53+03:00».

    На машине агента COM отдаёт дату не объектом, а строкой в русском формате — ветка
    isoformat её не ловит, и в пакет уезжало «28.07.2026». Прежние выгрузки (Windows-
    subprocess на другой сборке pywin32) давали ISO, поэтому смены нового формата
    выпадали из всех периодов: экраны показывали ноль при загруженных данных.
    Строки, не похожие на дату (синонимы перечислений), возвращаются как есть.
    """
    m = _RU_DT.match(s.strip())
    if not m:
        return s
    d, mo, y, hh, mi, ss = m.groups()
    if hh is None:
        return f"{y}-{mo}-{d}"
    return datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss), tzinfo=_MSK).isoformat()


def _val(obj: Any) -> Any:
    """COM Variant getter — поле может быть скаляром, COM-ссылкой 1С или COM-датой."""
    if obj is None:
        return None
    # (см. _iso_if_ru_date ниже по файлу — нормализация «28.07.2026 23:43:53» → ISO)
    # Скаляры — сразу.
    if isinstance(obj, (int, float, str, bool)):
        return obj
    # Дата 1С (COM Time) → ISO-строка с ВЕРНОЙ зоной (см. _MSK выше): стенные часы
    # 1С — московские, метку UTC от pywin32 игнорируем и ставим +03:00.
    if hasattr(obj, "isoformat"):
        try:
            if hasattr(obj, "hour"):   # дата-время
                return datetime(obj.year, obj.month, obj.day,
                                obj.hour, obj.minute, obj.second,
                                tzinfo=_MSK).isoformat()
            return obj.isoformat()     # чистая дата — зона не нужна
        except Exception:
            pass
    # Ссылка 1С (CDispatch) — извлекаем GUID через ib.String(УникальныйИдентификатор()).
    # ib.String — английский алиас глобальной функции Строка() платформы,
    # доступен из V83.COMConnector. Метод УникальныйИдентификатор() даёт
    # CDispatch-объект УникальныйИдентификатор, который сам не имеет
    # default property — но String() умеет конвертировать его в GUID-строку.
    try:
        guid_obj = obj.УникальныйИдентификатор()
        return str(_IB.String(guid_obj))  # type: ignore[union-attr]
    except Exception:
        pass
    # Значение перечисления (ВидДоговора, ЮридическоеФизическоеЛицо и пр.) — нет
    # УникальныйИдентификатор. Берём синоним через Строка(). Строго ПОСЛЕ ветки
    # ссылок, поэтому GUID-конвертация ссылок не затрагивается.
    try:
        s = str(_IB.String(obj))  # type: ignore[union-attr]
        if s and not s.startswith("<"):
            return _iso_if_ru_date(s)
    except Exception:
        pass
    # bound-method (выборка некоторых Variant-полей).
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


# ─────────────────────────────────────────────────────────────────────────
# Операции канала ЦБ ЭЛСИ.АЗК (сопутка/общепит). Перенесены построчно из
# server/app/services/onec/com_worker.py — там они отлажены на боевой базе.
# Правишь там — переноси сюда, иначе Linux-контейнер и Windows-subprocess
# начнут собирать РАЗНЫЕ пакеты смен.
# ─────────────────────────────────────────────────────────────────────────

def _dt_lit(s: str, end: bool = False) -> str:
    """'2026-06-01' → литерал ДАТАВРЕМЯ(2026,6,1,0,0,0) / (…,23,59,59) для end."""
    d = (s or "").strip()[:10].split("-")
    if len(d) != 3:
        return "2020,1,1,0,0,0"
    tail = "23,59,59" if end else "0,0,0"
    return f"{int(d[0])},{int(d[1])},{int(d[2])},{tail}"


def _xs(ib: Any, ref: Any) -> str:
    """GUID-строка из ссылки (через XMLСтрока — str() COM-UUID не сериализует)."""
    try:
        return str(ib.XMLСтрока(ref.УникальныйИдентификатор()))
    except Exception:
        return ""


def _recipe_for_dish(ib: Any, nom_ref: Any) -> list[dict[str, Any]]:
    """Актуальная ТТК блюда → ингредиенты [{НоменклатураUUID, Количество=Брутто}]."""
    try:
        q = ib.NewObject("Запрос")
        q.Текст = ("ВЫБРАТЬ ПЕРВЫЕ 1 Документ КАК Док ИЗ "
                   "РегистрСведений.ЗначенияТТКНоменклатуры.СрезПоследних ГДЕ Номенклатура = &Ном")
        q.УстановитьПараметр("Ном", nom_ref)
        s = q.Выполнить().Выбрать()
        if not s.Следующий():
            return []
        ttk = s.Док.ПолучитьОбъект()
        out = []
        for j in range(ttk.Товары.Количество()):
            rr = ttk.Товары.Получить(j)
            # OB-2: фильтры эталона (bsl:2060-2070, op_fetch_recipes:1125-1138) —
            # пропускаем строки Учитывать=Ложь, без номенклатуры и Брутто=0,
            # иначе фантомные ингредиенты завышают food-cost во всех витринах.
            try:
                уч = _val(rr.Учитывать)
            except Exception:
                уч = True
            if уч is False:
                continue
            if not _val(rr.Номенклатура):
                continue
            брутто = float(_val(rr.Брутто) or 0)
            if брутто == 0:
                continue
            out.append({"НоменклатураUUID": _xs(ib, rr.Номенклатура),
                        "Количество": брутто})
        return out
    except Exception:
        return []


def _is_cashless(форма: str) -> bool:
    """Безналичная ли форма оплаты (по ФормаОплаты ОРП). Реквизит-перечисление
    «БезналичнаяОплата» в ЭЛСИ.АЗК пуст, поэтому признак выводим из формы."""
    f = (форма or "").strip().lower()
    if not f:
        return False
    return not any(k in f for k in ("наличн", "нал."))


def _attach_purchases(ib: Any, orp: Any) -> list[dict[str, Any]]:
    """ПТУ (приходы) по Склад=ОРП.Склад + Дата ∈ [Открытие..Закрытие] (как .epf).

    ВидОперации=ОтПоставщика; документы с услугами/тарой пропускаются. → kind=purchase.
    """
    out: list[dict[str, Any]] = []
    try:
        otkr = getattr(orp, "ДатаВремяОткрытия", None)
        zakr = getattr(orp, "ДатаВремяЗакрытия", None)
        if not (otkr and zakr):
            return out
        q = ib.NewObject("Запрос")
        q.Текст = (
            "ВЫБРАТЬ Док.Ссылка КАК Ссылка, Док.Номер КАК Ном, Док.Дата КАК Дата, "
            "Док.Контрагент КАК Контр, Док.Организация КАК Орг, Док.Проведен КАК Пров, "
            "Док.ПометкаУдаления КАК Пом, Док.СуммаДокумента КАК СумДок, "
            "Док.СуммаВключаетНДС КАК СумВклНДС "
            "ИЗ Документ.ПоступлениеТоваровУслугНаАЗК КАК Док "
            # П2-фикс: интервал по ДНЮ как эталон — приходы в зазорах между сменами
            # больше не теряются. НАЧАЛОПЕРИОДА/КОНЕЦПЕРИОДА — функции ЯЗЫКА ЗАПРОСОВ
            # (НачалоДня/КонецДня — только в коде 1С, в запросе синтакс-ошибка).
            "ГДЕ Док.Склад = &Склад И Док.Дата МЕЖДУ НАЧАЛОПЕРИОДА(&От, ДЕНЬ) И КОНЕЦПЕРИОДА(&До, ДЕНЬ) "
            "И Док.ВидОперации = ЗНАЧЕНИЕ(Перечисление.ВидыОперацийПоступлениеТоваровУслугНаАЗК.ОтПоставщика) "
            "УПОРЯДОЧИТЬ ПО Док.Дата"
        )
        q.УстановитьПараметр("Склад", orp.Склад)
        q.УстановитьПараметр("От", otkr)
        q.УстановитьПараметр("До", zakr)
        s = q.Выполнить().Выбрать()
        while s.Следующий():
            obj = s.Ссылка.ПолучитьОбъект()
            if obj.Услуги.Количество() > 0 or obj.ВозвратнаяТара.Количество() > 0:
                continue
            ql = ib.NewObject("Запрос")
            ql.Текст = (
                "ВЫБРАТЬ Т.НомерСтроки КАК НС, Т.Номенклатура КАК Ном, Т.Количество КАК Кол, "
                "Т.Цена КАК Цена, Т.Сумма КАК Сум, Т.СуммаНДС КАК СНДС, "
                "ПРЕДСТАВЛЕНИЕ(Т.СтавкаНДС) КАК Ставка ИЗ "
                "Документ.ПоступлениеТоваровУслугНаАЗК.Товары КАК Т ГДЕ Т.Ссылка = &Д "
                "УПОРЯДОЧИТЬ ПО Т.НомерСтроки"
            )
            ql.УстановитьПараметр("Д", s.Ссылка)
            sl = ql.Выполнить().Выбрать()
            tovary = []
            while sl.Следующий():
                tovary.append({
                    "НомерСтроки": int(_val(sl.НС) or 0), "Номенклатура": _xs(ib, sl.Ном),
                    "Количество": float(_val(sl.Кол) or 0), "Цена": float(_val(sl.Цена) or 0),
                    "Сумма": float(_val(sl.Сум) or 0), "СуммаНДС": float(_val(sl.СНДС) or 0),
                    # П2-фикс: ставка НДС из СТРОКИ документа (не из карточки товара)
                    "СтавкаНДС": str(_val(sl.Ставка) or "").strip(),
                })
            out.append({
                "Тип": "purchase", "ИсточникUUID": _xs(ib, s.Ссылка),
                "Номер": str(_val(s.Ном) or "").strip(), "Дата": str(_val(s.Дата)),
                "Проведен": bool(_val(s.Пров)), "ПометкаУдаления": bool(_val(s.Пом)),
                # F8: флаг «Сумма ПТУ включает НДС» — по нему считаем net (обычно
                # Истина; для ПТУ «без НДС» net = Сумма без повторного вычитания).
                "СуммаВключаетНДС": bool(_val(s.СумВклНДС)),
                "Организация": _xs(ib, s.Орг), "СуммаДокумента": float(_val(s.СумДок) or 0),
                "Контрагент": _xs(ib, s.Контр), "Товары": tovary,
            })
    except Exception as _e:
        # Не глушим молча (раньше `return out` маскировал синтакс-ошибку запроса → 0 ПТУ).
        raise RuntimeError(f"_attach_purchases (Склад ОРП): {_e}")
    return out


def _build_shift_package(ib: Any, orp: Any, station: str) -> dict[str, Any]:
    """ОРП (объект) → пакет смены v2 (контракт .epf): Смена + retail_sale + recipe.

    КлассSKU берём ЗАПРОСОМ через ПРЕДСТАВЛЕНИЕ(...ВидНоменклатуры): str() COM-объекта
    enum'а не сериализуется (даёт <COMObject>), поэтому объектный доступ к виду НЕ
    работает в Python-COM. «Набор - комплект» → Общепит (подтверждено на НЛ-208).
    """
    tovary = []
    recipes: list[dict[str, Any]] = []
    seen_dish: set[str] = set()

    q = ib.NewObject("Запрос")
    q.Текст = (
        "ВЫБРАТЬ Т.НомерСтроки КАК НС, Т.Номенклатура КАК Ном, "
        "ПРЕДСТАВЛЕНИЕ(Т.Номенклатура.ВидНоменклатуры) КАК Вид, "
        "ПРЕДСТАВЛЕНИЕ(Т.СтавкаНДС) КАК Ставка, "
        "Т.Количество КАК Кол, Т.Цена КАК Цена, Т.Сумма КАК Сум, Т.СуммаНДС КАК СНДС "
        "ИЗ Документ.ОтчетОРозничныхПродажах.Товары КАК Т "
        "ГДЕ Т.Ссылка = &Док УПОРЯДОЧИТЬ ПО Т.НомерСтроки"
    )
    q.УстановитьПараметр("Док", orp.Ссылка)
    s = q.Выполнить().Выбрать()
    while s.Следующий():
        klass = "Общепит" if str(_val(s.Вид) or "").strip() == "Набор - комплект" else "Сопутка"
        nom_uuid = _xs(ib, s.Ном)
        is_dish = klass == "Общепит"
        tovary.append({
            "НомерСтроки": int(_val(s.НС) or 0), "Номенклатура": nom_uuid,
            "Количество": float(_val(s.Кол) or 0),
            "Цена": float(_val(s.Цена) or 0), "Сумма": float(_val(s.Сум) or 0),
            "СуммаНДС": float(_val(s.СНДС) or 0),
            "СтавкаНДС": str(_val(s.Ставка) or "").strip(),
            "КлассSKU": klass, "ЭтоБлюдо": is_dish,
        })
        if is_dish and nom_uuid not in seen_dish:
            seen_dish.add(nom_uuid)
            ing = _recipe_for_dish(ib, s.Ном)
            if ing:
                recipes.append({"Тип": "recipe", "БлюдоUUID": nom_uuid, "Ингредиенты": ing})

    # Оплаты — группировка Товары по ФормаОплаты (как .epf).
    # ⚠ Реквизит ТЧ «БезналичнаяОплата» в ЭЛСИ.АЗК — НЕ булево, а перечисление
    # «Виды оплат чека ККМ», и оно в базе ПУСТОЕ. Читать его нельзя: пустая ссылка
    # приходит COM-объектом, а bool(COM-объект) — всегда Истина, из-за чего наличные
    # помечались безналом во ВСЕХ сменах. Признак выводим из самой ФормаОплаты.
    oplaty = []
    try:
        qo = ib.NewObject("Запрос")
        qo.Текст = (
            "ВЫБРАТЬ ПРЕДСТАВЛЕНИЕ(Т.ФормаОплаты) КАК Форма, "
            "СУММА(Т.Сумма) КАК Сум ИЗ Документ.ОтчетОРозничныхПродажах.Товары КАК Т "
            "ГДЕ Т.Ссылка = &Д СГРУППИРОВАТЬ ПО ПРЕДСТАВЛЕНИЕ(Т.ФормаОплаты)"
        )
        qo.УстановитьПараметр("Д", orp.Ссылка)
        so = qo.Выполнить().Выбрать()
        while so.Следующий():
            форма = str(_val(so.Форма) or "").strip()
            oplaty.append({
                "ФормаОплаты": форма,
                "БезналичнаяОплата": _is_cashless(форма),
                "Сумма": float(_val(so.Сум) or 0),
            })
    except Exception:
        pass

    # Возвраты (ТЧ ВозвращенныеТовары)
    vozvraty = []
    try:
        qv = ib.NewObject("Запрос")
        qv.Текст = (
            "ВЫБРАТЬ Т.НомерСтроки КАК НС, Т.Номенклатура КАК Ном, Т.Количество КАК Кол, "
            "Т.Цена КАК Цена, Т.Сумма КАК Сум, Т.СуммаНДС КАК СНДС "
            "ИЗ Документ.ОтчетОРозничныхПродажах.ВозвращенныеТовары КАК Т "
            "ГДЕ Т.Ссылка = &Д УПОРЯДОЧИТЬ ПО Т.НомерСтроки"
        )
        qv.УстановитьПараметр("Д", orp.Ссылка)
        sv = qv.Выполнить().Выбрать()
        while sv.Следующий():
            vozvraty.append({
                "НомерСтроки": int(_val(sv.НС) or 0), "Номенклатура": _xs(ib, sv.Ном),
                "Количество": float(_val(sv.Кол) or 0), "Цена": float(_val(sv.Цена) or 0),
                "Сумма": float(_val(sv.Сум) or 0), "СуммаНДС": float(_val(sv.СНДС) or 0),
            })
    except Exception:
        pass

    nomer = str(_val(orp.Номер) or "").strip()
    orp_uuid = _xs(ib, orp.Ссылка)
    doc = {
        "Тип": "retail_sale_sidegoods", "ИсточникUUID": orp_uuid,
        "Номер": nomer, "Дата": str(_val(orp.Дата)),
        "Проведен": bool(_val(getattr(orp, "Проведен", True))),
        "ПометкаУдаления": bool(_val(getattr(orp, "ПометкаУдаления", False))),
        "СуммаДокумента": float(_val(getattr(orp, "СуммаДокумента", 0)) or 0),
        "Товары": tovary, "Оплаты": oplaty, "ВозвращенныеТовары": vozvraty,
    }
    return {
        "ВерсияФормата": "2",
        "Смена": {
            # П1-фикс: GUID смены (ОРП Ссылка) — уникальный ключ per-смена. Без него
            # ключ деградировал до «день|станция» и схлопывал двухсменные дни в 1 пакет.
            "Смена": orp_uuid,
            "КодАЗС": station, "НомерСмены": nomer, "ОСЭНомер": nomer,
            "Открытие": str(_val(getattr(orp, "ДатаВремяОткрытия", ""))),
            "Закрытие": str(_val(getattr(orp, "ДатаВремяЗакрытия", ""))),
            "Склад": _xs(ib, orp.Склад), "Организация": _xs(ib, orp.Организация),
        },
        "Документы": recipes + _attach_purchases(ib, orp) + [doc],
    }


def op_fetch_cb_shifts(period_from: str, period_to: str,
                       station: str = "208", limit: int = 50) -> list[dict[str, Any]]:
    """Извлечь смены ЦБ (сопутка/общепит) за период → пакеты v2 для cb_normalize.

    Опорный = ОРП; Товары с КлассSKU/ЭтоБлюдо; блюда + recipe (ТТК). Read-only.
    """
    ib = _require_ib()
    q = ib.NewObject("Запрос")
    # F7: отбор по ТОЧНОМУ коду склада/подразделения (параметр), не LIKE по имени —
    # LIKE "%208%" мог захватить чужой склад с «208» в имени или потерять смену при
    # переименовании. Сортировка ПО УБЫВАНИЮ: при обрезке лимитом отбрасываются
    # СТАРЕЙШИЕ смены, а не новейшие (раньше ПЕРВЫЕ по возрастанию теряли свежие).
    q.Текст = (
        f"ВЫБРАТЬ ПЕРВЫЕ {int(limit)} Т.Ссылка КАК Ссылка ИЗ Документ.ОтчетОРозничныхПродажах КАК Т "
        f"ГДЕ Т.Дата >= ДАТАВРЕМЯ({_dt_lit(period_from)}) И Т.Дата <= ДАТАВРЕМЯ({_dt_lit(period_to, True)}) "
        f"И (Т.Склад.Код = &Код ИЛИ Т.Склад.Код ПОДОБНО &КодСклада) "
        f"УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ"
    )
    q.УстановитьПараметр("Код", str(station))
    # Второй склад станции — её кладовая: код начинается с кода АЗС
    # (у 208 это 20800002). Реквизита «Подразделение» у ОРП нет, и обращение
    # к нему роняло весь запрос вместе с каналом.
    q.УстановитьПараметр("КодСклада", f"{station}0%")
    sel = q.Выполнить().Выбрать()
    packages = []
    while sel.Следующий():
        orp = sel.Ссылка.ПолучитьОбъект()
        # F4: пропускаем смену только если пусты ОБЕ ТЧ (продажи И возвраты) —
        # зеркало эталона СобратьRetailSaleSidegoods (bsl:455). Раньше проверялась
        # только Товары → смена «только возвраты» терялась вместе с прицепленными
        # к ней документами дня, а выручка не уменьшалась на возвраты.
        if orp.Товары.Количество() == 0 and orp.ВозвращенныеТовары.Количество() == 0:
            continue
        packages.append(_build_shift_package(ib, orp, station))
    return packages


def op_fetch_register_balance(
    register: str,
    dimensions: list[str] | None = None,
    resources: list[str] | None = None,
    on_date: str | None = None,
    top: int | None = None,
) -> list[dict[str, Any]]:
    """Остатки регистра накопления через виртуальную таблицу <Регистр>.Остатки.

    register — OData-имя (AccumulationRegister_ПартииТоваровНаСкладах).
    dimensions — измерения в выборку (Номенклатура/Склад/ДокументОприходования/…).
    resources — ресурсы: в выборку берётся <Ресурс>Остаток (Количество→КоличествоОстаток).
    on_date — ISO 'YYYY-MM-DD[THH:MM:SS]' срез (иначе текущие итоги).
    Ссылки (Номенклатура/Склад/док-регистратор) конвертируются в GUID через _val.
    """
    ib = _require_ib()
    qualified = _resolve_entity(register)
    dims = dimensions or []
    res = resources or ["Количество"]
    # Безопасные позиционные алиасы f0,f1,… — иначе алиас-колонка (напр. «Количество»)
    # коллидирует с методом Выборки (Выборка.Количество() = число строк) и _val вернёт
    # число строк вместо значения ресурса.
    alias_map: list[tuple[str, str]] = []  # (alias, out_name)
    parts: list[str] = []
    for i, d in enumerate(dims):
        a = f"f{i}"
        parts.append(f"Т.{d} КАК {a}")
        alias_map.append((a, d))
    for j, r in enumerate(res):
        a = f"f{len(dims) + j}"
        parts.append(f"Т.{r}Остаток КАК {a}")
        alias_map.append((a, r))
    top_clause = f"ПЕРВЫЕ {int(top)} " if top else ""

    period_expr = ""
    if on_date:
        import re
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}):(\d{2}))?", on_date)
        if m:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            hh, mi, ss = (m.group(4) or "23"), (m.group(5) or "59"), (m.group(6) or "59")
            period_expr = f"ДАТАВРЕМЯ({y},{mo},{d},{hh},{mi},{ss})"

    text = (
        f"ВЫБРАТЬ {top_clause}" + ", ".join(parts)
        + f" ИЗ {qualified}.Остатки({period_expr}) КАК Т"
    )
    q = ib.NewObject("Запрос")
    q.Текст = text
    sel = q.Выполнить().Выбрать()
    rows: list[dict[str, Any]] = []
    while sel.Следующий():
        rows.append({out: _val(getattr(sel, a)) for a, out in alias_map})
    return rows


def op_query_tabular(
    doc_type: str,
    tabular: str,
    select: list[str] | None = None,
    where: str | None = None,
    top: int | None = None,
) -> list[dict[str, Any]]:
    """Строки табличной части документа через прямой запрос (для чтения движений).

    doc_type — имя документа (ИнвентаризацияТоваровНаСкладе), tabular — ТЧ (Товары).
    select — поля ТЧ (Номенклатура/Количество/…) и шапки через «Ссылка.Поле»
    (Ссылка, Ссылка.Номер, Ссылка.Дата, Ссылка.Склад). where — сырое условие 1С
    с префиксом Т. (напр. «Т.Количество <> Т.КоличествоУчет»). Безопасные алиасы fN.
    Ссылки конвертируются в GUID через _val.
    """
    ib = _require_ib()
    fields = select or ["Номенклатура"]
    alias_map: list[tuple[str, str]] = []
    parts: list[str] = []
    for i, f in enumerate(fields):
        a = f"f{i}"
        parts.append(f"Т.{f} КАК {a}")
        alias_map.append((a, f))
    top_clause = f"ПЕРВЫЕ {int(top)} " if top else ""
    where_clause = f"ГДЕ {where} " if where else ""
    text = (
        f"ВЫБРАТЬ {top_clause}" + ", ".join(parts)
        + f" ИЗ Документ.{doc_type}.{tabular} КАК Т " + where_clause
    ).strip()
    q = ib.NewObject("Запрос")
    q.Текст = text
    sel = q.Выполнить().Выбрать()
    rows: list[dict[str, Any]] = []
    while sel.Следующий():
        rows.append({out: _val(getattr(sel, a)) for a, out in alias_map})
    return rows


# Маппинг имён полей OData → выражения языка запросов 1С.
# Если поля нет в карте — берём как Т.<поле> (кириллица as-is).
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
    # Документы БП 3.0 — реквизиты шапки. Подтягиваем GUID связанных
    # справочников (Контрагент/Организация/Склад) — имя подставит локальная БД.
    "Контрагент_Key":     "Т.Контрагент",
    "Организация_Key":    "Т.Организация",
    "Склад_Key":          "Т.Склад",
    "Договор_Key":        "Т.ДоговорКонтрагента",
    # Владелец подчинённого справочника (договор → контрагент). В OData стандартное
    # имя Owner_Key; в языке запросов 1С — Т.Владелец.
    "Owner_Key":          "Т.Владелец",
    # Реквизиты входящего документа поставщика (ТТН) — ключи сверки.
    # Имена реквизитов в OData кириллицей: НомерВходящегоДокумента / ДатаВходящегоДокумента.
    "НомерВходящегоДокумента": "Т.НомерВходящегоДокумента",
    "ДатаВходящегоДокумента":  "Т.ДатаВходящегоДокумента",
    # ВидОперации (enum) — приходит как ссылка, через _val конвертируется в строку.
    "ВидОперации":        "Т.ВидОперации",
    # Денежные итоги — нужны для расчёта НДС/наличных.
    "СуммаНДС":           "Т.СуммаНДС",
    "СуммаНаличных":      "Т.СуммаНаличных",
    "СуммаВключаетНДС":   "Т.СуммаВключаетНДС",
}


# Типы вне пакета смены: выпуск блюд (себестоимость общепита), оприходование
# излишков, возврат поставщику. Оркестратор зовёт их следом за сменами.

def op_fetch_production(period_from: str, period_to: str, station: str = "208") -> list[dict[str, Any]]:
    """Документ.ВыпускПродукции (общепит) за период по станции → пакет-готовые
    item'ы production_release (ВыпускБлюд[Товары] + Ингредиенты, связка
    Идентификатор↔ИдентификаторПродукция). Read-only."""
    ib = _require_ib()
    q = ib.NewObject("Запрос")
    q.Текст = (
        "ВЫБРАТЬ Т.Ссылка КАК Ссылка ИЗ Документ.ВыпускПродукции КАК Т "
        f"ГДЕ Т.Дата >= ДАТАВРЕМЯ({_dt_lit(period_from)}) И Т.Дата <= ДАТАВРЕМЯ({_dt_lit(period_to, True)}) "
        f'И Т.Склад.Код = "{station}" И Т.ПометкаУдаления = ЛОЖЬ УПОРЯДОЧИТЬ ПО Т.Дата'
    )
    sel = q.Выполнить().Выбрать()
    out: list[dict[str, Any]] = []
    while sel.Следующий():
        o = sel.Ссылка.ПолучитьОбъект()
        блюда = []
        for i in range(o.Товары.Количество()):
            r = o.Товары.Получить(i)
            блюда.append({
                "НомерСтроки": i + 1,
                "Идентификатор": str(_val(r.Идентификатор) or ""),
                "Номенклатура": _xs(ib, r.Номенклатура),
                "Количество": float(_val(r.Количество) or 0),
                "Цена": float(_val(r.Цена) or 0),
                "Сумма": float(_val(r.Сумма) or 0),
            })
        ингр = []
        for i in range(o.Ингредиенты.Количество()):
            r = o.Ингредиенты.Получить(i)
            ингр.append({
                "НомерСтроки": i + 1,
                "ИдентификаторПродукция": str(_val(r.ИдентификаторПродукция) or ""),
                "Номенклатура": _xs(ib, r.Номенклатура),
                "Количество": float(_val(r.Количество) or 0),
            })
        d = str(_val(o.Дата))
        out.append({
            "Тип": "production_release",
            "ИсточникUUID": _xs(ib, o.Ссылка),
            "Номер": str(_val(o.Номер) or "").strip(),
            "Дата": str(_val(o.Дата) or ""),
            "Проведен": bool(_val(o.Проведен)),
            "ПометкаУдаления": bool(_val(o.ПометкаУдаления)),
            "Организация": _xs(ib, o.Организация),
            "Склад": _xs(ib, o.Склад),
            "ВалютаДокумента": "RUB",
            "СуммаДокумента": float(_val(o.СуммаДокумента) or 0),
            "ВыпускБлюд": блюда,
            "Ингредиенты": ингр,
            "_station": station,
            "_day": d[:10],
        })
    return out


def op_fetch_gain(period_from: str, period_to: str, station: str = "208") -> list[dict[str, Any]]:
    """Документ.ОприходованиеТоваров за период по станции → пакет-готовые item'ы
    gain. Read-only."""
    ib = _require_ib()
    q = ib.NewObject("Запрос")
    q.Текст = (
        "ВЫБРАТЬ Т.Ссылка КАК Ссылка ИЗ Документ.ОприходованиеТоваров КАК Т "
        f"ГДЕ Т.Дата >= ДАТАВРЕМЯ({_dt_lit(period_from)}) И Т.Дата <= ДАТАВРЕМЯ({_dt_lit(period_to, True)}) "
        f'И Т.Склад.Код = "{station}" И Т.ПометкаУдаления = ЛОЖЬ УПОРЯДОЧИТЬ ПО Т.Дата'
    )
    sel = q.Выполнить().Выбрать()
    out: list[dict[str, Any]] = []
    while sel.Следующий():
        o = sel.Ссылка.ПолучитьОбъект()
        товары = []
        сумма_ндс = 0.0
        for i in range(o.Товары.Количество()):
            r = o.Товары.Получить(i)
            nds = float(_val(r.СуммаНДС) or 0)
            сумма_ндс += nds
            товары.append({
                "НомерСтроки": i + 1,
                "Номенклатура": _xs(ib, r.Номенклатура),
                "Количество": float(_val(r.Количество) or 0),
                "Цена": float(_val(r.Цена) or 0),
                "Сумма": float(_val(r.Сумма) or 0),
                "СтавкаНДС_raw": str(_val(r.СтавкаНДС) or ""),
                "СуммаНДС": nds,
            })
        d = str(_val(o.Дата))
        out.append({
            "Тип": "gain",
            "ИсточникUUID": _xs(ib, o.Ссылка),
            "Номер": str(_val(o.Номер) or "").strip(),
            "Дата": d,
            "Проведен": bool(_val(o.Проведен)),
            "ПометкаУдаления": bool(_val(o.ПометкаУдаления)),
            "Организация": _xs(ib, o.Организация),
            "Склад": _xs(ib, o.Склад),
            "Подразделение": str(_val(o.Подразделение) or ""),
            "ИнвентаризацияUUID": _xs(ib, o.ИнвентаризацияТоваровНаСкладе) if _val(o.ИнвентаризацияТоваровНаСкладе) else "",
            "МестоОприходования": str(_val(o.МестоОприходования) or ""),
            "СуммаДокумента": float(_val(o.СуммаДокумента) or 0),
            "ВалютаДокумента": "RUB",
            "СуммаВключаетНДС": bool(_val(o.СуммаВключаетНДС)),
            "НДСНеВыделять": not bool(_val(o.УчитыватьНДС)),
            "НДСВключенВСтоимость": bool(_val(o.НДСВключенВСтоимость)),
            "Товары": товары,
            "СуммаНДС": сумма_ндс,
            "_station": station,
            "_day": d[:10],
        })
    return out


def _return_doc_type_name(ib: Any) -> str:
    """Имя типа документа возврата поставщику в текущей конфигурации ЭЛСИ.АЗК.
    Зеркало эталона ОпределитьИмяТипаВозвратаПоставщику (bsl:869): в разных
    редакциях документ называется по-разному. Возврат "" если не покрыт."""
    for name in ("ВозвратТоваровПоставщикуНаАЗК", "ВозвратТоваровПоставщику"):
        if ib.Метаданные.Документы.Найти(name) is not None:
            return name
    return ""


def op_fetch_returns(period_from: str, period_to: str, station: str = "208") -> list[dict[str, Any]]:
    """Документ.ВозвратТоваровПоставщику(НаАЗК) за период по станции → пакет-готовые
    item'ы return_purchase (F2). Зеркало эталона СобратьReturnPurchase/
    СформироватьОбъектReturnPurchase (TL_ЭкспортБП_Сервер.bsl:815-962). Read-only.
    Пусто, если конфигурация не покрывает возвраты поставщику."""
    ib = _require_ib()
    tname = _return_doc_type_name(ib)
    if not tname:
        return []
    q = ib.NewObject("Запрос")
    # Склад может отсутствовать у документа в части редакций (эталон оборачивает в
    # Попытку) — фильтруем по складу, при синтакс-ошибке падаем на период целиком.
    base = (
        f"ВЫБРАТЬ Т.Ссылка КАК Ссылка ИЗ Документ.{tname} КАК Т "
        f"ГДЕ Т.Дата >= ДАТАВРЕМЯ({_dt_lit(period_from)}) И Т.Дата <= ДАТАВРЕМЯ({_dt_lit(period_to, True)}) "
        "И Т.ПометкаУдаления = ЛОЖЬ"
    )
    try:
        q.Текст = base + f' И Т.Склад.Код = "{station}" УПОРЯДОЧИТЬ ПО Т.Дата'
        sel = q.Выполнить().Выбрать()
    except Exception:
        q.Текст = base + " УПОРЯДОЧИТЬ ПО Т.Дата"
        sel = q.Выполнить().Выбрать()
    out: list[dict[str, Any]] = []
    while sel.Следующий():
        o = sel.Ссылка.ПолучитьОбъект()
        товары = []
        сумма_ндс = 0.0
        for i in range(o.Товары.Количество()):
            r = o.Товары.Получить(i)
            nds = float(_val(r.СуммаНДС) or 0)
            сумма_ндс += nds
            товары.append({
                "НомерСтроки": i + 1,
                "Номенклатура": _xs(ib, r.Номенклатура),
                "Количество": float(_val(r.Количество) or 0),
                "Цена": float(_val(r.Цена) or 0),
                "Сумма": float(_val(r.Сумма) or 0),
                "СтавкаНДС": str(_val(getattr(r, "СтавкаНДС", "")) or "").strip(),
                "СуммаНДС": nds,
            })
        # ПервичнаяПТУ_UUID — документ-основание (Сделка в БП 3.0); берём осторожно.
        pervichnaya = ""
        try:
            sd = getattr(o, "Сделка", None)
            if _val(sd):
                pervichnaya = _xs(ib, sd)
        except Exception:
            pass
        d = str(_val(o.Дата))
        out.append({
            "Тип": "return_purchase",
            "ИсточникUUID": _xs(ib, o.Ссылка),
            "Номер": str(_val(o.Номер) or "").strip(),
            "Дата": d,
            "Проведен": bool(_val(getattr(o, "Проведен", True))),
            "ПометкаУдаления": bool(_val(getattr(o, "ПометкаУдаления", False))),
            "Организация": _xs(ib, o.Организация) if _val(getattr(o, "Организация", None)) else "",
            "Контрагент": _xs(ib, o.Контрагент) if _val(getattr(o, "Контрагент", None)) else "",
            "Склад": _xs(ib, o.Склад) if _val(getattr(o, "Склад", None)) else "",
            "ПервичнаяПТУ_UUID": pervichnaya,
            "СуммаДокумента": float(_val(getattr(o, "СуммаДокумента", 0)) or 0),
            "ВалютаДокумента": "RUB",
            "СуммаВключаетНДС": bool(_val(getattr(o, "СуммаВключаетНДС", True))),
            "Товары": товары,
            "СуммаНДС": round(сумма_ндс, 2),
            "_station": station,
            "_day": d[:10],
        })
    return out
