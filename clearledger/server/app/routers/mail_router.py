"""/api/mail — почтовый коннектор пространства (docs/MAIL.md).

Ящики компании, ручной опрос, переписка нитями. Приём и правила — `mail_intake`;
здесь только вход в него и чтение накопленного.
"""
from __future__ import annotations

import os
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_product, get_current_user
from app.routers.users_router import require_company_admin
from app.database import get_db
from app.models import (
    ChatRoom, Contract, Counterparty, CounterpartyEmail, DocCard, MailAccount,
    MailAttachment, MailMessage, MailRule, MailThread, User,
)
from app.services import mail_intake, mail_secrets, mail_send

router = APIRouter(prefix="/mail", tags=["Почта пространства"])


async def _mail_scope(company_id: str, user: User, db: AsyncSession):
    """Компания запроса + право на продукт «Подключения».

    Членства мало: в переписке компании лежат договоры во вложениях, реквизиты и
    ответы контрагентов, а участником пространства бывает и внешний подрядчик.
    Суперадмин, админ организации и роль без ограничений проходят как раньше.
    """
    return await assert_company_product(company_id, user, db, "connect")


class AccountIn(BaseModel):
    address: str
    title: str = ""
    purpose: str | None = None
    mode: str = "both"
    imap_host: str | None = None
    imap_port: int = 993
    imap_folder: str = "INBOX"
    imap_security: str = "ssl"
    login: str | None = None
    # Пароль вводит сотрудник; в базу он ложится зашифрованным ключом стека.
    # Пустая строка означает «не менять» — иначе редактирование ящика ради смены
    # подписи стирало бы пароль.
    password: str | None = None
    secret_env: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_security: str = "starttls"
    display_name: str | None = None
    signature: str | None = None
    poll_interval_min: int = 15
    is_active: bool = True


def _check_secret_env(name: str | None) -> None:
    """Имя переменной окружения приходит из формы, а читаем мы её из окружения
    контейнера. Без ограничения в это поле можно было вписать `SECRET_KEY` или
    `DATABASE_URL`, указать свой IMAP-сервер без шифрования — и бэкенд отправил бы
    значение наружу командой LOGIN. Пароли ящиков живут под префиксом `MAIL_`.
    """
    if name and not mail_secrets.secret_env_allowed(name):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Переменная с паролем ящика должна начинаться с MAIL_ "
            "(и не быть служебной переменной почты платформы)")


def _account(a: MailAccount) -> dict[str, Any]:
    return {
        "id": str(a.id), "address": a.address, "title": a.title, "purpose": a.purpose,
        "mode": a.mode, "imapHost": a.imap_host, "imapPort": a.imap_port,
        "imapFolder": a.imap_folder, "login": a.login, "secretEnv": a.secret_env,
        "smtpHost": a.smtp_host, "smtpPort": a.smtp_port,
        "smtpSecurity": a.smtp_security, "imapSecurity": a.imap_security,
        "displayName": a.display_name, "signature": a.signature,
        "pollIntervalMin": a.poll_interval_min, "isActive": a.is_active,
        # Пароль не отдаём никогда — только признак, что он задан.
        "passwordSet": bool(a.password_enc),
        "lastUid": a.last_uid, "lastSyncAt": a.last_sync_at.isoformat() if a.last_sync_at else None,
        "lastError": a.last_error,
        # Признак, что переменная окружения на месте (для ящиков, настроенных
        # внедренцем): без него «ящик не отвечает» выясняется опросом, а не настройкой.
        "secretPresent": bool(a.secret_env and os.environ.get(a.secret_env)),
    }


