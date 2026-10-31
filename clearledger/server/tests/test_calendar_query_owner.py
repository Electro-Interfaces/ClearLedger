"""Fixed event-ID goldens on real SQL/HTTP; execute only via ROOT frozen gate."""
import os

if os.environ.get("RUN_CALENDAR_QUERY_OWNER_TESTS") != "1":
    raise RuntimeError("ROOT-approved calendar query runner required")

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.main import app
from app.models import (App, AuditEvent, CalendarAttendee, CalendarEvent, Company,
                        CompanyApp, UserCompany)
from app.routers import work_router
from app.services import calendar_queries, management_local
from tests.test_management_api import headers, management_data  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")

PREFIX = "calendar-owner-golden"
START = datetime(2026, 10, 30, 21, tzinfo=timezone.utc)
END = datetime(2026, 10, 31, 21, tzinfo=timezone.utc)
LABELS = ("organizer", "attendee", "both", "hidden", "public", "foreign", "disabled",
          "before", "ends-at-start", "starts-at-end", "overlap", "declined", "midnight",
          "cancelled", "far-future")
IDS = {label: uuid.UUID(f"c3100000-0000-4000-8000-{index:012x}")
       for index, label in enumerate(LABELS, 1)}
MINE = {IDS["organizer"], IDS["attendee"], IDS["both"], IDS["overlap"],
        IDS["declined"], IDS["midnight"], IDS["cancelled"]}
OVERVIEW = MINE | {IDS["public"]}


@pytest.fixture
async def calendar_data(management_data, db):
    d = management_data
    reader, other, cid = d["reader"], d["other"], d["cid"]
    disabled = Company(name="Тест · Другой профиль без Трека", profile_id="energy",
                       slug="calendar-disabled-" + uuid.uuid4().hex)
    db.add(disabled)
    await db.flush()
    db.add(UserCompany(user_id=reader.id, company_id=disabled.id, role="user"))
    for code in ("docs", "plan"):
        product = await db.scalar(select(App).where(App.code == code))
        if product is None:
            product = App(code=code, name=code, is_active=True)
            db.add(product)
            await db.flush()
        db.add(CompanyApp(company_id=disabled.id, app_id=product.id, enabled=False))
    for label, company, organizer, visibility, start, end in [
        ("organizer", cid, reader.id, "personal", START + timedelta(hours=12), START + timedelta(hours=13)),
        ("attendee", cid, other.id, "private", START + timedelta(hours=13), START + timedelta(hours=14)),
        ("both", cid, reader.id, "private", START + timedelta(hours=14), START + timedelta(hours=15)),
        ("hidden", cid, other.id, "private", START + timedelta(hours=15), START + timedelta(hours=16)),
        ("public", cid, other.id, "company", START + timedelta(hours=16), START + timedelta(hours=17)),
        ("foreign", d["other_cid"], reader.id, "private", START + timedelta(hours=17), START + timedelta(hours=18)),
        ("disabled", disabled.id, reader.id, "private", START + timedelta(hours=18), START + timedelta(hours=19)),
        ("before", cid, reader.id, "private", START - timedelta(hours=3), START - timedelta(hours=2)),
        ("ends-at-start", cid, reader.id, "private", START - timedelta(hours=1), START),
        ("starts-at-end", cid, reader.id, "private", END, END + timedelta(hours=1)),
        ("overlap", cid, reader.id, "private", START - timedelta(minutes=30), START + timedelta(minutes=30)),
        ("declined", cid, other.id, "private", START + timedelta(hours=19), START + timedelta(hours=20)),
        ("midnight", cid, reader.id, "private", START + timedelta(minutes=30), START + timedelta(hours=1)),
        ("cancelled", cid, reader.id, "private", START + timedelta(hours=20), START + timedelta(hours=21)),
        ("far-future", cid, reader.id, "private", datetime(2030, 1, 1, tzinfo=timezone.utc), datetime(2030, 1, 2, tzinfo=timezone.utc)),
    ]:
        db.add(CalendarEvent(id=IDS[label], company_id=company, organizer_id=organizer,
            title=PREFIX + ":" + label, starts_at=start, ends_at=end, visibility=visibility,
            status="cancelled" if label == "cancelled" else "planned", tz="Europe/Moscow",
            subject_ref=PREFIX + ":subject"))
    await db.flush()
    for label, user_id, response in [("attendee", reader.id, "pending"),
                                     ("both", reader.id, "accepted"),
                                     ("both", other.id, "accepted"),
                                     ("declined", reader.id, "declined")]:
        db.add(CalendarAttendee(event_id=IDS[label], user_id=user_id, response=response))
    reader.calendar_feed_token = "calendar-owner-test-" + uuid.uuid4().hex
    await db.commit()
    d["disabled_cid"] = disabled.id
    yield d
    await db.execute(delete(CalendarEvent).where(CalendarEvent.id.in_(IDS.values())))
    await db.commit()


