"""Правила доступа к чатам и граница истории, общие для предметных сервисов.

assert_participant может добавить foreign-access audit и запланировать уведомление;
транзакцией, flush/commit и отправкой сообщений по-прежнему владеет caller.
Три callback нужны только для late-bound hooks старого chat_router.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.deps import scope_company_id
from app.models import ChatParticipant, ChatRoom, User
from app.services.chat_scope import chat_scope_of

# Один throttle для service и legacy router, включая вызовы clear().
FOREIGN_SEEN: dict[tuple[uuid.UUID, uuid.UUID], datetime] = {}
FOREIGN_QUIET = timedelta(hours=1)



async def is_insider(user: User, cid: uuid.UUID) -> bool:
    """Свой сотрудник пространства — тот, для кого эта организация ОСНОВНАЯ.

    Партнёры и клиенты входят в пространство членством (`user_companies`), но их
    основная компания другая. Создавать чаты им пока нельзя (решение МАГа 30.07.2026):
    разговор в пространстве инициирует хозяин пространства.
    """
    return user.company_id == cid


async def audit_foreign_access(room: ChatRoom, user: User, db: AsyncSession, *,
                               seen=None, quiet=None, write=None) -> None:
    """Записать в журнал заход в разговор, участником которого человек не является.

    Право суперадмина войти в любой чат остаётся (без него не разобрать инцидент),
    но остаётся и след: «кто заходил» видно в журнале действий пространства.
    """
    seen = seen if seen is not None else FOREIGN_SEEN
    quiet = quiet if quiet is not None else FOREIGN_QUIET
    write = write if write is not None else log_audit
    key = (user.id, room.id)
    now = datetime.now(timezone.utc)
    previous = seen.get(key)
    if previous and now - previous < quiet:
        return
    seen[key] = now
    await write(db, actor=user, company_id=room.company_id, action="chat.foreign_access",
                    target=room.name or ("личная переписка" if room.type == "direct" else "чат"),
                    details={"roomId": str(room.id), "type": room.type})


async def assert_participant(room_id: uuid.UUID, user: User, db: AsyncSession, *,
                             company_of: Callable[..., Awaitable[uuid.UUID]] | None = None,
                             chat_scope: Callable[..., Awaitable[str | None]] | None = None,
                             audit_foreign: Callable[..., Awaitable[None]] | None = None) -> ChatRoom:
    """Комната существует, активна, юзер в ней участник и она принадлежит ВЫБРАННОЙ
    организации — иначе 404 (не палим чужое).

    Организации пространства строго изолированы: у мультиорганизационного человека
    (наш сотрудник, состоящий во всех) работа идёт в одной организации за раз, и
    комната соседней недоступна, пока он в неё не переключился. Без этой сверки
    членства хватало, чтобы прямым запросом достать чат другой организации.
    """
    company_of = company_of if company_of is not None else scope_company_id
    chat_scope = chat_scope if chat_scope is not None else chat_scope_of
    audit_foreign = audit_foreign if audit_foreign is not None else audit_foreign_access
    room = await db.get(ChatRoom, room_id)
    if room is None or not room.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    # Личные чаты компании не принадлежат — их изолирует состав участников.
    if room.company_id is not None and room.type != "direct":
        if room.company_id != await company_of(user, db):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    if room.scope_ticket_id is not None:
        from app.services.ticket_communications import assert_staff_room
        await assert_staff_room(db, room, user)
    if room.scope_task_id is not None:
        from app.services.task_access import assert_task_room
        await assert_task_room(db, room, user)
    p = (await db.execute(select(ChatParticipant.id).where(
        ChatParticipant.room_id == room_id, ChatParticipant.user_id == user.id))).scalar_one_or_none()
    if p is None and not user.is_superadmin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    # Контур — та же изоляция, что между организациями, только внутри одной: членство
    # в комнате вне своего приложения ничего не открывает. Проверка здесь, а не в
    # каждой ручке: через эту функцию идут и чтение ленты, и отправка, и вложения.
    # Комнаты предмета (заявка, задача) контуром не режутся: в список пространства
    # они не попадают вовсе (см. `list_rooms`), открываются только из карточки, и
    # границу им держит участие плюс актуальный ACL предмета выше. Иначе
    # оператор контакт-центра получал 404 на обсуждение СВОЕЙ заявки — комнату
    # заводят без продукта, и контур не совпадал никогда.
    if (room.company_id is not None and room.type != "direct"
            and room.scope_ticket_id is None and room.scope_task_id is None):
        scope = await chat_scope(user, room.company_id, db)
        if scope and room.scope_product != scope:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    if p is None:
        await audit_foreign(room, user, db)
    return room


async def history_from(room_id: uuid.UUID, user: User, db: AsyncSession) -> datetime | None:
    """С какого момента человеку видна переписка комнаты.

    None — с самого начала (так у всех, кого добавили обычным порядком). Время —
    его позвали «с чистого листа»: прошлое группы закрыто, и закрыто везде, где
    история отдаётся, — в ленте, поиске, счётчике непрочитанного, превью в списке
    и закреплённом сообщении. Достаточно одной незакрытой двери, чтобы правило
    перестало существовать.
    """
    return (await db.execute(select(ChatParticipant.history_from).where(
        ChatParticipant.room_id == room_id,
        ChatParticipant.user_id == user.id))).scalar_one_or_none()
