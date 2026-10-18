"""Опубликованная база своей компании через отдельный короткий служебный токен."""
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest

from app.services import app_registry
from tests.test_voice_core import _company, _key, _voice
from tests.test_voice_support_context import support_map
from tests.test_voice_tokens import sso_key  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_knowledge_relay_is_tenant_scoped_bounded_and_fail_closed(client, db, sso_key):
    own = await _company(db, "gig")
    await _voice(db, own.id, True)
    key = await _key(db, own.id, ["voice.identify"])
    wrong_key = await _key(db, own.id, ["voice.stats"])
    ref = f"support:article:{uuid.uuid4()}"
    seen = []
    state = {"status": 200, "body": {"availability": "available", "items": [
        {"ref": ref, "title": "Проверка соединения", "content": "Проверьте кабель.",
         "visibility": "cc", "version": 2, "audio": "MUST-NOT-RELAY", "company_id": "untrusted"},
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

            async def request(body=None, token=key):
                return await client.post("/api/eco/support/knowledge", json=body or {"topic": "connection", "limit": 3},
                                         headers={"X-Cloud-API-Key": token})

            r = await request()
            assert r.status_code == 200, r.text
            assert r.json() == {"availability": "available", "items": [
                {"ref": ref, "title": "Проверка соединения", "content": "Проверьте кабель.", "visibility": "cc", "version": 2}]}
            assert r.headers["cache-control"] == "no-store"
            path, bearer, payload = seen[-1]
            assert path == "/api/v1/eco/voice/knowledge"
            assert payload == {"topic": "connection", "limit": 3}
            claims = jwt.decode(bearer.split(" ", 1)[1], options={"verify_signature": False})
            assert claims["aud"] == "support" and claims["svc"] == "voice.knowledge" and claims["cid"] == support_id
            assert claims["jti"] and 0 < claims["exp"] - claims["iat"] <= 120
            before = len(seen)
            assert (await request(token=wrong_key)).status_code == 403
            assert (await request({"topic": "connection", "company_id": str(uuid.uuid4())})).status_code == 422
            assert (await request({"topic": "connection", "limit": 4})).status_code == 422
            assert (await request({"topic": ""})).status_code == 422
            assert len(seen) == before
            await _voice(db, own.id, False)
            assert (await request()).status_code == 403
            await _voice(db, own.id, True)
            await app_registry.set_app(db, own.id, app.id, False)
            assert (await request()).json() == {"availability": "unavailable", "items": []}
            assert len(seen) == before
            await app_registry.set_app(db, own.id, app.id, True)
            state["body"] = {"availability": "unavailable", "reason": "topic_unconfigured", "items": []}
            assert (await request()).json() == state["body"]
            for body in [
                {"availability": "available", "items": [{"ref": ref, "title": "Secret", "content": "x", "visibility": "internal", "version": 1}]},
                {"availability": "available", "items": [{"ref": ref, "title": "Long", "content": "x" * 16001, "visibility": "public", "version": 1}]},
                {"availability": "available", "items": [{"ref": ref, "title": "Bad", "content": "x", "visibility": "public", "version": True}]},
                {"availability": "available", "items": [None]},
                {"availability": "available", "items": [], "debug": "MUST-NOT-RELAY"},
            ]:
                state["body"] = body
                r = await request()
                assert r.status_code == 200
                if body["items"]:
                    assert r.json() == {"availability": "unavailable", "items": []}
                else:
                    assert r.json() == {"availability": "available", "items": []}
            state["status"] = 503
            assert (await request()).json() == {"availability": "unavailable", "items": []}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
