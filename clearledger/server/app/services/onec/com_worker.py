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
    # Значение перечисления (ВидДоговора, ЮридическоеФизическоеЛицо и пр.) — нет
    # УникальныйИдентификатор. Берём синоним через Строка(). Строго ПОСЛЕ ветки
    # ссылок, поэтому GUID-конвертация ссылок не затрагивается.
    try:
        s = str(IB.String(obj))  # type: ignore[union-attr]
        if s and not s.startswith("<"):
            return s
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


def op_metadata_registers(name_substring: str = "") -> list[str]:
    """Список всех InformationRegister_ имён через Метаданные.РегистрыСведений.
    Опционально фильтрует по подстроке в имени (case-insensitive)."""
    ib = _require_ib()
    out: list[str] = []
    coll = ib.Метаданные.РегистрыСведений
    ns = name_substring.lower()
    for i in range(coll.Количество()):
        item = coll.Получить(i)
        nm = _val(item.Имя) or ""
        if not ns or ns in str(nm).lower():
            out.append(f"InformationRegister_{nm}")
    return out


def op_metadata_documents(name_substring: str = "") -> list[str]:
    """Список всех Document_ имён через Метаданные.Документы (probe товародвижения).
    Опционально фильтрует по подстроке в имени (case-insensitive)."""
    ib = _require_ib()
    out: list[str] = []
    coll = ib.Метаданные.Документы
    ns = name_substring.lower()
    for i in range(coll.Количество()):
        item = coll.Получить(i)
        nm = _val(item.Имя) or ""
        if not ns or ns in str(nm).lower():
            out.append(f"Document_{nm}")
    return out


def op_metadata_accum_registers(name_substring: str = "") -> list[str]:
    """Список всех AccumulationRegister_ имён через Метаданные.РегистрыНакопления
    (probe остатков/партий товаров). Опционально фильтрует по подстроке."""
    ib = _require_ib()
    out: list[str] = []
    coll = ib.Метаданные.РегистрыНакопления
    ns = name_substring.lower()
    for i in range(coll.Количество()):
        item = coll.Получить(i)
        nm = _val(item.Имя) or ""
        if not ns or ns in str(nm).lower():
            out.append(f"AccumulationRegister_{nm}")
    return out


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


def _resolve_field(field: str) -> str:
    """ODATA-имя → выражение в языке запросов 1С.
    Поля типа 'X_Key' маппятся в Т.X (просто отбрасываем суффикс _Key).
    Кириллические имена — добавляем алиас Т.<имя>."""
    if field in ODATA_TO_QUERY_FIELDS:
        return ODATA_TO_QUERY_FIELDS[field]
    if field.endswith("_Key"):
        base = field[:-4]
        return f"Т.{base}"
    return f"Т.{field}"


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
        if f.startswith("RAW:"):
            # `RAW:<sql>` — встроенное выражение без преобразований
            alias_pairs.append(f[4:])
        else:
            alias_pairs.append(f"{_resolve_field(f)} КАК {f}")

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


