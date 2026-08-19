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

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    DocApproval, DocCard, DocEvent, DocKind, DocShareLink, DocVersion, Organization,
    SourceFile,
)
from app.services import external_approval

router = APIRouter(prefix="/doc-share", tags=["Документ по ссылке"])

# Текст, под которым человек ставит подтверждение. Хранится вместе с отметкой:
# через два года спор будет не о факте нажатия, а о том, с чем согласились.
ACK_TEXT = ("Подтверждаю получение документа и ознакомление с его содержанием. "
            "Подтверждение равнозначно отметке о получении.")
PUBLIC_ERROR_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}


def new_token() -> str:
    return secrets.token_urlsafe(24)


def token_hash(token: str) -> str:
    """Хеш токена — то, что хранится в базе вместо самого токена."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


async def _link_or_404(db: AsyncSession, token: str,
                       for_update: bool = False) -> DocShareLink:
    # Ищем по хешу; колонка прежнего открытого токена остаётся запасным путём,
    # пока бэкфилл не проставил хеши всем выданным ссылкам.
    statement = select(DocShareLink).where(
        (DocShareLink.token_hash == token_hash(token)) | (DocShareLink.token == token))
    if for_update:
        statement = statement.execution_options(
            populate_existing=True).with_for_update()
    row = (await db.execute(statement)).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if (row is None or row.revoked or row.expires_at < now or
            row.version_snapshot is None or row.card_snapshot is None):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка недействительна",
                            headers=PUBLIC_ERROR_HEADERS)
    doc = await db.get(DocCard, row.doc_id)
    if doc is None or doc.confidentiality == "strict":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка недействительна",
                            headers=PUBLIC_ERROR_HEADERS)
    return row


async def _shared_versions(db: AsyncSession,
                           link: DocShareLink) -> list[tuple[DocVersion, dict]]:
    snapshot = link.version_snapshot or []
    ids = [item.get("id") for item in snapshot if item.get("id")]
    if not ids:
        return []
    rows = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == link.doc_id, DocVersion.id.in_(ids)))).scalars().all()
    by_id = {str(row.id): row for row in rows}
    return [(by_id[item["id"]], item) for item in snapshot if item["id"] in by_id]


@router.get("/verify/{token}")
async def verify_registration(token: str, response: Response,
                              db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Проверить только запись в журнале, без доступа к карточке и файлам."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    if len(token) > 64:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена",
                            headers=PUBLIC_ERROR_HEADERS)
    doc = (await db.execute(select(DocCard).where(
        DocCard.verify_token == token, DocCard.reg_number.is_not(None)
    ))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена",
                            headers=PUBLIC_ERROR_HEADERS)

    checked_at = datetime.now(timezone.utc).isoformat()
    if doc.confidentiality in {"private", "strict"}:
        return {
            "record_status": "restricted", "checked_at": checked_at,
            "message": "Сведения о документе ограничены политикой доступа организации.",
            "disclaimer": "Код подтверждает только обращение к записи в системе и не является электронной подписью.",
        }

    organization = (await db.get(Organization, doc.organization_id)
                    if doc.organization_id else None)
    kind = await db.get(DocKind, doc.kind_id)
    versions = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == doc.id, DocVersion.tombstoned_at.is_(None),
        DocVersion.is_current.is_(True)).order_by(
        DocVersion.role, DocVersion.revision))).scalars().all()
    return {
        "record_status": "cancelled" if doc.status == "cancelled" else "registered",
        "organization": ({"name": organization.name, "inn": organization.inn,
                          "kpp": organization.kpp} if organization else None),
        "kind": kind.name if kind else doc.kind_code,
        "reg_number": doc.reg_number,
        "reg_date": doc.reg_date.isoformat() if doc.reg_date else None,
        "document_status": doc.status,
        "current_revision": doc.current_revision,
        "files": [{"role": row.role, "revision": row.revision,
                   "algorithm": "SHA-256", "sha256": row.sha256} for row in versions],
        "signature_status": "not_checked",
        "checked_at": checked_at,
        "disclaimer": ("Найдена запись с указанными реквизитами. Это не проверка "
                       "электронной подписи и не подтверждение юридической силы копии."),
    }


@router.get("/{token}")
async def open_link(token: str, request: Request, response: Response,
                    db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Карточка документа для получателя: реквизиты и файлы на скачивание."""
    response.headers.update(PUBLIC_ERROR_HEADERS)
    link = await _link_or_404(db, token, for_update=True)
    doc = await db.get(DocCard, link.doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка недействительна",
                            headers=PUBLIC_ERROR_HEADERS)

    versions = await _shared_versions(db, link)
    card = link.card_snapshot or {
        "title": doc.title, "reg_number": doc.reg_number,
        "reg_date": doc.reg_date.isoformat() if doc.reg_date else None,
        "summary": doc.summary,
    }

    link.opened_count += 1
    link.last_opened_at = datetime.now(timezone.utc)
    link.last_ip = (request.client.host if request.client else None)
    await db.commit()

    return {
        "title": card.get("title"),
        "reg_number": card.get("reg_number"),
        "reg_date": card.get("reg_date"),
        "summary": card.get("summary"),
        "recipient_name": link.recipient_name,
        "acknowledged_at": link.acknowledged_at.isoformat()
        if link.acknowledged_at else None,
        "ack_text": ACK_TEXT,
        # Ссылка на визу говорит о себе прямо: человек должен понимать, что от
        # него хотят подписи, ещё до того, как нажмёт кнопку.
        "purpose": link.purpose,
        "approval": await _approval_view(db, link),
        "files": [{"id": str(v.id),
                   "file_name": snapshot.get("file_name") or v.file_name,
                   "size": snapshot.get("size") or v.size_bytes}
                  for v, snapshot in versions],
    }


