"""
CRUD для каталога типов точек обслуживания (LocationTypeDef).

Тип точки = код + единица + набор полей (схема). Встроенные типы
(company_id IS NULL, is_builtin=true) доступны всем и не удаляются; кастомные
типы компании управляются её админом. Значения полей конкретной точки лежат в
ServiceLocation.extra_metadata. Нижестоящий код опирается на стабильный `code`.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import LocationTypeDef, User
from app.routers.users_router import require_company_admin

router = APIRouter(prefix="/location-types", tags=["Типы точек"])


class LocationTypeIn(BaseModel):
    company_id: str
    code: str
    name: str
    icon: str = "MapPin"
    unit: str = ""
    nomenclature_kind: str = "none"
    fields: list[dict[str, Any]] = Field(default_factory=list)
    sort_order: int = 0


class LocationTypeUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    icon: str | None = None
    unit: str | None = None
    nomenclature_kind: str | None = None
    fields: list[dict[str, Any]] | None = None
    sort_order: int | None = None
    status: str | None = None


class LocationTypeOut(BaseModel):
    id: str
    company_id: str | None = None
    code: str
    name: str
    icon: str
    unit: str
    nomenclature_kind: str
    fields: list[dict[str, Any]]
    is_builtin: bool
    sort_order: int
    status: str
    createdAt: str
    updatedAt: str


def _out(t: LocationTypeDef) -> LocationTypeOut:
    return LocationTypeOut(
        id=str(t.id),
        company_id=str(t.company_id) if t.company_id else None,
        code=t.code, name=t.name, icon=t.icon, unit=t.unit,
        nomenclature_kind=t.nomenclature_kind, fields=t.fields or [],
        is_builtin=t.is_builtin, sort_order=t.sort_order, status=t.status,
        createdAt=t.created_at.isoformat() if t.created_at else "",
        updatedAt=t.updated_at.isoformat() if t.updated_at else "",
    )


@router.get("", response_model=list[LocationTypeOut])
async def list_location_types(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Встроенные типы (company_id IS NULL) + кастомные типы компании."""
    cid = await assert_company_member(company_id, current_user, db)
    res = await db.execute(
        select(LocationTypeDef)
        .where(or_(
            LocationTypeDef.company_id.is_(None),
            LocationTypeDef.company_id == cid,
        ))
        .order_by(LocationTypeDef.sort_order, LocationTypeDef.name)
    )
    return [_out(t) for t in res.scalars().all()]


@router.post("", response_model=LocationTypeOut)
async def create_location_type(
    payload: LocationTypeIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать кастомный тип точки компании (право — админ компании)."""
    cid = await require_company_admin(payload.company_id, current_user, db)
    # Не даём затенить встроенный код — но дубль кастомного отлавливает uq-индекс.
    t = LocationTypeDef(
        company_id=cid, code=payload.code.strip(), name=payload.name.strip(),
        icon=payload.icon or "MapPin", unit=payload.unit or "",
        nomenclature_kind=payload.nomenclature_kind or "none",
        fields=payload.fields or [], is_builtin=False, sort_order=payload.sort_order,
    )
    db.add(t)
    await db.flush()
    return _out(t)


async def _get_type_for_admin(
    type_id: str, current_user: User, db: AsyncSession
) -> LocationTypeDef:
    """Загрузить тип и проверить право: встроенные — только суперадмин,
    кастомные — админ их компании."""
    t = await db.get(LocationTypeDef, type_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тип точки не найден")
    if t.company_id is None:
        if not current_user.is_superadmin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Встроенные типы правит только суперадмин"
            )
    else:
        await require_company_admin(str(t.company_id), current_user, db)
    return t


@router.patch("/{type_id}", response_model=LocationTypeOut)
async def update_location_type(
    type_id: str,
    payload: LocationTypeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    t = await _get_type_for_admin(type_id, current_user, db)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(t, k, v)
    await db.flush()
    # onupdate=func.now() истекает updated_at после flush — перечитываем, чтобы
    # _out не триггерил синхронную дозагрузку (MissingGreenlet).
    await db.refresh(t)
    return _out(t)


@router.delete("/{type_id}")
async def delete_location_type(
    type_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    t = await db.get(LocationTypeDef, type_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тип точки не найден")
    if t.is_builtin or t.company_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Встроенный тип нельзя удалить")
    await require_company_admin(str(t.company_id), current_user, db)
    await db.delete(t)
    return {"ok": True}
