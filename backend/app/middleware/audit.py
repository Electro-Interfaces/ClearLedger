"""Middleware для записи действий в audit_log."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.database import async_session


async def log_audit(
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Записать действие в audit_log.

    Вызывается из эндпоинтов после успешной операции.
    Использует отдельную сессию, чтобы не влиять на основную транзакцию.
    """
    async with async_session() as db:
        await db.execute(
            text("""
                INSERT INTO audit_log (id, user_id, action, entity_type, entity_id, details, ip_address, created_at)
                VALUES (gen_random_uuid(), :user_id, :action, :entity_type, :entity_id, :details::jsonb, :ip, now())
            """),
            {
                "user_id": str(user_id) if user_id else None,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details": json.dumps(details or {}, ensure_ascii=False, default=str),
                "ip": ip_address,
            },
        )
        await db.commit()
