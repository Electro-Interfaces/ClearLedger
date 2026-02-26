"""KPI / статистика для дашборда."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Entry, Source, User
from app.api.deps import get_current_user

router = APIRouter(prefix="/stats", tags=["stats"])


class KpiResponse(BaseModel):
    uploaded_today: int
    total_verified: int
    in_processing: int
    errors: int
    transferred_today: int
    total_entries: int
    total_sources: int


class CategoryStatResponse(BaseModel):
    category_id: str
    count: int


@router.get("/kpi", response_model=KpiResponse)
async def get_kpi(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """KPI для дашборда."""
    base = select(Entry)
    if company_id:
        base = base.where(Entry.company_id == company_id)

    # Одним запросом через conditional aggregation
    q = select(
        func.count(Entry.id).label("total"),
        func.count().filter(
            Entry.created_at >= func.date_trunc('day', func.now())
        ).label("uploaded_today"),
        func.count().filter(
            Entry.status.in_(["verified", "transferred"])
        ).label("total_verified"),
        func.count().filter(
            Entry.status.in_(["new", "recognized"])
        ).label("in_processing"),
        func.count().filter(
            Entry.status == "error"
        ).label("errors"),
        func.count().filter(
            (Entry.status == "transferred") &
            (Entry.updated_at >= func.date_trunc('day', func.now()))
        ).label("transferred_today"),
    )
    if company_id:
        q = q.where(Entry.company_id == company_id)

    row = (await db.execute(q)).one()

    # Кол-во источников
    sq = select(func.count(Source.id))
    if company_id:
        sq = sq.where(Source.company_id == company_id)
    total_sources = (await db.execute(sq)).scalar() or 0

    return KpiResponse(
        uploaded_today=row.uploaded_today,
        total_verified=row.total_verified,
        in_processing=row.in_processing,
        errors=row.errors,
        transferred_today=row.transferred_today,
        total_entries=row.total,
        total_sources=total_sources,
    )


@router.get("/categories", response_model=list[CategoryStatResponse])
async def get_category_stats(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Распределение записей по категориям."""
    q = (
        select(Entry.category_id, func.count(Entry.id).label("count"))
        .group_by(Entry.category_id)
        .order_by(func.count(Entry.id).desc())
    )
    if company_id:
        q = q.where(Entry.company_id == company_id)

    result = await db.execute(q)
    return [
        CategoryStatResponse(category_id=row.category_id, count=row.count)
        for row in result.all()
    ]
