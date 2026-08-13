"""Приём почты пространства: ящики компании, разбор писем, нити (docs/MAIL.md).

Один коннектор «Почта компании» — много ящиков. Механика одна: забрать по IMAP,
разобрать, понять от кого, сшить в нить, сохранить с вложениями. Различаются у
ящиков учётка, назначение и (следующей волной) правила.

Три вещи, которые здесь сделаны намеренно и без которых почта ломается:

  1. **UIDVALIDITY.** Сервер вправе перенумеровать ящик; сохранённый UID после
     этого указывает на чужое письмо. При смене значения приём начинается заново,
     а дубли отсекаются по `Message-ID`.
  2. **Нить по `References`, а не по теме.** Тему правят, переводят и дописывают
     «Re:» — по ней одна переписка разваливается на несколько.
  3. **Оригинал письма.** Тело и заголовки сохраняются как пришли: спор «что было
     в письме» решается оригиналом, а не нашей интерпретацией.

IMAP-клиент синхронный (`imaplib` из стандартной библиотеки), поэтому опрос
уходит в поток: тянуть асинхронную библиотеку ради одного поллера незачем.
"""
from __future__ import annotations

import asyncio
import email
import hashlib
import imaplib
import logging
import os
import re
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime, parseaddr, getaddresses
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Counterparty, CounterpartyEmail, MailAccount, MailAttachment, MailMessage,
    MailRule, MailThread,
)

logger = logging.getLogger("clearledger.mail")

# Вложения, которые не принимаем никогда: исполняемое из письма — это не документ.
_DENY_EXT = {".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".js", ".vbs", ".msi",
             ".jar", ".ps1", ".lnk"}
# Потолок на письмо и на вложение: чужой ящик присылает что угодно.
MAX_MESSAGE_BYTES = 25 * 1024 * 1024
MAX_ATTACH_BYTES = 15 * 1024 * 1024
# Сколько писем берём за один заход: первый опрос большого ящика иначе висит минуты.
BATCH = 50


