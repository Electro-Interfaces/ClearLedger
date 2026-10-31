"""Focused SQL/ASGI characterization, executed only by the frozen ROOT gate."""
import os
from urllib.parse import urlsplit

import pytest

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_MEETING_HOSTS_QUERY_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Requires {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)
if (os.environ.get("ROOT_APPROVED_MEETING_HOSTS_QUERY_TESTS") != "1"
        or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]
        or urlsplit(os.environ["TEST_DATABASE_URL"]).path != "/api_meeting_hosts_test_20261030"):
    raise RuntimeError("Requires ROOT approval and the exact disposable meeting-hosts database")

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import _visit_company, get_current_user
from app.database import get_db
from app.models import CalendarAttendee, CalendarEvent, Company, User, UserCompany
from app.routers import conf_router, work_router
from app.scope import set_request_organization, set_request_scope
from app.services import jitsi

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def world(db):
    """Own synthetic rows, committed once; every observation uses a fresh session."""
    visit = _visit_company.set(None)
    set_request_scope(None)
    set_request_organization(None)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    suffix = uuid.uuid4().hex
    async with factory() as setup:
        company = Company(name="Синтетическая компания встреч", slug="meeting-hosts-" + suffix,
                          profile_id="energy")
        setup.add(company)
        await setup.flush()
        people = {key: User(name=name, email=f"{key}-{suffix}@example.invalid",
                            password_hash="unused-synthetic", company_id=company.id,
                            email_notify=["meeting"], mail_only=False)
                  for key, name in [("organizer", "Организатор"), ("alpha", "Анна"),
                                    ("bravo", "Борис"), ("listener", "Слушатель")]}
        setup.add_all(people.values())
        await setup.flush()
        setup.add_all(UserCompany(user_id=p.id, company_id=company.id, role="admin" if key == "organizer" else "user")
                      for key, p in people.items())
        start = datetime(2030, 1, 1, 10, tzinfo=timezone.utc)
        event = CalendarEvent(company_id=company.id, organizer_id=people["organizer"].id,
                              title="Запрос ведущих", starts_at=start, ends_at=start + timedelta(hours=1), tz="UTC")
        other = CalendarEvent(company_id=company.id, organizer_id=people["organizer"].id,
                              title="Другая встреча", starts_at=start, ends_at=start + timedelta(hours=1), tz="UTC")
        setup.add_all([event, other])
        await setup.flush()
        setup.add_all(CalendarAttendee(event_id=event.id, user_id=p.id, is_host=False)
                      for p in people.values())
        # A marked host of another event must never enter this event's result.
        setup.add(CalendarAttendee(event_id=other.id, user_id=people["listener"].id, is_host=True))
        await setup.commit()
        w = SimpleNamespace(factory=factory, cid=company.id, event_id=event.id,
                            people=people, ids={k: p.id for k, p in people.items()})
    try:
        yield w
    finally:
        set_request_scope(None)
        set_request_organization(None)
        _visit_company.reset(visit)


@pytest.mark.parametrize("marked,expected", [
    ([], ["organizer"]),
    (["bravo"], ["bravo"]),
    (["bravo", "alpha"], ["alpha", "bravo"]),
], ids=["none-falls-back", "one-overrides-organizer", "multiple-override-organizer"])
async def test_literal_host_results_and_compatible_wrapper(world, marked, expected):
    w = world
    async with w.factory() as writer:
        rows = (await writer.scalars(select(CalendarAttendee).where(CalendarAttendee.event_id == w.event_id))).all()
        for row in rows:
            row.is_host = row.user_id in {w.ids[key] for key in marked}
        await writer.commit()
    async with w.factory() as fresh:
        ev = await fresh.get(CalendarEvent, w.event_id)
        golden = {w.ids[key] for key in expected}
        assert await jitsi.meeting_hosts(fresh, ev) == golden
        assert await conf_router.ведущие_встречи(fresh, ev) == golden
        assert isinstance(await conf_router.ведущие_встречи(fresh, ev), set)


async def test_query_is_read_only_without_commit_rollback_or_token(world, monkeypatch):
    w = world
    async with w.factory() as fresh:
        await fresh.execute(text("SET TRANSACTION READ ONLY"))
        assert await fresh.scalar(text("SHOW transaction_read_only")) == "on"
        ev = await fresh.get(CalendarEvent, w.event_id)

        async def forbidden_transaction(*args, **kwargs):
            pytest.fail("Host selection must not commit/rollback its caller")

        def forbidden_token(*args, **kwargs):
            pytest.fail("Host selection must not issue a token")

        with monkeypatch.context() as patch:
            patch.setattr(fresh, "commit", forbidden_transaction)
            patch.setattr(fresh, "rollback", forbidden_transaction)
            patch.setattr(jitsi, "sign_token", forbidden_token)
            patch.setattr(jitsi, "meeting_urls", forbidden_token)
            assert await jitsi.meeting_hosts(fresh, ev) == {w.ids["organizer"]}
            assert await conf_router.ведущие_встречи(fresh, ev) == {w.ids["organizer"]}
            assert fresh.in_transaction()


