"""Где используется договор — по фактическим ссылкам из приложений.

Договор — один на пространство, приложения на него ссылаются. Ответ на «где он
используется» нужен в трёх местах: в карточке договора (переход в приложение), при
удалении — договор со ссылками не стирается, а закрывается, как пометка удаления в 1С
(иначе расчёты станции молча теряют договор: `SET NULL`), — и в списке договоров:
«договоры приложения» = привязанные к нему (`contract_links`) ∪ используемые им.

Источник — приложение (код из реестра `eco_apps`), подпись и выражение «строки,
ссылающиеся на договор» с колонкой `cid`. Таблицы есть во всех стеках (схема общая).
Проводки (`gl_turnovers`) не опрашиваются: индекса по договору нет, а в бухгалтерских
стеках таблица в миллионы строк — проводка всё равно стоит на первичном документе.
"""
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _col(table: str, col: str = "contract_id") -> str:
    return f"SELECT {col} AS cid FROM {table} WHERE {col} IS NOT NULL"


# (приложение, подпись, SELECT … AS cid — по строке на ссылку)
_SOURCES: list[tuple[str, str, str]] = [
    ("ops", "Расчёты станций", _col("station_contract_settlements")),
    ("ops", "Условия «Хозяйства»", _col("ops_contract_terms")),
    ("ops", "Начисления «Хозяйства»", _col("ops_period_charges")),
    ("ops", "Документы контрагента «Хозяйства»", _col("ops_counterparty_docs")),
    ("ops", "Приборы учёта", _col("ops_meters")),
    ("ops", "Документы оборудования", _col("ezs_equipment_documents")),
    ("ops", "Поставки оборудования", _col("ezs_supply_documents")),
    ("projects", "Площадки и проекты", _col("ezs_sites")),
    ("projects", "Проекты площадок", _col("ezs_projects")),
    ("projects", "Интеграции",
     "SELECT c.id AS cid FROM ezs_sites s"
     " CROSS JOIN jsonb_array_elements_text(COALESCE(s.workspace_data->'integration'->'contractIds', '[]'::jsonb)) x"
     " JOIN contracts c ON c.id::text = x"),
    ("docs", "Документы «Трека»",
     "SELECT c.id AS cid FROM doc_cards d JOIN contracts c ON d.subject_ref = 'contract:' || c.id::text"),
    ("shop", "Приёмки магазина", _col("store_receipts")),
    ("books", "Первичные документы", _col("accounting_docs")),
    ("books", "Входящие документы", _col("intake_items")),
    ("mail", "Правила почты", _col("mail_rules", "set_contract_id")),
    # Договор обслуживания «Поддержки» (SLA, заявки) ссылается на договор пространства.
    ("support", "Сервисные договоры «Поддержки»", _col("service_contracts")),
]

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
    for app, label, sql in _SOURCES:
        n = (await db.execute(text(f"SELECT count(*) FROM ({sql}) u WHERE u.cid = :cid"), {"cid": contract_id})).scalar() or 0
        if n:
            out.append({"app": app, "label": label, "count": int(n)})
    return out


async def usage_by_contract(db: AsyncSession, company_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    """Сводка по всем договорам компании: {contract_id: {"apps": set, "projects": set}}.

    Один запрос на источник с группировкой — а не 15 запросов на каждый из 900 договоров.
    """
    out: dict[uuid.UUID, dict] = {}
    scope = "u.cid IN (SELECT id FROM contracts WHERE company_id = :co)"
    for app, _label, sql in _SOURCES:
        for (cid,) in (await db.execute(text(f"SELECT DISTINCT u.cid FROM ({sql}) u WHERE {scope}"), {"co": company_id})).all():
            out.setdefault(cid, {"apps": set(), "projects": set()})["apps"].add(app)
    for cid, ref in (await db.execute(text(f"SELECT u.cid, u.ref FROM ({_PROJECT_USAGE}) u WHERE {scope}"), {"co": company_id})).all():
        out.setdefault(cid, {"apps": set(), "projects": set()})["projects"].add(ref)
    return out
