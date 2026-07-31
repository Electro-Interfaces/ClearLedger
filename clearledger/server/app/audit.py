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
    text = " · ".join(parts) or None
    # Системные события (прогоны каналов, фоновые службы) идут без актора,
    # а user_id/user_name в таблице NOT NULL — пишем служебного «актора».
    db.add(AuditEvent(
        company_id=company_id,
        user_id=str(actor.id) if actor else "system",
        user_name=actor.name if actor else "Платформа",
        action=action,
        details=text,
    ))
    # Оповещения идут по тем же событиям, что и журнал, — отдельного генератора не нужно.
    # Доставка в фоне со своей сессией: транзакцию вызывающего не держит и запрос не
    # ломает, если чат или почта недоступны (см. services/notify.py).
    from app.services.notify import dispatch_async   # локально: иначе кольцо импортов
    dispatch_async(company_id, action, who=actor.name if actor else None, details=text)
