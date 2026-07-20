"""Материализованная витрина L3 для аналитики ЭЗС (Ф3).

Грейн: company_id × day × location_id × connector_type × user_type — аддитивные
метрики сессий (без визитов: они неаддитивны по коннектору). Регион/станция и
любые измерения справочника резолвятся JOIN'ом при ЧТЕНИИ (Ф1.3: справочник —
единственный источник истины по измерениям), в витрине хранится только факт.

Витрина создаётся лениво (CREATE TABLE IF NOT EXISTS) — без миграции в models/
database (не пересекаясь с параллельной работой над схемой). Обновляется АТОМАРНО
в конце ingest сессий (в той же транзакции, что данные+bump_version).

Выручка = coalesce(client_amount, amount) — как в analytics_service._cs_aggregate
(у ЮЛ amount=0, реальная выручка в client_amount).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory

_mart_ready = False

_DDL = """
CREATE TABLE IF NOT EXISTS mv_charge_daily (
    company_id      uuid        NOT NULL,
    day             date        NOT NULL,
    location_id     varchar(40) NOT NULL DEFAULT '',
    connector_type  varchar(40) NOT NULL DEFAULT '',
    user_type       varchar(20) NOT NULL DEFAULT '',
    sessions        integer     NOT NULL DEFAULT 0,
    energy_kwh      numeric     NOT NULL DEFAULT 0,
    revenue         numeric     NOT NULL DEFAULT 0,
    duration_min    numeric     NOT NULL DEFAULT 0,
    success         integer     NOT NULL DEFAULT 0,
    charged         integer     NOT NULL DEFAULT 0,
    cnt_retail      integer     NOT NULL DEFAULT 0,
    paid_retail     integer     NOT NULL DEFAULT 0,
    PRIMARY KEY (company_id, day, location_id, connector_type, user_type)
)
"""

# Пересчёт грейна из факта. coalesce к '' — PK не допускает NULL; при чтении
# пустая строка трактуется как «не заполнено».
_REBUILD_INSERT = """
INSERT INTO mv_charge_daily
    (company_id, day, location_id, connector_type, user_type,
     sessions, energy_kwh, revenue, duration_min, success, charged, cnt_retail, paid_retail)
SELECT company_id,
       CAST(started_at AS date) AS day,
       coalesce(location_id, ''),
       coalesce(connector_type, ''),
       coalesce(user_type, ''),
       count(*),
       coalesce(sum(energy_kwh), 0),
       coalesce(sum(coalesce(client_amount, amount)), 0),
       coalesce(sum(duration_min), 0),
       coalesce(sum(CASE WHEN result = 'Complete' THEN 1 ELSE 0 END), 0),
       coalesce(sum(CASE WHEN energy_kwh > 0 THEN 1 ELSE 0 END), 0),
       coalesce(sum(CASE WHEN user_type IS DISTINCT FROM 'ЮЛ' THEN 1 ELSE 0 END), 0),
       coalesce(sum(CASE WHEN paid_at IS NOT NULL AND user_type IS DISTINCT FROM 'ЮЛ' THEN 1 ELSE 0 END), 0)
  FROM charge_sessions
 WHERE company_id = :cid AND started_at IS NOT NULL
 GROUP BY company_id, CAST(started_at AS date),
          coalesce(location_id, ''), coalesce(connector_type, ''), coalesce(user_type, '')
"""


async def ensure_mart() -> None:
    """Ленивое создание витрины (раз на процесс) в ОТДЕЛЬНОЙ транзакции. Отдельно от
    ingest: иначе откат ingest (Ф1.1) снял бы CREATE, а флаг остался бы взведён →
    следующий rebuild упал бы на отсутствующей таблице. CREATE IF NOT EXISTS идемпотентен."""
    global _mart_ready
    if _mart_ready:
        return
    async with async_session_factory() as w:
        await w.execute(text(_DDL))
        await w.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_mv_charge_daily_company_day"
            " ON mv_charge_daily (company_id, day)"))
        await w.commit()
    _mart_ready = True


async def rebuild_mart(db: AsyncSession, company_id) -> int:
    """Полный пересчёт витрины компании из факта. Вызывать в конце ingest В ТОЙ ЖЕ
    транзакции (коммитит вызывающий через bump_version) — витрина и данные становятся
    видны атомарно. 122k строк → грейн быстро; DELETE+INSERT в одной txn."""
    await ensure_mart()
    await db.execute(text("DELETE FROM mv_charge_daily WHERE company_id = :cid"),
                     {"cid": str(company_id)})
    res = await db.execute(text(_REBUILD_INSERT), {"cid": str(company_id)})
    return int(res.rowcount or 0)