@router.get("/{token}/file/{version_id}")
async def download(token: str, version_id: str, db: AsyncSession = Depends(get_db)):
    """Скачать файл документа. Отдаём только действующие редакции этого документа:
    ссылка не должна становиться входом в хранилище файлов пространства."""
    link = await _link_or_404(db, token, for_update=True)
    allowed = ({item.get("id") for item in link.version_snapshot}
               if link.version_snapshot is not None else
               {str(v.id) for v, _ in await _shared_versions(db, link)})
    if version_id not in allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден",
                            headers=PUBLIC_ERROR_HEADERS)
    v = (await db.execute(select(DocVersion).where(
        DocVersion.id == version_id, DocVersion.doc_id == link.doc_id,
        DocVersion.archive_purged_at.is_(None),
    ))).scalar_one_or_none()
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден",
                            headers=PUBLIC_ERROR_HEADERS)
    sf = await db.get(SourceFile, v.file_id)
    if sf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден",
                            headers=PUBLIC_ERROR_HEADERS)
    return FileResponse(path=sf.storage_path, media_type=sf.mime_type or
                        "application/octet-stream", filename=v.file_name,
                        headers=PUBLIC_ERROR_HEADERS)


async def _approval_view(db: AsyncSession, link: DocShareLink) -> dict[str, Any] | None:
    """Что именно просят согласовать. Пусто, если ссылка только на показ."""
    if link.purpose != "approve" or not link.approval_id:
        return None
    row = await db.get(DocApproval, link.approval_id)
    if row is None:
        return None
    return {
        "step_name": row.step_name,
        "round": row.round,
        "status": row.status,
        "used_at": link.used_at.isoformat() if link.used_at else None,
        # Тексты показываем оба: человек видит, под чем распишется в каждом случае.
        "approve_text": external_approval.APPROVE_TEXT,
        "reject_text": external_approval.REJECT_TEXT,
    }


class AckIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=300)


@router.post("/{token}/ack")
async def acknowledge(token: str, payload: AckIn, request: Request, response: Response,
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Подтвердить получение.

    Повторное нажатие ничего не меняет: отметка о получении ставится один раз, и
    переписывать её более поздним временем нельзя.
    """
    response.headers.update(PUBLIC_ERROR_HEADERS)
    link = await _link_or_404(db, token, for_update=True)
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
        "files": link.version_snapshot,
        "card": link.card_snapshot,
    }
    db.add(DocEvent(doc_id=link.doc_id, kind="dispatch",
                    actor_name=payload.name.strip(),
                    to_value="получение подтверждено",
                    note=f"по ссылке, {ip or 'адрес неизвестен'}"))
    await db.commit()
    return {"acknowledged_at": now.isoformat()}


class DecideIn(BaseModel):
    """Решение внешнего участника.

    Имя обязательно и не подставляется из ссылки: подписывает человек, а ссылку
    ему мог переслать кто угодно, и в доказательстве должно стоять то имя,
    которое он назвал сам.
    """

    name: str = Field(..., min_length=2, max_length=300)
    approved: bool
    comment: str | None = Field(None, max_length=2000)


@router.post("/{token}/decide")
async def decide_by_link(token: str, payload: DecideIn, request: Request,
                         response: Response,
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Поставить визу по ссылке — одну, на одном шаге, один раз.

    Проверки срока и отзыва делает `_link_or_404` при каждом обращении: отозванная
    ссылка перестаёт работать в ту же секунду, а не со следующего выпуска.
    """
    response.headers.update(PUBLIC_ERROR_HEADERS)
    link = await _link_or_404(db, token, for_update=True)
    try:
        result = await external_approval.decide(
            db, link, approved=payload.approved, signer_name=payload.name,
            comment=payload.comment,
            ip=(request.client.host if request.client else None),
            user_agent=request.headers.get("user-agent"))
    except external_approval.ExternalApprovalError as exc:
        # Причину называем: человек снаружи не может посмотреть журнал и обязан
        # понять, чинить ему что-то или просить новую ссылку.
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc),
                            headers=PUBLIC_ERROR_HEADERS) from exc
    await db.commit()
    return result
