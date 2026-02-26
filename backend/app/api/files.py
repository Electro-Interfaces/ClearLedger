"""Отдача файлов из Layer 1 через API (JWT-защита)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Source, User
from app.api.deps import get_current_user
from app.services.storage import get_file_path

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{source_id}")
async def download_file(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Скачать оригинальный файл по source_id."""
    result = await db.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Файл не найден")

    abs_path = get_file_path(source.file_path)
    return FileResponse(
        abs_path,
        filename=source.file_name,
        media_type=source.mime_type,
    )
