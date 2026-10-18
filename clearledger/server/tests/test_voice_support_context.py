"""Межприложенный контекст: точная карта, чужой номер и отказ upstream."""
import json
import threading
import uuid
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from sqlalchemy import select

from app.models import App, AppCompanyLink
from app.services import app_registry
from tests.test_voice_core import _company, _key, _seed_caller, _voice
from tests.test_voice_tokens import sso_key  # noqa: F401 — fixture ключа RS256

pytestmark = pytest.mark.asyncio(loop_scope="session")


@asynccontextmanager
async def support_map(db, cid):
    await app_registry.seed_apps(db)
    app = (await db.execute(select(App).where(App.code == "support"))).scalar_one()
    await app_registry.set_app(db, cid, app.id, True)
    old_config = app.config
    link = (await db.execute(select(AppCompanyLink).where(
        AppCompanyLink.app_id == app.id, AppCompanyLink.company_id == cid,
    ))).scalar_one_or_none()
    old_external = link.external_company_id if link else None
    external = str(uuid.uuid4())
    if link:
        link.external_company_id = external
    else:
        link = AppCompanyLink(app_id=app.id, company_id=cid, external_company_id=external)
        db.add(link)
    await db.commit()
    try:
        yield app, external
    finally:
        app.config = old_config
        if old_external:
            link.external_company_id = old_external
        else:
            await db.delete(link)
        await db.commit()


async def test_support_context_keeps_exact_company_and_legacy_shapes(client, db):
    own = await _company(db, "gig")
    foreign = await _company(db, "rushydro")
    await _voice(db, own.id, True)
    key = await _key(db, own.id, ["voice.identify"])
    phone = f"+7900{uuid.uuid4().int % 10**7:07d}"
    seeded = await _seed_caller(db, own, phone)
    await _seed_caller(db, foreign, phone)
    async with support_map(db, own.id) as (_app, support_id):
        body = {"supportCompanyId": support_id, "phone": phone, "detail": True,
                "limit": 2, "phones": [phone, "8" + phone[2:]]}
        r = await client.post("/api/eco/support/customer-context", json=body,
                              headers={"X-Cloud-API-Key": key})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["coreCompanyId"] == str(own.id) and data["supportCompanyId"] == support_id
        assert data["corePartyRef"] == f"ezs:{seeded['ext']}"
        assert data["availability"] == "available"
        assert data["charging"]["sessions"] == 3
        assert data["charging"]["kwh"] == 41.5
        assert data["charging"]["sessions_30d"] == 2
        assert data["ezs"]["graded"] == 3 and data["ezs"]["failed"] == 1
        assert data["details"]["total"] == 3 and len(data["details"]["sessions"]) == 2
        assert data["details"]["limit"] == 2
        assert {o["ref"] for o in data["objects"]} == {seeded["loc"]}
        assert phone not in r.text

        body["supportCompanyId"] = str(uuid.uuid4())
        r = await client.post("/api/eco/support/customer-context", json=body,
                              headers={"X-Cloud-API-Key": key})
        assert r.status_code == 403, r.text
        r = await client.post("/api/eco/support/customer-context", json=body)
        assert r.status_code == 422, r.text
        assert any(error["loc"] == ["header", "X-Cloud-API-Key"] for error in r.json()["detail"])
        body["supportCompanyId"] = support_id
        await app_registry.set_app(db, own.id, _app.id, False)
        r = await client.post("/api/eco/support/customer-context", json=body,
                              headers={"X-Cloud-API-Key": key})
        assert r.status_code == 403 and "Поддержка" in r.json()["detail"]
        await app_registry.set_app(db, own.id, _app.id, True)


async def test_support_context_unknown_and_unmapped_are_distinct(client, db):
    own = await _company(db, "gig")
    await _voice(db, own.id, True)
    key = await _key(db, own.id, ["voice.identify"])
    async with support_map(db, own.id) as (_app, support_id):
        body = {"supportCompanyId": support_id, "phone": "+79000009998"}
        r = await client.post("/api/eco/support/customer-context", json=body,
                              headers={"X-Cloud-API-Key": key})
        assert r.status_code == 200, r.text
        assert r.json()["availability"] == "available"
        assert r.json()["caller"] is None and r.json()["charging"] is None
    r = await client.post("/api/eco/support/customer-context", json=body,
                          headers={"X-Cloud-API-Key": key})
    assert r.status_code == 403, r.text


async def test_node_summary_reads_support_with_signed_tenant_and_fails_partial(client, db, sso_key):
    own = await _company(db, "gig")
    foreign = await _company(db, "rushydro")
    await _voice(db, own.id, True)
    key = await _key(db, own.id, ["voice.identify"])
    phone = f"+7900{uuid.uuid4().int % 10**7:07d}"
    seeded = await _seed_caller(db, own, phone)
    await _seed_caller(db, foreign, phone)
    seen = []
    state = {"status": 200, "body": {"availability": "available", "tickets": [
        {"ref": "support:ticket-1", "number": "TS-TEST-1", "title": "Тестовая заявка",
         "status": "open", "objectRef": seeded["loc"], "audio": "MUST-NOT-RELAY"},
    ]}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, self.headers.get("Authorization"),
                         json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            raw = json.dumps(state["body"]).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        async with support_map(db, own.id) as (app, support_id):
            app.config = {**(app.config or {}), "internalUrl": f"http://127.0.0.1:{server.server_port}"}
            await db.commit()
            async def summary():
                return await client.post("/api/eco/ezs/customer-summary", json={"phone": phone},
                                         headers={"X-Cloud-API-Key": key})

            r = await summary()
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["ticketAvailability"] == "available"
            assert data["tickets"][0]["number"] == "TS-TEST-1"
            assert "MUST-NOT-RELAY" not in r.text
            path, header, body = seen[-1]
            assert path == "/api/v1/eco/voice/context"
            claims = jwt.decode(header.removeprefix("Bearer "), sso_key, algorithms=["RS256"], audience="support")
            assert claims["cid"] == support_id and claims["svc"] == "voice.context"
            assert claims["exp"] - claims["iat"] == 120 and claims["jti"]
            assert body["objectRefs"] == [seeded["loc"]] and "companyId" not in body

            for status_code, payload in [(503, {}), (200, []), (200, {"tickets": []}),
                                         (200, {"availability": "available", "tickets": [{"bad": "data"}]})]:
                state.update(status=status_code, body=payload)
                r = await summary()
                assert r.status_code == 200, r.text
                assert r.json()["ticketAvailability"] == "unavailable" and r.json()["tickets"] == []
                assert r.json()["sessions"], "отказ Поддержки не стирает данные Ядра"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
