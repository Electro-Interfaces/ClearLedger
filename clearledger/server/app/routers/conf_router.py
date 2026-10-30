"""«Конференции» — приложение пространства (docs/CONF.md).

Второй системы встреч здесь нет. Плановая конференция — это встреча календаря:
у неё уже есть участники, ответы, внешние гости, письма с календарным вложением
и напоминания. Приложение добавляет то, чего у календаря нет: журнал
проведённых конференций (кто пришёл, сколько шло, где запись) и один экран, с
которого конференция заводят, входят в него и потом ищут.

Комната у встречи постоянная (`jitsi.room_for`) — вернуться в неё можно и
назавтра. Ведущим входит любой участник: без ведущего Jitsi держит остальных на
«ждём организатора», и опоздание одного человека отменяет совещание.
"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import (
    CalendarAttendee, CalendarEvent, CalendarGuest, ConfPresence, ConfRoom,
    ConfSession, User, UserCompany,
)
from app.services import jitsi

router = APIRouter(prefix="/conf", tags=["Конференции"])


class MeetingIn(BaseModel):
    company_id: str
    title: str = Field(default="", max_length=300)
    # Пусто — конференция сейчас. Иначе встреча встаёт в календарь на это время.
    starts_at: datetime | None = None
    minutes: int = Field(default=60, ge=5, le=600)
    attendee_ids: list[str] = Field(default_factory=list)
    # Внешние участники: им уходит письмо с гостевой ссылкой и календарным
    # вложением. Учётной записи гость не получает.
    guest_emails: list[str] = Field(default_factory=list)
    subject_ref: str | None = None
    description: str | None = None
    # Позвать сразу. Чат — всегда: он в пространстве и читается тут же.
    notify: bool = True
    # Открыть всему пространству: конференцию увидит и сможет присоединиться
    # любой сотрудник. По умолчанию закрыта — видят только позванные.
    open_to_space: bool = False
    # Ведущие из позванных; пусто — ведущий тот, кто созывает.
    host_ids: list[str] = Field(default_factory=list)
    # Конференция по расписанию: правило серии календаря (`{"mode": "weekly"}`).
    # Повторения создаёт планировщик — с теми же участниками и той же комнатой.
    recurrence: dict | None = None
    # Продублировать почтой. Отдельная воля, а не довесок к приглашению: письмо
    # со встречей нужно тем, кто живёт в Outlook и на совещание приходит из
    # своего календаря, а на ежедневную планёрку оно шлёт лишний конверт.
    email_copy: bool = False


class RoomIn(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=200)
    purpose: str | None = Field(None, max_length=300)


class NoteIn(BaseModel):
    company_id: str
    note: str = Field(default="", max_length=4000)


def _uuid(value: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Неверный {name}")


async def _company(company_id: str, user: User, db: AsyncSession) -> uuid.UUID:
    cid = _uuid(company_id, "company_id")
    есть = (await db.execute(select(UserCompany.user_id).where(
        UserCompany.company_id == cid,
        UserCompany.user_id == user.id))).scalar_one_or_none()
    if есть is None and not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к пространству")
    return cid


def _room_of(url: str | None) -> str | None:
    """Имя нашей комнаты из ссылки. Чужая ссылка (Zoom, Teams) — не наша."""
    if not url:
        return None
    хвост = url.rstrip("/").split("/")[-1].split("?")[0].split("#")[0]
    return хвост if хвост.startswith("ledger-") else None


async def _people(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


def _session_dto(s: ConfSession, люди: dict) -> dict[str, Any]:
    длилось = int((s.ended_at - s.started_at).total_seconds()) if s.ended_at else None
    return {
        "id": str(s.id),
        "started_at": s.started_at,
        "ended_at": s.ended_at,
        "seconds": длилось,
        "note": s.note,
        "recording": bool(s.recording_path),
        "recording_seconds": s.recording_seconds,
        "came": [{
            "user_id": str(p.user_id),
            "name": (люди.get(p.user_id).name if люди.get(p.user_id) else "—"),
            "joined_at": p.joined_at,
        } for p in getattr(s, "_presence", [])],
    }


def _event_dto(ev: CalendarEvent, участники: list, гости: list,
               сессия: ConfSession | None, люди: dict, me: uuid.UUID) -> dict[str, Any]:
    организатор = люди.get(ev.organizer_id)
    return {
        "id": str(ev.id),
        "title": ev.title,
        "description": ev.description,
        "starts_at": ev.starts_at,
        "ends_at": ev.ends_at,
        "tz": ev.tz,
        "status": ev.status,
        "subject_ref": ev.subject_ref,
        "organizer_id": str(ev.organizer_id),
        "organizer": организатор.name if организатор else None,
        "guest_url": ev.conference_url,
        "room": _room_of(ev.conference_url),
        "mine": ev.organizer_id == me or any(a.user_id == me for a in участники),
        # Мой ответ: pending — меня позвали и я ещё не сказал, буду ли.
        # Без этого приглашение неотличимо от чужой встречи, которую видно
        # просто потому, что она открыта пространству.
        "my_response": next((a.response for a in участники if a.user_id == me), None),
        "organizer_is_me": ev.organizer_id == me,
        "attendees": [{
            "user_id": str(a.user_id),
            "name": (люди.get(a.user_id).name if люди.get(a.user_id) else "—"),
            "response": a.response,
        } for a in участники],
        "guests": [{"email": g.email, "name": g.name, "response": g.response}
                   for g in гости],
        "live": bool(сессия and сессия.ended_at is None),
        "session": _session_dto(сессия, люди) if сессия else None,
    }


async def _load(db: AsyncSession, события: list[CalendarEvent],
                me: uuid.UUID) -> list[dict[str, Any]]:
    """Собрать карточки списком: участники, гости, последняя сессия, имена."""
    if not события:
        return []
    ids = [e.id for e in события]
    участники = (await db.execute(select(CalendarAttendee).where(
        CalendarAttendee.event_id.in_(ids)))).scalars().all()
    гости = (await db.execute(select(CalendarGuest).where(
        CalendarGuest.event_id.in_(ids),
        CalendarGuest.revoked_at.is_(None)))).scalars().all()
    сессии = (await db.execute(select(ConfSession).where(
        ConfSession.event_id.in_(ids)).order_by(
            ConfSession.started_at.desc()))).scalars().all()
    присутствие = []
    if сессии:
        присутствие = (await db.execute(select(ConfPresence).where(
            ConfPresence.session_id.in_([s.id for s in сессии])))).scalars().all()
    for s in сессии:
        s._presence = [p for p in присутствие if p.session_id == s.id]
    по_событию: dict[uuid.UUID, ConfSession] = {}
    for s in сессии:
        по_событию.setdefault(s.event_id, s)
    # Сколько материалов приложено: повестку читают ДО входа, и строка должна
    # сказать, что она есть.
    from app.models import CalendarPaper
    материалов = {i: n for i, n in (await db.execute(select(
        CalendarPaper.event_id, func.count()).where(
            CalendarPaper.event_id.in_(ids)).group_by(CalendarPaper.event_id))).all()}

    люди = await _people(db, ({e.organizer_id for e in события}
                              | {a.user_id for a in участники}
                              | {p.user_id for p in присутствие}))
    return [{**_event_dto(e,
                          [a for a in участники if a.event_id == e.id],
                          [g for g in гости if g.event_id == e.id],
                          по_событию.get(e.id), люди, me),
             "papers": материалов.get(e.id, 0)}
            for e in события]


@router.get("/meetings")
async def meetings_list(
    company_id: str = Query(...),
    scope: str = Query("upcoming", pattern="^(upcoming|past|mine)$"),
    q: str = Query("", max_length=200),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Конференции пространства: ближайшие, прошедшие, мои.

    Список строится по встречам с НАШЕЙ комнатой: встреча со ссылкой на Zoom
    остаётся в календаре, но в «Конференциях» ей делать нечего — войти ведущим
    туда мы не можем и о том, состоялась ли она, ничего не знаем.
    """
    cid = await _company(company_id, current_user, db)
    await _закрыть_брошенные(db, cid)
    сейчас = datetime.now(timezone.utc)
    условия = [CalendarEvent.company_id == cid,
               CalendarEvent.conference_url.ilike("%/ledger-%")]
    # Конференция уходит вперёд или назад по ФАКТУ, а не по часам в календаре:
    # закрытая — прошедшая, даже если по расписанию ещё «идёт». Пока делили по
    # времени, завершённая конференция висела в «Назначены» до конца её часа, и
    # человек видел в списке то, что сам только что закончил (замечание МАГа
    # 10.09.2026).
    # Закрытой считается конференция, которую закончили В ЕЁ ВРЕМЯ. Вход за
    # неделю до срока (проверить комнату, ссылку) и «Завершить» после него
    # встречу не отменяют: иначе назначенная на 20-е пропадала из «Назначены»
    # тринадцатого (проверка 13.10.2026).
    своё = aliased(CalendarEvent)
    закрытые = select(ConfSession.event_id).join(
        своё, своё.id == ConfSession.event_id).where(
        ConfSession.company_id == cid, ConfSession.ended_at.isnot(None),
        ConfSession.ended_at >= своё.starts_at)
    if scope == "upcoming":
        условия.append(CalendarEvent.ends_at >= сейчас)
        условия.append(CalendarEvent.id.not_in(закрытые))
        # Отменённая — не назначенная: серия после отмены висела в списке
        # строкой «отменена» на каждое повторение (69 строк, 13.10.2026).
        условия.append(CalendarEvent.status != "cancelled")
    elif scope == "past":
        условия.append(or_(CalendarEvent.ends_at < сейчас,
                           CalendarEvent.id.in_(закрытые)))
    if q.strip():
        условия.append(CalendarEvent.title.ilike(f"%{q.strip()}%"))

    мои_события = select(CalendarAttendee.event_id).where(
        CalendarAttendee.user_id == current_user.id)
    # Конференция видна тем, кого позвали. Открытой всему пространству она
    # становится намеренно (`visibility='company'`) — иначе человек видел бы
    # чужой разговор, куда его не звали, и мог бы к нему присоединиться.
    условия.append(or_(CalendarEvent.visibility == "company",
                       CalendarEvent.organizer_id == current_user.id,
                       CalendarEvent.id.in_(мои_события)))
    if scope == "mine":
        условия.append(or_(CalendarEvent.organizer_id == current_user.id,
                           CalendarEvent.id.in_(мои_события)))

    порядок = (CalendarEvent.starts_at.asc() if scope == "upcoming"
               else CalendarEvent.starts_at.desc())
    события = (await db.execute(select(CalendarEvent).where(*условия)
                                .order_by(порядок).limit(limit))).scalars().all()
    return {"meetings": await _load(db, list(события), current_user.id),
            "enabled": settings.jitsi_enabled}


