"""Интеграционные ACL проверки: только выделенная TEST_DATABASE_URL из conftest."""
import base64
import json
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
import httpx
from sqlalchemy import func, select

from app.auth import create_access_token
from app.main import app
from app.models import (
    App, CalendarAttendee, CalendarEvent, ChatMessage, ChatParticipant, ChatRoom,
    Company, CompanyApp, CompanyRole, Task, TaskParticipant, TaskWatcher, User, UserCompany,
)
from app.services.management_config import ManagementConfig, RemoteSource
from app.services.management_delegation import sign_access

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
async def management_data(db, tmp_path, monkeypatch):
    companies = [Company(name="Тест обзора", slug=f"management-{uuid.uuid4().hex}", profile_id="office")
                 for _ in range(2)]
    db.add_all(companies)
    await db.flush()
    cid, other_cid = (c.id for c in companies)
    users = [User(id=uuid.uuid4(), company_id=cid, name=name, email=f"mgmt-{uuid.uuid4().hex}@test.invalid",
                  password_hash="!test", role="user", is_superadmin=False,
                  last_seen_at=datetime.now(timezone.utc)) for name in ("Читатель", "Другой", "Администратор")]
    db.add_all(users)
    await db.flush()
    reader, other, admin = users
    db.add_all([UserCompany(user_id=u.id, company_id=cid, role="admin" if u is admin else "user")
                for u in users])
    db.add(UserCompany(user_id=reader.id, company_id=other_cid, role="user"))
    apps = {}
    for code in ("docs", "chat"):
        application = (await db.execute(select(App).where(App.code == code))).scalar_one_or_none()
        if application is None:
            application = App(code=code, name=code, is_active=True)
            db.add(application)
            await db.flush()
        apps[code] = application
        db.add(CompanyApp(company_id=cid, app_id=application.id, enabled=True))
        db.add(CompanyApp(company_id=other_cid, app_id=application.id, enabled=True))
    tasks = {}
    for name, visibility, author, assignee, company_id in [
        ("public", "company", other, None, cid),
        ("private-hidden", "private", other, other, cid),
        ("private-author", "private", reader, other, cid),
        ("private-assignee", "private", other, reader, cid),
        ("private-watcher", "private", other, other, cid),
        ("private-participant", "private", other, other, cid),
        ("personal-other", "personal", other, other, cid),
        ("personal-mine", "personal", reader, reader, cid),
        ("other-company", "company", other, None, other_cid),
    ]:
        task = Task(company_id=company_id, title=name, visibility=visibility, author_id=author.id,
                    assignee_id=assignee.id if assignee else None, status="open",
                    due_at=datetime(2026, 10, 24, 12, tzinfo=timezone.utc))
        db.add(task)
        tasks[name] = task
    await db.flush()
    db.add(TaskWatcher(task_id=tasks["private-watcher"].id, user_id=reader.id))
    db.add(TaskParticipant(task_id=tasks["private-participant"].id, user_id=reader.id, role="executor"))
    events = {}
    for name, visibility, organizer, company_id, start in [
        ("public-event", "company", other, cid, datetime(2026, 10, 24, 8, tzinfo=timezone.utc)),
        ("private-hidden-event", "private", other, cid, datetime(2026, 10, 24, 9, tzinfo=timezone.utc)),
        ("personal-hidden-event", "personal", other, cid, datetime(2026, 10, 24, 10, tzinfo=timezone.utc)),
        ("my-event", "private", reader, cid, datetime(2026, 10, 24, 11, tzinfo=timezone.utc)),
        ("invited-event", "private", other, cid, datetime(2026, 10, 24, 12, tzinfo=timezone.utc)),
        # Уже 24 октября в Москве, ещё 23 октября UTC.
        ("near-midnight", "company", other, cid, datetime(2026, 10, 23, 21, 30, tzinfo=timezone.utc)),
        ("next-day", "company", other, cid, datetime(2026, 10, 24, 21, 30, tzinfo=timezone.utc)),
        ("foreign-event", "company", reader, other_cid, datetime(2026, 10, 24, 10, tzinfo=timezone.utc)),
    ]:
        event = CalendarEvent(company_id=company_id, title=name, organizer_id=organizer.id,
                              visibility=visibility, starts_at=start, ends_at=start+timedelta(minutes=15),
                              tz="Europe/Moscow", status="planned")
        db.add(event)
        events[name] = event
    await db.flush()
    db.add(CalendarAttendee(event_id=events["invited-event"].id, user_id=reader.id,
                            role="required", response="accepted"))
    rooms = {}
    for name, room_type, company_id, participant in [
        ("joined-room", "group", cid, reader), ("hidden-room", "group", cid, other),
        ("joined-direct", "direct", cid, reader), ("hidden-direct", "direct", cid, other),
        ("foreign-room", "group", other_cid, reader),
    ]:
        room = ChatRoom(company_id=company_id, name=name, type=room_type, is_active=True, is_archived=False)
        db.add(room)
        await db.flush()
        db.add(ChatParticipant(room_id=room.id, user_id=participant.id, role="member",
                               last_read_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
                               history_from=datetime(2026, 10, 24, tzinfo=timezone.utc)))
        rooms[name] = room
    await db.flush()
    db.add(ChatMessage(room_id=rooms["joined-room"].id, user_id=other.id, user_name=other.name,
                       type="text", content="HIDDEN HISTORY SECRET",
                       created_at=datetime(2026, 10, 23, tzinfo=timezone.utc)))
    await db.commit()
    path = tmp_path / "management.json"
    config = {"enabled": True, "hub_enabled": True, "code": "desk", "name": "Управляющее пространство"}
    path.write_text(json.dumps(config))
    monkeypatch.setenv("MANAGEMENT_CONFIG_PATH", str(path))
    return {"cid": cid, "other_cid": other_cid, "reader": reader, "other": other, "admin": admin,
            "tasks": tasks, "events": events, "rooms": rooms, "apps": apps,
            "path": path, "config": config}


