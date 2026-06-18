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
from app.models import User, UserCompany
from app.utils import resolve_company_id
from app.schemas import UserAdminResponse, UserAdminUpdate, UserCreate

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


def _resp(u: User) -> UserAdminResponse:
    return UserAdminResponse(
        id=str(u.id), email=u.email, name=u.name,
        role=u.role, is_superadmin=u.is_superadmin,
    )


@router.get("", response_model=list[UserAdminResponse])
async def list_users(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Пользователи компании (по членству)."""
    cid = await require_company_admin(company_id, current_user, db)
    rows = (
        await db.execute(
            select(User)
            .join(UserCompany, UserCompany.user_id == User.id)
            .where(UserCompany.company_id == cid)
            .order_by(User.email)
        )
    ).scalars().all()
    return [_resp(u) for u in rows]


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
        return _resp(existing)

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
    return _resp(user)


@router.patch("/{user_id}", response_model=UserAdminResponse)
async def update_user(
    user_id: str,
    payload: UserAdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Изменить имя / роль пользователя (в контексте компании админа)."""
    cid = await require_company_admin(payload.company_id, current_user, db)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    target = await db.get(User, uid)
    if target is None or not await _is_member(uid, cid, db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    # Суперадмина через эти эндпоинты не трогаем (только CLI).
    if target.is_superadmin and not current_user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нельзя менять суперадмина")
    if payload.name is not None:
        target.name = payload.name
    if payload.role is not None:
        target.role = payload.role
    await db.flush()
    return _resp(target)


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