@router.get("/live")
async def meetings_live(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Что идёт прямо сейчас — чтобы зайти в конференцию, а не выяснять по телефону.

    Показываем ТОЛЬКО то, куда человека пустили: свои конференции, открытые
    пространству и постоянные комнаты. Первая версия отдавала все идущие сессии
    компании вместе с гостевой ссылкой — посторонний видел тему закрытого
    разговора и мог передать рабочую ссылку наружу, притом что штатный вход ему
    возвращал 403 и создавал ложное ощущение приватности (CONF-01, приёмка
    10.09.2026).
    """
    cid = await _company(company_id, current_user, db)
    await _закрыть_брошенные(db, cid)
    сессии = (await db.execute(select(ConfSession).where(
        ConfSession.company_id == cid, ConfSession.ended_at.is_(None))
        .order_by(ConfSession.started_at.desc()).limit(50))).scalars().all()
    if not сессии:
        return {"live": []}

    # Права считаем по событиям: постоянная комната принадлежит всему
    # пространству, у конференции право даёт приглашение или открытость.
    ids = [s.event_id for s in сессии if s.event_id]
    события: dict[uuid.UUID, CalendarEvent] = {}
    зван: set[uuid.UUID] = set()
    if ids:
        события = {e.id: e for e in (await db.execute(select(CalendarEvent).where(
            CalendarEvent.id.in_(ids)))).scalars().all()}
        зван = set((await db.execute(select(CalendarAttendee.event_id).where(
            CalendarAttendee.event_id.in_(ids),
            CalendarAttendee.user_id == current_user.id))).scalars())

    мои = []
    for s in сессии:
        if s.conf_room_id is not None:
            мои.append(s)                       # постоянная комната — общая
            continue
        ev = события.get(s.event_id) if s.event_id else None
        if ev is None:
            # Сессия без события: показываем только тому, кто её открыл.
            if s.started_by == current_user.id:
                мои.append(s)
            continue
        if (ev.visibility == "company" or ev.organizer_id == current_user.id
                or ev.id in зван):
            мои.append(s)
    if not мои:
        return {"live": []}

    присутствие = (await db.execute(select(ConfPresence).where(
        ConfPresence.session_id.in_([s.id for s in мои])))).scalars().all()
    люди = await _people(db, {p.user_id for p in присутствие})
    состав: dict[uuid.UUID, list] = {}
    свои_ids = [s.event_id for s in мои if s.event_id]
    if свои_ids:
        for a in (await db.execute(select(CalendarAttendee).where(
                CalendarAttendee.event_id.in_(свои_ids)))).scalars().all():
            состав.setdefault(a.event_id, []).append(a)
    ответ = []
    for s in мои:
        s._presence = [p for p in присутствие if p.session_id == s.id]
        участники = состав.get(s.event_id, []) if s.event_id else []
        ответ.append({**_session_dto(s, люди), "title": s.title,
                      "event_id": str(s.event_id) if s.event_id else None,
                      # Сколько звали и сколько подтвердили: у идущей конференции
                      # это тот же вопрос, что у назначенной.
                      "invited": len(участники),
                      "accepted": sum(1 for a in участники if a.response == "accepted"),
                      "organizer_is_me": bool(
                          события.get(s.event_id) is not None
                          and события[s.event_id].organizer_id == current_user.id),
                      # Гостевая ссылка = вход без пропуска. Отдаём её только
                      # тому, кто и сам вправе войти, — иначе ссылку унесут.
                      "guest_url": f"https://{settings.jitsi_domain}/{s.room}"})
    return {"live": ответ}


async def _закрыть_комнату(room: str) -> bool:
    """Уничтожить комнату на сервере конференций: разговор кончился для всех.

    Без этого «Завершить» закрывает только запись в журнале, а комната живёт:
    брошенная вкладка держала её час и всё это время шла запись (случай МАГа
    10.09.2026). Отказ приёмника не считаем ошибкой — конференция в журнале уже
    закрыта, и человеку незачем видеть отказ инфраструктуры.
    """
    if not settings.conf_closer_url or not settings.conf_ingest_token:
        return False
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as клиент:
            ответ = await клиент.post(settings.conf_closer_url,
                                      json={"room": room,
                                            "token": settings.conf_ingest_token})
        return ответ.status_code == 200 and ответ.json().get("closed") is True
    except Exception:  # noqa: BLE001
        return False


# Сколько постоянная комната стоит пустой, прежде чем разговор в ней считается
# оконченным: минута, если все вышли сами (вернуться за забытым вопросом —
# тот же разговор), и пять, если вкладки просто замолчали — человек мог
# закрыть пространство, не выходя из комнаты.
ROOM_EMPTY_SEC = 60
ROOM_SILENT_SEC = 300


async def _отметить_приход(db: AsyncSession, сессия: ConfSession, user: User,
                           moderator: bool = False) -> None:
    """Человек вошёл в комнату — впервые или вернулся.

    Сигнал «я здесь» ставим сразу: без него вошедший и закрывший вкладку в
    первые полминуты числился в комнате до её закрытия по сроку.
    """
    сейчас = datetime.now(timezone.utc)
    p = (await db.execute(select(ConfPresence).where(
        ConfPresence.session_id == сессия.id,
        ConfPresence.user_id == user.id))).scalar_one_or_none()
    if p is None:
        db.add(ConfPresence(session_id=сессия.id, user_id=user.id,
                            last_seen_at=сейчас, moderator=moderator))
    else:
        p.last_seen_at = сейчас
        p.left_at = None
        p.moderator = moderator


async def _закрыть_брошенные(db: AsyncSession, cid: uuid.UUID) -> None:
    """Закрыть конференции, которые давно кончились.

    О конце разговора нам никто не сообщает: люди просто закрывают вкладку, и
    «Завершить» нажимает хорошо если один из десяти. Без этого счётчик «идут
    сейчас» через день показывает позавчерашнюю планёрку, и человек перестаёт
    ему верить — а он единственное, ради чего в раздел заходят.

    Срок — полчаса после конца встречи (задержались — это нормально) либо
    четыре часа для конференции без времени: столько живёт токен ведущего,
    дальше в комнату всё равно не войти.
    """
    сейчас = datetime.now(timezone.utc)
    живые = (await db.execute(select(ConfSession).where(
        ConfSession.company_id == cid, ConfSession.ended_at.is_(None)))).scalars().all()
    if not живые:
        return
    события = {}
    ids = [s.event_id for s in живые if s.event_id]
    if ids:
        события = {e.id: e for e in (await db.execute(select(CalendarEvent).where(
            CalendarEvent.id.in_(ids)))).scalars().all()}
    изменили = False
    # Постоянная комната пустеет без «Завершить»: кнопки у места нет, люди
    # просто выходят. Пока её закрывал только четырёхчасовой срок, пустая
    # комната всё это время стояла в «Идут сейчас» (проверка 13.10.2026).
    # Комнату на сервере не гасим: гость по ссылке нам не виден и мог остаться.
    комнатные = [s for s in живые if s.conf_room_id is not None]
    if комнатные:
        отметки: dict[uuid.UUID, list[ConfPresence]] = {}
        for p in (await db.execute(select(ConfPresence).where(
                ConfPresence.session_id.in_([s.id for s in комнатные])))).scalars():
            отметки.setdefault(p.session_id, []).append(p)
        for s in комнатные:
            виделись = [p.left_at or p.last_seen_at or p.joined_at
                        for p in отметки.get(s.id, [])]
            последний = max(виделись, default=s.started_at)
            if all(p.left_at for p in отметки.get(s.id, [])):
                тишина = ROOM_EMPTY_SEC          # все вышли сами
            else:
                тишина = ROOM_SILENT_SEC         # вкладка замолчала — ждём дольше
            if (сейчас - последний).total_seconds() > тишина:
                s.ended_at = max(последний, s.started_at)
                s.close_reason = "empty"
                изменили = True
    for s in живые:
        if s.ended_at is not None:
            continue
        ev = события.get(s.event_id) if s.event_id else None
        предел = s.started_at + timedelta(hours=4)
        if ev:
            # Не позже срока жизни токена: в повторение серии входят и за
            # недели до его даты, и такая конференция висела в «Идут сейчас»
            # до конца встречи по календарю (РусГидро, 07.10–13.10.2026).
            предел = min(предел, ev.ends_at + timedelta(minutes=30))
        # Не раньше начала: в комнату заходят и после того, как час встречи в
        # календаре кончился, — тогда «конец по расписанию» оказывается в
        # прошлом, и конференция получала отрицательную длительность.
        предел = max(предел, s.started_at + timedelta(minutes=15))
        if сейчас > предел:
            s.ended_at = предел
            s.close_reason = "auto"
            изменили = True
    if изменили:
        await db.commit()
        for s in живые:
            if s.close_reason == "auto":
                await _закрыть_комнату(s.room)


async def _пригласить(db: AsyncSession, ev: CalendarEvent, кого: list[User],
                      организатор: User, гостевая: str,
                      почтой: bool = False) -> dict[str, int]:
    """Позвать людей пространства: строка в чат и, по воле зовущего, письмо.

    Чат идёт всегда: он внутри пространства, читается там же, где работают, и
    ссылка в нём кликается сразу. Письмо — по отдельной галочке: оно нужно, когда
    участник живёт в Outlook и на встречу приходит из своего календаря, но на
    ежедневной планёрке превращается в лишний конверт каждому.

    Пишем в личную переписку ЗОВУЩЕГО с позванным, а не служебной строкой от
    «Секретаря». Человек ищет приглашение там, где разговаривает с коллегой:
    пока оно приходило в отдельный чат от безличного отправителя, его не
    связывали с конференцией и не находили (замечание МАГа 10.09.2026).

    Ошибки доставки глотаем: конференция уже заведена, и лежащий почтовый сервер
    не должен её отменять.
    """
    from app.services import email_service, ics, meeting_notice, notify, space_time

    когда = space_time.as_utc(ev.starts_at).astimezone(space_time.zone(ev.tz))
    подпись = когда.strftime("%d.%m.%Y в %H:%M")

    def файл(человек: User) -> str:
        # Приглашение (`METHOD:REQUEST`) с получателем в составе: письмо уходит
        # с `method=REQUEST`, и PUBLISH внутри расходился с ним — по RFC 6047
        # такое письмо клиент вправе не принять за приглашение (QA 27.10.2026).
        return ics.event_ics(uid=f"{ev.id}@conf.elsyplus", title=ev.title,
                             starts_at=ev.starts_at, ends_at=ev.ends_at,
                             description=ev.description, url=гостевая, join_url=jitsi.with_subject(гостевая, ev.title),
                             organizer_email=организатор.email,
                             organizer_name=организатор.name,
                             attendees=[(человек.email, человек.name)], invite=True,
                             sequence=meeting_notice._sequence())
    письмом = чатом = 0
    for человек in кого:
        if человек.id == организатор.id:
            continue
        текст = (f"{организатор.name} зовёт на конференцию «{ev.title}»\n"
                 f"Когда: {подпись}\nСсылка: {гостевая}")
        try:
            if (почтой and человек.email and notify.wants_email(человек, "meeting")
                    and await email_service.send_meeting_invite(
                    человек.email,
                    subject=f"Конференция: {ev.title} — {подпись}",
                    text=текст,
                    html=(f"<p>{организатор.name} зовёт на конференцию "
                          f"<b>{ev.title}</b>.</p><p>Когда: {подпись}</p>"
                          f'<p><a href="{гостевая}">Присоединиться</a></p>'),
                    ics=файл(человек))):
                письмом += 1
        except Exception:
            pass
        try:
            await meeting_notice.в_личку(db, ev.company_id, организатор, человек,
                                         f"📹 {текст}", f"Конференция: {ev.title}")
            чатом += 1
        except Exception:
            pass
    return {"mailed": письмом, "chatted": чатом}


@router.post("/meetings", status_code=status.HTTP_201_CREATED)
async def meeting_create(
    payload: MeetingIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Завести конференцию: сейчас или на время, с участниками и приглашениями."""
    from app.routers import work_router

    if not settings.jitsi_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Конференции не настроены")
    cid = await _company(payload.company_id, current_user, db)
    начало = payload.starts_at or datetime.now(timezone.utc)
    название = payload.title.strip() or f"Конференция · {current_user.name}"
    повтор = (payload.recurrence or None) if payload.starts_at else None
    if повтор:
        work_router._check_event_details(
            начало, начало + timedelta(minutes=payload.minutes),
            current_user.tz or "Europe/Moscow", повтор, None, None)

    ev = CalendarEvent(
        company_id=cid, organizer_id=current_user.id, title=название,
        description=payload.description or None,
        starts_at=начало, ends_at=начало + timedelta(minutes=payload.minutes),
        tz=(current_user.tz or "Europe/Moscow"),
        location="Конференция",
        # Закрытая по умолчанию: конференцию видят те, кого позвали. «Открыть
        # пространству» — отдельная воля организатора, а не молчаливое согласие.
        visibility=("company" if payload.open_to_space else "private"),
        subject_ref=payload.subject_ref or None, recurrence=повтор)
    db.add(ev)
    await db.flush()
    # Комната считается от номера встречи: ссылка постоянна, и завтрашний вход
    # ведёт туда же, куда сегодняшнее приглашение.
    ev.conference_url = jitsi.meeting_urls(
        jitsi.event_room(ev), current_user.name)["guest_url"]

    зовём = {_uuid(i, "attendee_ids") for i in payload.attendee_ids} | {current_user.id}
    свои = set((await db.execute(select(UserCompany.user_id).where(
        UserCompany.company_id == cid, UserCompany.user_id.in_(зовём)))).scalars())
    ведущие = ({_uuid(i, "host_ids") for i in payload.host_ids} & зовём & свои) or {current_user.id}
    for uid in зовём & свои:
        db.add(CalendarAttendee(
            event_id=ev.id, user_id=uid, role="required", is_host=uid in ведущие,
            response="accepted" if uid == current_user.id else "pending"))
    await db.commit()
    await db.refresh(ev)

    доставка = {"mailed": 0, "chatted": 0, "guests": 0}
    if payload.notify:
        люди = (await db.execute(select(User).where(
            User.id.in_((свои & зовём) - {current_user.id})))).scalars().all()
        доставка.update(await _пригласить(db, ev, list(люди), current_user,
                                          ev.conference_url, payload.email_copy))
        for адрес in payload.guest_emails:
            адрес = адрес.strip().lower()
            if "@" not in адрес:
                continue
            try:
                await work_router.guest_invite(
                    str(ev.id),
                    work_router.GuestIn(company_id=str(cid), email=адрес),
                    db=db, current_user=current_user)
                доставка["guests"] += 1
            except HTTPException:
                continue

    карточки = await _load(db, [ev], current_user.id)
    return {**карточки[0], "delivery": доставка}


# Сколько ждём ведущего после начала: дальше комнату открывает первый вошедший
# (решение МАГа 15.10.2026). Опоздание ведущего не должно срывать совещание, но
# и раньше срока роль не перехватить.
ЖДЁМ_ВЕДУЩЕГО = timedelta(minutes=5)


async def ведущие_встречи(db: AsyncSession, ev: CalendarEvent) -> set:
    """Ведущие встречи: отмеченные участники, а не отмечен никто — организатор."""
    return await jitsi.meeting_hosts(db, ev)


async def войти_во_встречу(db: AsyncSession, cid, ev: CalendarEvent, user: User) -> dict:
    """Вход в видеоконференцию встречи — один на карточку календаря и «Конференции».

    Раньше входы расходились: из карточки ведущим входил любой приглашённый, из
    «Конференций» — только организатор. Теперь пропуск ведущего у отмеченных
    ведущих; остальные входят участниками и ждут. Если через `ЖДЁМ_ВЕДУЩЕГО`
    после начала ведущего в комнате нет, первый вошедший получает пропуск
    ведущего — только он: следующий застанет ведущего в комнате.
    """
    room = jitsi.event_room(ev)
    сессия = (await db.execute(select(ConfSession).where(
        ConfSession.event_id == ev.id,
        ConfSession.ended_at.is_(None)))).scalar_one_or_none()
    сейчас = datetime.now(timezone.utc)
    ждать_до = None
    if user.id in await ведущие_встречи(db, ev):
        ведущий = True
    elif сейчас < ev.starts_at + ЖДЁМ_ВЕДУЩЕГО:
        ведущий, ждать_до = False, ev.starts_at + ЖДЁМ_ВЕДУЩЕГО
    else:
        есть_ведущий = False
        if сессия is not None:
            есть_ведущий = any(_в_комнате(p, сейчас) for p in (await db.execute(
                select(ConfPresence).where(ConfPresence.session_id == сессия.id,
                                           ConfPresence.moderator.is_(True),
                                           ConfPresence.user_id != user.id))).scalars())
        ведущий = not есть_ведущий
    urls = jitsi.meeting_urls(room, user.name, moderator=ведущий, subject=ev.title)
    if not ev.conference_url:
        ev.conference_url = urls["guest_url"]
        await jitsi.share_series_url(db, ev)
    if сессия is None:
        сессия = ConfSession(company_id=cid, event_id=ev.id, room=room,
                             title=ev.title, subject_ref=ev.subject_ref,
                             started_by=user.id)
        db.add(сессия)
        await db.flush()
    await _отметить_приход(db, сессия, user, moderator=ведущий)
    await db.commit()
    return {**urls, "session_id": str(сессия.id), "moderator": ведущий,
            "host_wait_until": ждать_до}


@router.post("/meetings/{event_id}/join")
async def meeting_join(
    event_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Войти в конференцию ведущим и отметить приход.

    Отметка — то, ради чего журнал заводится: через неделю карточка отвечает,
    кто на конференции был, а кого позвали и не дождались.
    """
    if not settings.jitsi_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Конференции не настроены")
    cid = await _company(company_id, current_user, db)
    ev = await db.get(CalendarEvent, _uuid(event_id, "event_id"))
    if ev is None or ev.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Конференция не найдена")
    if ev.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Встреча отменена")
    свой = ev.organizer_id == current_user.id or (await db.execute(select(
        CalendarAttendee.id).where(
            CalendarAttendee.event_id == ev.id,
            CalendarAttendee.user_id == current_user.id))).scalar_one_or_none()
    if not свой and ev.visibility != "company":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Это не ваша встреча")

    # Ведущего решает общее правило (`войти_во_встречу`): отмеченные ведущие,
    # а через 5 минут без ведущего — первый вошедший (МАГ, 15.10.2026).
    return await войти_во_встречу(db, cid, ev, current_user)


# Сколько молчит вкладка, прежде чем мы считаем, что человек вышел. Браузер о
# закрытии сообщает ненадёжно: `sendBeacon` теряется при обрыве связи, убитом
# процессе и спящем ноутбуке. Поэтому присутствие держится на сигнале «я здесь»
# раз в полминуты, а порог берётся с запасом на пропущенный сигнал.
PRESENCE_TTL_SEC = 90


def _в_комнате(p: "ConfPresence", now: datetime) -> bool:
    """Человек считается присутствующим, пока не вышел и подаёт сигнал.

    Старые записи (до появления сигнала) считаются присутствующими, только если
    сессия ещё идёт: иначе история созвонов задним числом опустела бы.
    """
    if p.left_at is not None:
        return False
    if p.last_seen_at is None:
        return True
    return (now - p.last_seen_at).total_seconds() <= PRESENCE_TTL_SEC


@router.post("/sessions/{session_id}/ping")
async def session_ping(
    session_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Я ещё здесь»: вкладка подаёт сигнал, пока человек в комнате."""
    cid = await _company(company_id, current_user, db)
    s = await db.get(ConfSession, _uuid(session_id, "session_id"))
    if s is None or s.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Конференция не найдена")
    p = (await db.execute(select(ConfPresence).where(
        ConfPresence.session_id == s.id,
        ConfPresence.user_id == current_user.id))).scalar_one_or_none()
    if p is not None:
        p.last_seen_at = datetime.now(timezone.utc)
        # Вернулся в ту же комнату после выхода — отметка о выходе снимается.
        p.left_at = None
        await db.commit()
    return {"ok": True}


@router.post("/sessions/{session_id}/leave")
async def session_leave(
    session_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Человек вышел из комнаты — сам, не закрывая конференцию для остальных."""
    cid = await _company(company_id, current_user, db)
    s = await db.get(ConfSession, _uuid(session_id, "session_id"))
    if s is None or s.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Конференция не найдена")
    p = (await db.execute(select(ConfPresence).where(
        ConfPresence.session_id == s.id,
        ConfPresence.user_id == current_user.id))).scalar_one_or_none()
    if p is not None and p.left_at is None:
        p.left_at = datetime.now(timezone.utc)
        await db.commit()
    return {"ok": True}


@router.post("/sessions/{session_id}/end")
async def session_end(
    session_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Закрыть конференция: разошлись.

    Закрывает участник, а не сервер: комната живёт своей жизнью, и о том, что
    там пусто, мы узнаём последними.
    """
    cid = await _company(company_id, current_user, db)
    s = await db.get(ConfSession, _uuid(session_id, "session_id"))
    if s is None or s.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Конференция не найден")
    # Гасит конференцию встречи тот, кто её собрал, или его помощник. Кнопку
    # интерфейс показывал только организатору, а сервер пускал любого: номер
    # сессии открытой конференции виден всем в «Идут сейчас» (QA 27.10.2026).
    # Постоянная комната общая — её закрывает любой, как и раньше.
    from app.routers.work_router import can_manage_calendar
    ev = await db.get(CalendarEvent, s.event_id) if s.event_id else None
    if ev is not None and not await can_manage_calendar(db, cid, ev.organizer_id, current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Завершить конференцию может тот, кто её собрал, или его помощник")
    закрыта = False
    if s.ended_at is None:
        s.ended_at = datetime.now(timezone.utc)
        s.close_reason = "user"
        # Разошлись раньше — в календаре встреча кончается тогда же: иначе она
        # стояла «запланированной» до конца своего часа, занимала время и звала
        # войти в погашенную комнату (решение МАГа 27.10.2026). Весь день и
        # голову серии не трогаем: по голове считаются следующие встречи.
        if (ev is not None and not ev.all_day and not ev.recurrence
                and ev.starts_at < s.ended_at < ev.ends_at):
            ev.ends_at = s.ended_at
        # Конференция закрыта — в ней никого не осталось по определению. Прежде
        # записи присутствия жили дальше, и комната показывала участников уже
        # после того, как её погасили (замечание Маркова 11.09.2026).
        for p in (await db.execute(select(ConfPresence).where(
                ConfPresence.session_id == s.id,
                ConfPresence.left_at.is_(None)))).scalars().all():
            p.left_at = s.ended_at
        await db.commit()
        # Разговор кончился для всех: комнату уничтожаем, оставшиеся вкладки
        # отключаются. Иначе конференция «завершена» только на нашей стороне.
        закрыта = await _закрыть_комнату(s.room)
    return {"id": str(s.id), "ended_at": s.ended_at, "room_closed": закрыта}


@router.post("/sessions/{session_id}/note")
async def session_note(
    session_id: str,
    payload: NoteIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Записать, о чём договорились. Пишет любой, кто был: секретаря у конференции нет."""
    cid = await _company(payload.company_id, current_user, db)
    s = await db.get(ConfSession, _uuid(session_id, "session_id"))
    if s is None or s.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Конференция не найден")
    s.note = payload.note.strip() or None
    await db.commit()
    return {"id": str(s.id), "note": s.note}


# ── Записи ──────────────────────────────────────────────────────────────────
async def _сессия_записи(db: AsyncSession, room: str, имя: str | None) -> ConfSession | None:
    """Сессия, которой принадлежит запись: последняя, начатая до начала записи.

    Комната у постоянной конференции одна на все созывы, и запись, доставленная
    с опозданием, ложилась на последний созыв, а не на свой («Оперативка»
    06.10.2026 оказалась у входа от 13.10). Начало записи jibri пишет в имя
    файла: `<комната>_ГГГГ-ММ-ДД-ЧЧ-ММ-СС.mp4`.
    """
    запрос = select(ConfSession).where(ConfSession.room == room).order_by(
        ConfSession.started_at.desc())
    m = re.search(r"_(\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d)\.mp4$", имя or "")
    if m:
        from zoneinfo import ZoneInfo
        # ponytail: часы сервера записи — московские (он у нас один). Появится
        # сервер в другом поясе — передавать начало записи полем из finalize.sh.
        начало = datetime.strptime(m[1], "%Y-%m-%d-%H-%M-%S").replace(
            tzinfo=ZoneInfo("Europe/Moscow"))
        своя = (await db.execute(запрос.where(
            ConfSession.started_at <= начало + timedelta(minutes=5)))).scalars().first()
        if своя:
            return своя
    return (await db.execute(запрос)).scalars().first()


@router.post("/recordings/ingest", status_code=status.HTTP_201_CREATED)
async def recording_ingest(
    room: str = Form(...),
    token: str = Form(...),
    seconds: int = Form(0),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Принять запись конференции с сервера записи.

    Сюда стучится finalize-скрипт jibri сразу после того, как конференция
    закончился. Пространств несколько, а сервер записи один, поэтому скрипт
    предлагает файл каждому по очереди: своей комнату признаёт только то
    пространство, у которого есть такая сессия. Ключ подтверждает, что файл
    прислал наш сервер, а не посторонний с угаданным именем комнаты.
    """
    from app.services import file_store

    # Сравнение за постоянное время: по времени ответа `!=` секрет подбирается посимвольно.
    if (not settings.conf_ingest_token or len(settings.conf_ingest_token) < 16
            or not secrets.compare_digest(str(token or ""), settings.conf_ingest_token)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ключ приёма не подошёл")
    сессия = await _сессия_записи(db, room, file.filename)
    if сессия is None:
        # Не наша комната — пусть скрипт спросит следующее пространство.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната не найдена")

    данные = await file.read()
    if not данные:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл")
    строка = file_store.put(db, сессия.company_id, данные,
                            file_name=file.filename or f"{room}.mp4",
                            mime="video/mp4", purpose="attachment")
    # Файл сначала должен оказаться в базе: без flush SQLAlchemy успевала
    # отправить UPDATE сессии раньше INSERT файла, и запись отбивалась внешним
    # ключом — доставка возвращала 500 при полностью исправном файле.
    await db.flush()
    сессия.recording_file_id = строка.id
    сессия.recording_path = file.filename
    сессия.recording_seconds = seconds or None
    if сессия.ended_at is None:
        # Запись кончилась — значит кончился и конференция.
        сессия.ended_at = datetime.now(timezone.utc)
    # Расшифровка — сразу: протокол нужен, пока разговор свежий, а не
    # когда кто-то вспомнит нажать кнопку.
    сессия.transcript_status, сессия.transcript_error = "queued", None
    сессия.transcript, сессия.protocol = None, None
    await db.commit()
    from app.services import conf_transcribe
    conf_transcribe.поставить(сессия.id)
    return {"session_id": str(сессия.id), "file_id": str(строка.id), "size": len(данные)}


async def _можно_смотреть(db: AsyncSession, s: ConfSession, user: User) -> bool:
    """Запись доступна тем, кого конференция касался.

    Членства в пространстве мало: запись закрытой встречи — это сама встреча,
    только целиком и с голосами. Открыта организатору, приглашённым и тем, кто
    в комнате был.
    """
    if user.is_superadmin:
        return True
    был = (await db.execute(select(ConfPresence.id).where(
        ConfPresence.session_id == s.id,
        ConfPresence.user_id == user.id))).scalar_one_or_none()
    if был is not None or s.started_by == user.id:
        return True
    if s.event_id is None:
        return False
    ev = await db.get(CalendarEvent, s.event_id)
    if ev is None:
        return False
    if ev.organizer_id == user.id:
        return True
    зван = (await db.execute(select(CalendarAttendee.id).where(
        CalendarAttendee.event_id == ev.id,
        CalendarAttendee.user_id == user.id))).scalar_one_or_none()
    return зван is not None


@router.get("/recordings")
async def recordings_list(
    company_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Записи конференций: что можно пересмотреть."""
    cid = await _company(company_id, current_user, db)
    сессии = (await db.execute(select(ConfSession).where(
        ConfSession.company_id == cid, ConfSession.recording_file_id.isnot(None))
        .order_by(ConfSession.started_at.desc()).limit(limit))).scalars().all()
    доступные = [s for s in сессии if await _можно_смотреть(db, s, current_user)]
    люди = await _people(db, {s.started_by for s in доступные if s.started_by})
    админ = await _админ(db, cid, current_user)
    организаторы = {e.id: e.organizer_id for e in (await db.execute(select(CalendarEvent).where(
        CalendarEvent.id.in_([s.event_id for s in доступные if s.event_id])))).scalars()}
    return {"recordings": [{
        "session_id": str(s.id),
        "event_id": str(s.event_id) if s.event_id else None,
        "title": s.title,
        "started_at": s.started_at,
        "seconds": (int((s.ended_at - s.started_at).total_seconds())
                    if s.ended_at else None),
        "recording_seconds": s.recording_seconds,
        "file_url": f"/api/files/{s.recording_file_id}",
        "started_by": (люди.get(s.started_by).name if люди.get(s.started_by) else None),
        "subject_ref": s.subject_ref,
        "can_remove": админ or current_user.id in (s.started_by, организаторы.get(s.event_id)),
        "transcript_status": _состояние(s)[0],
        "has_protocol": bool(s.protocol),
    } for s in доступные]}


@router.post("/recordings/{session_id}/remove")
async def recording_remove(
    session_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Удалить запись конференции: файл с диска и из хранилища.

    Удаляет тот, кто конференцию собрал или назначил, и администратор
    пространства: запись — его разговор, а не общая библиотека. Приглашённый
    смотрит, но не удаляет. Сама конференция остаётся в «Истории» — уходит
    только файл (замечание МАГа 14.10.2026: удалить было нечем).
    """
    from pathlib import Path

    from app.models import SourceFile

    cid = await _company(company_id, current_user, db)
    s = await db.get(ConfSession, _uuid(session_id, "session_id"))
    if s is None or s.company_id != cid or s.recording_file_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    ev = await db.get(CalendarEvent, s.event_id) if s.event_id else None
    if not (await _админ(db, cid, current_user)
            or current_user.id in (s.started_by, ev.organizer_id if ev else None)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Удалить запись может организатор или администратор")
    файл = await db.get(SourceFile, s.recording_file_id)
    s.recording_file_id = None
    s.recording_path = None
    s.recording_seconds = None
    await db.flush()
    путь = файл.storage_path if файл else None
    if файл is not None:
        await db.delete(файл)
    await db.commit()
    if путь:
        Path(путь).unlink(missing_ok=True)
    return {"removed": True}


# ── Расшифровка и протокол ──────────────────────────────────────────────────
# «Дешифратор + протокол с распределением задач» (РусГидро, «ТЗ по СРМ» п. 6).
# Запись → ASR пространства → черновик протокола правилами → человек правит →
# поручения ставятся задачами «Трека» обычной ручкой `POST /api/tasks` из
# интерфейса (маршрут, письмо исполнителю и след у встречи — как у любой задачи),
# протокол рассылается участникам в личный чат.

class ProtocolItemIn(BaseModel):
    kind: str = Field(pattern="^(decision|task)$")
    text: str = Field(min_length=1, max_length=2000)
    at: float | None = None
    assignee_id: str | None = None
    due: str | None = None
    task_id: str | None = None


class ProtocolIn(BaseModel):
    company_id: str
    items: list[ProtocolItemIn] = Field(max_length=200)
    send: bool = False


async def _люди_встречи(db: AsyncSession, s: ConfSession) -> list[User]:
    """Кого касается созвон: позванные на встречу, бывшие в комнате, собравший."""
    ids = {p for p in (await db.execute(select(ConfPresence.user_id).where(
        ConfPresence.session_id == s.id, ConfPresence.user_id.isnot(None)))).scalars()}
    if s.started_by:
        ids.add(s.started_by)
    if s.event_id:
        ev = await db.get(CalendarEvent, s.event_id)
        if ev is not None:
            ids.add(ev.organizer_id)
            ids |= set((await db.execute(select(CalendarAttendee.user_id).where(
                CalendarAttendee.event_id == ev.id))).scalars())
    if not ids:
        return []
    return list((await db.execute(select(User).where(User.id.in_(ids))
                                  .order_by(User.name))).scalars())


async def _запись_для(db: AsyncSession, session_id: str, company_id: str,
                      user: User) -> ConfSession:
    cid = await _company(company_id, user, db)
    s = await db.get(ConfSession, _uuid(session_id, "session_id"))
    if (s is None or s.company_id != cid or s.recording_file_id is None
            or not await _можно_смотреть(db, s, user)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    return s


def _состояние(s: ConfSession) -> tuple[str | None, str | None]:
    """Статус расшифровки с поправкой на перезапуск сервера посреди работы."""
    from app.services import conf_transcribe

    if s.transcript_status in ("queued", "running") and not conf_transcribe.идёт(s.id):
        return "error", "Расшифровка прервалась (перезапуск сервера) — запустите снова"
    return s.transcript_status, s.transcript_error


@router.get("/recordings/{session_id}/transcript")
async def recording_transcript(
    session_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Расшифровка и протокол записи: сохранённый, а пока его нет — черновик."""
    from app.services import conf_protocol, space_time

    s = await _запись_для(db, session_id, company_id, current_user)
    статус, ошибка = _состояние(s)
    люди = await _люди_встречи(db, s)
    пункты, черновик = s.protocol, False
    if пункты is None and статус == "done":
        сегодня = space_time.local_date(datetime.now(timezone.utc), None)
        пункты = conf_protocol.черновик(s.transcript or [],
                                        [(str(u.id), u.name) for u in люди], сегодня)
        черновик = True
    return {
        "session_id": str(s.id), "title": s.title, "event_id": str(s.event_id) if s.event_id else None,
        "status": статус, "error": ошибка,
        "segments": s.transcript or [],
        "protocol": пункты or [], "draft": черновик,
        "people": [{"id": str(u.id), "name": u.name} for u in люди],
    }


@router.post("/recordings/{session_id}/transcribe")
async def recording_transcribe(
    session_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Расшифровать запись (или расшифровать заново после сбоя)."""
    from app.services import conf_transcribe

    s = await _запись_для(db, session_id, company_id, current_user)
    if conf_transcribe.идёт(s.id):
        return {"status": s.transcript_status or "queued"}
    s.transcript_status, s.transcript_error = "queued", None
    await db.commit()
    conf_transcribe.поставить(s.id)
    return {"status": "queued"}


@router.post("/recordings/{session_id}/protocol")
async def recording_protocol(
    session_id: str,
    payload: ProtocolIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сохранить протокол; по `send` — разослать участникам в личный чат.

    Пишет любой, кто имеет доступ к записи, как и заметку: секретаря у
    конференции нет. Пустую заметку встречи протокол заполняет текстом — так
    итог виден в «Истории» без открытия записи.
    """
    from app.services import conf_protocol, meeting_notice

    s = await _запись_для(db, session_id, payload.company_id, current_user)
    люди = await _люди_встречи(db, s)
    свои = {str(u.id) for u in люди}
    пункты = []
    for п in payload.items:
        if п.assignee_id and п.assignee_id not in свои:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Исполнитель должен быть участником встречи")
        пункты.append(п.model_dump())
    s.protocol = пункты
    имена = {str(u.id): u.name for u in люди}
    текст = conf_protocol.текстом(пункты, имена)
    if текст and not (s.note or "").strip():
        s.note = текст
    разослано = 0
    if payload.send and текст:
        for человек in люди:
            if человек.id == current_user.id:
                continue
            try:
                await meeting_notice.в_личку(
                    db, s.company_id, current_user, человек,
                    f"📝 Протокол: {s.title}\n{текст}", f"Протокол: {s.title}")
                разослано += 1
            except Exception:
                pass
    await db.commit()
    return {"saved": len(пункты), "sent": разослано}


async def authorize_conf_recording_download(db: AsyncSession, user: User,
                                            file_id: uuid.UUID) -> None:
    """Проверка при скачивании записи по прямой ссылке.

    Адрес файла легко переслать, а в записи звучит весь конференция — правило то же,
    что у карточки: организатор, приглашённые и бывшие в комнате.
    """
    сессии = (await db.execute(select(ConfSession).where(
        ConfSession.recording_file_id == file_id))).scalars().all()
    for s in сессии:
        if await _можно_смотреть(db, s, user):
            return
    if сессии:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")


# ── Статистика ──────────────────────────────────────────────────────────────
@router.get("/stats")
async def conf_stats(
    company_id: str = Query(...),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сколько созванивались: по людям и по предметам.

    Считаем по состоявшимся конференциим, а не по назначенным встречам: назначить
    можно что угодно, а конференция либо был, либо нет.
    """
    cid = await _company(company_id, current_user, db)
    начало = datetime.now(timezone.utc) - timedelta(days=days)
    сессии = (await db.execute(select(ConfSession).where(
        ConfSession.company_id == cid,
        ConfSession.started_at >= начало))).scalars().all()
    if not сессии:
        return {"days": days, "total": 0, "seconds": 0, "with_recording": 0,
                "unmeasured": 0, "people": [], "subjects": []}

    присутствие = (await db.execute(select(ConfPresence).where(
        ConfPresence.session_id.in_([s.id for s in сессии])))).scalars().all()
    люди = await _people(db, {p.user_id for p in присутствие})

    # Длительность знаем не у всех: у конференции, закрытой по сроку, конец
    # поставлен нами по правилу, а не по тому, когда люди разошлись. Считать
    # такое временем разговора — врать в разы (полтора часа вместо трёх минут),
    # поэтому в сумму идут только измеренные: закрытые человеком и записанные.
    def измерено(s: ConfSession) -> int | None:
        if s.recording_seconds:
            return s.recording_seconds
        if s.ended_at and s.close_reason != "auto":
            return int((s.ended_at - s.started_at).total_seconds())
        return None

    длительности = {s.id: (измерено(s) or 0) for s in сессии}
    без_замера = sum(1 for s in сессии if измерено(s) is None)
    по_людям: dict[uuid.UUID, dict[str, int]] = {}
    for p in присутствие:
        строка = по_людям.setdefault(p.user_id, {"meetings": 0, "seconds": 0})
        строка["meetings"] += 1
        строка["seconds"] += длительности.get(p.session_id, 0)

    по_предметам: dict[str, dict[str, Any]] = {}
    for s in сессии:
        строка = по_предметам.setdefault(s.subject_ref or "", {"meetings": 0, "seconds": 0})
        строка["meetings"] += 1
        строка["seconds"] += длительности.get(s.id, 0)

    return {
        "days": days,
        "total": len(сессии),
        "seconds": sum(длительности.values()),
        "with_recording": sum(1 for s in сессии if s.recording_file_id),
        # Сколько конференций осталось без измеренного времени: их длительность
        # в сумму не вошла, и человек должен знать, почему сумма меньше ожидаемой.
        "unmeasured": без_замера,
        "people": sorted(({"user_id": str(uid),
                           "name": (люди.get(uid).name if люди.get(uid) else "—"),
                           **знач} for uid, знач in по_людям.items()),
                         key=lambda r: (-r["seconds"], -r["meetings"])),
        "subjects": sorted(({"subject_ref": ключ, **знач}
                            for ключ, знач in по_предметам.items()),
                           key=lambda r: (-r["seconds"], -r["meetings"])),
    }


# ── Постоянные комнаты ──────────────────────────────────────────────────────
#
# Комната — это место, а не событие: «Оперативка», «Переговорная», «Дежурная».
# Заходят без приглашения и без назначения встречи. Ведущим входит каждый:
# у места нет организатора, а комната, которую некому открыть, бесполезна.
@router.get("/rooms")
async def rooms_list(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Постоянные комнаты пространства и кто в них сейчас."""
    cid = await _company(company_id, current_user, db)
    await _закрыть_брошенные(db, cid)
    комнаты = (await db.execute(select(ConfRoom).where(
        ConfRoom.company_id == cid, ConfRoom.archived_at.is_(None))
        .order_by(ConfRoom.sort, ConfRoom.name))).scalars().all()
    сессии = (await db.execute(select(ConfSession).where(
        ConfSession.company_id == cid, ConfSession.ended_at.is_(None),
        ConfSession.conf_room_id.isnot(None)))).scalars().all()
    присутствие = []
    if сессии:
        присутствие = (await db.execute(select(ConfPresence).where(
            ConfPresence.session_id.in_([s.id for s in сессии])))).scalars().all()
    люди = await _people(db, {p.user_id for p in присутствие})
    по_комнате = {s.conf_room_id: s for s in сессии}
    сейчас = datetime.now(timezone.utc)
    return {"rooms": [{
        "id": str(к.id),
        "name": к.name,
        "purpose": к.purpose,
        "guest_url": f"https://{settings.jitsi_domain}/{jitsi.room_for(f'room:{к.id}')}",
        "live": к.id in по_комнате,
        # Только те, кто сейчас в комнате: вышедшие и замолчавшие вкладки не в
        # счёт. «Кто входил» — это история созвона, а не список присутствующих.
        "inside": [{
            "user_id": str(p.user_id),
            "name": (люди.get(p.user_id).name if люди.get(p.user_id) else "—"),
        } for p in присутствие
            if по_комнате.get(к.id) and p.session_id == по_комнате[к.id].id
            and _в_комнате(p, сейчас)],
        "since": (по_комнате[к.id].started_at if к.id in по_комнате else None),
    } for к in комнаты], "can_manage": await _админ(db, cid, current_user)}


async def _админ(db: AsyncSession, cid: uuid.UUID, user: User) -> bool:
    """Комнаты заводит администратор ПРОСТРАНСТВА: комната — часть его состава,
    а не личная запись. Роль смотрим по членству в компании, а не по глобальному
    полю: в одном пространстве человек администратор, в соседнем — обычный."""
    if user.is_superadmin:
        return True
    роль = (await db.execute(select(UserCompany.role).where(
        UserCompany.company_id == cid,
        UserCompany.user_id == user.id))).scalar_one_or_none()
    return роль == "admin"


@router.post("/rooms", status_code=status.HTTP_201_CREATED)
async def room_create(
    payload: RoomIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Завести постоянную комнату."""
    cid = await _company(payload.company_id, current_user, db)
    if not await _админ(db, cid, current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Заводить комнаты может администратор пространства")
    к = ConfRoom(company_id=cid, name=payload.name.strip(),
                 purpose=(payload.purpose or "").strip() or None,
                 created_by=current_user.id)
    db.add(к)
    await db.commit()
    await db.refresh(к)
    return {"id": str(к.id), "name": к.name, "purpose": к.purpose,
            "guest_url": f"https://{settings.jitsi_domain}/{jitsi.room_for(f'room:{к.id}')}",
            "live": False, "inside": [], "since": None}


@router.post("/rooms/{room_id}/archive")
async def room_archive(
    room_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Убрать комнату из списка.

    Не удаляем: в журнале остались разговоры, которые в ней прошли, и строка
    без имени комнаты читалась бы как потерянная.
    """
    cid = await _company(company_id, current_user, db)
    if not await _админ(db, cid, current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Убирать комнаты может администратор пространства")
    к = await db.get(ConfRoom, _uuid(room_id, "room_id"))
    if к is None or к.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната не найдена")
    к.archived_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": str(к.id), "archived": True}


@router.post("/rooms/{room_id}/join")
async def room_join(
    room_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Войти в постоянную комнату.

    Ведущим входит каждый: у места нет организатора, и комната, которую некому
    открыть, никому не нужна. Разговор в ней попадает в журнал так же, как
    назначенная конференция, — иначе половина разговоров компании нигде не
    останется.
    """
    if not settings.jitsi_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Конференции не настроены")
    cid = await _company(company_id, current_user, db)
    к = await db.get(ConfRoom, _uuid(room_id, "room_id"))
    if к is None or к.company_id != cid or к.archived_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната не найдена")

    room = jitsi.room_for(f"room:{к.id}")
    urls = jitsi.meeting_urls(room, current_user.name, subject=к.name)
    сессия = (await db.execute(select(ConfSession).where(
        ConfSession.conf_room_id == к.id,
        ConfSession.ended_at.is_(None)))).scalar_one_or_none()
    if сессия is None:
        сессия = ConfSession(company_id=cid, conf_room_id=к.id, room=room,
                             title=к.name, started_by=current_user.id)
        db.add(сессия)
        await db.flush()
    await _отметить_приход(db, сессия, current_user)
    await db.commit()
    return {**urls, "session_id": str(сессия.id), "moderator": True}
