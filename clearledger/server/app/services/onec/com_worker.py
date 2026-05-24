# 32-bit Python worker — мост между FastAPI (64-bit) и V83.COMConnector.
#
# Запуск из родительского процесса:
#   py -3.13-32 -m app.services.onec.com_worker
# Протокол: JSON-Lines через stdin/stdout (по одной команде/ответу на строку).
# Завершение: пустая строка или EOF.
#
# Поддерживаемые операции:
#   {"op": "connect",          "args": {"conn_string": "File=...;Usr=...;Pwd=..."}}
#   {"op": "metadata_catalogs"}
#   {"op": "fetch_entity",     "args": {"entity": "Контрагенты", "select": [...], "filter": "...", "orderby": "...", "top": N, "skip": M}}
#   {"op": "count_entity",     "args": {"entity": "Контрагенты", "filter": "..."}}
#   {"op": "ping"}
#
# Имена сущностей передаются БЕЗ префикса OData (`Контрагенты`, не `Catalog_Контрагенты`),
# потому что в COM-запросе мы используем `Справочник.Контрагенты`. Клиент-обёртка
# выполняет конвертацию.

from __future__ import annotations

import json
import sys
from typing import Any

# Принудительно переводим stdio в UTF-8 — Windows-консоль по умолчанию cp1251,
# что ломает JSON с кириллицей при пайпе родительскому процессу.
try:
    sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, OSError):
    pass

try:
    import win32com.client  # type: ignore[import-not-found]
except ImportError as exc:
    print(json.dumps({"ok": False, "error": f"pywin32 not installed: {exc}"}), flush=True)
    sys.exit(1)


# Глобальное состояние воркера — COM-объект инфобазы.
IB: Any = None


# Кириллические имена сущностей → имена в языке запросов 1С.
# OData-схема: префикс типа метаданного_имя; COM: квалификатор.имя.
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
    """COM Variant getter — поле может быть скаляром, COM-ссылкой 1С или COM-датой."""
    if obj is None:
        return None
    # Скаляры — сразу.
    if isinstance(obj, (int, float, str, bool)):
        return obj
    # Дата 1С (COM Time) → ISO-строка.
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    # Ссылка 1С (CDispatch) — извлекаем GUID через ib.String(УникальныйИдентификатор()).
    # ib.String — английский алиас глобальной функции Строка() платформы,
    # доступен из V83.COMConnector. Метод УникальныйИдентификатор() даёт
    # CDispatch-объект УникальныйИдентификатор, который сам не имеет
    # default property — но String() умеет конвертировать его в GUID-строку.
    try:
        guid_obj = obj.УникальныйИдентификатор()
        return str(IB.String(guid_obj))  # type: ignore[union-attr]
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
    """OData_имя → язык запросов 1С (Catalog_Контрагенты → Справочник.Контрагенты)."""
    for prefix, qualifier in ENTITY_TYPE_PREFIX.items():
        if odata_name.startswith(prefix):
            return f"{qualifier}.{odata_name[len(prefix):]}"
    raise ValueError(f"Неизвестный префикс OData-сущности: {odata_name}")


def op_connect(conn_string: str) -> dict[str, Any]:
    global IB
    conn = win32com.client.Dispatch("V83.COMConnector")
    IB = conn.Connect(conn_string)
    md = IB.Метаданные
    return {
        "config_name": _val(md.Имя),
        "config_synonym": _val(md.Синоним),
        "config_version": _val(md.Версия),
    }


def _require_ib() -> Any:
    if IB is None:
        raise RuntimeError("Соединение не открыто — сначала вызвать op=connect")
    return IB


def op_metadata_catalogs() -> list[str]:
    """Список всех Catalog_ имён через коллекцию Метаданные.Справочники."""
    ib = _require_ib()
    catalogs: list[str] = []
    coll = ib.Метаданные.Справочники
    for i in range(coll.Количество()):
        item = coll.Получить(i)
        catalogs.append(f"Catalog_{_val(item.Имя)}")
    return catalogs


