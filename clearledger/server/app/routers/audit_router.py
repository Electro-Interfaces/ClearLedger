"""
Роутер аудит-лога: история действий по записям и компаниям.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import AuditEvent, User
from app.schemas import AuditEventResponse, PaginatedAudit

router = APIRouter(prefix="/audit", tags=["Аудит"])


def _audit_response(event: AuditEvent) -> AuditEventResponse:
    """Конвертирует ORM AuditEvent в схему ответа."""
    return AuditEventResponse(
        id=str(event.id),
        entry_id=str(event.entry_id) if event.entry_id else None,
        company_id=str(event.company_id),
        user_id=event.user_id,
        user_name=event.user_name,
        action=event.action,
        details=event.details,
        timestamp=event.timestamp,
    )


@router.get("", response_model=PaginatedAudit)
async def list_audit_events(
    company_id: str | None = Query(None),
    action: str | None = Query(None),
    entry_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список событий аудита с фильтрами."""
    query = select(AuditEvent)
    count_query = select(func.count(AuditEvent.id))

    if company_id:
        try:
            cid = uuid.UUID(company_id)
            query = query.where(AuditEvent.company_id == cid)
            count_query = count_query.where(AuditEvent.company_id == cid)
        except ValueError:
            pass

    if action:
        query = query.where(AuditEvent.action == action)
        count_query = count_query.where(AuditEvent.action == action)

    if entry_id:
        try:
            eid = uuid.UUID(entry_id)
            query = query.where(AuditEvent.entry_id == eid)
            count_query = count_query.where(AuditEvent.entry_id == eid)
        except ValueError:
            pass

    if date_from:
        query = query.where(AuditEvent.timestamp >= date_from)
        count_query = count_query.where(AuditEvent.timestamp >= date_from)

    if date_to:
        query = query.where(AuditEvent.timestamp <= date_to)
        count_query = count_query.where(AuditEvent.timestamp <= date_to)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(AuditEvent.timestamp.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    events = result.scalars().all()

    return PaginatedAudit(
        items=[_audit_response(e) for e in events],
        total=total,
    )


@router.get("/entry/{entry_id}", response_model=list[AuditEventResponse])
async def get_entry_audit(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """История аудита для конкретной записи."""
    try:
        eid = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный ID записи")

    result = await db.execute(
        select(AuditEvent)
        .where(AuditEvent.entry_id == eid)
        .order_by(AuditEvent.timestamp.desc())
    )
    events = result.scalars().all()
    return [_audit_response(e) for e in events]
