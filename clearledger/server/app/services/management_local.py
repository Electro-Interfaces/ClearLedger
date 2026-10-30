"""Read-only проекции через действующие ACL источника, без побочных ensure/commit."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_product
from app.models import CalendarEvent, ChatParticipant, ChatRoom, Task, User
from app.services.management_config import Kind
from app.services.management_schemas import ManagementRecord


async def read_local(db: AsyncSession, user: User, cid: uuid.UUID, kind: Kind, *,
                     query: str, date_from: datetime | None, date_to: datetime | None,
                     limit: int) -> tuple[list[ManagementRecord], bool]:
    from app.services.app_registry import company_apps
    apps = {a["code"]: a for a in await company_apps(db, cid)}
    product = "chat" if kind == "chats" else ("docs" if "docs" in apps else "plan")
    if not apps.get(product, {}).get("enabled"):
        raise HTTPException(403, "Продукт источника выключен")
    if kind == "chats":
        await assert_company_product(str(cid), user, db, "chat")
        return await _chats(db, user, cid, query, limit)

    # Тот же гейт продукта, что у исходных /tasks и /work/calendar.
    from app.services.task_access import assert_work as _assert_work
    from app.services.task_queries import names as _names, not_personal as _not_personal
    from app.services.task_access import is_admin as _is_admin, visible_to as _visible_to
    await _assert_work(str(cid), user, db)
    if kind == "tasks":
        sel = select(Task).where(Task.company_id == cid, _not_personal(),
                                 _visible_to(user, await _is_admin(db, cid, user)))
        if query:
            sel = sel.where(Task.title.icontains(query, autoescape=True, escape="\\"))
        rows = list((await db.execute(sel.order_by(Task.updated_at.desc(), Task.id)
                                     .limit(limit + 1))).scalars())
        truncated = len(rows) > limit
        rows = rows[:limit]
        names = await _names(db, rows)
        return [ManagementRecord(source_id=t.id, kind=kind, title=t.title,
                                 status=t.status, updated_at=t.updated_at, due_at=t.due_at,
                                 author_name=names[t.id].get("author"),
                                 assignee_name=names[t.id].get("assignee"),
                                 project_name=names[t.id].get("project")) for t in rows], truncated

    # Объединение «мой» + «общий» календарь; закрытая встреча — только участникам.
    # Используем исходный общий предикат, без прав администратора на чужое личное.
    from app.services.calendar_queries import my_events_clause as _my_events_clause
    sel = select(CalendarEvent).where(
        CalendarEvent.company_id == cid,
        or_(_my_events_clause(user.id), CalendarEvent.visibility == "company"),
        CalendarEvent.starts_at < date_to, CalendarEvent.ends_at > date_from)
    if query:
        sel = sel.where(CalendarEvent.title.icontains(query, autoescape=True, escape="\\"))
    rows = list((await db.execute(sel.order_by(CalendarEvent.starts_at, CalendarEvent.id)
                                 .limit(limit + 1))).scalars())
    truncated = len(rows) > limit
    rows = rows[:limit]
    ids = {r.organizer_id for r in rows}
    names = dict((await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()) if ids else {}
    return [ManagementRecord(source_id=e.id, kind=kind, title=e.title,
                             subtitle=e.tz, status=e.status, updated_at=e.updated_at,
                             starts_at=e.starts_at, ends_at=e.ends_at,
                             author_name=names.get(e.organizer_id)) for e in rows], truncated


async def _chats(db: AsyncSession, user: User, cid: uuid.UUID, query: str,
                 limit: int) -> tuple[list[ManagementRecord], bool]:
    from app.routers.chat_router import _assert_participant, _chat_scope

    # Все поддерживаемые runtime имеют этот исходный helper. В старом demo
    # services.chat_scope ещё нет; не заменяем отсутствие ACL открытым доступом.
    scope = await _chat_scope(user, cid, db)
    sel = (select(ChatRoom).join(ChatParticipant, and_(
        ChatParticipant.room_id == ChatRoom.id, ChatParticipant.user_id == user.id))
        .where(ChatRoom.company_id == cid, ChatRoom.is_active.is_(True),
               ChatRoom.is_archived.is_(False), ChatRoom.scope_ticket_id.is_(None),
               ChatRoom.scope_task_id.is_(None)))
    # Это отбор списка; сам доступ ниже проверяет исходная _assert_participant.
    if scope:
        sel = sel.where(or_(ChatRoom.type == "direct", ChatRoom.scope_product == scope))
    out = []
    # Stream не ограничивает скрытыми строками лимит видимых результатов.
    rows = await db.stream_scalars(sel.order_by(ChatRoom.id))
    try:
        async for candidate in rows:
            try:
                room = await _assert_participant(candidate.id, user, db)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            title = room.name
            if not title and room.type == "direct":
                title = (await db.execute(select(User.name).join(
                    ChatParticipant, ChatParticipant.user_id == User.id).where(
                    ChatParticipant.room_id == room.id, User.id != user.id)
                    .order_by(User.id).limit(1))).scalar_one_or_none()
            title = title or "Чат"
            if query and query.casefold() not in title.casefold():
                continue
            out.append(ManagementRecord(source_id=room.id, kind="chats", title=title,
                                        status=room.type))
            if len(out) > limit:
                return out[:limit], True
    finally:
        await rows.close()
    # Не запрашиваем текст/счётчики сообщений: история до history_from закрыта.
    return out, False
