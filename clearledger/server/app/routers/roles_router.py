"""
Именованные роли доступа per-компания (hybrid RBAC).
Системные роли (is_system) — только чтение (нельзя удалять/переименовывать);
кастомные — создание (clone-to-create), правка, удаление админом компании.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access_catalog import sanitize_modules
from app.audit import log_audit
from app.auth import get_current_user
from app.database import get_db
from app.models import CompanyRole, User, UserCompany
from app.routers.users_router import require_company_admin
from app.schemas import CompanyRoleCreate, CompanyRoleResponse, CompanyRoleUpdate

router = APIRouter(prefix="/roles", tags=["Роли доступа"])


def _scope_or_none(value: str | None) -> str | None:
    """Контур переписки роли: код приложения или ничего.

    Пустая строка из формы — это «контура нет», а не приложение с пустым кодом:
    иначе роль получила бы контур, в котором не видно ни одного чата.
    """
    v = (value or "").strip()
    return v or None


async def _to_resp(role: CompanyRole, db: AsyncSession) -> CompanyRoleResponse:
    cnt = (await db.execute(
        select(func.count()).select_from(UserCompany).where(UserCompany.role_id == role.id)
    )).scalar_one()
    return CompanyRoleResponse(
        id=str(role.id), name=role.name, modules=role.modules,
        is_system=role.is_system, members_count=int(cnt or 0),
        chat_scope=role.chat_scope,
    )


@router.get("", response_model=list[CompanyRoleResponse])
async def list_roles(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Роли компании: системные + кастомные, с числом носителей."""
    cid = await require_company_admin(company_id, current_user, db)
    roles = (await db.execute(
        select(CompanyRole).where(CompanyRole.company_id == cid)
        .order_by(CompanyRole.is_system.desc(), CompanyRole.name)
    )).scalars().all()
    return [await _to_resp(r, db) for r in roles]


@router.post("", response_model=CompanyRoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: CompanyRoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать кастомную роль (обычно клонированием шаблона на фронте)."""
    cid = await require_company_admin(payload.company_id, current_user, db)
    dup = (await db.execute(
        select(CompanyRole).where(CompanyRole.company_id == cid, CompanyRole.name == payload.name)
    )).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Роль с таким именем уже есть")
    role = CompanyRole(
        company_id=cid, name=payload.name.strip(),
        modules=sanitize_modules(payload.modules), is_system=False,
        chat_scope=_scope_or_none(payload.chat_scope),
    )
    db.add(role)
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid, action="role.create",
                    target=role.name, details={"modules": role.modules})
    await db.commit()
    return await _to_resp(role, db)


@router.patch("/{role_id}", response_model=CompanyRoleResponse)
async def update_role(
    role_id: str,
    payload: CompanyRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Изменить кастомную роль (имя/модули). Системные — только чтение."""
    cid = await require_company_admin(payload.company_id, current_user, db)
    role = await db.get(CompanyRole, uuid.UUID(role_id))
    if role is None or role.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Роль не найдена")
    if role.is_system:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Системную роль нельзя изменять")
    role.name = payload.name.strip()
    role.modules = sanitize_modules(payload.modules)
    # Контур меняем, только если о нём вообще спросили: старая форма роли поля не
    # знает и не шлёт его — обнулять по умолчанию значило бы молча выпускать
    # контакт-центр в общую переписку при любой правке названия.
    if "chat_scope" in payload.model_fields_set:
        role.chat_scope = _scope_or_none(payload.chat_scope)
    await log_audit(db, actor=current_user, company_id=cid, action="role.update",
                    target=role.name, details={"modules": role.modules})
    await db.commit()
    return await _to_resp(role, db)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удалить кастомную роль. Носители роли → ad-hoc без модулей (role_id=NULL)."""
    cid = await require_company_admin(company_id, current_user, db)
    role = await db.get(CompanyRole, uuid.UUID(role_id))
    if role is None or role.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Роль не найдена")
    if role.is_system:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Системную роль нельзя удалить")
    members = (await db.execute(
        select(UserCompany).where(UserCompany.role_id == role.id)
    )).scalars().all()
    for m in members:
        m.role_id = None  # снятие роли; modules останется как есть (обычно None)
    await log_audit(db, actor=current_user, company_id=cid, action="role.delete",
                    target=role.name, details={"members_reset": len(members)})
    await db.delete(role)
    await db.commit()
