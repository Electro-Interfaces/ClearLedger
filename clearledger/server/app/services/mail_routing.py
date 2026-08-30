"""Куда письмо едет дальше: комната, задача, документ, заявка (docs/MAIL.md).

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

from app.models import (
    ChatMessage, ChatParticipant, ChatRoom, Counterparty, DocCard, DocEvent,
    DocKind, DocVersion, MailAttachment, MailMessage, Task, TaskAttachment,
    TaskEvent, TaskParticipant, User,
)
from app.services import doc_text, file_store

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
    """Положить письмо в ленту задачи её событием и перенести вложения.

    Раньше письмо дописывалось в конец описания задачи, а вложения терялись совсем.
    При этом рядом, в `POST /api/tasks/{номер}/inbound-email`, та же работа сделана
    правильно: событие с автором, идемпотентность по `Message-ID` и возврат мяча.
    Два пути разошлись, здесь они сведены к одному — иначе входящий документ,
    который почти всегда приезжает вложением, пропадал молча.
    """
    task = (await db.execute(select(Task).where(
        Task.company_id == cid, Task.number == number))).scalar_one_or_none()
    if task is None:
        logger.warning("письмо %s: задача №%s не найдена", row.id, number)
        return False

    # Пишет только тот, кого в задачу приглашали: плюс-адрес виден в письме и
    # утекает пересылкой. Правило то же, что у `/inbound-email`, и ослаблять его
    # здесь нельзя — иначе через общий вход в задачу пишет посторонний.
    email = (row.from_email or "").strip().lower()
    author = (await db.execute(
        select(User).join(TaskParticipant, TaskParticipant.user_id == User.id)
        .where(TaskParticipant.task_id == task.id, func.lower(User.email) == email)
    )).scalar_one_or_none()
    if author is None:
        logger.warning("письмо %s: %s не участник задачи №%s",
                       row.id, email or "(без адреса)", number)
        return False

    # Повтор ловим по Message-ID: поллер перечитывает ящик после смены UIDVALIDITY.
    if row.message_id:
        dup = (await db.execute(select(TaskEvent.id).where(
            TaskEvent.task_id == task.id,
            TaskEvent.from_value == row.message_id))).scalar_one_or_none()
        if dup is not None:
            return True

    text = (row.body_text or "").strip() or "(письмо без текста)"
    ev = TaskEvent(
        task_id=task.id, kind="mail", user_id=author.id,
        actor_name=row.from_name or author.name or email,
        from_value=row.message_id, note=text)
    db.add(ev)
    await db.flush()

    await _attachments_to_task(db, cid, row, task, ev, author.id)
    # Ответ пришёл — мяч снова у нас.
    task.waiting_for = "us"
    await db.flush()
    return True


async def _attachments_to_task(db: AsyncSession, cid, row: MailMessage, task: Task,
                               event: TaskEvent, author_id) -> int:
    """Перенести вложения письма в файлы задачи.

    Содержимое вложения лежит в самой строке письма, поэтому файл появляется в
    общем хранилище только здесь. Вложение без содержимого пропускаем: строка о
    нём в переписке остаётся, а пустой файл в задаче выглядел бы как испорченный
    документ.
    """
    rows = (await db.execute(select(MailAttachment).where(
        MailAttachment.company_id == cid,
        MailAttachment.message_id == row.id))).scalars().all()
    count = 0
    for att in rows:
        if not att.content:
            continue
        sf = file_store.put(db, cid, att.content,
                            file_name=att.file_name, mime=att.content_type)
        await db.flush()
        db.add(TaskAttachment(task_id=task.id, file_id=sf.id,
                              event_id=event.id, uploaded_by=author_id))
        count += 1
    if count:
        await db.flush()
    return count


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


async def to_doc(db: AsyncSession, cid, row: MailMessage) -> bool:
    """Завести входящий документ из письма известного корреспондента.

    Регистрационный номер не присваивается: автоматизация доставляет документ в
    реестр черновиком, а регистрацию по-прежнему выполняет человек.
    """
    if row.counterparty_id is None:
        logger.warning("письмо %s: документ не создан, корреспондент не опознан", row.id)
        return False
    attachments = (await db.execute(select(MailAttachment).where(
        MailAttachment.company_id == cid,
        MailAttachment.message_id == row.id))).scalars().all()
    attachments = [item for item in attachments if item.content]
    if not attachments:
        logger.warning("письмо %s: документ не создан, нет непустого вложения", row.id)
        return False

    source_ref = f"mail:{row.message_id or row.id}"[:200]
    duplicate = (await db.execute(select(DocCard.id).where(
        DocCard.company_id == cid, DocCard.source == "mail",
        DocCard.source_ref == source_ref))).scalar_one_or_none()
    if duplicate is not None:
        return True
    kind = (await db.execute(select(DocKind).where(
        DocKind.company_id == cid, DocKind.family == "incoming",
        DocKind.is_active.is_(True)).order_by(DocKind.sort_order))).scalars().first()
    if kind is None:
        logger.warning("письмо %s: документ не создан, нет входящего вида", row.id)
        return False
    counterparty = await db.get(Counterparty, row.counterparty_id)
    if counterparty is None or counterparty.company_id != cid:
        logger.warning("письмо %s: корреспондент принадлежит другой компании", row.id)
        return False

    doc = DocCard(
        company_id=cid, kind_id=kind.id, kind_code=kind.code,
        family=kind.family, direction=kind.direction,
        title=(row.subject or attachments[0].file_name or "Входящий документ")[:500],
        summary=(row.body_text or "")[:4000] or None,
        counterparty_id=counterparty.id, counterparty_name=counterparty.name or "",
        external_date=row.sent_at.date() if row.sent_at else None,
        source="mail", source_ref=source_ref, has_files=True, current_revision=1)
    db.add(doc)
    await db.flush()
    db.add(DocEvent(
        doc_id=doc.id, kind="mail", actor_name=row.from_name or row.from_email,
        to_value=kind.name, note=f"автоматически из письма {row.from_email or '—'}"))

    role_revisions = {"body": 0, "attachment": 0}
    for index, attachment in enumerate(attachments):
        role = "body" if index == 0 else "attachment"
        role_revisions[role] += 1
        mime = attachment.content_type or "application/octet-stream"
        stored = file_store.put(
            db, cid, attachment.content, file_name=attachment.file_name, mime=mime)
        await db.flush()
        db.add(DocVersion(
            company_id=cid, doc_id=doc.id, revision=role_revisions[role], role=role,
            file_id=stored.id, file_name=stored.file_name, mime=mime,
            size_bytes=len(attachment.content),
            sha256=attachment.sha256 or stored.fingerprint,
            content_text=(await doc_text.extract(
                attachment.content, mime, stored.file_name)) or ""))
    await db.flush()
    return True


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
    if rule.action == "doc":
        return "doc" if await to_doc(db, cid, row) else None
    if rule.action == "inbox":
        return "inbox" if await to_support_inbox(db, cid, row) else None
    return None


# Ящики, за которыми нет человека: автоответчики, отчёты и служебные рассылки.
# Обращение от них означало бы разговор, в котором некому отвечать, — а очередь
# оператора живёт тем, что каждая строка в ней требует ответа.
_ROBOT_LOCALPARTS = (
    "noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon",
    "postmaster", "bounce", "bounces", "abuse", "dmarc", "dmarc-report",
    "dmarcreport", "notification", "notifications", "automailer",
)


def is_robot_sender(address: str | None) -> bool:
    """Письмо от машины, а не от человека."""
    local = (address or "").split("@", 1)[0].strip().lower()
    if not local:
        return True
    return any(local == p or local.startswith(f"{p}-") or local.startswith(f"{p}+")
               or local.startswith(f"{p}.") for p in _ROBOT_LOCALPARTS)


async def to_support_inbox(db: AsyncSession, cid, row: MailMessage) -> bool:
    """Письмо — в очередь обращений Поддержки.

    Не заявка и не документ: заявка всегда про объект, документ — про вложение, а
    человек просто написал. Разговор — это разговор, откуда бы он ни пришёл, и
    место у него одно: общая очередь, где лежат звонки и обращения из пространств.

    Два отказа здесь важнее самой доставки:

    * **робот.** Отчёт DMARC, автоответ «письмо не доставлено» и рассылка — не
      обращение: отвечать на них некому, а в очереди каждая строка ждёт ответа.
    * **свой же ящик.** Ответ поддержки уходит письмом; вернись он обращением —
      получится разговор системы с собой, и петля будет расти сама.

    Отказ не теряет письмо: оно уже сохранено в переписке компании, и человек его
    там увидит.
    """
    from sqlalchemy import func

    from app.models import MailAccount
    from app.services import support_mirror

    sender = (row.from_email or "").strip().lower()
    if is_robot_sender(sender):
        logger.info("письмо %s: обращение не заводим, отправитель служебный (%s)",
                    row.id, sender)
        return False

    own = await db.scalar(select(func.count()).select_from(MailAccount).where(
        MailAccount.company_id == cid, func.lower(MailAccount.address) == sender))
    if own:
        logger.info("письмо %s: обращение не заводим, письмо от своего ящика", row.id)
        return False

    account = await db.get(MailAccount, row.account_id) if row.account_id else None
    ok = await support_mirror.mirror_mail(
        db, cid, row, reply_inbox=account.address if account else None)
    if not ok:
        logger.warning("письмо %s: обращение не заведено", row.id)
    return ok
