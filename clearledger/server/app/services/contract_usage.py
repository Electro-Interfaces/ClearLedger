"""Где используется договор — по фактическим ссылкам из приложений.

Договор — один на пространство, приложения на него ссылаются. Ответ на «где он
используется» нужен в двух местах: в карточке договора (переход в приложение) и
при удалении — договор со ссылками не стирается, а закрывается, как пометка
удаления в 1С: иначе расчёты станции молча теряют договор (`SET NULL`).

Каждая строка — приложение (код из реестра `eco_apps`), подпись и запрос-счётчик.
Таблицы есть во всех стеках (схема общая), поэтому без проверок существования.
Проводки (`gl_turnovers`) не опрашиваются: индекса по договору нет, а в бухгалтерских
стеках таблица в миллионы строк — проводка всё равно стоит на первичном документе.
"""
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# (приложение, подпись, SQL с параметром :cid — id договора)
_SOURCES: list[tuple[str, str, str]] = [
    ("ops", "Расчёты станций", "SELECT count(*) FROM station_contract_settlements WHERE contract_id = :cid"),
    ("ops", "Условия «Хозяйства»", "SELECT count(*) FROM ops_contract_terms WHERE contract_id = :cid"),
    ("ops", "Начисления «Хозяйства»", "SELECT count(*) FROM ops_period_charges WHERE contract_id = :cid"),
    ("ops", "Документы контрагента «Хозяйства»", "SELECT count(*) FROM ops_counterparty_docs WHERE contract_id = :cid"),
    ("ops", "Приборы учёта", "SELECT count(*) FROM ops_meters WHERE contract_id = :cid"),
    ("ops", "Документы оборудования", "SELECT count(*) FROM ezs_equipment_documents WHERE contract_id = :cid"),
    ("ops", "Поставки оборудования", "SELECT count(*) FROM ezs_supply_documents WHERE contract_id = :cid"),
    ("projects", "Площадки и проекты", "SELECT count(*) FROM ezs_sites WHERE contract_id = :cid"),
    ("projects", "Проекты площадок", "SELECT count(*) FROM ezs_projects WHERE contract_id = :cid"),
    ("projects", "Интеграции",
     "SELECT count(*) FROM ezs_sites WHERE workspace_data->'integration'->'contractIds' ? :cs"),
    ("docs", "Документы «Трека»", "SELECT count(*) FROM doc_cards WHERE subject_ref = 'contract:' || :cs"),
    ("shop", "Приёмки магазина", "SELECT count(*) FROM store_receipts WHERE contract_id = :cid"),
    ("books", "Первичные документы", "SELECT count(*) FROM accounting_docs WHERE contract_id = :cid"),
    ("books", "Входящие документы", "SELECT count(*) FROM intake_items WHERE contract_id = :cid"),
    ("mail", "Правила почты", "SELECT count(*) FROM mail_rules WHERE set_contract_id = :cid"),
]


async def contract_usage(db: AsyncSession, contract_id: uuid.UUID) -> list[dict]:
    """[{app, label, count}] — только непустые источники."""
    out = []
    for app, label, sql in _SOURCES:
        n = (await db.execute(text(sql), {"cid": contract_id, "cs": str(contract_id)})).scalar() or 0
        if n:
            out.append({"app": app, "label": label, "count": int(n)})
    return out
