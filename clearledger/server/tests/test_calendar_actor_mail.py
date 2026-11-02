"""Действующий участник тоже получает обновление своего почтового календаря.

Только отдельная TEST_DATABASE_URL: общий conftest пересоздаёт схемы.
SMTP перехвачен до сети; проверяем настоящий MIME и оба вложения ICS.
"""
import base64
import uuid
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import delete, select

from app.config import settings
from app.models import CalendarAttendee, CalendarDelegate, CalendarEvent, Company, User, UserCompany
from app.routers import conf_router, work_router
from app.services import meeting_notice

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def delivery(monkeypatch):
    import aiosmtplib

    messages, chats = [], []
    # Исторический clock seam сохранён для characterization. Нативная версия
    # теперь живёт в строке; same-second покрывает test_calendar_protocol_version.
    clock = [1793400000]
    monkeypatch.setattr(meeting_notice, "_sequence", lambda: clock[0], raising=False)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_from", "Calendar <calendar@example.test>")
    monkeypatch.setattr(settings, "calendar_reply_mailbox", "replies@example.test")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    monkeypatch.setattr(settings, "jitsi_signing_key", base64.b64encode(pem).decode())

    async def smtp(message, **kwargs):
        # Сервис глотает ошибки SMTP: записываем попытку до проверок, чтобы
        # неожиданный адрес не спрятался за обработчиком исключений.
        messages.append(BytesParser(policy=policy.default).parsebytes(message.as_bytes()))
        assert kwargs["hostname"] == "smtp.example.test"
        assert str(message["To"]).endswith("@example.test")
        return {}, "captured"

    async def chat(db, company_id, sender, recipient, text, title):
        chats.append((sender.id, recipient.id))
        return True

    monkeypatch.setattr(aiosmtplib, "send", smtp)
    monkeypatch.setattr(meeting_notice, "в_личку", chat)
    return messages, chats, clock


async def scenario(db, conference, created_by_delegate=False):
    company = await db.scalar(select(Company).where(Company.slug == "rushydro"))
    people = [User(email=f"{role}-{uuid.uuid4()}@example.test", name=role,
                   password_hash="!test", company_id=company.id, email_notify=["meeting"])
              for role in ("Organizer", "Assistant", "Attendee")]
    db.add_all(people)
    await db.flush()
    owner, assistant, attendee = people
    db.add_all([UserCompany(company_id=company.id, user_id=p.id, role="admin") for p in people])
    db.add(CalendarDelegate(company_id=company.id, owner_id=owner.id,
                            delegate_id=assistant.id, created_by=owner.id))
    await db.flush()
    start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
    if conference:
        event = await conf_router.meeting_create(conf_router.MeetingIn(
            company_id=str(company.id), title="Calendar update regression",
            starts_at=start, attendee_ids=[str(assistant.id), str(attendee.id)],
            email_copy=True), db=db, current_user=owner)
    else:
        event = await work_router.calendar_create(work_router.EventIn(
            company_id=str(company.id), title="Calendar update regression",
            starts_at=start, ends_at=start + timedelta(hours=1),
            attendee_ids=[str(assistant.id), str(attendee.id)],
            on_behalf_of=str(owner.id) if created_by_delegate else None),
            db=db, current_user=assistant if created_by_delegate else owner)
    return company, owner, assistant, attendee, event, start


def calendar_part(message, method, recipient, uid, start, owner):
    parts = [p for p in message.walk() if p.get_content_type() == "text/calendar"]
    assert len(parts) == 2, "нужны календарная часть тела и файл invite.ics"
    calendars = []
    for part in parts:
        assert part.get_param("method") == method
        text = part.get_payload(decode=True).decode("utf-8").replace("\r\n", "\n").replace("\n ", "")
        assert f"METHOD:{method}" in text
        assert f"UID:{uid}" in text
        assert f"DTSTART:{start:%Y%m%dT%H%M%SZ}" in text
        assert f"DTEND:{start + timedelta(hours=1):%Y%m%dT%H%M%SZ}" in text
        assert f"ORGANIZER;CN={owner.name}:mailto:replies@example.test" in text
        assert any(line.startswith("ATTENDEE;") and line.endswith(f"mailto:{recipient}")
                   for line in text.splitlines())
        assert f"STATUS:{'CANCELLED' if method == 'CANCEL' else 'CONFIRMED'}" in text
        calendars.append(text)
    assert calendars[0] == calendars[1]
    assert parts[1].get_filename() == "invite.ics"
    return int(next(line.split(":", 1)[1] for line in calendars[0].splitlines()
                    if line.startswith("SEQUENCE:")))


