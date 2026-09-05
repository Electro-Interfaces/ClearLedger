from fastapi import HTTPException
from sqlalchemy import select, text

from app.models import ChatParticipant, ChatRoom, User, UserCompany
from app.services import work_contexts


async def ensure_room(db, cid, user, ref, *, purpose="main", audience="internal", participant_ids=()):
    from app.routers.chat_router import _is_insider, _assert_participant
    context = await work_contexts.resolve(db, cid, user, ref)
    if not user.is_superadmin and not await _is_insider(user, cid):
        raise HTTPException(403, "Группу приложения создаёт сотрудник пространства")
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": f"chat-context:{cid}:{ref}:{purpose}"})
    room = await db.scalar(select(ChatRoom).where(ChatRoom.company_id == cid,
        ChatRoom.scope_ref == ref, ChatRoom.scope_purpose == purpose, ChatRoom.is_active.is_(True)))
    if room:
        await _assert_participant(room.id, user, db)
        return room
    members = []
    for uid in set(participant_ids) - {user.id}:
        person = await db.get(User, uid)
        if not person or not await db.get(UserCompany, (uid, cid)):
            raise HTTPException(400, "Участник не состоит в пространстве")
        if audience == "internal" and (person.mail_only or not await _is_insider(person, cid)):
            raise HTTPException(400, "Во внутреннюю группу можно добавить только сотрудников")
        members.append(uid)
    room = ChatRoom(company_id=cid, type="group", name=context["title"][:200], created_by=user.id,
        scope_product=context["application"], scope_ref=ref, scope_purpose=purpose, audience=audience,
        scope_object_id=context.get("object_id"))
    db.add(room)
    await db.flush()
    db.add(ChatParticipant(room_id=room.id, user_id=user.id, role="owner"))
    for uid in members:
        db.add(ChatParticipant(room_id=room.id, user_id=uid, role="member"))
    await db.flush()
    return room
