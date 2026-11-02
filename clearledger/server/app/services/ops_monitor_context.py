from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select, text

from app.services.session_scope import station_locations_sql

MSK = timezone(timedelta(hours=3))


def session_time_iso(value):
    """Время сессии в БД — МСК без tz; в API всегда передаём смещение явно."""
    if value is None:
        return None
    return (value.replace(tzinfo=MSK) if value.tzinfo is None else value.astimezone(MSK)).isoformat()


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


async def monitor_locations(db, company_id, location_ids=None, station_codes=None):
    locations = {x for x in location_ids.split('|') if x} if location_ids else None
    if station_codes:
        rows = await db.execute(text('SELECT unnest(' + station_locations_sql() + ')::text'),
                                {'stations': station_codes.split('|'), 'company_id': str(company_id)})
        selected = set(rows.scalars().all())
        locations = selected if locations is None else locations & selected
    return locations


async def visit_summary(db, company_id, start, end, *, location_ids=None):
    # None preserves the native company-wide contract; EMPTY must stay empty.
    # Apply the object ceiling in attempts, before visit grouping/counting.
    location_filter = " AND location_id = ANY(CAST(:location_ids AS text[]))" if location_ids is not None else ""
    rows = (await db.execute(text("""
        WITH attempts AS (
            SELECT location_id, coalesce(visit_key, 'session:' || id::text) AS key,
                   user_id, energy_kwh
            FROM charge_sessions
            WHERE company_id=:company AND started_at >= :start AND started_at <= :end
              AND location_id IS NOT NULL
        """ + location_filter + """
        ), visits AS (
            SELECT location_id, key, bool_or(energy_kwh>0) AS charged
            FROM attempts GROUP BY location_id, key
        )
        SELECT v.location_id, count(DISTINCT v.key) AS visits,
               count(DISTINCT v.key) FILTER(WHERE v.charged) AS ok,
               count(DISTINCT a.user_id) FILTER(WHERE NOT v.charged) AS lost
        FROM visits v JOIN attempts a USING(location_id,key)
        GROUP BY v.location_id
    """), {"company": company_id, "start": start, "end": end,
           **({"location_ids": sorted(location_ids)} if location_ids is not None else {})})).mappings().all()
    return {r["location_id"]: dict(r) for r in rows}


def _session_conditions(company_id, location_ids):
    from app.models import ChargeSession
    conditions = [ChargeSession.company_id == company_id]
    if location_ids is not None:
        conditions.append(ChargeSession.location_id.in_(location_ids))
    return conditions


async def session_boundary(db, company_id, *, location_ids=None, through=None):
    """Object-scoped observed data boundary, never a company-wide watermark."""
    from app.models import ChargeSession
    conditions = _session_conditions(company_id, location_ids)
    if through is not None:
        conditions.append(ChargeSession.started_at <= through)
    return await db.scalar(select(func.max(ChargeSession.started_at)).where(*conditions))


async def session_summary(db, company_id, start, end, *, location_ids=None):
    """Read-only non-financial totals; round only after summing raw energy."""
    from app.models import ChargeSession
    sessions, energy = (await db.execute(select(
        func.count(), func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
    ).where(*_session_conditions(company_id, location_ids),
            ChargeSession.started_at >= start, ChargeSession.started_at <= end))).one()
    return {"sessions": int(sessions), "energyKwh": decimal_round(energy)}
