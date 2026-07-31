"""
Подразделения — штатная структура компании в пространстве.

Дерево с руководителями: «кто кому подчиняется и кто за что отвечает». По нему
строится цепочка эскалации (сначала начальник подразделения, потом выше), подача
людей по отделам и, дальше, права на уровне подразделения. Смотреть могут все
члены компании (структура — не секрет внутри организации), менять — админ.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import Department, User, UserCompany
from app.routers.users_router import require_company_admin

router = APIRouter(prefix="/departments", tags=["Подразделения"])


class DepartmentIn(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=200)
    parent_id: str | None = None
    head_user_id: str | None = None


class DepartmentPatch(BaseModel):
    company_id: str
    name: str | None = Field(None, min_length=1, max_length=200)
    # '' — снять значение (None в PATCH значит «не трогать»).
    parent_id: str | None = None
    head_user_id: str | None = None


def _uuid(v: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Невалидный {what}")


@router.get("")
async def list_departments(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    deps = (await db.execute(
        select(Department).where(Department.company_id == cid).order_by(Department.name)
    )).scalars().all()
    heads = {d.head_user_id for d in deps if d.head_user_id}
    names: dict[uuid.UUID, str] = {}
    if heads:
        for uid, name in (await db.execute(
                select(User.id, User.name).where(User.id.in_(heads)))).all():
            names[uid] = name
    counts = dict((await db.execute(
        select(UserCompany.department_id, func.count())
        .where(UserCompany.company_id == cid, UserCompany.department_id.is_not(None))
        .group_by(UserCompany.department_id))).all())
    return {"departments": [{
        "id": str(d.id), "name": d.name,
        "parent_id": str(d.parent_id) if d.parent_id else None,
        "head_user_id": str(d.head_user_id) if d.head_user_id else None,
        "head_name": names.get(d.head_user_id),
        "people": counts.get(d.id, 0),
    } for d in deps]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await require_company_admin(payload.company_id, current_user, db)
    dep = Department(
        id=uuid.uuid4(), company_id=cid, name=payload.name.strip(),
        parent_id=_uuid(payload.parent_id, "parent_id") if payload.parent_id else None,
        head_user_id=_uuid(payload.head_user_id, "head_user_id") if payload.head_user_id else None,
    )
    db.add(dep)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="department.create", target=dep.name)
    await db.flush()
    return {"id": str(dep.id)}


@router.patch("/{department_id}")
async def update_department(
    department_id: str,
    payload: DepartmentPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await require_company_admin(payload.company_id, current_user, db)
    dep = await db.get(Department, _uuid(department_id, "id"))
    if dep is None or dep.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подразделение не найдено")
    if payload.name is not None:
        dep.name = payload.name.strip()
    if payload.parent_id is not None:
        new_parent = _uuid(payload.parent_id, "parent_id") if payload.parent_id else None
        # Петля родителя утопила бы обход дерева — поднимаемся до корня и проверяем.
        seen = {dep.id}
        cur = new_parent
        while cur is not None:
            if cur in seen:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Нельзя подчинить подразделение самому себе")
            seen.add(cur)
            parent = await db.get(Department, cur)
            cur = parent.parent_id if parent else None
        dep.parent_id = new_parent
    if payload.head_user_id is not None:
        dep.head_user_id = (_uuid(payload.head_user_id, "head_user_id")
                            if payload.head_user_id else None)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="department.update", target=dep.name)
    await db.flush()
    return {"ok": True}


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    department_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await require_company_admin(company_id, current_user, db)
    dep = await db.get(Department, _uuid(department_id, "id"))
    if dep is None or dep.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подразделение не найдено")
    # Людей не теряем: membership.department_id и дочерние parent_id уходят в NULL (FK).
    await log_audit(db, actor=current_user, company_id=cid,
                    action="department.delete", target=dep.name)
    await db.delete(dep)
