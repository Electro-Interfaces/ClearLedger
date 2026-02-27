"""
CRUD для коннекторов (интеграции с внешними системами).
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Connector, User
from app.utils import resolve_company_id, resolve_company_id_optional
from app.schemas import ConnectorCreate, ConnectorResponse, ConnectorUpdate

router = APIRouter(prefix="/connectors", tags=["Коннекторы"])


def _connector_response(conn: Connector) -> ConnectorResponse:
    """Конвертирует ORM Connector в схему ответа."""
    return ConnectorResponse(
        id=str(conn.id),
        name=conn.name,
        type=conn.type,
        url=conn.url,
        company_id=str(conn.company_id),
        status=conn.status,
        last_sync=conn.last_sync,
        last_sync_at=conn.last_sync_at,
        sync_status=conn.sync_status,
        records_count=conn.records_count,
        errors_count=conn.errors_count,
        category_id=conn.category_id,
        interval=conn.interval,
        config=conn.config or {},
        created_at=conn.created_at,
    )


async def _get_connector_or_404(
    connector_id: str, db: AsyncSession
) -> Connector:
    """Получает коннектор или бросает 404."""
    try:
        uid = uuid.UUID(connector_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный ID коннектора")

    result = await db.execute(select(Connector).where(Connector.id == uid))
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Коннектор не найден",
        )
    return conn


@router.get("", response_model=list[ConnectorResponse])
async def list_connectors(
    company_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список коннекторов (опционально по компании)."""
    query = select(Connector)

    # Изоляция данных по компании
    cid = await resolve_company_id_optional(company_id, db) or current_user.company_id
    query = query.where(Connector.company_id == cid)

    query = query.order_by(Connector.created_at.desc())
    result = await db.execute(query)
    connectors = result.scalars().all()
    return [_connector_response(c) for c in connectors]


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Получить коннектор по ID."""
    conn = await _get_connector_or_404(connector_id, db)
    return _connector_response(conn)


@router.post(
    "",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_connector(
    body: ConnectorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать новый коннектор."""
    cid = await resolve_company_id(body.company_id, db)

    conn = Connector(
        name=body.name,
        type=body.type,
        url=body.url,
        company_id=cid,
        status=body.status,
        category_id=body.category_id,
        interval=body.interval,
        config=body.config,
    )
    db.add(conn)
    await db.flush()
    return _connector_response(conn)


@router.patch("/{connector_id}", response_model=ConnectorResponse)
async def update_connector(
    connector_id: str,
    body: ConnectorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Частичное обновление коннектора."""
    conn = await _get_connector_or_404(connector_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(conn, field, value)

    await db.flush()
    return _connector_response(conn)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удаление коннектора."""
    conn = await _get_connector_or_404(connector_id, db)
    await db.delete(conn)


@router.post("/{connector_id}/poll")
async def poll_connector(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Запустить синхронизацию (poll) коннектора.
    В текущей версии — обновляет статусы и last_sync_at.
    Реальный polling внешних систем — TODO.
    """
    conn = await _get_connector_or_404(connector_id, db)

    now = datetime.now(timezone.utc)
    conn.sync_status = "syncing"
    conn.last_sync_at = now
    await db.flush()

    # TODO: реальный polling внешнего источника
    # Пока — имитация успешной синхронизации
    conn.sync_status = "synced"
    conn.last_sync = now.isoformat()
    await db.flush()

    return {
        "entries": [],
        "synced_at": now.isoformat(),
        "connector_id": str(conn.id),
    }
