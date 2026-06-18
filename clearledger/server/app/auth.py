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

    return user


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
    """
    cid = await resolve_company_id(company_ref, db)  # 400, если нет такой компании
    if user.is_superadmin:
        return cid
    result = await db.execute(
        select(UserCompany.company_id).where(
            UserCompany.user_id == user.id,
            UserCompany.company_id == cid,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к компании",
        )
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


async def get_company_by_api_key(
    x_cloud_api_key: str = Header(..., alias="X-Cloud-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Company:
    """
    FastAPI dependency: аутентификация по X-Cloud-API-Key.
    Используется внешними системами (TSupport) для доступа к audit-data.
    """
    if not x_cloud_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется X-Cloud-API-Key",
        )

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
