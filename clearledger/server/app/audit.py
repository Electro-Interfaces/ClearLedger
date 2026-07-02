"""
Журнал аудита RBAC — пишет в существующую таблицу AuditEvent.
Best-practice: фиксировать кто/когда/что менял в доступе/ролях/команде.
"""
import json
from typing import Any
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, User


async def log_audit(
    db: AsyncSession,
    *,
    actor: User | None,
    company_id: uuid.UUID,
    action: str,
    target: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Добавить событие в журнал (без commit — коммитит вызывающий эндпоинт).
    action — маркер вида `role.create` / `member.access` / `user.create`."""
    parts: list[str] = []
    if target:
        parts.append(target)
    if details:
        parts.append(json.dumps(details, ensure_ascii=False))
    db.add(AuditEvent(
        company_id=company_id,
        user_id=str(actor.id) if actor else None,
        user_name=actor.name if actor else None,
        action=action,
        details=" · ".join(parts) or None,
    ))
