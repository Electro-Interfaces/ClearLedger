"""Почасовая занятость: объединение полуоткрытых интервалов физических портов.

Времена источника — naive МСК. Local сдвигает и интервалы, и границы дня.
Длительность, энергия, результат и оплата не заменяют фактический интервал.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Mapping
from uuid import UUID

from sqlalchemy import String, and_, bindparam, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession as S, Region as R, ServiceLocation as L
from app.scope import current_object_scope, scope_location_conds
from app.services.analytics_service import AnalyticsService, PeriodFilter
from app.services.ops_monitor_context import session_time_iso
from app.services.session_scope import station_locations_sql


def physical_id(station_id: str, connector_no: str) -> str:
    return f"{station_id}:{connector_no}"


def _merged(intervals: list[tuple[datetime, datetime]]):
    """Сначала объединить, затем нарезать: два порта не удваивают станцию."""
    end = start = None
    for lo, hi in sorted(intervals):
        if end is None:
            start, end = lo, hi
        elif lo <= end:
            end = max(end, hi)
        else:
            yield start, end
            start, end = lo, hi
    if end is not None:
        yield start, end


def calculate_hourly_occupancy(
    stations: list[dict[str, Any]], connectors: list[dict[str, Any]],
    sessions: Iterable[Mapping[str, Any]], date_from: date, date_to: date,
    *, tz: str = "msk", group_by: str = "auto",
    connector_types: list[str] | None = None, connector_ids: list[str] | None = None,
    last_session_at: datetime | None = None,
    available_connector_types: list[str] | None = None,
    physical_connector_types: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Чистый расчёт; sessions уже сужены компанией, контуром и dim.

    Каталог — вся история контура, независимо от двух собственных фильтров.
    Пустой JSON-массив connector_ids означает отсутствие сужения (как CSV).
    Непривязанные сессии учитываются только в quality; без номера порта
    валидный интервал участвует в станции, если нет отбора физических портов.
    """
    if date_to < date_from or date_to == date.max:
        raise ValueError("Некорректный период")
    if tz not in ("msk", "local") or group_by not in ("auto", "station", "connector"):
        raise ValueError("Некорректный часовой пояс или разрез")
    grouping = ("connector" if len(stations) == 1 else "station") if group_by == "auto" else group_by
    station_map = {s["station_id"]: s for s in stations}
    types, ids = set(connector_types or []), set(connector_ids or [])
    port_types = physical_connector_types or {}
    selected = [c for c in connectors if (not types or types.intersection(
        port_types.get(c["id"], {c["connector_type"]})))
                and (not ids or c["id"] in ids)]
    selected_stations = {c["station_id"] for c in selected}
    series = {}
    available = 60 * ((date_to - date_from).days + 1)
    descriptors = selected if grouping == "connector" else [
        dict(s, id=s["station_id"], connector_no=None, connector_type=None)
        for s in stations if not ids or s["station_id"] in selected_stations
    ]
    for descriptor in descriptors:
        # msk_offset — служебный атрибут станции, в ответ не попадает.
        series[descriptor["id"]] = {
            k: v for k, v in descriptor.items() if k != "msk_offset"
        } | {"points": [dict(hour=h, occupied_minutes=0.0, available_minutes=available,
                           occupancy_pct=0.0, starts=0) for h in range(24)]}
    intervals = defaultdict(list)
    lo = datetime.combine(date_from, time.min)
    hi = datetime.combine(date_to + timedelta(days=1), time.min)
    quality = dict(missing_interval_sessions=0, missing_connector_sessions=0,
                   unmapped_station_sessions=0,
                   last_session_at=session_time_iso(last_session_at))
    for row in sessions:
        station_id = row["station_id"]
        no = (row["connector_no"] or "").strip()
        key = physical_id(station_id, no) if station_id and no else None
        # Тип отбирает записи сессий; каталог содержит актуальный тип порта.
        if (types and row["connector_type"] not in types) or (ids and key not in ids):
            continue
        station = station_map.get(station_id)
        offset = timedelta(hours=(station.get("msk_offset") or 0) if station and tz == "local" else 0)
        start = row["started_at"] + offset if row["started_at"] else None
        finish = row["finished_at"] + offset if row["finished_at"] else None
        valid = start is not None and finish is not None and finish > start
        starts_in_period = start is not None and lo <= start < hi
        relevant = starts_in_period or (valid and start < hi and finish > lo)
        # Без начала: относим к периоду по известному концу; без обеих дат
        # датировать запись нельзя, quality показывает её в любом периоде.
        relevant = relevant or (start is None and (finish is None or lo <= finish < hi))
        if not relevant:
            continue
        if not valid:
            quality["missing_interval_sessions"] += 1
        if not no:
            quality["missing_connector_sessions"] += 1
        if station is None:
            quality["unmapped_station_sessions"] += 1
            continue
        series_id = station_id if grouping == "station" else key
        if series_id not in series:
            continue
        if starts_in_period:
            series[series_id]["points"][start.hour]["starts"] += 1
        if valid:
            intervals[series_id].append((max(start, lo), min(finish, hi)))
    for series_id, spans in intervals.items():
        for start, finish in _merged(spans):
            while start < finish:
                end = min(finish, start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
                series[series_id]["points"][start.hour]["occupied_minutes"] += (end - start).total_seconds() / 60
                start = end
    for item in series.values():
        for point in item["points"]:
            point["occupancy_pct"] = round(100 * point["occupied_minutes"] / available, 6)
            point["occupied_minutes"] = round(point["occupied_minutes"], 6)
    return dict(group_by=grouping, tz=tz,
                period={"from": date_from.isoformat(), "to": date_to.isoformat()},
                hours=list(range(24)), series=list(series.values()), connectors=connectors,
                connector_types=(available_connector_types if available_connector_types is not None
                                 else sorted({c["connector_type"] for c in connectors if c["connector_type"]})),
                quality=quality)


async def hourly_occupancy(
    db: AsyncSession, f: PeriodFilter, *, tz: str = "msk", group_by: str = "auto",
    connector_types: list[str] | None = None, connector_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Загрузка только нужных колонок; без лимита портов/сессий и без записи в БД."""
    cid = f.company_id
    if not isinstance(cid, UUID):
        raise ValueError("company_id обязателен")
    if f.date_to < f.date_from or f.date_to == date.max:
        raise ValueError("Некорректный период")
    fleet = [L.company_id == cid, L.type == "ev_charging", L.is_test.is_(False),
             L.operational_status != "decommissioned", *scope_location_conds(L.id)]
    # Существующий контур разрешает текущие/прежние номера в location_id;
    # затем берём ВСЮ историю объекта, включая переименованные номера CPO.
    # У переиспользованного номера приоритет текущего владельца в справочнике.
    for codes in (f.station_codes, [f.dim_val] if f.dim_by == "station" else None):
        if codes:
            resolved = text(station_locations_sql(":ho_codes", ":ho_company")).bindparams(
                bindparam("ho_codes", list(codes), type_=ARRAY(String), unique=True),
                bindparam("ho_company", str(cid), unique=True))
            fleet.append(L.id.op("= ANY")(resolved))
    if f.regions:
        fleet.append(func.coalesce(R.name, "—").in_(f.regions))
    if f.dim_by == "region":
        fleet.append(func.coalesce(R.name, "—") == f.dim_val)
    region_join = and_(R.id == L.region_id, R.company_id == cid)
    locations = (await db.execute(select(L.id, L.station_number, L.code, L.name, R.msk_offset)
                                 .outerjoin(R, region_join).where(*fleet).order_by(L.id))).all()
    stations = []
    for loc in locations:
        code = loc.station_number or loc.code
        stations.append(dict(station_id=loc.id, station_code=code, station_name=loc.name,
                             label=f"{loc.name} ({code})", msk_offset=loc.msk_offset or 0))
    station_map = {s["station_id"]: s for s in stations}
    scope = [S.company_id == cid, *scope_location_conds(S.location_id)]
    if f.regions:
        scope.append(func.coalesce(R.name, "—").in_(f.regions))
    dim = AnalyticsService._dim_cond(f.dim_by, f.dim_val) if f.dim_by != "station" else None
    if dim is not None:
        scope.append(dim)
    # История только сопоставленных физических портов выбранных станций.
    number = func.nullif(func.btrim(S.connector_no), "")
    history = (select(S.location_id, number.label("no"), S.connector_type)
               .select_from(S).outerjoin(L, and_(L.id == S.location_id, L.company_id == cid))
               .outerjoin(R, region_join)
               .where(*scope, S.location_id.in_(station_map), number.is_not(None))
               .distinct(S.location_id, number)
               .order_by(S.location_id, number, S.started_at.desc().nulls_last(), S.id.desc()))
    connectors = []
    for row in (await db.execute(history)).all():
        station = station_map[row.location_id]
        connectors.append({k: station[k] for k in ("station_id", "station_code", "station_name")} | dict(
            id=physical_id(row.location_id, row.no), connector_no=row.no,
            connector_type=row.connector_type,
            label=f"{station['label']} · №{row.no}" + (f" · {row.connector_type}" if row.connector_type else "")))
    type_history = (await db.execute(
        select(S.location_id, number.label("no"), S.connector_type).select_from(S)
        .outerjoin(L, and_(L.id == S.location_id, L.company_id == cid)).outerjoin(R, region_join)
        .where(*scope, S.location_id.in_(station_map), S.connector_type.is_not(None), S.connector_type != "")
        .distinct()
    )).all()
    available_types = sorted({row.connector_type for row in type_history})
    physical_types = defaultdict(set)
    for row in type_history:
        if row.no:
            physical_types[physical_id(row.location_id, row.no)].add(row.connector_type)
    # Непривязанные сессии не приписываем станции по похожему коду.
    # В пространственно суженном контуре их принадлежность неизвестна.
    spatial_scope = bool(f.station_codes or f.regions or f.dim_by in ("station", "region")
                         or current_object_scope())
    mapped = S.location_id.in_(station_map)
    scope.append(mapped if spatial_scope else or_(mapped, L.id.is_(None)))
    joined = S.__table__.outerjoin(L, and_(L.id == S.location_id, L.company_id == cid)).outerjoin(R, region_join)
    filtered = list(scope)
    if connector_types:
        filtered.append(S.connector_type.in_(connector_types))
    if connector_ids:
        filtered.append(func.concat(S.location_id, ":", number).in_(connector_ids))
    last = (await db.execute(select(func.max(S.started_at)).select_from(joined).where(*filtered))).scalar_one()
    shift = func.coalesce(R.msk_offset, 0) * timedelta(hours=1) if tz == "local" else timedelta(0)
    start, finish = S.started_at + shift, S.finished_at + shift
    lo = datetime.combine(f.date_from, time.min)
    hi = datetime.combine(f.date_to + timedelta(days=1), time.min)
    temporal = or_(and_(start >= lo, start < hi),
                   and_(start < hi, finish > lo, finish > start),
                   and_(start.is_(None), or_(finish.is_(None), and_(finish >= lo, finish < hi))))
    rows = await db.stream(select(S.location_id.label("station_id"), S.connector_no, S.connector_type,
                                  S.started_at, S.finished_at).select_from(joined).where(*filtered, temporal))
    # Только интервалы запрошенного периода, не весь реестр истории.
    sessions = [row._mapping async for row in rows]
    return calculate_hourly_occupancy(stations, connectors, sessions, f.date_from, f.date_to,
                                      tz=tz, group_by=group_by, connector_types=connector_types,
                                      connector_ids=connector_ids, last_session_at=last,
                                      available_connector_types=available_types,
                                      physical_connector_types=physical_types)
