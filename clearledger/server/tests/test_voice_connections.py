"""Настройки связей: права, каноническая компания, ограничение и очистка ответа."""
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest

from tests.test_voice_core import _company, _key, _voice
from tests.test_voice_support_context import support_map
from tests.test_voice_tokens import _h, _login, _user, sso_key  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_connections_relay_scope_redaction_checks_and_failure(client, db, sso_key):
    own = await _company(db, "gig")
    await _voice(db, own.id, True)
    token = await _login(client, "admin@clearledger.ru", "admin123")
    headers = {**_h(token), "X-Company-Id": str(own.id)}
    seen = []
    state = {"status": 200, "body": {}}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization"), None))
            self.respond()

        def do_POST(self):
            seen.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.respond()

        def respond(self):
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
        async with support_map(db, own.id) as (app, external):
            app.config = {**(app.config or {}), "internalUrl": f"http://127.0.0.1:{server.server_port}"}
            await db.commit()
            connector = str(uuid.uuid4())
            state["body"] = {"company_id": external, "connections": [{
                "id": connector, "provider": "megafon", "enabled": True, "status": "active", "configured": True,
                "endpoint": "https://example.invalid/crmapi/v1?api_key=MUST-NOT-LEAK#secret",
                "sources": {"api_key": "env", "crm_token": "connector", "private": "MUST-NOT-LEAK"},
                "readiness": {"history": {"configured": True, "enabled": True}, "events": {"configured": True, "enabled": True}},
                "webhook_path": "/api/v1/telephony/megafon?token=MUST-NOT-LEAK",
                "last_sync_at": "2026-10-19T10:00:00Z", "last_error": "MUST-NOT-LEAK upstream error",
                "credentials": {"api_key": "MUST-NOT-LEAK"},
            }], "debug": "MUST-NOT-LEAK"}
            r = await client.get("/api/voice/connections", headers=headers)
            assert r.status_code == 200, r.text
            assert r.json()["company_id"] == str(own.id)
            c = r.json()["connections"][0]
            assert c["endpoint"] == "https://example.invalid/crmapi/v1"
            assert c["webhook_path"] is None and c["last_error"]
            assert "MUST-NOT-LEAK" not in r.text and "credentials" not in r.text
            assert r.headers["cache-control"] == "private, no-store"
            claims = jwt.decode(seen[-1][1].removeprefix("Bearer "), options={"verify_signature": False})
            assert claims["cid"] == external and claims["aud"] == "support" and claims["svc"] == "voice.connections"
            assert 0 < claims["exp"] - claims["iat"] <= 120
            state["body"]["connections"][0]["webhook_path"] = "/api/v1/telephony/megafon/event"
            assert (await client.get("/api/voice/connections", headers=headers)).json()["connections"][0]["webhook_path"] == "/api/v1/telephony/megafon/event"
            state["body"]["company_id"] = str(uuid.uuid4())
            assert (await client.get("/api/voice/connections", headers=headers)).status_code == 503
            state["body"] = {"ok": True, "at": "2026-10-19T10:00:00Z", "message": "MUST-NOT-LEAK", "data": "MUST-NOT-LEAK"}
            r = await client.post("/api/voice/connections/check", headers=headers, json={"connector_id": connector})
            assert r.status_code == 200 and r.json()["ok"] is True, r.text
            assert "MUST-NOT-LEAK" not in r.text
            assert seen[-1][2] == {"connector_id": connector}
            assert seen[-1][0] == "/api/v1/eco/voice/connections/check"
            r = await client.post("/api/voice/connections/check", headers=headers, json={"connector_id": None})
            assert r.status_code == 200 and seen[-1][2] == {"connector_id": None}
            before = len(seen)
            assert (await client.post("/api/voice/connections/check", headers=headers, json={"connector_id": connector, "company_id": external})).status_code == 422
            assert len(seen) == before
            state["status"] = 404
            assert (await client.post("/api/voice/connections/check", headers=headers, json={"connector_id": connector})).status_code == 404
            state["status"] = 500
            r = await client.get("/api/voice/connections", headers=headers)
            assert r.status_code == 503 and "MUST-NOT-LEAK" not in r.text
            state["status"] = 200
            state["body"] = {"debug": "x" * 130000}
            assert (await client.get("/api/voice/connections", headers=headers)).status_code == 503

            ordinary = await _user(client, f"connection-{uuid.uuid4().hex[:6]}@example.com", "gig", "user")
            denied = {**_h(ordinary), "X-Company-Id": str(own.id)}
            before = len(seen)
            foreign = await _company(db, "rushydro")
            assert (await client.get("/api/voice/connections", headers={**_h(ordinary), "X-Company-Id": str(foreign.id)})).status_code == 403
            assert len(seen) == before
            for method, path in [("GET", ""), ("POST", "/check")]:
                r = await client.request(method, "/api/voice/connections" + path, headers=denied,
                                         **({"json": {"connector_id": connector}} if method == "POST" else {}))
                assert r.status_code == 403, r.text
            assert len(seen) == before
            await _voice(db, own.id, False)
            assert (await client.get("/api/voice/connections", headers=headers)).status_code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


async def test_node_key_diagnostic_requires_scope_and_enabled_product(client, db):
    own = await _company(db, "gig")
    await _voice(db, own.id, True)
    key = await _key(db, own.id, ["voice.identify"])
    wrong = await _key(db, own.id, ["voice.stats"])
    url = "/api/eco/voice/connection"
    assert (await client.get(url)).status_code == 422  # обязательный заголовок, как в остальных ручках ключа
    assert (await client.get(url, headers={"X-Cloud-API-Key": wrong})).status_code == 403
    r = await client.get(url, headers={"X-Cloud-API-Key": key})
    assert r.status_code == 200 and r.json() == {"status": "ok", "company_id": str(own.id)}
    assert r.headers["cache-control"] == "private, no-store"
    await _voice(db, own.id, False)
    assert (await client.get(url, headers={"X-Cloud-API-Key": key})).status_code == 403
