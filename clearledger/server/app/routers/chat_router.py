"""
Чат (внутренний мессенджер) — порт ядра TSupport на FastAPI.

REST /api/chat/* + WebSocket /api/chat/ws?token=JWT.
Комнаты компании (Общий чат) + личные (direct) + группы; company-scoped,
доступ к комнате = членство в chat_participants. Live-обновления и presence — WS.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import (
    APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status,
)
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import decode_token, get_current_user
from app.database import async_session_factory, get_db
from app.deps import capture_company_header, scope_company_id
from app.models import (
    ChatFolder, ChatMessage, ChatMessageReaction, ChatParticipant, ChatRoom, User, UserCompany,
)
from app.services.chat_ws import manager

# capture_company_header кладёт X-Company-Id в contextvar до тела эндпоинта —
# так пространство чата/заявок = ВЫБРАННАЯ в UI организация (строгая изоляция).
router = APIRouter(prefix="/chat", tags=["Чат"],
                   dependencies=[Depends(capture_company_header)])

GENERAL_ROOM_NAME = "Общий чат"


# ── helpers ──────────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _company_of(user: User, db: AsyncSession) -> uuid.UUID:
    """Пространство чата/заявок = ВЫБРАННАЯ в UI организация: заголовок
    X-Company-Id с проверкой членства (→ 403 для чужой) либо дефолтная компания
    юзера. Организации строго изолированы: сотрудник видит чаты и сотрудников
    ТОЛЬКО той организации, в которой сейчас находится — пространства не
    перемешиваются (даже у мультикомпанийного юзера/суперадмина)."""
    return await scope_company_id(user, db)


async def _member_ids(user_id: uuid.UUID, db: AsyncSession) -> set[uuid.UUID]:
    """Компании, где юзер состоит (для проверки принадлежности собеседников)."""
    rows = (await db.execute(
        select(UserCompany.company_id).where(UserCompany.user_id == user_id)
    )).scalars().all()
    return set(rows)


async def _assert_participant(room_id: uuid.UUID, user: User, db: AsyncSession) -> ChatRoom:
    """Комната существует, активна, и юзер в ней участник — иначе 404 (не палим чужое)."""
    room = await db.get(ChatRoom, room_id)
    if room is None or not room.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    p = (await db.execute(select(ChatParticipant.id).where(
        ChatParticipant.room_id == room_id, ChatParticipant.user_id == user.id))).scalar_one_or_none()
    if p is None and not user.is_superadmin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    return room


SYSTEM_ROOMS = [("general", GENERAL_ROOM_NAME), ("news", "Объявления")]


async def ensure_company_rooms(user: User, cid: uuid.UUID, db: AsyncSession) -> None:
    """Ленивое создание системных комнат компании (Общий чат, Объявления) +
    членство текущего юзера. Писать в «Объявления» могут только admin (в роуте)."""
    for kind, room_name in SYSTEM_ROOMS:
        room = (await db.execute(select(ChatRoom).where(
            ChatRoom.company_id == cid, ChatRoom.kind == kind, ChatRoom.is_active.is_(True),
        ))).scalar_one_or_none()
        if room is None:
            room = ChatRoom(type="company", kind=kind, name=room_name,
                            company_id=cid, created_by=user.id)
            db.add(room)
            try:
                await db.flush()
            except Exception:  # noqa: BLE001 — гонка, ловит unique-индекс
                await db.rollback()
                room = (await db.execute(select(ChatRoom).where(
                    ChatRoom.company_id == cid, ChatRoom.kind == kind,
                    ChatRoom.is_active.is_(True)))).scalar_one_or_none()
        if room is not None:
            exists = (await db.execute(select(ChatParticipant.id).where(
                ChatParticipant.room_id == room.id, ChatParticipant.user_id == user.id))).scalar_one_or_none()
            if exists is None:
                db.add(ChatParticipant(room_id=room.id, user_id=user.id, role="member"))
                await db.flush()


def _can_write(room: ChatRoom, user: User) -> bool:
    """Право писать в комнату. В «Объявления» (news) — только admin/суперадмин."""
    if room.kind == "news":
        return user.is_superadmin or user.role == "admin"
    return True


# ── schemas ──────────────────────────────────────────────────────────────────
class PinnedOut(BaseModel):
    id: str
    content: str
    userName: str | None = None


class RoomOut(BaseModel):
    id: str
    type: str
    kind: str | None = None
    name: str | None = None
    isArchived: bool = False
    participantCount: int = 0
    unreadCount: int = 0
    directPeerId: str | None = None
    lastMessage: str | None = None
    lastMessageAt: str | None = None
    createdBy: str | None = None
    pinnedMessage: PinnedOut | None = None


class ParticipantOut(BaseModel):
    userId: str
    name: str
    role: str          # роль в комнате (member/admin)
    online: bool = False


class RoomDetailOut(RoomOut):
    participants: list[ParticipantOut] = Field(default_factory=list)


class ReactionOut(BaseModel):
    emoji: str
    count: int
    mine: bool = False


class MessageOut(BaseModel):
    id: str
    roomId: str
    userId: str | None = None
    userName: str | None = None
    type: str = "text"
    content: str = ""
    fileUrl: str | None = None
    fileName: str | None = None
    fileSize: int | None = None
    replyTo: str | None = None
    replyPreview: str | None = None
    replyAuthor: str | None = None
    isEdited: bool = False
    isDeleted: bool = False
    readCount: int = 0
    reactions: list[ReactionOut] = Field(default_factory=list)
    createdAt: str


class CreateRoomBody(BaseModel):
    type: str = "group"                    # direct | group
    name: str | None = None
    participantIds: list[str] = Field(default_factory=list)


class SendMessageBody(BaseModel):
    content: str = ""
    replyTo: str | None = None
    type: str = "text"
    fileUrl: str | None = None
    fileName: str | None = None
    fileSize: int | None = None
    mentions: list[str] = Field(default_factory=list)


class AddParticipantBody(BaseModel):
    userId: str


class ReactBody(BaseModel):
    emoji: str


class PinBody(BaseModel):
    messageId: str | None = None


class EditMessageBody(BaseModel):
    content: str


class FolderBody(BaseModel):
    name: str
    roomIds: list[str] = Field(default_factory=list)


class ReorderBody(BaseModel):
    folderIds: list[str]


# ── список комнат ────────────────────────────────────────────────────────────
@router.get("/rooms", response_model=list[RoomOut])
async def list_rooms(
    archived: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company_of(current_user, db)
    await ensure_company_rooms(current_user, cid, db)

    # Только комнаты ВЫБРАННОЙ организации — иначе мультикомпанийный юзер увидел
    # бы чаты двух орг вперемешку. Строгая изоляция пространств.
    rows = (await db.execute(
        select(ChatRoom, ChatParticipant.last_read_at)
        .join(ChatParticipant, and_(ChatParticipant.room_id == ChatRoom.id,
                                    ChatParticipant.user_id == current_user.id))
        .where(ChatRoom.is_active.is_(True), ChatRoom.is_archived.is_(archived),
               ChatRoom.company_id == cid)
    )).all()

    out: list[RoomOut] = []
    for room, last_read in rows:
        pcount = (await db.execute(select(func.count()).select_from(ChatParticipant)
                  .where(ChatParticipant.room_id == room.id))).scalar() or 0
        unread = (await db.execute(select(func.count()).select_from(ChatMessage).where(
            ChatMessage.room_id == room.id, ChatMessage.deleted_at.is_(None),
            ChatMessage.user_id != current_user.id,
            ChatMessage.created_at > (last_read or datetime(1970, 1, 1, tzinfo=timezone.utc)),
        ))).scalar() or 0
        last = (await db.execute(select(ChatMessage).where(
            ChatMessage.room_id == room.id, ChatMessage.deleted_at.is_(None))
            .order_by(ChatMessage.created_at.desc()).limit(1))).scalar_one_or_none()
        name, peer_id = room.name, None
        if room.type == "direct":
            other = (await db.execute(
                select(ChatParticipant.user_id, User.name)
                .join(User, User.id == ChatParticipant.user_id)
                .where(ChatParticipant.room_id == room.id, ChatParticipant.user_id != current_user.id)
                .limit(1))).first()
            if other:
                peer_id = str(other[0])
                name = name or other[1]
        pinned = await _pinned_out(room, db)
        out.append(RoomOut(
            id=str(room.id), type=room.type, kind=room.kind, name=name,
            isArchived=room.is_archived, participantCount=int(pcount), unreadCount=int(unread),
            directPeerId=peer_id, createdBy=str(room.created_by) if room.created_by else None,
            lastMessage=(last.content if last and not last.deleted_at else None) if last else None,
            lastMessageAt=(last.created_at.isoformat() if last else None),
            pinnedMessage=pinned,
        ))
    # системные комнаты вверх (Общий чат, Объявления), затем по времени последнего сообщения
    _sys = {"general": 0, "news": 1}
    out.sort(key=lambda r: (
        _sys.get(r.kind or "", 2),
        r.lastMessageAt is None, "" if r.lastMessageAt is None else _neg(r.lastMessageAt),
    ))
    return out


def _neg(iso: str) -> str:
    """Инверсия ISO-времени для сортировки по убыванию в кортеже (свежие выше)."""
    return "".join(chr(0x10FFFF - ord(c)) if c.isdigit() else c for c in iso)


async def _pinned_out(room: ChatRoom, db: AsyncSession) -> PinnedOut | None:
    if not room.pinned_message_id:
        return None
    m = await db.get(ChatMessage, room.pinned_message_id)
    if m is None or m.deleted_at is not None:
        return None
    txt = m.content if m.type == "text" else (m.file_name or f"[{m.type}]")
    return PinnedOut(id=str(m.id), content=(txt or "")[:200], userName=m.user_name)


# ── создать комнату (direct дедуп / group) ───────────────────────────────────
@router.post("/rooms", response_model=RoomDetailOut, status_code=status.HTTP_201_CREATED)
async def create_room(
    body: CreateRoomBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company_of(current_user, db)
    pids: list[uuid.UUID] = []
    for s in body.participantIds:
        try:
            pids.append(uuid.UUID(s))
        except (ValueError, TypeError):
            continue
    pids = [p for p in pids if p != current_user.id]

    # direct: собеседник должен быть в той же компании; дедуп существующей комнаты
    if body.type == "direct":
        if len(pids) != 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Личный чат — ровно один собеседник")
        peer = pids[0]
        if cid not in await _member_ids(peer, db):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Собеседник не из вашей компании")
        existing = (await db.execute(
            select(ChatRoom.id).where(
                ChatRoom.type == "direct", ChatRoom.is_active.is_(True), ChatRoom.company_id == cid,
                ChatRoom.id.in_(select(ChatParticipant.room_id).where(ChatParticipant.user_id == current_user.id)),
                ChatRoom.id.in_(select(ChatParticipant.room_id).where(ChatParticipant.user_id == peer)),
            ).limit(1))).scalar_one_or_none()
        if existing:
            return await get_room(str(existing), current_user, db)

    room = ChatRoom(type=body.type, kind=None, name=body.name, company_id=cid, created_by=current_user.id)
    db.add(room)
    await db.flush()
    db.add(ChatParticipant(room_id=room.id, user_id=current_user.id, role="admin"))
    for peer in pids:
        # участник должен быть членом компании комнаты
        if cid in await _member_ids(peer, db):
            db.add(ChatParticipant(room_id=room.id, user_id=peer, role="member"))
    await db.flush()
    return await get_room(str(room.id), current_user, db)


# ── детали комнаты + участники ───────────────────────────────────────────────
@router.get("/rooms/{room_id}", response_model=RoomDetailOut)
async def get_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    parts = (await db.execute(
        select(ChatParticipant.user_id, ChatParticipant.role, User.name)
        .join(User, User.id == ChatParticipant.user_id)
        .where(ChatParticipant.room_id == rid))).all()
    online = manager.online_user_ids()
    plist = [ParticipantOut(userId=str(uid), name=nm, role=rl, online=str(uid) in online)
             for uid, rl, nm in parts]
    name, peer_id = room.name, None
    if room.type == "direct":
        for p in plist:
            if p.userId != str(current_user.id):
                peer_id = p.userId
                name = name or p.name
    return RoomDetailOut(
        id=str(room.id), type=room.type, kind=room.kind, name=name,
        isArchived=room.is_archived, participantCount=len(plist), directPeerId=peer_id,
        createdBy=str(room.created_by) if room.created_by else None, participants=plist,
        pinnedMessage=await _pinned_out(room, db),
    )


# ── сообщения ────────────────────────────────────────────────────────────────
def _msg_out(m: ChatMessage, read_count: int, reply: ChatMessage | None,
             reactions: list[ReactionOut] | None = None) -> MessageOut:
    deleted = m.deleted_at is not None
    return MessageOut(
        id=str(m.id), roomId=str(m.room_id),
        userId=str(m.user_id) if m.user_id else None, userName=m.user_name,
        type=m.type, content="" if deleted else m.content,
        fileUrl=None if deleted else m.file_url,
        fileName=None if deleted else m.file_name,
        fileSize=None if deleted else m.file_size,
        replyTo=str(m.reply_to) if m.reply_to else None,
        replyPreview=(None if not reply or reply.deleted_at else reply.content[:120]),
        replyAuthor=(None if not reply else reply.user_name),
        isEdited=m.is_edited, isDeleted=deleted, readCount=read_count,
        reactions=reactions or [],
        createdAt=m.created_at.isoformat(),
    )


async def _load_reactions(
    message_ids: list[uuid.UUID], me: uuid.UUID, db: AsyncSession,
) -> dict[uuid.UUID, list[ReactionOut]]:
    """Агрегация реакций по сообщениям: emoji → count + пометка своей."""
    if not message_ids:
        return {}
    rows = (await db.execute(select(
        ChatMessageReaction.message_id, ChatMessageReaction.emoji, ChatMessageReaction.user_id,
    ).where(ChatMessageReaction.message_id.in_(message_ids)))).all()
    agg: dict[uuid.UUID, dict[str, dict]] = {}
    for mid, emoji, uid in rows:
        slot = agg.setdefault(mid, {}).setdefault(emoji, {"count": 0, "mine": False})
        slot["count"] += 1
        if uid == me:
            slot["mine"] = True
    return {
        mid: [ReactionOut(emoji=e, count=v["count"], mine=v["mine"]) for e, v in emap.items()]
        for mid, emap in agg.items()
    }


@router.get("/rooms/{room_id}/messages", response_model=list[MessageOut])
async def list_messages(
    room_id: str,
    limit: int = Query(100, ge=1, le=200),
    before: str | None = Query(None),
    search: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    await _assert_participant(rid, current_user, db)
    stmt = select(ChatMessage).where(ChatMessage.room_id == rid)
    if before:
        try:
            stmt = stmt.where(ChatMessage.created_at < datetime.fromisoformat(before))
        except ValueError:
            pass
    if search:
        stmt = stmt.where(ChatMessage.content.ilike(f"%{search}%"), ChatMessage.deleted_at.is_(None))
    msgs = list((await db.execute(stmt.order_by(ChatMessage.created_at.desc()).limit(limit))).scalars().all())
    msgs.reverse()
    # read_count: сколько ДРУГИХ участников прочитали (last_read_at >= created_at)
    reply_ids = {m.reply_to for m in msgs if m.reply_to}
    replies = {}
    if reply_ids:
        for r in (await db.execute(select(ChatMessage).where(ChatMessage.id.in_(reply_ids)))).scalars():
            replies[r.id] = r
    reactions = await _load_reactions([m.id for m in msgs], current_user.id, db)
    out = []
    for m in msgs:
        rc = (await db.execute(select(func.count()).select_from(ChatParticipant).where(
            ChatParticipant.room_id == rid, ChatParticipant.user_id != m.user_id,
            ChatParticipant.last_read_at.is_not(None),
            ChatParticipant.last_read_at >= m.created_at))).scalar() or 0
        out.append(_msg_out(m, int(rc), replies.get(m.reply_to), reactions.get(m.id)))
    return out


@router.post("/rooms/{room_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    room_id: str,
    body: SendMessageBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    if not _can_write(room, current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "В «Объявления» пишут только администраторы")
    mtype = body.type if body.type in ("text", "image", "video", "file") else "text"
    content = (body.content or "").strip()
    has_file = bool(body.fileUrl)
    if not content and not has_file:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое сообщение")
    reply_to = None
    if body.replyTo:
        try:
            reply_to = uuid.UUID(body.replyTo)
        except (ValueError, TypeError):
            reply_to = None
    msg = ChatMessage(
        room_id=rid, user_id=current_user.id, user_name=current_user.name,
        type=mtype, content=content, reply_to=reply_to,
        file_url=body.fileUrl or None, file_name=body.fileName or None,
        file_size=body.fileSize if isinstance(body.fileSize, int) else None,
    )
    db.add(msg)
    room.updated_at = _now()
    await db.flush()
    reply = await db.get(ChatMessage, reply_to) if reply_to else None
    payload = _msg_out(msg, 0, reply)
    await db.commit()
    # live-рассылка участникам комнаты
    await manager.broadcast(f"chat:{rid}", {"type": "chat:message", **payload.model_dump()})
    # персональные пуши упомянутым (@) — только реальным участникам комнаты, ≠ автор
    if body.mentions:
        want = {str(u) for u in _uuid_list(body.mentions)} - {str(current_user.id)}
        if want:
            part_ids = {str(u) for u in (await db.execute(select(ChatParticipant.user_id)
                        .where(ChatParticipant.room_id == rid))).scalars().all()}
            for uid in want & part_ids:
                await manager.broadcast(f"user:{uid}", {
                    "type": "chat:mention", "roomId": str(rid), "roomName": room.name,
                    "fromName": current_user.name, "messageId": str(msg.id),
                    "preview": (content or msg.file_name or "")[:120],
                })
    return payload


@router.post("/rooms/{room_id}/read")
async def mark_read(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    await _assert_participant(rid, current_user, db)
    await db.execute(text(
        "UPDATE chat_participants SET last_read_at = now() WHERE room_id = :r AND user_id = :u"
    ), {"r": str(rid), "u": str(current_user.id)})
    await db.commit()
    await manager.broadcast(f"chat:{rid}",
                            {"type": "chat:read", "roomId": str(rid), "userId": str(current_user.id)})
    return {"ok": True}


# ── реакции (toggle) ─────────────────────────────────────────────────────────
@router.post("/rooms/{room_id}/messages/{message_id}/react")
async def react_message(
    room_id: str,
    message_id: str,
    body: ReactBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rid, mid = uuid.UUID(room_id), uuid.UUID(message_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    await _assert_participant(rid, current_user, db)
    emoji = (body.emoji or "").strip()[:16]
    if not emoji:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустая реакция")
    msg = await db.get(ChatMessage, mid)
    if msg is None or msg.room_id != rid or msg.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")
    existing = (await db.execute(select(ChatMessageReaction).where(
        ChatMessageReaction.message_id == mid,
        ChatMessageReaction.user_id == current_user.id))).scalar_one_or_none()
    if existing is not None and existing.emoji == emoji:
        await db.delete(existing)                       # снять свою реакцию
    elif existing is not None:
        existing.emoji = emoji                          # заменить на другую
    else:
        db.add(ChatMessageReaction(message_id=mid, user_id=current_user.id,
                                   user_name=current_user.name, emoji=emoji))
    await db.commit()
    agg = (await _load_reactions([mid], current_user.id, db)).get(mid, [])
    reactions = [r.model_dump() for r in agg]
    await manager.broadcast(f"chat:{rid}", {
        "type": "chat:reaction", "roomId": str(rid), "messageId": str(mid),
        "reactions": [{"emoji": r["emoji"], "count": r["count"]} for r in reactions],
    })
    return {"messageId": str(mid), "reactions": reactions}


# ── закреп сообщения ─────────────────────────────────────────────────────────
@router.post("/rooms/{room_id}/pin")
async def pin_message(
    room_id: str,
    body: PinBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    if body.messageId is None:
        room.pinned_message_id = None
    else:
        try:
            mid = uuid.UUID(body.messageId)
        except (ValueError, TypeError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
        msg = await db.get(ChatMessage, mid)
        if msg is None or msg.room_id != rid or msg.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")
        room.pinned_message_id = mid
    await db.commit()
    pinned = await _pinned_out(room, db)
    await manager.broadcast(f"chat:{rid}", {
        "type": "chat:pin", "roomId": str(rid),
        "pinnedMessage": pinned.model_dump() if pinned else None,
    })
    return {"roomId": str(rid), "pinnedMessage": pinned.model_dump() if pinned else None}


# ── редактирование / удаление сообщения ──────────────────────────────────────
@router.patch("/rooms/{room_id}/messages/{message_id}", response_model=MessageOut)
async def edit_message(
    room_id: str,
    message_id: str,
    body: EditMessageBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rid, mid = uuid.UUID(room_id), uuid.UUID(message_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    await _assert_participant(rid, current_user, db)
    msg = await db.get(ChatMessage, mid)
    if msg is None or msg.room_id != rid or msg.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")
    if msg.user_id != current_user.id and not current_user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Можно править только свои сообщения")
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое сообщение")
    msg.content = content
    msg.is_edited = True
    msg.edited_at = _now()
    await db.commit()
    reply = await db.get(ChatMessage, msg.reply_to) if msg.reply_to else None
    reactions = (await _load_reactions([mid], current_user.id, db)).get(mid)
    payload = _msg_out(msg, 0, reply, reactions)
    await manager.broadcast(f"chat:{rid}", {"type": "message:edited", **payload.model_dump()})
    return payload


@router.delete("/rooms/{room_id}/messages/{message_id}")
async def delete_message(
    room_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rid, mid = uuid.UUID(room_id), uuid.UUID(message_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    msg = await db.get(ChatMessage, mid)
    if msg is None or msg.room_id != rid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")
    my = (await db.execute(select(ChatParticipant.role).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
    can = (msg.user_id == current_user.id or current_user.is_superadmin
           or room.created_by == current_user.id or my == "admin")
    if not can:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет прав удалять это сообщение")
    if msg.deleted_at is None:
        msg.deleted_at = _now()
        if room.pinned_message_id == mid:            # снять закреп при удалении
            room.pinned_message_id = None
        await db.commit()
    await manager.broadcast(f"chat:{rid}", {
        "type": "message:deleted", "roomId": str(rid), "messageId": str(mid)})
    return {"ok": True}


# ── архив комнаты ────────────────────────────────────────────────────────────
async def _set_archived(room_id: str, flag: bool, current_user: User, db: AsyncSession):
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    if room.kind in ("general", "news"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Системный чат нельзя архивировать")
    my = (await db.execute(select(ChatParticipant.role).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
    if not (current_user.is_superadmin or room.created_by == current_user.id or my == "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет прав")
    room.is_archived = flag
    room.archived_at = _now() if flag else None
    await db.commit()
    await manager.broadcast(f"chat:{rid}", {
        "type": "room:archived", "roomId": str(rid), "isArchived": flag})
    return {"ok": True, "isArchived": flag}


@router.post("/rooms/{room_id}/archive")
async def archive_room(room_id: str, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    return await _set_archived(room_id, True, current_user, db)


@router.post("/rooms/{room_id}/unarchive")
async def unarchive_room(room_id: str, current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    return await _set_archived(room_id, False, current_user, db)


# ── папки (группировки чатов) ────────────────────────────────────────────────
class FolderOut(BaseModel):
    id: str
    name: str
    roomIds: list[str] = Field(default_factory=list)
    sortOrder: int = 0


def _folder_out(f: ChatFolder) -> FolderOut:
    return FolderOut(id=str(f.id), name=f.name,
                     roomIds=[str(r) for r in (f.room_ids or [])], sortOrder=f.sort_order or 0)


@router.get("/folders", response_model=list[FolderOut])
async def list_folders(current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ChatFolder).where(ChatFolder.user_id == current_user.id)
            .order_by(ChatFolder.sort_order, ChatFolder.created_at))).scalars().all()
    return [_folder_out(f) for f in rows]


@router.post("/folders", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(body: FolderBody, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    name = (body.name or "").strip()[:80]
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое имя папки")
    rids = _uuid_list(body.roomIds)
    maxo = (await db.execute(select(func.max(ChatFolder.sort_order))
            .where(ChatFolder.user_id == current_user.id))).scalar()
    f = ChatFolder(user_id=current_user.id, name=name, room_ids=rids,
                   sort_order=(maxo or 0) + 1)
    db.add(f)
    await db.commit()
    return _folder_out(f)


@router.patch("/folders/{folder_id}", response_model=FolderOut)
async def update_folder(folder_id: str, body: FolderBody,
                        current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    try:
        fid = uuid.UUID(folder_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    f = await db.get(ChatFolder, fid)
    if f is None or f.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена")
    if body.name is not None and body.name.strip():
        f.name = body.name.strip()[:80]
    f.room_ids = _uuid_list(body.roomIds)
    f.updated_at = _now()
    await db.commit()
    return _folder_out(f)


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    try:
        fid = uuid.UUID(folder_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    f = await db.get(ChatFolder, fid)
    if f is None or f.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена")
    await db.delete(f)
    await db.commit()
    return {"ok": True}


@router.post("/folders/reorder")
async def reorder_folders(body: ReorderBody, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    for i, s in enumerate(body.folderIds):
        try:
            fid = uuid.UUID(s)
        except (ValueError, TypeError):
            continue
        f = await db.get(ChatFolder, fid)
        if f is not None and f.user_id == current_user.id:
            f.sort_order = i
    await db.commit()
    return {"ok": True}


def _uuid_list(items: list[str]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for s in items or []:
        try:
            out.append(uuid.UUID(str(s)))
        except (ValueError, TypeError):
            continue
    return out


# ── участники ────────────────────────────────────────────────────────────────
@router.post("/rooms/{room_id}/participants", status_code=status.HTTP_201_CREATED)
async def add_participant(
    room_id: str,
    body: AddParticipantBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rid = uuid.UUID(room_id)
        target = uuid.UUID(body.userId)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    # право добавлять: создатель, admin комнаты или суперадмин
    my = (await db.execute(select(ChatParticipant.role).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
    if not (current_user.is_superadmin or room.created_by == current_user.id or my == "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет прав добавлять участников")
    if room.company_id not in await _member_ids(target, db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Пользователь не из компании чата")
    exists = (await db.execute(select(ChatParticipant.id).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == target))).scalar_one_or_none()
    if exists is None:
        db.add(ChatParticipant(room_id=rid, user_id=target, role="member"))
        await db.commit()
    return {"ok": True}


# ── поиск юзеров компании ────────────────────────────────────────────────────
@router.get("/users/search")
async def search_users(
    q: str = Query(""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company_of(current_user, db)
    # Только сотрудники ВЫБРАННОЙ организации (user_companies) ≠ я — сотрудников
    # другой организации не видно (изоляция пространств).
    stmt = (select(User.id, User.name, User.email)
            .join(UserCompany, UserCompany.user_id == User.id)
            .where(UserCompany.company_id == cid, User.id != current_user.id))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.email.ilike(like)))
    rows = (await db.execute(stmt.order_by(User.name).limit(20))).all()
    online = manager.online_user_ids()
    return [{"userId": str(uid), "name": nm, "email": em, "online": str(uid) in online}
            for uid, nm, em in rows]


# ── presence ─────────────────────────────────────────────────────────────────
@router.get("/presence")
async def presence(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # юзеры, с кем я в общих комнатах ВЫБРАННОЙ организации (не смешиваем орг.)
    cid = await _company_of(current_user, db)
    my_rooms = (select(ChatParticipant.room_id)
                .join(ChatRoom, ChatRoom.id == ChatParticipant.room_id)
                .where(ChatParticipant.user_id == current_user.id, ChatRoom.company_id == cid))
    rows = (await db.execute(
        select(User.id, User.name)
        .join(ChatParticipant, ChatParticipant.user_id == User.id)
        .where(ChatParticipant.room_id.in_(my_rooms), User.id != current_user.id)
        .distinct())).all()
    online = manager.online_user_ids()
    return [{"userId": str(uid), "name": nm, "online": str(uid) in online} for uid, nm in rows]


# ── WebSocket ────────────────────────────────────────────────────────────────
async def _ws_user(token: str) -> User | None:
    """Аутентификация WS по JWT из query (WS не шлёт заголовки)."""
    try:
        payload = decode_token(token)
        uid = uuid.UUID(payload.get("sub"))
    except Exception:  # noqa: BLE001
        return None
    async with async_session_factory() as db:
        return (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()


async def _ws_can_subscribe(user: User, channel: str, db: AsyncSession) -> bool:
    """Тенант-изоляция подписок: свой user-канал, своя компания, свои комнаты."""
    if user.is_superadmin:
        return True
    if channel == f"user:{user.id}":
        return True
    if channel.startswith("company:"):
        cid = channel.split(":", 1)[1]
        return cid in {str(c) for c in await _member_ids(user.id, db)} or str(user.company_id) == cid
    if channel.startswith("chat:"):
        rid = channel.split(":", 1)[1]
        try:
            p = (await db.execute(select(ChatParticipant.id).where(
                ChatParticipant.room_id == uuid.UUID(rid),
                ChatParticipant.user_id == user.id))).scalar_one_or_none()
            return p is not None
        except (ValueError, TypeError):
            return False
    return False


@router.websocket("/ws")
async def chat_ws(ws: WebSocket, token: str = Query(...)):
    user = await _ws_user(token)
    if user is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    cid = str(user.company_id) if user.company_id else None
    became_online = await manager.connect(ws, str(user.id), cid)
    await ws.send_json({"type": "connected", "userId": str(user.id)})
    if became_online and cid:
        await manager.broadcast(f"company:{cid}",
                                {"type": "presence", "userId": str(user.id),
                                 "userName": user.name, "online": True})
    try:
        while True:
            data = await ws.receive_json()
            mtype = data.get("type")
            if mtype == "ping":
                await ws.send_json({"type": "pong"})
            elif mtype == "subscribe":
                ch = data.get("channel", "")
                async with async_session_factory() as db:
                    ok = await _ws_can_subscribe(user, ch, db)
                if ok:
                    manager.subscribe(ws, ch)
                else:
                    await ws.send_json({"type": "subscribe:denied", "channel": ch})
            elif mtype == "unsubscribe":
                manager.unsubscribe(ws, data.get("channel", ""))
            elif mtype == "typing":
                ch = data.get("channel", "")
                if manager.is_subscribed(ws, ch):
                    await manager.broadcast(ch, {"type": "chat:typing", "userId": str(user.id),
                                                 "userName": user.name}, exclude=ws)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        uid, ucid, became_offline = await manager.disconnect(ws)
        if became_offline and ucid:
            async with async_session_factory() as db:
                await db.execute(text("UPDATE users SET last_seen_at = now() WHERE id = :u"), {"u": uid})
                await db.commit()
            await manager.broadcast(f"company:{ucid}",
                                    {"type": "presence", "userId": uid, "online": False})
