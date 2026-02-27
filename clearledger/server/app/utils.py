"""
Общие утилиты для роутеров.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company


async def resolve_company_id(
    company_id: str,
    db: AsyncSession,
) -> uuid.UUID:
    """
    Резолвит company_id (UUID или slug) в UUID.
    Фронтенд использует slug ('npk', 'rti') как Company.id,
    бэкенд хранит UUID. Эта функция пробует UUID, потом slug.
    """
    # Попытка как UUID
    try:
        uid = uuid.UUID(company_id)
        result = await db.execute(select(Company.id).where(Company.id == uid))
        if result.scalar_one_or_none() is not None:
            return uid
    except ValueError:
        pass

    # Fallback по slug
    result = await db.execute(
        select(Company.id).where(Company.slug == company_id)
    )
    found = result.scalar_one_or_none()
    if found is not None:
        return found

    raise HTTPException(status_code=400, detail="Невалидный company_id")


async def resolve_company_id_optional(
    company_id: str | None,
    db: AsyncSession,
) -> uuid.UUID | None:
    """
    Опциональная версия: если company_id=None, возвращает None.
    Если передан — резолвит через resolve_company_id.
    """
    if not company_id:
        return None
    return await resolve_company_id(company_id, db)
