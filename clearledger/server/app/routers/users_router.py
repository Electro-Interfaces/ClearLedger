"""
Управление пользователями компании (админ компании / суперадмин).

Право управлять пользователями в компании имеет суперадмин ИЛИ член компании
с глобальной ролью 'admin'. Все операции скоупятся по company_id. is_superadmin
через эти эндпоинты НЕ выдаётся (только через CLI grant_company_access.py).
"""
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access_catalog import sanitize_modules
from app.audit import log_audit
from app.auth import get_current_user, hash_password, resolve_member_modules
from app.database import get_db
from app.models import (ChatParticipant, ChatRoom, Contract, Counterparty, Company,
                        CompanyRole, Department, ServiceLocation, User, UserCompany)
from app.services import email_service
from app.utils import resolve_company_id, resolve_org_id
from app.schemas import (
    CompanyMembership,
    GrantCompanyBody,
    MemberAccessUpdate,
    MemberContractsUpdate,
    MemberModulesUpdate,
    MemberScopeUpdate,
    StationPinUpdate,
    UserAdminResponse,
    UserAdminUpdate,
    UserCreate,
)
from app.services.station_roster import enqueue_station_roster, refresh_company_rosters

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Пользователи"])


async def _membership_role(user_id: uuid.UUID, cid: uuid.UUID, db: AsyncSession) -> str | None:
    """Роль пользователя в компании (user|admin) или None, если не член."""
    res = await db.execute(
        select(UserCompany.role).where(
            UserCompany.user_id == user_id, UserCompany.company_id == cid
        )
    )
    return res.scalar_one_or_none()


async def require_company_admin(
    company_ref: str, current_user: User, db: AsyncSession
) -> uuid.UUID:
    """Резолвит компанию и проверяет, что текущий пользователь — её админ:
    суперадмин ИЛИ член с ролью 'admin' В ЭТОЙ компании (роль-на-компанию)."""
    cid = await resolve_company_id(company_ref, db)
    if current_user.is_superadmin:
        return cid
    if await _membership_role(current_user.id, cid, db) != "admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Требуются права администратора компании"
        )
    return cid


async def _is_member(user_id: uuid.UUID, cid: uuid.UUID, db: AsyncSession) -> bool:
    return await _membership_role(user_id, cid, db) is not None


async def _is_company_admin(user: User, cid: uuid.UUID, db: AsyncSession) -> bool:
    """Может ли user администрировать компанию cid (суперадмин или admin-член)."""
    if user.is_superadmin:
        return True
    return await _membership_role(user.id, cid, db) == "admin"


async def _memberships(user_id: uuid.UUID, db: AsyncSession) -> list[CompanyMembership]:
    rows = (
        await db.execute(
            select(Company.slug, Company.name, UserCompany.role, UserCompany.position, UserCompany.modules)
            .join(UserCompany, UserCompany.company_id == Company.id)
            .where(UserCompany.user_id == user_id)
            .order_by(Company.slug)
        )
    ).all()
    return [CompanyMembership(slug=s, name=n, role=r, position=p, modules=mods) for s, n, r, p, mods in rows]


