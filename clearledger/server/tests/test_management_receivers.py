"""Explicit aliases for multiple companies of one pinned management receiver."""
import base64
from contextvars import ContextVar
import uuid

import httpx
import jwt
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.routers import management_router
from app.services import management_delegation as delegation, management_overview as aggregation
from app.services.management_config import ManagementConfig, RemoteSource
from test_management_api import headers, management_data  # noqa: F401
from test_management_unit import signing_keys  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")


def configs(d, keys):
    sources, inbound = [], []
    for alias, company in [("office-a", d["cid"]), ("office-b", d["other_cid"])]:
        sources.append({"code": alias, "receiver_code": "office", "name": alias,
            "base_url": "https://office.invalid", "company_id": company, "company_name": alias,
            "grants": [{"id": alias, "local_user_id": d["reader"].id,
                        "local_company_id": d["cid"], "remote_user_id": d["reader"].id, "kinds": ["tasks"]}]})
        inbound.append({"id": alias, "actor_user_id": d["reader"].id,
                        "actor_company_id": d["cid"], "user_id": d["reader"].id,
                        "company_id": company, "kinds": ["tasks"]})
    hub = ManagementConfig(enabled=True, hub_enabled=True, code="desk", signing_private_key_b64=keys[1], sources=sources)
    receiver = ManagementConfig(enabled=True, code="office", trusted_issuers=[{
        "issuer": "desk", "public_key_b64": keys[2], "grants": inbound}])
    return hub, receiver


@pytest.mark.parametrize("receiver_code", [None, "office"])
async def test_legacy_audience_and_explicit_receiver_are_exact(signing_keys, receiver_code):
    source = RemoteSource(code="office-a", receiver_code=receiver_code, name="A", base_url="https://office.invalid",
        company_id=uuid.uuid4(), company_name="A", grants=[{"id": "grant", "local_user_id": uuid.uuid4(),
        "local_company_id": uuid.uuid4(), "remote_user_id": uuid.uuid4(), "kinds": ["tasks"]}])
    if receiver_code is None:
        # Old serialized config without the new field must remain fully valid.
        raw = source.model_dump(exclude={"receiver_code"})
        source = RemoteSource.model_validate(raw)
    hub = ManagementConfig(code="desk", signing_private_key_b64=signing_keys[1])
    token = delegation.sign_access(hub, source, source.grants[0], "tasks")
    claims = jwt.decode(token, base64.b64decode(signing_keys[2]), algorithms=["RS256"],
                        audience="management:" + (receiver_code or source.code), issuer="desk")
    assert claims["aud"] == "management:" + (receiver_code or source.code)
    assert claims["target_company_id"] == str(source.company_id)


@pytest.mark.parametrize("invalid", ["https://office.invalid", "office/", "Office", "", "*"])
async def test_receiver_code_is_an_explicit_code(invalid):
    with pytest.raises(ValidationError):
        RemoteSource(code="office-a", receiver_code=invalid, name="A", base_url="https://office.invalid",
                     company_id=uuid.uuid4(), company_name="A")


async def test_same_record_uuid_keeps_two_aliases_and_company_identities(management_data, signing_keys, monkeypatch):
    d = management_data
    hub, _ = configs(d, signing_keys)
    record = uuid.uuid4()
    seen = []

    def reply(request):
        claims = jwt.decode(request.headers["authorization"][7:], base64.b64decode(signing_keys[2]),
                            algorithms=["RS256"], audience="management:office", issuer="desk")
        seen.append((claims["grant_id"], claims["target_company_id"]))
        return httpx.Response(200, json={"fetched_at": aggregation.now().isoformat(), "truncated": False,
            "items": [{"source_id": str(record), "kind": "tasks", "title": "same UUID"}]})

    monkeypatch.setattr(aggregation.httpx, "AsyncClient", lambda **kw: AsyncClient(**kw, transport=httpx.MockTransport(reply)))
    context = ContextVar("alias_config", default=hub)
    monkeypatch.setattr(management_router, "load_config", context.get)
    isolated = FastAPI();isolated.include_router(management_router.router, prefix="/api")
    async with AsyncClient(transport=ASGITransport(app=isolated), base_url="http://hub") as client:
        response = await client.get("/api/management/overview", headers=headers(d), params={"kind": "tasks"})
    assert response.status_code == 200
    items = [item for item in response.json()["items"] if item["source"]["code"].startswith("office-")]
    assert len(items) == len({item["id"] for item in items}) == 2
    assert {item["source_id"] for item in items} == {str(record)}
    assert {(item["source"]["code"], item["source"]["company_id"]) for item in items} == set(seen)
    assert all(item["href"].startswith("https://office.invalid/docs/work?") for item in items)


