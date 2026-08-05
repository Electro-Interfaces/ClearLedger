"""Почтовые участники чатов: разговор с теми, кто в пространство не заходит.

Подрядчик, поставщик, инженер заказчика работают в своей почте, и заводить их в
наш интерфейс никто не будет. Поэтому участник комнаты может быть «почтовым»
(`users.mail_only`): каждое сообщение комнаты уходит ему письмом, а его ответ
возвращается в ту же ленту обычным сообщением. В чате он выглядит участником —
с пометкой, что доставка идёт письмом, чтобы автор понимал, куда уходит текст.

Адресация ответа — плюс-адресацией ящика приёма: `ящик+r<комната>@домен`
(`Reply-To`). Тема письма при этом роли не играет: человек отвечает как обычно,
может её переписать или переслать письмо — комната всё равно определится. Тегов
в теме, как в почтовом мосте заявок, здесь нет намеренно.

Забирает письма из ящика поллер Поддержки (общий на пространство), он же зовёт
`POST /api/chat/rooms/{id}/inbound-email` с входящим ключом пространства.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from html import escape as html_escape
from email.utils import parseaddr

from sqlalchemy import select

from app.config import settings
from app.models import ChatParticipant, User
from app.services.email_service import send_notice

logger = logging.getLogger(__name__)

# Живые фоновые задачи: см. комментарий у create_task ниже.
_tasks: set = set()


def reply_address(room_id: uuid.UUID | str) -> str | None:
    """Адрес, с которого ответ вернётся именно в эту комнату. None — ящик не задан."""
    inbox = parseaddr(settings.chat_mail_inbox)[1]
    if not inbox or "@" not in inbox:
        return None
    local, domain = inbox.rsplit("@", 1)
    return f"{local}+r{room_id}@{domain}"


def room_from_address(address: str) -> uuid.UUID | None:
    """Обратный разбор: `ящик+r<комната>@домен` → комната. None — адрес не наш."""
    addr = parseaddr(address or "")[1].lower()
    if "+r" not in addr or "@" not in addr:
        return None
    tag = addr.rsplit("@", 1)[0].split("+r", 1)[1]
    try:
        return uuid.UUID(tag)
    except (ValueError, TypeError):
        return None


def _body(room_name: str | None, author: str, text: str, reply_to: str | None) -> tuple[str, str]:
    """Текст и HTML письма. Подпись объясняет, как ответить — иначе не ответят.

    Всё, что пришло от людей — текст, имя автора, имя комнаты — экранируем: письмо
    уходит наружу от почты компании, и незакрытый тег в сообщении превращает
    служебное уведомление в готовую фишинговую страницу у получателя.
    """
    head = f"{author} · {room_name or 'Чат'}"
    room_h, author_h, text_h = (html_escape(room_name or "Чат"),
                                html_escape(author), html_escape(text))
    hint = ("Ответьте на это письмо — ваш ответ увидят участники обсуждения."
            if reply_to else "Это уведомление об обсуждении.")
    plain = f"{head}\n\n{text}\n\n— — —\n{hint}"
    html = (
        '<!doctype html><html><body style="margin:0;background:#f1f5f9;'
        'font-family:Arial,Helvetica,sans-serif">'
        '<div style="max-width:640px;margin:24px auto;background:#fff;border:1px solid #e2e8f0;'
        'border-radius:12px;overflow:hidden">'
        f'<div style="background:#0f172a;color:#fff;padding:12px 20px;font-size:14px">'
        f'{room_h}</div>'
        '<div style="padding:20px;color:#0f172a;font-size:14px;line-height:1.6">'
        f'<div style="color:#64748b;margin-bottom:8px">{author_h}</div>'
        f'<div style="white-space:pre-wrap">{text_h}</div></div>'
        '<div style="padding:10px 20px;background:#f8fafc;color:#64748b;font-size:12px;'
        f'border-top:1px solid #e2e8f0">{html_escape(hint)}</div></div></body></html>'
    )
    return plain, html


def push_room_mail_async(
    room_id: uuid.UUID, room_name: str | None, author_name: str,
    text: str, exclude_user_id: uuid.UUID,
) -> None:
    """Разослать сообщение комнаты её почтовым участникам. Fire-and-forget.

    Своя сессия и свои ошибки: отправка письма не должна ни держать транзакцию
    отправителя, ни ронять сообщение в чате, если почтовик недоступен.
    """
    if not settings.chat_mail_inbox or not settings.smtp_host:
        return

    async def _run() -> None:
        from app.database import async_session_factory
        try:
            async with async_session_factory() as db:
                rows = (await db.execute(
                    select(User.email, User.name)
                    .join(ChatParticipant, ChatParticipant.user_id == User.id)
                    .where(ChatParticipant.room_id == room_id,
                           ChatParticipant.user_id != exclude_user_id,
                           User.mail_only.is_(True))
                )).all()
                emails = [e for e, _ in rows if e]
                if not emails:
                    return
                reply = reply_address(room_id)
                plain, html = _body(room_name, author_name, text, reply)
                subject = f"{room_name or 'Обсуждение'}: сообщение от {author_name}"
                # Каждому — своё письмо. Общий To светил бы адреса подрядчиков друг
                # другу: в одной комнате сидят люди разных внешних организаций.
                for addr in emails:
                    await send_notice([addr], subject, plain, html, reply_to=reply)
        except Exception as exc:  # noqa: BLE001 — почта не должна ронять чат
            logger.warning("[chat-mail] рассылка по комнате %s: %s", room_id, exc)

    try:
        # Ссылку держим в модуле: голый create_task() сборщик мусора вправе убрать
        # до того, как задача доработает — тихая потеря письма и уведомления.
        task = asyncio.get_running_loop().create_task(_run())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except RuntimeError:
        pass  # вне цикла событий (тесты, скрипты) — рассылать некому
