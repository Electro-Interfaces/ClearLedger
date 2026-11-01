"""
Журнал аудита RBAC — пишет в существующую таблицу AuditEvent.
Best-practice: фиксировать кто/когда/что менял в доступе/ролях/команде.
"""
import json
from typing import Any, Literal
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
    notification_timing: Literal["immediate", "after_root_commit"] = "immediate",
    doc_notice_id: uuid.UUID | None = None,
) -> None:
    """Добавить событие в журнал (без commit — коммитит вызывающий эндпоинт).
    action — маркер вида `role.create` / `member.access` / `user.create`."""
    if notification_timing not in ("immediate", "after_root_commit"):
        raise ValueError("unknown audit notification timing")
    if doc_notice_id is not None:
        if action != "doc.register" or notification_timing != "after_root_commit":
            raise ValueError("document notices require deferred doc.register opt-in")
        if not isinstance(doc_notice_id, uuid.UUID):
            raise TypeError("document notice requires a native UUID")
    if notification_timing == "after_root_commit":
        from app.services.after_root_commit import validate_audit_notification_session
        validate_audit_notification_session(db)
    parts: list[str] = []
    if target:
        parts.append(target)
    if details:
        parts.append(json.dumps(details, ensure_ascii=False))
    text = " · ".join(parts) or None
    if notification_timing == "after_root_commit":
        who = actor.name if actor else None
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
    if notification_timing == "after_root_commit":
        from app.services.after_root_commit import enqueue_audit_notification
        enqueue_audit_notification(db, company_id=company_id, action=action,
                                   who=who, details=text, doc_notice_id=doc_notice_id)
        return
    from app.services.notify import dispatch_async   # локально: иначе кольцо импортов
    dispatch_async(company_id, action, who=actor.name if actor else None, details=text)
