"""Извещения участникам встречи: в личный чат, письмом с календарным файлом.

Приглашение уходило и раньше, а отмена и перенос — нет: встреча исчезала или
съезжала молча, и люди приходили в пустую комнату (замечание РусГидро
14.10.2026, «ТЗ по СРМ», пп. 2–3). Здесь одна точка, через которую идут все три
повода: позвать, отменить, перенести.

Календарный файл идёт с тем же `UID`, что у приглашения, и с растущим
`SEQUENCE`: так Outlook и Gmail сами убирают или переставляют встречу у
получателя, а не заводят рядом вторую.

Ошибки доставки глотаем: почта и чат живут отдельно от встречи, и лежащий
почтовый сервер не должен откатывать отмену, которую человек уже сделал.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (CalendarAttendee, CalendarEvent, CalendarGuest, ChatMessage,
                        ChatParticipant, ChatRoom, User)

log = logging.getLogger(__name__)


def uid_встречи(ev: CalendarEvent) -> str:
    """UID календарного файла — тот же, с которым ушло приглашение.

    Конференцию зовут из «Конференций» (`@conf.elsyplus`), обычную встречу —
    из календаря (`@trek`). Отмена с другим UID оставила бы у человека обе.
    """
    своя_комната = bool(ev.conference_url and re.search(r"/ledger-[0-9a-f]+", ev.conference_url))
    return f"{ev.id}@conf.elsyplus" if своя_комната else f"{ev.id}@trek"


def _sequence() -> int:
    """Номер версии встречи для календаря получателя: только растёт.

    Минуты от эпохи: хранить счётчик правок ради одного числа незачем, а
    следующая правка всегда получает номер больше предыдущей.
    """
    return int(datetime.now(timezone.utc).timestamp() // 60)


async def в_личку(db: AsyncSession, company_id, от: User, кому: User,
                  текст: str, заголовок: str) -> bool:
    """Строка в личную переписку двоих и push закрытой вкладке.

    Комната ищется по участникам, а не по имени: переименование не должно
    заводить вторую. Пишем от того, кто действует, а не от «Секретаря» —
    человек ищет такие вещи в разговоре с коллегой (МАГ, 10.09.2026).
    """
    from app.services import web_push

    мои = select(ChatParticipant.room_id).where(ChatParticipant.user_id == от.id)
    его = select(ChatParticipant.room_id).where(ChatParticipant.user_id == кому.id)
    комната = (await db.execute(select(ChatRoom).where(
        ChatRoom.company_id == company_id, ChatRoom.type == "direct",
        ChatRoom.is_active.is_(True),
        ChatRoom.id.in_(мои), ChatRoom.id.in_(его)).limit(1))).scalar_one_or_none()
    if комната is None:
        комната = ChatRoom(company_id=company_id, type="direct", created_by=от.id)
        db.add(комната)
        await db.flush()
        db.add_all([ChatParticipant(room_id=комната.id, user_id=от.id),
                    ChatParticipant(room_id=комната.id, user_id=кому.id)])
        await db.flush()
    db.add(ChatMessage(room_id=комната.id, user_id=от.id, user_name=от.name,
                       type="text", content=текст))
    await db.flush()
    try:
        web_push.push_room_async(комната.id, от.name, заголовок, от.id)
    except Exception:
        pass
    return True


def _когда(ev: CalendarEvent, starts_at: datetime | None = None) -> str:
    from app.services import space_time

    момент = space_time.as_utc(starts_at or ev.starts_at).astimezone(space_time.zone(ev.tz))
    return момент.strftime("%d.%m.%Y в %H:%M")


async def известить(db: AsyncSession, ev: CalendarEvent, кто: User, повод: str,
                    было: datetime | None = None, только: set | None = None,
                    кроме: set | None = None) -> dict[str, int]:
    """Сообщить участникам, что их позвали, встречу отменили или перенесли.

    `повод` — `invite`, `cancel` или `move`; для переноса `было` — прежнее
    начало. `только` — известить лишь этих людей (новые участники), `кроме` —
    всех, кроме них. Гостям приглашение уходит своим путём (`/guests`), здесь
    они получают только отмену и перенос. Тот, кто действует, извещение себе
    не получает: он и так знает.
    """
    from app.services import email_service, ics

    отмена = повод == "cancel"
    когда = _когда(ev)
    if повод == "invite":
        тема = f"Приглашение: {ev.title} — {когда}"
        строка = (f"{кто.name} зовёт на встречу «{ev.title}» {когда}."
                  + (f"\nГде: {ev.location}" if ev.location else "")
                  + (f"\nСсылка на видеовстречу: {ev.conference_url}" if ev.conference_url else ""))
    elif отмена:
        тема = f"Отменено: {ev.title} — {когда}"
        строка = (f"Встреча «{ev.title}» {когда} отменена"
                  + (f": {ev.cancel_reason}" if ev.cancel_reason else "") + ".")
    else:
        тема = f"Перенесено: {ev.title} — {когда}"
        строка = (f"Встреча «{ev.title}» перенесена"
                  + (f" с {_когда(ev, было)}" if было else "") + f" на {когда}."
                  + (f"\nСсылка: {ev.conference_url}" if ev.conference_url else ""))

    люди = (await db.execute(select(User).join(
        CalendarAttendee, CalendarAttendee.user_id == User.id).where(
        CalendarAttendee.event_id == ev.id, User.id != кто.id))).scalars().all()
    люди = [ч for ч in люди if (только is None or ч.id in только)
            and not (кроме and ч.id in кроме)]
    гости = [] if повод == "invite" else (await db.execute(select(CalendarGuest).where(
        CalendarGuest.event_id == ev.id))).scalars().all()

    свои = [(ч.email, ч.name) for ч in люди if ч.email]
    чужие = [(г.email, г.name) for г in гости]
    номер = _sequence()

    def файл(uid: str, кому: list[tuple[str, str | None]]) -> str:
        return ics.event_ics(
            uid=uid, title=ev.title, starts_at=ev.starts_at, ends_at=ev.ends_at,
            description=ev.description, location=ev.location, url=ev.conference_url,
            organizer_email=кто.email, organizer_name=кто.name,
            attendees=кому, invite=not отмена, cancelled=отмена, sequence=номер)

    # Гостю приглашение всегда уходило с `@trek` (`_письмо_гостю`), людям
    # пространства на конференцию — с `@conf.elsyplus`: каждому — свой UID.
    адреса = ([(почта, файл(uid_встречи(ev), свои)) for почта, _ in свои]
              + [(почта, файл(f"{ev.id}@trek", чужие)) for почта, _ in чужие])
    html = (f'<div style="font-family:system-ui,sans-serif;line-height:1.5">'
            f'<p style="font-size:16px"><b>{ev.title}</b></p><p>'
            + строка.replace("\n", "<br>") + "</p></div>")

    чатом = письмом = 0
    for человек in люди:
        try:
            значок = "📅 " if повод == "invite" else "❌ " if отмена else "🕑 "
            await в_личку(db, ev.company_id, кто, человек, значок + строка, тема)
            чатом += 1
        except Exception:
            log.warning("Извещение в чат %s по встрече %s не ушло", человек.id, ev.id,
                        exc_info=True)
    for почта, вложение in адреса:
        try:
            if await email_service.send_meeting_invite(
                    почта, subject=тема, text=строка, html=html, ics=вложение,
                    method="CANCEL" if отмена else "REQUEST"):
                письмом += 1
        except Exception:
            log.warning("Письмо %s по встрече %s не ушло", почта, ev.id, exc_info=True)
    return {"chatted": чатом, "mailed": письмом}