@pytest.mark.parametrize("conference", [False, True], ids=["meeting", "conference"])
@pytest.mark.parametrize("actor", ["organizer", "assistant"])
async def test_actor_gets_two_moves_and_cancel(db, delivery, conference, actor):
    messages, chats, clock = delivery
    company, owner, assistant, attendee, event, start = await scenario(db, conference)
    acting = owner if actor == "organizer" else assistant
    uid = f"{event['id']}@{'conf.elsyplus' if conference else 'trek'}"
    initial = next(m for m in messages if str(m["To"]) == attendee.email)
    previous = calendar_part(initial, "REQUEST", attendee.email, uid, start, owner)
    # Организатор мог добавить исходную встречу файлом вместо приглашения.
    exported = await work_router.calendar_ics(
        event["id"], company_id=str(company.id), db=db, current_user=owner)
    assert f"UID:{uid}" in exported.body.decode()

    # Внешний гость остаётся со своим прежним @trek UID даже у конференции.
    guest_email = f"guest-{uuid.uuid4()}@example.test"
    await work_router.guest_invite(event["id"], work_router.GuestIn(
        company_id=str(company.id), email=guest_email), db=db, current_user=owner)

    for shift, method in [(1, "REQUEST"), (2, "REQUEST"), (2, "CANCEL")]:
        messages.clear()
        chats.clear()
        clock[0] += 1
        moved = start + timedelta(hours=shift)
        change = ({"cancel": True, "cancel_reason": "Test cancellation"} if method == "CANCEL"
                  else {"starts_at": moved, "ends_at": moved + timedelta(hours=1)})
        result = await work_router.calendar_action(event["id"], work_router.EventAction(
            company_id=str(company.id), **change), db=db, current_user=acting)
        assert result["status"] == ("cancelled" if method == "CANCEL" else "planned")
        recipients = {str(m["To"]) for m in messages}
        assert acting.email in recipients, "действующий участник не получил обновление VK"
        assert recipients == {owner.email, assistant.email, attendee.email, guest_email}
        for message in messages:
            recipient = str(message["To"])
            target_uid = f"{event['id']}@trek" if recipient == guest_email else uid
            sequence = calendar_part(message, method, recipient, target_uid, moved, owner)
            assert sequence > previous
        previous = sequence
        assert all(sender != recipient for sender, recipient in chats), "не нужен чат с собой"
        assert {recipient for _, recipient in chats} == {p.id for p in (owner, assistant, attendee)
                                                         if p.id != acting.id}


@pytest.mark.parametrize("created_by_delegate", [False, True], ids=["owner", "assistant"])
async def test_invite_reaches_actor_and_opt_out_is_respected(db, delivery, created_by_delegate):
    messages, chats, clock = delivery
    company, owner, assistant, attendee, event, start = await scenario(
        db, False, created_by_delegate=created_by_delegate)
    actor = assistant if created_by_delegate else owner
    assert {str(m["To"]) for m in messages} == {owner.email, assistant.email, attendee.email}
    assert all(sender != recipient for sender, recipient in chats)
    actor.email_notify = ["digest"]
    await db.commit()
    for cancel in (False, True):
        messages.clear()
        chats.clear()
        clock[0] += 1
        change = ({"cancel": True, "cancel_reason": "Test"} if cancel else {
            "starts_at": start + timedelta(hours=1), "ends_at": start + timedelta(hours=2)})
        await work_router.calendar_action(event["id"], work_router.EventAction(
            company_id=str(company.id), **change), db=db, current_user=actor)
        assert {str(m["To"]) for m in messages} == {p.email for p in (owner, assistant, attendee)
                                                   if p.id != actor.id}
        assert all(sender != recipient for sender, recipient in chats)


async def test_actor_still_obeys_recipient_filters(db, delivery):
    messages, chats, _ = delivery
    _, owner, assistant, attendee, event, _ = await scenario(db, False)
    ev = await db.get(CalendarEvent, uuid.UUID(event["id"]))
    messages.clear()
    chats.clear()
    result = await meeting_notice.известить(db, ev, assistant, "invite", только={assistant.id})
    assert result == {"mailed": 1, "chatted": 0}
    assert [str(m["To"]) for m in messages] == [assistant.email]
    messages.clear()
    await meeting_notice.известить(db, ev, assistant, "move", кроме={assistant.id})
    assert {str(m["To"]) for m in messages} == {owner.email, attendee.email}


@pytest.mark.parametrize("preferences,mail_only,expected", [
    (None, False, True), ([], False, False), ([], True, True),
], ids=["default", "disabled", "mail-only"])
async def test_actor_mail_preferences(db, delivery, preferences, mail_only, expected):
    messages, chats, _ = delivery
    _, owner, assistant, attendee, event, _ = await scenario(db, False)
    owner.email_notify, owner.mail_only = preferences, mail_only
    await db.flush()
    ev = await db.get(CalendarEvent, uuid.UUID(event["id"]))
    messages.clear()
    chats.clear()
    await meeting_notice.известить(db, ev, owner, "move")
    recipients = {str(m["To"]) for m in messages}
    assert (owner.email in recipients) is expected
    assert {assistant.email, attendee.email} <= recipients
    assert all(sender != recipient for sender, recipient in chats)


async def test_delegate_outside_attendees_is_not_added_to_mail(db, delivery):
    messages, chats, _ = delivery
    _, owner, assistant, attendee, event, _ = await scenario(db, False)
    ev = await db.get(CalendarEvent, uuid.UUID(event["id"]))
    await db.execute(delete(CalendarAttendee).where(
        CalendarAttendee.event_id == ev.id, CalendarAttendee.user_id == assistant.id))
    await db.flush()
    messages.clear()
    chats.clear()
    await meeting_notice.известить(db, ev, assistant, "move")
    assert {str(m["To"]) for m in messages} == {owner.email, attendee.email}
    assert {recipient for _, recipient in chats} == {owner.id, attendee.id}