def _decode(value: str | None) -> str:
    """Заголовок в читаемый вид: `=?utf-8?B?...?=` приезжает почти в каждом письме."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 — кривой заголовок не повод терять письмо
        return value


def _body(msg: Message) -> tuple[str, str]:
    """Текст и html письма. Части перебираем сами: `get_body` не видит вложенные
    multipart от некоторых отправителей."""
    text_parts, html_parts = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename():
            continue
        ctype = part.get_content_type()
        try:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if ctype == "text/plain":
            text_parts.append(body)
        elif ctype == "text/html":
            html_parts.append(body)
    return "\n".join(text_parts).strip(), "\n".join(html_parts).strip()


def _attachments(msg: Message) -> list[dict[str, Any]]:
    out = []
    for part in msg.walk():
        name = part.get_filename()
        if not name:
            continue
        name = _decode(name)
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        payload = part.get_payload(decode=True) or b""
        if ext in _DENY_EXT:
            logger.warning("вложение %s отклонено по расширению", name)
            continue
        if len(payload) > MAX_ATTACH_BYTES:
            logger.warning("вложение %s отклонено по размеру (%s)", name, len(payload))
            continue
        out.append({
            "name": name,
            "content_type": part.get_content_type(),
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "content": payload,
        })
    return out


def _refs(msg: Message) -> list[str]:
    """Цепочка предков письма: `References` + `In-Reply-To`."""
    raw = " ".join(filter(None, [msg.get("References", ""), msg.get("In-Reply-To", "")]))
    return re.findall(r"<[^>]+>", raw)


def _fetch_sync(account: dict[str, Any]) -> tuple[list[tuple[int, bytes]], int | None, str | None]:
    """Синхронный заход в ящик: вернуть новые письма, UIDVALIDITY и ошибку."""
    password = os.environ.get(account["secret_env"] or "", "")
    if not (account["imap_host"] and account["login"] and password):
        return [], None, "не заданы адрес IMAP, логин или переменная с паролем"
    try:
        conn = imaplib.IMAP4_SSL(account["imap_host"], account["imap_port"])
        conn.login(account["login"], password)
        conn.select(account["imap_folder"], readonly=True)

        validity = None
        typ, data = conn.status(account["imap_folder"], "(UIDVALIDITY)")
        if typ == "OK" and data:
            m = re.search(rb"UIDVALIDITY (\d+)", data[0] or b"")
            if m:
                validity = int(m.group(1))

        # Смена UIDVALIDITY означает перенумерацию: начинаем с начала, дубли
        # отсечёт Message-ID.
        last_uid = account["last_uid"] or 0
        if validity and account["uid_validity"] and validity != account["uid_validity"]:
            last_uid = 0

        typ, data = conn.uid("search", None, f"UID {last_uid + 1}:*")
        uids = [int(u) for u in (data[0] or b"").split() if int(u) > last_uid]
        out: list[tuple[int, bytes]] = []
        for uid in uids[:BATCH]:
            typ, msg_data = conn.uid("fetch", str(uid), "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if raw and len(raw) <= MAX_MESSAGE_BYTES:
                out.append((uid, raw))
        conn.logout()
        return out, validity, None
    except Exception as e:  # noqa: BLE001 — ошибку показываем в карточке ящика
        return [], None, str(e)[:400]


async def poll_account(db: AsyncSession, account: MailAccount) -> dict[str, Any]:
    """Забрать новые письма ящика, разобрать и сохранить."""
    if account.mode == "out" or not account.is_active:
        return {"fetched": 0, "saved": 0, "skipped": "ящик не принимает почту"}

    snapshot = {
        "imap_host": account.imap_host, "imap_port": account.imap_port,
        "imap_folder": account.imap_folder, "login": account.login,
        "secret_env": account.secret_env, "last_uid": account.last_uid,
        "uid_validity": account.uid_validity,
    }
    letters, validity, error = await asyncio.to_thread(_fetch_sync, snapshot)

    account.last_sync_at = datetime.now(timezone.utc)
    account.last_error = error
    if validity:
        account.uid_validity = validity
    if error:
        await db.commit()
        return {"fetched": 0, "saved": 0, "error": error}

    saved = 0
    for uid, raw in letters:
        try:
            if await _save_message(db, account, uid, raw):
                saved += 1
        except Exception as e:  # noqa: BLE001 — одно кривое письмо не рвёт приём
            logger.exception("письмо uid=%s не сохранено: %s", uid, e)
        account.last_uid = max(account.last_uid or 0, uid)
    await db.commit()
    return {"fetched": len(letters), "saved": saved}


async def _save_message(db: AsyncSession, account: MailAccount, uid: int,
                        raw: bytes) -> bool:
    msg = email.message_from_bytes(raw)
    message_id = (msg.get("Message-ID") or "").strip() or None

    # Повтор ловим по Message-ID: после смены UIDVALIDITY ящик перечитывается
    # целиком, и без этой проверки лента задвоится.
    if message_id:
        exists = (await db.execute(select(MailMessage.id).where(
            MailMessage.company_id == account.company_id,
            MailMessage.message_id == message_id))).scalars().first()
        if exists:
            return False

    from_name, from_email = parseaddr(_decode(msg.get("From")))
    to_all = [addr for _, addr in getaddresses([_decode(msg.get("To") or ""),
                                                _decode(msg.get("Cc") or "")]) if addr]
    subject = _decode(msg.get("Subject"))[:500]
    try:
        sent_at = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    except Exception:  # noqa: BLE001
        sent_at = None

    text_body, html_body = _body(msg)
    atts = _attachments(msg)

    # Кто написал: адрес → карточка контрагента. Неизвестный адрес не ошибка —
    # это работа для человека (следующая волна: обучение адресов).
    cp_id = await _guess_counterparty(db, account.company_id, from_email)

    thread = await _thread_for(db, account, msg, subject, message_id, from_email, cp_id)

    row = MailMessage(
        company_id=account.company_id, account_id=account.id, thread_id=thread.id,
        direction="in", uid=uid, message_id=message_id,
        in_reply_to=(msg.get("In-Reply-To") or "").strip() or None,
        subject=subject, from_name=from_name[:300] or None, from_email=from_email or None,
        to_emails=to_all, sent_at=sent_at,
        body_text=text_body[:200000] or None, body_html=html_body[:400000] or None,
        counterparty_id=cp_id,
        # Заголовки целиком: по ним разбираются спорные случаи и проверки SPF/DKIM.
        headers={k: _decode(v)[:1000] for k, v in msg.items()},
        has_attachments=bool(atts),
        status="new",
    )

    # Правила: первое сработавшее решает судьбу письма и может сразу проставить
    # контрагента и договор — это и есть ответ «что, кому и куда отнести».
    rule = await apply_rules(db, account, row, bool(atts))
    if rule is not None:
        row.status = {"reject": "rejected", "quarantine": "quarantine"}.get(
            rule.action, "accepted")
        if rule.set_counterparty_id and not row.counterparty_id:
            row.counterparty_id = rule.set_counterparty_id
            cp_id = rule.set_counterparty_id
        rule.hits = (rule.hits or 0) + 1

    db.add(row)
    await db.flush()

    for a in atts:
        db.add(MailAttachment(
            company_id=account.company_id, message_id=row.id,
            file_name=a["name"][:500], content_type=a["content_type"],
            size=a["size"], sha256=a["sha256"], content=a["content"],
        ))

    thread.messages_count = (thread.messages_count or 0) + 1
    thread.last_message_at = sent_at or datetime.now(timezone.utc)
    if cp_id and not thread.counterparty_id:
        thread.counterparty_id = cp_id
    return True


async def _thread_for(db: AsyncSession, account: MailAccount, msg: Message,
                      subject: str, message_id: str | None,
                      from_email: str | None, cp_id) -> MailThread:
    """Найти нить по предкам письма или завести новую."""
    refs = _refs(msg)
    if refs:
        found = (await db.execute(select(MailThread).where(
            MailThread.company_id == account.company_id,
            MailThread.root_message_id.in_(refs)))).scalars().first()
        if found:
            return found
        # Ответ пришёл раньше, чем мы увидели исходное письмо: нить заводится по
        # самому старому предку, к ней же приклеится оригинал, когда дойдёт.
        thread = MailThread(
            company_id=account.company_id, account_id=account.id,
            subject=re.sub(r"^(re|fwd?|ответ|пересылка)[:\s]+", "", subject, flags=re.I)[:500],
            root_message_id=refs[0], counterparty_id=cp_id,
            participants=[from_email] if from_email else [],
        )
        db.add(thread)
        await db.flush()
        return thread

    thread = MailThread(
        company_id=account.company_id, account_id=account.id,
        subject=subject or "(без темы)", root_message_id=message_id,
        counterparty_id=cp_id, participants=[from_email] if from_email else [],
    )
    db.add(thread)
    await db.flush()
    return thread


async def _guess_counterparty(db: AsyncSession, cid, from_email: str | None):
    """Опознать отправителя: выученный адрес → адрес карточки → домен.

    Выученное человеком стоит первым и намеренно: он знает, что «бухгалтер Ирина
    с личной почты» — это ТСМ, а справочник об этом не догадается никогда.
    """
    if not from_email or "@" not in from_email:
        return None
    addr = from_email.lower().strip()
    domain = addr.split("@")[-1]

    learned = (await db.execute(select(CounterpartyEmail.counterparty_id).where(
        CounterpartyEmail.company_id == cid,
        func.lower(CounterpartyEmail.address) == addr))).scalars().first()
    if learned:
        return learned

    exact = (await db.execute(select(Counterparty.id).where(
        Counterparty.company_id == cid,
        func.lower(Counterparty.email) == addr))).scalars().first()
    if exact:
        return exact

    # Домен — слабее адреса, поэтому берём его, только если он ведёт к ОДНОЙ
    # карточке: на mail.ru и yandex.ru сидит половина контрагентов сразу.
    same = (await db.execute(select(Counterparty.id).where(
        Counterparty.company_id == cid,
        func.lower(Counterparty.email).like(f"%@{domain}")))).scalars().all()
    return same[0] if len(same) == 1 else None


async def apply_rules(db: AsyncSession, account: MailAccount, row: MailMessage,
                      has_attachments: bool) -> MailRule | None:
    """Найти первое подходящее правило. Пустое условие условием не считается."""
    rules = (await db.execute(select(MailRule).where(
        MailRule.company_id == account.company_id,
        MailRule.is_active.is_(True)).order_by(MailRule.sort))).scalars().all()

    sender = (row.from_email or "").lower()
    domain = sender.split("@")[-1] if "@" in sender else ""
    subject = (row.subject or "").lower()

    for r in rules:
        if r.account_id and r.account_id != account.id:
            continue
        if r.from_email and r.from_email.lower() != sender:
            continue
        if r.from_domain and r.from_domain.lower().lstrip("@") != domain:
            continue
        if r.subject_like and r.subject_like.lower() not in subject:
            continue
        if r.has_attachment is not None and r.has_attachment != has_attachments:
            continue
        if r.unknown_sender is not None and r.unknown_sender != (row.counterparty_id is None):
            continue
        return r
    return None


async def learn_address(db: AsyncSession, cid, address: str, counterparty_id,
                        user: str | None = None) -> dict[str, Any]:
    """Запомнить, чей это адрес, и применить знание к УЖЕ полученным письмам.

    Обучение без обратной силы бесполезно: человек размечает адрес именно тогда,
    когда смотрит на непонятое письмо, и ждёт, что вся переписка встанет на место.
    """
    addr = address.lower().strip()
    exists = (await db.execute(select(CounterpartyEmail).where(
        CounterpartyEmail.company_id == cid,
        func.lower(CounterpartyEmail.address) == addr))).scalars().first()
    if exists:
        exists.counterparty_id = counterparty_id
    else:
        db.add(CounterpartyEmail(company_id=cid, counterparty_id=counterparty_id,
                                 address=addr, source="learned", created_by=user))

    msgs = (await db.execute(select(MailMessage).where(
        MailMessage.company_id == cid,
        func.lower(MailMessage.from_email) == addr))).scalars().all()
    threads = set()
    for m in msgs:
        m.counterparty_id = counterparty_id
        if m.thread_id:
            threads.add(m.thread_id)
    for t in (await db.execute(select(MailThread).where(
        MailThread.company_id == cid, MailThread.id.in_(threads)))).scalars().all() if threads else []:
        t.counterparty_id = counterparty_id
    await db.commit()
    return {"address": addr, "messages": len(msgs), "threads": len(threads)}


async def poll_all(db: AsyncSession, company_id) -> dict[str, Any]:
    """Опросить все активные ящики компании."""
    accounts = (await db.execute(select(MailAccount).where(
        MailAccount.company_id == company_id,
        MailAccount.is_active.is_(True)))).scalars().all()
    out = {}
    for a in accounts:
        out[a.address] = await poll_account(db, a)
    return {"accounts": len(accounts), "result": out}
