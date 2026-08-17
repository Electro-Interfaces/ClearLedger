"""Публичная проверка регистрации документа без раскрытия внутренней карточки."""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import DocCard


async def ensure_token(db: AsyncSession, doc: DocCard) -> str:
    """Выдать стабильный случайный код. 24 байта дают 192 бита энтропии."""
    if not doc.verify_token:
        locked = (await db.execute(select(DocCard).where(
            DocCard.id == doc.id).execution_options(
                populate_existing=True).with_for_update())).scalar_one()
        if locked.verify_token:
            return locked.verify_token
        locked.verify_token = secrets.token_urlsafe(24)
        await db.flush()
        return locked.verify_token
    return doc.verify_token


async def public_url(db: AsyncSession, doc: DocCard) -> str:
    token = await ensure_token(db, doc)
    return f"{get_settings().app_public_url.rstrip('/')}/doc-verify/{token}"
