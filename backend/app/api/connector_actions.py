"""Действия с коннекторами: ручной запуск, проверка статуса."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Connector, User
from app.api.deps import get_current_user, require_role
from app.services.email_connector import poll_email_connector

router = APIRouter(prefix="/connectors", tags=["connector-actions"])


class PollResult(BaseModel):
    processed: int = 0
    attachments: int = 0
    errors: int = 0
    error: str | None = None


@router.post("/{connector_id}/poll", response_model=PollResult)
async def trigger_poll(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner", "operator")),
):
    """Ручной запуск polling коннектора."""
    result = await db.execute(
        select(Connector).where(Connector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Коннектор не найден")

    if connector.type == "email":
        stats = await poll_email_connector(str(connector_id))
        # Обновляем счётчики
        connector.records_count += stats.get("attachments", 0)
        connector.errors_count += stats.get("errors", 0)
        if stats.get("processed", 0) > 0:
            from datetime import datetime, timezone
            connector.last_sync = datetime.now(timezone.utc)
            connector.status = "active"
        await db.commit()
        return PollResult(**stats)

    raise HTTPException(status_code=400, detail=f"Тип коннектора '{connector.type}' не поддерживает polling")