async def test_two_company_aliases_use_real_receiver_grants_and_sql(management_data, signing_keys, monkeypatch):
    d = management_data
    hub, receiver = configs(d, signing_keys)
    context = ContextVar("multi_company_config", default=hub)
    monkeypatch.setattr(management_router, "load_config", context.get)
    hub_app, source_app = FastAPI(), FastAPI()
    for app in (hub_app, source_app): app.include_router(management_router.router, prefix="/api")

    class ReceiverTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            assert request.url.host == "office.invalid"
            marker = context.set(receiver)
            try: return await ASGITransport(app=source_app).handle_async_request(request)
            finally: context.reset(marker)

    monkeypatch.setattr(aggregation.httpx, "AsyncClient", lambda **kw: AsyncClient(**kw, transport=ReceiverTransport()))
    async with AsyncClient(transport=ASGITransport(app=hub_app), base_url="http://hub") as client:
        response = await client.get("/api/management/overview", headers=headers(d), params={"kind": "tasks"})
        assert response.status_code == 200
        payload = response.json()
        assert {x["code"]:x["state"] for x in payload["sources"]} == {"desk":"ok", "office-a":"ok", "office-b":"ok"}
        a = [item for item in payload["items"] if item["source"]["code"] == "office-a"]
        b = [item for item in payload["items"] if item["source"]["code"] == "office-b"]
        assert {item["title"] for item in a} == {"public", "private-author", "private-assignee", "private-watcher", "private-participant"}
        assert {item["title"] for item in b} == {"other-company"}
        assert {item["source"]["company_id"] for item in a} == {str(d["cid"])}
        assert {item["source"]["company_id"] for item in b} == {str(d["other_cid"])}
        receiver.trusted_issuers[0].grants.pop()
        revoked = await client.get("/api/management/overview", headers=headers(d), params={"kind":"tasks"})
        assert {x["code"]:x["state"] for x in revoked.json()["sources"]} == {"desk":"ok", "office-a":"ok", "office-b":"forbidden"}
        assert not any(item["source"]["code"] == "office-b" for item in revoked.json()["items"])


@pytest.mark.parametrize("changed", ["company", "grant", "kind", "audience"])
async def test_alias_cannot_change_receiver_grant_binding(management_data, signing_keys, monkeypatch, changed):
    d = management_data
    hub, receiver = configs(d, signing_keys)
    source = hub.sources[0]
    token = delegation.sign_access(hub, source, source.grants[0], "tasks")
    claims = jwt.decode(token, options={"verify_signature":False})
    claims.update({"company":{"target_company_id":str(d["other_cid"])},
                   "grant":{"grant_id":"office-b"}, "kind":{"kind":"calendar"},
                   "audience":{"aud":"management:office-a"}}[changed])
    token = jwt.encode(claims, signing_keys[0], algorithm="RS256", headers={"typ":delegation.TOKEN_TYPE})
    monkeypatch.setattr(management_router, "load_config", lambda:receiver)
    isolated = FastAPI();isolated.include_router(management_router.router, prefix="/api")
    async with AsyncClient(transport=ASGITransport(app=isolated), base_url="http://source") as client:
        response = await client.get("/api/management/source-overview", params={"kind":"tasks"},
                                    headers={"Authorization":"Bearer "+token})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert "items" not in response.json()
