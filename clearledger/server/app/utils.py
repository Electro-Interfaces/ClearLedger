"""
Общие утилиты для роутеров.
"""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company


def _parse_bound(value: str) -> datetime:
    """'YYYY-MM-DD' или ISO-datetime → tz-aware datetime (UTC, как хранит БД)."""
    s = (value or "").strip()
    dt = datetime.fromisoformat(s[:10]) if len(s) == 10 else datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def day_start(date_from: str) -> datetime:
    """Нижняя граница периода для сравнения с timestamp-колонкой."""
    return _parse_bound(date_from)


def day_end(date_to: str) -> datetime:
    """Верхняя граница периода для сравнения с timestamp-колонкой.

    Голая дата 'YYYY-MM-DD' задаёт полночь — весь последний день периода выпадает
    (эталон services/analytics_service.py: _load_docs достраивает до конца суток).
    Плюс сравнение timestamptz со строкой asyncpg вообще не выполняет
    ('operator does not exist: timestamp with time zone >= character varying'),
    поэтому возвращаем datetime, а не строку.
    """
    dt = _parse_bound(date_to)
    if len((date_to or "").strip()) == 10:  # голая дата → конец суток
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


async def resolve_org_id(
    organization_id: str | None,
    company_id: uuid.UUID,
    db: AsyncSession,
) -> uuid.UUID | None:
    """Карточка юрлица, которое представляет участник → UUID (или None, если снимаем).

    Проверка принадлежности компании обязательна: без неё внешнего участника можно
    было бы привязать к контрагенту чужого пространства и подписать его в чатах чужой
    организацией. Пустая строка — осознанное «связь снять».
    """
    from app.models import Counterparty   # локально: utils не тянет весь реестр моделей

    if organization_id is None or organization_id == "":
        return None
    try:
        org_uuid = uuid.UUID(organization_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный id организации")
    org = await db.get(Counterparty, org_uuid)
    if org is None or org.company_id != company_id:
        raise HTTPException(status_code=404, detail="Организация не найдена в компании")
    return org_uuid


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