async def snapshot(db):
    return {model.__tablename__: sorted(repr(tuple(row)) for row in
            (await db.execute(select(model.__table__))).all())
            for model in (CalendarEvent, CalendarAttendee, AuditEvent)}


def result_ids(rows, key="id"):
    ids = [uuid.UUID(row[key]) for row in rows]
    assert len(ids) == len(set(ids)), "organizer + attendee must not duplicate an event"
    return set(ids)


async def native(client, d, **extra):
    params = {"company_id": str(d["cid"]), "from": START.isoformat(), "to": END.isoformat(),
              "q": PREFIX}
    params.update(extra)
    return await client.get("/api/work/calendar", headers=headers(d), params=params)


async def overview(client, d, **extra):
    params = {"kind": "calendar", "query": PREFIX, "date_from": "2026-10-31",
              "date_to": "2026-10-31", "time_zone": "Europe/Moscow"}
    params.update(extra)
    return await client.get("/api/management/overview", headers=headers(d), params=params)


async def test_native_wrapper_resolves_owner_without_sql(monkeypatch):
    uid, expression = uuid.uuid4(), object()
    owner = Mock(return_value=expression)
    monkeypatch.setattr(calendar_queries, "my_events_clause", owner)
    assert work_router._my_events_clause(uid) is expression
    owner.assert_called_once_with(uid)


async def test_sql_fixed_ids_owner_is_participation_not_company_or_date_acl(calendar_data, db):
    d = calendar_data
    before = await snapshot(db)
    rows = list((await db.scalars(select(CalendarEvent.id).where(
        CalendarEvent.id.in_(IDS.values()), calendar_queries.my_events_clause(d["reader"].id)))).all())
    expected = {IDS["organizer"], IDS["attendee"], IDS["both"], IDS["foreign"], IDS["disabled"],
                IDS["before"], IDS["ends-at-start"], IDS["starts-at-end"], IDS["overlap"],
                IDS["declined"], IDS["midnight"], IDS["cancelled"], IDS["far-future"]}
    assert set(rows) == expected and len(rows) == 13
    assert await snapshot(db) == before


