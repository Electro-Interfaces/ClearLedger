"""«Принять» из VK, Outlook, Яндекса доходит до календаря пространства (28.10.2026).

Приглашение уходит с организатором — ящиком ответов; почтовая программа шлёт
туда `METHOD:REPLY`, а пространство ставит ответ тому, кто его дал, и только
ему: адрес в файле должен совпасть с отправителем и быть позван на встречу.
"""
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.models import CalendarAttendee, CalendarGuest, Company, User, UserCompany
from app.services import calendar_replies
from app.services.ics import event_ics


def _ответ(uid: str, кто: str, partstat: str, *, от: str | None = None,
           comment: str | None = None, stamp: datetime | None = None) -> bytes:
    """Письмо-ответ, как его шлёт Outlook: часть text/calendar; method=REPLY,
    строки сложены продолжением."""
    stamp = stamp or datetime.now(timezone.utc)
    строки = [
        "BEGIN:VCALENDAR", "PRODID:Microsoft Exchange Server 2010", "VERSION:2.0",
        "METHOD:REPLY", "BEGIN:VEVENT",
        f'ATTENDEE;PARTSTAT={partstat};CN="Тестовый,\r\n  Участник":MAILTO:{кто.upper()}',
        *([f"COMMENT;LANGUAGE=ru-RU:{comment}"] if comment else []),
        f"UID:{uid}", "SEQUENCE:1761600000",
        f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}", "END:VEVENT", "END:VCALENDAR", ""]
    msg = EmailMessage()
    msg["From"] = f"Тестовый Участник <{от or кто}>"
    msg["To"] = "rushydro-calendar@dataworker.ru"
    msg["Subject"] = "Принято: Планёрка"
    msg["Date"] = stamp.strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.set_content("Принято")
    msg.add_attachment("\r\n".join(строки).encode("utf-8"), maintype="text",
                       subtype="calendar", params={"method": "REPLY"})
    return msg.as_bytes()


def test_разбор_ответа_outlook():
    raw = _ответ("abc@trek", "ivanov@example.test", "TENTATIVE", comment="Опоздаю\\, на 10 минут")
    import email
    texts = calendar_replies._calendar_texts(email.message_from_bytes(raw))
    [r] = calendar_replies.parse_reply(texts[0])
    assert r["uid"] == "abc@trek" and r["email"] == "ivanov@example.test"
    assert r["response"] == "tentative" and r["comment"] == "Опоздаю, на 10 минут"


def test_приглашение_и_отмена_не_ответ():
    assert calendar_replies.parse_reply("BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\n"
                                        "UID:a@trek\r\nATTENDEE;PARTSTAT=ACCEPTED:mailto:a@b\r\n"
                                        "END:VEVENT\r\nEND:VCALENDAR") == []


def test_организатор_в_приглашении_ящик_ответов(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "calendar_reply_mailbox", "rushydro-calendar@dataworker.ru")
    t = datetime(2026, 11, 2, 7, tzinfo=timezone.utc)
    приглашение = event_ics(uid="e@trek", title="Планёрка", starts_at=t, ends_at=t + timedelta(hours=1),
                            organizer_email="boss@rushydro.ru", organizer_name="Михеев А.Г.",
                            attendees=[("a@b.ru", None)], invite=True)
    assert "ORGANIZER;CN=Михеев А.Г.:mailto:rushydro-calendar@dataworker.ru" in приглашение
    # Лента подписки и выгрузка (PUBLISH) — с хозяином: на них не отвечают.
    выгрузка = event_ics(uid="e@trek", title="Планёрка", starts_at=t, ends_at=t + timedelta(hours=1),
                         organizer_email="boss@rushydro.ru", organizer_name="Михеев А.Г.")
    assert "mailto:boss@rushydro.ru" in выгрузка
    monkeypatch.setattr(settings, "calendar_reply_mailbox", "")
    assert "mailto:boss@rushydro.ru" in event_ics(
        uid="e@trek", title="Планёрка", starts_at=t, ends_at=t + timedelta(hours=1),
        organizer_email="boss@rushydro.ru", invite=True), "без ящика — как было"


