"""
Общие FastAPI-зависимости и хелперы tenant-scoping (мультитенантность).

Три паттерна доступа к данным компании (см. план мультитенантности):
  - company_id в query  → `cid: CompanyDep` (списки/фильтры/stats/analytics);
  - company_id в теле    → `await assert_company_member(payload.company_id, user, db)`;
  - объект по path-/{id}  → `await get_owned(Model, id, user, db)`.
"""

import uuid
from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CompanyScope, get_current_user
from app.database import get_db
from app.models import User, UserCompany

# company_id из query + проверка членства → UUID компании.
CompanyDep = Annotated[uuid.UUID, Depends(CompanyScope())]

# Текущий пользователь (для краткости в сигнатурах).
CurrentUser = Annotated[User, Depends(get_current_user)]

# Сессия БД.
DbDep = Annotated[AsyncSession, Depends(get_db)]

_T = TypeVar("_T")


async def get_owned(
    model: type[_T],
    obj_id,
    current_user: User,
    db: AsyncSession,
) -> _T:
    """
    Грузит объект по первичному ключу и проверяет принадлежность доступной
    компании. Для не-суперадмина сверяет obj.company_id с членством.

    Возвращает 404 (не 403) и для несуществующего, и для чужого объекта —
    чтобы не раскрывать существование чужих данных. Объект обязан иметь
    атрибут company_id.
    """
    obj = await db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    if current_user.is_superadmin:
        return obj
    result = await db.execute(
        select(UserCompany.company_id).where(
            UserCompany.user_id == current_user.id,
            UserCompany.company_id == obj.company_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    return obj
