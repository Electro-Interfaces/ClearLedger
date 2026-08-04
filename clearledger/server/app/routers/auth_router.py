"""
Роутер аутентификации: регистрация, логин, текущий пользователь.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    resolve_member_modules,
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


def _client_ip(request: Request) -> str | None:
    """IP входящего — за Traefik/nginx настоящий адрес живёт в X-Forwarded-For."""
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return xff or (request.client.host if request.client else None)


async def _pending_invite(email: str, db: AsyncSession):
    """Живое приглашение на этот адрес, если человека самого ещё нет.

    Приглашённый, который не прошёл по ссылке, в системе НЕ существует: вход отвечает
    ему «неверный email или пароль», а восстановление пароля молчит — оба ответа
    заводят в тупик и человек идёт к администратору. Обе двери смотрят сюда.
    """
    from app.models import Invitation
    inv = (await db.execute(
        select(Invitation)
        .where(Invitation.email == email, Invitation.status == "pending")
        .order_by(Invitation.created_at.desc())
    )).scalars().first()
    if inv is None or inv.expires_at < datetime.now(timezone.utc):
        return None
    return inv


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Вход по email + пароль. Возвращает JWT."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None and await _pending_invite(body.email, db) is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Вас пригласили в это пространство, но приглашение ещё не принято: "
                   "пароль задаётся по ссылке из письма-приглашения. Не нашли письмо — "
                   "нажмите «Забыли пароль?», и приглашение придёт заново.",
        )

    # Почтовый участник чатов учётной записью не пользуется: он живёт в своей
    # почте, пароля у него нет вовсе. Говорим это прямо — иначе человек будет
    # ломиться в «Забыли пароль?» и получать письма, которые ничего не меняют.
    if user is not None and user.mail_only:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Этот адрес участвует в обсуждениях по электронной почте и входа "
                   "в пространство не имеет. Отвечайте письмом на сообщения, которые "
                   "приходят вам от участников.",
        )

    if user is None or not verify_password(body.password, user.password_hash):
        # Неудачную попытку по СУЩЕСТВУЮЩЕМУ email пишем в журнал его компании:
        # админ должен видеть, что в учётку ломятся. Несуществующие email не пишем —
        # журнал не место для перебора чужих адресов.
        if user is not None and user.company_id is not None:
            await log_audit(db, actor=user, company_id=user.company_id,
                            action="auth.login_failed", target=_client_ip(request))
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    # Отметка входа: без неё карта пространства показывала «не заходили» даже у тех, кто
    # работает каждый день — раньше last_seen_at обновлял только веб-сокет чата.
    user.last_seen_at = datetime.now(timezone.utc)
    if user.company_id is not None:
        await log_audit(db, actor=user, company_id=user.company_id,
                        action="auth.login", target=_client_ip(request))
    await db.commit()

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
    # Почтовому участнику восстанавливать нечего: учётка держит его в составе
    # чатов, но входа не даёт. Ссылка на смену пароля только запутала бы.
    if user is not None and user.mail_only:
        return {"ok": True}
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

    # Пароля ещё нет, но человека звали — высылаем приглашение заново (с новым токеном:
    # старая ссылка из письма могла потеряться или истечь). Так приглашённый выбирается
    # из тупика сам, не дожидаясь администратора.
    inv = await _pending_invite(body.email, db)
    if inv is not None:
        from app.routers.invitations_router import INVITE_TTL  # ленивый: там свой импорт этого модуля
        raw = secrets.token_urlsafe(32)
        inv.token_hash = _hash_token(raw)
        inv.expires_at = datetime.now(timezone.utc) + INVITE_TTL
        await db.flush()
        company = await db.get(Company, inv.company_id)
        try:
            await email_service.send_invite(
                inv.email, raw, company.name if company else "",
                None, inv.role, inv.expires_at,
            )
        except Exception as exc:  # noqa: BLE001 — сбой письма не должен ронять запрос
            _reset_log.error("send_invite (forgot-password) failed: %s", exc)
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
    if user.company_id is not None:
        await log_audit(db, actor=user, company_id=user.company_id,
                        action="auth.password_reset")
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
        # Обычный — только свои, с ролью и ЭФФЕКТИВНЫМИ правами членства.
        rows = (
            await db.execute(
                select(Company, UserCompany)
                .join(UserCompany, UserCompany.company_id == Company.id)
                .where(UserCompany.user_id == current_user.id)
                .order_by(Company.name)
            )
        ).all()
        # ⚠ Права считает `resolve_member_modules`, а не поле `UserCompany.modules`:
        # у человека с ИМЕНОВАННОЙ ролью это поле NULL (набор лежит в самой роли), а
        # фронт читает NULL как «полный доступ» — то есть назначенная роль не
        # ограничивала ничего. admin-член видит всё.
        briefs = [
            _brief(c, uc.role, None if uc.role == "admin" else await resolve_member_modules(uc, db))
            for c, uc in rows
        ]

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
