"""
Отчёты: по периоду, контрагентам, источникам, ошибкам.
"""

import uuid
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import DataEntry, User
from app.utils import resolve_company_id
from app.schemas import CounterpartyStat, ErrorStat, PeriodReport, SourceStat

router = APIRouter(prefix="/reports", tags=["Отчёты"])


# Маппинг источников на русские метки
SOURCE_LABELS = {
    "upload": "Загрузка файла",
    "photo": "Фото",
    "manual": "Ручной ввод",
    "api": "API",
    "email": "Email",
    "oneC": "1С",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "paste": "Вставка текста",
}


@router.get("/period", response_model=PeriodReport)
async def report_period(
    company_id: str = Query(..., description="ID компании"),
    date_from: str = Query(..., description="Дата начала (ISO)"),
    date_to: str = Query(..., description="Дата окончания (ISO)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отчёт по периоду: количество по статусам."""
    cid = await resolve_company_id(company_id, db)

    query = (
        select(DataEntry)
        .where(DataEntry.company_id == cid)
        .where(DataEntry.created_at >= date_from)
        .where(DataEntry.created_at <= date_to)
    )
    result = await db.execute(query)
    entries = result.scalars().all()

    status_counts: Counter = Counter()
    for entry in entries:
        status_counts[entry.status] += 1

    return PeriodReport(
        date_from=date_from,
        date_to=date_to,
        uploaded=len(entries),
        verified=status_counts.get("verified", 0),
        rejected=status_counts.get("error", 0),
        transferred=status_counts.get("transferred", 0),
        archived=status_counts.get("archived", 0),
    )


@router.get("/counterparties", response_model=list[CounterpartyStat])
async def report_counterparties(
    company_id: str = Query(..., description="ID компании"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Статистика по контрагентам (из metadata._counterparty или metadata.counterparty)."""
    cid = await resolve_company_id(company_id, db)

    query = select(DataEntry).where(DataEntry.company_id == cid)
    if date_from:
        query = query.where(DataEntry.created_at >= date_from)
    if date_to:
        query = query.where(DataEntry.created_at <= date_to)

    result = await db.execute(query)
    entries = result.scalars().all()

    stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "verified": 0, "rejected": 0})
    for entry in entries:
        meta = entry.meta or {}
        counterparty = (
            meta.get("counterparty")
            or meta.get("_counterparty")
            or "Не указан"
        )
        stats[counterparty]["count"] += 1
        if entry.status == "verified":
            stats[counterparty]["verified"] += 1
        elif entry.status == "error":
            stats[counterparty]["rejected"] += 1

    return [
        CounterpartyStat(
            counterparty=name,
            count=data["count"],
            verified=data["verified"],
            rejected=data["rejected"],
        )
        for name, data in sorted(stats.items(), key=lambda x: -x[1]["count"])
    ]


@router.get("/sources", response_model=list[SourceStat])
async def report_sources(
    company_id: str = Query(..., description="ID компании"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Статистика по источникам документов."""
    cid = await resolve_company_id(company_id, db)

    query = select(DataEntry).where(DataEntry.company_id == cid)
    if date_from:
        query = query.where(DataEntry.created_at >= date_from)
    if date_to:
        query = query.where(DataEntry.created_at <= date_to)

    result = await db.execute(query)
    entries = result.scalars().all()

    counter: Counter = Counter()
    for entry in entries:
        counter[entry.source] += 1

    return [
        SourceStat(
            source=source,
            label=SOURCE_LABELS.get(source, source),
            count=count,
        )
        for source, count in counter.most_common()
    ]


@router.get("/errors", response_model=list[ErrorStat])
async def report_errors(
    company_id: str = Query(..., description="ID компании"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Статистика по ошибкам (записи со статусом error)."""
    cid = await resolve_company_id(company_id, db)

    query = (
        select(DataEntry)
        .where(DataEntry.company_id == cid)
        .where(DataEntry.status == "error")
    )
    if date_from:
        query = query.where(DataEntry.created_at >= date_from)
    if date_to:
        query = query.where(DataEntry.created_at <= date_to)

    result = await db.execute(query)
    entries = result.scalars().all()

    counter: Counter = Counter()
    for entry in entries:
        meta = entry.meta or {}
        # Причина ошибки может быть в meta._error или в source_label
        reason = meta.get("_error") or meta.get("_reject_reason") or entry.source_label or "Не указана"
        counter[reason] += 1

    return [
        ErrorStat(reason=reason, count=count)
        for reason, count in counter.most_common()
    ]
