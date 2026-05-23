"""
13 эндпоинтов /api/onec/* — интеграция с 1С:Бухгалтерия 3.0 (БП ГИГ).
Pull-only по идеологии ClearLedger v3 — клиент только ЧИТАЕТ из 1С,
запись в 1С выполняется её собственным расширением, которое тянет данные
из ClearLedger HTTP API.

Эндпоинт #12 (export) оставлен заглушкой со статусом 'not_implemented' —
EnterpriseData XML push реализуется отдельно после стабилизации pull.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import OneCConnection, OneCSyncLog, User
from app.schemas import (
    OneCConnectionCreate,
    OneCConnectionResponse,
    OneCConnectionUpdate,
    OneCSyncLogResponse,
    OneCSyncResult,
    OneCSyncStats,
    OneCSyncStatusResponse,
    OneCTestResult,
)
from app.services.onec.crypto import encrypt_password
from app.services.onec.sync_service import OneCSyncService

router = APIRouter(prefix="/onec", tags=["1С интеграция"])


# ─── маппинг ORM → схема ────────────────────────────────────────────

def _connection_response(c: OneCConnection) -> OneCConnectionResponse:
    return OneCConnectionResponse(
        id=str(c.id),
        company_id=str(c.company_id),
        name=c.name,
        odata_url=c.odata_url,
        username=c.username,
        exchange_path=c.exchange_path,
        status=c.status,
        last_sync_at=c.last_sync_at,
        sync_interval_sec=c.sync_interval_sec,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _synclog_response(log: OneCSyncLog) -> OneCSyncLogResponse:
    return OneCSyncLogResponse(
        id=str(log.id),
        connection_id=str(log.connection_id),
        direction=log.direction,
        sync_type=log.sync_type,
        status=log.status,
        items_processed=log.items_processed,
        items_created=log.items_created,
        items_updated=log.items_updated,
        items_errors=log.items_errors,
        details=log.details or {},
        started_at=log.started_at,
        finished_at=log.finished_at,
    )


async def _get_connection_or_404(connection_id: str, db: AsyncSession) -> OneCConnection:
    try:
        cid = uuid.UUID(connection_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid connection id") from exc
    result = await db.execute(select(OneCConnection).where(OneCConnection.id == cid))
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return conn


def _sync_result_from_log(log: OneCSyncLog) -> OneCSyncResult:
    return OneCSyncResult(
        status=log.status,
        stats=OneCSyncStats(
            processed=log.items_processed,
            created=log.items_created,
            updated=log.items_updated,
            errors=log.items_errors,
        ),
        details=log.details or {},
        log_id=str(log.id),
    )


# ─── 1. GET /onec/connections ───────────────────────────────────────

@router.get("/connections", response_model=list[OneCConnectionResponse])
async def list_connections(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[OneCConnectionResponse]:
    stmt = select(OneCConnection)
    if company_id:
        try:
            stmt = stmt.where(OneCConnection.company_id == uuid.UUID(company_id))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid company_id") from exc
    result = await db.execute(stmt.order_by(OneCConnection.created_at.desc()))
    return [_connection_response(c) for c in result.scalars().all()]


# ─── 2. GET /onec/connections/{id} ──────────────────────────────────

@router.get("/connections/{connection_id}", response_model=OneCConnectionResponse)
async def get_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCConnectionResponse:
    conn = await _get_connection_or_404(connection_id, db)
    return _connection_response(conn)


# ─── 3. POST /onec/connections ──────────────────────────────────────

@router.post("/connections", response_model=OneCConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    payload: OneCConnectionCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCConnectionResponse:
    try:
        cid = uuid.UUID(payload.company_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid company_id") from exc

    conn = OneCConnection(
        id=uuid.uuid4(),
        company_id=cid,
        name=payload.name,
        odata_url=payload.odata_url.rstrip("/"),
        username=payload.username,
        password_encrypted=encrypt_password(payload.password),
        exchange_path=payload.exchange_path,
        sync_interval_sec=payload.sync_interval_sec,
        status="inactive",
    )
    db.add(conn)
    await db.flush()
    await db.refresh(conn)
    return _connection_response(conn)


# ─── 4. PATCH /onec/connections/{id} ────────────────────────────────

@router.patch("/connections/{connection_id}", response_model=OneCConnectionResponse)
async def update_connection(
    connection_id: str,
    payload: OneCConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCConnectionResponse:
    conn = await _get_connection_or_404(connection_id, db)
    if payload.name is not None:
        conn.name = payload.name
    if payload.odata_url is not None:
        conn.odata_url = payload.odata_url.rstrip("/")
    if payload.username is not None:
        conn.username = payload.username
    if payload.password is not None:
        conn.password_encrypted = encrypt_password(payload.password)
    if payload.exchange_path is not None:
        conn.exchange_path = payload.exchange_path
    if payload.sync_interval_sec is not None:
        conn.sync_interval_sec = payload.sync_interval_sec
    if payload.status is not None:
        conn.status = payload.status
    await db.flush()
    await db.refresh(conn)
    return _connection_response(conn)


# ─── 5. DELETE /onec/connections/{id} ───────────────────────────────

@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> None:
    conn = await _get_connection_or_404(connection_id, db)
    await db.delete(conn)


# ─── 6. POST /onec/connections/{id}/test ────────────────────────────

@router.post("/connections/{connection_id}/test", response_model=OneCTestResult)
async def test_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCTestResult:
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    result = await service.test_connection(conn)
    new_status = "active" if result["available"] else "error"
    conn.status = new_status
    await db.flush()
    return OneCTestResult(**result)


# ─── 7-9. POST /onec/connections/{id}/sync/* ────────────────────────

@router.post("/connections/{connection_id}/sync/catalogs", response_model=OneCSyncResult)
async def sync_catalogs(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncResult:
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    log = await service.sync_catalogs(conn)
    conn.last_sync_at = log.finished_at
    await db.flush()
    return _sync_result_from_log(log)


@router.post("/connections/{connection_id}/sync/documents", response_model=OneCSyncResult)
async def sync_documents(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncResult:
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    log = await service.sync_documents(conn)
    conn.last_sync_at = log.finished_at
    await db.flush()
    return _sync_result_from_log(log)


@router.post("/connections/{connection_id}/sync/full", response_model=OneCSyncResult)
async def sync_full(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncResult:
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    log = await service.sync_catalogs(conn)
    conn.last_sync_at = log.finished_at
    await db.flush()
    return _sync_result_from_log(log)


# ─── 10. GET /onec/connections/{id}/sync/status ─────────────────────

@router.get("/connections/{connection_id}/sync/status", response_model=OneCSyncStatusResponse)
async def get_sync_status(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncStatusResponse:
    conn = await _get_connection_or_404(connection_id, db)
    # Текущий лог — самый свежий со статусом running.
    running = (await db.execute(
        select(OneCSyncLog)
        .where(OneCSyncLog.connection_id == conn.id, OneCSyncLog.status == "running")
        .order_by(desc(OneCSyncLog.started_at))
        .limit(1)
    )).scalar_one_or_none()
    return OneCSyncStatusResponse(
        is_syncing=running is not None,
        current_log=_synclog_response(running) if running else None,
        connection_status=conn.status,
        last_sync_at=conn.last_sync_at,
    )


# ─── 11. GET /onec/connections/{id}/history ─────────────────────────

@router.get("/connections/{connection_id}/history", response_model=list[OneCSyncLogResponse])
async def get_sync_history(
    connection_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[OneCSyncLogResponse]:
    conn = await _get_connection_or_404(connection_id, db)
    limit = max(1, min(limit, 200))
    result = await db.execute(
        select(OneCSyncLog)
        .where(OneCSyncLog.connection_id == conn.id)
        .order_by(desc(OneCSyncLog.started_at))
        .limit(limit)
    )
    return [_synclog_response(log) for log in result.scalars().all()]


# ─── 12-13. Экспорт (заглушки) ──────────────────────────────────────
# Идеология v3 предписывает pull со стороны 1С, а не push из ClearLedger.
# Эндпоинты оставлены для совместимости фронта, возвращают not_implemented.

@router.post("/connections/{connection_id}/export")
async def export_to_1c(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    await _get_connection_or_404(connection_id, db)
    return {
        "status": "not_implemented",
        "file_path": None,
        "entries_count": 0,
        "error": "Экспорт в 1С через EnterpriseData XML не реализован. "
                 "По идеологии ClearLedger v3 расширение 1С тянет данные из ClearLedger HTTP API.",
    }


@router.get("/connections/{connection_id}/export/status")
async def get_export_status(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    await _get_connection_or_404(connection_id, db)
    return {"status": "not_implemented", "files": [], "error": None}
