"""
Статистика: KPI дашборда и распределение по категориям.
"""

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import DataEntry, User
from app.utils import resolve_company_id
from app.schemas import CategoryStatResponse, KpiResponse

router = APIRouter(prefix="/stats", tags=["Статистика"])


@router.get("/kpi", response_model=KpiResponse)
async def get_kpi(
    company_id: str = Query(..., description="ID компании"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """KPI для дашборда: загрузки за сегодня, верифицировано, в обработке, ошибки, передано."""
    cid = await resolve_company_id(company_id, db)

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    base = select(DataEntry).where(DataEntry.company_id == cid)

    # Все записи для подсчёта статусов
    result = await db.execute(base)
    all_entries = result.scalars().all()

    status_counts: Counter[str] = Counter()
    uploaded_today = 0
    transferred_today = 0

    for entry in all_entries:
        status_counts[entry.status] += 1
        if entry.created_at and entry.created_at >= today_start:
            uploaded_today += 1
        if (
            entry.status == "transferred"
            and entry.updated_at
            and entry.updated_at >= today_start
        ):
            transferred_today += 1

    return KpiResponse(
        uploaded_today=uploaded_today,
        total_verified=status_counts.get("verified", 0),
        in_processing=status_counts.get("new", 0) + status_counts.get("recognized", 0),
        errors=status_counts.get("error", 0),
        transferred_today=transferred_today,
    )


@router.get("/categories", response_model=list[CategoryStatResponse])
async def get_category_stats(
    company_id: str = Query(..., description="ID компании"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Распределение записей по категориям (для диаграммы)."""
    cid = await resolve_company_id(company_id, db)

    query = (
        select(DataEntry.category_id, func.count(DataEntry.id).label("cnt"))
        .where(DataEntry.company_id == cid)
        .where(DataEntry.status != "archived")
        .group_by(DataEntry.category_id)
        .order_by(func.count(DataEntry.id).desc())
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        CategoryStatResponse(
            category_id=row.category_id,
            label=row.category_id,  # фронтенд маппит на локализованные названия
            count=row.cnt,
        )
        for row in rows
    ]