# Маппинг имён полей OData → выражения языка запросов 1С.
# Если поля нет в карте — берём как Т.<поле> (кириллица as-is).
ODATA_TO_QUERY_FIELDS: dict[str, str] = {
    "Ref_Key":            "Т.Ссылка",
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


def _build_query_text(
    qualified_entity: str,
    select: list[str] | None,
    filter_expr: str | None,
    orderby: str | None,
    top: int | None,
    skip: int | None,
) -> tuple[str, dict[str, Any]]:
    fields = select if select else ["Ref_Key"]
    alias_pairs = []
    for f in fields:
        if f in ODATA_TO_QUERY_FIELDS:
            alias_pairs.append(f"{ODATA_TO_QUERY_FIELDS[f]} КАК {f}")
        elif f.startswith("RAW:"):
            # `RAW:<sql>` — встроенное выражение без преобразований
            alias_pairs.append(f[4:])
        else:
            # Кириллические поля (ИНН, КПП, Артикул, СуммаДокумента ...) — как есть.
            alias_pairs.append(f"Т.{f} КАК {f}")

    select_clause = ", ".join(alias_pairs)
    top_clause = f"ПЕРВЫЕ {top}" if top else ""
    where_clause = ""
    if filter_expr:
        # OData → 1С: `eq` → `=`, `ne` → `<>`, `ge` → `>=`, `le` → `<=`, кавычки.
        # datetime'YYYY-MM-DDTHH:MM:SS' → ДАТАВРЕМЯ(Y,M,D,H,M,S).
        import re

        converted = filter_expr
        converted = converted.replace(" eq ", " = ")
        converted = converted.replace(" ne ", " <> ")
        converted = converted.replace(" ge ", " >= ")
        converted = converted.replace(" le ", " <= ")
        converted = converted.replace(" gt ", " > ")
        converted = converted.replace(" lt ", " < ")
        converted = re.sub(
            r"datetime'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})'",
            r"ДАТАВРЕМЯ(\1,\2,\3,\4,\5,\6)",
            converted,
        )
        converted = converted.replace("'", '"')
        where_clause = "ГДЕ " + converted
    order_clause = f"УПОРЯДОЧИТЬ ПО {orderby}" if orderby else ""

    text = (
        f"ВЫБРАТЬ {top_clause} {select_clause} "
        f"ИЗ {qualified_entity} КАК Т "
        f"{where_clause} {order_clause}".strip()
    )
    return text, {}


def op_fetch_entity(
    entity: str,
    select: list[str] | None = None,
    filter: str | None = None,  # noqa: A002 — shadowing встроенного для совместимости с OData
    orderby: str | None = None,
    top: int | None = None,
    skip: int | None = None,
) -> list[dict[str, Any]]:
    ib = _require_ib()
    qualified = _resolve_entity(entity)

    # В языке запросов 1С есть только ПЕРВЫЕ N (LIMIT), нет OFFSET. Для skip=K
    # запрашиваем (skip + top) первых записей, затем пропускаем skip в курсоре.
    # Это работает корректно для последовательной пагинации с фиксированным
    # ORDER BY (например Ref_Key), но потенциально дорого для глубоких страниц.
    effective_top: int | None = top
    if skip and top:
        effective_top = top + skip
    elif skip and not top:
        effective_top = None  # без ПЕРВЫЕ — вернёт всё, курсор пропустит skip

    text, _ = _build_query_text(qualified, select, filter, orderby, effective_top, skip)
    q = ib.NewObject("Запрос")
    q.Текст = text
    sel = q.Выполнить().Выбрать()

    if skip:
        for _ in range(skip):
            if not sel.Следующий():
                return []

    fields = select if select else ["Ref_Key"]
    rows: list[dict[str, Any]] = []
    while sel.Следующий():
        row: dict[str, Any] = {}
        for f in fields:
            if f.startswith("RAW:"):
                # raw-выражение оставляет только последний КАК-алиас в SELECT,
                # а сюда передавать имя с прицепленным алиасом нельзя — пропускаем.
                continue
            row[f] = _val(getattr(sel, f))
        rows.append(row)
    return rows


def op_fetch_doc_lines(
    doc_type: str,
    doc_ref: str,
    tabular_name: str,
    select: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Достать ТЧ документа через прямой доступ к объекту.

    Через Документы.<doc_type>.НайтиПоИдентификатору(УИД) → ПолучитьОбъект()
    → получаем доступ к ТЧ по имени реквизита (Товары/Услуги/...).
    Поля select — внутренние имена реквизитов 1С (Номенклатура, Количество,
    Цена, Сумма, СтавкаНДС, СуммаНДС, Всего, СчетУчета и т.п.).
    Для ссылочных полей _val извлекает GUID через ib.String().
    """
    ib = _require_ib()
    # pywin32 видит у менеджера документа только английские алиасы:
    # FindByNumber / GetRef / EmptyRef (не НайтиПоИдентификатору). Используем
    # GetRef(уид) — создаёт ссылку из УИД без обращения к БД, потом GetObject().
    doc_manager = getattr(ib.Documents, doc_type)
    uid_obj = ib.NewObject("УникальныйИдентификатор", doc_ref)
    doc_ref_obj = doc_manager.GetRef(uid_obj)  # alias ПолучитьСсылку
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


def op_enrich_nomenclature(refs: list[str]) -> dict[str, dict[str, Any]]:
    """Для списка GUID Номенклатуры — вернуть {guid: {name, unit, density}}.

    Тонна↔литр конвертация для топлива требует плотности (Catalog.Номенклатура.
    Плотность — это доп.реквизит в БП ГИГ). Если поля нет — возвращаем None."""
    ib = _require_ib()
    if not refs:
        return {}
    # Передаём массив через параметр запроса.
    arr = ib.NewObject("Array")
    cat_mgr = ib.Catalogs.Номенклатура
    for guid_str in refs:
        try:
            uid = ib.NewObject("УникальныйИдентификатор", guid_str)
            arr.Add(cat_mgr.GetRef(uid))
        except Exception:
            continue
    q = ib.NewObject("Запрос")
    # Плотность в БП ГИГ — обычно реквизит "Плотность". Если не существует,
    # fallback — отсутствует в результате, в UI просто не будет конвертации.
    q.Текст = (
        "ВЫБРАТЬ "
        "Т.Ссылка КАК Ref, "
        "Т.Наименование КАК Name, "
        "ПРЕДСТАВЛЕНИЕ(Т.ЕдиницаИзмерения) КАК Unit, "
        "Т.Артикул КАК Article "
        "ИЗ Справочник.Номенклатура КАК Т "
        "ГДЕ Т.Ссылка В (&Refs)"
    )
    q.УстановитьПараметр("Refs", arr)
    sel = q.Выполнить().Выбрать()
    result: dict[str, dict[str, Any]] = {}
    while sel.Следующий():
        ref_guid = _val(sel.Ref)
        if not ref_guid:
            continue
        result[str(ref_guid)] = {
            "name": _val(sel.Name),
            "unit": _val(sel.Unit),
            "article": _val(sel.Article),
            # Плотность пока не тянем — пробуем добавить отдельным запросом
            # с защитой от отсутствия поля.
        }
    # Пытаемся подтянуть Плотность отдельным запросом — если упадёт,
    # просто пропустим без enrichment плотности.
    try:
        q2 = ib.NewObject("Запрос")
        q2.Текст = (
            "ВЫБРАТЬ Т.Ссылка КАК Ref, Т.Плотность КАК Density "
            "ИЗ Справочник.Номенклатура КАК Т ГДЕ Т.Ссылка В (&Refs)"
        )
        q2.УстановитьПараметр("Refs", arr)
        sel2 = q2.Выполнить().Выбрать()
        while sel2.Следующий():
            ref = _val(sel2.Ref)
            if ref and ref in result:
                d = _val(sel2.Density)
                if d:
                    result[ref]["density"] = float(d)
    except Exception:
        pass
    return result


def op_fetch_postings(
    doc_type: str,
    doc_ref: str,
) -> list[dict[str, Any]]:
    """Достать проводки документа из РегистрБухгалтерии.Хозрасчетный.

    Через запрос языка 1С с параметром-ссылкой на регистратор. Возвращает
    Период / СчетДт / СчетКт / Сумма / Субконто*. Все ссылочные поля
    конвертируются в строки через _val (GUID или представление)."""
    ib = _require_ib()
    doc_manager = getattr(ib.Documents, doc_type)
    uid_obj = ib.NewObject("УникальныйИдентификатор", doc_ref)
    doc_ref_obj = doc_manager.GetRef(uid_obj)
    if doc_ref_obj is None:
        return []

    q = ib.NewObject("Запрос")
    # Минимум — Период/Счета/Сумма. Субконто в БП 3.0 имеют разную
    # структуру реквизитов (Субконто1..3 vs СубконтоДт/СубконтоКт в
    # зависимости от настроек плана счетов), берём расширение позже
    # после смотра реального ответа.
    q.Текст = (
        "ВЫБРАТЬ "
        "Р.Период КАК Period, "
        "ПРЕДСТАВЛЕНИЕ(Р.СчетДт) КАК AccountDt, "
        "ПРЕДСТАВЛЕНИЕ(Р.СчетКт) КАК AccountCt, "
        "Р.Сумма КАК Amount "
        "ИЗ РегистрБухгалтерии.Хозрасчетный КАК Р "
        "ГДЕ Р.Регистратор = &Регистратор"
    )
    q.УстановитьПараметр("Регистратор", doc_ref_obj)
    sel = q.Выполнить().Выбрать()
    fields = ["Period", "AccountDt", "AccountCt", "Amount"]
    rows: list[dict[str, Any]] = []
    i = 0
    while sel.Следующий():
        i += 1
        out: dict[str, Any] = {"LineNumber": i}
        for f in fields:
            try:
                out[f] = _val(getattr(sel, f))
            except Exception:
                out[f] = None
        rows.append(out)
    return rows


def op_count_entity(entity: str, filter: str | None = None) -> int:  # noqa: A002
    ib = _require_ib()
    qualified = _resolve_entity(entity)
    where_clause = ""
    if filter:
        where_clause = "ГДЕ " + filter.replace(" eq ", " = ").replace(" ne ", " <> ").replace("'", '"')
    q = ib.NewObject("Запрос")
    q.Текст = f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК Cnt ИЗ {qualified} КАК Т {where_clause}".strip()
    sel = q.Выполнить().Выбрать()
    sel.Следующий()
    return int(_val(sel.Cnt) or 0)


def main() -> int:
    while True:
        line = sys.stdin.readline()
        if not line:
            return 0
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
            op = cmd.get("op")
            args = cmd.get("args") or {}
            if op == "ping":
                result: Any = "pong"
            elif op == "connect":
                result = op_connect(args["conn_string"])
            elif op == "metadata_catalogs":
                result = op_metadata_catalogs()
            elif op == "fetch_entity":
                result = op_fetch_entity(**args)
            elif op == "count_entity":
                result = op_count_entity(**args)
            elif op == "fetch_doc_lines":
                result = op_fetch_doc_lines(**args)
            elif op == "fetch_postings":
                result = op_fetch_postings(**args)
            elif op == "enrich_nomenclature":
                result = op_enrich_nomenclature(**args)
            elif op == "exit":
                return 0
            else:
                raise ValueError(f"Unknown op: {op}")
            sys.stdout.write(json.dumps({"ok": True, "result": result}, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
