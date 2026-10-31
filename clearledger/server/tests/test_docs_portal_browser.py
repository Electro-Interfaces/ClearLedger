"""Browser over real local HTTPS M10/docs/product endpoints; no intercepted success."""
import asyncio
import json
import os
from pathlib import Path
import socket
import threading
import subprocess
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import uvicorn

if os.environ.get("RUN_DOCS_PORTAL_BROWSER_TESTS") != "1":
    pytest.skip("RUN_DOCS_PORTAL_BROWSER_TESTS=1 is required", allow_module_level=True)

from tests.test_docs_portal import env, application, SCOPES, DOCS_FLAG, partner_test_safety_error
from app.auth import gate_ok
from app.services import partner_identity as identity, docs_portal as portal

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_real_https_browser_pkce_public_gate_swagger_and_product(env, tmp_path, monkeypatch):
    # env/db guard runs before any fixture can touch another database.
    assert partner_test_safety_error(os.environ, flag=DOCS_FLAG) is None
    # Delivery is outside this acceptance; never send synthetic login notifications.
    async def no_email(*args, **kwargs): pass
    from app.routers import auth_router
    from app.services import notify
    monkeypatch.setattr(auth_router.email_service, "send_notice", no_email)
    monkeypatch.setattr(notify, "dispatch_async", lambda *args, **kwargs: None)
    monkeypatch.setattr(logging.getLogger("httpx"), "level", logging.WARNING)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    origin = f"https://127.0.0.1:{port}"
    monkeypatch.setattr(identity.settings, "partner_oauth_issuer", origin)
    monkeypatch.setattr(portal.settings, "partner_docs_sandbox_api_url", origin + "/api/v1")
    # A separate engine is owned by the uvicorn thread/loop, not conftest's loop.
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = application(factory, origin)
    handshake = tmp_path / "frontend.json"
    mode_file = tmp_path / "docs-mode"
    @app.middleware("http")
    async def test_runtime_configuration(request, call_next):
        # Fixture control changes real settings, never an HTTP response or verifier.
        if mode_file.exists():
            portal.settings.partner_docs_environment = mode_file.read_text()
        return await call_next(request)

    @app.get("/{path:path}")
    async def frontend(path: str, request: Request):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Test surface not mounted"}, status_code=404)
        if not handshake.exists():
            return Response(status_code=503)
        config = json.loads(handshake.read_text())
        headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
        if path.startswith("p/"):
            root = Path(config["publicDir"]).resolve()
            file = (root / path[2:]).resolve()
            if not file.is_relative_to(root) or not file.is_file(): return Response(status_code=404, headers=headers)
            return FileResponse(file, headers=headers)
        async with factory() as db:
            gated = await gate_ok(request.cookies.get("cl_gate"), db)
        is_html = "text/html" in request.headers.get("accept", "")
        if is_html and not gated:
            return FileResponse(Path(config["publicDir"]) / "public.html", media_type="text/html", headers=headers)
        if not gated:
            return Response(status_code=403, headers=headers)
        root = Path(config["mainDir"]).resolve()
        file = root / "index.html" if is_html else (root / path).resolve()
        if not file.is_relative_to(root) or not file.is_file(): return Response(status_code=404, headers=headers)
        return FileResponse(file, headers=headers)

    @asynccontextmanager
    async def close_engine(_app):
        yield
        await engine.dispose()
    app.router.lifespan_context = close_engine

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    import ipaddress
    certificate = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()) \
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1)) \
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1)) \
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False).sign(key, hashes.SHA256())
    cert, private = tmp_path / "localhost.crt", tmp_path / "localhost.key"
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private.chmod(0o600)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, ssl_certfile=str(cert), ssl_keyfile=str(private),
        access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    try:
        for _ in range(100):
            if server.started: break
            await asyncio.sleep(.1)
        assert server.started
        async with AsyncClient(base_url=origin, verify=False) as client:
            headers = {"Authorization": "Bearer " + env["core"]}
            registered = await client.post("/api/developer/clients", headers=headers, json={"companyId": str(env["company"].id),
                "name": "Synthetic browser docs", "redirectUris": [origin + "/developer/api/callback", origin + portal.PREFIX + "/oauth2-redirect"],
                "scopes": SCOPES, "authMethod": "none"})
            assert registered.status_code == 201, registered.text
            client_id = registered.json()["clientId"]
            assert (await client.post(f"/api/developer/clients/{client_id}/status", headers=headers, json={"enabled": True})).status_code == 200
            installed = await client.post(f"/api/developer/clients/{client_id}/installations", headers=headers,
                json={"companyId": str(env["company"].id), "scopes": SCOPES, "locationIds": None,
                    "resourceScopes": {"objects": {"mode": "ALL", "ids": []}}})
            assert installed.status_code == 201, installed.text
            monkeypatch.setattr(portal.settings, "partner_docs_client_id", client_id)
        workspace = Path(__file__).resolve().parents[2]
        process = await asyncio.to_thread(subprocess.run,
            ["node", "--test", "--experimental-strip-types", "tests/developer-docs/browser.test.ts"],
            cwd=workspace, env={**os.environ, "DOCS_E2E_ORIGIN": origin, "DOCS_E2E_HANDSHAKE": str(handshake),
                "DOCS_E2E_DIR": str(tmp_path / "browser"), "DOCS_E2E_USER": env["user"].email,
                "DOCS_E2E_COMPANY": str(env["company"].id), "DOCS_E2E_CLIENT": client_id, "DOCS_E2E_MODE_FILE": str(mode_file)},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300, check=False)
        output = process.stdout.decode()
        (tmp_path / "browser.log").write_text(output)
        assert process.returncode == 0, output[-14000:]
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 15)
