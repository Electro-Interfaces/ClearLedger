"""Серверная нормализация: fuzzy match через pg_trgm."""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Counterparty


async def fuzzy_match_counterparty(
    db: AsyncSession,
    company_id: str,
    name: str,
    threshold: float = 0.3,
) -> Counterparty | None:
    """
    Найти контрагента по fuzzy-совпадению имени через pg_trgm.
    Возвращает лучшее совпадение с similarity >= threshold.
    """
    query = (
        select(Counterparty)
        .where(Counterparty.company_id == company_id)
        .where(text("similarity(name, :search_name) > :threshold"))
        .order_by(text("similarity(name, :search_name) DESC"))
        .limit(1)
    )
    result = await db.execute(
        query,
        {"search_name": name, "threshold": threshold},
    )
    return result.scalar_one_or_none()
