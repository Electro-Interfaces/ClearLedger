"""Offline: подпись, привязки, фильтрация каталога, безопасная проекция и даты."""
import base64
import json
import time
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from pydantic import ValidationError

from app.services import management_delegation as delegation
from app.services import management_overview as aggregation
from app.services.management_config import (
    ManagementConfig, ManagementConfigError, RemoteSource, load_config,
)
from app.services.management_schemas import ManagementRecord


@pytest.fixture(scope="module")
def signing_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, base64.b64encode(private).decode(), base64.b64encode(public).decode()


@pytest.fixture
def link(signing_keys):
    actor, company, remote_user, remote_company = (uuid.uuid4() for _ in range(4))
    source = RemoteSource(code="remote", name="Источник", base_url="https://source.invalid",
                          company_id=remote_company, company_name="Компания источника", grants=[{
                              "id": "grant-one", "local_user_id": actor,
                              "local_company_id": company, "remote_user_id": remote_user,
                              "kinds": ["chats", "tasks", "calendar"]}])
    hub = ManagementConfig(enabled=True, hub_enabled=True, code="desk", signing_private_key_b64=signing_keys[1],
                           sources=[source])
    receiver = ManagementConfig(enabled=True, code="remote", trusted_issuers=[{
        "issuer": "desk", "public_key_b64": signing_keys[2], "grants": [{
            "id": "grant-one", "actor_user_id": actor, "actor_company_id": company,
            "user_id": remote_user, "company_id": remote_company,
            "kinds": ["chats", "tasks", "calendar"]}]}])
    return hub, source, receiver


def token_for(link, changes=None, *, key=None):
    hub, source, _ = link
    token = delegation.sign_access(hub, source, source.grants[0], "tasks")
    if changes is None:
        return token
    claims = jwt.decode(token, options={"verify_signature": False})
    claims.update(changes)
    return jwt.encode(claims, key or base64.b64decode(hub.signing_private_key_b64),
                      algorithm="RS256", headers={"typ": delegation.TOKEN_TYPE})


@pytest.mark.parametrize("changes", [
    {"iss": "unknown"}, {"aud": "management:other"}, {"scope": "all"},
    {"kind": "chats"}, {"sub": str(uuid.uuid4())},
    {"actor_company_id": str(uuid.uuid4())}, {"target_user_id": str(uuid.uuid4())},
    {"target_company_id": str(uuid.uuid4())}, {"grant_id": "not-granted"},
    {"exp": 1}, {"exp": int(time.time()) + 600}, {"nbf": int(time.time()) + 10},
    {"iat": 0}, {"exp": str(int(time.time()) + 50)},
])
async def test_reject_invalid_delegation(link, changes):
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await delegation.verify_access(token_for(link, changes), "tasks", link[2], db)
    assert exc.value.status_code == 403
    db.get.assert_not_called()


async def test_signature_kind_and_revocation(link, signing_keys, monkeypatch):
    db = AsyncMock()
    another = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_key = another.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())
    with pytest.raises(HTTPException):
        await delegation.verify_access(token_for(link, {}, key=wrong_key), "tasks", link[2], db)
    token = token_for(link)
    receiver = link[2].model_copy(deep=True)
    receiver.trusted_issuers[0].grants[0].kinds = ["chats"]
    with pytest.raises(HTTPException):
        await delegation.verify_access(token, "tasks", receiver, db)
    receiver.trusted_issuers[0].grants = []
    with pytest.raises(HTTPException):
        await delegation.verify_access(token, "tasks", receiver, db)
    user = SimpleNamespace(id=link[1].grants[0].remote_user_id, mail_only=False,
                           email="explicit@test.invalid")
    monkeypatch.setattr(delegation, "assert_company_member", AsyncMock())
    db.get.side_effect = [user, None]
    with pytest.raises(HTTPException):
        await delegation.verify_access(token, "tasks", link[2], db)
    db.get.side_effect = [user, object()]
    result = await delegation.verify_access(token, "tasks", link[2], db)
    assert result.user is user
    assert result.company_id == link[1].company_id
    for unusable in (None, SimpleNamespace(mail_only=True),
                     SimpleNamespace(mail_only=False, email="robot@space.local")):
        db.get.side_effect = None
        db.get.return_value = unusable
        with pytest.raises(HTTPException):
            await delegation.verify_access(token, "tasks", link[2], db)


