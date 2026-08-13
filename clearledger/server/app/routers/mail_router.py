"""/api/mail — почтовый коннектор пространства (docs/MAIL.md).

Ящики компании, ручной опрос, переписка нитями. Приём и правила — `mail_intake`;
здесь только вход в него и чтение накопленного.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import Counterparty, MailAccount, MailAttachment, MailMessage, MailThread, User
from app.services import mail_intake

router = APIRouter(prefix="/mail", tags=["Почта пространства"])


class AccountIn(BaseModel):
    address: str
    title: str = ""
    purpose: str | None = None
    mode: str = "both"
    imap_host: str | None = None
    imap_port: int = 993
    imap_folder: str = "INBOX"
    login: str | None = None
    secret_env: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    is_active: bool = True


def _account(a: MailAccount) -> dict[str, Any]:
    return {
        "id": str(a.id), "address": a.address, "title": a.title, "purpose": a.purpose,
        "mode": a.mode, "imapHost": a.imap_host, "imapPort": a.imap_port,
        "imapFolder": a.imap_folder, "login": a.login, "secretEnv": a.secret_env,
        "smtpHost": a.smtp_host, "smtpPort": a.smtp_port, "isActive": a.is_active,
        "lastUid": a.last_uid, "lastSyncAt": a.last_sync_at.isoformat() if a.last_sync_at else None,
        "lastError": a.last_error,
        # Пароль не показываем и не возвращаем никогда — в базе его нет вовсе.
        # Здесь только признак, что переменная окружения на месте: без него
        # «ящик не отвечает» выясняется опросом, а не настройкой.
        "secretPresent": bool(a.secret_env and os.environ.get(a.secret_env)),
    }


@router.get("/accounts")
async def accounts(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Ящики компании с их назначением и состоянием опроса."""
    cid = await assert_company_member(company_id, current_user, db)
    rows = (await db.execute(select(MailAccount).where(
        MailAccount.company_id == cid).order_by(MailAccount.address))).scalars().all()
    return {"rows": [_account(a) for a in rows]}


@router.post("/accounts")
async def create_account(
    company_id: str,
    body: AccountIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_member(company_id, current_user, db)
    a = MailAccount(company_id=cid, **body.model_dump())
    db.add(a)
    await db.commit()
    return _account(a)


@router.put("/accounts/{account_id}")
async def update_account(
    account_id: str,
    company_id: str,
    body: AccountIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_member(company_id, current_user, db)
    a = (await db.execute(select(MailAccount).where(
        MailAccount.company_id == cid, MailAccount.id == account_id))).scalar_one_or_none()
    if a is None:
        return {"error": "not_found"}
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    await db.commit()
    return _account(a)


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_member(company_id, current_user, db)
    a = (await db.execute(select(MailAccount).where(
        MailAccount.company_id == cid, MailAccount.id == account_id))).scalar_one_or_none()
    if a is not None:
        await db.delete(a)
        await db.commit()
    return {"deleted": bool(a)}


@router.post("/poll")
async def poll(
    company_id: str,
    account_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Забрать почту сейчас: один ящик или все активные."""
    cid = await assert_company_member(company_id, current_user, db)
    if account_id:
        a = (await db.execute(select(MailAccount).where(
            MailAccount.company_id == cid, MailAccount.id == account_id))).scalar_one_or_none()
        if a is None:
            return {"error": "not_found"}
        return await mail_intake.poll_account(db, a)
    return await mail_intake.poll_all(db, cid)


@router.get("/threads")
async def threads(
    company_id: str,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Переписка нитями — свежие сверху."""
    cid = await assert_company_member(company_id, current_user, db)
    query = select(MailThread).where(MailThread.company_id == cid)
    if q:
        query = query.where(MailThread.subject.ilike(f"%{q}%"))
    rows = (await db.execute(
        query.order_by(MailThread.last_message_at.desc()).limit(limit))).scalars().all()

    names = {}
    ids = [t.counterparty_id for t in rows if t.counterparty_id]
    if ids:
        names = {c.id: c.name for c in (await db.execute(select(Counterparty).where(
            Counterparty.id.in_(ids)))).scalars().all()}
    return {"rows": [{
        "id": str(t.id), "subject": t.subject, "messages": t.messages_count,
        "lastAt": t.last_message_at.isoformat() if t.last_message_at else None,
        "counterpartyId": str(t.counterparty_id) if t.counterparty_id else None,
        "counterpartyName": names.get(t.counterparty_id),
        "participants": t.participants or [],
    } for t in rows]}


@router.get("/thread")
async def thread(
    company_id: str,
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Письма нити с вложениями."""
    cid = await assert_company_member(company_id, current_user, db)
    msgs = (await db.execute(select(MailMessage).where(
        MailMessage.company_id == cid, MailMessage.thread_id == thread_id)
        .order_by(MailMessage.sent_at))).scalars().all()
    atts: dict[Any, list] = {}
    if msgs:
        for a in (await db.execute(select(MailAttachment).where(
            MailAttachment.company_id == cid,
            MailAttachment.message_id.in_([m.id for m in msgs])))).scalars().all():
            atts.setdefault(a.message_id, []).append({
                "id": str(a.id), "name": a.file_name, "size": a.size,
                "contentType": a.content_type,
            })
    return {"rows": [{
        "id": str(m.id), "direction": m.direction, "subject": m.subject,
        "fromName": m.from_name, "fromEmail": m.from_email, "to": m.to_emails or [],
        "sentAt": m.sent_at.isoformat() if m.sent_at else None,
        "text": m.body_text, "html": m.body_html, "status": m.status,
        "counterpartyId": str(m.counterparty_id) if m.counterparty_id else None,
        "attachments": atts.get(m.id, []),
    } for m in msgs]}


@router.get("/attachment")
async def attachment(
    company_id: str,
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отдать вложение как файл."""
    cid = await assert_company_member(company_id, current_user, db)
    a = (await db.execute(select(MailAttachment).where(
        MailAttachment.company_id == cid,
        MailAttachment.id == attachment_id))).scalar_one_or_none()
    if a is None or a.content is None:
        return Response(status_code=404)
    return Response(
        content=a.content,
        media_type=a.content_type or "application/octet-stream",
        # Имя в заголовке кодируем: кириллица в filename ломает скачивание.
        headers={"Content-Disposition":
                 "attachment; filename*=UTF-8''" + quote(a.file_name)},
    )
