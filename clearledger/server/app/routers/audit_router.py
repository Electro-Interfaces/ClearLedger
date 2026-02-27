"""
Роутер аудит-лога: история действий по записям и компаниям.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from app.auth import get_current_user
from app.database import get_db
from app.models import AuditEvent, User
from app.schemas import AuditEventResponse
from app.utils import resolve_company_id, resolve_company_id_optional


class AuditEventCreate(BaseModel):
    """Схема создания аудит-события (camelCase от фронтенда)."""
    companyId: str
    entryId: str | None = None
    action: str
    details: str | None = None
    userId: str | None = None
    userName: str | None = None

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


@router.post("", response_model=AuditEventResponse, status_code=201)
async def create_audit_event(
    body: AuditEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать событие аудита (используется фронтендом для логирования действий)."""
    cid = await resolve_company_id(body.companyId, db)

    entry_id = None
    if body.entryId:
        try:
            entry_id = uuid.UUID(body.entryId)
        except ValueError:
            pass

    event = AuditEvent(
        company_id=cid,
        entry_id=entry_id,
        user_id=body.userId or str(current_user.id),
        user_name=body.userName or current_user.name,
        action=body.action,
        details=body.details,
    )
    db.add(event)
    await db.flush()
    return _audit_response(event)


@router.get("", response_model=list[AuditEventResponse])
async def list_audit_events(
    company_id: str | None = Query(None),
    action: str | None = Query(None),
    entry_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список событий аудита с фильтрами. Возвращает плоский массив."""
    query = select(AuditEvent)

    # Изоляция данных по компании
    cid = await resolve_company_id_optional(company_id, db) or current_user.company_id
    query = query.where(AuditEvent.company_id == cid)

    if action:
        query = query.where(AuditEvent.action == action)

    if entry_id:
        try:
            eid = uuid.UUID(entry_id)
            query = query.where(AuditEvent.entry_id == eid)
        except ValueError:
            pass

    if date_from:
        query = query.where(AuditEvent.timestamp >= date_from)

    if date_to:
        query = query.where(AuditEvent.timestamp <= date_to)

    query = query.order_by(AuditEvent.timestamp.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    events = result.scalars().all()

    return [_audit_response(e) for e in events]


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
