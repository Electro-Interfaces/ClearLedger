"""Где используется договор — по фактическим ссылкам из приложений.

Договор — один на пространство, приложения на него ссылаются. Ответ на «где он
используется» нужен в трёх местах: в карточке договора (переход в приложение), при
удалении — договор со ссылками не стирается, а закрывается, как пометка удаления в 1С
(иначе расчёты станции молча теряют договор: `SET NULL`), — и в списке договоров:
«договоры приложения» = привязанные к нему (`contract_links`) ∪ используемые им.

Источник — приложение (код из реестра `eco_apps`), подпись и выражение «строки,
ссылающиеся на договор» с колонкой `cid`. Контур «Поддержки» необязателен:
его таблицу создают миграции соседнего приложения, а не ядра.
Проводки (`gl_turnovers`) не опрашиваются: индекса по договору нет, а в бухгалтерских
стеках таблица в миллионы строк — проводка всё равно стоит на первичном документе.
"""
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _col(table: str, col: str = "contract_id") -> str:
    return f"SELECT {col} AS cid FROM {table} WHERE {col} IS NOT NULL"


def _subject(table: str, column: str = "subject_ref") -> str:
    # Сравнение строк, без приведения произвольной ссылки к UUID: старое или
    # незаполненное значение не должно ломать весь список договоров.
    return (f"SELECT c.id AS cid FROM {table} r JOIN contracts c"
            f" ON r.{column} = 'contract:' || c.id::text"
            " AND r.company_id = c.company_id")


# Основная карточка и бумаги договора — разные способы связи. UNION по паре
# (договор, документ) учитывает бумагу один раз, даже если есть обе связи.
_DOCUMENTS = """
    SELECT cid FROM (
        SELECT c.id AS cid, d.id AS doc_id FROM doc_cards d JOIN contracts c
          ON d.company_id = c.company_id AND d.subject_ref = 'contract:' || c.id::text
        UNION
        SELECT c.id, d.id FROM doc_relations r
          JOIN doc_cards d ON d.id = r.doc_id AND d.company_id = r.company_id
          JOIN contracts c ON c.company_id = r.company_id
            AND r.target_ref = 'contract:' || c.id::text
        UNION
        SELECT c.id, d.id FROM doc_cards d JOIN contracts c
          ON d.company_id = c.company_id AND d.attrs->>'contract_id' = c.id::text
    ) documents
"""


# (приложение, подпись, SELECT … AS cid — по строке на ссылку)
_SOURCES: list[tuple[str, str, str]] = [
    ("ops", "Расчёты станций", _col("station_contract_settlements")),
    ("ops", "Условия «Хозяйства»", _col("ops_contract_terms")),
    ("ops", "Начисления «Хозяйства»", _col("ops_period_charges")),
    ("ops", "Документы контрагента «Хозяйства»", _col("ops_counterparty_docs")),
    ("ops", "Приборы учёта", _col("ops_meters")),
    ("ops", "Документы оборудования", _col("ezs_equipment_documents")),
    ("ops", "Поставки оборудования", _col("ezs_supply_documents")),
    ("ops", "Документы ЗИП и материалов", _col("ezs_spare_documents")),
    # Договор аренды или хранения склада лежит в карточке склада (реквизиты точки).
    ("ops", "Склады оборудования",
     "SELECT c.id AS cid FROM service_locations l JOIN contracts c"
     " ON c.id::text = l.extra_metadata->'warehouse'->>'contractId' WHERE l.type = 'warehouse'"),
    ("projects", "Площадки и проекты", _col("ezs_sites")),
    ("projects", "Проекты площадок", _col("ezs_projects")),
    ("projects", "Интеграции",
     "SELECT c.id AS cid FROM ezs_sites s"
     " CROSS JOIN jsonb_array_elements_text(COALESCE(s.workspace_data->'integration'->'contractIds', '[]'::jsonb)) x"
     " JOIN contracts c ON c.id::text = x"),
    ("docs", "Документы «Трека»", _DOCUMENTS),
    ("docs", "Поручения по договору", _subject("tasks")),
    ("docs", "Календарь по договору", _subject("calendar_events")),
    ("docs", "Напоминания по договору", _subject("personal_reminders", "target_ref")),
    ("core", "Основания участия людей",
     "SELECT c.id AS cid FROM user_companies u JOIN contracts c"
     " ON c.company_id = u.company_id AND u.contract_ids @> jsonb_build_array(c.id::text)"),
    ("core", "Адресный охват договора", _col("contract_locations")),
    ("core", "Аналитика договора", _col("contract_dimensions")),
    ("market", "Предложения по договору", _subject("market_growth_leads")),
    ("core", "Обсуждения с партнёрами", _subject("eco_partner_topics")),
    ("core", "Сообщения партнёров", _subject("eco_partner_messages")),
    ("conf", "Встречи по договору", _subject("conf_sessions")),
    ("shop", "Приёмки магазина", _col("store_receipts")),
    ("books", "Первичные документы", _col("accounting_docs")),
    ("books", "Входящие документы", _col("intake_items")),
    ("mail", "Правила почты", _col("mail_rules", "set_contract_id")),
]


