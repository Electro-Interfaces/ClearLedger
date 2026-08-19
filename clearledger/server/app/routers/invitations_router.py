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
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, get_current_user, hash_password
from app.config import get_settings
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
    company_name: str | None = None,
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
        scope=getattr(inv, "scope", None) or "company",
        company_id=str(inv.company_id),
        company_name=company_name,
    )


async def _accept_targets(inv: Invitation, db: AsyncSession) -> list[uuid.UUID]:
    """В какие организации заводить членство при принятии приглашения.

    `scope=company` — в одну (как было). `scope=space` — во все организации
    пространства: приглашение в пространство именно это и означает.
    """
    if (getattr(inv, "scope", None) or "company") != "space":
        return [inv.company_id]
    ids = [i for (i,) in (await db.execute(select(Company.id))).all()]
    return ids or [inv.company_id]


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
            inviter.name if inviter else None, inv.role, inv.expires_at,
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

    # Приглашение в пространство заводит членство во ВСЕХ организациях контейнера
    # (`_accept_targets`), а право проверено только на одну. Значит администратор
    # одной организации мог выдать себе или третьему лицу доступ ко всем
    # остальным — и с ролью admin, потому что роль и область задаются независимо.
    # Такое решение принимает владелец контейнера, а не администратор компании.
    is_space = (getattr(payload, "scope", None) or "company") == "space"
    if is_space and not current_user.is_superadmin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Приглашение в пространство выдаёт только суперадминистратор: "
            "оно даёт членство во всех организациях контейнера")

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
            party_type=party, organization_id=org_id, scope=payload.scope,
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
        inv.scope = payload.scope
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
    # Приглашения этой организации ПЛЮС приглашения в пространство целиком: последние
    # висят на организации, от имени которой позвали, но касаются всех. Без этого
    # список выглядел пустым у всех организаций, кроме одной, — а человек уже позван.
    rows = (
        await db.execute(
            select(Invitation)
            # Приглашения на всё пространство видит только тот, кто вправе их
            # выдавать: администратору одной организации чужой список ничего не
            # даёт, а email и роль приглашённого показывает.
            .where(Invitation.status == "pending",
                   (Invitation.company_id == cid) if not current_user.is_superadmin
                   else ((Invitation.company_id == cid) | (Invitation.scope == "space")))
            .order_by(Invitation.created_at.desc())
        )
    ).scalars().all()
    # Кто уже работает, того звать не нужно: показывать «ожидает принятия» на
    # действующем сотруднике значит вводить администратора в заблуждение. Такие
    # приглашения могли остаться от заведения человека напрямую или от повторного
    # приглашения; на чтении их скрываем, а при следующем действии они закроются.
    emails = {(i.email or "").strip().lower() for i in rows}
    if emails:
        members = {e.lower() for (e,) in (await db.execute(
            select(User.email).join(UserCompany, UserCompany.user_id == User.id)
            .where(func.lower(User.email).in_(emails),
                   UserCompany.company_id == cid))).all()}
        rows = [i for i in rows if (i.email or "").strip().lower() not in members]
    # Имена организаций пространства — для пометки «выпущено в …» у приглашений,
    # пришедших из другой организации (scope=space).
    companies = {
        c_id: nm for c_id, nm in (await db.execute(
            select(Company.id, Company.name)
            .where(Company.id.in_({i.company_id for i in rows})))).all()
    }
    # Имена компаний-партнёров — одним запросом на весь список, а не по строке.
    org_ids = {i.organization_id for i in rows if i.organization_id}
    names: dict[uuid.UUID, str] = {}
    if org_ids:
        for oid, nm, short in (await db.execute(select(
                Counterparty.id, Counterparty.name, Counterparty.short_name)
                .where(Counterparty.id.in_(org_ids)))).all():
            names[oid] = short or nm
    return [_resp(i, org_name=names.get(i.organization_id) if i.organization_id else None,
                  company_name=companies.get(i.company_id))
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
    """Причина отказа — словами. «Приглашение недействительно» без объяснения
    заставляло людей стучаться админу с «битой ссылкой», хотя чаще всего они
    просто открыли ссылку из предыдущего письма после перевыпуска."""
    inv = (
        await db.execute(select(Invitation).where(Invitation.token_hash == _hash(token)))
    ).scalar_one_or_none()
    if inv is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Ссылка недействительна. Если приглашение отправляли несколько раз, "
            "работает только ссылка из последнего письма. Попросите администратора "
            "выслать приглашение ещё раз.")
    if inv.status == "accepted":
        raise HTTPException(
            status.HTTP_410_GONE,
            "Это приглашение уже принято. Войдите со своим email и паролем; "
            "если пароль забыт — восстановите его на странице входа.")
    if inv.status != "pending":
        raise HTTPException(
            status.HTTP_410_GONE,
            "Приглашение отозвано администратором компании. Если это ошибка — "
            "попросите выслать новое.")
    if inv.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status.HTTP_410_GONE,
            f"Срок действия ссылки истёк: она работает {INVITE_TTL.days} дней "
            "с момента отправки. Попросите администратора выслать приглашение заново.")
    return inv


