"""Почтовый канал «Задач»: поручение тому, кто в пространство не заходит.

Подрядчик работает там, где привык. Механика уже построена для чатов
(`chat_mail.py`) — здесь она повторена для задач, а не выдумана заново:
почтовый участник (`users.mail_only`), письмо с `Reply-To` на плюс-адрес,
ответ возвращается в ленту задачи обычной репликой с пометкой «письмом».

Отличие от чатов ровно одно — тег адреса: `ящик+t<номер>@домен` вместо `+r`.
Номер задачи, а не UUID: этот адрес человек видит в письме и иногда набирает
руками, а «t42» набирается, в отличие от тридцати шести знаков.

Письма из ящика забирает поллер Поддержки (общий на пространство), он же зовёт
`POST /api/tasks/{id}/inbound-email` входящим ключом пространства. Второго
поллера здесь нет и быть не должно.
"""
from __future__ import annotations

import asyncio
import logging
from email.utils import parseaddr
from html import escape as html_escape

from app.config import settings
from app.services.email_service import send_notice

logger = logging.getLogger(__name__)

# Живые фоновые задачи: голый create_task() сборщик мусора вправе убрать до того,
# как письмо уйдёт (та же грабля, что в chat_mail).
_tasks: set = set()


def reply_address(number: int) -> str | None:
    """Адрес, с которого ответ вернётся именно в эту задачу. None — ящик не задан."""
    inbox = parseaddr(settings.chat_mail_inbox)[1]
    if not inbox or "@" not in inbox:
        return None
    local, domain = inbox.rsplit("@", 1)
    return f"{local}+t{number}@{domain}"


def task_from_address(address: str) -> int | None:
    """Обратный разбор: `ящик+t<номер>@домен` → номер задачи. None — адрес не наш."""
    addr = parseaddr(address or "")[1].lower()
    if "+t" not in addr or "@" not in addr:
        return None
    tag = addr.rsplit("@", 1)[0].split("+t", 1)[1]
    return int(tag) if tag.isdigit() else None


def _body(number: int, title: str, author: str, note: str | None,
          description: str | None, due: str | None, reply_to: str | None) -> tuple[str, str]:
    """Текст и HTML письма-поручения.

    Всё, что пришло от людей, экранируем: письмо уходит наружу от почты компании,
    и незакрытый тег в описании превращает поручение в готовую фишинговую
    страницу у получателя.
    """
    head = f"Задача №{number}: {title}"
    hint = ("Ответьте на это письмо — ваш ответ увидят в карточке задачи."
            if reply_to else "Это уведомление о задаче.")
    lines = [head, "", f"Поручил: {author}"]
    if due:
        lines.append(f"Срок: {due}")
    if note:
        lines += ["", note]
    if description:
        lines += ["", description]
    plain = "\n".join([*lines, "", "— — —", hint])

    def block(label: str, value: str) -> str:
        return (f'<div style="color:#64748b;margin-bottom:4px">{html_escape(label)}</div>'
                f'<div style="white-space:pre-wrap;margin-bottom:12px">{html_escape(value)}</div>')

    html = (
        '<!doctype html><html><body style="margin:0;background:#f1f5f9;'
        'font-family:Arial,Helvetica,sans-serif">'
        '<div style="max-width:640px;margin:24px auto;background:#fff;border:1px solid #e2e8f0;'
        'border-radius:12px;overflow:hidden">'
        f'<div style="background:#0f172a;color:#fff;padding:12px 20px;font-size:14px">'
        f'{html_escape(head)}</div>'
        '<div style="padding:20px;color:#0f172a;font-size:14px;line-height:1.6">'
        + block("Поручил", author)
        + (block("Срок", due) if due else "")
        + (block("Что нужно", note) if note else "")
        + (block("Подробности", description) if description else "")
        + '</div>'
        '<div style="padding:10px 20px;background:#f8fafc;color:#64748b;font-size:12px;'
        f'border-top:1px solid #e2e8f0">{html_escape(hint)}</div></div></body></html>'
    )
    return plain, html


def enabled() -> bool:
    """Есть ли куда и чем писать. Канал, который не настроен, обязан честно
    говорить о себе в интерфейсе, а не молча глотать поручения."""
    return bool(settings.chat_mail_inbox and settings.smtp_host)


def send_delegation_async(email: str, number: int, title: str, author: str,
                          note: str | None = None, description: str | None = None,
                          due: str | None = None) -> None:
    """Отправить поручение внешнему участнику. Fire-and-forget.

    Своя задача и свои ошибки: недоступный SMTP не должен ронять делегирование —
    запись о нём уже сделана, и человек видит её в карточке.
    """
    if not enabled():
        return
    reply = reply_address(number)
    plain, html = _body(number, title, author, note, description, due, reply)

    async def _run() -> None:
        try:
            await send_notice([email], f"Задача №{number}: {title}", plain, html,
                              reply_to=reply)
        except Exception as exc:  # noqa: BLE001 — почта не должна ронять задачу
            logger.warning("[task-mail] поручение №%s на %s: %s", number, email, exc)

    _spawn(_run())


def send_notice_async(emails: list[str], subject: str, text: str) -> None:
    """Короткое уведомление своим: поручили, упомянули, ответила внешняя сторона.

    Подписок и категорий здесь нет намеренно: это письмо конкретному человеку о
    его работе, а не рассылка администраторам о событии пространства (та живёт в
    `notify.py` со своими правилами).
    """
    targets = [e for e in emails if e]
    if not targets or not settings.smtp_host:
        return

    async def _run() -> None:
        try:
            await send_notice(targets, subject, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[task-mail] уведомление «%s»: %s", subject, exc)

    _spawn(_run())


async def send_notice_checked(emails: list[str], subject: str,
                              text: str) -> tuple[bool, str | None]:
    """Отправить регламентное письмо и вернуть подтверждённый результат."""
    targets = [email for email in emails if email]
    if not targets:
        return False, "Не указан адрес получателя"
    if not settings.smtp_host:
        return False, "SMTP не настроен"
    try:
        await send_notice(targets, subject, text)
        return True, None
    except Exception as exc:  # noqa: BLE001 — планировщик сохранит ошибку для повтора
        logger.warning("[task-mail] уведомление «%s»: %s", subject, exc)
        return False, str(exc)[:500]


def _spawn(coro) -> None:
    try:
        task = asyncio.get_running_loop().create_task(coro)
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except RuntimeError:
        coro.close()  # вне цикла событий (тесты, скрипты) — отправлять некому
