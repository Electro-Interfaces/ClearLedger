"""Actual CalendarEvent transactions and MIME, ROOT-only disposable database.

The clock stays in one second. The organizer revision belongs to stored state;
terminal SMTP/chat/conference delivery is captured before imports by the runner.
"""
import asyncio
import base64
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
import uuid

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import delete, select

from app.auth import get_current_user
from app.config import settings
from app.main import app
from app.models import (CalendarAttendee, CalendarDelegate, CalendarEvent, CalendarGuest,
                        Company, ConfSession, User, UserCompany)
from app.routers import conf_router, invite_router, work_router
from app.services import calendar_protocol, calendar_series, ics, meeting_notice
from tests.test_calendar_actor_mail import calendar_part

pytestmark = pytest.mark.asyncio(loop_scope="session")
NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)


class Clock(datetime):
    instant = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz is not None else cls.instant.replace(tzinfo=None)


@pytest_asyncio.fixture(loop_scope="session")
async def world(db, client, monkeypatch):
    import aiosmtplib
    from tests.conftest import _test_session_factory

    company = await db.scalar(select(Company).where(Company.slug == "rushydro"))
    other = await db.scalar(select(Company).where(Company.slug == "gig"))
    people = [User(email=f"revision-{name}-{uuid.uuid4()}@example.test", name=name,
                   password_hash="!synthetic", company_id=cid, role="user", email_notify=["meeting"])
              for name, cid in (("Owner", company.id), ("Assistant", company.id),
                                ("Attendee", company.id), ("Foreign", other.id))]
    db.add_all(people)
    await db.flush()
    owner, assistant, attendee, foreign = people
    db.add_all([UserCompany(user_id=p.id, company_id=p.company_id, role="admin") for p in people])
    db.add(CalendarDelegate(company_id=company.id, owner_id=owner.id,
                            delegate_id=assistant.id, created_by=owner.id))
    await db.commit()
    result = SimpleNamespace(db=db, client=client, company=company, other=other,
                             owner=owner, assistant=assistant, attendee=attendee, foreign=foreign,
                             messages=[], chats=[], factory=_test_session_factory, actor=owner)
    previous = app.dependency_overrides.get(get_current_user)

    async def actor():
        return result.actor

    async def smtp(message, **kwargs):
        assert kwargs["hostname"] == "smtp.example.test"
        parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
        assert str(parsed["To"]).endswith("@example.test")
        result.messages.append(parsed)
        return {}, "captured"

    async def chat(_db, _cid, sender, recipient, _text, _title):
        result.chats.append((sender.id, recipient.id))
        return True

    async def close_room(*args, **kwargs):
        return True

    app.dependency_overrides[get_current_user] = actor
    monkeypatch.setattr(aiosmtplib, "send", smtp)
    monkeypatch.setattr(meeting_notice, "в_личку", chat)
    monkeypatch.setattr(conf_router, "_закрыть_комнату", close_room)
    for module in (work_router, conf_router, ics):
        monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(Clock, "instant", NOW)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_from", "Calendar <calendar@example.test>")
    monkeypatch.setattr(settings, "calendar_reply_mailbox", "replies@example.test")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    monkeypatch.setattr(settings, "jitsi_signing_key", base64.b64encode(pem).decode())
    try:
        yield result
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous


async def create(w, *, conference=False, series=False, attendees=None):
    start = NOW + timedelta(days=3)
    ids = attendees if attendees is not None else [str(w.assistant.id), str(w.attendee.id)]
    if conference:
        event = await conf_router.meeting_create(conf_router.MeetingIn(
            company_id=str(w.company.id), title="Protocol revision", starts_at=start,
            attendee_ids=ids, email_copy=True), db=w.db, current_user=w.owner)
    else:
        event = await work_router.calendar_create(work_router.EventIn(
            company_id=str(w.company.id), title="Protocol revision", starts_at=start,
            ends_at=start + timedelta(hours=1), attendee_ids=ids,
            recurrence={"mode": "weekly"} if series else None), db=w.db, current_user=w.owner)
    return event["id"], start


async def stored(w, event_id):
    async with w.factory() as session:
        ev = await session.get(CalendarEvent, uuid.UUID(str(event_id)))
        return SimpleNamespace(sequence=ev.protocol_sequence, starts=ev.starts_at, ends=ev.ends_at,
                               status=ev.status, title=ev.title, url=ev.conference_url)


async def action(w, event_id, **changes):
    return await w.client.post(f"/api/work/calendar/{event_id}",
        json={"company_id": str(w.company.id), **changes})


def body_sequence(raw):
    text = raw.decode() if isinstance(raw, bytes) else raw
    return int(next(line.split(":", 1)[1] for line in text.replace("\r\n ", "").splitlines()
                    if line.startswith("SEQUENCE:")))