def op_describe_entity(entity: str) -> dict[str, list[str]]:
    """Возвращает структуру метаданных объекта 1С:
    {dimensions, resources, attributes, std_attributes}.

    Универсальный probe для УчетнойПолитики и других регистров/справочников,
    где состав реквизитов меняется от версии к версии БП.
    Имена возвращаем в формате 'Имя' (как в языке запросов 1С).
    """
    ib = _require_ib()
    qualified = _resolve_entity(entity)
    qualifier, _, name = qualified.partition(".")
    # Доступ к Метаданные.<категория>.Получить(имя)
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
    coll = getattr(md, coll_name)
    obj = coll.Найти(name)
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
                item = collection.Получить(i)
                out.append(str(item.Имя))
            except Exception:
                continue
        return out

    result: dict[str, list[str]] = {
        "dimensions": [],
        "resources": [],
        "attributes": [],
    }
    for attr_name, key in (("Измерения", "dimensions"), ("Ресурсы", "resources"), ("Реквизиты", "attributes")):
        try:
            result[key] = _names(getattr(obj, attr_name))
        except AttributeError:
            result[key] = []
    # Табличные части (для документов) — {имя ТЧ: [реквизиты]}. Нужно для маппинга
    # колонок ТЧ движений (Инвентаризация.Товары: факт/учёт/отклонение и т.п.).
    try:
        tabs: dict[str, list[str]] = {}
        tcoll = obj.ТабличныеЧасти
        for i in range(tcoll.Количество()):
            t = tcoll.Получить(i)
            tabs[str(t.Имя)] = _names(t.Реквизиты)
        if tabs:
            result["tabulars"] = tabs
    except Exception:
        pass
    return result


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
    # Парсим RAW:<expr> КАК <alias> — берём alias как имя ключа в row
    field_to_attr: list[tuple[str, str]] = []  # (output_key, attr_in_selection)
    import re
    for f in fields:
        if f.startswith("RAW:"):
            body = f[4:].strip()
            m = re.search(r"\s+КАК\s+([A-Za-zА-Яа-я_][A-Za-zА-Яа-я0-9_]*)\s*$", body, re.IGNORECASE)
            if m:
                alias = m.group(1)
                field_to_attr.append((alias, alias))
            # без alias — пропускаем (нет имени для row)
        else:
            field_to_attr.append((f, f))
    rows: list[dict[str, Any]] = []
    while sel.Следующий():
        row: dict[str, Any] = {}
        for out_key, attr in field_to_attr:
            row[out_key] = _val(getattr(sel, attr))
        rows.append(row)
    return rows


