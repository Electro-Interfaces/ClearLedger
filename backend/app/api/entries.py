"""CRUD для записей (public.entries)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Entry, User
from app.schemas.entries import EntryCreate, EntryUpdate, EntryOut, EntryList
from app.api.deps import get_current_user
from app.middleware.audit import log_audit

router = APIRouter(prefix="/entries", tags=["entries"])


@router.get("", response_model=EntryList)
async def list_entries(
    company_id: str | None = None,
    category_id: str | None = None,
    status: str | None = None,
    doc_purpose: str | None = None,
    sync_status: str | None = None,
    search: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Список записей с фильтрацией и пагинацией."""
    q = select(Entry)
    count_q = select(func.count(Entry.id))

    if company_id:
        q = q.where(Entry.company_id == company_id)
        count_q = count_q.where(Entry.company_id == company_id)
    if category_id:
        q = q.where(Entry.category_id == category_id)
        count_q = count_q.where(Entry.category_id == category_id)
    if status:
        q = q.where(Entry.status == status)
        count_q = count_q.where(Entry.status == status)
    if doc_purpose:
        q = q.where(Entry.doc_purpose == doc_purpose)
        count_q = count_q.where(Entry.doc_purpose == doc_purpose)
    if sync_status:
        q = q.where(Entry.sync_status == sync_status)
        count_q = count_q.where(Entry.sync_status == sync_status)
    if search:
        pattern = f"%{search}%"
        q = q.where(Entry.title.ilike(pattern))
        count_q = count_q.where(Entry.title.ilike(pattern))

    total = (await db.execute(count_q)).scalar() or 0
    q = q.order_by(Entry.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    items = [EntryOut.model_validate(e) for e in result.scalars().all()]

    return EntryList(items=items, total=total)


@router.get("/{entry_id}", response_model=EntryOut)
async def get_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Одна запись по ID."""
    result = await db.execute(select(Entry).where(Entry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return EntryOut.model_validate(entry)


@router.post("", response_model=EntryOut, status_code=201)
async def create_entry(
    data: EntryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Создание записи (ручной ввод)."""
    entry = Entry(
        company_id=data.company_id,
        title=data.title,
        category_id=data.category_id,
        subcategory_id=data.subcategory_id,
        doc_type_id=data.doc_type_id,
        source_type=data.source_type,
        source_label=data.source_label,
        metadata_=data.metadata,
        doc_purpose=data.doc_purpose,
        sync_status=data.sync_status,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    await log_audit(user.id, "create", "entry", str(entry.id), ip_address=request.client.host if request.client else None)
    return EntryOut.model_validate(entry)


@router.patch("/{entry_id}", response_model=EntryOut)
async def update_entry(
    entry_id: UUID,
    data: EntryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Обновление записи."""
    result = await db.execute(select(Entry).where(Entry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    update_data = data.model_dump(exclude_unset=True)
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")
    for field, value in update_data.items():
        setattr(entry, field, value)

    await db.commit()
    await db.refresh(entry)
    await log_audit(user.id, "update", "entry", str(entry_id), details=data.model_dump(exclude_unset=True), ip_address=request.client.host if request.client else None)
    return EntryOut.model_validate(entry)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Удаление записи."""
    result = await db.execute(select(Entry).where(Entry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    await db.delete(entry)
    await db.commit()
    await log_audit(user.id, "delete", "entry", str(entry_id), ip_address=request.client.host if request.client else None)