@pytest.mark.parametrize("conference", [False, True])
@pytest.mark.parametrize("delegate", [False, True])
async def test_same_second_two_real_moves_and_cancel_all_recipients(world, conference, delegate):
    w = world
    eid, start = await create(w, conference=conference)
    uid = f"{eid}@{'conf.elsyplus' if conference else 'trek'}"
    assert (await stored(w, eid)).sequence == 0
    initial = next(m for m in w.messages if str(m["To"]) == w.attendee.email)
    assert calendar_part(initial, "REQUEST", w.attendee.email, uid, start, w.owner) == 0
    guest = await work_router.guest_invite(eid, work_router.GuestIn(
        company_id=str(w.company.id), email="revision-guest@example.test"), db=w.db, current_user=w.owner)
    assert (await stored(w, eid)).sequence == 0, "recipient addition is not organizer-state revision"
    w.actor = w.assistant if delegate else w.owner
    for expected, shift, cancel in ((1, 1, False), (2, 2, False), (3, 2, True)):
        w.messages.clear()
        w.chats.clear()
        moved = start + timedelta(hours=shift)
        changes = ({"cancel": True, "cancel_reason": "Synthetic cancellation"} if cancel else
                   {"starts_at": moved.isoformat(), "ends_at": (moved + timedelta(hours=1)).isoformat()})
        response = await action(w, eid, **changes)
        assert response.status_code == 200, response.text
        assert "protocol_sequence" not in response.json(), "public DTO must remain unchanged"
        assert (await stored(w, eid)).sequence == expected
        recipients = {str(m["To"]) for m in w.messages}
        assert recipients == {w.owner.email, w.assistant.email, w.attendee.email, guest["email"]}
        for message in w.messages:
            recipient = str(message["To"])
            target_uid = f"{eid}@trek" if recipient == guest["email"] else uid
            assert calendar_part(message, "CANCEL" if cancel else "REQUEST", recipient,
                                 target_uid, moved, w.owner) == expected
            for part in message.walk():
                if part.get_content_type() == "text/calendar":
                    text = part.get_payload(decode=True).decode()
                    assert "DTSTAMP:20261031T120000Z" in text
                    assert "LAST-MODIFIED:" not in text
                    if part.get_filename() == "invite.ics":
                        assert "\r\n" in text, "raw attachment retains the existing ICS line endings"
        assert all(sender != recipient for sender, recipient in w.chats)
    assert Clock.instant == NOW, "no clock spreading, sleep, or per-delivery version allocation"


async def test_readers_guest_email_export_and_feed_share_version(world):
    w = world
    eid, start = await create(w)
    guest = await work_router.guest_invite(eid, work_router.GuestIn(
        company_id=str(w.company.id), email="revision-reader@example.test"), db=w.db, current_user=w.owner)
    response = await action(w, eid, starts_at=(start + timedelta(hours=1)).isoformat(),
                            ends_at=(start + timedelta(hours=2)).isoformat())
    assert response.status_code == 200
    own = await w.client.get(f"/api/work/calendar/{eid}/ics", params={"company_id": str(w.company.id)})
    external = await w.client.get(f"/api/invite/{guest['token']}/ics")
    assert own.status_code == external.status_code == 200
    assert body_sequence(own.content) == body_sequence(external.content) == 1
    w.owner.calendar_feed_token = "revision-owned-feed-" + uuid.uuid4().hex
    await w.db.commit()
    feed = await w.client.get("/api/work/calendar/feed/" + w.owner.calendar_feed_token + ".ics")
    assert feed.status_code == 200, feed.text
    assert f"UID:{eid}@trek" in feed.text and "SEQUENCE:1" in feed.text
    assert own.headers["content-disposition"] == 'attachment; filename="meeting.ics"'
    assert feed.headers["cache-control"] == "no-store"
    assert (await stored(w, eid)).sequence == 1, "reads never advance revision"


async def test_noop_retries_recipient_add_and_partstat_do_not_advance(world):
    w = world
    eid, start = await create(w, attendees=[str(w.attendee.id)])
    assert (await action(w, eid, starts_at=start.isoformat(),
                         ends_at=(start + timedelta(hours=1)).isoformat())).status_code == 200
    assert (await stored(w, eid)).sequence == 0
    w.actor = w.attendee
    assert (await action(w, eid, response="accepted")).status_code == 200
    assert (await action(w, eid, propose_starts_at=(start + timedelta(hours=2)).isoformat(),
                         propose_ends_at=(start + timedelta(hours=3)).isoformat())).status_code == 200
    assert (await stored(w, eid)).sequence == 0
    w.actor = w.owner
    w.messages.clear()
    assert (await action(w, eid, attendee_ids=[str(w.attendee.id), str(w.assistant.id)])).status_code == 200
    assert {str(m["To"]) for m in w.messages} == {w.assistant.email}
    assert all(body_sequence(p.get_payload(decode=True)) == 0 for m in w.messages for p in m.walk()
               if p.get_content_type() == "text/calendar")
    assert (await stored(w, eid)).sequence == 0
    for _ in range(2):
        assert (await action(w, eid, cancel=True, cancel_reason="Same logical cancellation")).status_code == 200
        assert (await stored(w, eid)).sequence == 1


