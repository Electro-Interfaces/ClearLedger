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

from app.auth import get_current_user, hash_password
from app.database import get_db
from app.models import Company, User, UserCompany
from app.utils import resolve_company_id
from app.schemas import (
    GrantCompanyBody,
    UserAdminResponse,
    UserAdminUpdate,
    UserCreate,
)

router = APIRouter(prefix="/users", tags=["Пользователи"])


async def require_company_admin(
    company_ref: str, current_user: User, db: AsyncSession
) -> uuid.UUID:
    """Резолвит компанию и проверяет, что текущий пользователь — её админ
    (суперадмин или член с ролью 'admin'). Возвращает UUID, иначе 403."""
    cid = await resolve_company_id(company_ref, db)
    if current_user.is_superadmin:
        return cid
    if current_user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуются права администратора")
    member = await db.execute(
        select(UserCompany.company_id).where(
            UserCompany.user_id == current_user.id,
            UserCompany.company_id == cid,
        )
    )
    if member.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к компании")
    return cid


async def _is_member(user_id: uuid.UUID, cid: uuid.UUID, db: AsyncSession) -> bool:
    res = await db.execute(
        select(UserCompany.company_id).where(
            UserCompany.user_id == user_id, UserCompany.company_id == cid
        )
    )
    return res.scalar_one_or_none() is not None


async def _is_company_admin(user: User, cid: uuid.UUID, db: AsyncSession) -> bool:
    """Может ли user администрировать компанию cid (суперадмин или admin-член)."""
    if user.is_superadmin:
        return True
    return user.role == "admin" and await _is_member(user.id, cid, db)


async def _company_slugs(user_id: uuid.UUID, db: AsyncSession) -> list[str]:
    rows = (
        await db.execute(
            select(Company.slug)
            .join(UserCompany, UserCompany.company_id == Company.id)
            .where(UserCompany.user_id == user_id)
            .order_by(Company.slug)
        )
    ).scalars().all()
    return list(rows)


async def _resp(u: User, db: AsyncSession) -> UserAdminResponse:
    return UserAdminResponse(
        id=str(u.id), email=u.email, name=u.name,
        role=u.role, is_superadmin=u.is_superadmin,
        companies=await _company_slugs(u.id, db),
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
    else:
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
        # Пользователь уже есть — просто выдаём членство в этой компании.
        if not await _is_member(existing.id, cid, db):
            db.add(UserCompany(user_id=existing.id, company_id=cid))
            await db.flush()
        return await _resp(existing, db)

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        role=payload.role,
        company_id=cid,
        is_superadmin=False,
    )
    db.add(user)
    await db.flush()
    db.add(UserCompany(user_id=user.id, company_id=cid))
    await db.flush()
    return await _resp(user, db)


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
        target.name = payload.name
    if payload.role is not None:
        target.role = payload.role
    await db.flush()
    return await _resp(target, db)


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
        db.add(UserCompany(user_id=uid, company_id=cid))
        await db.flush()
    return await _resp(target, db)


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
