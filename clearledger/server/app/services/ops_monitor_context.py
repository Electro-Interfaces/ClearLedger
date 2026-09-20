from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text

MSK = timezone(timedelta(hours=3))


def decimal_round(value, places=1):
    return float(Decimal(str(value or 0)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP))


def monitor_context(boundary, as_of=None, now=None):
    now = (now or datetime.now(MSK)).astimezone(MSK).replace(tzinfo=None)
    point = boundary or now
    if as_of is not None:
        point = min(point, datetime.combine(as_of, datetime.max.time()))
    return point, {
        "asOf": point.replace(tzinfo=MSK).isoformat(),
        "dataThrough": boundary.replace(tzinfo=MSK).isoformat() if boundary else None,
        "dataLagHours": max(0, round((now - boundary).total_seconds() / 3600, 1)) if boundary else None,
        "requestedDate": as_of.isoformat() if as_of else None,
        "catalogMode": "current",
        "snapshotNote": "Сессии — на выбранный день (МСК). Состав парка и паспортные статусы — текущие; история состава не восстановлена.",
    }


def region_matches(value, selection):
    return not selection or (value or "— регион не указан") in selection.split("|")


async def visit_summary(db, company_id, start, end):
    rows = (await db.execute(text("""
        WITH attempts AS (
            SELECT location_id, coalesce(visit_key, 'session:' || id::text) AS key,
                   user_id, energy_kwh
            FROM charge_sessions
            WHERE company_id=:company AND started_at >= :start AND started_at <= :end
              AND location_id IS NOT NULL
        ), visits AS (
            SELECT location_id, key, bool_or(energy_kwh>0) AS charged
            FROM attempts GROUP BY location_id, key
        )
        SELECT v.location_id, count(DISTINCT v.key) AS visits,
               count(DISTINCT v.key) FILTER(WHERE v.charged) AS ok,
               count(DISTINCT a.user_id) FILTER(WHERE NOT v.charged) AS lost
        FROM visits v JOIN attempts a USING(location_id,key)
        GROUP BY v.location_id
    """), {"company": company_id, "start": start, "end": end})).mappings().all()
    return {r["location_id"]: dict(r) for r in rows}