def headers(data, user="reader", cid=None):
    who = data[user]
    return {"Authorization": "Bearer " + create_access_token(str(who.id), who.email),
            "X-Company-Id": str(cid or data["cid"])}


async def get_overview(data, kind, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/api/management/overview", headers=headers(data),
                                params={"kind": kind, **kwargs})


async def test_local_task_acl_and_company_scope(management_data):
    d = management_data
    response = await get_overview(d, "tasks")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["sources"][0]["state"] == "ok", result
    assert {i["title"] for i in result["items"]} == {
        "public", "private-author", "private-assignee", "private-watcher", "private-participant"}
    assert all(i["source"]["company_id"] == str(d["cid"]) for i in result["items"])
    assert response.headers["cache-control"] == "no-store"
    filtered = await get_overview(d, "tasks", query="private-assignee", limit=1)
    assert [i["title"] for i in filtered.json()["items"]] == ["private-assignee"]
    assert not filtered.json()["truncated"]
    capped = await get_overview(d, "tasks", limit=1)
    assert len(capped.json()["items"]) == 1 and capped.json()["truncated"]


async def test_calendar_acl_day_bounds_and_no_task_deadlines(management_data):
    response = await get_overview(management_data, "calendar", date_from="2026-10-24",
                                   date_to="2026-10-24", time_zone="Europe/Moscow")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["sources"][0]["state"] == "ok", result
    assert {i["title"] for i in result["items"]} == {"public-event", "my-event", "invited-event", "near-midnight"}
    assert all(i["starts_at"] and i["ends_at"] and i["kind"] == "calendar" for i in result["items"])
    assert all(i["subtitle"] == "Europe/Moscow" for i in result["items"])


async def test_chat_participation_history_and_read_only(management_data, db):
    d = management_data
    tables = (ChatRoom, ChatParticipant, ChatMessage)
    before = [(await db.execute(select(func.count()).select_from(t))).scalar_one() for t in tables]
    last_read = (await db.execute(select(ChatParticipant.last_read_at).where(
        ChatParticipant.room_id == d["rooms"]["joined-room"].id,
        ChatParticipant.user_id == d["reader"].id))).scalar_one()
    response = await get_overview(d, "chats")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["sources"][0]["state"] == "ok", result
    assert {i["title"] for i in result["items"]} == {"joined-room", "joined-direct"}
    assert "HIDDEN HISTORY SECRET" not in response.text
    assert all(i["unread_count"] is None and i["subtitle"] is None for i in result["items"])
    after = [(await db.execute(select(func.count()).select_from(t))).scalar_one() for t in tables]
    assert before == after
    assert last_read == (await db.execute(select(ChatParticipant.last_read_at).where(
        ChatParticipant.room_id == d["rooms"]["joined-room"].id,
        ChatParticipant.user_id == d["reader"].id))).scalar_one()
    role = CompanyRole(company_id=d["cid"], name="Контур поддержки", chat_scope="support", modules=None)
    db.add(role)
    await db.flush()
    membership = await db.get(UserCompany, (d["reader"].id, d["cid"]))
    membership.role_id = role.id
    await db.commit()
    scoped = await get_overview(d, "chats")
    assert {i["title"] for i in scoped.json()["items"]} == {"joined-direct"}