@pytest.mark.parametrize("scope,subject,expected", [
    ("mine", False, MINE), ("company", False, {IDS["public"]}),
    ("mine", True, OVERVIEW),
])
async def test_native_list_keeps_company_period_visibility_and_no_duplicates(calendar_data, db, scope, subject, expected):
    d = calendar_data
    before = await snapshot(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await native(client, d, scope=scope, **({"subject_ref": PREFIX + ":subject"} if subject else {}))
    assert response.status_code == 200, response.text
    assert result_ids(response.json()["events"]) == expected
    assert response.json()["total"] == len(expected) and response.json()["truncated"] is False
    assert await snapshot(db) == before


@pytest.mark.parametrize("label,status", [("organizer", 200), ("attendee", 200),
    ("both", 200), ("declined", 200), ("public", 200), ("hidden", 403), ("foreign", 404)])
async def test_native_detail_keeps_existing_http_acl(calendar_data, db, label, status):
    d = calendar_data
    before = await snapshot(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/work/calendar/{IDS[label]}", headers=headers(d),
                                    params={"company_id": str(d["cid"])})
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json()["id"] == str(IDS[label])
    else:
        assert response.json() == {"detail": "Это не ваша встреча" if status == 403 else "Встреча не найдена"}
    assert await snapshot(db) == before


async def test_management_uses_direct_owner_without_native_hook_or_writes(calendar_data, db, monkeypatch):
    d = calendar_data
    before = await snapshot(db)
    original, seen = calendar_queries.my_events_clause, []
    def owner(uid):
        seen.append(uid)
        return original(uid)
    with monkeypatch.context() as patch:
        patch.setattr(calendar_queries, "my_events_clause", owner)
        old = Mock(side_effect=AssertionError("management called obsolete native binding"))
        patch.setattr(work_router, "_my_events_clause", old)
        commit, flush = AsyncMock(side_effect=AssertionError("read committed")), AsyncMock(side_effect=AssertionError("read flushed"))
        patch.setattr(db, "commit", commit)
        patch.setattr(db, "flush", flush)
        rows, truncated = await management_local.read_local(db, d["reader"], d["cid"], "calendar",
            query=PREFIX, date_from=START, date_to=END, limit=100)
        assert {row.source_id for row in rows} == OVERVIEW and len(rows) == 8
        assert not truncated and seen == [d["reader"].id]
        old.assert_not_called()
        commit.assert_not_awaited()
        flush.assert_not_awaited()
    assert await snapshot(db) == before


async def test_management_http_golden_utc_and_limit(calendar_data, db, pytestconfig):
    d = calendar_data
    before = await snapshot(db)
    boundary = pytestconfig._calendar_query_boundary
    deliveries = len(boundary.capture)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await overview(client, d)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["sources"][0]["state"] == "ok"
        assert result_ids(data["items"], "source_id") == OVERVIEW
        assert response.headers["cache-control"] == "no-store"
        midnight = next(row for row in data["items"] if row["source_id"] == str(IDS["midnight"]))
        assert datetime.fromisoformat(midnight["starts_at"].replace("Z", "+00:00")) == START + timedelta(minutes=30)
        capped = await overview(client, d, limit=1)
        assert capped.status_code == 200, capped.text
        assert result_ids(capped.json()["items"], "source_id") == {IDS["overlap"]}
        assert capped.json()["truncated"] is True
    assert len(boundary.capture) == deliveries
    assert await snapshot(db) == before


@pytest.mark.parametrize("superadmin", [False, True])
async def test_admin_nonparticipant_keeps_personal_calendar_and_detail_private(calendar_data, db, superadmin):
    d = calendar_data
    d["admin"].is_superadmin = superadmin
    await db.commit()
    before = await snapshot(db)
    auth = headers(d, user="admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/work/calendar", headers=auth, params={
            "company_id": str(d["cid"]), "from": START.isoformat(), "to": END.isoformat(), "q": PREFIX})
        assert response.status_code == 200, response.text
        assert response.json()["events"] == [] and response.json()["total"] == 0
        card = await client.get(f"/api/work/calendar/{IDS['hidden']}", headers=auth,
                                params={"company_id": str(d["cid"])})
        assert card.status_code == 403 and card.json() == {"detail": "Это не ваша встреча"}
        listed = await client.get("/api/management/overview", headers=auth, params={
            "kind": "calendar", "query": PREFIX, "date_from": "2026-10-31", "date_to": "2026-10-31"})
        assert listed.status_code == 200, listed.text
        assert result_ids(listed.json()["items"], "source_id") == {IDS["public"]}
    assert await snapshot(db) == before


@pytest.mark.parametrize("reason", ["disabled-profile", "membership", "modules"])
async def test_existing_caller_membership_modules_and_legacy_profile_split(calendar_data, db, reason):
    d = calendar_data
    cid = d["cid"]
    if reason == "disabled-profile":
        cid = d["disabled_cid"]
    else:
        member = await db.get(UserCompany, (d["reader"].id, cid))
        if reason == "membership":
            await db.delete(member)
        else:
            member.modules = ["chat"]
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        native_response = await native(client, d, company_id=str(cid))
        # Existing native _assert_work checks member modules, while management
        # additionally checks CompanyApp.enabled; ROOT msg_2289f382a39c preserves
        # this legacy difference for M03 review without changing authority here.
        assert native_response.status_code == (200 if reason == "disabled-profile" else 403), native_response.text
        if reason == "disabled-profile":
            assert result_ids(native_response.json()["events"]) == {IDS["disabled"]}
        response = await client.get("/api/management/overview", headers=headers(d, cid=cid), params={
            "kind": "calendar", "query": PREFIX, "date_from": "2026-10-31", "date_to": "2026-10-31"})
        assert response.status_code == (403 if reason == "membership" else 200), response.text
        if response.status_code == 200:
            assert response.json()["items"] == []
            assert response.json()["sources"][0]["state"] == "forbidden"


async def test_token_feed_preserves_separate_cross_company_trust_and_window(calendar_data, db, monkeypatch):
    d = calendar_data
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(work_router, "datetime", Frozen)
    before = await snapshot(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/work/calendar/feed/{d['reader'].calendar_feed_token}.ics")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/calendar")
        actual = [uuid.UUID(line[4:].split("@")[0]) for line in response.text.splitlines()
                  if line.startswith("UID:c3100000-")]
        expected = {IDS["organizer"], IDS["attendee"], IDS["both"], IDS["foreign"], IDS["disabled"],
                    IDS["before"], IDS["ends-at-start"], IDS["starts-at-end"], IDS["overlap"],
                    IDS["declined"], IDS["midnight"], IDS["cancelled"]}
        assert set(actual) == expected and len(actual) == 12
        assert "STATUS:CANCELLED" in response.text
        assert (await client.get("/api/work/calendar/feed/short.ics")).status_code == 404
    assert await snapshot(db) == before
