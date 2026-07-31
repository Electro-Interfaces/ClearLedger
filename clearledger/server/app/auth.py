"""
JWT-аутентификация: создание токена, верификация, dependency.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Company, User, UserCompany
from app.utils import resolve_company_id

settings = get_settings()

# Хеширование паролей (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer-схема для Swagger UI
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Хеширует пароль bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Проверяет пароль против хеша."""
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, email: str) -> str:
    """Создаёт JWT access-токен."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": user_id,
        "email": email,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    """Декодирует JWT. Бросает HTTPException при ошибке."""
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен истёк",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency: извлекает текущего пользователя из JWT.
    Возвращает объект User из БД.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )

    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен: отсутствует sub",
        )

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный ID пользователя в токене",
        )

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
        )

    await _touch_presence(user, db)
    return user


# Как часто обновляем отметку присутствия. Писать на каждый запрос — лишняя нагрузка на
# БД, поэтому «тёплое» обновление: раз в PRESENCE_TOUCH_SECONDS активной работы. Кто
# сейчас в системе, определяется по свежести этой отметки (services/space_map).
PRESENCE_TOUCH_SECONDS = 120


async def _touch_presence(user: User, db: AsyncSession) -> None:
    """Отметить, что человек сейчас работает. Тихо: сбой отметки не ломает запрос."""
    now = datetime.now(timezone.utc)
    seen = user.last_seen_at
    if seen is not None:
        # В старых записях отметка могла лечь без таймзоны — сравниваем аккуратно.
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        if (now - seen).total_seconds() < PRESENCE_TOUCH_SECONDS:
            return
    try:
        user.last_seen_at = now
        await db.commit()
    except Exception:  # noqa: BLE001 — присутствие не важнее самого запроса
        await db.rollback()


async def assert_company_member(
    company_ref: str,
    user: User,
    db: AsyncSession,
) -> uuid.UUID:
    """
    Резолвит company_ref (UUID|slug) в UUID и проверяет, что пользователь
    имеет к этой компании доступ.

    Суперадмин — доступ ко всем. Иначе требуется членство в user_companies.
    Бросает 400 при неизвестной компании, 403 при отсутствии членства.
    Единая точка проверки прав на компанию для всех эндпоинтов данных.

    Здесь же выставляется СКОУП ДАННЫХ запроса (`app/scope.py`) — объекты, которые
    участнику разрешено видеть. Место выбрано именно это: фильтр по объектам нужен
    десяткам ручек, и протаскивать его параметром — однажды забыть в одной и открыть
    данные. Пройти к данным компании мимо этой функции нельзя.
    """
    from app.scope import _as_ids, set_request_scope

    cid = await resolve_company_id(company_ref, db)  # 400, если нет такой компании
    if user.is_superadmin:
        set_request_scope(None)
        return cid
    m = (await db.execute(
        select(UserCompany).where(
            UserCompany.user_id == user.id,
            UserCompany.company_id == cid,
        )
    )).scalar_one_or_none()
    if m is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к компании",
        )
    # Админ компании видит всю сеть: иначе он не настроит то, чего не видит.
    set_request_scope(None if m.role == "admin" else _as_ids(m.object_scope))
    return cid


def CompanyScope(query_param: str = "company_id"):
    """
    Фабрика FastAPI-зависимости для эндпоинтов, где company_id приходит в query.
    Достаёт company_id, проверяет членство, возвращает UUID компании.

    Использование:
        cid: uuid.UUID = Depends(CompanyScope())
    или через alias app.deps.CompanyDep.
    """

    async def _dep(
        company_id: str = Query(..., alias=query_param),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> uuid.UUID:
        return await assert_company_member(company_id, current_user, db)

    return _dep


async def resolve_member_modules(m: UserCompany, db: AsyncSession) -> list[str] | None:
    """Эффективный набор модулей члена: назначенная роль (role_id) приоритетнее
    ad-hoc modules. Возвращает None = полный доступ (admin / роль «Полный доступ»)."""
    if m.role == "admin":
        return None
    if m.role_id is not None:
        from app.models import CompanyRole
        role = await db.get(CompanyRole, m.role_id)
        if role is not None:
            return role.modules
    return m.modules


# Продукты пространства, покрывающие серверный модуль. Права раздаются ключами
# продуктов (`sales` — весь продукт, `sales:variances` — его пункт), а ручки
# гейтятся модулями Учёта (`management`): без карты любой явный набор получал
# в меню пункт, а от сервера — 403 «Доступ запрещён» на данные этого же пункта.
# Гранулярность до пункта остаётся клиентским гейтом (см. productAccess.ts) —
# сервер держит границу продукта, как и раньше держал границу модуля.
_MODULE_PRODUCTS: dict[str, tuple[str, ...]] = {
    "management": ("sales", "ops"),
    "store": ("shop",),
    "accounting": ("finance",),
    "financial": ("finance",),
    "tax": ("finance",),
}


def _module_allowed(module_key: str, mods: list[str]) -> bool:
    if module_key in mods or f"ledger:{module_key}" in mods or "ledger" in mods:
        return True
    for product in _MODULE_PRODUCTS.get(module_key, ()):
        if product in mods or any(k.startswith(product + ":") for k in mods):
            return True
    return False


async def check_module_access(
    user: User, cid: uuid.UUID, db: AsyncSession, module_key: str
) -> None:
    """RBAC-проверка модуля для УЖЕ резолвнутой компании (когда cid получен из
    X-Company-Id через scope_company_id). Полный доступ: суперадмин, admin-член,
    эффективные modules=NULL. Иначе 403, если ни module_key, ни покрывающий его
    продукт (или пункт продукта) не входят в разрешённые.
    Используется гейтом роутеров со скоупом «по юзеру» (store и т.п.)."""
    if user.is_superadmin:
        return
    m = await db.get(UserCompany, (user.id, cid))
    if m is None or m.role == "admin":
        return
    mods = await resolve_member_modules(m, db)
    if mods is None:
        return
    if not _module_allowed(module_key, mods):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к модулю",
        )


async def assert_company_module(
    company_ref: str, user: User, db: AsyncSession, module_key: str
) -> uuid.UUID:
    """assert_company_member + RBAC-проверка модуля.

    Полный доступ (без проверки): суперадмин, admin-член, эффективные modules=NULL.
    Иначе 403, если module_key не в разрешённых модулях (с учётом роли).
    """
    cid = await assert_company_member(company_ref, user, db)  # membership + 403
    await check_module_access(user, cid, db, module_key)
    return cid


def CompanyModuleScope(module_key: str, query_param: str = "company_id"):
    """Как CompanyScope, но дополнительно требует доступ к модулю module_key (RBAC)."""

    async def _dep(
        company_id: str = Query(..., alias=query_param),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> uuid.UUID:
        return await assert_company_module(company_id, current_user, db, module_key)

    return _dep


async def get_company_by_api_key(
    x_cloud_api_key: str = Header(..., alias="X-Cloud-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Company:
    """
    FastAPI dependency: аутентификация по X-Cloud-API-Key.
    Используется внешними системами (TSupport, дедуп-нода, edge-агенты).

    Сначала именные ключи (space_inbound_keys, по SHA256-хешу: видно, КТО ходит,
    и любого можно отозвать отдельно), затем легаси-ключ компании — он один на
    всех и остаётся, пока настроенные внешние узлы не переведены на именные.
    """
    if not x_cloud_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется X-Cloud-API-Key",
        )

    import hashlib
    from datetime import datetime, timezone

    from app.models import SpaceInboundKey
    key_hash = hashlib.sha256(x_cloud_api_key.encode()).hexdigest()
    named = (await db.execute(
        select(SpaceInboundKey).where(
            SpaceInboundKey.key_hash == key_hash,
            SpaceInboundKey.revoked_at.is_(None),
        )
    )).scalar_one_or_none()
    if named is not None:
        named.last_used_at = datetime.now(timezone.utc)
        company = await db.get(Company, named.company_id)
        if company is not None:
            return company

    result = await db.execute(
        select(Company).where(Company.cloud_api_key == x_cloud_api_key)
    )
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный API-ключ",
        )

    return company