async def test_new_attendee_and_move_share_one_committed_revision(world):
    w = world
    eid, start = await create(w, attendees=[str(w.attendee.id)])
    w.messages.clear()
    response = await action(w, eid, attendee_ids=[str(w.attendee.id), str(w.assistant.id)],
                            starts_at=(start + timedelta(hours=1)).isoformat(),
                            ends_at=(start + timedelta(hours=2)).isoformat())
    assert response.status_code == 200
    assert {str(m["To"]) for m in w.messages} == {w.owner.email, w.attendee.email, w.assistant.email}
    assert all(body_sequence(p.get_payload(decode=True)) == 1 for m in w.messages for p in m.walk()
               if p.get_content_type() == "text/calendar")
    assert (await stored(w, eid)).sequence == 1


async def test_concurrent_real_actions_recheck_committed_row_without_sleep(world, monkeypatch):
    w = world
    eid, start = await create(w)
    first_locked, second_attempted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = calendar_series.lock_event
    first_session = None
    observed = []

    async def coordinated(db, cid, event_id, **kwargs):
        nonlocal first_session
        if first_session is None:
            first_session = db
            event = await original(db, cid, event_id, **kwargs)
            first_locked.set()
            await asyncio.wait_for(release.wait(), 10)
        else:
            if db is not first_session:
                second_attempted.set()
            event = await original(db, cid, event_id, **kwargs)
        if event is not None:
            observed.append((db is first_session, event.protocol_sequence))
        return event

    monkeypatch.setattr(calendar_series, "lock_event", coordinated)
    async with w.factory() as a, w.factory() as b:
        async def change(session, shift):
            return await work_router.calendar_action(eid, work_router.EventAction(
                company_id=str(w.company.id), starts_at=start + timedelta(hours=shift),
                ends_at=start + timedelta(hours=shift + 1)), db=session, current_user=w.owner)
        one = asyncio.create_task(change(a, 1))
        two = None
        try:
            await asyncio.wait_for(first_locked.wait(), 10)
            two = asyncio.create_task(change(b, 2))
            await asyncio.wait_for(second_attempted.wait(), 10)
            release.set()
            await asyncio.wait_for(asyncio.gather(one, two), 20)
        finally:
            release.set()
            for task in (one, two):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(t for t in (one, two) if t is not None), return_exceptions=True)
    result = await stored(w, eid)
    assert result.sequence == 2 and result.starts == start + timedelta(hours=2)
    assert (False, 1) in observed, "second transaction must see the first committed revision"


async def test_clock_backwards_and_legacy_floor_need_no_timestamp_counter(world, monkeypatch):
    w = world
    eid, start = await create(w)
    event = await w.db.get(CalendarEvent, uuid.UUID(eid))
    event.protocol_sequence = calendar_protocol.LEGACY_BOUND
    await w.db.commit()
    monkeypatch.setattr(Clock, "instant", NOW - timedelta(days=3650))
    response = await action(w, eid, title="Organizer changed title")
    assert response.status_code == 200
    assert (await stored(w, eid)).sequence == calendar_protocol.LEGACY_BOUND + 1
    assert (await action(w, eid, title="Organizer changed title")).status_code == 200
    assert (await stored(w, eid)).sequence == calendar_protocol.LEGACY_BOUND + 1


async def test_exhaustion_rolls_back_state_and_emits_nothing(world):
    w = world
    eid, start = await create(w)
    event = await w.db.get(CalendarEvent, uuid.UUID(eid))
    event.protocol_sequence = calendar_protocol.MAX_SEQUENCE
    await w.db.commit()
    w.messages.clear()
    w.chats.clear()
    response = await action(w, eid, starts_at=(start + timedelta(hours=1)).isoformat(),
                            ends_at=(start + timedelta(hours=2)).isoformat())
    assert response.status_code == 409
    result = await stored(w, eid)
    assert result.sequence == calendar_protocol.MAX_SEQUENCE and result.starts == start
    assert not w.messages and not w.chats


