"""API-эндпоинты интеграции 1С."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import OneCConnection, OneCSyncLog, User
from app.api.deps import get_current_user, require_role
from app.schemas.onec import (
    OneCConnectionCreate, OneCConnectionUpdate, OneCConnectionOut,
    OneCTestResult, OneCSyncLogOut, SyncResult,
    ExportResult, ExportFeedback,
)
from app.services.onec.crypto import encrypt_password, decrypt_password
from app.services.onec.odata_client import ODataClient
from app.services.onec.sync_service import sync_catalogs, sync_documents, sync_full

router = APIRouter(prefix="/onec", tags=["onec"])


# ── Подключения CRUD ──────────────────────────────────────

@router.get("/connections", response_model=list[OneCConnectionOut])
async def list_connections(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Список подключений 1С."""
    q = select(OneCConnection)
    if company_id:
        q = q.where(OneCConnection.company_id == company_id)
    result = await db.execute(q.order_by(OneCConnection.name))
    return [OneCConnectionOut.model_validate(c) for c in result.scalars().all()]


@router.get("/connections/{connection_id}", response_model=OneCConnectionOut)
async def get_connection(
    connection_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Детали подключения."""
    result = await db.execute(
        select(OneCConnection).where(OneCConnection.id == connection_id)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение 1С не найдено")
    return OneCConnectionOut.model_validate(conn)


@router.post("/connections", response_model=OneCConnectionOut, status_code=201)
async def create_connection(
    data: OneCConnectionCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner", "operator")),
):
    """Создать подключение 1С."""
    conn = OneCConnection(
        company_id=data.company_id,
        name=data.name,
        odata_url=data.odata_url,
        username=data.username,
        password_encrypted=encrypt_password(data.password),
        exchange_path=data.exchange_path,
        sync_interval_sec=data.sync_interval_sec,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return OneCConnectionOut.model_validate(conn)


@router.patch("/connections/{connection_id}", response_model=OneCConnectionOut)
async def update_connection(
    connection_id: UUID,
    data: OneCConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner", "operator")),
):
    """Обновить подключение 1С."""
    result = await db.execute(
        select(OneCConnection).where(OneCConnection.id == connection_id)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение 1С не найдено")

    update_data = data.model_dump(exclude_unset=True)

    # Если обновляют пароль — шифруем
    if "password" in update_data:
        conn.password_encrypted = encrypt_password(update_data.pop("password"))

    for field, value in update_data.items():
        setattr(conn, field, value)

    await db.commit()
    await db.refresh(conn)
    return OneCConnectionOut.model_validate(conn)


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner")),
):
    """Удалить подключение 1С."""
    result = await db.execute(
        select(OneCConnection).where(OneCConnection.id == connection_id)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение 1С не найдено")
    await db.delete(conn)
    await db.commit()


# ── Тест подключения ──────────────────────────────────────

@router.post("/connections/{connection_id}/test", response_model=OneCTestResult)
async def test_connection(
    connection_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Тест подключения к 1С (GET $metadata)."""
    result = await db.execute(
        select(OneCConnection).where(OneCConnection.id == connection_id)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение 1С не найдено")

    password = decrypt_password(conn.password_encrypted)
    async with ODataClient(conn.odata_url, conn.username, password) as client:
        check = await client.check_availability()

    return OneCTestResult(**check)


# ── Синхронизация ─────────────────────────────────────────

@router.post("/connections/{connection_id}/sync/catalogs", response_model=SyncResult)
async def sync_catalogs_endpoint(
    connection_id: UUID,
    _user: User = Depends(require_role("admin", "owner", "operator")),
):
    """Синхронизировать справочники из 1С."""
    try:
        result = await sync_catalogs(connection_id)
        return SyncResult(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/connections/{connection_id}/sync/documents", response_model=SyncResult)
async def sync_documents_endpoint(
    connection_id: UUID,
    _user: User = Depends(require_role("admin", "owner", "operator")),
):
    """Синхронизировать документы из 1С."""
    try:
        result = await sync_documents(connection_id)
        return SyncResult(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/connections/{connection_id}/sync/full", response_model=SyncResult)
async def sync_full_endpoint(
    connection_id: UUID,
    _user: User = Depends(require_role("admin", "owner", "operator")),
):
    """Полная синхронизация: справочники + документы."""
    try:
        result = await sync_full(connection_id)
        return SyncResult(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Статус и история ──────────────────────────────────────

@router.get("/connections/{connection_id}/sync/status")
async def sync_status(
    connection_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Текущий статус синхронизации (последний running или последний завершённый)."""
    # Проверяем что подключение существует
    conn_result = await db.execute(
        select(OneCConnection).where(OneCConnection.id == connection_id)
    )
    conn = conn_result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение 1С не найдено")

    # Ищем running лог
    result = await db.execute(
        select(OneCSyncLog).where(
            OneCSyncLog.connection_id == connection_id,
            OneCSyncLog.status == "running",
        ).order_by(desc(OneCSyncLog.started_at)).limit(1)
    )
    running = result.scalar_one_or_none()

    if running:
        return {
            "is_syncing": True,
            "current_log": OneCSyncLogOut.model_validate(running),
            "connection_status": conn.status,
            "last_sync_at": conn.last_sync_at,
        }

    # Последний завершённый
    result = await db.execute(
        select(OneCSyncLog).where(
            OneCSyncLog.connection_id == connection_id,
        ).order_by(desc(OneCSyncLog.started_at)).limit(1)
    )
    last = result.scalar_one_or_none()

    return {
        "is_syncing": False,
        "current_log": OneCSyncLogOut.model_validate(last) if last else None,
        "connection_status": conn.status,
        "last_sync_at": conn.last_sync_at,
    }


@router.get("/connections/{connection_id}/history", response_model=list[OneCSyncLogOut])
async def sync_history(
    connection_id: UUID,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """История синхронизаций."""
    result = await db.execute(
        select(OneCSyncLog).where(
            OneCSyncLog.connection_id == connection_id,
        ).order_by(desc(OneCSyncLog.started_at)).limit(limit)
    )
    return [OneCSyncLogOut.model_validate(log) for log in result.scalars().all()]


# ── Экспорт в 1С (Фаза 3) ────────────────────────────────

@router.post("/connections/{connection_id}/export", response_model=ExportResult)
async def export_to_1c(
    connection_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner", "operator")),
):
    """Экспорт верифицированных записей в папку обмена 1С (EnterpriseData XML)."""
    from app.services.onec.file_exchange import export_verified_entries

    result = await db.execute(
        select(OneCConnection).where(OneCConnection.id == connection_id)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение 1С не найдено")
    if not conn.exchange_path:
        raise HTTPException(status_code=400, detail="Папка обмена не настроена")

    export_result = await export_verified_entries(conn)
    return ExportResult(**export_result)


@router.get("/connections/{connection_id}/export/status", response_model=ExportFeedback)
async def export_status(
    connection_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Проверить feedback от 1С (файлы status_*.xml в from_1c/)."""
    from app.services.onec.file_exchange import check_feedback

    result = await db.execute(
        select(OneCConnection).where(OneCConnection.id == connection_id)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Подключение 1С не найдено")
    if not conn.exchange_path:
        raise HTTPException(status_code=400, detail="Папка обмена не настроена")

    feedback = await check_feedback(conn)
    return ExportFeedback(**feedback)
