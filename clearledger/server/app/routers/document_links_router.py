"""
CRUD для связей между документами (DocumentLink).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.deps import get_owned
from app.models import DocumentLink, DataEntry, User
from app.schemas import DocumentLinkCreate, DocumentLinkResponse

router = APIRouter(prefix="/document-links", tags=["Связи документов"])


def _link_response(link: DocumentLink) -> DocumentLinkResponse:
    """Конвертирует ORM DocumentLink в схему ответа."""
    return DocumentLinkResponse(
        id=str(link.id),
        source_entry_id=str(link.source_entry_id),
        target_entry_id=str(link.target_entry_id),
        link_type=link.link_type,
        label=link.label,
        created_at=link.created_at,
    )


@router.get("", response_model=list[DocumentLinkResponse])
async def list_links(
    link_type: str | None = Query(None),
    company_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список связей с фильтрами по типу и компании."""
    query = select(DocumentLink)

    if link_type:
        query = query.where(DocumentLink.link_type == link_type)

    # Изоляция данных по компании (проверяем членство при явном company_id)
    if company_id:
        cid = await assert_company_member(company_id, current_user, db)
    else:
        cid = current_user.company_id
        if cid is None:
            raise HTTPException(status_code=400, detail="Укажите company_id")
    query = query.join(
        DataEntry,
        or_(
            DocumentLink.source_entry_id == DataEntry.id,
            DocumentLink.target_entry_id == DataEntry.id,
        ),
    ).where(DataEntry.company_id == cid)

    query = query.order_by(DocumentLink.created_at.desc())
    result = await db.execute(query)
    links = result.scalars().unique().all()
    return [_link_response(l) for l in links]


@router.get("/entry/{entry_id}", response_model=list[DocumentLinkResponse])
async def get_links_for_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Все связи для конкретной записи (как source или target)."""
    try:
        uid = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный ID записи")

    # Изоляция: доступ к связям только для своей записи (иначе 404).
    await get_owned(DataEntry, uid, current_user, db)

    query = select(DocumentLink).where(
        or_(
            DocumentLink.source_entry_id == uid,
            DocumentLink.target_entry_id == uid,
        )
    ).order_by(DocumentLink.created_at.desc())

    result = await db.execute(query)
    links = result.scalars().all()
    return [_link_response(l) for l in links]


@router.post(
    "",
    response_model=DocumentLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_link(
    body: DocumentLinkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать связь между двумя записями."""
    try:
        src_id = uuid.UUID(body.source_entry_id)
        tgt_id = uuid.UUID(body.target_entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидные ID записей")

    # Изоляция: обе записи должны принадлежать доступной компании (иначе 404).
    src_entry = await get_owned(DataEntry, src_id, current_user, db)
    tgt_entry = await get_owned(DataEntry, tgt_id, current_user, db)
    if src_entry.company_id != tgt_entry.company_id:
        raise HTTPException(status_code=400, detail="Записи из разных компаний")

    # Проверяем дубликат
    existing = await db.execute(
        select(DocumentLink).where(
            DocumentLink.link_type == body.link_type,
            or_(
                (DocumentLink.source_entry_id == src_id) & (DocumentLink.target_entry_id == tgt_id),
                (DocumentLink.source_entry_id == tgt_id) & (DocumentLink.target_entry_id == src_id),
            ),
        )
    )
    found = existing.scalar_one_or_none()
    if found:
        return _link_response(found)

    link = DocumentLink(
        source_entry_id=src_id,
        target_entry_id=tgt_id,
        link_type=body.link_type,
        label=body.label,
    )
    db.add(link)
    await db.flush()
    return _link_response(link)


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    link_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удалить связь."""
    try:
        uid = uuid.UUID(link_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный ID связи")

    result = await db.execute(select(DocumentLink).where(DocumentLink.id == uid))
    link = result.scalar_one_or_none()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Связь не найдена",
        )
    # Изоляция: связь принадлежит компании своих записей — проверяем членство.
    await get_owned(DataEntry, link.source_entry_id, current_user, db)
    await db.delete(link)
