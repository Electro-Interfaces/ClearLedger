"""
Чат (внутренний мессенджер) — порт ядра TSupport на FastAPI.

REST /api/chat/* + WebSocket /api/chat/ws?token=JWT.
Комнаты компании (Общий чат) + личные (direct) + группы; company-scoped,
доступ к комнате = членство в chat_participants. Live-обновления и presence — WS.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status,
)
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete as sa_delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import (
    assert_company_product, decode_token, get_company_by_api_key, get_current_user,
)
from app.config import get_settings
from app.database import async_session_factory, get_db
from app.deps import capture_company_header, scope_company_id
from app.models import (
    ChatFolder, ChatMessage, ChatMessageReaction, ChatParticipant, ChatPushSubscription,
    ChatPoll, ChatPollVote, ChatRoom, ChatTicketLink, Company, Counterparty,
    DocRelation, ServiceLocation, User, UserCompany,
)
from app.services import chat_mail, process_templates, web_push
from app.services import link_preview as link_preview_service
from app.services.space_projection import ProjectionError, create_object_ticket
from app.services.chat_ws import manager

# capture_company_header кладёт X-Company-Id в contextvar до тела эндпоинта —
# так пространство чата/заявок = ВЫБРАННАЯ в UI организация (строгая изоляция).
router = APIRouter(prefix="/chat", tags=["Чат"],
                   dependencies=[Depends(capture_company_header)])

GENERAL_ROOM_NAME = "Общий чат"


# ── helpers ──────────────────────────────────────────────────────────────────
async def _assert_company_object(object_id: str, cid: uuid.UUID, db: AsyncSession) -> None:
    """Объект должен принадлежать компании чата — чужой привязать нельзя."""
    loc_cid = (await db.execute(select(ServiceLocation.company_id).where(
        ServiceLocation.id == object_id))).scalar_one_or_none()
    if loc_cid != cid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Объект не из этого пространства")


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
    человек бывает админом в своей компании и обычным участником в чужой. Глобальное
    поле `users.role` тут НЕ смотрим — у перенесённых с прода людей оно стоит как
    попало, и на пилоте четверо рядовых сотрудников получали доступ ко всему
    управлению чатами пространства (та же грабля, что в `_is_company_admin`).
    """
    if user.is_superadmin:
        return True
    role = (await db.execute(select(UserCompany.role).where(
        UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
    return role == "admin"


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


# Когда о заходе в чужой разговор уже записали: (кто, куда) → момент. Троттлинг в
# памяти процесса, а не запрос к журналу — `_assert_participant` зовётся на каждое
# действие в чате, и без него листание ленты писало бы в аудит десятки строк подряд.
# ponytail: словарь растёт, пока живёт процесс; чистить, если суперадминов станет много.
_FOREIGN_SEEN: dict[tuple[uuid.UUID, uuid.UUID], datetime] = {}
_FOREIGN_QUIET = timedelta(hours=1)


async def _audit_foreign_access(room: ChatRoom, user: User, db: AsyncSession) -> None:
    """Записать в журнал заход в разговор, участником которого человек не является.

    Право суперадмина войти в любой чат остаётся (без него не разобрать инцидент),
    но остаётся и след: «кто заходил» видно в журнале действий пространства.
    """
    key = (user.id, room.id)
    now = datetime.now(timezone.utc)
    seen = _FOREIGN_SEEN.get(key)
    if seen and now - seen < _FOREIGN_QUIET:
        return
    _FOREIGN_SEEN[key] = now
    await log_audit(db, actor=user, company_id=room.company_id, action="chat.foreign_access",
                    target=room.name or ("личная переписка" if room.type == "direct" else "чат"),
                    details={"roomId": str(room.id), "type": room.type})


async def _assert_participant(room_id: uuid.UUID, user: User, db: AsyncSession) -> ChatRoom:
    """Комната существует, активна, юзер в ней участник и она принадлежит ВЫБРАННОЙ
    организации — иначе 404 (не палим чужое).

    Организации пространства строго изолированы: у мультиорганизационного человека
    (наш сотрудник, состоящий во всех) работа идёт в одной организации за раз, и
    комната соседней недоступна, пока он в неё не переключился. Без этой сверки
    членства хватало, чтобы прямым запросом достать чат другой организации.
    """
    room = await db.get(ChatRoom, room_id)
    if room is None or not room.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    # Личные чаты компании не принадлежат — их изолирует состав участников.
    if room.company_id is not None and room.type != "direct":
        if room.company_id != await _company_of(user, db):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    p = (await db.execute(select(ChatParticipant.id).where(
        ChatParticipant.room_id == room_id, ChatParticipant.user_id == user.id))).scalar_one_or_none()
    if p is None and not user.is_superadmin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    if p is None:
        await _audit_foreign_access(room, user, db)
    return room


def _событие(kind: str, message: dict) -> dict:
    """Событие сокета из сообщения — так, чтобы вид события пережил распаковку.

    У сообщения есть своё поле `type` (text/image/file/system), и в форме
    `{"type": kind, **message}` оно затирало вид события: подписчик получал
    `type: "text"` вместо `chat:message` и не узнавал событие вовсе. Вид ставим
    последним, а тип самого сообщения отдаём отдельным полем — по нему лента
    отличает служебную запись от реплики.
    """
    return {**message, "type": kind, "messageType": message.get("type") or "text"}


async def _history_from(room_id: uuid.UUID, user: User, db: AsyncSession) -> datetime | None:
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


# Базовый набор чатов, который есть в пространстве с первого дня (концепция МАГа
# 30.07.2026). Больше — по потребности, руками: пусто открывшееся пространство не
# объясняет человеку, зачем ему чат, а десяток заготовок он закроет и не вернётся.
#
#   Обновления платформы — канал разработчика платформы: что нового в продуктах,
#                       регламентные работы. Пишем в него мы, пространство читает.
#                       Без бренда в имени: пространство заказчика не упоминает
#                       Элси+ (проверка white-label, 31.07.2026).
#   Объявления        — канал компании: слово руководства сотрудникам. Владельца
#                       назначает администратор (директор, секретарь, кадры).
#   Общий чат         — группа со всеми людьми пространства, включая партнёров:
#                       место, где просто спросить.
#
# Групп под рабочие места пространство НЕ заводит (решение МАГа 30.07.2026): группа
# нужна тогда, когда людям есть о чём говорить, и создают её они сами — привязку к
# приложению задают в диалоге создания. Автоматика плодила чаты, в которые никто не
# написал: витрина считает приложение включённым и по дефолту профиля, поэтому у
# пилота их набегало по десятку.
#
# Тип комнаты — по смыслу, а не «системная»: канал односторонний (`_can_write`),
# группа говорит вся. Раньше все три были `company`, и «Объявления» вели себя как
# группа — писать мог любой участник.
SYSTEM_ROOMS = [
    ("general", GENERAL_ROOM_NAME, "group"),
    ("news", "Объявления", "channel"),
    ("platform", "Обновления платформы", "channel"),
]

async def ensure_company_rooms(user: User, cid: uuid.UUID, db: AsyncSession) -> None:
    """Базовый набор чатов пространства + членство ВСЕХ его людей.

    Идемпотентно при любом заходе: комнаты создаются раз, участники добираются.
    Создаются ТОЛЬКО три общих комнаты (`SYSTEM_ROOMS`) — групп под приложения
    пространство не заводит (решение МАГа, подтверждено 31.07.2026: у пилотов
    автогруппы трижды вычищали руками): группу создают люди сами, привязку к
    приложению задают в диалоге создания.
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
            # Почтовые участники сюда НЕ входят: человек, живущий в своей почте,
            # попадает ровно в те разговоры, куда его позвали. Иначе ему письмами
            # уходят и объявления компании, и новости платформы — рассылка, на
            # которую он не подписывался.
            space_ids = set((await db.execute(select(User.id).where(
                User.mail_only.is_(False),
                or_(
                    User.company_id == cid,
                    User.id.in_(select(UserCompany.user_id).where(UserCompany.company_id == cid)),
                ),
            ))).scalars().all())
            space_ids.add(user.id)
            missing = space_ids - member_ids
            if missing:
                # ON CONFLICT, а не просто `db.add`: эту дописку одновременно делают все
                # открытые вкладки пространства (список чатов обновляется по таймеру), и
                # без него второй пришедший ловил уникальный индекс `uq_chat_participants`
                # → 500 на списке чатов. Ровно сценарий первого дня, когда четырнадцать
                # человек заходят в пространство разом и у каждого `missing` не пуст.
                # id и is_muted проставляем явно: у модели это python-side default, а
                # он в core-insert по таблице не всегда доезжает (уже ловили на
                # `space_inbound_keys` — NOT NULL id при вставке мимо ORM).
                await db.execute(pg_insert(ChatParticipant.__table__).values([
                    {"id": uuid.uuid4(), "room_id": room.id, "user_id": uid,
                     "role": "member", "is_muted": False} for uid in missing
                ]).on_conflict_do_nothing(index_elements=["room_id", "user_id"]))



async def _is_company_admin(db: AsyncSession, company_id: uuid.UUID | None,
                            user: User) -> bool:
    """Администратор ЭТОГО пространства — по членству, а не по полю `users.role`.

    Глобальная роль осталась от прежней модели и у перенесённых с прода людей
    стоит как попало: на пилоте право писать в «Объявления» получили четверо
    рядовых сотрудников, а настоящий администратор компании — нет.
    """
    if user.is_superadmin:
        return True
    if company_id is None:
        return False
    role = (await db.execute(select(UserCompany.role).where(
        UserCompany.user_id == user.id, UserCompany.company_id == company_id))).scalar_one_or_none()
    return role == "admin"


def _can_write(room: ChatRoom, user: User, room_role: str | None = None,
               company_admin: bool = False) -> bool:
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
    # «Объявления» — канал самой компании: её администратор говорит в нём по
    # должности В ЭТОМ пространстве (членство), назначенный владелец — по роли в
    # комнате. Раньше здесь стояло `user.role == "admin"` — глобальное поле,
    # унаследованное от прежней модели: на пилоте оно дало право публиковать
    # четверым рядовым и отняло у администратора компании.
    if room.kind == "news":
        return user.is_superadmin or company_admin or room_role in ("owner", "admin")
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
    # Чат закреплён вверху МОЕГО списка (личная настройка участия).
    isPinned: bool = False
    # Могу ли я здесь писать. Считает СЕРВЕР: фронт раньше выводил это сам из
    # глобальной роли пользователя и расходился с сервером — человек видел поле
    # ввода, а отправка возвращала 403.
    canWrite: bool = True
    # Моя роль В ЭТОЙ комнате (owner | admin | member) — по ней панель решает, показывать
    # ли поле ввода: в канале пишут владелец и его админы. Без этого поля фронт судил по
    # виду комнаты, и в канале, открытом администратором, поле ввода было у всех — а
    # отправка возвращала отказ.
    myRole: str | None = None
    # Приложение, к которому привязан чат: панель свойств объясняет, ПОЧЕМУ этот чат
    # здесь виден — «группа приложения Топливо», а не просто «группа».
    scopeProduct: str | None = None
    # Аватар чата (/api/files/<id>); NULL — иконка по типу комнаты.
    avatarUrl: str | None = None
    # «Без звука» до этого момента: чат не шлёт push и не красит общий счётчик.
    mutedUntil: str | None = None
    # Объект пространства, при котором живёт чат («группа по станции»).
    scopeObjectId: str | None = None
    scopeObjectName: str | None = None
    # Чат заявки: скрыт из общего списка, открывается из её карточки.
    scopeTicketId: str | None = None


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
    # Участник живёт в своей почте: сообщения уходят ему письмом. Автору важно
    # видеть это ДО отправки — разговор при таком участнике идёт иначе.
    mailOnly: bool = False
    email: str | None = None
    # Фото человека (/api/files/<id>). Пусто — рисуется генеративный кружок.
    avatarUrl: str | None = None


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
    # Опрос, если сообщение — опрос: вопрос, варианты, голоса и мой выбор.
    poll: dict | None = None
    # Сообщение пришло письмом, а не из интерфейса: собеседник живёт в почте, и
    # это видно в ленте — иначе непонятно, почему он «не читает» и отвечает не сразу.
    externalSource: str | None = None
    # Пересланное: имя автора оригинала («Переслано от …»).
    forwardedFrom: str | None = None
    # Кто написал: vendor | internal | partner. Признак стоит у КАЖДОГО сообщения, а не
    # только в списке участников: читая переписку, важно видеть, кто говорит, не сверяясь
    # со составом комнаты.
    authorParty: str | None = None


class CreateRoomBody(BaseModel):
    type: str = "group"                    # direct | group | channel
    name: str | None = None
    participantIds: list[str] = Field(default_factory=list)
    # Объект пространства, при котором живёт чат («группа по станции»).
    scopeObjectId: str | None = None
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
    # Видит ли новичок прошлое группы. По умолчанию да — в рабочую группу зовут
    # ради общего контекста, и чаще всего он нужен целиком. Снимают галочку там,
    # где до прихода человека обсуждали не его дело.
    seeHistory: bool = True


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
    object_id: str | None = Query(
        None, description="Только чаты этого объекта — для карточки объекта"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company_of(current_user, db)
    await ensure_company_rooms(current_user, cid, db)

    # Только комнаты ВЫБРАННОЙ организации — иначе мультикомпанийный юзер увидел
    # бы чаты двух орг вперемешку. Строгая изоляция пространств.
    rows = (await db.execute(
        select(ChatRoom, ChatParticipant.last_read_at, ChatParticipant.role,
               ChatParticipant.muted_until, ChatParticipant.pinned_at,
               ChatParticipant.joined_at, ChatParticipant.history_from)
        .join(ChatParticipant, and_(ChatParticipant.room_id == ChatRoom.id,
                                    ChatParticipant.user_id == current_user.id))
        .where(ChatRoom.is_active.is_(True), ChatRoom.is_archived.is_(archived),
               ChatRoom.company_id == cid,
               # Контекст приложения: правая рельса просит чаты своего приложения, и к
               # ним всегда добавляются чаты без привязки — общие для пространства
               # (личные, «Общий чат», «Объявления»). Верхняя кнопка параметр не
               # передаёт и получает всё: один чат, разные предустановки.
               or_(ChatRoom.scope_product.is_(None), ChatRoom.scope_product == product)
               if product else text("true"),
               ChatRoom.scope_object_id == object_id if object_id else text("true"),
               # Чаты заявок и задач скрыты из общего пространства: их видно только
               # из карточки заявки/задачи (решение МАГа) — сюда попадают лишь
               # обычные комнаты. Про задачу это было записано в `ensure_task_room`
               # и в `TaskChat`, но не сделано: «Задача №25» висела в общем списке
               # у всех, кто открыл вкладку «Обсуждение».
               ChatRoom.scope_ticket_id.is_(None), ChatRoom.scope_task_id.is_(None))
    )).all()

    # Имена привязанных объектов — одним запросом, а не по комнате.
    obj_ids = {room.scope_object_id for room, *_ in rows if room.scope_object_id}
    obj_names: dict[str, str] = dict((await db.execute(
        select(ServiceLocation.id, ServiceLocation.name)
        .where(ServiceLocation.id.in_(obj_ids)))).all()) if obj_ids else {}

    company_admin = await _is_company_admin(db, cid, current_user)

    # Всё, что нужно строкам списка, — пакетными запросами, а не по комнате. Было пять
    # запросов на каждую (состав, непрочитанные, последнее сообщение, собеседник,
    # закреплённое), а список перечитывается на каждое событие чата: двадцать комнат
    # превращались в сотню запросов на один показ.
    rids = [room.id for room, *_ in rows]
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    counts: dict[uuid.UUID, int] = {}
    unread_map: dict[uuid.UUID, int] = {}
    last_map: dict[uuid.UUID, ChatMessage] = {}
    peer_map: dict[uuid.UUID, tuple[str, str | None, str | None]] = {}
    pin_map: dict[uuid.UUID, ChatMessage] = {}
    if rids:
        counts = dict((await db.execute(
            select(ChatParticipant.room_id, func.count())
            .where(ChatParticipant.room_id.in_(rids))
            .group_by(ChatParticipant.room_id))).all())
        # Порог непрочитанного — момент ВСТУПЛЕНИЯ, а не начало времён: человека,
        # которого только что вписали в «Общий чат», иначе встречает вся его история
        # как непрочитанная, и счётчик показывает сотни. Порог у каждой комнаты свой,
        # поэтому условие собирается по комнатам — но запрос остаётся один.
        # Позванному «с чистого листа» прошлое комнаты закрыто и здесь: иначе он
        # прочёл бы его в превью списка и получил бы всю историю в счётчике.
        hidden = {room.id: hist for room, *_rest, hist in rows if hist is not None}
        thresholds = [(room.id, max(filter(None, (last_read or joined_at or epoch,
                                                  hidden.get(room.id)))))
                      for room, last_read, _role, _mute, _pin, joined_at, _hist in rows]
        unread_map = dict((await db.execute(
            select(ChatMessage.room_id, func.count()).where(
                ChatMessage.deleted_at.is_(None),
                ChatMessage.user_id != current_user.id,
                or_(*[and_(ChatMessage.room_id == r, ChatMessage.created_at > t)
                      for r, t in thresholds]),
            ).group_by(ChatMessage.room_id))).all())
        # DISTINCT ON — последнее живое сообщение каждой комнаты одним проходом.
        видимые = or_(*[and_(ChatMessage.room_id == r,
                             ChatMessage.created_at >= hidden[r]) if r in hidden
                        else ChatMessage.room_id == r for r in rids])
        last_map = {m.room_id: m for m in (await db.execute(
            select(ChatMessage).distinct(ChatMessage.room_id)
            .where(видимые, ChatMessage.deleted_at.is_(None))
            .order_by(ChatMessage.room_id, ChatMessage.created_at.desc()))).scalars().all()}
        # У личного чата лицо собеседника, а не иконка комнаты: список из десяти
        # одинаковых кружков не отличить, а человека узнают по фото.
        direct_ids = [room.id for room, *_ in rows if room.type == "direct"]
        if direct_ids:
            peer_map = {r: (str(uid), nm, av) for r, uid, nm, av in (await db.execute(
                select(ChatParticipant.room_id, ChatParticipant.user_id, User.name, User.avatar_url)
                .join(User, User.id == ChatParticipant.user_id)
                .where(ChatParticipant.room_id.in_(direct_ids),
                       ChatParticipant.user_id != current_user.id))).all()}
        pin_ids = [room.pinned_message_id for room, *_ in rows if room.pinned_message_id]
        if pin_ids:
            pin_map = {m.id: m for m in (await db.execute(
                select(ChatMessage).where(ChatMessage.id.in_(pin_ids),
                                          ChatMessage.deleted_at.is_(None)))).scalars().all()}

    out: list[RoomOut] = []
    for room, last_read, my_role, muted_until, pinned_at, joined_at, hist in rows:
        pcount = counts.get(room.id, 0)
        unread = unread_map.get(room.id, 0)
        last = last_map.get(room.id)
        name, peer_id, peer_avatar = room.name, None, None
        if room.type == "direct" and room.id in peer_map:
            peer_id, peer_name, peer_avatar = peer_map[room.id]
            name = name or peer_name
        pm = pin_map.get(room.pinned_message_id) if room.pinned_message_id else None
        if pm is not None and hist is not None and pm.created_at < hist:
            pm = None                      # закреплено до его прихода — не его история
        pinned = None if pm is None else PinnedOut(
            id=str(pm.id), userName=pm.user_name,
            content=((pm.content if pm.type == "text" else (pm.file_name or f"[{pm.type}]")) or "")[:200])
        out.append(RoomOut(
            id=str(room.id), type=room.type, kind=room.kind, name=name,
            isArchived=room.is_archived, participantCount=int(pcount), unreadCount=int(unread),
            directPeerId=peer_id, createdBy=str(room.created_by) if room.created_by else None,
            # Обрезаем: список чатов грузится у всех и постоянно, а одно длинное
            # сообщение утяжеляло бы ответ каждому участнику навсегда.
            # У вложения текст пуст, и список показывал «Нет сообщений» там, где файл
            # уже отправлен. Правило то же, что у закреплённого сообщения выше.
            lastMessage=(None if last is None else
                         ((last.content if last.type == "text"
                           else (last.file_name or f"[{last.type}]")) or "")[:200]),
            lastMessageAt=(last.created_at.isoformat() if last else None),
            pinnedMessage=pinned,
            myRole=my_role,
            scopeProduct=room.scope_product,
            avatarUrl=room.avatar_url or peer_avatar,
            mutedUntil=muted_until.isoformat() if muted_until else None,
            isPinned=pinned_at is not None,
            canWrite=_can_write(room, current_user, my_role, company_admin),
            scopeObjectId=room.scope_object_id,
            scopeObjectName=obj_names.get(room.scope_object_id or ""),
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


async def _pinned_out(room: ChatRoom, db: AsyncSession,
                      since: datetime | None = None) -> PinnedOut | None:
    if not room.pinned_message_id:
        return None
    m = await db.get(ChatMessage, room.pinned_message_id)
    if m is None or m.deleted_at is not None:
        return None
    if since is not None and m.created_at < since:
        return None                        # закреплено до его прихода в группу
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

    scope_object = None
    if body.type != "direct" and body.scopeObjectId:
        await _assert_company_object(body.scopeObjectId, cid, db)
        scope_object = body.scopeObjectId

    room = ChatRoom(type=body.type, kind=None, name=body.name, company_id=cid,
                    created_by=current_user.id,
                    # Личный чат контекста не имеет: он про людей, а не про экран.
                    scope_product=(body.scopeProduct or None) if body.type != "direct" else None,
                    scope_object_id=scope_object)
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
        select(ChatParticipant.user_id, ChatParticipant.role, User.name, User.company_id,
               User.mail_only, User.email, User.avatar_url)
        .join(User, User.id == ChatParticipant.user_id)
        .where(ChatParticipant.room_id == rid))).all()
    online = await manager.online_user_ids()
    # Кто в разговоре: свой сотрудник или человек компании-партнёра — и какой именно.
    # В смешанной группе (наши плюс партнёры) без этого не понять, при ком говорим,
    # а это первое, что нужно знать перед тем, как написать.
    ext_cids = {r[3] for r in parts if r[3] is not None and r[3] != room.company_id}
    titles = await _company_titles(db, ext_cids)
    parties = await _party_types(db, room.company_id, {r[0] for r in parts})
    plist = [ParticipantOut(userId=str(uid), name=nm, role=rl, online=str(uid) in online,
                            isExternal=(ucid is not None and ucid != room.company_id),
                            companyName=titles.get(ucid) if ucid != room.company_id else None,
                            partyType=parties.get(uid, "internal"),
                            mailOnly=bool(mail_only), email=mail if mail_only else None,
                            avatarUrl=avatar)
                        for uid, rl, nm, ucid, mail_only, mail, avatar in parts]
    name, peer_id = room.name, None
    if room.type == "direct":
        for p in plist:
            if p.userId != str(current_user.id):
                peer_id = p.userId
                name = name or p.name
    obj_name = None
    if room.scope_object_id:
        obj_name = (await db.execute(select(ServiceLocation.name).where(
            ServiceLocation.id == room.scope_object_id))).scalar_one_or_none()
    # Скрытые комнаты (чат заявки) не попадают в общий список — фронт строит их
    # шапку из детали, поэтому роль зрителя нужна прямо здесь.
    my_role = next((p.role for p in plist if p.userId == str(current_user.id)), None)
    can_write = _can_write(room, current_user, my_role,
                           await _is_company_admin(db, room.company_id, current_user))
    return RoomDetailOut(
        id=str(room.id), type=room.type, kind=room.kind, name=name,
        isArchived=room.is_archived, participantCount=len(plist), directPeerId=peer_id,
        createdBy=str(room.created_by) if room.created_by else None, participants=plist,
        pinnedMessage=await _pinned_out(room, db, await _history_from(rid, current_user, db)),
        canWrite=can_write,
        avatarUrl=room.avatar_url,
        scopeProduct=room.scope_product,
        scopeObjectId=room.scope_object_id, scopeObjectName=obj_name,
        scopeTicketId=str(room.scope_ticket_id) if room.scope_ticket_id else None,
        myRole=my_role,
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
        externalSource=m.external_source,
        forwardedFrom=None if deleted else m.forwarded_from,
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
    room = await _assert_participant(rid, current_user, db)
    stmt = select(ChatMessage).where(ChatMessage.room_id == rid)
    граница = await _history_from(rid, current_user, db)
    if граница is not None:
        stmt = stmt.where(ChatMessage.created_at >= граница)
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
    # Опросы страницы — одним запросом: результат нужен сразу, иначе карточка
    # опроса в ленте появлялась бы пустой и дозагружалась по одному.
    poll_ids = [m.id for m in msgs if m.type == "poll"]
    polls: dict[uuid.UUID, dict] = {}
    if poll_ids:
        for poll in (await db.execute(select(ChatPoll).where(
                ChatPoll.message_id.in_(poll_ids)))).scalars():
            polls[poll.message_id] = await _poll_out(poll, current_user.id, db)

    # «Кто прочитал» считается по отметкам участников — их берём один раз на комнату,
    # а не запросом на каждое сообщение: страница ленты — сто сообщений, и столько же
    # было запросов COUNT. Участников в комнате десятки, сравнение идёт в памяти.
    reads = [(uid, ts) for uid, ts in (await db.execute(
        select(ChatParticipant.user_id, ChatParticipant.last_read_at)
        .where(ChatParticipant.room_id == rid,
               ChatParticipant.last_read_at.is_not(None)))).all()]

    out = []
    for m in msgs:
        rc = sum(1 for uid, ts in reads if uid != m.user_id and ts >= m.created_at)
        item = _msg_out(m, int(rc), replies.get(m.reply_to), reactions.get(m.id),
                        parties.get(m.user_id) if m.user_id else None)
        item.poll = polls.get(m.id)
        out.append(item)
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
    if not _can_write(room, current_user, room_role,
                      await _is_company_admin(db, room.company_id, current_user)):
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
        # Отвечать можно только на сообщение ЭТОЙ комнаты. Лента подставляет в ответ
        # первые 120 символов оригинала и имя автора — без проверки достаточно было
        # подставить id сообщения из чужого чата, чтобы его текст увидели все здесь.
        if reply_to is not None:
            src_room = (await db.execute(select(ChatMessage.room_id).where(
                ChatMessage.id == reply_to))).scalar_one_or_none()
            if src_room != rid:
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
    await manager.broadcast(f"chat:{rid}", _событие("chat:message", payload.model_dump()))
    # Web Push тем, кого нет в системе: вкладка закрыта — сообщение всё равно догонит.
    web_push.push_room_async(
        rid, room.name or current_user.name,
        f"{current_user.name}: {(content or msg.file_name or 'вложение')[:140]}",
        current_user.id)
    # Участникам, живущим в своей почте, сообщение уходит письмом: для них это
    # единственный способ увидеть разговор, вкладки у них нет вовсе.
    chat_mail.push_room_mail_async(
        rid, room.name, current_user.name,
        content or msg.file_name or "(вложение)", current_user.id)
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
    # Закреп — заявление на всю комнату, поэтому право то же, что и на публикацию:
    # иначе в «Объявлениях» любой читатель перевешивает шапку канала.
    my_role = (await db.execute(select(ChatParticipant.role).where(
        ChatParticipant.room_id == rid,
        ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
    if not _can_write(room, current_user, my_role,
                      await _is_company_admin(db, room.company_id, current_user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Закреплять может ведущий канала")
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
    await manager.broadcast(f"chat:{rid}", _событие("message:edited", payload.model_dump()))
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
           or room.created_by == current_user.id or my in ("owner", "admin"))
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
    if not (current_user.is_superadmin or room.created_by == current_user.id or my in ("owner", "admin")):
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
    if not (current_user.is_superadmin or room.created_by == current_user.id or my in ("owner", "admin")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет прав добавлять участников")
    if room.company_id not in await _member_ids(target, db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Пользователь не из компании чата")
    exists = (await db.execute(select(ChatParticipant.id).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == target))).scalar_one_or_none()
    if exists is not None:
        return {"ok": True}
    сейчас = _now()
    db.add(ChatParticipant(room_id=rid, user_id=target, role="member",
                           history_from=None if body.seeHistory else сейчас))
    # Появление человека в группе — событие разговора, а не тихая правка состава:
    # остальные должны видеть, кто пришёл и чьими стараниями. Заодно это событие
    # обновляет у всех состав комнаты — оно приезжает тем же сокетом, что и текст.
    имя = (await db.execute(select(User.name).where(User.id == target))).scalar_one_or_none()
    msg = ChatMessage(room_id=rid, user_id=current_user.id, user_name=current_user.name,
                      type="system", content=f"Добавлен участник: {имя or 'без имени'}")
    db.add(msg)
    room.updated_at = сейчас
    await db.flush()
    payload = _msg_out(msg, 0, None, None, None)
    await db.commit()
    await manager.broadcast(f"chat:{rid}", _событие("chat:message", payload.model_dump()))
    return {"ok": True}


class AddMailParticipantBody(BaseModel):
    email: str
    name: str | None = None
    # Организация внешнего участника — карточка юрлица пространства (`counterparties`).
    # Не обязательна: без неё человек просто «внешний», принадлежность проставят позже
    # в Центре управления, как и любому партнёру.
    organizationId: str | None = None


@router.post("/rooms/{room_id}/participants/mail", status_code=status.HTTP_201_CREATED)
async def add_mail_participant(
    room_id: str,
    body: AddMailParticipantBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Позвать в чат человека, который живёт в своей почте.

    Он не заходит в пространство и не заводит пароль: сообщения комнаты уходят
    ему письмом, ответ возвращается в ленту. Учётка нужна лишь для того, чтобы у
    его сообщений был автор, а у комнаты — состав; войти ею нельзя.
    """
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    email = (body.email or "").strip().lower()
    if "@" not in email or " " in email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен адрес электронной почты")
    if not get_settings().chat_mail_inbox:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "В пространстве не настроен ящик приёма — писать по почте некуда")

    room = await _assert_participant(rid, current_user, db)
    my = await _my_room_role(rid, current_user, db)
    if not (current_user.is_superadmin or room.created_by == current_user.id or my in ("owner", "admin")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет прав добавлять участников")
    # Личный чат — разговор двоих; третьего, пусть и почтового, туда не вводят.
    if room.type == "direct":
        raise HTTPException(status.HTTP_409_CONFLICT, "В личный чат участников не добавляют")

    user = (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none()
    if user is None:
        user = User(
            email=email, name=(body.name or "").strip() or email.split("@")[0],
            # Пароля у почтового участника нет: строка-заглушка не является
            # валидным bcrypt-хешем, поэтому проверка пароля всегда отвергнет вход.
            password_hash="!", role="user", company_id=room.company_id, mail_only=True,
        )
        db.add(user)
        await db.flush()
        org_id = None
        if body.organizationId:
            try:
                org_id = uuid.UUID(body.organizationId)
            except (ValueError, TypeError):
                org_id = None
        db.add(UserCompany(user_id=user.id, company_id=room.company_id,
                           role="user", party_type="partner", organization_id=org_id))
    elif not user.mail_only and room.company_id not in await _member_ids(user.id, db):
        # Условие было вывернуто: отказ срабатывал, когда у найденной учётки НЕТ
        # членств вообще, а человек из ЧУЖОЙ компании молча добавлялся в комнату
        # обычным участником. Сверяем именно с компанией этой комнаты.
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Такой адрес уже занят учётной записью другого пространства")

    exists = (await db.execute(select(ChatParticipant.id).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == user.id))).scalar_one_or_none()
    if exists is None:
        db.add(ChatParticipant(room_id=rid, user_id=user.id, role="member"))
    await db.commit()
    return {"ok": True, "userId": str(user.id), "email": email,
            "replyAddress": chat_mail.reply_address(rid)}


class InboundEmailBody(BaseModel):
    """Письмо, пришедшее в комнату (зовёт почтовый мост Поддержки)."""
    fromAddress: str
    fromName: str | None = None
    text: str
    # Message-ID письма: ключ идемпотентности, повторная доставка дубля не создаёт.
    messageId: str | None = None
    # Ссылка на письмо-первоисточник в архиве Поддержки — чтобы из ленты чата
    # можно было дойти до оригинала, а не только до вычищенного текста.
    emailMessageId: str | None = None


@router.post("/rooms/{room_id}/inbound-email", status_code=status.HTTP_201_CREATED)
async def inbound_email(
    room_id: str,
    body: InboundEmailBody,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Ответ почтового участника → сообщение в ленте комнаты.

    Пишет только тот, кто уже в комнате: адрес комнаты может утечь пересылкой
    письма, и по нему не должен получать слово посторонний. Незнакомый
    отправитель отклоняется — карантин ведёт почтовый мост, у него для этого
    есть и оригинал письма, и экран.
    """
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await db.get(ChatRoom, rid)
    if room is None or room.company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")

    email = (body.fromAddress or "").strip().lower()
    author = (await db.execute(
        select(User).join(ChatParticipant, ChatParticipant.user_id == User.id)
        .where(ChatParticipant.room_id == rid, func.lower(User.email) == email)
    )).scalar_one_or_none()
    if author is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Отправитель {email or '(без адреса)'} не участник этого чата")

    external_key = (body.messageId or "").strip() or None
    if external_key:
        dup = (await db.execute(select(ChatMessage.id).where(
            ChatMessage.room_id == rid, ChatMessage.external_id == external_key))).scalar_one_or_none()
        if dup is not None:
            return {"ok": True, "messageId": str(dup), "duplicate": True}

    text_body = (body.text or "").strip() or "(письмо без текста)"
    msg = ChatMessage(
        room_id=rid, user_id=author.id, user_name=author.name, type="text",
        content=text_body, external_id=external_key,
        external_source="email", external_ref=(body.emailMessageId or None),
    )
    db.add(msg)
    room.updated_at = _now()
    await db.flush()
    parties = await _party_types(db, room.company_id, {author.id})
    payload = _msg_out(msg, 0, None, None, parties.get(author.id))
    await db.commit()

    await manager.broadcast(f"chat:{rid}", _событие("chat:message", payload.model_dump()))
    web_push.push_room_async(rid, room.name or author.name,
                             f"{author.name}: {text_body[:140]}", author.id)
    # Письмо ушло одному участнику, но разговор общий: остальные почтовые
    # участники комнаты должны увидеть ответ так же, как видят его в ленте.
    chat_mail.push_room_mail_async(rid, room.name, author.name, text_body, author.id)
    return {"ok": True, "messageId": str(msg.id)}


# ── самоуправление чата: владелец и админы ведут его без админа пространства ─
# Роли комнаты (owner/admin/member) существовали, но распоряжаться ими мог только
# админ пространства из «Управления → Чаты». Создатель группы не мог ни переименовать
# её, ни убрать человека — хотя группу завёл он и вести её должен он.

class RoomRenameBody(BaseModel):
    name: str | None = None
    # Аватар: путь файла пространства (/api/files/<id>); "" — убрать аватар.
    # camelCase — как во всех Body этого роутера (userId, scopeProduct): конвертации нет.
    avatarUrl: str | None = None
    # Привязка к приложению («специализированная группа»): "" — отвязать.
    scopeProduct: str | None = None
    # Привязка к объекту пространства: "" — отвязать.
    scopeObjectId: str | None = None


class ParticipantRoleBody(BaseModel):
    role: str   # admin | member


async def _my_room_role(rid: uuid.UUID, user: User, db: AsyncSession) -> str | None:
    return (await db.execute(select(ChatParticipant.role).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == user.id))).scalar_one_or_none()


@router.patch("/rooms/{room_id}")
async def rename_room(
    room_id: str, body: RoomRenameBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Переименовать чат или сменить аватар — владелец или админ чата.
    Имя системного чата закрыто, аватар — можно (его меняет владелец комнаты)."""
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    my = await _my_room_role(rid, current_user, db)
    if not (current_user.is_superadmin or room.created_by == current_user.id
            or my in ("owner", "admin")):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Менять чат может его владелец или админ")
    if room.type == "direct":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Личную переписку не настраивают")
    if body.name is not None:
        if room.kind is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Имя системного чата — часть устройства пространства")
        name = body.name.strip()
        if not name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Имя не может быть пустым")
        room.name = name
    if body.avatarUrl is not None:
        url = body.avatarUrl.strip()
        # Только файлы пространства: внешний адрес в src — чужой контент и утечка.
        if url and not url.startswith("/api/files/"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Аватар — файл пространства (/api/files/…)")
        room.avatar_url = url or None
    if body.scopeProduct is not None:
        # Привязка группы к приложению: системным не meняем — они общие по устройству.
        if room.kind is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Системный чат — общий для пространства, привязки у него нет")
        room.scope_product = body.scopeProduct.strip() or None
    if body.scopeObjectId is not None:
        if room.kind is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Системный чат — общий для пространства, привязки у него нет")
        oid = body.scopeObjectId.strip()
        if oid:
            await _assert_company_object(oid, room.company_id, db)
        room.scope_object_id = oid or None
    await db.commit()
    return {"ok": True, "name": room.name, "avatarUrl": room.avatar_url,
            "scopeProduct": room.scope_product, "scopeObjectId": room.scope_object_id}


@router.delete("/rooms/{room_id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_participant(
    room_id: str, user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Убрать участника: владелец — любого, админ чата — обычных участников."""
    try:
        rid, uid = uuid.UUID(room_id), uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    my = await _my_room_role(rid, current_user, db)
    is_owner = (current_user.is_superadmin or room.created_by == current_user.id
                or my == "owner")
    if not (is_owner or my == "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Убирать участников может владелец или админ чата")
    if room.kind is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Состав системного чата ведёт пространство")
    if room.type == "direct":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Личную переписку не редактируют")
    p = (await db.execute(select(ChatParticipant).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == uid))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Участник не найден")
    if p.user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Себя убрать нельзя")
    if p.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Владельца чата убрать нельзя")
    if not is_owner and p.role == "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Админа чата убирает только владелец")
    await db.delete(p)
    await db.commit()


@router.post("/rooms/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Выйти из группы самому. Системные чаты пространства и каналы — без выхода:
    «Общий чат», «Объявления» и «Обновления платформы» обязательны для всех, от
    канала не отписываются — его состав ведёт владелец."""
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    if room.kind is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Из чатов пространства не выходят — они обязательны для всех")
    if room.type != "group":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Выйти можно из группы; канал и личную переписку можно архивировать")
    p = (await db.execute(select(ChatParticipant).where(
        ChatParticipant.room_id == rid,
        ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вы не участник этого чата")
    if p.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Владелец не выходит из своей группы — сначала передайте её в «Управлении»")
    await db.delete(p)
    await db.commit()


class MuteBody(BaseModel):
    # 'forever' — навсегда, ISO-время — до момента, null — включить уведомления.
    until: str | None = None


class PollCreateBody(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    options: list[str] = Field(min_length=2, max_length=10)
    multiple: bool = False
    anonymous: bool = False
    # Участник может дописать свой вариант — опрос со свободным ответом.
    allowCustom: bool = False


class PollVoteBody(BaseModel):
    # Пустой список = снять свой голос: передумать — нормально, пока опрос открыт.
    options: list[int] = Field(default_factory=list)


async def _poll_out(poll: ChatPoll, me: uuid.UUID, db: AsyncSession) -> dict:
    """Опрос с результатами. Имена голосовавших — только у неанонимного:
    в рабочем чате важно знать, кто едет на объект, но решает это автор."""
    rows = (await db.execute(
        select(ChatPollVote.option_index, ChatPollVote.user_id, User.name)
        .join(User, User.id == ChatPollVote.user_id)
        .where(ChatPollVote.poll_id == poll.id))).all()
    counts = [0] * len(poll.options)
    voters: list[list[str]] = [[] for _ in poll.options]
    mine: list[int] = []
    people: set[uuid.UUID] = set()
    for idx, uid, name in rows:
        if 0 <= idx < len(counts):
            counts[idx] += 1
            people.add(uid)
            if uid == me:
                mine.append(idx)
            elif not poll.anonymous:
                voters[idx].append(name or "—")
    if not poll.anonymous:
        for idx in mine:
            voters[idx].insert(0, "Вы")
    return {
        "id": str(poll.id),
        "question": poll.question,
        "options": list(poll.options),
        "counts": counts,
        "voters": None if poll.anonymous else voters,
        "multiple": poll.multiple,
        "anonymous": poll.anonymous,
        "allowCustom": poll.allow_custom,
        "myVotes": sorted(mine),
        "totalVoters": len(people),
        "isClosed": poll.closed_at is not None,
        "createdBy": str(poll.created_by) if poll.created_by else None,
    }


@router.post("/rooms/{room_id}/polls", status_code=status.HTTP_201_CREATED)
async def create_poll(
    room_id: str, body: PollCreateBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Спросить мнение участников чата.

    Опрос идёт сообщением в ленту: его видно в переписке наравне со всем
    остальным, а не в отдельном разделе, куда надо ещё зайти. Право создавать —
    то же, что право писать: в канале это владелец и его админы.
    """
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    room_role = (await db.execute(select(ChatParticipant.role).where(
        ChatParticipant.room_id == room.id,
        ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
    if not _can_write(room, current_user, room_role,
                      await _is_company_admin(db, room.company_id, current_user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "В этом чате писать может не каждый")

    options = [o.strip()[:150] for o in body.options if o and o.strip()]
    if len(options) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужно минимум два варианта")
    if len(set(options)) != len(options):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Варианты повторяются")

    question = body.question.strip()
    msg = ChatMessage(room_id=rid, user_id=current_user.id, user_name=current_user.name,
                      type="poll", content=question)
    db.add(msg)
    await db.flush()
    poll = ChatPoll(room_id=rid, message_id=msg.id, question=question, options=options,
                    multiple=body.multiple, anonymous=body.anonymous,
                    allow_custom=body.allowCustom, created_by=current_user.id)
    db.add(poll)
    room.updated_at = _now()
    await db.flush()

    parties = await _party_types(db, room.company_id, {current_user.id})
    payload = _msg_out(msg, 0, None, None, parties.get(current_user.id))
    poll_data = await _poll_out(poll, current_user.id, db)
    await db.commit()

    body_out = {**payload.model_dump(), "poll": poll_data}
    await manager.broadcast(f"chat:{rid}", _событие("chat:message", body_out))
    web_push.push_room_async(rid, room.name or current_user.name,
                             f"{current_user.name}: опрос «{question[:100]}»", current_user.id)
    chat_mail.push_room_mail_async(rid, room.name, current_user.name,
                                   f"Опрос: {question}\n\n" + "\n".join(f"— {o}" for o in options),
                                   current_user.id)
    return body_out


@router.post("/polls/{poll_id}/vote")
async def vote_poll(
    poll_id: str, body: PollVoteBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отдать голос (или снять его, прислав пустой список).

    Переголосование заменяет прежний выбор целиком: опрос отвечает на вопрос
    «что думают сейчас», а не «кто когда передумал».
    """
    try:
        pid = uuid.UUID(poll_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    poll = await db.get(ChatPoll, pid)
    if poll is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Опрос не найден")
    await _assert_participant(poll.room_id, current_user, db)
    if poll.closed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Опрос завершён")

    picks = sorted({i for i in body.options if 0 <= i < len(poll.options)})
    if not poll.multiple and len(picks) > 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "В этом опросе выбирают один вариант")

    await db.execute(sa_delete(ChatPollVote).where(
        ChatPollVote.poll_id == pid, ChatPollVote.user_id == current_user.id))
    for i in picks:
        db.add(ChatPollVote(poll_id=pid, user_id=current_user.id, option_index=i))
    await db.flush()
    data = await _poll_out(poll, current_user.id, db)
    await db.commit()
    # Результат меняется у всех, кто смотрит на опрос, — рассылаем как реакцию.
    await manager.broadcast(f"chat:{poll.room_id}",
                            {"type": "chat:poll", "roomId": str(poll.room_id),
                             "messageId": str(poll.message_id)})
    return data


class PollOptionBody(BaseModel):
    text: str = Field(min_length=1, max_length=150)


@router.post("/polls/{poll_id}/options")
async def add_poll_option(
    poll_id: str, body: PollOptionBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Дописать свой вариант и сразу отдать за него голос.

    Спрашивающий редко знает все ответы заранее, поэтому опрос может быть
    открытым. Вариант дописывается в список АТОМАРНО, прямо в базе
    (`options || to_jsonb(...)`): двое, ответивших одновременно, иначе затёрли бы
    ответ друг друга — прочитали бы один и тот же список и записали каждый свой.

    Совпадение с существующим вариантом (без учёта регистра и пробелов) не
    плодит дубль: голос уходит за то, что уже есть.
    """
    try:
        pid = uuid.UUID(poll_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    poll = await db.get(ChatPoll, pid)
    if poll is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Опрос не найден")
    await _assert_participant(poll.room_id, current_user, db)
    if poll.closed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Опрос завершён")
    if not poll.allow_custom:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "В этом опросе свои варианты не принимаются")

    text_value = " ".join(body.text.split())[:150]
    if not text_value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой вариант")

    existing = [str(o).strip().lower() for o in poll.options]
    if text_value.lower() in existing:
        index = existing.index(text_value.lower())
    else:
        if len(poll.options) >= 20:
            raise HTTPException(status.HTTP_409_CONFLICT, "Слишком много вариантов")
        row = (await db.execute(text(
            "UPDATE chat_polls SET options = options || to_jsonb(CAST(:t AS text)) "
            "WHERE id = :id RETURNING jsonb_array_length(options) - 1 AS idx"
        ), {"t": text_value, "id": str(pid)})).first()
        index = int(row[0])
        await db.refresh(poll)

    if not poll.multiple:
        await db.execute(sa_delete(ChatPollVote).where(
            ChatPollVote.poll_id == pid, ChatPollVote.user_id == current_user.id))
    already = (await db.execute(select(ChatPollVote.id).where(
        ChatPollVote.poll_id == pid, ChatPollVote.user_id == current_user.id,
        ChatPollVote.option_index == index))).scalar_one_or_none()
    if already is None:
        db.add(ChatPollVote(poll_id=pid, user_id=current_user.id, option_index=index))
    await db.flush()
    data = await _poll_out(poll, current_user.id, db)
    await db.commit()
    await manager.broadcast(f"chat:{poll.room_id}",
                            {"type": "chat:poll", "roomId": str(poll.room_id),
                             "messageId": str(poll.message_id)})
    return data


@router.post("/polls/{poll_id}/close")
async def close_poll(
    poll_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Завершить опрос: голоса больше не принимаются, итог виден всем.

    Закрывает автор, владелец чата или админ пространства — тот же круг, что
    отвечает за порядок в переписке.
    """
    try:
        pid = uuid.UUID(poll_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    poll = await db.get(ChatPoll, pid)
    if poll is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Опрос не найден")
    room = await _assert_participant(poll.room_id, current_user, db)
    my_role = await _my_room_role(poll.room_id, current_user, db)
    if not (poll.created_by == current_user.id or current_user.is_superadmin
            or room.created_by == current_user.id or my_role in ("owner", "admin")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Завершить опрос может тот, кто его создал")
    if poll.closed_at is None:
        poll.closed_at = _now()
    data = await _poll_out(poll, current_user.id, db)
    await db.commit()
    await manager.broadcast(f"chat:{poll.room_id}",
                            {"type": "chat:poll", "roomId": str(poll.room_id),
                             "messageId": str(poll.message_id)})
    return data


@router.get("/link-preview")
async def link_preview(
    url: str = Query(..., max_length=2000),
    current_user: User = Depends(get_current_user),
):
    """Заголовок и описание страницы по ссылке из переписки.

    Ходит только по публичным адресам и не следует за редиректами — иначе
    ручка превращается в сканер внутренней сети чужими руками (см.
    services/link_preview.py). Молчание страницы — не ошибка: фронт просто
    оставит обычную ссылку.
    """
    data = await link_preview_service.fetch_preview(url)
    return data or {}


@router.get("/rooms/{room_id}/media")
async def room_media(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Всё, что присылали в чат: фотографии и файлы одним списком.

    Искать вложение прокруткой ленты — работа на минуту; здесь оно находится
    сразу. Отдаём последние 200 — на практике этого хватает, а полная выгрузка
    переписки за годы в панель всё равно не помещается.
    """
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    await _assert_participant(rid, current_user, db)
    rows = (await db.execute(
        select(ChatMessage.id, ChatMessage.file_url, ChatMessage.file_name,
               ChatMessage.file_size, ChatMessage.type, ChatMessage.user_name,
               ChatMessage.created_at)
        .where(ChatMessage.room_id == rid, ChatMessage.deleted_at.is_(None),
               ChatMessage.file_url.is_not(None))
        .order_by(ChatMessage.created_at.desc()).limit(200)
    )).all()
    return [{
        "messageId": str(mid), "fileUrl": url, "fileName": name, "fileSize": size,
        "type": mtype, "userName": author, "createdAt": created.isoformat(),
    } for mid, url, name, size, mtype, author, created in rows]


@router.post("/rooms/{room_id}/pin-room")
async def pin_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Закрепить чат вверху своего списка (повторный вызов — открепить).

    Настройка личная: важные разговоры у каждого свои, и закреплять их за всех
    участников было бы вмешательством в чужой список.
    """
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    await _assert_participant(rid, current_user, db)
    p = (await db.execute(select(ChatParticipant).where(
        ChatParticipant.room_id == rid,
        ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вы не участник этого чата")
    p.pinned_at = None if p.pinned_at else _now()
    await db.commit()
    return {"ok": True, "isPinned": p.pinned_at is not None}


@router.post("/rooms/{room_id}/mute")
async def mute_room(
    room_id: str, body: MuteBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """«Без звука»: чат перестаёт слать push и красить общий счётчик."""
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    await _assert_participant(rid, current_user, db)
    p = (await db.execute(select(ChatParticipant).where(
        ChatParticipant.room_id == rid,
        ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вы не участник этого чата")
    if body.until is None:
        p.muted_until = None
    elif body.until == "forever":
        p.muted_until = datetime(9999, 1, 1, tzinfo=timezone.utc)
    else:
        try:
            p.muted_until = datetime.fromisoformat(body.until)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "until: 'forever', ISO-время или null")
    await db.commit()
    return {"mutedUntil": p.muted_until.isoformat() if p.muted_until else None}


class ForwardBody(BaseModel):
    toRoomIds: list[str]


@router.post("/messages/{message_id}/forward", response_model=list[MessageOut])
async def forward_message(
    message_id: str, body: ForwardBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Переслать сообщение в другие чаты. Копия несёт имя автора ОРИГИНАЛА:
    форвард форварда оригинал не теряет."""
    try:
        mid = uuid.UUID(message_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    src = await db.get(ChatMessage, mid)
    if src is None or src.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")
    await _assert_participant(src.room_id, current_user, db)
    origin = src.forwarded_from or src.user_name

    made: list[tuple[ChatMessage, ChatRoom]] = []
    for rid_s in body.toRoomIds[:20]:
        try:
            rid = uuid.UUID(rid_s)
        except (ValueError, TypeError):
            continue
        room = await _assert_participant(rid, current_user, db)
        room_role = (await db.execute(select(ChatParticipant.role).where(
            ChatParticipant.room_id == rid,
            ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
        if not _can_write(room, current_user, room_role,
                          await _is_company_admin(db, room.company_id, current_user)):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"В «{room.name or 'этот канал'}» вам писать нельзя")
        msg = ChatMessage(
            room_id=rid, user_id=current_user.id, user_name=current_user.name,
            type=src.type, content=src.content, forwarded_from=origin,
            file_url=src.file_url, file_name=src.file_name, file_size=src.file_size,
        )
        db.add(msg)
        room.updated_at = _now()
        made.append((msg, room))
    if not made:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не выбран ни один чат")
    await db.flush()
    parties = await _party_types(db, made[0][1].company_id, {current_user.id})
    outs = [_msg_out(m, 0, None, None, parties.get(current_user.id)) for m, _ in made]
    await db.commit()
    for out_msg, (m, room) in zip(outs, made):
        await manager.broadcast(f"chat:{m.room_id}", _событие("chat:message", out_msg.model_dump()))
        web_push.push_room_async(
            m.room_id, room.name or current_user.name,
            f"{current_user.name}: {(m.content or m.file_name or 'вложение')[:140]}",
            current_user.id)
    return outs


@router.get("/search")
async def search_all_messages(
    q: str = Query(..., min_length=2),
    limit: int = Query(30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Глобальный поиск по всем чатам, где человек участник (в пределах организации)."""
    cid = await _company_of(current_user, db)
    rows = (await db.execute(
        select(ChatMessage, ChatRoom)
        .join(ChatRoom, ChatRoom.id == ChatMessage.room_id)
        .join(ChatParticipant, and_(ChatParticipant.room_id == ChatRoom.id,
                                    ChatParticipant.user_id == current_user.id))
        .where(ChatRoom.company_id == cid, ChatRoom.is_active.is_(True),
               ChatMessage.deleted_at.is_(None),
               ChatMessage.content.ilike(f"%{q}%"))
        .order_by(ChatMessage.created_at.desc()).limit(limit)
    )).all()
    return [{
        "messageId": str(m.id), "roomId": str(r.id),
        "roomName": r.name or ("Личная переписка" if r.type == "direct" else "Чат"),
        "userName": m.user_name, "preview": m.content[:160],
        "createdAt": m.created_at.isoformat(),
    } for m, r in rows]


# ── сопряжение с заявками (docs/TICKETS.md, решение МАГа 31.07.2026) ─────────
class TicketFromMessageBody(BaseModel):
    # Не задан — объект чата; нет и его — «Офис» (type=office): бизнес-заявка без
    # станции всё равно чья-то (правило МАГа 31.07.2026).
    objectId: str | None = None
    title: str | None = None
    priority: str = "medium"


@router.post("/messages/{message_id}/ticket")
async def ticket_from_message(
    message_id: str, body: TicketFromMessageBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Заявка из сообщения: обсудили — отправили на выполнение.

    Создание идёт через эко-канал Поддержки (`create_object_ticket`) — там заявке
    начисляются стадия, SLA и аудит; напрямую в public.tickets не пишем. След
    остаётся с обеих сторон: связь в `chat_ticket_links` + системное сообщение."""
    try:
        mid = uuid.UUID(message_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    msg = await db.get(ChatMessage, mid)
    if msg is None or msg.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")
    room = await _assert_participant(msg.room_id, current_user, db)
    # Объект: явный выбор → привязка чата → «Офис» по умолчанию.
    object_id = (body.objectId or "").strip() or room.scope_object_id
    if not object_id:
        object_id = (await db.execute(select(ServiceLocation.id).where(
            ServiceLocation.company_id == room.company_id,
            ServiceLocation.type == "office").limit(1))).scalar_one_or_none()
    if not object_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Выберите объект: объекта «Офис» в реестре пространства нет")
    await _assert_company_object(object_id, room.company_id, db)

    src_text = (msg.content or msg.file_name or "").strip()
    description = (f"{msg.user_name or 'Участник'}: {src_text}\n\n"
                   f"(из обсуждения «{room.name or 'чат'}»)")
    try:
        res = await create_object_ticket(
            db, room.company_id, object_id,
            description=description, title=(body.title or None),
            priority=body.priority if body.priority in ("low", "medium", "high") else "medium",
            author_email=current_user.email)
    except ProjectionError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    ticket = res.get("ticket") if isinstance(res.get("ticket"), dict) else res
    t_id = ticket.get("id") or res.get("id")
    t_num = str(ticket.get("displayNumber") or ticket.get("display_number")
                or ticket.get("number") or "")
    try:
        t_uuid = uuid.UUID(str(t_id))
    except (ValueError, TypeError):
        t_uuid = None
    if t_uuid is not None:
        db.add(ChatTicketLink(room_id=room.id, message_id=mid, ticket_id=t_uuid,
                              ticket_number=t_num or None, created_by=current_user.id))

    note = ChatMessage(
        room_id=room.id, user_id=current_user.id, user_name=current_user.name,
        type="text",
        content=f"→ Создана заявка{f' №{t_num}' if t_num else ''}"
                f"{f': {body.title}' if body.title else ''} — открыть в «Заявках»",
        reply_to=mid,
    )
    db.add(note)
    room.updated_at = _now()
    await db.flush()
    parties = await _party_types(db, room.company_id, {current_user.id})
    payload = _msg_out(note, 0, msg, None, parties.get(current_user.id))
    await db.commit()
    await manager.broadcast(f"chat:{room.id}", _событие("chat:message", payload.model_dump()))
    return {"ok": True, "ticketId": str(t_id) if t_id else None, "ticketNumber": t_num or None}


class TaskFromMessageBody(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=300)
    assigneeId: str | None = None
    dueAt: datetime | None = None


@router.post("/messages/{message_id}/task", status_code=status.HTTP_201_CREATED)
async def task_from_message(
    message_id: str, body: TaskFromMessageBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Поставить поручение по сообщению.

    Процесс из сообщения уже был, но он требует шаблона — а половина работы
    рождается в разговоре без всякого шаблона: «сделай, пожалуйста». Раньше это
    значило переписать сообщение руками в форму постановки, и связь с
    обсуждением терялась вместе с причиной.

    Ссылка двусторонняя: в чат уходит сообщение с номером задачи, в задаче
    остаётся след с адресом обсуждения. Разговор, из которого выросла работа,
    спрашивают чаще, чем кажется — там причина.
    """
    from app.models import (
        SourceFile, Task, TaskAttachment, TaskEvent, TaskType,
    )
    from app.services import work_state

    try:
        mid = uuid.UUID(message_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")

    msg = await db.get(ChatMessage, mid)
    if msg is None or msg.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")
    room = await _assert_participant(msg.room_id, current_user, db)
    await assert_company_product(str(room.company_id), current_user, db, "docs")

    source_ref = f"chat:{mid}:task"
    duplicate = await db.scalar(select(TaskEvent.id).join(
        Task, Task.id == TaskEvent.task_id).where(
            Task.company_id == room.company_id,
            TaskEvent.kind == "created",
            TaskEvent.note == source_ref).limit(1))
    if duplicate is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Поручение по этому сообщению уже поставлено")

    src = (msg.content or msg.file_name or "").strip()
    title = (body.title or src)[:300].strip()
    if len(title) < 3:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "В сообщении нечего поручить: задайте заголовок")

    assignee_id = None
    if body.assigneeId:
        try:
            assignee_id = uuid.UUID(body.assigneeId)
        except (ValueError, TypeError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Неверный исполнитель") from None
        if await db.get(UserCompany, (assignee_id, room.company_id)) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Исполнитель не состоит в пространстве")

    # Тип не спрашиваем: у поручения из разговора его обычно нет, а маршрут по
    # умолчанию тот же, что у поставленного руками.
    route = [{"code": "new", "name": "Постановка"},
             {"code": "in_progress", "name": "В работе"},
             {"code": "review", "name": "Проверка"}]
    default_type = (await db.execute(select(TaskType).where(
        TaskType.company_id == room.company_id, TaskType.code == "errand",
        TaskType.is_active.is_(True)))).scalars().first()
    if default_type is not None and default_type.route:
        route = default_type.route

    task = Task(
        company_id=room.company_id,
        type_id=default_type.id if default_type is not None else None,
        title=title,
        description=(f"{msg.user_name or 'Участник'}: {src}\n\n"
                     f"Из обсуждения «{room.name or 'чат'}»."),
        priority=(default_type.default_priority if default_type is not None else "medium"),
        status="open", stage_code=route[0]["code"],
        stage_column=work_state.stage_column_of(route, route[0]["code"]),
        assignee_id=assignee_id, author_id=current_user.id,
        object_id=room.scope_object_id, due_at=body.dueAt)
    db.add(task)
    await db.flush()
    # Ключ источника хранится в следе создания: по нему ловится повтор, и по нему
    # же видно, откуда работа взялась.
    db.add(TaskEvent(task_id=task.id, kind="created", user_id=current_user.id,
                     to_value=route[0]["name"], note=source_ref))

    if msg.file_url:
        try:
            file_id = uuid.UUID(msg.file_url.rstrip("/").rsplit("/", 1)[-1])
        except (ValueError, TypeError):
            file_id = None
        source_file = await db.get(SourceFile, file_id) if file_id else None
        if source_file is not None and source_file.company_id == room.company_id:
            db.add(TaskAttachment(task_id=task.id, file_id=source_file.id,
                                  uploaded_by=current_user.id))

    target_url = (f"{get_settings().app_public_url.rstrip('/')}"
                  f"/docs/company?view=errands&task={task.id}")
    note = ChatMessage(
        room_id=room.id, user_id=current_user.id, user_name=current_user.name,
        type="text",
        content=f"→ Поставлено поручение №{task.number}: {title}\n{target_url}",
        reply_to=mid)
    db.add(note)
    room.updated_at = _now()
    await db.flush()
    parties = await _party_types(db, room.company_id, {current_user.id})
    payload = _msg_out(note, 0, msg, None, parties.get(current_user.id))
    await db.commit()
    await manager.broadcast(f"chat:{room.id}",
                            _событие("chat:message", payload.model_dump()))
    return {"taskId": str(task.id), "number": task.number, "title": task.title,
            "url": target_url, "message": payload}


class ProcessFromMessageBody(BaseModel):
    templateId: str
    responsibleId: str | None = None
    title: str | None = Field(None, min_length=3, max_length=300)


@router.post("/messages/{message_id}/process", status_code=status.HTTP_201_CREATED)
async def process_from_message(
    message_id: str, body: ProcessFromMessageBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Запустить из сообщения документный маршрут или внутреннюю задачу."""
    from app.models import (
        DocCard, SourceFile, Task, TaskAttachment, TaskEvent, TaskTemplate,
    )

    try:
        mid = uuid.UUID(message_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    msg = await db.get(ChatMessage, mid)
    if msg is None or msg.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")
    room = await _assert_participant(msg.room_id, current_user, db)
    await assert_company_product(str(room.company_id), current_user, db, "docs")

    try:
        template_id = uuid.UUID(body.templateId)
        responsible_id = uuid.UUID(body.responsibleId) if body.responsibleId else None
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    tpl = await db.get(TaskTemplate, template_id)
    if tpl is None or tpl.company_id != room.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шаблон процесса не найден")
    source_ref = f"chat:{mid}:template:{tpl.id}"
    if tpl.doc_kind_id:
        duplicate = await db.scalar(select(DocCard.id).where(
            DocCard.company_id == room.company_id,
            DocCard.source == "chat",
            DocCard.source_ref == source_ref,
        ).limit(1))
    else:
        duplicate = await db.scalar(select(TaskEvent.id).join(
            Task, Task.id == TaskEvent.task_id).where(
                Task.company_id == room.company_id,
                TaskEvent.kind == "created",
                TaskEvent.from_value == source_ref,
            ).limit(1))
    if duplicate is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Этот процесс из сообщения уже запускали")

    src = (msg.content or msg.file_name or "").strip()
    context = (f"{msg.user_name or 'Участник'}: {src}\n\n"
               f"Из обсуждения «{room.name or 'чат'}».")
    try:
        if tpl.doc_kind_id:
            entity, result = await process_templates.launch(
                db, room.company_id, tpl, current_user,
                responsible_id=responsible_id,
                source="chat",
                source_ref=source_ref,
                source_note=f"из обсуждения «{room.name or 'чат'}»",
                summary_suffix=context,
                object_id=room.scope_object_id,
            )
            # Обратная ссылка на обсуждение. В чат мы пишем сообщение со ссылкой
            # на документ, а в карточке оставался только `source_ref` — строка,
            # по которой человек никуда не перейдёт. Разговор, из которого
            # документ вырос, спрашивают чаще, чем кажется: там причина.
            db.add(DocRelation(
                company_id=room.company_id, doc_id=entity.id, kind="discussion",
                target_ref=f"room:{room.id}", created_by=current_user.id))
        else:
            entity, result = await process_templates.launch_task(
                db, room.company_id, tpl, current_user,
                responsible_id=responsible_id,
                title=body.title or src[:300] or tpl.title,
                source_ref=source_ref,
                source_note=f"из обсуждения «{room.name or 'чат'}»",
                summary_suffix=context,
                object_id=room.scope_object_id,
            )
            if msg.file_url:
                try:
                    file_id = uuid.UUID(msg.file_url.rstrip("/").rsplit("/", 1)[-1])
                except (ValueError, TypeError):
                    file_id = None
                source_file = await db.get(SourceFile, file_id) if file_id else None
                if source_file is not None and source_file.company_id == room.company_id:
                    db.add(TaskAttachment(
                        task_id=entity.id,
                        file_id=source_file.id,
                        uploaded_by=current_user.id,
                    ))
    except process_templates.ProcessTemplateError as exc:
        code = (status.HTTP_403_FORBIDDEN if "Недостаточно прав" in str(exc)
                else status.HTTP_400_BAD_REQUEST)
        raise HTTPException(code, str(exc)) from exc

    if tpl.doc_kind_id:
        target_url = (f"{get_settings().app_public_url.rstrip('/')}"
                      f"/docs?view=all&doc={entity.id}")
        state = ("маршрут согласования запущен" if result["started"]
                 else "этап подготовки создан")
    else:
        target_url = (f"{get_settings().app_public_url.rstrip('/')}"
                      f"/docs/work?view=errands&task={entity.id}")
        state = f"задача №{entity.number} поставлена"
    note = ChatMessage(
        room_id=room.id, user_id=current_user.id, user_name=current_user.name,
        type="text",
        content=f"→ Запущен процесс «{tpl.name}»: {state}\n{target_url}",
        reply_to=mid)
    db.add(note)
    room.updated_at = _now()
    await db.flush()
    parties = await _party_types(db, room.company_id, {current_user.id})
    payload = _msg_out(note, 0, msg, None, parties.get(current_user.id))
    await db.commit()
    await manager.broadcast(f"chat:{room.id}", _событие("chat:message", payload.model_dump()))
    if tpl.doc_kind_id:
        return {"ok": True, **process_templates.launch_out(entity, tpl, result),
                "documentUrl": target_url}
    return {"ok": True, **process_templates.task_launch_out(entity, tpl, result),
            "taskUrl": target_url}


@router.post("/tasks/{task_id}/room", response_model=RoomDetailOut)
async def ensure_task_room(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Чат задачи: скрытая группа «быстро обсудить, не засоряя ленту».

    Лента задачи — это след работы (кто двинул, кто передал, чем подтвердил), и
    короткие «а когда сможешь?» в ней только мешают. Поэтому обсуждение живёт
    отдельной комнатой, в общий список чатов она не попадает и открывается
    только из карточки задачи — как у заявок.
    """
    from app.models import Task, TaskWatcher

    cid = await _company_of(current_user, db)
    # Поручения переехали в «Трек», а ключ `plan` остался только у ранее выданных
    # ролей. Гейт спрашивает сначала новый продукт, потом старый — как в самих
    # ручках поручений (`tasks_router._assert_work`). Иначе первый же человек, у
    # которого есть только «Трек», не смог бы открыть обсуждение своей работы.
    try:
        await assert_company_product(str(cid), current_user, db, "docs")
    except HTTPException:
        await assert_company_product(str(cid), current_user, db, "plan")
    try:
        tid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    task = await db.get(Task, tid)
    if task is None or task.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")

    room = (await db.execute(select(ChatRoom).where(
        ChatRoom.scope_task_id == tid, ChatRoom.company_id == cid,
        ChatRoom.is_active.is_(True)))).scalar_one_or_none()
    if room is None:
        room = ChatRoom(type="group", kind=None, name=f"Задача №{task.number}",
                        company_id=cid, created_by=current_user.id, scope_task_id=tid,
                        scope_object_id=task.object_id)
        db.add(room)
        await db.flush()
        db.add(ChatParticipant(room_id=room.id, user_id=current_user.id, role="owner"))

    # Кто причастен к работе, тот и в обсуждении: автор, исполнитель, наблюдатели.
    # Состав добирается при КАЖДОМ заходе, а не только при заведении комнаты: работу
    # передают, наблюдателей добавляют потом, и назначенный позже исполнитель иначе
    # оставался вне разговора — сообщения ему не приходили, пока он сам не откроет
    # вкладку. Тот же идемпотентный добор, что у системных комнат пространства.
    watchers = (await db.execute(select(TaskWatcher.user_id).where(
        TaskWatcher.task_id == tid))).scalars().all()
    known = set((await db.execute(select(ChatParticipant.user_id).where(
        ChatParticipant.room_id == room.id))).scalars().all())
    missing = {i for i in (task.author_id, task.assignee_id, current_user.id, *watchers)
               if i and i not in known}
    if missing:
        await db.execute(pg_insert(ChatParticipant.__table__).values([
            {"id": uuid.uuid4(), "room_id": room.id, "user_id": uid,
             "role": "member", "is_muted": False} for uid in missing
        ]).on_conflict_do_nothing(index_elements=["room_id", "user_id"]))
    await db.commit()
    return await get_room(str(room.id), current_user, db)


@router.post("/tickets/{ticket_id}/room", response_model=RoomDetailOut)
async def ensure_ticket_room(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Чат заявки: скрытая группа «быстро обсудить и записать следующий шаг».

    В общий список чатов не попадает — увидеть её можно только из карточки заявки.
    Создаётся при первом обращении; участники — подключённые к заявке (автор,
    исполнители; матч между схемами по email) плюс открывший."""
    cid = await _company_of(current_user, db)
    try:
        tid = uuid.UUID(ticket_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")

    # Заявка — своей компании, и вызывающий к ней причастен. Без этой проверки чат
    # заявки открывался ЛЮБОМУ сотруднику пространства по её id: комната скрытая, но
    # ручка молча вписывала пришедшего в участники и отдавала всю переписку.
    t = (await db.execute(text(
        "select t.id, t.number, t.display_number, t.title, t.customer_user_id, "
        "t.assigned_to, t.current_assignee_id, lower(cu.email) as customer_email, "
        "lower(au.email) as assignee_email, lower(ca.email) as current_email "
        "from public.tickets t "
        "left join public.users cu on cu.id = t.customer_user_id "
        "left join public.users au on au.id = t.assigned_to "
        "left join public.users ca on ca.id = t.current_assignee_id "
        "where t.id = :t"), {"t": str(tid)})).first()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    my_email = (current_user.email or "").lower()
    related = bool(my_email) and my_email in {
        t.customer_email, t.assignee_email, t.current_email} - {None}
    if not (related or current_user.is_superadmin
            or await _is_space_admin(current_user, cid, db)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Обсуждение заявки доступно её участникам")

    existing = (await db.execute(select(ChatRoom).where(
        ChatRoom.scope_ticket_id == tid, ChatRoom.company_id == cid,
        ChatRoom.is_active.is_(True)))).scalar_one_or_none()
    if existing is not None:
        p = (await db.execute(select(ChatParticipant.id).where(
            ChatParticipant.room_id == existing.id,
            ChatParticipant.user_id == current_user.id))).scalar_one_or_none()
        if p is None:
            db.add(ChatParticipant(room_id=existing.id, user_id=current_user.id, role="member"))
            await db.commit()
        return await get_room(str(existing.id), current_user, db)

    num = t.display_number or (str(t.number) if t.number is not None else "")
    room = ChatRoom(type="group", kind=None,
                    name=f"Заявка {('№' + num) if num else ''}".strip(),
                    company_id=cid, created_by=current_user.id, scope_ticket_id=tid)
    db.add(room)
    await db.flush()
    db.add(ChatParticipant(room_id=room.id, user_id=current_user.id, role="owner"))
    # Подключённые к заявке — люди Поддержки; в пространство их приводит email.
    sup_ids = [x for x in (t.customer_user_id, t.assigned_to, t.current_assignee_id) if x]
    if sup_ids:
        emails = [e for (e,) in (await db.execute(text(
            "select lower(email) from public.users where id = any(:ids)"),
            {"ids": sup_ids})).all() if e]
        if emails:
            core_ids = (await db.execute(select(User.id).where(
                func.lower(User.email).in_(emails),
                User.id != current_user.id))).scalars().all()
            for uid in core_ids:
                if cid in await _member_ids(uid, db):
                    db.add(ChatParticipant(room_id=room.id, user_id=uid, role="member"))
    await db.commit()
    return await get_room(str(room.id), current_user, db)


# ── Web Push: подписки браузера ──────────────────────────────────────────────
class PushSubscribeBody(BaseModel):
    endpoint: str
    keys: dict = {}   # {p256dh, auth} — как отдаёт PushSubscription.toJSON()
    showPreview: bool = True   # текст сообщения в уведомлении (иначе «Новое сообщение»)


@router.get("/push/vapid")
async def push_vapid_key(db: AsyncSession = Depends(get_db),
                         _: User = Depends(get_current_user)):
    """Публичный VAPID-ключ стека — applicationServerKey для подписки браузера."""
    keys = await web_push.get_or_create_keys(db)
    return {"key": keys.public_key}


@router.post("/push/subscribe", status_code=status.HTTP_201_CREATED)
async def push_subscribe(
    body: PushSubscribeBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить подписку браузера. Идемпотентно по endpoint: браузер один — строка одна."""
    p256dh = (body.keys or {}).get("p256dh", "")
    auth = (body.keys or {}).get("auth", "")
    if not body.endpoint or not p256dh or not auth:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неполная подписка")
    existing = (await db.execute(select(ChatPushSubscription).where(
        ChatPushSubscription.endpoint == body.endpoint))).scalar_one_or_none()
    if existing is not None:
        existing.user_id, existing.p256dh, existing.auth = current_user.id, p256dh, auth
        existing.show_preview = body.showPreview
    else:
        db.add(ChatPushSubscription(user_id=current_user.id, endpoint=body.endpoint,
                                    p256dh=p256dh, auth=auth, show_preview=body.showPreview))
    await db.commit()
    return {"ok": True}


@router.post("/push/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def push_unsubscribe(
    body: PushSubscribeBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(sa_delete(ChatPushSubscription).where(
        ChatPushSubscription.endpoint == body.endpoint,
        ChatPushSubscription.user_id == current_user.id))
    await db.commit()


@router.patch("/rooms/{room_id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def set_participant_role(
    room_id: str, user_id: str, body: ParticipantRoleBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Назначить или снять админа чата — только владелец. Админов может быть несколько."""
    if body.role not in ("admin", "member"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Роль: admin или member")
    try:
        rid, uid = uuid.UUID(room_id), uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await _assert_participant(rid, current_user, db)
    my = await _my_room_role(rid, current_user, db)
    if not (current_user.is_superadmin or room.created_by == current_user.id
            or my == "owner"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Роли в чате раздаёт его владелец")
    if room.type == "direct":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "В личной переписке нет ролей")
    p = (await db.execute(select(ChatParticipant).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == uid))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Участник не найден")
    if p.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "У чата один владелец — передача владения в «Управлении»")
    p.role = body.role
    await db.commit()


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
    stmt = (select(User.id, User.name, User.email, User.avatar_url, UserCompany.party_type)
            .join(UserCompany, UserCompany.user_id == User.id)
            .where(UserCompany.company_id == cid, User.id != current_user.id))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.email.ilike(like)))
    rows = (await db.execute(stmt.order_by(User.name).limit(20))).all()
    online = await manager.online_user_ids()
    return [{"userId": str(uid), "name": nm, "email": em, "online": str(uid) in online,
             "avatarUrl": av, "partyType": party_type or "internal"}
            for uid, nm, em, av, party_type in rows]


# ── карточка человека ────────────────────────────────────────────────────────
@router.get("/users/{user_id}/profile")
async def user_profile(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """«Кто это» по клику на человека в чатах: то, что о нём знает пространство.

    Доступно любому участнику пространства (не только админу): должность,
    принадлежность и последний вход — не секрет от коллег, это и есть ответ
    на вопрос «с кем я говорю»."""
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    cid = await _company_of(current_user, db)
    m = await db.get(UserCompany, (uid, cid))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Человек не из вашего пространства")
    u = await db.get(User, uid)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    org = await db.get(Counterparty, m.organization_id) if m.organization_id else None
    return {
        "userId": str(uid),
        "name": u.name,
        "email": u.email,
        "position": m.position,
        "role": m.role,
        "partyType": getattr(m, "party_type", None) or "internal",
        "organizationName": (org.short_name or org.name) if org else None,
        "lastSeenAt": u.last_seen_at.isoformat() if u.last_seen_at else None,
        "avatarUrl": u.avatar_url,
        "mailOnly": u.mail_only,
    }


class MyProfileBody(BaseModel):
    """Что человек меняет о себе сам. Имя — то, как его зовут в разговоре."""
    name: str | None = None
    # Файл пространства (/api/files/<id>); "" — убрать фото.
    avatarUrl: str | None = None
    # Телефоны — его личные контакты, а не сведения о месте работы: их он и
    # правит сам. "" — убрать номер.
    phoneMobile: str | None = None
    phoneOffice: str | None = None


@router.patch("/me")
async def update_me(
    body: MyProfileBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Своё имя и фото. Должность и принадлежность правит администратор —
    это сведения о месте человека в пространстве, а не его личное дело."""
    if body.name is not None:
        name = body.name.strip()
        if len(name) < 2:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Имя слишком короткое")
        current_user.name = name[:255]
    if body.avatarUrl is not None:
        url = body.avatarUrl.strip()
        # Только файл пространства: чужой URL превратил бы аватар в трекер,
        # который отдаёт стороннему серверу, кто и когда открыл чат.
        if url and not url.startswith("/api/files/"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ожидается файл пространства")
        current_user.avatar_url = url or None
    for поле, значение in (("phone_mobile", body.phoneMobile),
                           ("phone_office", body.phoneOffice)):
        if значение is not None:
            setattr(current_user, поле, значение.strip()[:40] or None)
    await db.commit()
    return {"ok": True, "name": current_user.name, "avatarUrl": current_user.avatar_url}


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
    online = await manager.online_user_ids()
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


async def _admin_room(room_id: str, cid: uuid.UUID, db: AsyncSession) -> ChatRoom:
    """Комната, которой администратор пространства вправе управлять.

    Личная переписка двоих и скрытый чат заявки сюда НЕ попадают. Управление
    составом — это право добавить кого угодно, в том числе себя: без этого фильтра
    администратор вписывался в чужую личку и читал её обычной ручкой сообщений.
    Список комнат он по-прежнему видит целиком (кто с кем говорит — вопрос
    администрирования), но войти в разговор двоих не может.
    """
    try:
        rid = uuid.UUID(room_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    room = await db.get(ChatRoom, rid)
    if room is None or room.company_id != cid or not room.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    if room.type == "direct" or room.scope_ticket_id is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Личной перепиской и обсуждением заявки управлять нельзя")
    return room


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

    # Комнаты-спутники (обсуждение задачи, чат заявки) в реестр не идут: это часть
    # карточки, а не чат пространства. Иначе администратор считает их за живые
    # группы — на пилоте пустая «Задача №25» попадала и в счётчик «молчат месяц».
    rooms = (await db.execute(select(ChatRoom).where(
        ChatRoom.company_id == cid, ChatRoom.is_active.is_(True),
        ChatRoom.is_archived.is_(archived),
        ChatRoom.scope_task_id.is_(None), ChatRoom.scope_ticket_id.is_(None),
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
    room = await _admin_room(room_id, cid, db)
    rid = room.id

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
    added = wanted - have
    for uid in added:
        db.add(ChatParticipant(room_id=rid, user_id=uid, role="member"))
    # Состав чата меняет администратор — это видно в журнале пространства: человек
    # должен иметь возможность узнать, кто добавил его в разговор и когда.
    if added:
        await log_audit(db, actor=current_user, company_id=cid, action="chat.people_add",
                        target=room.name or "чат", details={"roomId": str(rid), "added": len(added)})
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
    room = await _admin_room(room_id, cid, db)
    rid = room.id
    # Системные комнаты («Общий чат», «Объявления») не переименовываем: их имя —
    # часть устройства пространства, а не пользовательская настройка.
    if body.name is not None and room.kind is None:
        room.name = body.name.strip() or room.name
    if body.scopeProduct is not None:
        room.scope_product = body.scopeProduct.strip() or None
    await log_audit(db, actor=current_user, company_id=cid, action="chat.room_patch",
                    target=room.name or "чат", details={"roomId": str(rid)})
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
    room = await _admin_room(room_id, cid, db)
    rid = room.id
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
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
    await log_audit(db, actor=current_user, company_id=cid, action="chat.role_set",
                    target=room.name or "чат",
                    details={"roomId": str(rid), "userId": str(uid), "role": body.role})
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
    room = await _admin_room(room_id, cid, db)
    rid = room.id
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    p = (await db.execute(select(ChatParticipant).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == uid))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Участник не найден")
    if p.role == "owner":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Нельзя вывести владельца: сначала передайте владение другому")
    await db.delete(p)
    await log_audit(db, actor=current_user, company_id=cid, action="chat.participant_remove",
                    target=room.name or "чат", details={"roomId": str(rid), "userId": str(uid)})
    await db.commit()