@pytest.mark.parametrize("denial", ["foreign", "outsider", "revoked_member", "module"])
async def test_current_tenant_membership_and_history_denial_unchanged(world, denial):
    w = world
    eid, start = await create(w)
    w.messages.clear()
    restore = []
    if denial == "foreign":
        w.actor = w.foreign
    elif denial == "outsider":
        await w.db.execute(delete(CalendarAttendee).where(
            CalendarAttendee.event_id == uuid.UUID(eid), CalendarAttendee.user_id == w.assistant.id))
        await w.db.commit()
        w.actor = w.assistant
    elif denial == "revoked_member":
        await w.db.execute(delete(UserCompany).where(
            UserCompany.company_id == w.company.id, UserCompany.user_id == w.attendee.id))
        await w.db.commit()
        w.actor = w.attendee
    else:
        member = await w.db.get(UserCompany, (w.owner.id, w.company.id))
        restore.append((member, member.role, member.modules, member.role_id))
        member.role, member.modules, member.role_id = "user", [], None
        await w.db.commit()
    try:
        response = await action(w, eid, starts_at=(start + timedelta(hours=1)).isoformat(),
                                ends_at=(start + timedelta(hours=2)).isoformat())
    finally:
        for member, role, modules, role_id in restore:
            member.role, member.modules, member.role_id = role, modules, role_id
        if restore:
            await w.db.commit()
    assert response.status_code == 403
    assert (await stored(w, eid)).sequence == 0
    assert not w.messages


async def test_series_url_and_future_cancellations_each_advance_once(world):
    w = world
    eid, start = await create(w, series=True)
    ids = list((await w.db.scalars(select(CalendarEvent.id).where(
        (CalendarEvent.id == uuid.UUID(eid)) | (CalendarEvent.series_id == uuid.UUID(eid))))).all())
    assert len(ids) > 2
    response = await action(w, eid, video=True)
    assert response.status_code == 200
    for event_id in ids:
        assert (await stored(w, event_id)).sequence == 1
    assert (await action(w, eid, video=True)).status_code == 200
    for event_id in ids:
        assert (await stored(w, event_id)).sequence == 1
    assert (await action(w, eid, cancel=True, cancel_reason="Cancel future instances")).status_code == 200
    for event_id in ids:
        result = await stored(w, event_id)
        assert result.sequence == 2 and result.status == "cancelled"


async def test_poll_status_and_chosen_time_have_stored_revisions(world):
    w = world
    eid, start = await create(w)
    opened = await w.client.post(f"/api/work/calendar/{eid}/poll", json={
        "company_id": str(w.company.id), "options": [
            {"starts_at": (start + timedelta(hours=1)).isoformat(),
             "ends_at": (start + timedelta(hours=2)).isoformat()},
            {"starts_at": (start + timedelta(hours=3)).isoformat(),
             "ends_at": (start + timedelta(hours=4)).isoformat()}]})
    assert opened.status_code == 201, opened.text
    assert (await stored(w, eid)).sequence == 1
    options = await w.client.get(f"/api/work/calendar/{eid}/poll", params={"company_id": str(w.company.id)})
    chosen = await w.client.post(f"/api/work/calendar/{eid}/poll/pick", json={
        "company_id": str(w.company.id), "option_id": options.json()["options"][0]["id"]})
    assert chosen.status_code == 200, chosen.text
    assert (await stored(w, eid)).sequence == 2


async def test_guest_reply_and_counter_leave_organizer_revision(world):
    w = world
    eid, start = await create(w)
    guest = await work_router.guest_invite(eid, work_router.GuestIn(
        company_id=str(w.company.id), email="revision-rsvp@example.test"), db=w.db, current_user=w.owner)
    await invite_router.invite_respond(guest["token"], invite_router.RsvpIn(response="accepted"), db=w.db)
    await invite_router.invite_propose(guest["token"], invite_router.ProposeIn(
        starts_at=start + timedelta(hours=1), ends_at=start + timedelta(hours=2)), db=w.db)
    assert (await stored(w, eid)).sequence == 0


async def test_conference_end_shortening_and_repeated_close(world, monkeypatch):
    w = world
    eid, start = await create(w, conference=True)
    session = ConfSession(company_id=w.company.id, event_id=uuid.UUID(eid),
                          room="ledger-01234567", title="Protocol revision", started_by=w.owner.id)
    w.db.add(session)
    await w.db.commit()
    monkeypatch.setattr(Clock, "instant", start + timedelta(minutes=30))
    await conf_router.session_end(str(session.id), company_id=str(w.company.id), db=w.db, current_user=w.owner)
    first = await stored(w, eid)
    assert first.ends == start + timedelta(minutes=30) and first.sequence == 1
    await conf_router.session_end(str(session.id), company_id=str(w.company.id), db=w.db, current_user=w.owner)
    assert (await stored(w, eid)).sequence == 1
