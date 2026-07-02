"""
Управление пользователями компании (админ компании / суперадмин).

Право управлять пользователями в компании имеет суперадмин ИЛИ член компании
с глобальной ролью 'admin'. Все операции скоупятся по company_id. is_superadmin
через эти эндпоинты НЕ выдаётся (только через CLI grant_company_access.py).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access_catalog import sanitize_modules
from app.audit import log_audit
from app.auth import get_current_user, hash_password, resolve_member_modules
from app.database import get_db
from app.models import Company, CompanyRole, User, UserCompany
from app.utils import resolve_company_id
from app.schemas import (
    CompanyMembership,
    GrantCompanyBody,
    MemberAccessUpdate,
    MemberModulesUpdate,
    UserAdminResponse,
    UserAdminUpdate,
    UserCreate,
)

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
    if scope_cid is not None:
        m = await db.get(UserCompany, (u.id, scope_cid))
        if m is not None:
            role = m.role
            position = m.position
            modules = await resolve_member_modules(m, db)
            if m.role_id is not None:
                r = await db.get(CompanyRole, m.role_id)
                if r is not None:
                    role_id_str = str(r.id)
                    role_name = r.name
    return UserAdminResponse(
        id=str(u.id), email=u.email, name=u.name,
        role=role, position=position, modules=modules,
        role_id=role_id_str, role_name=role_name,
        is_superadmin=u.is_superadmin, companies=memberships,
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

    existing = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        # Пользователь уже есть — выдаём членство в этой компании с ролью.
        if not await _is_member(existing.id, cid, db):
            db.add(UserCompany(user_id=existing.id, company_id=cid,
                               role=payload.role, position=payload.position))
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
                       role=payload.role, position=payload.position))
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid, action="user.create",
                    target=user.email, details={"role": payload.role})
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
    # Роль/должность — per-company (нужен company_id).
    if payload.role is not None or payload.position is not None:
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
