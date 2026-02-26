"""Просмотр аудит-лога (только admin)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import AuditLog, User
from app.api.deps import require_role

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(BaseModel):
    id: UUID
    user_id: UUID | None
    action: str
    entity_type: str
    entity_id: str | None
    details: dict
    ip_address: str | None
    created_at: str

    model_config = {"from_attributes": True}


class AuditList(BaseModel):
    items: list[AuditOut]
    total: int


@router.get("", response_model=AuditList)
async def list_audit(
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin")),
):
    """Список записей аудит-лога (admin only)."""
    q = select(AuditLog)
    count_q = select(func.count(AuditLog.id))

    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
        count_q = count_q.where(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
        count_q = count_q.where(AuditLog.entity_id == entity_id)
    if action:
        q = q.where(AuditLog.action == action)
        count_q = count_q.where(AuditLog.action == action)

    total = (await db.execute(count_q)).scalar() or 0
    q = q.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    items = [AuditOut.model_validate(a) for a in result.scalars().all()]

    return AuditList(items=items, total=total)
