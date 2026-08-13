"""Куда письмо едет дальше: комната, задача, заявка (docs/MAIL.md).

Приём письма и его дальнейшая судьба — разные вещи. Приём разбирает и сохраняет,
здесь письмо доезжает до места, где с ним работают: в комнату чата, в задачу, в
заявку Поддержки. Так задумано с самого начала: вход один, потребителей много.

Два пути попадания:

  1. **Плюс-адрес** — ответ почтового участника: `ящик+r<комната>@домен` и
     `ящик+t<номер задачи>@домен`. Механику построили раньше (`chat_mail.py`,
     `task_mail.py`), и она уже живёт в переписке с подрядчиками — здесь мы её
     не переписываем, а подхватываем на общем входе.
  2. **Правило** — «письма с домена подрядчика клади в комнату проекта» или
     «в заявку по такому-то объекту».

Ошибка маршрута не рвёт приём: письмо уже сохранено, и потерять его из-за того,
что комната удалена, было бы хуже, чем не доставить.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, ChatParticipant, ChatRoom, MailMessage, Task, User

logger = logging.getLogger("clearledger.mail")

# `ящик+r<uuid комнаты>@домен` и `ящик+t<номер задачи>@домен` — те же теги, что
# ставят исходящие письма чатов и задач. Тема письма роли не играет: человек её
# правит и пересылает, а плюс-адрес остаётся в `To`.
_PLUS_ROOM = re.compile(r"\+r([0-9a-f-]{36})@", re.I)
_PLUS_TASK = re.compile(r"\+t(\d+)@", re.I)


def plus_target(row: MailMessage, headers: dict[str, Any] | None) -> tuple[str, str] | None:
    """Найти адрес вида `+r…`/`+t…` среди получателей. Возвращает («room»|«task», id)."""
    candidates = list(row.to_emails or [])
    for key in ("Delivered-To", "X-Original-To", "Envelope-To", "To", "Cc"):
        value = (headers or {}).get(key)
        if value:
            candidates.append(str(value))
    for raw in candidates:
        m = _PLUS_ROOM.search(raw)
        if m:
            return "room", m.group(1)
        m = _PLUS_TASK.search(raw)
        if m:
            return "task", m.group(1)
    return None


async def to_chat_room(db: AsyncSession, cid, row: MailMessage, room_id) -> bool:
    """Положить письмо сообщением в комнату.

    Автором встаёт участник с тем же адресом — так письмо выглядит его репликой, а
    не сообщением от системы. Если отправителя в комнате нет (правило кладёт письма
    постороннего), сообщение всё равно появляется, но подписано адресом: терять
    письмо из-за формальности участия хуже, чем показать его с пометкой.
    """
    try:
        rid = uuid.UUID(str(room_id))
    except (ValueError, TypeError):
        return False
    room = (await db.execute(select(ChatRoom).where(
        ChatRoom.id == rid, ChatRoom.company_id == cid))).scalar_one_or_none()
    if room is None:
        logger.warning("письмо %s: комната %s не найдена", row.id, room_id)
        return False

    email = (row.from_email or "").strip().lower()
    author = (await db.execute(
        select(User).join(ChatParticipant, ChatParticipant.user_id == User.id)
        .where(ChatParticipant.room_id == rid, func.lower(User.email) == email)
    )).scalar_one_or_none()

    # Повтор ловим по Message-ID письма: поллер может перечитать ящик после смены
    # UIDVALIDITY, и комната не должна получить второй экземпляр.
    if row.message_id:
        dup = (await db.execute(select(ChatMessage.id).where(
            ChatMessage.room_id == rid,
            ChatMessage.external_id == row.message_id))).scalar_one_or_none()
        if dup is not None:
            return True

    text = (row.body_text or "").strip() or "(письмо без текста)"
    if author is None:
        text = f"Письмо от {row.from_email or 'неизвестного отправителя'}:\n\n{text}"

    db.add(ChatMessage(
        room_id=rid,
        user_id=author.id if author is not None else None,
        user_name=author.name if author is not None else (row.from_name or row.from_email),
        type="text", content=text,
        external_id=row.message_id, external_source="email",
        external_ref=row.subject,
    ))
    await db.flush()
    return True


async def to_task(db: AsyncSession, cid, row: MailMessage, number: int) -> bool:
    """Дописать письмо в задачу как её событие (ответ почтового исполнителя)."""
    task = (await db.execute(select(Task).where(
        Task.company_id == cid, Task.number == number))).scalar_one_or_none()
    if task is None:
        logger.warning("письмо %s: задача №%s не найдена", row.id, number)
        return False
    text = (row.body_text or "").strip() or "(письмо без текста)"
    task.description = ((task.description or "")
                        + f"\n\n--- письмо от {row.from_email or '—'} ---\n{text[:4000]}")
    await db.flush()
    return True


async def to_ticket(db: AsyncSession, cid, row: MailMessage, object_id: str) -> bool:
    """Завести заявку в Поддержке по письму.

    Заявка всегда про ОБЪЕКТ — поэтому правило обязано его указать. Без объекта
    заявку заводить некуда, и это не ограничение реализации, а устройство разреза
    поддержки: там работают с тем, что стоит на площадке.
    """
    from app.services import space_projection
    text = (row.body_text or "").strip() or "(письмо без текста)"
    try:
        await space_projection.create_object_ticket(
            db, cid, object_id,
            title=(row.subject or "Письмо")[:200],
            description=f"Письмо от {row.from_email or '—'}\n\n{text[:4000]}",
            author_email=row.from_email,
        )
        return True
    except Exception as e:  # noqa: BLE001 — недоступная Поддержка не рвёт приём почты
        logger.warning("письмо %s: заявка не заведена: %s", row.id, e)
        return False


async def route(db: AsyncSession, cid, row: MailMessage, rule) -> str | None:
    """Доставить письмо по плюс-адресу или по правилу. Возвращает, куда доехало."""
    # Плюс-адрес сильнее правила: это прямой ответ в конкретную комнату или задачу,
    # и гадать по домену отправителя, когда адрес назван явно, незачем.
    target = plus_target(row, row.headers)
    if target:
        kind, value = target
        if kind == "room" and await to_chat_room(db, cid, row, value):
            return "chat"
        if kind == "task" and value.isdigit() and await to_task(db, cid, row, int(value)):
            return "task"

    if rule is None:
        return None
    if rule.action == "chat" and rule.set_room_id:
        return "chat" if await to_chat_room(db, cid, row, rule.set_room_id) else None
    if rule.action == "ticket" and rule.set_object_id:
        return "ticket" if await to_ticket(db, cid, row, rule.set_object_id) else None
    return None