async def _service_contract_alias(db: AsyncSession) -> str | None:
    """Только доказанный полный alias другой service_contracts; UNKNOWN → None.

    Зависимость сама по себе не доказывает равенство строк. Принимаем ровно
    deparse полной прямой проекции, построенной из каталога физической таблицы.
    Любая другая форма, RLS или options сохраняют прежний отдельный источник.
    """
    rows = (await db.execute(text("""
        SELECT nv.nspname || '.' || v.relname AS alias,
               pg_catalog.pg_get_viewdef(v.oid, false) AS definition,
               'SELECT ' || (
                   SELECT string_agg('service_contracts.' || pg_catalog.quote_ident(a.attname),
                                     ', ' ORDER BY a.attnum)
                   FROM pg_catalog.pg_attribute a
                   WHERE a.attrelid = b.oid AND a.attnum > 0 AND NOT a.attisdropped
               ) || ' FROM ' || CASE WHEN pg_catalog.pg_table_is_visible(b.oid)
                   THEN 'service_contracts' ELSE nb.nspname || '.service_contracts'
               END || ';' AS expected
        FROM pg_catalog.pg_class v
        JOIN pg_catalog.pg_namespace nv ON nv.oid = v.relnamespace
        JOIN pg_catalog.pg_class b ON b.oid = pg_catalog.to_regclass(
            CASE nv.nspname WHEN 'core' THEN 'public.service_contracts'
                            WHEN 'public' THEN 'core.service_contracts' END)
        JOIN pg_catalog.pg_namespace nb ON nb.oid = b.relnamespace
        JOIN pg_catalog.pg_rewrite r ON r.ev_class = v.oid
            AND r.rulename = '_RETURN' AND r.ev_type = '1' AND r.is_instead
        WHERE v.relname = 'service_contracts' AND nv.nspname IN ('core', 'public')
          AND v.relkind = 'v' AND b.relkind = 'r' AND NOT b.relispartition
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_inherits i
              WHERE i.inhparent = b.oid OR i.inhrelid = b.oid
          )
          AND NOT b.relrowsecurity AND NOT b.relforcerowsecurity
          AND NOT v.relrowsecurity AND NOT v.relforcerowsecurity
          AND COALESCE(cardinality(v.reloptions), 0) = 0
          AND COALESCE(cardinality(b.reloptions), 0) = 0
          AND EXISTS (
              SELECT 1 FROM pg_catalog.pg_depend d
              WHERE d.classid = 'pg_catalog.pg_rewrite'::pg_catalog.regclass
                AND d.objid = r.oid AND d.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
                AND d.refobjid = b.oid
          )
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_depend d
              WHERE d.classid = 'pg_catalog.pg_rewrite'::pg_catalog.regclass
                AND d.objid = r.oid AND d.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
                AND d.refobjid NOT IN (v.oid, b.oid)
          )
          AND EXISTS (
              SELECT 1 FROM pg_catalog.pg_attribute a
              WHERE a.attrelid = b.oid AND a.attname = 'id'
                AND a.attnum > 0 AND NOT a.attisdropped
          )
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_attribute a
              WHERE a.attrelid = b.oid AND a.attnum > 0 AND NOT a.attisdropped
                AND a.attname !~ '^[a-z_][a-z0-9_]*$'
          )
          AND ARRAY(SELECT a.attname FROM pg_catalog.pg_attribute a
                    WHERE a.attrelid = v.oid AND a.attnum > 0 AND NOT a.attisdropped
                    ORDER BY a.attnum)
            = ARRAY(SELECT a.attname FROM pg_catalog.pg_attribute a
                    WHERE a.attrelid = b.oid AND a.attnum > 0 AND NOT a.attisdropped
                    ORDER BY a.attnum)
    """))).mappings().all()
    if len(rows) == 1:
        row = rows[0]
        if row["definition"] and row["expected"]:
            # Две точные формы одного списка колонок: deparser может опустить
            # префикс единственной таблицы. Меняем только сгенерированный эталон;
            # SQL view не переписываем. Имена колонок выше ограничены ASCII.
            expected = row["expected"]
            bare = expected.replace("service_contracts.", "")
            if " ".join(row["definition"].split()) in (expected, bare):
                return row["alias"]
    return None


