"""
CRUD для ServiceLocation (точки обслуживания) — АЗС/магазины/офисы/склады.

Перенесено из localStorage фронта в бэкенд: точки общие для всех браузеров и
совпадают с конфигом каналов. Публичный (как sources/channels), company-scoped.
id — клиентский nanoid (String), чтобы фронт и бэк совпадали.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.deps import CompanyDep, get_owned
from app.models import ServiceLocation, User

router = APIRouter(prefix="/locations", tags=["Точки обслуживания"])


class LocationIn(BaseModel):
    id: str
    company_id: str
    code: str
    name: str
    type: str = "other"
    status: str = "active"
    address: str | None = None
    description: str | None = None
    sourceBindings: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class LocationUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    type: str | None = None
    status: str | None = None
    address: str | None = None
    description: str | None = None
    sourceBindings: list[Any] | None = None
    metadata: dict[str, Any] | None = None


class LocationOut(BaseModel):
    id: str
    code: str
    name: str
    type: str
    status: str
    address: str | None = None
    description: str | None = None
    sourceBindings: list[Any]
    metadata: dict[str, Any] | None = None
    createdAt: str
    updatedAt: str


def _out(l: ServiceLocation) -> LocationOut:
    return LocationOut(
        id=l.id, code=l.code, name=l.name, type=l.type, status=l.status,
        address=l.address, description=l.description,
        sourceBindings=l.source_bindings or [],
        metadata=l.extra_metadata,
        createdAt=l.created_at.isoformat() if l.created_at else "",
        updatedAt=l.updated_at.isoformat() if l.updated_at else "",
    )


@router.get("", response_model=list[LocationOut])
async def list_locations(cid: CompanyDep, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == cid)
        .order_by(ServiceLocation.code)
    )
    return [_out(l) for l in res.scalars().all()]


@router.post("", response_model=LocationOut)
async def create_location(
    payload: LocationIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(payload.company_id, current_user, db)
    existing = await db.get(ServiceLocation, payload.id)
    if existing:
        # upsert по клиентскому id — но чужую точку (другой компании) перехватить
        # нельзя: get_owned бросит 404, если нет членства в её компании.
        await get_owned(ServiceLocation, payload.id, current_user, db)
        existing.company_id = cid
        existing.code = payload.code
        existing.name = payload.name
        existing.type = payload.type
        existing.status = payload.status
        existing.address = payload.address
        existing.description = payload.description
        existing.source_bindings = payload.sourceBindings
        existing.extra_metadata = payload.metadata
        loc = existing
    else:
        loc = ServiceLocation(
            id=payload.id, company_id=cid, code=payload.code, name=payload.name,
            type=payload.type, status=payload.status, address=payload.address,
            description=payload.description, source_bindings=payload.sourceBindings,
            extra_metadata=payload.metadata,
        )
        db.add(loc)
    await db.flush()
    # onupdate=func.now() истекает updated_at после flush на UPDATE-ветке upsert
    # → _out не должен триггерить синхронную дозагрузку (MissingGreenlet).
    await db.refresh(loc)
    return _out(loc)


@router.patch("/{location_id}", response_model=LocationOut)
async def update_location(
    location_id: str,
    payload: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = await get_owned(ServiceLocation, location_id, current_user, db)
    data = payload.model_dump(exclude_unset=True)
    if "sourceBindings" in data:
        loc.source_bindings = data.pop("sourceBindings")
    if "metadata" in data:
        loc.extra_metadata = data.pop("metadata")
    for k, v in data.items():
        setattr(loc, k, v)
    await db.flush()
    await db.refresh(loc)
    return _out(loc)


@router.delete("/{location_id}")
async def delete_location(
    location_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = await get_owned(ServiceLocation, location_id, current_user, db)
    await db.delete(loc)
    return {"ok": True}