async def test_product_grants_and_disabled_app(management_data, db):
    d = management_data
    membership = await db.get(UserCompany, (d["reader"].id, d["cid"]))
    membership.modules = ["info"]
    await db.commit()
    for kind in ("tasks", "calendar", "chats"):
        args = {"date_from": "2026-10-24", "date_to": "2026-10-24"} if kind == "calendar" else {}
        response = await get_overview(d, kind, **args)
        assert response.json()["sources"][0]["state"] == "forbidden", response.text
        assert not response.json()["items"]
    membership.modules = None
    record = (await db.execute(select(CompanyApp).where(CompanyApp.company_id == d["cid"],
                              CompanyApp.app_id == d["apps"]["docs"].id))).scalar_one()
    record.enabled = False
    await db.commit()
    response = await get_overview(d, "tasks")
    assert response.json()["sources"][0]["state"] == "forbidden"
    assert not response.json()["items"]


async def test_http_auth_validation_disabled_and_config_failure(management_data):
    d = management_data
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for params in ({}, {"kind": "unknown"}, {"kind": "tasks", "limit": 201},
                       {"kind": "calendar"}, {"kind": "calendar", "date_from": "2026-10-24", "date_to": "2026-10-23"}):
            response = await client.get("/api/management/overview", headers=headers(d), params=params)
            assert response.status_code == 422, response.text
        assert (await client.get("/api/management/overview", params={"kind": "tasks"})).status_code == 401
        no_company = headers(d)
        no_company.pop("X-Company-Id")
        assert (await client.get("/api/management/overview", headers=no_company,
                                  params={"kind": "tasks"})).status_code == 422
        response = await client.get("/api/management/overview", headers=headers(d, cid=uuid.uuid4()),
                                    params={"kind": "tasks"})
        assert response.status_code in (400, 403)
        assert (await client.get("/api/management/source-overview", headers=headers(d),
                                  params={"kind": "tasks"})).status_code == 403
        assert (await client.post("/api/management/overview", headers=headers(d))).status_code == 405
        assert (await client.get("/api/management/status", headers=headers(d))).json() == {"enabled": True}
        d["path"].write_text(json.dumps({"enabled": True}))
        assert (await client.get("/api/management/status", headers=headers(d))).json() == {"enabled": False}
        disabled = await get_overview(d, "tasks")
        assert disabled.json() == {"enabled": False, "fetched_at": disabled.json()["fetched_at"],
                                    "items": [], "sources": [], "truncated": False}
        d["path"].write_text('{"sources":"invalid secret address"}')
        bad = await get_overview(d, "tasks")
        assert bad.status_code == 503 and "secret" not in bad.text


async def test_delegated_source_acl_and_membership_revocation(management_data, db):
    d = management_data
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = base64.b64encode(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode()
    public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    actor, actor_company = uuid.uuid4(), uuid.uuid4()
    source = RemoteSource(code="desk", name="Test", base_url="https://source.invalid",
        company_id=d["cid"], company_name="Test", grants=[{"id": "explicit", "local_user_id": actor,
        "local_company_id": actor_company, "remote_user_id": d["reader"].id, "kinds": ["tasks", "chats", "calendar"]}])
    hub = ManagementConfig(enabled=True, hub_enabled=True, code="hub", signing_private_key_b64=private)
    receiver = {**d["config"], "hub_enabled": False, "trusted_issuers": [{"issuer": "hub",
        "public_key_b64": public, "grants": [{"id": "explicit", "actor_user_id": str(actor),
        "actor_company_id": str(actor_company), "user_id": str(d["reader"].id),
        "company_id": str(d["cid"]), "kinds": ["tasks", "chats", "calendar"]}]}]}
    d["path"].write_text(json.dumps(receiver))
    token = sign_access(hub, source, source.grants[0], "tasks")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/management/source-overview", params={"kind": "tasks"},
                                    headers={"Authorization": f"Bearer {token}", "X-Company-Id": str(d["other_cid"])})
        assert response.status_code == 200, response.text
        assert {i["title"] for i in response.json()["items"]} == {
            "public", "private-author", "private-assignee", "private-watcher", "private-participant"}
        for kind, expected, extra in [
            ("chats", {"joined-room", "joined-direct"}, {}),
            ("calendar", {"public-event", "my-event", "invited-event", "near-midnight"},
             {"date_from": "2026-10-24", "date_to": "2026-10-24", "time_zone": "Europe/Moscow"}),
        ]:
            scoped_token = sign_access(hub, source, source.grants[0], kind)
            scoped = await client.get("/api/management/source-overview", params={"kind": kind, **extra},
                                      headers={"Authorization": f"Bearer {scoped_token}"})
            assert scoped.status_code == 200, scoped.text
            assert {i["title"] for i in scoped.json()["items"]} == expected
        # Scoped credential не становится обычной сессией.
        denied = await client.get("/api/management/overview", params={"kind": "tasks"},
                                  headers={"Authorization": f"Bearer {token}", "X-Company-Id": str(d["cid"])})
        assert denied.status_code == 401
        d["reader"].mail_only = True
        await db.commit()
        blocked_user = await client.get("/api/management/source-overview", params={"kind": "tasks"},
                                        headers={"Authorization": f"Bearer {token}"})
        assert blocked_user.status_code == 403
        d["reader"].mail_only = False
        await db.commit()
        member = await db.get(UserCompany, (d["reader"].id, d["cid"]))
        await db.delete(member)
        await db.commit()
        revoked = await client.get("/api/management/source-overview", params={"kind": "tasks"},
                                   headers={"Authorization": f"Bearer {token}"})
        assert revoked.status_code == 403