async def _sources(db: AsyncSession) -> list[tuple[str, str, str]]:
    sources = list(_SOURCES)
    # В одной БД могут остаться обе поставки. Миграция116 добавляет ссылку
    # активной таблице (core имеет приоритет); старая public может существовать
    # без contract_id. Такая таблица не является источником UUID-связей.
    # Проверяем колонку до запроса, не прерывая транзакцию и не подбирая договор
    # по строковому номеру. Имена схем остаются явными и при проверке, и при чтении.
    support_tables = []
    for table in ("core.service_contracts", "public.service_contracts"):
        if await db.scalar(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_attribute
                WHERE attrelid = to_regclass(:table) AND attname = 'contract_id'
                  AND attnum > 0 AND NOT attisdropped
            )
        """), {"table": table}):
            support_tables.append(table)
    alias = await _service_contract_alias(db) if len(support_tables) == 2 else None
    for table in support_tables:
        if table != alias:
            sources.append(("support", "Сервисные договоры «Поддержки»", _col(table)))
    return sources


# Проект, в котором договор используется по факту: площадка «Проектов».
_PROJECT_USAGE = """
    SELECT contract_id AS cid, 'site:' || id::text AS ref FROM ezs_sites WHERE contract_id IS NOT NULL
    UNION SELECT contract_id, 'site:' || site_id::text FROM ezs_projects WHERE contract_id IS NOT NULL AND site_id IS NOT NULL
    UNION SELECT c.id, 'site:' || s.id::text FROM ezs_sites s
        CROSS JOIN jsonb_array_elements_text(COALESCE(s.workspace_data->'integration'->'contractIds', '[]'::jsonb)) x
        JOIN contracts c ON c.id::text = x
"""


async def contract_usage(db: AsyncSession, contract_id: uuid.UUID) -> list[dict]:
    """[{app, label, count}] — только непустые источники."""
    out = []
    for app, label, sql in await _sources(db):
        n = (await db.execute(text(f"SELECT count(*) FROM ({sql}) u WHERE u.cid = :cid"), {"cid": contract_id})).scalar() or 0
        if n:
            out.append({"app": app, "label": label, "count": int(n)})
    for app, count in (await db.execute(text(
        "SELECT app_code, count(*) FROM contract_links WHERE contract_id = :cid GROUP BY app_code"
    ), {"cid": contract_id})).all():
        out.append({"app": app, "label": "Явные привязки к приложению и проектам", "count": int(count)})
    return out


async def usage_by_contract(db: AsyncSession, company_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    """Сводка по всем договорам компании: {contract_id: {"apps": set, "projects": set}}.

    Один запрос на источник с группировкой — а не 15 запросов на каждый из 900 договоров.
    """
    out: dict[uuid.UUID, dict] = {}
    scope = "u.cid IN (SELECT id FROM contracts WHERE company_id = :co)"
    for app, _label, sql in await _sources(db):
        for (cid,) in (await db.execute(text(f"SELECT DISTINCT u.cid FROM ({sql}) u WHERE {scope}"), {"co": company_id})).all():
            out.setdefault(cid, {"apps": set(), "projects": set()})["apps"].add(app)
    for cid, ref in (await db.execute(text(f"SELECT u.cid, u.ref FROM ({_PROJECT_USAGE}) u WHERE {scope}"), {"co": company_id})).all():
        out.setdefault(cid, {"apps": set(), "projects": set()})["projects"].add(ref)
    for cid, app, ref in (await db.execute(text(
        "SELECT contract_id, app_code, project_ref FROM contract_links WHERE company_id = :co"
    ), {"co": company_id})).all():
        item = out.setdefault(cid, {"apps": set(), "projects": set()})
        item["apps"].add(app)
        if ref:
            item["projects"].add(ref)
    return out