async def test_caller_rollback_retains_host_change_ownership(world):
    w = world
    async with w.factory() as transaction:
        row = await transaction.scalar(select(CalendarAttendee).where(
            CalendarAttendee.event_id == w.event_id, CalendarAttendee.user_id == w.ids["alpha"]))
        row.is_host = True
        await transaction.flush()
        ev = await transaction.get(CalendarEvent, w.event_id)
        assert await jitsi.meeting_hosts(transaction, ev) == {w.ids["alpha"]}
        await transaction.rollback()
    async with w.factory() as fresh:
        ev = await fresh.get(CalendarEvent, w.event_id)
        assert await jitsi.meeting_hosts(fresh, ev) == {w.ids["organizer"]}
        assert await fresh.scalar(select(CalendarAttendee.is_host).where(
            CalendarAttendee.event_id == w.event_id, CalendarAttendee.user_id == w.ids["alpha"])) is False


async def test_query_and_wrapper_propagate_execute_error():
    error = RuntimeError("synthetic execute failure")
    db = SimpleNamespace(execute=AsyncMock(side_effect=error))
    ev = SimpleNamespace(id=uuid.uuid4(), organizer_id=uuid.uuid4())
    for helper in (jitsi.meeting_hosts, conf_router.ведущие_встречи):
        with pytest.raises(RuntimeError) as caught:
            await helper(db, ev)
        assert caught.value is error


async def test_asgi_invitation_uses_sorted_hosts_and_captured_delivery(world, meeting_delivery_capture, monkeypatch):
    w = world
    app = FastAPI()
    app.include_router(work_router.router, prefix="/api")

    async def principal():
        return w.people["organizer"]

    async def session():
        async with w.factory() as fresh:
            yield fresh

    app.dependency_overrides[get_current_user] = principal
    app.dependency_overrides[get_db] = session
    # Token generation is irrelevant for the supplied guest URL and forbidden here.
    def no_token(*args, **kwargs):
        pytest.fail("The invitation case must not issue a token")
    monkeypatch.setattr(jitsi, "sign_token", no_token)
    payload = {
        "company_id": str(w.cid), "title": "Проверка ведущих",
        "starts_at": "2030-01-01T10:00:00Z", "ends_at": "2030-01-01T11:00:00Z",
        "tz": "UTC", "location": "Кабинет", "video": False,
        "conference_url": "https://meet.example.invalid/ledger-acde",
        "attendee_ids": [str(w.ids[key]) for key in ["bravo", "alpha", "listener"]],
        "host_ids": [str(w.ids["bravo"]), str(w.ids["alpha"])],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test") as client:
        response = await client.post("/api/work/calendar", json=payload)
    assert response.status_code == 201, response.text
    event_id = uuid.UUID(response.json()["id"])
    async with w.factory() as fresh:
        ev = await fresh.get(CalendarEvent, event_id)
        assert await jitsi.meeting_hosts(fresh, ev) == {w.ids["alpha"], w.ids["bravo"]}
    golden = (
        "Организатор зовёт на встречу «Проверка ведущих» 01.01.2030 в 10:00.\n"
        "Где: Кабинет\nСсылка на видеовстречу: https://meet.example.invalid/ledger-acde\n"
        "Ведущие: Анна, Борис"
    )
    mails = meeting_delivery_capture["meeting_email"]
    chats = meeting_delivery_capture["chat"]
    # Live e44ea4d6 also updates the actor's external calendar (old 3, now 4).
    assert len(mails) == 4 and len(chats) == 3
    assert {m["to"] for m in mails} == {w.people[k].email for k in ["organizer", "alpha", "bravo", "listener"]}
    assert {c["person_id"] for c in chats} == {w.ids[k] for k in ["alpha", "bravo", "listener"]}
    for mail in mails:
        assert mail["text"] == golden
        assert mail["subject"] == "Приглашение: Проверка ведущих — 01.01.2030 в 10:00"
        assert mail["method"] == "REQUEST"
        assert "<br>Ведущие: Анна, Борис" in mail["html"]
        ics = mail["ics"].replace("\r\n ", "")
        assert f"UID:{event_id}@conf.elsyplus\r\n" in ics
        assert "METHOD:REQUEST\r\n" in ics and "DTSTART:20300101T100000Z\r\n" in ics
    assert all(c["text"] == "📅 " + golden for c in chats)
