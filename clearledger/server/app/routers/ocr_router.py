"""
OCR роутер (Phase D): распознавание текста из изображений и PDF.
Использует Tesseract OCR (subprocess).
"""

import asyncio
import logging
import os
import re
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.auth import get_current_user
from app.config import get_settings
from app.models import User
from app.schemas import OcrField, OcrResponse

logger = logging.getLogger("clearledger.ocr")
settings = get_settings()

router = APIRouter(prefix="/ocr", tags=["OCR"])

# Поддерживаемые MIME-типы
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/bmp",
    "image/webp",
    "application/pdf",
}


def _extract_fields(text: str) -> list[OcrField]:
    """
    Извлекает структурированные поля из OCR-текста.
    Простой rule-based экстрактор для типичных российских документов.
    """
    fields: list[OcrField] = []

    # ИНН (10 или 12 цифр)
    inn_match = re.search(r"ИНН\s*[:\s]*(\d{10,12})", text, re.IGNORECASE)
    if inn_match:
        fields.append(OcrField(
            key="inn", label="ИНН", value=inn_match.group(1), confidence=0.85,
        ))

    # Номер документа
    doc_num = re.search(
        r"(?:№|номер|N|#)\s*[:\s]*([А-Яа-яA-Za-z0-9\-/]+)", text, re.IGNORECASE
    )
    if doc_num:
        fields.append(OcrField(
            key="doc_number", label="Номер документа", value=doc_num.group(1), confidence=0.75,
        ))

    # Дата документа
    date_match = re.search(
        r"(?:от|дата|date)\s*[:\s]*(\d{1,2}[./]\d{1,2}[./]\d{2,4})", text, re.IGNORECASE
    )
    if date_match:
        fields.append(OcrField(
            key="doc_date", label="Дата документа", value=date_match.group(1), confidence=0.8,
        ))

    # Сумма
    amount_match = re.search(
        r"(?:сумма|итого|всего|total|amount)\s*[:\s]*([\d\s]+[.,]\d{2})",
        text,
        re.IGNORECASE,
    )
    if amount_match:
        fields.append(OcrField(
            key="amount", label="Сумма", value=amount_match.group(1).strip(), confidence=0.7,
        ))

    # КПП
    kpp_match = re.search(r"КПП\s*[:\s]*(\d{9})", text, re.IGNORECASE)
    if kpp_match:
        fields.append(OcrField(
            key="kpp", label="КПП", value=kpp_match.group(1), confidence=0.85,
        ))

    return fields


@router.post("", response_model=OcrResponse)
async def recognize_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Распознавание текста из изображения или PDF.

    - Поддерживает: JPEG, PNG, TIFF, BMP, WebP, PDF
    - Лимит: 10 МБ
    - Таймаут: 30 секунд
    - Языки: русский + английский
    """
    if not settings.ocr_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OCR отключён в настройках сервера",
        )

    # Проверка MIME-типа
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Неподдерживаемый тип файла: {content_type}. "
                   f"Поддерживаются: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
        )

    # Чтение файла с проверкой размера
    content = await file.read()
    if len(content) > settings.ocr_max_file_size:
        max_mb = settings.ocr_max_file_size / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой. Максимум: {max_mb:.0f} МБ",
        )

    # Сохраняем во временный файл
    suffix = _get_suffix(content_type)
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        # Запуск Tesseract (async, не блокирует event loop)
        proc = await asyncio.create_subprocess_exec(
            "tesseract",
            tmp_path,
            "stdout",
            "-l", "rus+eng",
            "--oem", "3",
            "--psm", "3",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=settings.ocr_timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"OCR таймаут: превышено {settings.ocr_timeout} секунд",
            )

        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode(errors="replace")
            logger.error("Tesseract ошибка: %s", stderr_text)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка OCR: {stderr_text.strip()[:200]}",
            )

        text = stdout_bytes.decode(errors="replace").strip()
        if not text:
            return OcrResponse(
                text="",
                fields=[],
                confidence=0.0,
                metadata={"warning": "Текст не распознан"},
            )

        # Извлечение полей
        fields = _extract_fields(text)

        # Средняя уверенность
        avg_confidence = (
            sum(f.confidence for f in fields) / len(fields) if fields else 0.5
        )

        return OcrResponse(
            text=text,
            fields=fields,
            confidence=round(avg_confidence, 2),
            metadata={
                "file_name": file.filename or "unknown",
                "file_size": str(len(content)),
                "content_type": content_type,
                "fields_count": str(len(fields)),
            },
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tesseract OCR не установлен на сервере",
        )
    finally:
        # Очистка временного файла
        try:
            os.unlink(tmp_path)
        except (OSError, UnboundLocalError):
            pass


def _get_suffix(content_type: str) -> str:
    """Определяет расширение файла по MIME-типу."""
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/tiff": ".tiff",
        "image/bmp": ".bmp",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }
    return mapping.get(content_type, ".tmp")
