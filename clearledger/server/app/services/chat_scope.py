"""Контур переписки: с кем человек вообще может говорить в пространстве.

Контур роли (`company_roles.chat_scope`) запирает человека в его приложении —
так оператор подрядчика не получает внутреннюю переписку заказчика по факту
заведения учётки.

До 08.09.2026 граница держалась только со стороны комнат, а справочник людей
отдавался всем и целиком: оператор находил поиском любого сотрудника заказчика
с почтой, должностью и последним входом. Проверяющий нашёл это живым запросом.
Поэтому определение теперь одно на всех потребителей — `chat_router`,
`matrix_chat_router` и сам сервис Matrix, — и границу держат оба конца.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyRole, User, UserCompany


async def chat_scope_of(user: User, cid: uuid.UUID, db: AsyncSession) -> str | None:
    """Контур человека в пространстве — код приложения или None.

    Берётся из НАЗНАЧЕННОЙ роли, а не из набора модулей: набор отвечает, какие
    приложения открыть, контур — с кем человек в них разговаривает. Владелец
    контейнера контура не имеет никогда: он и есть надзор.
    """
    if user.is_superadmin:
        return None
    return (await db.execute(
        select(CompanyRole.chat_scope)
        .join(UserCompany, UserCompany.role_id == CompanyRole.id)
        .where(UserCompany.user_id == user.id, UserCompany.company_id == cid,
               CompanyRole.chat_scope.isnot(None))
        .limit(1)
    )).scalar_one_or_none()


def scope_member_ids(cid: uuid.UUID, scope: str):
    """Подзапрос: люди пространства, запертые в ЭТОМ контуре.

    Ими и ограничен справочник для человека с контуром. Человек БЕЗ контура
    видит всех, включая контурных: сотрудник заказчика вправе написать оператору
    поддержки, ограничение одностороннее.
    """
    return (select(UserCompany.user_id)
            .join(CompanyRole, CompanyRole.id == UserCompany.role_id)
            .where(UserCompany.company_id == cid, CompanyRole.chat_scope == scope))