async def test_full_hub_to_source_api_with_real_acl_and_database(management_data, monkeypatch):
    """Подменён только HTTP транспорт/выбор config; обе API-ручки и SQL настоящие."""
    from app.routers import management_router
    from app.services import management_overview as aggregation

    d = management_data
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = base64.b64encode(private_key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode()
    public = base64.b64encode(private_key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    # У hub текущая компания B, у источника A: UUID привязаны явно на обеих сторонах.
    hub_config = ManagementConfig(enabled=True, hub_enabled=True, code="hub", name="Управление",
        signing_private_key_b64=private, sources=[{
            "code": "customer", "name": "Источник клиента", "base_url": "https://customer.invalid",
            "company_id": d["cid"], "company_name": "Доверенное название компании",
            "grants": [{"id": "full-path", "local_user_id": d["reader"].id,
                        "local_company_id": d["other_cid"], "remote_user_id": d["reader"].id,
                        "kinds": ["tasks"]}]}])
    source_config = ManagementConfig(enabled=True, hub_enabled=False, code="customer",
        trusted_issuers=[{"issuer": "hub", "public_key_b64": public, "grants": [{
            "id": "full-path", "actor_user_id": d["reader"].id,
            "actor_company_id": d["other_cid"], "user_id": d["reader"].id,
            "company_id": d["cid"], "kinds": ["tasks"]}]}])
    request_config = ContextVar("management_test_config", default=hub_config)
    monkeypatch.setattr(management_router, "load_config", request_config.get)
    hub_app, source_app = FastAPI(), FastAPI()
    hub_app.include_router(management_router.router, prefix="/api")
    source_app.include_router(management_router.router, prefix="/api")
    source_requests = []

    class SourceTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            assert request.url.host == "customer.invalid"
            assert request.url.path == "/api/management/source-overview"
            assert request.headers["authorization"] != headers(d)["Authorization"]
            assert "x-company-id" not in request.headers
            source_requests.append(request.url.path)
            context = request_config.set(source_config)
            try:
                return await ASGITransport(app=source_app).handle_async_request(request)
            finally:
                request_config.reset(context)

    # Hub использует настоящий AsyncClient, но вместо сети попадает во второе ASGI.
    monkeypatch.setattr(aggregation.httpx, "AsyncClient", lambda **kwargs: AsyncClient(
        **kwargs, transport=SourceTransport()))
    async with AsyncClient(transport=ASGITransport(app=hub_app), base_url="http://hub") as client:
        result = await client.get("/api/management/overview", params={"kind": "tasks"},
                                  headers=headers(d, cid=d["other_cid"]))
        assert result.status_code == 200, result.text
        data = result.json()
        assert [(s["code"], s["state"]) for s in data["sources"]] == [("hub", "ok"), ("customer", "ok")], data
        assert {i["title"] for i in data["items"] if i["source"]["code"] == "hub"} == {"other-company"}
        remote = [i for i in data["items"] if i["source"]["code"] == "customer"]
        assert {i["title"] for i in remote} == {
            "public", "private-author", "private-assignee", "private-watcher", "private-participant"}
        assert all(i["source"]["company_id"] == str(d["cid"])
                   and i["href"].startswith("https://customer.invalid/docs/work?") for i in remote)
        assert len({i["id"] for i in data["items"]}) == 6
        # Приёмник отзывает grant; следующая сборка остаётся частично полезной.
        source_config.trusted_issuers[0].grants.clear()
        partial = await client.get("/api/management/overview", params={"kind": "tasks"},
                                   headers=headers(d, cid=d["other_cid"]))
        assert partial.status_code == 200, partial.text
        assert [i["title"] for i in partial.json()["items"]] == ["other-company"]
        assert partial.json()["sources"][1]["state"] == "forbidden"
        assert source_requests == ["/api/management/source-overview"] * 2
