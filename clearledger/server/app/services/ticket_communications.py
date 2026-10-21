"""Актуальный actor/ticket ACL принадлежит Поддержке, не копии public.tickets."""
from __future__ import annotations
import uuid
import httpx
from fastapi import HTTPException
from sqlalchemy import select
from app.models import App, ChatParticipant, User, UserCompany
from app.services import sso
from app.services.support_scope import support_company_id
from app.services.space_projection import _internal_base_url
from app.services.app_registry import company_apps

STAFF_PURPOSE = "support_staff"

def is_ticket_room(room):
    return room.scope_ticket_id is not None

def is_staff_room(room):
    return (is_ticket_room(room) and room.scope_purpose == STAFF_PURPOSE
            and room.scope_product == "support" and room.audience == "internal")

async def access(db, cid, user, ticket_id, *, event=None, candidates=False):
    """Ни superadmin, ни старое участие не заменяют текущий Support ACL."""
    if user is None or user.mail_only or await db.get(UserCompany, (user.id, cid)) is None:
        raise HTTPException(403, "Нет доступа к взаимодействию заявки")
    mapped = await support_company_id(db, cid)
    if not mapped or not any(a["code"] == "support" and a["enabled"] for a in await company_apps(db, cid)):
        raise HTTPException(404, "Поддержка не подключена компании")
    app = await db.scalar(select(App).where(App.code == "support"))
    token = sso.sign_service_token(aud="support", scope="ticket.communication",
        app_company_id=str(mapped), actor_id=str(user.id))
    if app is None or not token:
        raise HTTPException(503, "Взаимодействие временно недоступно")
    tid = str(uuid.UUID(str(ticket_id)))
    action = "communication-candidates" if candidates else "communication-events" if event is not None else "communication-access"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(f"{_internal_base_url(app, 'support')}/api/v1/eco/tickets/{tid}/{action}",
                headers={"Authorization": f"Bearer {token}"}, json=event or {})
    except httpx.HTTPError:
        raise HTTPException(503, "Поддержка временно недоступна") from None
    if response.status_code in (403, 404):
        raise HTTPException(response.status_code, "Взаимодействие заявки недоступно")
    if response.status_code != 200:
        raise HTTPException(503, "Поддержка не подтвердила доступ")
    try:
        data = response.json()
        if not candidates and (data.get("ticketId") != tid or data.get("supportCompanyId") != str(mapped)
                or data.get("actorCoreUserId") != str(user.id)
                or type(data.get("canStaffChat")) is not bool or type(data.get("canVideo")) is not bool):
            raise ValueError()
        if candidates and (not isinstance(data.get("candidates"),list) or len(data["candidates"])>50
                or any(not isinstance(x,dict) or not x.get("coreUserId") for x in data["candidates"])):
            raise ValueError()
        if event is not None and data.get("ok") is not True:
            raise ValueError()
    except (ValueError, AttributeError):
        raise HTTPException(503, "Поддержка не подтвердила контекст") from None
    return data

async def assert_staff_room(db, room, user, *, require_member=True):
    if not is_staff_room(room) or not room.is_active:
        raise HTTPException(404, "Чат не найден")  # legacy mixed не становится private
    if require_member and await db.scalar(select(ChatParticipant.id).where(
            ChatParticipant.room_id == room.id, ChatParticipant.user_id == user.id)) is None:
        raise HTTPException(404, "Чат не найден")
    result = await access(db, room.company_id, user, room.scope_ticket_id)
    if not result["canStaffChat"]:
        raise HTTPException(404, "Чат не найден")
    return result

async def ensure_staff_room(db, cid, user, ticket_id):
    from sqlalchemy import text
    from app.models import ChatRoom
    tid = uuid.UUID(str(ticket_id))
    proof = await access(db, cid, user, tid)
    if not proof["canStaffChat"]:
        raise HTTPException(403, "Служебное обсуждение недоступно")
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"support-staff:{cid}:{tid}"})
    room = await db.scalar(select(ChatRoom).where(ChatRoom.company_id == cid,
        ChatRoom.scope_ticket_id == tid, ChatRoom.scope_purpose == STAFF_PURPOSE,
        ChatRoom.is_active.is_(True)))
    if room is not None:
        await assert_staff_room(db, room, user)
        return room
    room = ChatRoom(company_id=cid, type="group", name="Служебное обсуждение заявки",
        created_by=user.id, scope_ticket_id=tid,
        scope_product="support", scope_purpose=STAFF_PURPOSE, audience="internal")
    db.add(room)
    await db.flush()
    db.add(ChatParticipant(room_id=room.id, user_id=user.id, role="owner"))
    await db.commit()
    return room

async def recipient_allowed(db, room, user_id):
    if not is_ticket_room(room):
        return True
    user = await db.get(User, uuid.UUID(str(user_id)))
    if user is None:
        return False
    try:
        await assert_staff_room(db, room, user)
        return True
    except HTTPException:
        return False

async def delivery_allowed(channel, payload, user_id):
    """Тот же gate для межпроцессного WS и персональных mention previews."""
    from app.database import async_session_factory
    from app.models import ChatRoom
    rid = channel[5:] if channel.startswith("chat:") else payload.get("roomId")
    if not channel.startswith("chat:") and not str(payload.get("type", "")).startswith("chat:"):
        return True
    if not rid:
        return True
    try:
        room_id = uuid.UUID(str(rid))
    except (ValueError, TypeError):
        return True  # opaque internal non-room channels; REST/subscribe accept UUID only
    try:
        async with async_session_factory() as db:
            room = await db.get(ChatRoom, room_id)
            if room is None or not await recipient_allowed(db, room, user_id):
                return False
            if is_ticket_room(room):
                from app.models import ChatMessage
                since = await db.scalar(select(ChatParticipant.history_from).where(
                    ChatParticipant.room_id == room.id, ChatParticipant.user_id == uuid.UUID(str(user_id))))
                if since is not None:
                    ids = [payload.get("replyTo")]
                    if payload.get("type") in ("chat:message", "chat:edit", "message:edited"):
                        ids.append(payload.get("id"))
                    pinned = payload.get("pinnedMessage")
                    if isinstance(pinned,dict):
                        ids.append(pinned.get("id"))
                    for message_id in filter(None,ids):
                        message = await db.get(ChatMessage,uuid.UUID(str(message_id)))
                        if message is not None and message.created_at < since:
                            return False
            return True
    except (ValueError, TypeError, HTTPException):
        return False
