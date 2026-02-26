"""CRUD для связей между документами (document_links)."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import DocumentLink, User
from app.api.deps import get_current_user

router = APIRouter(prefix="/document-links", tags=["document-links"])


class LinkCreate(BaseModel):
    source_entry_id: UUID
    target_entry_id: UUID
    link_type: str
    label: str | None = None


class LinkOut(BaseModel):
    id: UUID
    source_entry_id: UUID
    target_entry_id: UUID
    link_type: str
    label: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/entry/{entry_id}", response_model=list[LinkOut])
async def get_links_for_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Все связи для записи (как source, так и target)."""
    result = await db.execute(
        select(DocumentLink).where(
            or_(
                DocumentLink.source_entry_id == entry_id,
                DocumentLink.target_entry_id == entry_id,
            )
        )
    )
    return [LinkOut.model_validate(l) for l in result.scalars().all()]


@router.post("", response_model=LinkOut, status_code=201)
async def create_link(
    data: LinkCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Создать связь между документами."""
    link = DocumentLink(
        source_entry_id=data.source_entry_id,
        target_entry_id=data.target_entry_id,
        link_type=data.link_type,
        label=data.label,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return LinkOut.model_validate(link)


@router.delete("/{link_id}", status_code=204)
async def delete_link(
    link_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Удалить связь."""
    result = await db.execute(select(DocumentLink).where(DocumentLink.id == link_id))
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Связь не найдена")
    await db.delete(link)
    await db.commit()
