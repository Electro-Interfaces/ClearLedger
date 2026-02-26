"""
CRUD + действия жизненного цикла для DataEntry.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import AuditEvent, DataEntry, User
from app.schemas import (
    DataEntryCreate,
    DataEntryResponse,
    DataEntryUpdate,
    PaginatedEntries,
    RejectBody,
    TransferBody,
)

router = APIRouter(prefix="/entries", tags=["Записи"])


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _entry_response(entry: DataEntry) -> DataEntryResponse:
    """Конвертирует ORM DataEntry в схему ответа."""
    return DataEntryResponse(
        id=str(entry.id),
        title=entry.title,
        category_id=entry.category_id,
        subcategory_id=entry.subcategory_id,
        doc_type_id=entry.doc_type_id,
        company_id=str(entry.company_id),
        status=entry.status,
        source=entry.source,
        source_label=entry.source_label,
        file_url=entry.file_url,
        file_type=entry.file_type,
        file_size=entry.file_size,
        metadata=entry.metadata or {},
        ocr_data=entry.ocr_data,
        source_id=entry.source_id,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


async def _get_entry_or_404(
    entry_id: str, db: AsyncSession
) -> DataEntry:
    """Получает запись или бросает 404."""
    try:
        uid = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный ID записи")

    result = await db.execute(select(DataEntry).where(DataEntry.id == uid))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Запись не найдена",
        )
    return entry


async def _create_audit(
    db: AsyncSession,
    user: User,
    action: str,
    company_id: uuid.UUID,
    entry_id: uuid.UUID | None = None,
    details: str | None = None,
) -> None:
    """Создаёт событие аудита."""
    event = AuditEvent(
        entry_id=entry_id,
        company_id=company_id,
        user_id=str(user.id),
        user_name=user.name,
        action=action,
        details=details,
    )
    db.add(event)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=PaginatedEntries)
async def list_entries(
    company_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = Query(None),
    source: str | None = Query(None),
    category_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список записей с фильтрами и пагинацией."""
    query = select(DataEntry)
    count_query = select(func.count(DataEntry.id))

    # Фильтры
    if company_id:
        try:
            cid = uuid.UUID(company_id)
            query = query.where(DataEntry.company_id == cid)
            count_query = count_query.where(DataEntry.company_id == cid)
        except ValueError:
            pass

    if status_filter and status_filter != "all":
        query = query.where(DataEntry.status == status_filter)
        count_query = count_query.where(DataEntry.status == status_filter)

    if source:
        query = query.where(DataEntry.source == source)
        count_query = count_query.where(DataEntry.source == source)

    if category_id:
        query = query.where(DataEntry.category_id == category_id)
        count_query = count_query.where(DataEntry.category_id == category_id)

    if search:
        like_pattern = f"%{search}%"
        search_filter = or_(
            DataEntry.title.ilike(like_pattern),
            DataEntry.source_label.ilike(like_pattern),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if date_from:
        query = query.where(DataEntry.created_at >= date_from)
        count_query = count_query.where(DataEntry.created_at >= date_from)

    if date_to:
        query = query.where(DataEntry.created_at <= date_to)
        count_query = count_query.where(DataEntry.created_at <= date_to)

    # Общее количество
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Пагинация + сортировка
    query = query.order_by(DataEntry.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    entries = result.scalars().all()

    return PaginatedEntries(
        items=[_entry_response(e) for e in entries],
        total=total,
    )


@router.get("/{entry_id}", response_model=DataEntryResponse)
async def get_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Получить запись по ID."""
    entry = await _get_entry_or_404(entry_id, db)
    return _entry_response(entry)


@router.post(
    "",
    response_model=DataEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_entry(
    body: DataEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать новую запись."""
    try:
        cid = uuid.UUID(body.company_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный company_id")

    entry = DataEntry(
        title=body.title,
        category_id=body.category_id,
        subcategory_id=body.subcategory_id,
        doc_type_id=body.doc_type_id,
        company_id=cid,
        status=body.status,
        source=body.source,
        source_label=body.source_label,
        file_url=body.file_url,
        file_type=body.file_type,
        file_size=body.file_size,
        metadata=body.metadata,
        ocr_data=body.ocr_data,
        source_id=body.source_id,
    )
    db.add(entry)
    await db.flush()

    await _create_audit(db, current_user, "created", cid, entry.id)

    return _entry_response(entry)


@router.patch("/{entry_id}", response_model=DataEntryResponse)
async def update_entry(
    entry_id: str,
    body: DataEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Частичное обновление записи."""
    entry = await _get_entry_or_404(entry_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(entry, field, value)

    entry.updated_at = datetime.now(timezone.utc)
    await db.flush()

    await _create_audit(
        db, current_user, "updated", entry.company_id, entry.id,
        details=f"Обновлены поля: {', '.join(update_data.keys())}",
    )

    return _entry_response(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удаление записи (hard delete)."""
    entry = await _get_entry_or_404(entry_id, db)
    company_id = entry.company_id
    await _create_audit(
        db, current_user, "archived", company_id, entry_id,
        details="Запись удалена",
    )
    await db.delete(entry)


# ---------------------------------------------------------------------------
# Действия жизненного цикла
# ---------------------------------------------------------------------------

@router.post("/{entry_id}/verify", response_model=DataEntryResponse)
async def verify_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Верифицировать запись."""
    entry = await _get_entry_or_404(entry_id, db)
    entry.status = "verified"
    entry.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await _create_audit(db, current_user, "verified", entry.company_id, entry.id)
    return _entry_response(entry)


@router.post("/{entry_id}/reject", response_model=DataEntryResponse)
async def reject_entry(
    entry_id: str,
    body: RejectBody | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отклонить запись с опциональной причиной."""
    entry = await _get_entry_or_404(entry_id, db)
    entry.status = "error"
    entry.updated_at = datetime.now(timezone.utc)
    await db.flush()

    reason = body.reason if body else None
    await _create_audit(
        db, current_user, "rejected", entry.company_id, entry.id,
        details=reason,
    )
    return _entry_response(entry)


@router.post("/transfer")
async def transfer_entries(
    body: TransferBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Пакетная передача записей (статус → transferred)."""
    transferred_ids: list[str] = []

    for raw_id in body.ids:
        try:
            uid = uuid.UUID(raw_id)
        except ValueError:
            continue

        result = await db.execute(select(DataEntry).where(DataEntry.id == uid))
        entry = result.scalar_one_or_none()
        if entry and entry.status == "verified":
            entry.status = "transferred"
            entry.updated_at = datetime.now(timezone.utc)
            transferred_ids.append(raw_id)
            await _create_audit(
                db, current_user, "transferred", entry.company_id, entry.id,
            )

    await db.flush()
    return {"transferred": transferred_ids, "count": len(transferred_ids)}


@router.post("/{entry_id}/archive", response_model=DataEntryResponse)
async def archive_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Архивировать запись."""
    entry = await _get_entry_or_404(entry_id, db)
    entry.status = "archived"
    entry.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await _create_audit(db, current_user, "archived", entry.company_id, entry.id)
    return _entry_response(entry)


@router.post("/{entry_id}/restore", response_model=DataEntryResponse)
async def restore_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Восстановить запись из архива (→ new)."""
    entry = await _get_entry_or_404(entry_id, db)
    entry.status = "new"
    entry.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await _create_audit(db, current_user, "restored", entry.company_id, entry.id)
    return _entry_response(entry)


@router.post("/{entry_id}/exclude", response_model=DataEntryResponse)
async def exclude_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Исключить запись."""
    entry = await _get_entry_or_404(entry_id, db)
    # Сохраняем предыдущий статус в metadata
    prev_status = entry.status
    meta = dict(entry.metadata or {})
    meta["_excluded_from"] = prev_status
    entry.metadata = meta
    entry.status = "archived"
    entry.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await _create_audit(
        db, current_user, "excluded", entry.company_id, entry.id,
        details=f"Исключена из статуса: {prev_status}",
    )
    return _entry_response(entry)


@router.post("/{entry_id}/include", response_model=DataEntryResponse)
async def include_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Вернуть ранее исключённую запись."""
    entry = await _get_entry_or_404(entry_id, db)
    meta = dict(entry.metadata or {})
    restore_to = meta.pop("_excluded_from", "new")
    entry.metadata = meta
    entry.status = restore_to
    entry.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await _create_audit(
        db, current_user, "included", entry.company_id, entry.id,
        details=f"Восстановлена в статус: {restore_to}",
    )
    return _entry_response(entry)
