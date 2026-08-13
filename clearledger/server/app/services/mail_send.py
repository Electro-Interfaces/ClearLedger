"""Отправка писем из пространства (docs/MAIL.md, волна 4).

Ответ уходит С ТОГО ЖЕ ящика, в нить которого отвечают: адрес отправителя для
контрагента не меняется, и переписка не разваливается на две. Копия сохраняется
в нити как исходящее письмо — история общения должна быть полной, иначе через
месяц никто не вспомнит, что и кому отвечали.

Заголовки `In-Reply-To` и `References` проставляются обязательно: без них почтовый
клиент контрагента откроет ответ отдельным письмом, и нить порвётся уже у него.
"""
from __future__ import annotations

import logging
import os
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MailAccount, MailAttachment, MailMessage, MailThread

logger = logging.getLogger("clearledger.mail")


async def send_message(db: AsyncSession, cid, *, account_id, to: list[str],
                       subject: str, body: str, thread_id=None,
                       reply_to_message_id=None, author: str | None = None,
                       ) -> dict[str, Any]:
    """Отправить письмо и сохранить его копию в нити."""
    account = (await db.execute(select(MailAccount).where(
        MailAccount.company_id == cid, MailAccount.id == account_id))).scalar_one_or_none()
    if account is None:
        return {"error": "ящик не найден"}
    if account.mode == "in":
        return {"error": "ящик настроен только на приём"}
    if not to:
        return {"error": "не указан получатель"}

    parent = None
    if reply_to_message_id:
        parent = (await db.execute(select(MailMessage).where(
            MailMessage.company_id == cid,
            MailMessage.id == reply_to_message_id))).scalar_one_or_none()

    msg = EmailMessage()
    # Отображаемое имя — настройка ЯЩИКА, а не автора: письма с `buh@` подписаны
    # бухгалтерией, кто бы из сотрудников их ни отправлял.
    msg["From"] = (f"{account.display_name} <{account.address}>"
                   if account.display_name else account.address)
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    own_id = make_msgid(domain=account.address.split("@")[-1])
    msg["Message-ID"] = own_id
    if parent is not None and parent.message_id:
        # Без этих двух заголовков клиент контрагента откроет ответ отдельным
        # письмом, и нить порвётся на его стороне, даже если у нас она цела.
        msg["In-Reply-To"] = parent.message_id
        msg["References"] = parent.message_id
    # Подпись ящика приклеивается к каждому письму: контрагент должен видеть, с кем
    # разговаривает, а сотрудник — не набирать её руками каждый раз.
    msg.set_content(body + (f"\n\n--\n{account.signature}" if account.signature else ""))

    host = account.smtp_host or os.environ.get("SMTP_HOST", "")
    port = account.smtp_port or int(os.environ.get("SMTP_PORT", "587"))
    if not host:
        return {"error": "не задан SMTP-сервер ящика"}

    try:
        import aiosmtplib
        from app.services.mail_secrets import password_of
        password = password_of(account)
        # Сертификат ВНУТРЕННЕГО релея самоподписанный и выписан не на имя
        # контейнера — его проверять бессмысленно, связь идёт внутри стека. А вот
        # ящик у провайдера (Яндекс, почта заказчика) — это интернет, и раньше
        # пароль от него уходил по каналу с непроверенным сертификатом: MITM на
        # любом промежуточном узле снимал его молча.
        internal = "." not in host
        kwargs: dict[str, Any] = {
            "hostname": host, "port": port, "timeout": 20,
            "tls_context": (ssl._create_unverified_context() if internal
                            else ssl.create_default_context()),
        }
        if account.smtp_security == "ssl":
            kwargs["use_tls"] = True
        elif account.smtp_security == "starttls":
            kwargs["start_tls"] = True
        # На релее без шифрования аутентификация не нужна и вредна: сервер её не
        # ждёт и отвечает отказом, который человек читает как «неверный пароль».
        if password and account.login and account.smtp_security != "none":
            kwargs.update({"username": account.login, "password": password})
        if account.smtp_security == "none":
            # Релей стека принимает почту без аутентификации; STARTTLS с ним не
            # поднимаем вовсе, иначе рукопожатие падает на его же сертификате.
            kwargs["start_tls"] = False
        await aiosmtplib.send(msg, **kwargs)
    except Exception as e:  # noqa: BLE001 — причину показываем человеку, а не в лог
        logger.exception("письмо не отправлено: %s", e)
        return {"error": f"SMTP: {str(e)[:200]}"}

    thread = None
    if thread_id:
        thread = (await db.execute(select(MailThread).where(
            MailThread.company_id == cid, MailThread.id == thread_id))).scalar_one_or_none()
    if thread is None:
        thread = MailThread(
            company_id=cid, account_id=account.id, subject=subject,
            root_message_id=own_id,
            counterparty_id=parent.counterparty_id if parent is not None else None,
            participants=to,
        )
        db.add(thread)
        await db.flush()

    row = MailMessage(
        company_id=cid, account_id=account.id, thread_id=thread.id, direction="out",
        message_id=own_id,
        in_reply_to=parent.message_id if parent is not None else None,
        subject=subject, from_name=author, from_email=account.address,
        to_emails=to, sent_at=datetime.now(timezone.utc), body_text=body,
        status="accepted",
        counterparty_id=thread.counterparty_id,
    )
    db.add(row)
    thread.messages_count = (thread.messages_count or 0) + 1
    thread.last_message_at = row.sent_at
    await db.commit()
    return {"sent": True, "messageId": str(row.id), "threadId": str(thread.id)}
