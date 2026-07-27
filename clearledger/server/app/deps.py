"""
Общие FastAPI-зависимости и хелперы tenant-scoping (мультитенантность).

Три паттерна доступа к данным компании (см. план мультитенантности):
  - company_id в query  → `cid: CompanyDep` (списки/фильтры/stats/analytics);
  - company_id в теле    → `await assert_company_member(payload.company_id, user, db)`;
  - объект по path-/{id}  → `await get_owned(Model, id, user, db)`.
"""

import uuid
from contextvars import ContextVar
from typing import Annotated, TypeVar

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CompanyScope, assert_company_member, get_current_user
from app.database import get_db
from app.models import User, UserCompany

# company_id из query + проверка членства → UUID компании.
CompanyDep = Annotated[uuid.UUID, Depends(CompanyScope())]


# ── Активная компания из UI для роутеров со скоупом «по юзеру» ────────────────
# Роутеры fuel/store/… исторически скоупятся по user.company_id (дефолтная
# компания). Из-за этого переключение компании в шапке UI на них не влияло —
# суперадмин/мультикомпанийный юзер всегда видел дефолтную. Фронт теперь шлёт
# заголовок X-Company-Id (выбранная компания); он кладётся в contextvar
# зависимостью роутера (dependency и эндпоинт — один asyncio-контекст, значение
# видно в теле; между запросами не течёт — свой контекст на запрос + default).
_active_company: ContextVar[str | None] = ContextVar("active_company", default=None)


async def capture_company_header(
    x_company_id: str | None = Header(None, alias="X-Company-Id"),
) -> None:
    """Зависимость роутера: сохранить выбранную в UI компанию в contextvar."""
    _active_company.set(x_company_id)


async def scope_company_id(user: User, db: AsyncSession) -> uuid.UUID:
    """company_id для роутеров со скоупом «по юзеру»: выбранная в UI компания
    (заголовок X-Company-Id, с проверкой членства → 403 для чужой) либо
    дефолтная user.company_id, если заголовок не передан."""
    ref = _active_company.get()
    if ref:
        return await assert_company_member(ref, user, db)
    if user.company_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Компания не определена")
    return user.company_id

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

    Здесь же соблюдается СКОУП ДАННЫХ (`app/scope.py`): объект вне выданных
    участнику — такое же 404, как чужая компания. Скоуп резолвится по членству, а
    не из контекста запроса: часть одиночных ручек приходит сюда, минуя
    `assert_company_member` (id объекта в пути, company_id в запросе нет).
    """
    from app.models import ServiceLocation
    from app.scope import _as_ids

    obj = await db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    if current_user.is_superadmin:
        return obj
    m = (await db.execute(
        select(UserCompany).where(
            UserCompany.user_id == current_user.id,
            UserCompany.company_id == obj.company_id,
        )
    )).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    allowed = None if m.role == "admin" else _as_ids(m.object_scope)
    if allowed:
        # Сам объект (карточка станции) либо запись, привязанная к объекту
        # (оборудование, площадка, договорная позиция) — по `location_id`. Запись без
        # объекта участнику со скоупом не видна: она относится ко всей сети.
        ref = obj.id if model is ServiceLocation else getattr(obj, "location_id", None)
        if ref is None or str(ref) not in allowed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    return obj
