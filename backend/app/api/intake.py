"""Загрузка файлов → Layer 1 + Layer 1a (staging)."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Source, User, RawEntry
from app.schemas.entries import SourceOut
from app.api.deps import get_current_user
from app.services.storage import store_file
from app.services.parser import parse_file
from app.middleware.audit import log_audit

router = APIRouter(prefix="/intake", tags=["intake"])


@router.post("", response_model=SourceOut, status_code=201)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    company_id: str = Form(...),
    category_id: str = Form("uncategorized"),
    subcategory_id: str = Form("other"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Загрузка файла: сохранение в Layer 1 + парсинг в Layer 1a.

    1. Файл → /data/storage/...  (immutable)
    2. Метаданные → public.sources
    3. Парсинг → staging.raw_entries
    4. (позже) staging.sync_queue → облако
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Пустой файл")

    mime_type = file.content_type or "application/octet-stream"

    # 1. Layer 1 — сохранение файла
    file_path, fingerprint, file_size = store_file(
        company_id=company_id,
        category_id=category_id,
        subcategory_id=subcategory_id,
        original_filename=file.filename or "unnamed",
        content=content,
    )

    # 2. public.sources — метаданные файла
    source = Source(
        company_id=company_id,
        file_name=file.filename or "unnamed",
        mime_type=mime_type,
        file_size=file_size,
        file_path=file_path,
        fingerprint=fingerprint,
    )
    db.add(source)
    await db.flush()

    # 3. Layer 1a — парсинг
    parsed = parse_file(content, mime_type, file.filename or "unnamed")

    raw_entry = RawEntry(
        company_id=company_id,
        source_id=source.id,
        file_name=file.filename or "unnamed",
        mime_type=mime_type,
        extracted_text=parsed["extracted_text"],
        extracted_fields=parsed["extracted_fields"],
        page_count=parsed["page_count"],
        processing_status="parsed",
    )
    db.add(raw_entry)

    await db.commit()
    await db.refresh(source)
    await log_audit(user.id, "upload", "source", str(source.id), details={"file_name": file.filename}, ip_address=request.client.host if request.client else None)

    return SourceOut.model_validate(source)


@router.post("/batch", response_model=list[SourceOut], status_code=201)
async def upload_batch(
    files: list[UploadFile] = File(...),
    company_id: str = Form(...),
    category_id: str = Form("uncategorized"),
    subcategory_id: str = Form("other"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Пакетная загрузка нескольких файлов."""
    sources = []

    for file in files:
        content = await file.read()
        if not content:
            continue

        mime_type = file.content_type or "application/octet-stream"

        file_path, fingerprint, file_size = store_file(
            company_id=company_id,
            category_id=category_id,
            subcategory_id=subcategory_id,
            original_filename=file.filename or "unnamed",
            content=content,
        )

        source = Source(
            company_id=company_id,
            file_name=file.filename or "unnamed",
            mime_type=mime_type,
            file_size=file_size,
            file_path=file_path,
            fingerprint=fingerprint,
        )
        db.add(source)
        await db.flush()

        parsed = parse_file(content, mime_type, file.filename or "unnamed")

        raw_entry = RawEntry(
            company_id=company_id,
            source_id=source.id,
            file_name=file.filename or "unnamed",
            mime_type=mime_type,
            extracted_text=parsed["extracted_text"],
            extracted_fields=parsed["extracted_fields"],
            page_count=parsed["page_count"],
            processing_status="parsed",
        )
        db.add(raw_entry)
        sources.append(source)

    await db.commit()
    for s in sources:
        await db.refresh(s)

    return [SourceOut.model_validate(s) for s in sources]