async def test_missing_claims_type_and_algorithm_are_rejected(link):
    token = token_for(link)
    claims = jwt.decode(token, options={"verify_signature": False})
    key = base64.b64decode(link[0].signing_private_key_b64)
    for field in ("exp", "nbf", "iat", "jti", "sub", "grant_id", "target_company_id"):
        incomplete = {k: v for k, v in claims.items() if k != field}
        bad = jwt.encode(incomplete, key, algorithm="RS256", headers={"typ": delegation.TOKEN_TYPE})
        with pytest.raises(HTTPException):
            await delegation.verify_access(bad, "tasks", link[2], AsyncMock())
    wrong_type = jwt.encode(claims, key, algorithm="RS256", headers={"typ": "JWT"})
    hs = jwt.encode(claims, "not-a-source-key", algorithm="HS256", headers={"typ": delegation.TOKEN_TYPE})
    for bad in (wrong_type, hs, "malformed", "x" * 16385):
        with pytest.raises(HTTPException):
            await delegation.verify_access(bad, "tasks", link[2], AsyncMock())
    disabled = link[2].model_copy(update={"enabled": False})
    with pytest.raises(HTTPException):
        await delegation.verify_access(token, "tasks", disabled, AsyncMock())


def test_config_fail_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("MANAGEMENT_CONFIG_PATH", raising=False)
    assert load_config().enabled is False
    path = tmp_path / "config.json"
    path.write_text('{"enabled":true,"sources":"broken"}')
    monkeypatch.setenv("MANAGEMENT_CONFIG_PATH", str(path))
    with pytest.raises(ManagementConfigError):
        load_config()
    path.unlink()
    with pytest.raises(ManagementConfigError):
        load_config()


@pytest.mark.parametrize("base", ["http://source.invalid", "https://user:pass@source.invalid",
                                  "https://source.invalid/api", "https://source.invalid#fragment",
                                  "javascript:alert(1)", "https://source.invalid/?token=secret",
                                  "https://source.invalid\\evil", "https://source.invalid:bad"])
def test_source_origin_validation(link, base):
    with pytest.raises(ValidationError):
        RemoteSource.model_validate({**link[1].model_dump(), "base_url": base})


def test_day_bounds_and_dst():
    start, end = aggregation.calendar_bounds("calendar", date(2026, 10, 24),
                                              date(2026, 10, 24), "Europe/Moscow")
    assert start.isoformat() == "2026-10-23T21:00:00+00:00"
    assert end.isoformat() == "2026-10-24T21:00:00+00:00"
    start, end = aggregation.calendar_bounds("calendar", date(2026, 10, 25),
                                              date(2026, 10, 25), "Europe/Berlin")
    assert (end - start).total_seconds() == 25 * 3600
    for start_day, end_day, zone in [(None, None, "Europe/Moscow"),
                                      (date(2026, 10, 25), date(2026, 10, 24), "UTC"),
                                      (date(2026, 10, 24), date(2026, 10, 24), "unknown")]:
        with pytest.raises(HTTPException):
            aggregation.calendar_bounds("calendar", start_day, end_day, zone)


