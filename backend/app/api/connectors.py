"""CRUD для коннекторов."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Connector, User
from app.api.deps import get_current_user, require_role

router = APIRouter(prefix="/connectors", tags=["connectors"])


class ConnectorCreate(BaseModel):
    company_id: str
    name: str
    type: str
    url: str = ""
    config: dict = {}
    status: str = "disabled"
    category_id: str
    interval_sec: int = 3600


class ConnectorUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    url: str | None = None
    config: dict | None = None
    status: str | None = None
    category_id: str | None = None
    interval_sec: int | None = None


class ConnectorOut(BaseModel):
    id: UUID
    company_id: str
    name: str
    type: str
    url: str
    config: dict
    status: str
    category_id: str
    interval_sec: int
    last_sync: datetime | None
    records_count: int
    errors_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Список коннекторов."""
    q = select(Connector)
    if company_id:
        q = q.where(Connector.company_id == company_id)
    result = await db.execute(q.order_by(Connector.name))
    return [ConnectorOut.model_validate(c) for c in result.scalars().all()]


@router.get("/{connector_id}", response_model=ConnectorOut)
async def get_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Коннектор по ID."""
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Коннектор не найден")
    return ConnectorOut.model_validate(conn)


@router.post("", response_model=ConnectorOut, status_code=201)
async def create_connector(
    data: ConnectorCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner", "operator")),
):
    """Создать коннектор."""
    conn = Connector(**data.model_dump())
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return ConnectorOut.model_validate(conn)


@router.patch("/{connector_id}", response_model=ConnectorOut)
async def update_connector(
    connector_id: UUID,
    data: ConnectorUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner", "operator")),
):
    """Обновить коннектор."""
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Коннектор не найден")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(conn, field, value)

    await db.commit()
    await db.refresh(conn)
    return ConnectorOut.model_validate(conn)


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner")),
):
    """Удалить коннектор."""
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Коннектор не найден")
    await db.delete(conn)
    await db.commit()