@router.get("/accept/{token}", response_model=AcceptPreview)
async def preview_invite(token: str, db: AsyncSession = Depends(get_db)):
    inv = await _valid_invite(token, db)
    company = await _company(inv.company_id, db)
    user_exists = (
        await db.execute(select(User.id).where(User.email == inv.email))
    ).scalar_one_or_none() is not None
    # Пространство и организация — разные вещи, и человек обязан видеть, что именно
    # принимает: «Аудит» это ИМЯ ПРОСТРАНСТВА, внутри которого своя практика и
    # обслуживаемые организации. Приглашение в пространство даёт доступ ко всем.
    scope = getattr(inv, "scope", None) or "company"
    space_companies: list[str] = []
    if scope == "space":
        space_companies = [
            n for (n,) in (await db.execute(
                select(Company.name).order_by(Company.name))).all()
        ]
    return AcceptPreview(
        email=inv.email, company_name=company.name, role=inv.role, user_exists=user_exists,
        position=inv.position, expires_at=inv.expires_at,
        scope=scope, space_name=get_settings().ecosystem_brand,
        space_companies=space_companies,
    )


async def close_invites_for(db, email: str, company_id) -> int:
    """Закрыть открытые приглашения человека, который уже стал участником.

    Приглашение это просьба зайти, а не запись о доступе. Человека нередко заводят
    напрямую («Сотрудники» → добавить) или он приходит по второму приглашению, и
    прежнее висит в списке «ожидают принятия» месяцами: на пилоте так висели двое
    уже работающих сотрудников. Закрываем по факту членства, помечая, что вопрос
    снят не переходом по ссылке.
    """
    rows = (await db.execute(select(Invitation).where(
        Invitation.status == "pending",
        func.lower(Invitation.email) == (email or "").strip().lower(),
        (Invitation.company_id == company_id) | (Invitation.scope == "space"),
    ))).scalars().all()
    now = datetime.now(timezone.utc)
    for inv in rows:
        inv.status = "accepted"
        inv.accepted_at = now
    return len(rows)


@router.post("/accept/{token}")
async def accept_invite(
    token: str,
    payload: AcceptInvite,
    db: AsyncSession = Depends(get_db),
):
    inv = await _valid_invite(token, db)
    cid = inv.company_id
    # Должность приглашённый может уточнить сам — админ при приглашении часто
    # пишет её наугад. Зафиксирован только email: он и есть приглашение.
    position = (payload.position or "").strip() or inv.position
    # Приглашение в ПРОСТРАНСТВО заводит членство во всех его организациях: доступ
    # ко всему пространству — это и есть «во все компании», а не «в одну, а дальше
    # как-нибудь». Организации, появившиеся позже, добавляются администратором.
    targets = await _accept_targets(inv, db)

    user = (
        await db.execute(select(User).where(User.email == inv.email))
    ).scalar_one_or_none()

    if user is not None:
        # Существующий — добавляем членство с ролью/должностью, без автологина.
        for target in targets:
            if not await _is_member(user.id, target, db):
                db.add(UserCompany(user_id=user.id, company_id=target,
                                   role=inv.role, position=position,
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
    for target in targets:
        db.add(UserCompany(user_id=user.id, company_id=target,
                           role=inv.role, position=position,
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
