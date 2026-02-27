"""
Intake: загрузка файлов + скачивание сохранённых файлов.
POST /api/intake — загрузка файла, возвращает source_id.
GET /api/files/{file_id} — скачивание файла по ID.
"""

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import SourceFile, User
from app.utils import resolve_company_id_optional

router = APIRouter(tags=["Intake / Файлы"])

# Директория хранения загруженных файлов
UPLOAD_DIR = Path("uploads")


def _ensure_upload_dir() -> None:
    """Создаёт директорию для загрузок, если не существует."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/intake")
async def upload_file(
    file: UploadFile,
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Загрузить файл. Возвращает source_id.
    Файл сохраняется на диск, метаданные — в БД (source_files).
    """
    _ensure_upload_dir()

    content = await file.read()
    file_size = len(content)

    settings = get_settings()
    max_size = settings.ocr_max_file_size
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой ({file_size} байт, максимум {max_size})",
        )

    # SHA-256 fingerprint
    fingerprint = hashlib.sha256(content).hexdigest()

    # Генерируем UUID, сохраняем файл
    file_id = uuid.uuid4()
    ext = Path(file.filename or "file").suffix
    storage_name = f"{file_id}{ext}"
    storage_path = UPLOAD_DIR / storage_name

    with open(storage_path, "wb") as f:
        f.write(content)

    # Определяем company_id (slug или UUID)
    cid = await resolve_company_id_optional(company_id, db)
    if cid is None:
        cid = current_user.company_id

    # Запись в БД
    source = SourceFile(
        id=file_id,
        company_id=cid,
        file_name=file.filename or "unknown",
        mime_type=file.content_type or "application/octet-stream",
        size=file_size,
        storage_path=str(storage_path),
        fingerprint=fingerprint,
    )
    db.add(source)
    await db.flush()

    return {"source_id": str(file_id)}


@router.get("/files/{file_id}")
async def download_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Скачать файл по source_id."""
    try:
        uid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный ID файла")

    result = await db.execute(select(SourceFile).where(SourceFile.id == uid))
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден",
        )

    file_path = Path(source.storage_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден на диске",
        )

    return FileResponse(
        path=str(file_path),
        media_type=source.mime_type,
        filename=source.file_name,
    )