@router.get("/accounts")
async def accounts(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Ящики компании с их назначением и состоянием опроса."""
    cid = await _mail_scope(company_id, current_user, db)
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
    cid = await require_company_admin(company_id, current_user, db)
    data = body.model_dump()
    password = data.pop("password", None)
    _check_secret_env(data.get("secret_env"))
    a = MailAccount(company_id=cid, **data)
    if password:
        a.password_enc = mail_secrets.encrypt(password)
    db.add(a)
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid, action="mail.account.create",
                    target=a.address, details={"imap": a.imap_host, "mode": a.mode})
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
    cid = await require_company_admin(company_id, current_user, db)
    a = (await db.execute(select(MailAccount).where(
        MailAccount.company_id == cid, MailAccount.id == account_id))).scalar_one_or_none()
    if a is None:
        return {"error": "not_found"}
    data = body.model_dump()
    password = data.pop("password", None)
    _check_secret_env(data.get("secret_env"))
    for k, v in data.items():
        setattr(a, k, v)
    # Пустое поле пароля — «оставить как было»: правка подписи не должна стирать
    # доступ к ящику.
    if password:
        a.password_enc = mail_secrets.encrypt(password)
    await log_audit(db, actor=current_user, company_id=cid, action="mail.account.update",
                    target=a.address, details={"imap": a.imap_host, "mode": a.mode,
                                               "password_changed": bool(password)})
    await db.commit()
    return _account(a)


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await require_company_admin(company_id, current_user, db)
    a = (await db.execute(select(MailAccount).where(
        MailAccount.company_id == cid, MailAccount.id == account_id))).scalar_one_or_none()
    if a is not None:
        await log_audit(db, actor=current_user, company_id=cid,
                        action="mail.account.delete", target=a.address)
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
    cid = await _mail_scope(company_id, current_user, db)
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
    cid = await _mail_scope(company_id, current_user, db)
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
    cid = await _mail_scope(company_id, current_user, db)
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
                # Разобранное вложение помечено пакетом приёмки: видно, что
                # документы из письма уже поехали в разбор.
                "intakeBatchId": str(a.intake_batch_id) if a.intake_batch_id else None,
            })
    doc_refs = {f"mail:{m.message_id or m.id}": m.id for m in msgs}
    routed_docs = {
        doc_refs[row.source_ref]: str(row.id)
        for row in (await db.execute(select(DocCard).where(
            DocCard.company_id == cid, DocCard.source == "mail",
            DocCard.source_ref.in_(doc_refs),
        ))).scalars().all()
        if row.source_ref in doc_refs
    } if doc_refs else {}
    return {"rows": [{
        "id": str(m.id), "direction": m.direction, "subject": m.subject,
        "fromName": m.from_name, "fromEmail": m.from_email, "to": m.to_emails or [],
        "sentAt": m.sent_at.isoformat() if m.sent_at else None,
        "text": m.body_text, "html": m.body_html, "status": m.status,
        "counterpartyId": str(m.counterparty_id) if m.counterparty_id else None,
        # Куда письмо уехало: в комнату, задачу, заявку или приёмку.
        "routedTo": m.routed_to,
        "routedDocId": routed_docs.get(m.id),
        "routeError": m.route_error,
        "routeAttempts": m.route_attempts,
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
    cid = await _mail_scope(company_id, current_user, db)
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


@router.post("/messages/{message_id}/retry-route")
async def retry_route(
    message_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await require_company_admin(company_id, current_user, db)
    row = (await db.execute(select(MailMessage).where(
        MailMessage.company_id == cid,
        MailMessage.id == message_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Письмо не найдено")
    if row.routed_to == "duplicate":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Системный дубль письма повторно не маршрутизируется")
    if row.status in ("quarantine", "rejected"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала примите письмо из карантина")
    delivered = await mail_intake.retry_doc_route(db, cid, row)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="mail.route.retry", target=str(row.id),
                    details={"delivered": delivered, "error": row.route_error})
    await db.commit()
    return {"delivered": delivered, "routedTo": row.routed_to,
            "error": row.route_error}


# ── Волна 2: опознание и правила ─────────────────────────────────────────────

class RuleIn(BaseModel):
    name: str = ""
    account_id: str | None = None
    sort: int = 100
    from_email: str | None = None
    from_domain: str | None = None
    subject_like: str | None = None
    has_attachment: bool | None = None
    unknown_sender: bool | None = None
    action: str = Field("archive", pattern="^(intake|ticket|chat|task|doc|archive|quarantine|reject)$")
    set_counterparty_id: str | None = None
    set_contract_id: str | None = None
    set_room_id: str | None = None
    set_object_id: str | None = None
    is_active: bool = True


def _rule(r: MailRule) -> dict[str, Any]:
    return {
        "id": str(r.id), "name": r.name, "sort": r.sort,
        "accountId": str(r.account_id) if r.account_id else None,
        "fromEmail": r.from_email, "fromDomain": r.from_domain,
        "subjectLike": r.subject_like, "hasAttachment": r.has_attachment,
        "unknownSender": r.unknown_sender, "action": r.action,
        "setCounterpartyId": str(r.set_counterparty_id) if r.set_counterparty_id else None,
        "setContractId": str(r.set_contract_id) if r.set_contract_id else None,
        "setRoomId": str(r.set_room_id) if r.set_room_id else None,
        "setObjectId": r.set_object_id,
        "isActive": r.is_active, "hits": r.hits,
    }


async def _validate_rule_refs(db: AsyncSession, cid, body: RuleIn) -> None:
    for model, raw, label in (
        (MailAccount, body.account_id, "Почтовый ящик"),
        (Counterparty, body.set_counterparty_id, "Контрагент"),
        (Contract, body.set_contract_id, "Договор"),
        (ChatRoom, body.set_room_id, "Комната"),
    ):
        if not raw:
            continue
        try:
            ref = uuid.UUID(str(raw))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"{label}: неверный идентификатор") from exc
        row = await db.get(model, ref)
        if row is None or row.company_id != cid:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} не найден")
    if body.action == "chat" and not body.set_room_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Для правила «в чат» выберите комнату")
    if body.action == "ticket" and not (body.set_object_id or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Для заявки укажите объект")
    if body.action == "doc" and body.unknown_sender is True \
            and not body.set_counterparty_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Неизвестному отправителю нельзя создавать документ без контрагента")


@router.get("/rules")
async def rules(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Правила по порядку: первое сработавшее решает судьбу письма."""
    cid = await _mail_scope(company_id, current_user, db)
    rows = (await db.execute(select(MailRule).where(
        MailRule.company_id == cid).order_by(
            MailRule.sort, MailRule.created_at, MailRule.id))).scalars().all()
    return {"rows": [_rule(r) for r in rows]}


@router.post("/rules")
async def create_rule(
    company_id: str,
    body: RuleIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await require_company_admin(company_id, current_user, db)
    await _validate_rule_refs(db, cid, body)
    r = MailRule(company_id=cid, **body.model_dump())
    db.add(r)
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid,
                    action="mail.rule.create", target=str(r.id),
                    details={"name": r.name, "action": r.action, "sort": r.sort})
    await db.commit()
    return _rule(r)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    company_id: str,
    body: RuleIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await require_company_admin(company_id, current_user, db)
    await _validate_rule_refs(db, cid, body)
    r = (await db.execute(select(MailRule).where(
        MailRule.company_id == cid, MailRule.id == rule_id))).scalar_one_or_none()
    if r is None:
        return {"error": "not_found"}
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="mail.rule.update", target=str(r.id),
                    details={"name": r.name, "action": r.action, "sort": r.sort})
    await db.commit()
    return _rule(r)


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await require_company_admin(company_id, current_user, db)
    r = (await db.execute(select(MailRule).where(
        MailRule.company_id == cid, MailRule.id == rule_id))).scalar_one_or_none()
    if r is not None:
        await log_audit(db, actor=current_user, company_id=cid,
                        action="mail.rule.delete", target=str(r.id),
                        details={"name": r.name, "action": r.action})
        await db.delete(r)
        await db.commit()
    return {"deleted": bool(r)}


