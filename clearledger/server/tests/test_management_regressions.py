"""Регрессии ISSUE-001/004/005 через настоящий SQL и ASGI management API."""
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.main import app
from app.models import CalendarEvent, ChatParticipant, ChatRoom, Task
from app.routers import management_router
from app.services.management_config import ManagementConfig, RemoteSource
from app.services.management_delegation import sign_access
from tests.test_management_api import headers, management_data  # noqa: F401 — общая SQL-фикстура

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def source_headers(management_data):
    """Настоящий подписанный grant к синтетическому локальному источнику."""
    d = management_data
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = base64.b64encode(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode()
    public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    actor, actor_company = uuid.uuid4(), uuid.uuid4()
    source = RemoteSource(code="desk", name="Test", base_url="https://source.invalid",
        company_id=d["cid"], company_name="Test", grants=[{
            "id": "regression", "local_user_id": actor, "local_company_id": actor_company,
            "remote_user_id": d["reader"].id, "kinds": ["tasks", "calendar", "chats"]}])
    hub = ManagementConfig(enabled=True, hub_enabled=True, code="hub", signing_private_key_b64=private)
    d["path"].write_text(json.dumps({**d["config"], "trusted_issuers": [{
        "issuer": "hub", "public_key_b64": public, "grants": [{
            "id": "regression", "actor_user_id": str(actor), "actor_company_id": str(actor_company),
            "user_id": str(d["reader"].id), "company_id": str(d["cid"]),
            "kinds": ["tasks", "calendar", "chats"]}]}]}))
    return lambda kind: {"Authorization": "Bearer " + sign_access(hub, source, source.grants[0], kind)}


@pytest.mark.parametrize("kind", ["tasks", "calendar", "chats"])
@pytest.mark.parametrize("query", ["%", "_", "\\", r"\%_", "50\\", "бюДЖет", "СмЕтА", "MIX", "нет-совпадений", "' OR"])
async def test_literal_search_sql_acl_order_and_limit(management_data, source_headers, db, kind, query):
    d = management_data
    titles = ["Бюджет 50% ГОТОВ", "Бюджет 50X готов", "Бюджет 50_ готов",
              r"Бюджет 50\ готов", r"Mix \%_ СМЕТА", "Mix AXZ СМЕТА", "quote ' OR true --"]
    records = []
    for index, title in enumerate(titles):
        moment = datetime(2026, 10, 24, 12, index, tzinfo=timezone.utc)
        if kind == "tasks":
            row = Task(company_id=d["cid"], author_id=d["reader"].id, title=title,
                       visibility="company", status="open", updated_at=moment)
        elif kind == "calendar":
            row = CalendarEvent(company_id=d["cid"], organizer_id=d["reader"].id, title=title,
                visibility="company", status="planned", starts_at=moment,
                ends_at=moment + timedelta(minutes=1), tz="UTC")
        else:
            row = ChatRoom(company_id=d["cid"], name=title, type="group", is_active=True, is_archived=False)
        db.add(row)
        await db.flush()
        if kind == "chats":
            db.add(ChatParticipant(room_id=row.id, user_id=d["reader"].id, role="member"))
            db.add(ChatParticipant(room_id=row.id, user_id=d["admin"].id, role="member"))
        records.append(row)
    # Совпадение по строке не должно открыть соседнюю компанию/личное/чужой чат.
    hidden_title = "HIDDEN " + query
    if kind == "tasks":
        db.add_all([Task(company_id=cid, author_id=d["other"].id, title=hidden_title,
                        visibility=visibility, status="open") for cid, visibility in
                    [(d["cid"], "personal"), (d["other_cid"], "company")]])
        ordered = list(reversed(records))
    elif kind == "calendar":
        db.add_all([CalendarEvent(company_id=cid, organizer_id=d["other"].id, title=hidden_title,
            visibility=visibility, starts_at=moment, ends_at=moment + timedelta(minutes=1),
            tz="UTC", status="planned") for cid, visibility in
            [(d["cid"], "private"), (d["cid"], "personal"), (d["other_cid"], "company")]])
        ordered = records
    else:
        db.add(ChatRoom(company_id=d["cid"], name=hidden_title, type="group", is_active=True))
        ordered = sorted(records, key=lambda row: row.id)
    await db.commit()
    expected = [str(row.id) for row in ordered
                if query.casefold() in (row.name if kind == "chats" else row.title).casefold()]
    params = {"kind": kind, "query": query}
    if kind == "calendar":
        params.update(date_from="2026-10-24", date_to="2026-10-24", time_zone="UTC")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for endpoint, auth in [("overview", headers(d)), ("overview", headers(d, "admin")),
                               ("source-overview", source_headers(kind))]:
            for limit in (1, 100):
                response = await client.get("/api/management/" + endpoint, headers=auth,
                                            params={**params, "limit": limit})
                assert response.status_code == 200, response.text
                data = response.json()
                if endpoint == "overview":
                    assert data["sources"][0]["state"] == "ok", data
                assert [row["source_id"] for row in data["items"]] == expected[:limit], data
                assert data["truncated"] == (len(expected) > limit)
                assert response.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize("endpoint", ["status", "overview", "source-overview"])
@pytest.mark.parametrize("status", [401, 403, 404, 422, 503])
async def test_route_policy_includes_dependency_errors_and_keeps_handlers(endpoint, status):
    """Подключение роутера сохраняет route_class; ошибки Depends обрабатывает FastAPI."""
    isolated = FastAPI()
    isolated.include_router(management_router.router, prefix="/api")

    async def denied():
        raise HTTPException(status, "Отказ зависимости", headers={"X-Reason": "dependency"})

    # Оба Depends выполняются до входа в endpoint, включая source-overview.
    dependency = management_router.get_db if endpoint == "source-overview" else get_current_user
    isolated.dependency_overrides[dependency] = denied
    async with AsyncClient(transport=ASGITransport(app=isolated), base_url="http://test") as client:
        response = await client.get("/api/management/" + endpoint, params={"kind": "tasks"})
    assert response.status_code == status
    assert response.json() == {"detail": "Отказ зависимости"}
    assert response.headers["x-reason"] == "dependency"
    assert response.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize("endpoint", ["status", "overview", "source-overview"])
async def test_real_auth_validation_and_config_responses_no_store(management_data, source_headers, endpoint):
    d = management_data
    valid = source_headers("tasks") if endpoint == "source-overview" else headers(d)
    route = "/api/management/" + endpoint
    cases = [(401, {}, {"kind": "tasks"})]
    if endpoint == "source-overview":
        cases += [(403, {"Authorization": "Bearer malformed"}, {"kind": "tasks"})]
    else:
        cases += [(403, headers(d, "admin", d["other_cid"]), {"kind": "tasks"}),
                  (422, {"Authorization": valid["Authorization"]}, {"kind": "tasks"})]
    if endpoint != "status":
        cases += [(422, valid, params) for params in ({}, {"kind": "invalid"},
                  {"kind": "tasks", "limit": 0}, {"kind": "tasks", "limit": 201},
                  {"kind": "tasks", "query": "a" * 201},
                  {"kind": "calendar", "date_from": "not-a-date"})]
    if endpoint == "overview":
        cases += [(404, valid, {"kind": "tasks", "space": "unknown"})]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for status, auth, params in cases:
            response = await client.get(route, headers=auth, params=params)
            assert response.status_code == status, response.text
            assert response.headers.get("cache-control") == "no-store", response.text
        for enabled in (True, False):
            d["path"].write_text(json.dumps({**json.loads(d["path"].read_text()), "hub_enabled": enabled}))
            success = await client.get(route, headers=valid, params={"kind": "tasks"})
            assert success.status_code == 200, success.text
            assert success.headers.get("cache-control") == "no-store"
            if endpoint == "status":
                assert success.json() == {"enabled": enabled}
            elif endpoint == "overview":
                assert success.json()["enabled"] == enabled
                if not enabled:
                    assert success.json()["items"] == success.json()["sources"] == []
        d["path"].write_text('{"sources":"internal-secret-address"}')
        bad = await client.get(route, headers=valid, params={"kind": "tasks"})
        assert bad.status_code == 503
        assert bad.json() == {"detail": "Конфигурация обзора недоступна"}
        assert bad.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize("endpoint", ["overview", "source-overview"])
@pytest.mark.parametrize("first,last,zone,status", [
    ("0001-01-01", "0001-01-01", "Europe/Moscow", 422),
    ("0001-01-01", "0001-01-01", "Etc/GMT-14", 422),
    ("0001-01-01", "0001-01-01", "UTC", 200),
    ("0001-01-01", "0001-01-01", "Etc/GMT+12", 200),
    ("0001-01-01", "0001-01-01", "Pacific/Kiritimati", 200),
    ("9999-12-31", "9999-12-31", "UTC", 422),
    ("9999-12-31", "9999-12-31", "Europe/Moscow", 422),
    ("9999-12-31", "9999-12-31", "Etc/GMT+12", 422),
    ("9999-12-31", "9999-12-31", "Etc/GMT-14", 422),
    ("9999-12-30", "9999-12-30", "Etc/GMT+12", 200),
    ("9999-12-30", "9999-12-30", "Etc/GMT-14", 200),
    ("2026-01-01", "2027-01-02", "Europe/Moscow", 200),
    ("2026-01-01", "2027-01-03", "Europe/Moscow", 422),
    ("2026-03-29", "2026-03-29", "Europe/Berlin", 200),
    ("2026-10-25", "2026-10-25", "Europe/Berlin", 200),
    ("2026-10-24", "2026-10-24", "unknown", 422),
])
async def test_calendar_http_extremes(management_data, source_headers, endpoint, first, last, zone, status):
    auth = source_headers("calendar") if endpoint == "source-overview" else headers(management_data)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as client:
        response = await client.get("/api/management/" + endpoint, headers=auth, params={
            "kind": "calendar", "date_from": first, "date_to": last, "time_zone": zone})
    assert response.status_code == status, response.text
    assert response.headers.get("cache-control") == "no-store"
    if status == 422:
        assert isinstance(response.json()["detail"], str)
        assert "OverflowError" not in response.text and "Traceback" not in response.text
    elif endpoint == "overview":
        assert response.json()["sources"][0]["state"] == "ok", response.text


async def test_source_read_failure_keeps_sanitized_error_and_no_store(management_data, source_headers, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise RuntimeError("internal-secret-address")

    monkeypatch.setattr(management_router, "read_local", unavailable)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/management/source-overview", headers=source_headers("tasks"),
                                    params={"kind": "tasks"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Не удалось прочитать источник"}
    assert response.headers.get("cache-control") == "no-store"
