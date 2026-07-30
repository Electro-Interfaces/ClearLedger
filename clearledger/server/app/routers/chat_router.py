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
    ChatFolder, ChatMessage, ChatMessageReaction, ChatParticipant, ChatRoom, Company,
    User, UserCompany,
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


async def _is_space_admin(user: User, cid: uuid.UUID, db: AsyncSession) -> bool:
    """Администратор ПРОСТРАНСТВА: только он создаёт каналы.

    Роль берётся из членства в этой организации, а не из `User.role`: один и тот же
    человек бывает админом в своей компании и обычным участником в чужой.
    """
    if user.is_superadmin:
        return True
    role = (await db.execute(select(UserCompany.role).where(
        UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
    return role == "admin" or user.role == "admin"


async def _is_insider(user: User, cid: uuid.UUID) -> bool:
    """Свой сотрудник пространства — тот, для кого эта организация ОСНОВНАЯ.

    Партнёры и клиенты входят в пространство членством (`user_companies`), но их
    основная компания другая. Создавать чаты им пока нельзя (решение МАГа 30.07.2026):
    разговор в пространстве инициирует хозяин пространства.
    """
    return user.company_id == cid


async def _party_types(db: AsyncSession, cid: uuid.UUID,
                       user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Кто есть кто в ЭТОМ пространстве: `vendor` | `internal` | `partner`.

    Три категории, которые нужно различать в любом разговоре (требование МАГа):
    инженер разработчика платформы (мы), сотрудник самого пространства и человек
    компании-партнёра. Признак живёт в членстве (`user_companies.party_type`) — это не
    права, а ответ на вопрос «с кем я говорю»; тот же источник использует Центр
    управления, поэтому подписи в чате и в карте пространства не разъезжаются.

    Кого в членстве нет (свои по `users.company_id`) — `internal`: они и есть
    пространство.
    """
    if not user_ids:
        return {}
    rows = (await db.execute(select(UserCompany.user_id, UserCompany.party_type).where(
        UserCompany.company_id == cid, UserCompany.user_id.in_(user_ids)))).all()
    by_user = {uid: (pt or "internal") for uid, pt in rows}
    # Суперадмин платформы — это МЫ: учётку с правами на весь контейнер заказчику не
    # выдают, ею работает инженер разработчика. В членстве у него стоит дефолтный
    # `internal` (никто не проставлял принадлежность руками), и без этой поправки
    # поддержка платформы в переписке ничем не отличалась от сотрудника компании.
    # Явно заданные `partner`/`vendor` уважаем — их ставили осознанно.
    supers = set((await db.execute(select(User.id).where(
        User.id.in_(user_ids), User.is_superadmin.is_(True)))).scalars().all())
    return {uid: (by_user.get(uid) if by_user.get(uid) in ("partner", "vendor")
                  else ("vendor" if uid in supers else by_user.get(uid, "internal")))
            for uid in user_ids}


async def _company_titles(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Компании участников — чтобы в списке было видно, чей это сотрудник."""
    if not ids:
        return {}
    rows = (await db.execute(select(Company.id, Company.short_name, Company.name)
                             .where(Company.id.in_(ids)))).all()
    return {r[0]: (r[1] or r[2] or "—") for r in rows}


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


# Базовый набор чатов, который есть в пространстве с первого дня (концепция МАГа
# 30.07.2026). Больше — по потребности, руками: пусто открывшееся пространство не
# объясняет человеку, зачем ему чат, а десяток заготовок он закроет и не вернётся.
#
#   Обновления Элси+  — канал разработчика платформы: что нового в продуктах,
#                       регламентные работы. Пишем в него мы, пространство читает.
#   Объявления        — канал компании: слово руководства сотрудникам. Владельца
#                       назначает администратор (директор, секретарь, кадры).
#   Общий чат         — группа со всеми людьми пространства, включая партнёров:
#                       место, где просто спросить.
#
# Тип комнаты — по смыслу, а не «системная»: канал односторонний (`_can_write`),
# группа говорит вся. Раньше все три были `company`, и «Объявления» вели себя как
# группа — писать мог любой участник.
SYSTEM_ROOMS = [
    ("general", GENERAL_ROOM_NAME, "group"),
    ("news", "Объявления", "channel"),
    ("platform", "Обновления Элси+", "channel"),
]

# Приложения, которым своя группа не нужна: служебная кухня пространства и сервисы,
# у которых обсуждать нечего (сам чат, заявки, конференции). Группа появляется у
# ПРИКЛАДНОГО рабочего места — там, где идёт работа и возникают вопросы по ней.
_NO_GROUP_APPS = {"admin", "data", "info", "connect", "chat", "plan", "conf"}


async def ensure_company_rooms(user: User, cid: uuid.UUID, db: AsyncSession) -> None:
    """Базовый набор чатов пространства + членство ВСЕХ его людей.

    Идемпотентно при любом заходе: комнаты создаются раз, участники добираются.
    Кроме трёх общих комнат (`SYSTEM_ROOMS`) создаются группы подключённых
    приложений — по одной на рабочее место, с привязкой `scope_product`, чтобы в
    самом приложении правая рельса открывала его группу без выбора.
    """
    for kind, room_name, room_type in SYSTEM_ROOMS:
        room = (await db.execute(select(ChatRoom).where(
            ChatRoom.company_id == cid, ChatRoom.kind == kind, ChatRoom.is_active.is_(True),
        ))).scalar_one_or_none()
        if room is None:
            room = ChatRoom(type=room_type, kind=kind, name=room_name,
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
            # Комнаты, созданные до разделения на канал и группу, донастраиваем на
            # месте: иначе в «Объявлениях» пространства продолжает писать любой.
            if room.type == "company":
                room.type = room_type
            # В системные комнаты пространства входят ВСЕ его люди, а не только тот,
            # кто открыл панель. Иначе «Общий чат» не общий: у ГИГ в нём оказалось три
            # человека из шести — остальные панель не открывали, и написать им было
            # некуда. Участники добираются идемпотентно, при любом заходе любого.
            member_ids = set((await db.execute(select(ChatParticipant.user_id).where(
                ChatParticipant.room_id == room.id))).scalars().all())
            # Люди пространства — и те, у кого эта компания основная, и приглашённые в
            # неё через членство: партнёры, клиенты и подрядчики живут во втором списке.
            #
            # Выбираем ИЗ `users`, а не из членства напрямую: в `user_companies` бывают
            # осиротевшие строки (после переноса данных с прода остались членства
            # удалённых людей), и вставка такого id роняет всю операцию по внешнему ключу.
            space_ids = set((await db.execute(select(User.id).where(or_(
                User.company_id == cid,
                User.id.in_(select(UserCompany.user_id).where(UserCompany.company_id == cid)),
            )))).scalars().all())
            space_ids.add(user.id)
            missing = space_ids - member_ids
            for uid in missing:
                db.add(ChatParticipant(room_id=room.id, user_id=uid, role="member"))
            if missing:
                await db.flush()


async def _ensure_app_room(user: User, cid: uuid.UUID, code: str,
                           db: AsyncSession) -> None:
    """Группа приложения — по первому входу В ЭТО приложение, а не на весь каталог.

    Раньше комнаты заводились сразу для всех приложений витрины. Но витрина считает
    приложение включённым и по дефолту профиля: у пилота РусГидро так «подключены»
    шестнадцать, включая «Интернет-магазин» и «Диагностику», — и в чате появлялось
    десять групп, в которые никто никогда не напишет. Пустой список чатов честнее
    списка из пустых групп.

    Теперь группу создаёт сам факт работы: человек открыл рабочее место, рельса
    попросила чаты этого приложения — группа появилась и заселилась. Вопросы по работе
    живут в разрезе своего рабочего места, а не в общем чате, где тонут.

    Состав — все люди пространства: доступ к переписке о работе ≠ доступ к её данным,
    и пересчитывать эффективные права каждого на каждом заходе в чат слишком дорого.
    Лишних администратор выводит вручную (`/admin/rooms/{id}/participants`).
    """
    if not code or code in _NO_GROUP_APPS:
        return
    kind = f"app:{code}"
    room = (await db.execute(select(ChatRoom).where(
        ChatRoom.company_id == cid, ChatRoom.kind == kind,
        ChatRoom.is_active.is_(True)))).scalar_one_or_none()
    if room is None:
        # Имя — как у приложения в витрине этого профиля («Продажи» у энергетика,
        # «Топливо» у топливной сети): один и тот же продукт зовётся по-разному, и чат
        # должен называться так, как рабочее место в меню.
        name = code
        try:
            from app.services import app_registry
            apps = await app_registry.company_apps(db, cid)
            rec = next((a for a in apps if a["code"] == code), None)
            if rec is None or not rec.get("enabled"):
                return                      # приложение пространству не подключено
            name = rec["name"]
        except Exception:                   # noqa: BLE001 — реестр не поднят
            return
        room = ChatRoom(type="group", kind=kind, name=name, company_id=cid,
                        created_by=user.id, scope_product=code)
        db.add(room)
        try:
            await db.flush()
        except Exception:                   # noqa: BLE001 — гонка двух заходов
            await db.rollback()
            return

    member_ids = set((await db.execute(select(ChatParticipant.user_id).where(
        ChatParticipant.room_id == room.id))).scalars().all())
    space_ids = set((await db.execute(select(User.id).where(or_(
        User.company_id == cid,
        User.id.in_(select(UserCompany.user_id).where(UserCompany.company_id == cid)),
    )))).scalars().all())
    space_ids.add(user.id)
    missing = space_ids - member_ids
    for uid in missing:
        db.add(ChatParticipant(room_id=room.id, user_id=uid, role="member"))
    if missing:
        await db.flush()


def _can_write(room: ChatRoom, user: User, room_role: str | None = None) -> bool:
    """Право писать. Канал — односторонний, группа и личный — для всех участников.

    В КАНАЛЕ пишут только владелец и админы канала: это его смысл — новости, рассылка,
    слово руководителя, а не обсуждение. Право даёт роль В КОМНАТЕ (`room_role`), а не
    должность в компании: администратор пространства не должен автоматически говорить
    в чужом канале от чужого имени.
    """
    # Канал платформы ведёт разработчик: пространство читает, что мы выпустили, и
    # не пишет туда от нашего имени — даже администратор компании.
    if room.kind == "platform":
        return user.is_superadmin
    # «Объявления» — канал самой компании: её администратор говорит в нём по должности,
    # назначенный владелец — по роли в комнате.
    if room.kind == "news":
        return user.is_superadmin or user.role == "admin" or room_role in ("owner", "admin")
    if room.type == "channel":
        return user.is_superadmin or room_role in ("owner", "admin")
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
    # Моя роль В ЭТОЙ комнате (owner | admin | member) — по ней панель решает, показывать
    # ли поле ввода: в канале пишут владелец и его админы. Без этого поля фронт судил по
    # виду комнаты, и в канале, открытом администратором, поле ввода было у всех — а
    # отправка возвращала отказ.
    myRole: str | None = None
    # Приложение, к которому привязан чат: панель свойств объясняет, ПОЧЕМУ этот чат
    # здесь виден — «группа приложения Топливо», а не просто «группа».
    scopeProduct: str | None = None


class ParticipantOut(BaseModel):
    userId: str
    name: str
    role: str          # роль в комнате: owner | admin | member
    online: bool = False
    # Свой сотрудник или человек компании-партнёра — и какой именно компании.
    # Без этого в смешанной группе не понять, при ком идёт разговор.
    isExternal: bool = False
    companyName: str | None = None
    # Категория: vendor (разработчик платформы) | internal (свой) | partner (сторонний).
    # `isExternal` оставлен для совместимости — он отвечает только «не наш ли», а
    # инженера поддержки от подрядчика заказчика не отличает.
    partyType: str = "internal"


class RoomDetailOut(RoomOut):
    participants: list[ParticipantOut] = Field(default_factory=list)


class ReactionOut(BaseModel):
    emoji: str
    count: int
    mine: bool = False
    # Имена поставивших: «1» под сообщением не отвечает на вопрос «кто это поставил»,
    # а в группе спрашивают именно это. Первым идёт «Вы», если реакция своя.
    users: list[str] = Field(default_factory=list)


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
    # Кто написал: vendor | internal | partner. Признак стоит у КАЖДОГО сообщения, а не
    # только в списке участников: читая переписку, важно видеть, кто говорит, не сверяясь
    # со составом комнаты.
    authorParty: str | None = None


class CreateRoomBody(BaseModel):
    type: str = "group"                    # direct | group | channel
    name: str | None = None
    participantIds: list[str] = Field(default_factory=list)
    # Приложение, из которого чат создан: чат остаётся в его контексте.
    scopeProduct: str | None = None


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
    product: str | None = Query(
        None, description="Код приложения: вернуть его чаты и общие чаты пространства"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company_of(current_user, db)
    await ensure_company_rooms(current_user, cid, db)
    # Пришли из приложения (правая рельса передаёт его код) — значит в нём работают:
    # заводим его группу, если ещё нет. Верхняя кнопка код не передаёт и ничего не
    # создаёт: она про «все мои чаты», а не про конкретное рабочее место.
    if product:
        await _ensure_app_room(current_user, cid, product, db)

    # Только комнаты ВЫБРАННОЙ организации — иначе мультикомпанийный юзер увидел
    # бы чаты двух орг вперемешку. Строгая изоляция пространств.
    rows = (await db.execute(
        select(ChatRoom, ChatParticipant.last_read_at, ChatParticipant.role)
        .join(ChatParticipant, and_(ChatParticipant.room_id == ChatRoom.id,
                                    ChatParticipant.user_id == current_user.id))
        .where(ChatRoom.is_active.is_(True), ChatRoom.is_archived.is_(archived),
               ChatRoom.company_id == cid,
               # Контекст приложения: правая рельса просит чаты своего приложения, и к
               # ним всегда добавляются чаты без привязки — общие для пространства
               # (личные, «Общий чат», «Объявления»). Верхняя кнопка параметр не
               # передаёт и получает всё: один чат, разные предустановки.
               or_(ChatRoom.scope_product.is_(None), ChatRoom.scope_product == product)
               if product else text("true"))
    )).all()

    out: list[RoomOut] = []
    for room, last_read, my_role in rows:
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
            myRole=my_role,
            scopeProduct=room.scope_product,
        ))
    # системные комнаты вверх (Общий чат, Объявления), затем по времени последнего сообщения
    # В контексте приложения его собственный чат идёт ПЕРВЫМ: человек открыл рельсу в
    # «Топливе» — значит спрашивает про топливо, а общие комнаты пространства нужны ему
    # рядом, но не вперёд.
    _sys = {"general": 0, "news": 1, "platform": 2}
    out.sort(key=lambda r: (
        0 if (product and r.scopeProduct == product) else 1,
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

    # Кто что может создавать (концепция МАГа 30.07.2026):
    #   • канал — только администратор пространства: это рупор организации,
    #     и раздавать его всем нельзя;
    #   • группа и личный чат — любой СВОЙ сотрудник;
    #   • сторонний участник (сотрудник партнёра или клиента) — пока ничего:
    #     разговор в пространстве инициирует хозяин пространства.
    if body.type not in ("direct", "group", "channel"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Тип чата: direct, group или channel")
    if not await _is_insider(current_user, cid) and not current_user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Создавать чаты в этом пространстве могут только его сотрудники")
    if body.type == "channel" and not await _is_space_admin(current_user, cid, db):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Канал создаёт администратор пространства; вам доступны группы и личные чаты")
    if body.type in ("group", "channel") and not (body.name or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "У группы и канала должно быть название")

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

    room = ChatRoom(type=body.type, kind=None, name=body.name, company_id=cid,
                    created_by=current_user.id,
                    # Личный чат контекста не имеет: он про людей, а не про экран.
                    scope_product=(body.scopeProduct or None) if body.type != "direct" else None)
    db.add(room)
    await db.flush()
    # Создатель — ВЛАДЕЛЕЦ: в канале только он и назначенные им админы пишут, и его
    # нельзя вывести из комнаты. Раньше создатель получал «admin», и владельца у
    # комнаты не существовало вовсе.
    db.add(ChatParticipant(room_id=room.id, user_id=current_user.id,
                           role="member" if body.type == "direct" else "owner"))
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
        select(ChatParticipant.user_id, ChatParticipant.role, User.name, User.company_id)
        .join(User, User.id == ChatParticipant.user_id)
        .where(ChatParticipant.room_id == rid))).all()
    online = manager.online_user_ids()
    # Кто в разговоре: свой сотрудник или человек компании-партнёра — и какой именно.
    # В смешанной группе (наши плюс партнёры) без этого не понять, при ком говорим,
    # а это первое, что нужно знать перед тем, как написать.
    ext_cids = {r[3] for r in parts if r[3] is not None and r[3] != room.company_id}
    titles = await _company_titles(db, ext_cids)
    parties = await _party_types(db, room.company_id, {r[0] for r in parts})
    plist = [ParticipantOut(userId=str(uid), name=nm, role=rl, online=str(uid) in online,
                            isExternal=(ucid is not None and ucid != room.company_id),
                            companyName=titles.get(ucid) if ucid != room.company_id else None,
                            partyType=parties.get(uid, "internal"))
                        for uid, rl, nm, ucid in parts]
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
             reactions: list[ReactionOut] | None = None,
             author_party: str | None = None) -> MessageOut:
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
        authorParty=author_party,
    )


async def _load_reactions(
    message_ids: list[uuid.UUID], me: uuid.UUID, db: AsyncSession,
) -> dict[uuid.UUID, list[ReactionOut]]:
    """Агрегация реакций по сообщениям: emoji → count, пометка своей и ИМЕНА авторов.

    Имя берём join-ом к `users` в том же запросе: отдельный поход за именами на каждую
    реакцию — это N+1 на длинной переписке.
    """
    if not message_ids:
        return {}
    rows = (await db.execute(select(
        ChatMessageReaction.message_id, ChatMessageReaction.emoji,
        ChatMessageReaction.user_id, User.name,
    ).outerjoin(User, User.id == ChatMessageReaction.user_id)
     .where(ChatMessageReaction.message_id.in_(message_ids)))).all()
    agg: dict[uuid.UUID, dict[str, dict]] = {}
    for mid, emoji, uid, uname in rows:
        slot = agg.setdefault(mid, {}).setdefault(
            emoji, {"count": 0, "mine": False, "users": []})
        slot["count"] += 1
        if uid == me:
            slot["mine"] = True
            slot["users"].insert(0, "Вы")
        else:
            slot["users"].append(uname or "Участник")
    return {
        mid: [ReactionOut(emoji=e, count=v["count"], mine=v["mine"], users=v["users"])
              for e, v in emap.items()]
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
    # Принадлежность авторов — одним запросом на всю страницу переписки.
    parties = await _party_types(db, room.company_id,
                                 {m.user_id for m in msgs if m.user_id})
    out = []
    for m in msgs:
        rc = (await db.execute(select(func.count()).select_from(ChatParticipant).where(
            ChatParticipant.room_id == rid, ChatParticipant.user_id != m.user_id,
            ChatParticipant.last_read_at.is_not(None),
            ChatParticipant.last_read_at >= m.created_at))).scalar() or 0
        out.append(_msg_out(m, int(rc), replies.get(m.reply_to), reactions.get(m.id),
                            parties.get(m.user_id) if m.user_id else None))
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
    # Роль В КОМНАТЕ решает, можно ли писать: в канале это владелец и его админы.
    room_role = (await db.execute(select(ChatParticipant.role).where(
        ChatParticipant.room_id == room.id,
        ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
    if not _can_write(room, current_user, room_role):
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
    # Своё же сообщение уходит подписчикам сокета — с принадлежностью автора, иначе у
    # только что отправленного бейджа нет, а после перезагрузки он появляется.
    parties = await _party_types(db, room.company_id, {current_user.id})
    payload = _msg_out(msg, 0, reply, None, parties.get(current_user.id))
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

# ═══════════════════════════════════════════════════════════════════════════
# Приложение «Чаты» — управление чатами пространства (только администраторы)
#
# Обычные ручки выше отвечают на «мои чаты»: человек видит те комнаты, где он
# участник. Администратору нужен другой вопрос — «что вообще происходит в
# пространстве»: все каналы и группы, кто владелец, кто в составе, где партнёры,
# что заброшено. Поэтому отдельная ветка `/chat/admin/*` с проверкой роли на входе,
# а не расширение обычного списка флагом.
# ═══════════════════════════════════════════════════════════════════════════


async def _assert_space_admin(user: User, cid: uuid.UUID, db: AsyncSession) -> None:
    if not await _is_space_admin(user, cid, db):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Управление чатами доступно администраторам пространства")


class AdminRoomOut(BaseModel):
    id: str
    type: str                       # company | channel | group | direct
    kind: str | None = None
    name: str | None = None
    scopeProduct: str | None = None
    isArchived: bool = False
    ownerName: str | None = None
    participantCount: int = 0
    externalCount: int = 0          # сколько людей компаний-партнёров
    messageCount: int = 0
    lastMessageAt: str | None = None
    createdAt: str | None = None


class AdminRoomPatch(BaseModel):
    name: str | None = None
    scopeProduct: str | None = None      # '' → снять привязку к приложению


class AdminRoleBody(BaseModel):
    role: str                            # owner | admin | member


class AdminCreateRoomBody(BaseModel):
    """Создание чата администратором пространства.

    Отличие от обычного создания (`POST /rooms`): владельцем можно назначить ДРУГОГО
    человека. Так и работает канал — администратор его открывает, а ведёт назначенный
    (директор говорит от себя, кадры от себя), и это разные люди.
    """
    type: str = "channel"                # channel | group
    name: str
    ownerId: str | None = None           # кто ведёт; по умолчанию создатель
    participantIds: list[str] = Field(default_factory=list)
    everyone: bool = False               # заселить всех людей пространства
    scopeProduct: str | None = None      # привязка к приложению


class AdminAddPeopleBody(BaseModel):
    userIds: list[str] = Field(default_factory=list)
    everyone: bool = False


class AdminPersonOut(BaseModel):
    userId: str
    name: str
    email: str | None = None
    isExternal: bool = False             # сотрудник компании-партнёра
    companyName: str | None = None
    partyType: str = "internal"          # vendor | internal | partner


@router.get("/admin/rooms", response_model=list[AdminRoomOut])
async def admin_rooms(
    archived: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Все чаты пространства с составом и активностью — для приложения «Чаты»."""
    cid = await _company_of(current_user, db)
    await _assert_space_admin(current_user, cid, db)

    rooms = (await db.execute(select(ChatRoom).where(
        ChatRoom.company_id == cid, ChatRoom.is_active.is_(True),
        ChatRoom.is_archived.is_(archived),
    ).order_by(ChatRoom.updated_at.desc()))).scalars().all()
    if not rooms:
        return []
    ids = [r.id for r in rooms]

    # Состав комнат одним запросом: у администратора их сотни, и на каждую по два
    # запроса — это тот самый N+1, из-за которого экран открывается секундами.
    parts = (await db.execute(
        select(ChatParticipant.room_id, ChatParticipant.role, User.name, User.company_id)
        .join(User, User.id == ChatParticipant.user_id)
        .where(ChatParticipant.room_id.in_(ids)))).all()
    counts = (await db.execute(
        select(ChatMessage.room_id, func.count(), func.max(ChatMessage.created_at))
        .where(ChatMessage.room_id.in_(ids), ChatMessage.deleted_at.is_(None))
        .group_by(ChatMessage.room_id))).all()
    msg_by = {r[0]: (int(r[1]), r[2]) for r in counts}

    by_room: dict[uuid.UUID, list] = {}
    for rid, role, name, ucid in parts:
        by_room.setdefault(rid, []).append((role, name, ucid))

    out: list[AdminRoomOut] = []
    for r in rooms:
        members = by_room.get(r.id, [])
        owner = next((n for role, n, _ in members if role == "owner"), None)
        n_msg, last_at = msg_by.get(r.id, (0, None))
        out.append(AdminRoomOut(
            id=str(r.id), type=r.type, kind=r.kind, name=r.name,
            scopeProduct=r.scope_product, isArchived=r.is_archived,
            ownerName=owner,
            participantCount=len(members),
            externalCount=sum(1 for _, _, ucid in members if ucid is not None and ucid != cid),
            messageCount=n_msg,
            lastMessageAt=last_at.isoformat() if last_at else None,
            createdAt=r.created_at.isoformat() if r.created_at else None,
        ))
    return out


@router.get("/admin/people", response_model=list[AdminPersonOut])
async def admin_people(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Все люди пространства — для выбора владельца и состава.

    Не `/users/search`: тот ищет по членству и отдаёт двадцать записей без себя —
    для подсказки в переписке этого хватает, для состава канала нет. Здесь список
    полный, со своими и с людьми партнёров, помеченными их компанией.
    """
    cid = await _company_of(current_user, db)
    await _assert_space_admin(current_user, cid, db)
    rows = (await db.execute(select(User.id, User.name, User.email, User.company_id)
                             .where(or_(
                                 User.company_id == cid,
                                 User.id.in_(select(UserCompany.user_id).where(
                                     UserCompany.company_id == cid)),
                             )).order_by(User.name))).all()
    titles = await _company_titles(db, {r[3] for r in rows if r[3] and r[3] != cid})
    parties = await _party_types(db, cid, {r[0] for r in rows})
    return [AdminPersonOut(
        userId=str(uid), name=nm or (em or "—"), email=em,
        isExternal=bool(ucid and ucid != cid),
        companyName=titles.get(ucid) if ucid and ucid != cid else None,
        partyType=parties.get(uid, "internal"),
    ) for uid, nm, em, ucid in rows]


@router.post("/admin/rooms", response_model=AdminRoomOut, status_code=status.HTTP_201_CREATED)
async def admin_create_room(
    body: AdminCreateRoomBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Открыть канал или группу пространства и назначить того, кто её ведёт."""
    cid = await _company_of(current_user, db)
    await _assert_space_admin(current_user, cid, db)
    if body.type not in ("channel", "group"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Тип: channel или group")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "У канала и группы должно быть название")

    # Кого можно позвать: только людей ЭТОГО пространства — ни своих из другой
    # компании платформы, ни случайный id из запроса.
    space_ids = set((await db.execute(select(User.id).where(or_(
        User.company_id == cid,
        User.id.in_(select(UserCompany.user_id).where(UserCompany.company_id == cid)),
    )))).scalars().all())

    def _uuid(s: str) -> uuid.UUID | None:
        try:
            return uuid.UUID(s)
        except (ValueError, TypeError):
            return None

    owner_id = _uuid(body.ownerId) if body.ownerId else current_user.id
    if owner_id is None or (owner_id not in space_ids and owner_id != current_user.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Владельцем можно назначить только человека этого пространства")

    room = ChatRoom(type=body.type, name=name, company_id=cid,
                    created_by=current_user.id,
                    scope_product=(body.scopeProduct or "").strip() or None)
    db.add(room)
    await db.flush()

    members = space_ids if body.everyone else {
        u for u in (_uuid(s) for s in body.participantIds) if u in space_ids}
    members |= {owner_id, current_user.id}
    for uid in members:
        db.add(ChatParticipant(room_id=room.id, user_id=uid,
                               role="owner" if uid == owner_id else "member"))
    await db.commit()

    rooms = await admin_rooms(archived=False, current_user=current_user, db=db)
    found = next((x for x in rooms if x.id == str(room.id)), None)
    if found is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Чат создан, но не прочитан")
    return found


@router.post("/admin/rooms/{room_id}/participants", status_code=status.HTTP_204_NO_CONTENT)
async def admin_add_people(
    room_id: str, body: AdminAddPeopleBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Добавить людей в чат — списком или всё пространство сразу.

    Списком, а не по одному: набирая канал на тридцать человек, администратор иначе
    делает тридцать запросов и ждёт каждый.
    """
    cid = await _company_of(current_user, db)
    await _assert_space_admin(current_user, cid, db)
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await db.get(ChatRoom, rid)
    if room is None or room.company_id != cid or not room.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")

    space_ids = set((await db.execute(select(User.id).where(or_(
        User.company_id == cid,
        User.id.in_(select(UserCompany.user_id).where(UserCompany.company_id == cid)),
    )))).scalars().all())
    if body.everyone:
        wanted = space_ids
    else:
        wanted = set()
        for s in body.userIds:
            try:
                u = uuid.UUID(s)
            except (ValueError, TypeError):
                continue
            if u in space_ids:
                wanted.add(u)
    have = set((await db.execute(select(ChatParticipant.user_id).where(
        ChatParticipant.room_id == rid))).scalars().all())
    for uid in wanted - have:
        db.add(ChatParticipant(room_id=rid, user_id=uid, role="member"))
    await db.commit()


@router.patch("/admin/rooms/{room_id}", response_model=AdminRoomOut)
async def admin_patch_room(
    room_id: str, body: AdminRoomPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Переименовать чат или перевесить его на другое приложение."""
    cid = await _company_of(current_user, db)
    await _assert_space_admin(current_user, cid, db)
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await db.get(ChatRoom, rid)
    if room is None or room.company_id != cid or not room.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    # Системные комнаты («Общий чат», «Объявления») не переименовываем: их имя —
    # часть устройства пространства, а не пользовательская настройка.
    if body.name is not None and room.kind is None:
        room.name = body.name.strip() or room.name
    if body.scopeProduct is not None:
        room.scope_product = body.scopeProduct.strip() or None
    await db.commit()
    rooms = await admin_rooms(archived=room.is_archived, current_user=current_user, db=db)
    found = next((x for x in rooms if x.id == str(rid)), None)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    return found


@router.patch("/admin/rooms/{room_id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_set_role(
    room_id: str, user_id: str, body: AdminRoleBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Назначить роль в чате: владелец, админ канала или обычный участник."""
    cid = await _company_of(current_user, db)
    await _assert_space_admin(current_user, cid, db)
    if body.role not in ("owner", "admin", "member"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Роль: owner, admin или member")
    try:
        rid, uid = uuid.UUID(room_id), uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await db.get(ChatRoom, rid)
    if room is None or room.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    p = (await db.execute(select(ChatParticipant).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == uid))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Участник не найден")
    # Владелец в комнате один: назначая нового, прежнего опускаем до админа, иначе
    # «владельцев» становится двое и непонятно, кто отвечает за канал.
    if body.role == "owner":
        for other in (await db.execute(select(ChatParticipant).where(
            ChatParticipant.room_id == rid, ChatParticipant.role == "owner",
            ChatParticipant.user_id != uid))).scalars().all():
            other.role = "admin"
    p.role = body.role
    await db.commit()


@router.delete("/admin/rooms/{room_id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_remove_participant(
    room_id: str, user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Вывести человека из чата (владельца — нельзя, сначала передайте владение)."""
    cid = await _company_of(current_user, db)
    await _assert_space_admin(current_user, cid, db)
    try:
        rid, uid = uuid.UUID(room_id), uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await db.get(ChatRoom, rid)
    if room is None or room.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    p = (await db.execute(select(ChatParticipant).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == uid))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Участник не найден")
    if p.role == "owner":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Нельзя вывести владельца: сначала передайте владение другому")
    await db.delete(p)
    await db.commit()