async def _resp(
    u: User, db: AsyncSession, scope_cid: uuid.UUID | None = None
) -> UserAdminResponse:
    memberships = await _memberships(u.id, db)
    # role/position: в контексте компании — из членства; иначе глобальная роль.
    role = u.role
    position = None
    modules: list[str] | None = None    # эффективные (с учётом назначенной роли)
    role_id_str: str | None = None
    role_name: str | None = None
    party_type: str | None = None
    org_id: str | None = None
    org_name: str | None = None
    object_scope: list[str] | None = None
    contract_ids: list[str] | None = None
    department_id: str | None = None
    department_name: str | None = None
    if scope_cid is not None:
        m = await db.get(UserCompany, (u.id, scope_cid))
        if m is not None:
            role = m.role
            position = m.position
            if getattr(m, "department_id", None) is not None:
                dep = await db.get(Department, m.department_id)
                if dep is not None:
                    department_id = str(dep.id)
                    department_name = dep.name
            modules = await resolve_member_modules(m, db)
            # Скоуп отдаём как есть: на админа он не действует, но админом человек
            # может перестать быть — заранее заданный список тогда пригодится.
            object_scope = [str(x) for x in (m.object_scope or [])] or None
            # Основание допуска — справка, а не права: отдаём всем, включая админов.
            contract_ids = [str(x) for x in (getattr(m, "contract_ids", None) or [])] or None
            party_type = getattr(m, "party_type", None) or "internal"
            if m.organization_id is not None:
                org = await db.get(Counterparty, m.organization_id)
                if org is not None:
                    org_id = str(org.id)
                    org_name = org.short_name or org.name
            if m.role_id is not None:
                r = await db.get(CompanyRole, m.role_id)
                if r is not None:
                    role_id_str = str(r.id)
                    role_name = r.name
    return UserAdminResponse(
        id=str(u.id), email=u.email, name=u.name,
        role=role, position=position, modules=modules,
        role_id=role_id_str, role_name=role_name, object_scope=object_scope,
        contract_ids=contract_ids,
        department_id=department_id, department_name=department_name,
        party_type=party_type, organization_id=org_id, organization_name=org_name,
        is_superadmin=u.is_superadmin, last_seen_at=u.last_seen_at, companies=memberships,
        has_station_pin=bool(u.station_pin_hash),
    )


@router.get("", response_model=list[UserAdminResponse])
async def list_users(
    company_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Пользователи. С company_id — члены компании (нужны права админа компании).
    Без company_id — ВСЕ пользователи системы (только суперадмин) для админ-раздела."""
    if company_id:
        cid = await require_company_admin(company_id, current_user, db)
        rows = (
            await db.execute(
                select(User)
                .join(UserCompany, UserCompany.user_id == User.id)
                .where(UserCompany.company_id == cid)
                .order_by(User.email)
            )
        ).scalars().all()
        return [await _resp(u, db, scope_cid=cid) for u in rows]
    if not current_user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только суперадмин видит всех пользователей")
    rows = (await db.execute(select(User).order_by(User.email))).scalars().all()
    return [await _resp(u, db) for u in rows]


@router.post("", response_model=UserAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать пользователя в компании (или добавить существующего по email)."""
    cid = await require_company_admin(payload.company_id, current_user, db)

    # Принадлежность и организация — часть создания: партнёра заводят сразу партнёром.
    party = payload.party_type or "internal"
    org_id = await resolve_org_id(payload.organization_id, cid, db) if party != "internal" else None

    existing = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        # Пользователь уже есть — выдаём членство в этой компании с ролью.
        if not await _is_member(existing.id, cid, db):
            db.add(UserCompany(user_id=existing.id, company_id=cid,
                               role=payload.role, position=payload.position,
                               party_type=party, organization_id=org_id))
            await db.flush()
        return await _resp(existing, db, scope_cid=cid)

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        role=payload.role,            # глобальная роль — легаси-дефолт
        company_id=cid,
        is_superadmin=False,
    )
    db.add(user)
    await db.flush()
    db.add(UserCompany(user_id=user.id, company_id=cid,
                       role=payload.role, position=payload.position,
                       party_type=party, organization_id=org_id))
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid, action="user.create",
                    target=user.email, details={"role": payload.role, "partyType": party})
    return await _resp(user, db, scope_cid=cid)


