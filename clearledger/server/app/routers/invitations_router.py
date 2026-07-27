"""
Приглашения сотрудников в компанию по email.

Админ компании (или суперадмин) создаёт приглашение → письмо со ссылкой
`/invite/{token}`. Сырой токен только в письме; в БД — SHA256, одноразовый, TTL.
Принятие (accept) — публичное (без авторизации): новый пользователь задаёт пароль
и автологинится, существующий — добавляется членство (логинится сам).
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, get_current_user, hash_password
from app.database import get_db
from app.models import Company, Counterparty, Invitation, User, UserCompany
from app.routers.users_router import require_company_admin, _is_member
from app.services import email_service
from app.utils import resolve_org_id
from app.schemas import (
    AcceptInvite,
    AcceptPreview,
    InvitationCreate,
    InvitationResponse,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/invitations", tags=["Приглашения"])

INVITE_TTL = timedelta(days=7)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _resp(
    inv: Invitation,
    raw_token: str | None = None,
    email_sent: bool | None = None,
    org_name: str | None = None,
) -> InvitationResponse:
    """Ответ по приглашению.

    `raw_token` передаётся только при создании и перевыпуске — тогда в ответ
    кладём готовую ссылку. В списке приглашений ссылки нет и быть не может:
    в базе лежит хеш токена.

    `org_name` подставляет вызывающий: в списке — одним запросом на всех, иначе
    строка приглашения партнёра показывала бы «внешний» без имени компании.
    """
    return InvitationResponse(
        id=str(inv.id), email=inv.email, role=inv.role, position=inv.position,
        status=inv.status, created_at=inv.created_at, expires_at=inv.expires_at,
        party_type=getattr(inv, "party_type", None) or "internal",
        organization_id=str(inv.organization_id) if inv.organization_id else None,
        organization_name=org_name,
        invite_url=email_service.invite_link(raw_token) if raw_token else None,
        email_sent=email_sent,
    )


async def _org_name(inv: Invitation, db: AsyncSession) -> str | None:
    """Имя организации приглашения (для UI); None у своих сотрудников."""
    if not inv.organization_id:
        return None
    org = await db.get(Counterparty, inv.organization_id)
    return (org.short_name or org.name) if org is not None else None


async def _company(cid: uuid.UUID, db: AsyncSession) -> Company:
    c = await db.get(Company, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Компания не найдена")
    return c


async def _send(inv: Invitation, raw_token: str, company: Company, inviter: User | None) -> bool:
    """Отправляет письмо. Возвращает, ушло ли оно на самом деле: при
    незаконфигурированном SMTP или сбое — False, и тогда интерфейс предложит
    передать ссылку вручную вместо ложного «письмо отправлено»."""
    try:
        return await email_service.send_invite(
            inv.email, raw_token, company.name,
            inviter.name if inviter else None, inv.role,
        )
    except Exception as exc:  # не валим запрос, если SMTP недоступен
        import logging
        logging.getLogger("clearledger.email").error("send_invite failed: %s", exc)
        return False


# ─── Управление (админ компании) ────────────────────────────────────────────
@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: InvitationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await require_company_admin(payload.company_id, current_user, db)
    email = payload.email  # уже нормализован схемой (NormEmail: strip + lower)
    party = payload.party_type or "internal"
    org_id = await resolve_org_id(payload.organization_id, cid, db) if party != "internal" else None

    # Уже член компании?
    existing_user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing_user and await _is_member(existing_user.id, cid, db):
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь уже в компании")

    # Есть pending-приглашение → пересоздаём токен (resend).
    inv = (
        await db.execute(
            select(Invitation).where(
                Invitation.company_id == cid,
                Invitation.email == email,
                Invitation.status == "pending",
            )
        )
    ).scalar_one_or_none()

    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    if inv is None:
        inv = Invitation(
            id=uuid.uuid4(), company_id=cid, email=email, role=payload.role,
            position=payload.position, token_hash=_hash(raw), status="pending",
            invited_by=current_user.id, expires_at=now + INVITE_TTL,
            party_type=party, organization_id=org_id,
        )
        db.add(inv)
    else:
        inv.token_hash = _hash(raw)
        inv.role = payload.role
        inv.position = payload.position
        inv.expires_at = now + INVITE_TTL
        inv.invited_by = current_user.id
        inv.party_type = party
        inv.organization_id = org_id
    await db.flush()

    company = await _company(cid, db)
    sent = await _send(inv, raw, company, current_user)
    return _resp(inv, raw_token=raw, email_sent=sent, org_name=await _org_name(inv, db))


@router.get("", response_model=list[InvitationResponse])
async def list_invitations(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await require_company_admin(company_id, current_user, db)
    rows = (
        await db.execute(
            select(Invitation)
            .where(Invitation.company_id == cid, Invitation.status == "pending")
            .order_by(Invitation.created_at.desc())
        )
    ).scalars().all()
    # Имена организаций — одним запросом на весь список, а не по строке.
    org_ids = {i.organization_id for i in rows if i.organization_id}
    names: dict[uuid.UUID, str] = {}
    if org_ids:
        for oid, nm, short in (await db.execute(select(
                Counterparty.id, Counterparty.name, Counterparty.short_name)
                .where(Counterparty.id.in_(org_ids)))).all():
            names[oid] = short or nm
    return [_resp(i, org_name=names.get(i.organization_id) if i.organization_id else None)
            for i in rows]


async def _owned_invite(invitation_id: str, current_user: User, db: AsyncSession) -> Invitation:
    try:
        iid = uuid.UUID(invitation_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    inv = await db.get(Invitation, iid)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Приглашение не найдено")
    # Право — админ компании приглашения.
    await require_company_admin(str(inv.company_id), current_user, db)
    return inv


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = await _owned_invite(invitation_id, current_user, db)
    inv.status = "revoked"


@router.post("/{invitation_id}/resend", response_model=InvitationResponse)
async def resend_invitation(
    invitation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = await _owned_invite(invitation_id, current_user, db)
    if inv.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Приглашение не активно")
    raw = secrets.token_urlsafe(32)
    inv.token_hash = _hash(raw)
    inv.expires_at = datetime.now(timezone.utc) + INVITE_TTL
    await db.flush()
    company = await _company(inv.company_id, db)
    sent = await _send(inv, raw, company, current_user)
    return _resp(inv, raw_token=raw, email_sent=sent, org_name=await _org_name(inv, db))


# ─── Принятие приглашения (публичное, без авторизации) ──────────────────────
async def _valid_invite(token: str, db: AsyncSession) -> Invitation:
    inv = (
        await db.execute(select(Invitation).where(Invitation.token_hash == _hash(token)))
    ).scalar_one_or_none()
    if inv is None or inv.status != "pending":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Приглашение недействительно")
    if inv.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, "Срок приглашения истёк")
    return inv


@router.get("/accept/{token}", response_model=AcceptPreview)
async def preview_invite(token: str, db: AsyncSession = Depends(get_db)):
    inv = await _valid_invite(token, db)
    company = await _company(inv.company_id, db)
    user_exists = (
        await db.execute(select(User.id).where(User.email == inv.email))
    ).scalar_one_or_none() is not None
    return AcceptPreview(
        email=inv.email, company_name=company.name, role=inv.role, user_exists=user_exists,
    )


@router.post("/accept/{token}")
async def accept_invite(
    token: str,
    payload: AcceptInvite,
    db: AsyncSession = Depends(get_db),
):
    inv = await _valid_invite(token, db)
    cid = inv.company_id

    user = (
        await db.execute(select(User).where(User.email == inv.email))
    ).scalar_one_or_none()

    if user is not None:
        # Существующий — добавляем членство с ролью/должностью, без автологина.
        if not await _is_member(user.id, cid, db):
            db.add(UserCompany(user_id=user.id, company_id=cid,
                               role=inv.role, position=inv.position,
                               party_type=getattr(inv, "party_type", None) or "internal",
                               organization_id=inv.organization_id))
        inv.status = "accepted"
        inv.accepted_at = datetime.now(timezone.utc)
        await db.flush()
        return {"joined": True, "user_exists": True}

    # Новый — нужны имя и пароль.
    if not payload.password or not payload.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Укажите имя и пароль")
    user = User(
        email=inv.email, password_hash=hash_password(payload.password),
        name=payload.name, role=inv.role, company_id=cid, is_superadmin=False,
    )
    db.add(user)
    await db.flush()
    db.add(UserCompany(user_id=user.id, company_id=cid,
                       role=inv.role, position=inv.position,
                       party_type=getattr(inv, "party_type", None) or "internal",
                       organization_id=inv.organization_id))
    inv.status = "accepted"
    inv.accepted_at = datetime.now(timezone.utc)
    await db.flush()

    access_token = create_access_token(str(user.id), user.email)
    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=str(user.id), email=user.email, name=user.name, role=user.role,
            company_id=str(cid), is_superadmin=False, created_at=user.created_at,
        ),
    )