class LearnIn(BaseModel):
    address: str
    counterparty_id: str


@router.post("/learn-address")
async def learn_address(
    company_id: str,
    body: LearnIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Это письмо от такого-то»: запомнить адрес и применить к прошлой переписке."""
    cid = await require_company_admin(company_id, current_user, db)
    try:
        counterparty_id = uuid.UUID(body.counterparty_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Неверный идентификатор контрагента") from exc
    counterparty = await db.get(Counterparty, counterparty_id)
    if counterparty is None or counterparty.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Контрагент не найден")
    result = await mail_intake.learn_address(
        db, cid, body.address, counterparty_id, current_user.email)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="mail.address.learn", target=result["address"],
                    details={"counterparty_id": str(counterparty_id)})
    await db.commit()
    return result


@router.get("/addresses")
async def addresses(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Известные адреса контрагентов — что система уже знает о том, кто ей пишет."""
    cid = await _mail_scope(company_id, current_user, db)
    rows = (await db.execute(select(CounterpartyEmail, Counterparty.name)
        .join(Counterparty, Counterparty.id == CounterpartyEmail.counterparty_id)
        .where(CounterpartyEmail.company_id == cid)
        .order_by(CounterpartyEmail.address))).all()
    return {"rows": [{
        "id": str(e.id), "address": e.address, "source": e.source,
        "counterpartyId": str(e.counterparty_id), "counterpartyName": name,
    } for e, name in rows]}


# ── Волна 3: вложения письма в приёмку первички ──────────────────────────────

@router.post("/to-intake")
async def to_intake(
    company_id: str,
    message_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Разобрать вложения письма как документы. Приём в учёт — отдельным шагом."""
    cid = await _mail_scope(company_id, current_user, db)
    msg = (await db.execute(select(MailMessage).where(
        MailMessage.company_id == cid, MailMessage.id == message_id))).scalar_one_or_none()
    if msg is None:
        return {"error": "not_found"}
    atts = (await db.execute(select(MailAttachment).where(
        MailAttachment.company_id == cid,
        MailAttachment.message_id == msg.id))).scalars().all()
    res = await mail_intake.attachments_to_intake(db, cid, msg, atts)
    await db.commit()
    return res


# ── Волна 4: ответы из пространства и история общения ────────────────────────

class SendIn(BaseModel):
    account_id: str
    to: list[str]
    subject: str
    body: str
    thread_id: str | None = None
    reply_to_message_id: str | None = None
    # Идентификаторы файлов пространства (`source_files`): контрагенту уходит тот
    # же файл, что лежит у документа, а не его копия, сделанная ради отправки.
    attachments: list[str] = []


@router.post("/send")
async def send(
    company_id: str,
    body: SendIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Написать или ответить — с того же ящика, в ту же нить."""
    cid = await _mail_scope(company_id, current_user, db)
    return await mail_send.send_message(
        db, cid, account_id=body.account_id, to=body.to, subject=body.subject,
        body=body.body, thread_id=body.thread_id,
        reply_to_message_id=body.reply_to_message_id, author=current_user.email,
        attachments=body.attachments)


@router.get("/by-counterparty")
async def by_counterparty(
    company_id: str,
    counterparty_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Переписка с контрагентом — для его карточки.

    История общения должна лежать там же, где документы и долг: вопрос «о чём мы
    с ним говорили» задают ровно в тот момент, когда смотрят на его карточку.
    """
    cid = await _mail_scope(company_id, current_user, db)
    rows = (await db.execute(select(MailThread).where(
        MailThread.company_id == cid,
        MailThread.counterparty_id == counterparty_id)
        .order_by(MailThread.last_message_at.desc()).limit(limit))).scalars().all()
    return {"rows": [{
        "id": str(t.id), "subject": t.subject, "messages": t.messages_count,
        "lastAt": t.last_message_at.isoformat() if t.last_message_at else None,
    } for t in rows]}


# ── Волна 5: карантин и гигиена ──────────────────────────────────────────────

@router.get("/quarantine")
async def quarantine(
    company_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Письма, отложенные до решения человека: неизвестный отправитель, отказ
    проверки подлинности, правило «в карантин».

    Карантин без разбора — та же корзина, поэтому здесь не список «мусора», а
    очередь решений: принять, отклонить или запомнить адрес.
    """
    cid = await _mail_scope(company_id, current_user, db)
    rows = (await db.execute(select(MailMessage).where(
        MailMessage.company_id == cid,
        MailMessage.status.in_(["quarantine", "rejected"]))
        .order_by(MailMessage.sent_at.desc()).limit(limit))).scalars().all()
    return {"rows": [{
        "id": str(m.id), "status": m.status, "subject": m.subject,
        "fromEmail": m.from_email, "fromName": m.from_name,
        "sentAt": m.sent_at.isoformat() if m.sent_at else None,
        "threadId": str(m.thread_id) if m.thread_id else None,
        "hasAttachments": m.has_attachments,
        # Почему отложено: вердикт сервера о подлинности, если он был.
        "authVerdict": (m.headers or {}).get("_auth_verdict"),
    } for m in rows]}


class DecisionIn(BaseModel):
    message_ids: list[str]
    decision: str   # accept | reject


@router.post("/quarantine/decide")
async def decide(
    company_id: str,
    body: DecisionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Решение по карантину: принять письма в работу или отклонить."""
    cid = await _mail_scope(company_id, current_user, db)
    rows = (await db.execute(select(MailMessage).where(
        MailMessage.company_id == cid,
        MailMessage.id.in_(body.message_ids)))).scalars().all()
    if body.decision == "accept" and any(
            message.routed_to == "duplicate" for message in rows):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Системный дубль письма нельзя принять повторно")
    status = "accepted" if body.decision == "accept" else "rejected"
    for m in rows:
        m.status = status
    await db.commit()
    return {"updated": len(rows), "status": status}


@router.post("/accounts/{account_id}/test")
async def test_account(
    account_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Проверить настройки ящика: приём и отправка отдельно.

    Сотрудник должен увидеть результат сразу — «сервер не принял пароль» здесь и
    сейчас, а не пустая лента через час и догадки, что пошло не так.
    """
    cid = await require_company_admin(company_id, current_user, db)
    a = (await db.execute(select(MailAccount).where(
        MailAccount.company_id == cid, MailAccount.id == account_id))).scalar_one_or_none()
    if a is None:
        return {"error": "not_found"}
    return await mail_intake.test_account(db, a)