@router.patch("/{user_id}", response_model=UserAdminResponse)
async def update_user(
    user_id: str,
    payload: UserAdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Изменить имя / роль пользователя. С company_id — админ компании в её
    контексте; без company_id — суперадмин (любой пользователь)."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    if payload.company_id:
        cid = await require_company_admin(payload.company_id, current_user, db)
        target = await db.get(User, uid)
        if target is None or not await _is_member(uid, cid, db):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    elif current_user.is_superadmin:
        target = await db.get(User, uid)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Укажите company_id")
    # Суперадмина через эти эндпоинты не трогаем (только CLI).
    if target.is_superadmin and not current_user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нельзя менять суперадмина")
    if payload.name is not None:
        target.name = payload.name   # ФИО — глобально
    # Роль/должность/принадлежность/подразделение — per-company (нужен company_id).
    if (payload.role is not None or payload.position is not None
            or payload.party_type is not None or payload.organization_id is not None
            or payload.department_id is not None):
        if not payload.company_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Укажите company_id для роли/должности")
        membership = await db.get(UserCompany, (uid, cid))
        if membership is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не в компании")
        if payload.role is not None and payload.role != membership.role:
            membership.role = payload.role
            await log_audit(db, actor=current_user, company_id=cid, action="member.role",
                            target=target.email, details={"role": payload.role})
        if payload.position is not None:
            membership.position = payload.position or None  # "" → очистить
        if payload.party_type is not None and payload.party_type != getattr(membership, "party_type", None):
            membership.party_type = payload.party_type
            # Свой сотрудник не представляет внешнюю организацию — связь снимаем,
            # иначе в чатах остался бы висеть ярлык подрядчика.
            if payload.party_type == "internal":
                membership.organization_id = None
            await log_audit(db, actor=current_user, company_id=cid, action="member.party",
                            target=target.email, details={"partyType": payload.party_type})
        if payload.organization_id is not None:
            membership.organization_id = await resolve_org_id(payload.organization_id, cid, db)
        if payload.department_id is not None:
            if payload.department_id == "":
                membership.department_id = None
            else:
                dep = await db.get(Department, uuid.UUID(payload.department_id))
                if dep is None or dep.company_id != cid:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Подразделение не найдено")
                membership.department_id = dep.id
    await db.flush()
    return await _resp(target, db, scope_cid=cid if payload.company_id else None)


@router.put("/{user_id}/modules", response_model=UserAdminResponse)
async def set_member_modules(
    user_id: str,
    payload: MemberModulesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Назначить члену компании набор модулей доступа (RBAC).
    modules=null → полный доступ. Требует прав админа компании."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    cid = await require_company_admin(payload.company_id, current_user, db)
    membership = await db.get(UserCompany, (uid, cid))
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не член компании")
    target = await db.get(User, uid)
    if target is not None and target.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нельзя ограничивать суперадмина")
    # admin-члену модули не ограничиваем (у него полный доступ по роли).
    membership.modules = None if membership.role == "admin" else sanitize_modules(payload.modules)
    membership.role_id = None  # ad-hoc набор отменяет назначенную роль
    await db.flush()
    return await _resp(target, db, scope_cid=cid)


@router.put("/{user_id}/access", response_model=UserAdminResponse)
async def set_member_access(
    user_id: str,
    payload: MemberAccessUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Назначить доступ члену: именованная роль (mode=role) ИЛИ ad-hoc модули (mode=custom)."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    cid = await require_company_admin(payload.company_id, current_user, db)
    m = await db.get(UserCompany, (uid, cid))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не член компании")
    target = await db.get(User, uid)
    if target is not None and target.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нельзя ограничивать суперадмина")
    if m.role == "admin":
        m.role_id = None
        m.modules = None
        detail = "администратор — полный доступ"
    elif payload.mode == "role":
        role = await db.get(CompanyRole, uuid.UUID(payload.role_id)) if payload.role_id else None
        if role is None or role.company_id != cid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Роль не найдена")
        m.role_id = role.id
        m.modules = None
        detail = f"роль «{role.name}»"
    else:  # custom
        m.role_id = None
        m.modules = sanitize_modules(payload.modules)
        detail = "модули: " + (", ".join(m.modules) if m.modules else "все")
    await log_audit(db, actor=current_user, company_id=cid, action="member.access",
                    target=(target.email if target else user_id), details={"set": detail})
    await db.commit()
    return await _resp(target, db, scope_cid=cid)


@router.put("/{user_id}/scope", response_model=UserAdminResponse)
async def set_member_scope(
    user_id: str,
    payload: MemberScopeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Скоуп данных участника: объекты, по которым он видит данные.

    Пустой список приравнивается к «вся сеть» — сохранять «не видит ничего» через
    эту ручку нельзя: такой доступ отбирают ролью, а не скоупом, и молчаливая
    пустота выглядела бы как сломанные экраны.
    """
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    cid = await require_company_admin(payload.company_id, current_user, db)
    m = await db.get(UserCompany, (uid, cid))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не член компании")
    target = await db.get(User, uid)
    # `service_locations.id` — строковый nanoid, не UUID; валидация здесь одна:
    # объект должен принадлежать этой компании. Чужой id ничего не открыл бы (запросы
    # и так фильтруются по company_id), но и хранить его незачем.
    raw_ids = [str(x).strip() for x in (payload.object_scope or []) if str(x).strip()]
    ids: list[str] = []
    if raw_ids:
        own = (await db.execute(select(ServiceLocation.id).where(
            ServiceLocation.company_id == cid, ServiceLocation.id.in_(raw_ids)))).scalars().all()
        ids = [str(x) for x in own]
    m.object_scope = ids or None
    await log_audit(db, actor=current_user, company_id=cid, action="member.scope",
                    target=(target.email if target else user_id),
                    details={"objects": len(ids) if ids else "вся сеть"})
    # Смена скоупа меняет состав ростеров станций: кто теперь видит станцию —
    # тот и должен уметь войти на её рабочем месте. Ростер вторичен: сбой его
    # доставки не должен ронять запись скоупа.
    try:
        await refresh_company_rosters(db, cid)
    except Exception:
        logger.exception("ростер станций не переспущен после смены скоупа")
    await db.commit()
    return await _resp(target, db, scope_cid=cid)


@router.put("/{user_id}/station-pin", response_model=UserAdminResponse)
async def set_station_pin(
    user_id: str,
    payload: StationPinUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """PIN станции участника: короткий код входа на рабочем месте АЗС (edge).

    Пустой pin снимает PIN. После изменения ростеры станций компании
    переспускаются, чтобы новый bcrypt-хеш доехал до касс.
    """
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    cid = await require_company_admin(payload.company_id, current_user, db)
    if await db.get(UserCompany, (uid, cid)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не член компании")
    target = await db.get(User, uid)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    pin = (payload.pin or "").strip()
    if pin:
        if not pin.isdigit() or not (4 <= len(pin) <= 8):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "PIN — от 4 до 8 цифр")
        target.station_pin_hash = hash_password(pin)
    else:
        target.station_pin_hash = None
    await log_audit(db, actor=current_user, company_id=cid, action="member.station_pin",
                    target=target.email, details={"pin": "задан" if pin else "снят"})
    try:
        await refresh_company_rosters(db, cid)
    except Exception:
        logger.exception("ростер станций не переспущен после смены PIN")
    await db.commit()
    return await _resp(target, db, scope_cid=cid)


@router.post("/station/{station_id}/roster/push")
async def push_station_roster(
    station_id: int,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Принудительно переспустить ростер профилей на станцию (админ компании).

    Обычно ростер обновляется сам при смене PIN или скоупа; эта ручка — для
    первичной заливки на станцию и ручной пересинхронизации.
    """
    cid = await require_company_admin(company_id, current_user, db)
    n = await enqueue_station_roster(db, cid, station_id)
    await db.commit()
    return {"station_id": station_id, "profiles": n}


@router.put("/{user_id}/contracts", response_model=UserAdminResponse)
async def set_member_contracts(
    user_id: str,
    payload: MemberContractsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Основание допуска участника: договоры, по которым он работает в пространстве.

    Справка, а не права: список ничего не открывает и не закрывает — он отвечает на
    вопрос «на каком основании этот человек здесь». Поэтому пустой список законен и
    означает «основание не указано», а не «доступа нет».
    """
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    cid = await require_company_admin(payload.company_id, current_user, db)
    m = await db.get(UserCompany, (uid, cid))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не член компании")
    target = await db.get(User, uid)
    # Договор обязан быть из этой же компании: иначе в карточке человека появилось бы
    # основание из чужого пространства, и понять, откуда оно, было бы нельзя.
    ids: list[str] = []
    raw = [str(x).strip() for x in (payload.contract_ids or []) if str(x).strip()]
    if raw:
        try:
            wanted = [uuid.UUID(x) for x in raw]
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID договора")
        own = (await db.execute(select(Contract.id).where(
            Contract.company_id == cid, Contract.id.in_(wanted)))).scalars().all()
        ids = [str(x) for x in own]
    m.contract_ids = ids or None
    await log_audit(db, actor=current_user, company_id=cid, action="member.contracts",
                    target=(target.email if target else user_id),
                    details={"contracts": len(ids) if ids else "не указано"})
    await db.commit()
    return await _resp(target, db, scope_cid=cid)


@router.post("/{user_id}/reset-link")
async def issue_reset_link(
    user_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ссылка сброса пароля — админу компании, для передачи мессенджером.

    Восстановление живёт только письмом, и когда почта до человека не доходит
    (спам-фильтры, перенесённые пользователи, не знающие пароля), вход закрыт
    наглухо: пригласительная ссылка существующему говорит «войдите с паролем».
    Пароль админ не видит и не задаёт — только одноразовая ссылка, по которой
    человек сам поставит новый. Тот же механизм, что «Забыли пароль».
    """
    cid = await require_company_admin(company_id, current_user, db)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    user = await db.get(User, uid)
    if user is None or not await _is_member(uid, cid, db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if user.is_superadmin and not current_user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Ссылку для суперадмина выдаёт только суперадмин")
    raw = secrets.token_urlsafe(32)
    user.reset_token_hash = hashlib.sha256(raw.encode()).hexdigest()
    # Сутки, а не час письменного потока: ссылку передают мессенджером,
    # и открывают её не сразу.
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    user.reset_token_expires = expires
    await log_audit(db, actor=current_user, company_id=cid,
                    action="auth.reset_link_issued", target=user.email)
    await db.flush()
    return {"reset_url": email_service.reset_link(raw), "expires_at": expires}


async def _leave_company_chats(uid: uuid.UUID, cid: uuid.UUID, db: AsyncSession) -> None:
    """Вывести человека из всех чатов компании при отзыве членства.

    Иначе уволенный остаётся в «Общем чате» и в личных переписках: доступа к
    приложениям у него уже нет, а переписку он читает и в неё пишет — членство
    в комнате самостоятельно, `ensure_company_rooms` его не пересматривает.
    Личные переписки тоже: у второй стороны история остаётся, у ушедшего — нет.
    """
    await db.execute(delete(ChatParticipant).where(
        ChatParticipant.user_id == uid,
        ChatParticipant.room_id.in_(select(ChatRoom.id).where(ChatRoom.company_id == cid)),
    ))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(
    user_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Убрать пользователя из компании (отзыв членства). Если членств не
    осталось и это не суперадмин — удаляем запись пользователя."""
    cid = await require_company_admin(company_id, current_user, db)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    if uid == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя удалить самого себя")
    target = await db.get(User, uid)
    if target is None or not await _is_member(uid, cid, db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if target.is_superadmin and not current_user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нельзя удалить суперадмина")

    # Отзыв членства.
    membership = await db.get(UserCompany, (uid, cid))
    if membership:
        await db.delete(membership)
        await db.flush()
    await _leave_company_chats(uid, cid, db)
    await log_audit(db, actor=current_user, company_id=cid, action="user.remove", target=target.email)
    # Остались ли ещё членства?
    remaining = (
        await db.execute(
            select(UserCompany.company_id).where(UserCompany.user_id == uid)
        )
    ).first()
    if remaining is None and not target.is_superadmin:
        await db.delete(target)


@router.post("/{user_id}/companies", response_model=UserAdminResponse)
async def grant_company(
    user_id: str,
    payload: GrantCompanyBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Выдать пользователю членство в компании (админ этой компании / суперадмин)."""
    cid = await require_company_admin(payload.company_id, current_user, db)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    target = await db.get(User, uid)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if not await _is_member(uid, cid, db):
        db.add(UserCompany(user_id=uid, company_id=cid, role=payload.role))
        await db.flush()
    return await _resp(target, db, scope_cid=cid)


@router.delete("/{user_id}/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_company(
    user_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отозвать членство пользователя в компании (без удаления самой записи)."""
    cid = await require_company_admin(company_id, current_user, db)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    target = await db.get(User, uid)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if target.is_superadmin and not current_user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нельзя менять суперадмина")
    membership = await db.get(UserCompany, (uid, cid))
    if membership:
        await db.delete(membership)
        await db.flush()
    await _leave_company_chats(uid, cid, db)
