"""
Роутер аутентификации: регистрация, логин, текущий пользователь.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models import Company, User, UserCompany
from app.services import email_service
from app.utils import resolve_company_id
from app.schemas import (
    CompanyBrief,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Аутентификация"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Вход по email + пароль. Возвращает JWT."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    token = create_access_token(str(user.id), user.email)
    return TokenResponse(
        access_token=token,
        user=_user_response(user),
    )


# ===== Восстановление пароля по email =====

RESET_TTL = timedelta(hours=1)
_reset_log = logging.getLogger("clearledger.email")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """Запрос восстановления пароля: письмо со ссылкой-токеном.
    Всегда возвращает 200 — не раскрываем, существует ли email."""
    # email уже нормализован схемой (NormEmail: strip + lower)
    user = (
        await db.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if user is not None:
        raw = secrets.token_urlsafe(32)
        user.reset_token_hash = _hash_token(raw)
        user.reset_token_expires = datetime.now(timezone.utc) + RESET_TTL
        await db.flush()
        try:
            await email_service.send_password_reset(user.email, raw)
        except Exception as exc:  # noqa: BLE001 — сбой письма не должен ронять запрос
            _reset_log.error("send_password_reset failed: %s", exc)
    return {"ok": True}


async def _valid_reset_user(token: str, db: AsyncSession) -> User:
    user = (
        await db.execute(
            select(User).where(User.reset_token_hash == _hash_token(token))
        )
    ).scalar_one_or_none()
    if (
        user is None
        or user.reset_token_expires is None
        or user.reset_token_expires < datetime.now(timezone.utc)
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Ссылка недействительна или истекла"
        )
    return user


@router.get("/reset-password/{token}")
async def reset_password_preview(token: str, db: AsyncSession = Depends(get_db)):
    """Проверка токена восстановления (фронт показывает форму при валидном)."""
    user = await _valid_reset_user(token, db)
    return {"email": user.email}


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """Установка нового пароля по токену из письма (токен одноразовый)."""
    user = await _valid_reset_user(body.token, db)
    user.password_hash = hash_password(body.password)
    user.reset_token_hash = None
    user.reset_token_expires = None
    await db.flush()
    return {"ok": True}


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Регистрация нового пользователя — ТОЛЬКО суперадмин (саморегистрация
    закрыта; пользователей заводит админ компании через /api/users)."""
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Регистрация доступна только суперадмину",
        )
    # Проверка дубликата email
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким email уже существует",
        )

    # Проверка компании (UUID или slug)
    company_uuid = await resolve_company_id(body.company_id, db)

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        role="user",
        company_id=company_uuid,
    )
    db.add(user)
    await db.flush()

    # Членство в компании (источник истины прав доступа).
    db.add(UserCompany(user_id=user.id, company_id=company_uuid))
    await db.flush()

    token = create_access_token(str(user.id), user.email)
    return TokenResponse(
        access_token=token,
        user=_user_response(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(current_user: User = Depends(get_current_user)):
    """Продлить сессию — выдаёт новый JWT на основе текущего валидного."""
    token = create_access_token(str(current_user.id), current_user.email)
    return TokenResponse(
        access_token=token,
        user=_user_response(current_user),
    )


@router.get("/me", response_model=MeResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Текущий пользователь + список доступных компаний.
    Суперадмин получает все компании; обычный — только из user_companies.
    """
    if current_user.is_superadmin:
        # Суперадмин — все компании, роль 'admin' в каждой.
        companies = (
            await db.execute(select(Company).order_by(Company.name))
        ).scalars().all()
        briefs = [_brief(c, "admin") for c in companies]
    else:
        # Обычный — только свои, с ролью и модулями членства в каждой.
        rows = (
            await db.execute(
                select(Company, UserCompany.role, UserCompany.modules)
                .join(UserCompany, UserCompany.company_id == Company.id)
                .where(UserCompany.user_id == current_user.id)
                .order_by(Company.name)
            )
        ).all()
        # admin-член видит всё (modules игнорируется на всякий случай).
        briefs = [_brief(c, role, None if role == "admin" else mods) for c, role, mods in rows]

    return MeResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.name,
        role=current_user.role,
        is_superadmin=current_user.is_superadmin,
        default_company_id=str(current_user.company_id) if current_user.company_id else None,
        companies=briefs,
    )


def _brief(c, role: str, modules: list[str] | None = None) -> CompanyBrief:
    return CompanyBrief(
        id=str(c.id), slug=c.slug, name=c.name,
        short_name=c.short_name, color=c.color, profile_id=c.profile_id, role=role,
        modules=modules,
    )


def _user_response(user: User) -> UserResponse:
    """Конвертирует ORM-объект User в схему ответа (login/register/refresh)."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
        company_id=str(user.company_id) if user.company_id else None,
        is_superadmin=user.is_superadmin,
        created_at=user.created_at,
    )
