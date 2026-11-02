"""Small status read projection, after the canonical object authorization query."""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Company
from app.services.ops_monitor_context import (
    monitor_context, session_boundary, session_summary, session_time_iso, visit_summary,
)
from . import dto
from .queries import Query

SCOPE = "monitoring:read"
DESCRIPTION = "Read status and charging visit aggregates of authorized objects"
STATUSES = frozenset({"working", "no_link", "disabled", "decommissioned", "on_repair",
                      "maintenance", "not_working", "unknown"})


async def detail(query: Query, object_id: str, params: dto.MonitoringQuery) -> dto.Monitoring:
    # Includes typed object grants, current membership scope and own-org links.
    # No session/boundary helper may run until this lookup succeeds.
    location = await query.detail("objects", object_id)
    profile = await query.db.scalar(select(Company.profile_id).where(Company.id == query.facts.company_id))
    if profile != "energy":
        raise HTTPException(404, "Not found")
    ids = {location.id}
    boundary = await session_boundary(query.db, query.facts.company_id, location_ids=ids)
    point, context = monitor_context(boundary, params.asOf)
    start = point - timedelta(days=params.days)
    totals = await session_summary(query.db, query.facts.company_id, start, point, location_ids=ids)
    visits = (await visit_summary(query.db, query.facts.company_id, start, point, location_ids=ids)).get(location.id, {})
    count, ok = int(visits.get("visits", 0)), int(visits.get("ok", 0))
    last = await session_boundary(query.db, query.facts.company_id, location_ids=ids, through=point)
    return dto.Monitoring(
        point_id=location.id, status=location.operational_status if location.operational_status in STATUSES else "unknown",
        window=dto.MonitoringWindow(days=params.days, start=session_time_iso(start), end=session_time_iso(point)),
        totals=dto.MonitoringTotals(**totals, visits=count, successful_visits=ok, unsuccessful_visits=count - ok),
        last_seen_at=session_time_iso(last), provenance=dto.MonitoringProvenance(**context),
    )
