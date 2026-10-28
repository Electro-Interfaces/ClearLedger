"""Ответы на приглашения из почтовых программ (iMIP `METHOD:REPLY`, RFC 6047).

Приглашение уходит с организатором — ящиком ответов пространства
(`CALENDAR_REPLY_MAILBOX`, см. ics.event_ics). Человек нажимает «Принять» в VK,
Outlook или Яндексе, программа шлёт на этот адрес письмо с календарным файлом,
а мы раз в минуту забираем его и ставим ответ участнику или гостю — тот же,
что он поставил бы кнопкой в пространстве.

Чьё слово — решает адрес. Ответ принимается, только если адрес участника в
файле совпадает с отправителем письма и этот адрес действительно позван на
встречу: иначе любой мог бы ответить за другого. Письмо, не прошедшее проверку
подлинности почтовым сервером, не принимается вовсе.

Отдельный ящик, а не ящик приёма пространства: тот читает «Поддержка» для
заявок, и ответы «Принято» засоряли бы ленту писем компании.
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import re
import uuid
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import CalendarAttendee, CalendarEvent, CalendarGuest, User
from app.services.mail_intake import IMAP_TIMEOUT, auth_verdict, sender_of

logger = logging.getLogger("clearledger.calendar")

# Ответ в файле → ответ в пространстве. DELEGATED и прочее не трогаем: такого
# ответа у нас нет, а угадывать за человека хуже, чем оставить «без ответа».
_PARTSTAT = {"ACCEPTED": "accepted", "DECLINED": "declined", "TENTATIVE": "tentative"}
# Сколько писем за заход: ответов не бывает много, а первый заход в ящик с
# накопившейся почтой не должен держать цикл минутами.
BATCH = 50


def _calendar_texts(msg: Message) -> list[str]:
    """Календарные части письма. Outlook кладёт файл частью `text/calendar`,
    другие — вложением `.ics`; берём и то и другое."""
    out = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        name = (part.get_filename() or "").lower()
        if part.get_content_type() in ("text/calendar", "application/ics") or name.endswith(".ics"):
            payload = part.get_payload(decode=True) or b""
            out.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    return out


def parse_reply(text: str) -> list[dict]:
    """Ответы из календарного файла: [{uid, email, response, comment, stamp}].

    Только `METHOD:REPLY`: приглашение или отмена, пересланные в ящик, ответом
    не являются. Строки по стандарту сложены продолжением — сначала разворачиваем.
    """
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    if not any(line.strip().upper() == "METHOD:REPLY" for line in lines):
        return []
    out, cur = [], None
    for line in lines:
        name, _, value = line.partition(":")
        key = name.split(";", 1)[0].strip().upper()
        if key == "BEGIN" and value.strip().upper() == "VEVENT":
            cur = {"uid": None, "attendees": [], "comment": None, "stamp": None}
        elif key == "END" and value.strip().upper() == "VEVENT" and cur is not None:
            for addr, partstat in cur["attendees"]:
                if cur["uid"] and partstat in _PARTSTAT:
                    out.append({"uid": cur["uid"], "email": addr, "response": _PARTSTAT[partstat],
                                "comment": cur["comment"], "stamp": cur["stamp"]})
            cur = None
        elif cur is None:
            continue
        elif key == "UID":
            cur["uid"] = value.strip()
        elif key == "ATTENDEE":
            params = {k.strip().upper(): v for k, v in
                      (p.split("=", 1) for p in name.split(";")[1:] if "=" in p)}
            partstat = params.get("PARTSTAT", "").strip('"').upper()
            addr = re.sub(r"^mailto:", "", value.strip(), flags=re.IGNORECASE).lower()
            cur["attendees"].append((addr, partstat))
        elif key == "COMMENT":
            cur["comment"] = value.replace("\\n", "\n").replace("\\,", ",") \
                .replace("\\;", ";").replace("\\\\", "\\").strip()[:300] or None
        elif key == "DTSTAMP":
            try:
                cur["stamp"] = datetime.strptime(value.strip(), "%Y%m%dT%H%M%SZ") \
                    .replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return out


def _event_id(uid: str) -> uuid.UUID | None:
    """UID приглашения — `<id встречи>@trek` или `@conf.elsyplus`."""
    try:
        return uuid.UUID(uid.split("@", 1)[0])
    except (ValueError, AttributeError):
        return None


async def apply_message(db: AsyncSession, raw: bytes) -> list[str]:
    """Разобрать одно письмо и поставить ответы. Возвращает исходы для журнала."""
    msg = email.message_from_bytes(raw)
    verdict, _ = auth_verdict(msg)
    if verdict == "fail":
        return ["отклонено: письмо не прошло проверку подлинности"]
    sender = sender_of(msg)[1].lower()
    try:
        sent = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
    except (TypeError, ValueError):
        sent = None
    if sent is not None and sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    исходы = []
    for text in _calendar_texts(msg):
        for r in parse_reply(text):
            if r["email"] != sender:
                исходы.append(f"пропущено: {r['email']} отвечает письмом от {sender}")
                continue
            ev_id = _event_id(r["uid"])
            ev = await db.get(CalendarEvent, ev_id) if ev_id else None
            if ev is None:
                исходы.append(f"пропущено: встречи {r['uid']} нет")
                continue
            if ev.status == "cancelled":
                исходы.append(f"пропущено: встреча {ev.id} отменена")
                continue
            кто = (await db.execute(select(CalendarAttendee).join(
                User, User.id == CalendarAttendee.user_id).where(
                CalendarAttendee.event_id == ev.id,
                func.lower(User.email) == r["email"]))).scalars().first()
            if кто is None:
                кто = (await db.execute(select(CalendarGuest).where(
                    CalendarGuest.event_id == ev.id, CalendarGuest.revoked_at.is_(None),
                    func.lower(CalendarGuest.email) == r["email"]))).scalars().first()
            if кто is None:
                исходы.append(f"пропущено: {r['email']} не позван на {ev.id}")
                continue
            когда = r["stamp"] or sent or datetime.now(timezone.utc)
            # Письмо шло дольше, чем человек думал: если после него он уже ответил
            # в пространстве, старое «Принять» не должно перебить новое «Не смогу».
            if кто.responded_at and кто.responded_at > когда:
                исходы.append(f"пропущено: {r['email']} ответил позже в пространстве")
                continue
            кто.response = r["response"]
            кто.responded_at = когда
            кто.comment = r["comment"]
            кто.proposed_starts_at = None
            кто.proposed_ends_at = None
            исходы.append(f"{r['email']} → {r['response']} на {ev.id}")
    return исходы or ["пропущено: в письме нет ответа на приглашение"]


def _fetch_sync() -> list[tuple[bytes, bytes]]:
    """Непрочитанные письма ящика: [(uid, исходник)]. Читаем без отметки, отметку
    ставит `_mark_sync` после записи в базу — иначе сбой базы терял бы ответ."""
    conn = imaplib.IMAP4_SSL(settings.calendar_reply_imap_host,
                             settings.calendar_reply_imap_port, timeout=IMAP_TIMEOUT)
    try:
        conn.login(settings.calendar_reply_mailbox, settings.calendar_reply_password)
        conn.select("INBOX")
        _, data = conn.uid("search", None, "UNSEEN")
        out = []
        for uid in (data[0] or b"").split()[:BATCH]:
            typ, msg_data = conn.uid("fetch", uid, "(BODY.PEEK[])")
            if typ == "OK" and msg_data and isinstance(msg_data[0], tuple):
                out.append((uid, msg_data[0][1]))
        return out
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 — закрыть соединение не получилось, письма уже взяты
            pass


def _mark_sync(uids: list[bytes]) -> None:
    conn = imaplib.IMAP4_SSL(settings.calendar_reply_imap_host,
                             settings.calendar_reply_imap_port, timeout=IMAP_TIMEOUT)
    try:
        conn.login(settings.calendar_reply_mailbox, settings.calendar_reply_password)
        conn.select("INBOX")
        for uid in uids:
            conn.uid("store", uid, "+FLAGS", "(\\Seen)")
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


async def poll(db: AsyncSession) -> int:
    """Заход в ящик ответов. Ящик не задан — ничего не делаем. Письма остаются в
    ящике прочитанными: по ним разбирается спор «я же нажимал „Принять“»."""
    if not (settings.calendar_reply_mailbox and settings.calendar_reply_password):
        return 0
    письма = await asyncio.to_thread(_fetch_sync)
    if not письма:
        return 0
    for uid, raw in письма:
        for исход in await apply_message(db, raw):
            logger.info("ответ на приглашение: %s", исход)
    await db.commit()
    await asyncio.to_thread(_mark_sync, [uid for uid, _ in письма])
    return len(письма)
