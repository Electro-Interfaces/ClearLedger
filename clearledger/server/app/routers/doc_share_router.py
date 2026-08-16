"""Показ документа контрагенту по ссылке, без учётки в пространстве.

Зачем это нужно. Контрагент без электронного документооборота не заведёт себе
учётную запись ради двух накладных в квартал, а документ ему показать надо, и
факт получения зафиксировать тоже.

Чего это НЕ даёт. Открытие ссылки и нажатие кнопки — простая электронная подпись
по 63-ФЗ, и юридическую силу она приобретает только тогда, когда порядок её
использования согласован сторонами в договоре. Без такой оговорки в договоре это
счётчик открытий, и продавать его как подпись нельзя.

Ручки намеренно скупы: аноним смотрит и подтверждает получение, но ничего не
меняет. На «нет», «отозвана» и «истекла» ответ одинаковый — подсказывать, что
ссылка когда-то существовала, незачем.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DocCard, DocEvent, DocShareLink, DocVersion, SourceFile

router = APIRouter(prefix="/doc-share", tags=["Документ по ссылке"])

# Текст, под которым человек ставит подтверждение. Хранится вместе с отметкой:
# через два года спор будет не о факте нажатия, а о том, с чем согласились.
ACK_TEXT = ("Подтверждаю получение документа и ознакомление с его содержанием. "
            "Подтверждение равнозначно отметке о получении.")


def new_token() -> str:
    return secrets.token_urlsafe(24)


async def _link_or_404(db: AsyncSession, token: str) -> DocShareLink:
    row = (await db.execute(select(DocShareLink).where(
        DocShareLink.token == token))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None or row.revoked or row.expires_at < now:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка недействительна")
    return row


@router.get("/{token}")
async def open_link(token: str, request: Request,
                    db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Карточка документа для получателя: реквизиты и файлы на скачивание."""
    link = await _link_or_404(db, token)
    doc = await db.get(DocCard, link.doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка недействительна")

    versions = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == doc.id, DocVersion.tombstoned_at.is_(None),
        DocVersion.is_current.is_(True)).order_by(DocVersion.role))).scalars().all()

    link.opened_count += 1
    link.last_opened_at = datetime.now(timezone.utc)
    link.last_ip = (request.client.host if request.client else None)
    await db.commit()

    return {
        "title": doc.title,
        "reg_number": doc.reg_number,
        "reg_date": doc.reg_date.isoformat() if doc.reg_date else None,
        "summary": doc.summary,
        "recipient_name": link.recipient_name,
        "acknowledged_at": link.acknowledged_at.isoformat()
        if link.acknowledged_at else None,
        "ack_text": ACK_TEXT,
        "files": [{"id": str(v.id), "file_name": v.file_name,
                   "size": v.size_bytes} for v in versions],
    }


@router.get("/{token}/file/{version_id}")
async def download(token: str, version_id: str, db: AsyncSession = Depends(get_db)):
    """Скачать файл документа. Отдаём только действующие редакции этого документа:
    ссылка не должна становиться входом в хранилище файлов пространства."""
    link = await _link_or_404(db, token)
    v = (await db.execute(select(DocVersion).where(
        DocVersion.id == version_id, DocVersion.doc_id == link.doc_id,
        DocVersion.tombstoned_at.is_(None)))).scalar_one_or_none()
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")
    sf = await db.get(SourceFile, v.file_id)
    if sf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")
    return FileResponse(path=sf.storage_path, media_type=sf.mime_type or
                        "application/octet-stream", filename=v.file_name)


class AckIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=300)


@router.post("/{token}/ack")
async def acknowledge(token: str, payload: AckIn, request: Request,
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Подтвердить получение.

    Повторное нажатие ничего не меняет: отметка о получении ставится один раз, и
    переписывать её более поздним временем нельзя.
    """
    link = await _link_or_404(db, token)
    if link.acknowledged_at:
        return {"acknowledged_at": link.acknowledged_at.isoformat(), "repeated": True}

    now = datetime.now(timezone.utc)
    ip = request.client.host if request.client else None
    link.acknowledged_at = now
    link.acknowledged_by_name = payload.name.strip()
    link.ack_evidence = {
        "at": now.isoformat(), "ip": ip,
        "user_agent": request.headers.get("user-agent", "")[:300],
        "name": payload.name.strip(),
        # Дословный текст, который человеку показали. Наш пересказ спор не решит.
        "text": ACK_TEXT,
    }
    db.add(DocEvent(doc_id=link.doc_id, kind="dispatch",
                    actor_name=payload.name.strip(),
                    to_value="получение подтверждено",
                    note=f"по ссылке, {ip or 'адрес неизвестен'}"))
    await db.commit()
    return {"acknowledged_at": now.isoformat()}