def mock_remote(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(aggregation.httpx, "AsyncClient", lambda **kw: original(
        **kw, transport=httpx.MockTransport(handler)))


async def test_remote_metadata_and_href_are_untrusted(link, monkeypatch):
    sid = uuid.uuid4()
    def handler(request):
        assert request.url.path == "/api/management/source-overview"
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(200, json={"fetched_at": datetime.now(timezone.utc).isoformat(),
            "truncated": False, "items": [{"source_id": str(sid), "kind": "tasks", "title": "Visible",
              "href": "https://evil.invalid/", "source": {"company_id": "foreign", "code": "fake"}}]})
    mock_remote(monkeypatch, handler)
    items, status = await aggregation.fetch_remote(link[0], link[1], link[1].grants[0], "tasks",
                                                  {"kind": "tasks", "limit": 10}, 10)
    assert status.state == "ok"
    assert items[0].source.code == "remote"
    assert items[0].source.company_id == str(link[1].company_id)
    assert items[0].href.startswith("https://source.invalid/docs/work?")
    assert f"task={sid}" in items[0].href and "evil" not in items[0].href


@pytest.mark.parametrize("http_status,state", [(403, "forbidden"), (401, "forbidden"),
                                               (500, "error"), (302, "error"),
                                               (404, "not_configured"), (503, "not_configured")])
async def test_remote_error_sanitized(link, monkeypatch, http_status, state):
    mock_remote(monkeypatch, lambda request: httpx.Response(http_status,
                text="internal https://secret.local token=secret", headers={"location": "https://evil.invalid"}))
    items, status = await aggregation.fetch_remote(link[0], link[1], link[1].grants[0], "tasks", {}, 10)
    assert not items and status.state == state
    assert "secret" not in status.model_dump_json() and "local" not in (status.error or "")


@pytest.mark.parametrize("case", ["wrong-kind", "wrong-id", "duplicate", "over-limit", "future", "naive", "oversize", "invalid-json"])
async def test_remote_contract_errors_fail_closed(link, monkeypatch, case):
    row = {"source_id": str(uuid.uuid4()), "kind": "tasks", "title": "Allowed"}
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(), "truncated": False, "items": [row]}
    if case == "wrong-kind":
        row["kind"] = "calendar"
    elif case == "wrong-id":
        row["source_id"] = "../../evil?token=secret"
    elif case in ("duplicate", "over-limit"):
        payload["items"].append({**row, "source_id": row["source_id"] if case == "duplicate" else str(uuid.uuid4())})
    elif case == "future":
        payload["fetched_at"] = "2099-01-01T00:00:00Z"
    elif case == "naive":
        payload["fetched_at"] = "2026-10-24T00:00:00"
    raw = json.dumps(payload)
    if case == "oversize":
        raw = "x" * 2_000_001
    elif case == "invalid-json":
        raw = "invalid internal secret address"
    mock_remote(monkeypatch, lambda request: httpx.Response(200, text=raw))
    items, status = await aggregation.fetch_remote(link[0], link[1], link[1].grants[0], "tasks", {},
                                                  1 if case == "over-limit" else 10)
    assert not items and status.state == "error"
    assert "secret" not in status.model_dump_json()


async def test_remote_missing_credentials_and_timeout(link, monkeypatch):
    hub = link[0].model_copy(update={"signing_private_key_b64": ""})
    items, status = await aggregation.fetch_remote(hub, link[1], link[1].grants[0], "tasks", {}, 10)
    assert not items and status.state == "not_configured"
    def timeout(request):
        raise httpx.ReadTimeout("private source address", request=request)
    mock_remote(monkeypatch, timeout)
    items, status = await aggregation.fetch_remote(link[0], link[1], link[1].grants[0], "tasks", {}, 10)
    assert not items and status.state == "error"


async def test_overview_partial_catalog_and_limit(link, monkeypatch):
    hub, source, _ = link
    actor, cid = source.grants[0].local_user_id, source.grants[0].local_company_id
    hidden = source.model_copy(deep=True)
    hidden.code = "hidden"
    hidden.grants[0].local_user_id = uuid.uuid4()
    hub.sources.append(hidden)
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(name="Локальная компания", short_name=None)
    records = [ManagementRecord(source_id=uuid.uuid4(), kind="tasks", title="Локальная",
                                updated_at=datetime.now(timezone.utc))]
    local = AsyncMock(return_value=(records, True))
    monkeypatch.setattr(aggregation, "read_local", local)
    mock_remote(monkeypatch, lambda request: httpx.Response(500, text="private server error"))
    result = await aggregation.overview(hub, db, SimpleNamespace(id=actor), cid,
        "tasks", "all", "needle", None, None, "Europe/Moscow", 1)
    assert len(result.items) == 1 and result.truncated
    assert [(s.code, s.state) for s in result.sources] == [("desk", "ok"), ("remote", "error")]
    assert local.await_args.kwargs["query"] == "needle"
    with pytest.raises(HTTPException) as exc:
        await aggregation.overview(hub, db, SimpleNamespace(id=actor), cid,
            "tasks", "hidden", "", None, None, "UTC", 1)
    assert exc.value.status_code == 404
    hub.enabled = False
    disabled = await aggregation.overview(hub, db, SimpleNamespace(id=actor), cid,
        "tasks", "all", "", None, None, "UTC", 1)
    assert not disabled.enabled and not disabled.items and not disabled.sources