async def _встреча(db):
    from app.routers.work_router import EventIn, calendar_create
    company = await db.scalar(select(Company).limit(1))
    хозяин = await db.scalar(select(User).where(User.email == 'admin@clearledger.ru'))
    await db.merge(UserCompany(company_id=company.id, user_id=хозяин.id, role='admin'))
    зван = User(email=f'reply-{uuid.uuid4()}@example.test', name='Позванный',
                password_hash='!test', company_id=company.id)
    db.add(зван)
    await db.flush()
    db.add(UserCompany(company_id=company.id, user_id=зван.id, role='user'))
    await db.flush()
    t = (datetime.now(timezone.utc) + timedelta(days=4)).replace(minute=0, second=0, microsecond=0)
    ev = await calendar_create(EventIn(company_id=str(company.id), title='Планёрка', starts_at=t,
                                       ends_at=t + timedelta(hours=1), attendee_ids=[str(зван.id)]),
                               db=db, current_user=хозяин)
    гость = CalendarGuest(event_id=uuid.UUID(ev['id']), email=f'guest-{uuid.uuid4()}@partner.test',
                          token_hash='y' * 64, token_prefix='y' * 8, expires_at=t + timedelta(days=1))
    db.add(гость)
    await db.flush()
    return ev, зван, гость


async def _ответ_у(db, ev_id, user_id):
    return (await db.execute(select(CalendarAttendee).where(
        CalendarAttendee.event_id == uuid.UUID(ev_id),
        CalendarAttendee.user_id == user_id))).scalar_one()


@pytest.mark.asyncio(loop_scope='session')
async def test_принять_из_почты_ставит_ответ_сотруднику_и_гостю(db, monkeypatch):
    from app.services import email_service

    async def не_слать(*_, **__):
        return True
    monkeypatch.setattr(email_service, 'send_meeting_invite', не_слать)
    ev, зван, гость = await _встреча(db)

    await calendar_replies.apply_message(db, _ответ(f"{ev['id']}@trek", зван.email, "ACCEPTED"))
    assert (await _ответ_у(db, ev['id'], зван.id)).response == 'accepted'

    # UID конференции — тот же id встречи с другим хвостом.
    await calendar_replies.apply_message(
        db, _ответ(f"{ev['id']}@conf.elsyplus", гость.email, "DECLINED", comment="В отпуске"))
    await db.flush()
    await db.refresh(гость)
    assert гость.response == 'declined' and гость.comment == 'В отпуске'


@pytest.mark.asyncio(loop_scope='session')
async def test_за_другого_не_ответить_и_позднее_не_перебить(db, monkeypatch):
    from app.services import email_service

    async def не_слать(*_, **__):
        return True
    monkeypatch.setattr(email_service, 'send_meeting_invite', не_слать)
    ev, зван, гость = await _встреча(db)

    # Письмо от гостя с ответом за сотрудника — чужое слово.
    исход = await calendar_replies.apply_message(
        db, _ответ(f"{ev['id']}@trek", зван.email, "DECLINED", от=гость.email))
    assert (await _ответ_у(db, ev['id'], зван.id)).response == 'pending', исход

    # Незваный адрес — не участник.
    исход = await calendar_replies.apply_message(
        db, _ответ(f"{ev['id']}@trek", "stranger@evil.test", "ACCEPTED"))
    assert 'не позван' in исход[0]

    # Ответил в пространстве «Не смогу», потом дошло старое письмо «Принять».
    у = await _ответ_у(db, ev['id'], зван.id)
    у.response, у.responded_at = 'declined', datetime.now(timezone.utc)
    await db.flush()
    await calendar_replies.apply_message(
        db, _ответ(f"{ev['id']}@trek", зван.email, "ACCEPTED",
                   stamp=datetime.now(timezone.utc) - timedelta(hours=1)))
    assert (await _ответ_у(db, ev['id'], зван.id)).response == 'declined'