def op_find_docs_by_nomenclature(nomenclature_ref: str, limit: int = 50) -> list[dict[str, Any]]:
    """Поиск ПТУ + КорректировкаПоступления где есть данная номенклатура в ТЧ Товары.

    Прямой Запрос в 1С — соединяем ТЧ ПТУ.Товары с шапкой по Ссылке,
    фильтр по Номенклатура = заданный GUID."""
    ib = _require_ib()
    q = ib.NewObject("Запрос")
    q.Текст = (
        f"ВЫБРАТЬ ПЕРВЫЕ {int(limit)} "
        "Т.Ссылка.Ссылка КАК Ссылка, "
        "Т.Ссылка.Номер КАК Номер, "
        "Т.Ссылка.Дата КАК Дата, "
        "Т.Ссылка.Контрагент.Наименование КАК КонтрагентИмя, "
        "Т.Ссылка.Контрагент.ИНН КАК ИНН, "
        "Т.Ссылка.Организация.Наименование КАК ОрганизацияИмя, "
        "Т.Ссылка.СуммаДокумента КАК СуммаДок, "
        "Т.Количество КАК Количество, "
        "Т.Цена КАК Цена, "
        "Т.Сумма КАК Сумма, "
        "\"ПТУ\" КАК ТипДок "
        "ИЗ Документ.ПоступлениеТоваровУслуг.Товары КАК Т "
        "ГДЕ Т.Номенклатура = &Ном "
        "УПОРЯДОЧИТЬ ПО Дата УБЫВ"
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
    # ⚠ В ЭЛСИ.АЗК поле единицы = БазоваяЕдиницаИзмерения (не ЕдиницаИзмерения).
    q.Текст = (
        "ВЫБРАТЬ "
        "Т.Ссылка КАК Ref, "
        "Т.Наименование КАК Name, "
        "ПРЕДСТАВЛЕНИЕ(Т.БазоваяЕдиницаИзмерения) КАК Unit, "
        "Т.Артикул КАК Article, "
        "Т.НаименованиеПолное КАК FullName, "
        "Т.Код КАК Code, "
        "ПРЕДСТАВЛЕНИЕ(Т.ОсновнойПоставщик) КАК Supplier "
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
            "full_name": _val(sel.FullName),
            "code": _val(sel.Code),
            "supplier": _val(sel.Supplier),
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
    # TODO: субконто через AccountingRegisters.Хозрасчетный.CreateRecordSet()
    # — там доступ через Соответствие(ВидСубконто→Значение) независимо от
    # плана счетов. Пока берём минимум — проводки без аналитики (закрывает
    # ~80% сверки: суммы по счетам + инварианты розничной модели §1.4 спеки).
    text_with_subconto = (
        "ВЫБРАТЬ "
        "Р.Период КАК Period, "
        "ПРЕДСТАВЛЕНИЕ(Р.СчетДт) КАК AccountDt, "
        "ПРЕДСТАВЛЕНИЕ(Р.СчетКт) КАК AccountCt, "
        "Р.Сумма КАК Amount, "
        "ПРЕДСТАВЛЕНИЕ(Р.СубконтоДт1) КАК SubcontoDt1, "
        "ПРЕДСТАВЛЕНИЕ(Р.СубконтоДт2) КАК SubcontoDt2, "
        "ПРЕДСТАВЛЕНИЕ(Р.СубконтоДт3) КАК SubcontoDt3, "
        "ПРЕДСТАВЛЕНИЕ(Р.СубконтоКт1) КАК SubcontoCt1, "
        "ПРЕДСТАВЛЕНИЕ(Р.СубконтоКт2) КАК SubcontoCt2, "
        "ПРЕДСТАВЛЕНИЕ(Р.СубконтоКт3) КАК SubcontoCt3 "
        "ИЗ РегистрБухгалтерии.Хозрасчетный КАК Р "
        "ГДЕ Р.Регистратор = &Регистратор"
    )
    text_minimal = (
        "ВЫБРАТЬ "
        "Р.Период КАК Period, "
        "ПРЕДСТАВЛЕНИЕ(Р.СчетДт) КАК AccountDt, "
        "ПРЕДСТАВЛЕНИЕ(Р.СчетКт) КАК AccountCt, "
        "Р.Сумма КАК Amount "
        "ИЗ РегистрБухгалтерии.Хозрасчетный КАК Р "
        "ГДЕ Р.Регистратор = &Регистратор"
    )

    # Пробуем расширенный запрос, при ошибке откатываемся на минимальный.
    fields_extended = ["Period", "AccountDt", "AccountCt", "Amount",
                       "SubcontoDt1", "SubcontoDt2", "SubcontoDt3",
                       "SubcontoCt1", "SubcontoCt2", "SubcontoCt3"]
    fields_minimal = ["Period", "AccountDt", "AccountCt", "Amount"]
    try:
        q.Текст = text_with_subconto
        q.УстановитьПараметр("Регистратор", doc_ref_obj)
        sel = q.Выполнить().Выбрать()
        fields = fields_extended
    except Exception:
        # Поля СубконтоДт/Кт могут отсутствовать (план счетов с общими
        # субконто) — пробуем альтернативные имена.
        try:
            q.Текст = text_with_subconto.replace("СубконтоДт", "Субконто").replace("СубконтоКт", "Субконто")
            # Без раздельных Дт/Кт — оставим только Субконто1..3 один раз.
            q.Текст = (
                "ВЫБРАТЬ "
                "Р.Период КАК Period, "
                "ПРЕДСТАВЛЕНИЕ(Р.СчетДт) КАК AccountDt, "
                "ПРЕДСТАВЛЕНИЕ(Р.СчетКт) КАК AccountCt, "
                "Р.Сумма КАК Amount, "
                "ПРЕДСТАВЛЕНИЕ(Р.Субконто1) КАК Subconto1, "
                "ПРЕДСТАВЛЕНИЕ(Р.Субконто2) КАК Subconto2, "
                "ПРЕДСТАВЛЕНИЕ(Р.Субконто3) КАК Subconto3 "
                "ИЗ РегистрБухгалтерии.Хозрасчетный КАК Р "
                "ГДЕ Р.Регистратор = &Регистратор"
            )
            q.УстановитьПараметр("Регистратор", doc_ref_obj)
            sel = q.Выполнить().Выбрать()
            fields = ["Period", "AccountDt", "AccountCt", "Amount",
                      "Subconto1", "Subconto2", "Subconto3"]
        except Exception:
            q.Текст = text_minimal
            q.УстановитьПараметр("Регистратор", doc_ref_obj)
            sel = q.Выполнить().Выбрать()
            fields = fields_minimal
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


def _xs(ib: Any, ref: Any) -> str:
    """GUID-строка из ссылки (через XMLСтрока — str() COM-UUID не сериализует)."""
    try:
        return str(ib.XMLСтрока(ref.УникальныйИдентификатор()))
    except Exception:
        return ""


def _dt_lit(s: str, end: bool = False) -> str:
    """'2026-06-01' → литерал ДАТАВРЕМЯ(2026,6,1,0,0,0) / (…,23,59,59) для end."""
    d = (s or "").strip()[:10].split("-")
    if len(d) != 3:
        return "2020,1,1,0,0,0"
    tail = "23,59,59" if end else "0,0,0"
    return f"{int(d[0])},{int(d[1])},{int(d[2])},{tail}"


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
            out.append({"НоменклатураUUID": _xs(ib, rr.Номенклатура),
                        "Количество": float(_val(rr.Брутто) or 0)})
        return out
    except Exception:
        return []


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
            "Док.Контрагент КАК Контр ИЗ Документ.ПоступлениеТоваровУслугНаАЗК КАК Док "
            "ГДЕ Док.Склад = &Склад И Док.Дата МЕЖДУ &От И &До "
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
                "Т.Цена КАК Цена, Т.Сумма КАК Сум, Т.СуммаНДС КАК СНДС ИЗ "
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
                })
            out.append({
                "Тип": "purchase", "ИсточникUUID": _xs(ib, s.Ссылка),
                "Номер": str(_val(s.Ном) or "").strip(), "Дата": str(_val(s.Дата)),
                "Контрагент": _xs(ib, s.Контр), "Товары": tovary,
            })
    except Exception:
        return out
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

    # Оплаты — группировка Товары по ФормаОплаты + признак безнала (как .epf)
    oplaty = []
    try:
        qo = ib.NewObject("Запрос")
        qo.Текст = (
            "ВЫБРАТЬ ПРЕДСТАВЛЕНИЕ(Т.ФормаОплаты) КАК Форма, Т.БезналичнаяОплата КАК Безнал, "
            "СУММА(Т.Сумма) КАК Сум ИЗ Документ.ОтчетОРозничныхПродажах.Товары КАК Т "
            "ГДЕ Т.Ссылка = &Д СГРУППИРОВАТЬ ПО ПРЕДСТАВЛЕНИЕ(Т.ФормаОплаты), Т.БезналичнаяОплата"
        )
        qo.УстановитьПараметр("Д", orp.Ссылка)
        so = qo.Выполнить().Выбрать()
        while so.Следующий():
            oplaty.append({
                "ФормаОплаты": str(_val(so.Форма) or "").strip(),
                "БезналичнаяОплата": bool(_val(so.Безнал)),
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
    doc = {
        "Тип": "retail_sale_sidegoods", "ИсточникUUID": _xs(ib, orp.Ссылка),
        "Номер": nomer, "Дата": str(_val(orp.Дата)),
        "СуммаДокумента": float(_val(getattr(orp, "СуммаДокумента", 0)) or 0),
        "Товары": tovary, "Оплаты": oplaty, "ВозвращенныеТовары": vozvraty,
    }
    return {
        "ВерсияФормата": "2",
        "Смена": {
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
    q.Текст = (
        f"ВЫБРАТЬ ПЕРВЫЕ {int(limit)} Т.Ссылка КАК Ссылка ИЗ Документ.ОтчетОРозничныхПродажах КАК Т "
        f"ГДЕ Т.Дата >= ДАТАВРЕМЯ({_dt_lit(period_from)}) И Т.Дата <= ДАТАВРЕМЯ({_dt_lit(period_to, True)}) "
        f'И (Т.Склад.Наименование ПОДОБНО "%{station}%" ИЛИ Т.Подразделение.Наименование ПОДОБНО "%{station}%") '
        f"УПОРЯДОЧИТЬ ПО Т.Дата"
    )
    sel = q.Выполнить().Выбрать()
    packages = []
    while sel.Следующий():
        orp = sel.Ссылка.ПолучитьОбъект()
        if orp.Товары.Количество() == 0:
            continue
        packages.append(_build_shift_package(ib, orp, station))
    return packages


def op_fetch_barcodes(limit: int | None = None) -> list[dict[str, Any]]:
    """Штрихкоды из РегистрСведений.Штрихкоды: Штрихкод + GUID номенклатуры (Владелец).
    fetch_entity не годится (строит запрос под справочник с Т.Ссылка)."""
    ib = _require_ib()
    top = f"ПЕРВЫЕ {int(limit)} " if limit else ""
    q = ib.NewObject("Запрос")
    q.Текст = (
        "ВЫБРАТЬ " + top
        + "Т.Штрихкод КАК Barcode, Н.Ссылка КАК Owner, Н.Наименование КАК OwnerName, "
        + "ПРЕДСТАВЛЕНИЕ(Т.ТипШтрихкода) КАК Type, Т.Основной КАК Main "
        + "ИЗ РегистрСведений.Штрихкоды КАК Т "
        + "ВНУТРЕННЕЕ СОЕДИНЕНИЕ Справочник.Номенклатура КАК Н "
        + "ПО Н.Ссылка = ВЫРАЗИТЬ(Т.Владелец КАК Справочник.Номенклатура) "
        + 'ГДЕ Т.Штрихкод <> ""'
    )
    sel = q.Выполнить().Выбрать()
    rows: list[dict[str, Any]] = []
    while sel.Следующий():
        rows.append({
            "barcode": _val(sel.Barcode),
            "owner": _val(sel.Owner),        # Н.Ссылка — обычная ссылка → GUID номенклатуры
            "owner_name": _val(sel.OwnerName),
            "type": _val(sel.Type),
            "main": _val(sel.Main),
        })
    return rows


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


def op_fetch_recipes(period_from: str, period_to: str, station: str = "208") -> list[dict[str, Any]]:
    """kind=recipe (ТТК блюд для модели B общепита). Зеркалит СобратьRecipe из
    TL_ЭкспортБП: блюда+ТТК — DISTINCT из Документ.ВыпускПродукции.Товары за период
    по складу; ингредиенты — из Документ.ТТК.Товары (ресурс Брутто = валовый расход
    сырья на 1 порцию, только Учитывать). Read-only. Дедуп по блюду."""
    ib = _require_ib()
    if ib.Метаданные.Документы.Найти("ТТК") is None:
        return []
    q = ib.NewObject("Запрос")
    q.Текст = (
        "ВЫБРАТЬ РАЗЛИЧНЫЕ Тов.Номенклатура КАК Блюдо, Тов.Номенклатура.Наименование КАК БлюдоИмя, "
        "Тов.ТТК КАК ТТК ИЗ Документ.ВыпускПродукции.Товары КАК Тов "
        f"ГДЕ Тов.Ссылка.Дата >= ДАТАВРЕМЯ({_dt_lit(period_from)}) "
        f"И Тов.Ссылка.Дата <= ДАТАВРЕМЯ({_dt_lit(period_to, True)}) "
        f'И Тов.Ссылка.Склад.Код = "{station}" И НЕ Тов.Ссылка.ПометкаУдаления'
    )
    sel = q.Выполнить().Выбрать()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    while sel.Следующий():
        блюдо = sel.Блюдо
        if not _val(блюдо):
            continue
        bkey = _xs(ib, блюдо)
        if bkey in seen:
            continue
        ттк = sel.ТТК
        if not _val(ттк):
            continue
        obj = ттк.ПолучитьОбъект()
        if obj is None:
            continue
        ингр: list[dict[str, Any]] = []
        for i in range(obj.Товары.Количество()):
            r = obj.Товары.Получить(i)
            try:
                уч = _val(r.Учитывать)
            except Exception:
                уч = True
            if уч is False:
                continue
            инг = r.Номенклатура
            if not _val(инг):
                continue
            try:
                брутто = float(_val(r.Брутто) or 0)
            except Exception:
                брутто = 0.0
            if брутто == 0:
                continue
            ингр.append({"НоменклатураUUID": _xs(ib, инг), "Количество": брутто})
        if not ингр:
            continue
        seen.add(bkey)
        out.append({
            "Тип": "recipe",
            "ИсточникUUID": _xs(ib, ттк),
            "БлюдоUUID": bkey,
            "БлюдоНаименование": str(_val(sel.БлюдоИмя) or "").strip(),
            "Ингредиенты": ингр,
            "_station": station,
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


def op_fetch_orgs() -> list[dict[str, Any]]:
    """Справочник.Организации → реквизиты для НСИ-секции пакета (Организация
    ищется приёмником по ИНН, не автосоздаётся). Поля ЭЛСИ.АЗК: ИНН/КПП/
    НаименованиеПолное/ОГРН/КодПоОКПО/ЮрФизЛицо."""
    ib = _require_ib()
    q = ib.NewObject("Запрос")
    q.Текст = (
        "ВЫБРАТЬ Т.Ссылка КАК Ref, Т.Наименование КАК Name, Т.НаименованиеПолное КАК FullName, "
        "Т.ИНН КАК ИНН, Т.КПП КАК КПП, Т.ОГРН КАК ОГРН, Т.КодПоОКПО КАК ОКПО, "
        "ПРЕДСТАВЛЕНИЕ(Т.ЮрФизЛицо) КАК ЮрФизЛицо, Т.ПометкаУдаления КАК Del "
        "ИЗ Справочник.Организации КАК Т"
    )
    sel = q.Выполнить().Выбрать()
    rows: list[dict[str, Any]] = []
    while sel.Следующий():
        rows.append({
            "ref": _xs(ib, sel.Ref), "name": _val(sel.Name), "full_name": _val(sel.FullName),
            "inn": _val(sel.ИНН), "kpp": _val(sel.КПП), "ogrn": _val(sel.ОГРН),
            "okpo": _val(sel.ОКПО), "jur_fiz": _val(sel.ЮрФизЛицо), "deleted": bool(_val(sel.Del)),
        })
    return rows


def op_fetch_warehouses() -> list[dict[str, Any]]:
    """Справочник.Склады → код/имя/ВидСклада для НСИ-секции пакета (Склад
    ищется приёмником по UUID/номеру АЗС, не автосоздаётся)."""
    ib = _require_ib()
    q = ib.NewObject("Запрос")
    q.Текст = (
        "ВЫБРАТЬ Т.Ссылка КАК Ref, Т.Код КАК Code, Т.Наименование КАК Name, "
        "ПРЕДСТАВЛЕНИЕ(Т.ВидСклада) КАК ВидСклада, Т.ПометкаУдаления КАК Del "
        "ИЗ Справочник.Склады КАК Т"
    )
    sel = q.Выполнить().Выбрать()
    rows: list[dict[str, Any]] = []
    while sel.Следующий():
        rows.append({
            "ref": _xs(ib, sel.Ref), "code": str(_val(sel.Code) or "").strip(),
            "name": _val(sel.Name), "kind": _val(sel.ВидСклада), "deleted": bool(_val(sel.Del)),
        })
    return rows


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
            elif op == "metadata_registers":
                result = op_metadata_registers(**args)
            elif op == "metadata_documents":
                result = op_metadata_documents(**args)
            elif op == "metadata_accum_registers":
                result = op_metadata_accum_registers(**args)
            elif op == "fetch_register_balance":
                result = op_fetch_register_balance(**args)
            elif op == "query_tabular":
                result = op_query_tabular(**args)
            elif op == "fetch_entity":
                result = op_fetch_entity(**args)
            elif op == "describe_entity":
                result = op_describe_entity(**args)
            elif op == "count_entity":
                result = op_count_entity(**args)
            elif op == "fetch_doc_lines":
                result = op_fetch_doc_lines(**args)
            elif op == "fetch_cb_shifts":
                result = op_fetch_cb_shifts(**args)
            elif op == "find_docs_by_nomenclature":
                result = op_find_docs_by_nomenclature(**args)
            elif op == "fetch_postings":
                result = op_fetch_postings(**args)
            elif op == "enrich_nomenclature":
                result = op_enrich_nomenclature(**args)
            elif op == "fetch_barcodes":
                result = op_fetch_barcodes(**args)
            elif op == "fetch_orgs":
                result = op_fetch_orgs()
            elif op == "fetch_warehouses":
                result = op_fetch_warehouses()
            elif op == "fetch_production":
                result = op_fetch_production(**args)
            elif op == "fetch_gain":
                result = op_fetch_gain(**args)
            elif op == "fetch_recipes":
                result = op_fetch_recipes(**args)
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
