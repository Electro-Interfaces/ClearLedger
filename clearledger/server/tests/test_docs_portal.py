"""Real M10 + curated product + docs cookie, dedicated local PostgreSQL only."""
import base64
import os
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI, HTTPException
from sqlalchemy import select

from tests.partner_test_safety import partner_test_safety_error

DOCS_FLAG = "RUN_DOCS_PORTAL_TESTS"
if os.environ.get(DOCS_FLAG) != "1":
    pytest.skip(DOCS_FLAG + "=1 is required", allow_module_level=True)
_safety_error = partner_test_safety_error(os.environ, flag=DOCS_FLAG)
if _safety_error:
    raise pytest.UsageError("Refusing docs portal test database: " + _safety_error)

from app.auth import token_for, hash_password
from app.database import get_db
from app.models import Company, User, UserCompany, ServiceLocation
from app.models_docs_portal import DocsPortalSession
from app.models_partner import PartnerClient, PartnerGrant, PartnerInstallation, PartnerToken, PartnerTokenFamily
from app.routers import auth_router, partner_admin_router, partner_oauth_router, docs_portal_router
from app.services import partner_identity as identity, docs_portal as portal
from app.product_api import create_product_api
from app.api_contracts import policy_registry
from tests.conftest import _test_session_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")
ORIGIN = "https://docs.example.test"
CALLBACK = ORIGIN + "/developer/api/callback"
SWAGGER_CALLBACK = ORIGIN + portal.PREFIX + "/oauth2-redirect"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
SCOPES = ["openid", "docs:read", "objects:read"]


def application(factory, issuer):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_exception_handler(identity.PartnerProblem, identity.problem_handler)
    for router in [auth_router.router, partner_oauth_router.router, partner_oauth_router.consent_router,
                   partner_admin_router.router, docs_portal_router.router]:
        app.include_router(router, prefix="/api")
    async def database():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    child = create_product_api(session_factory=factory, enabled=True, issuer=issuer, source_revision="synthetic-docs-test")
    policy_registry(child)
    app.state.product_api = child
    app.mount("/api/v1", child)
    return app


@pytest_asyncio.fixture(loop_scope="session")
async def env(db, monkeypatch):
    assert partner_test_safety_error(os.environ, flag=DOCS_FLAG) is None
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    for name, value in {"partner_oauth_enabled": True, "partner_api_enabled": True, "partner_docs_enabled": True,
        "partner_oauth_issuer": ORIGIN, "partner_oauth_audience": "urn:docs:synthetic",
        "partner_oauth_signing_key": base64.b64encode(key).decode(), "partner_oauth_kid": "docs-test",
        "partner_docs_environment": "sandbox", "partner_docs_sandbox_api_url": ORIGIN + "/api/v1"}.items():
        monkeypatch.setattr(identity.settings, name, value)
    partner_oauth_router._hits.clear()
    suffix = uuid.uuid4().hex[:12]
    company = Company(name="Synthetic docs company", slug="docs-" + suffix, profile_id="energy")
    db.add(company); await db.flush()
    user = User(company_id=company.id, email=suffix + "@example.com", name="Synthetic docs developer",
        password_hash=hash_password("synthetic-password"), role="user", is_superadmin=False)
    db.add(user); await db.flush()
    member = UserCompany(user_id=user.id, company_id=company.id, role="admin")
    db.add(member)
    loc = ServiceLocation(id="docs-" + suffix, company_id=company.id, code="synthetic", name="Synthetic docs object")
    db.add(loc); await db.commit()
    app = application(_test_session_factory, ORIGIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        env = {"client": client, "db": db, "app": app, "company": company, "user": user,
            "member": member, "location": loc, "core": token_for(user, expires_at=identity.now() + timedelta(minutes=20))}
        reg = await register(env)
        monkeypatch.setattr(portal.settings, "partner_docs_client_id", reg["clientId"])
        env["registration"] = reg
        yield env


async def register(env):
    client = env["client"]
    headers = {"Authorization": "Bearer " + env["core"]}
    response = await client.post("/api/developer/clients", json={"companyId": str(env["company"].id),
        "name": "Synthetic public docs", "redirectUris": [CALLBACK, SWAGGER_CALLBACK], "scopes": SCOPES, "authMethod": "none"}, headers=headers)
    assert response.status_code == 201, response.text
    reg = response.json()
    assert (await client.post(f'/api/developer/clients/{reg["clientId"]}/status', json={"enabled": True}, headers=headers)).status_code == 200
    install = await client.post(f'/api/developer/clients/{reg["clientId"]}/installations', json={"companyId": str(env["company"].id),
        "scopes": SCOPES, "locationIds": None, "resourceScopes": {"objects": {"mode": "ALL", "ids": []}}}, headers=headers)
    assert install.status_code == 201, install.text
    reg["installationId"] = install.json()["installationId"]
    return reg


async def token(env, scopes=None, client_id=None, callback=CALLBACK):
    scopes = scopes or ["openid", "docs:read"]
    ac = env["client"]
    response = await ac.get("/api/oauth2/authorize", params={"response_type": "code", "client_id": client_id or env["registration"]["clientId"],
        "redirect_uri": callback, "scope": " ".join(scopes), "state": "synthetic-state", "nonce": "synthetic-nonce",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256", "prompt": "consent"})
    assert response.status_code == 302, response.text
    rid = parse_qs(urlsplit(response.headers["location"]).query)["requestId"][0]
    headers = {"Authorization": "Bearer " + env["core"]}
    assert (await ac.get("/api/developer/authorization-requests/" + rid, headers=headers)).status_code == 200
    approved = await ac.post("/api/developer/authorization-requests/" + rid + "/approve", headers=headers,
        json={"companyId": str(env["company"].id), "scopes": scopes})
    assert approved.status_code == 200, approved.text
    code = parse_qs(urlsplit(approved.json()["redirectUrl"]).query)["code"][0]
    exchanged = await ac.post("/api/oauth2/token", data={"grant_type": "authorization_code", "client_id": client_id or env["registration"]["clientId"],
        "redirect_uri": callback, "code_verifier": VERIFIER, "code": code})
    assert exchanged.status_code == 200, exchanged.text
    return exchanged.json()["access_token"]


async def session(env, access=None):
    access = access or await token(env)
    response = await env["client"].post(portal.PREFIX + "/session", headers={"Authorization": "Bearer " + access,
        "Origin": ORIGIN, "X-Docs-CSRF": "bootstrap"})
    assert response.status_code == 200, response.text
    env["tokenId"] = (await identity.verify_partner_access_token(access, env["db"])).token_id
    return response, access


@pytest.mark.parametrize("path", ["/ui", "/openapi.json", "/assets/swagger-ui-bundle.js", "/assets/swagger-ui.css", "/assets/portal-init.js", "/oauth2-redirect"])
async def test_each_surface_needs_docs_cookie_not_core_or_product_bearer(env, path):
    ac = env["client"]
    for headers in [{}, {"Authorization": "Bearer " + env["core"]}, {"Authorization": "Bearer " + await token(env, ["objects:read"])}]:
        response = await ac.get(portal.PREFIX + path, headers=headers)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"


async def test_cookie_session_actual_curated_schema_assets_and_no_product_permission(env):
    response, access = await session(env)
    cookie = response.headers["set-cookie"]
    assert all(flag in cookie for flag in ["HttpOnly", "Secure", "SameSite=strict", "Path=/api/developer/docs"])
    assert access not in cookie
    db = env["db"]
    record = (await db.execute(select(DocsPortalSession).where(DocsPortalSession.token_id == env["tokenId"]))).scalar_one()
    assert record and len(record.cookie_hash) == 64 and record.expires_at <= identity.now() + timedelta(seconds=180)
    for path in ["/ui", "/openapi.json", "/assets/swagger-ui-bundle.js", "/assets/swagger-ui.css", "/assets/portal-init.js", "/oauth2-redirect"]:
        view = await env["client"].get(portal.PREFIX + path)
        assert view.status_code == 200, view.text[:200]
        assert view.headers["cache-control"] == "no-store"
        assert view.headers["referrer-policy"] == "no-referrer"
    spec = (await env["client"].get(portal.PREFIX + "/openapi.json")).json()
    assert spec["servers"] == [{"url": ORIGIN + "/api/v1"}]
    assert "/objects" in spec["paths"] and "/auth/login" not in spec["paths"]
    assert (await env["client"].get("/api/v1/objects")).status_code == 401
    assert (await env["client"].get("/api/v1/objects", headers={"Authorization": "Bearer " + access})).status_code == 403


@pytest.mark.parametrize("cause", ["token", "family", "grant", "client", "installation", "membership", "account", "session", "expiry", "profile"])
async def test_every_subsequent_byte_rechecks_canonical_live_authority(env, cause, monkeypatch):
    await session(env)
    db = env["db"]
    row = (await db.execute(select(DocsPortalSession).where(DocsPortalSession.token_id == env["tokenId"]))).scalar_one()
    tok = await db.get(PartnerToken, row.token_id)
    family = await db.get(PartnerTokenFamily, tok.family_id)
    grant = await db.get(PartnerGrant, family.grant_id)
    if cause == "token": tok.revoked = True
    elif cause == "family": family.revoked = True
    elif cause == "grant": grant.approved = False
    elif cause == "client": (await db.get(PartnerClient, grant.client_id)).enabled = False
    elif cause == "installation": (await db.get(PartnerInstallation, grant.installation_id)).approved = False
    elif cause == "membership": await db.delete(env["member"])
    elif cause == "account": env["user"].token_version += 1
    elif cause == "session": row.revoked = True
    elif cause == "expiry": row.expires_at = identity.now() - timedelta(seconds=1)
    elif cause == "profile": monkeypatch.setattr(identity.settings, "partner_oauth_kid", "rotated-docs-key")
    await db.commit()
    for path in ["/ui", "/openapi.json", "/assets/swagger-ui-bundle.js", "/assets/swagger-ui.css", "/oauth2-redirect"]:
        response = await env["client"].get(portal.PREFIX + path)
        assert response.status_code == 401, response.text
        assert response.headers["cache-control"] == "no-store"


async def test_origin_csrf_logout_and_supported_revoke(env):
    access = await token(env)
    ac = env["client"]
    for headers in [{"Authorization": "Bearer " + access}, {"Authorization": "Bearer " + access, "Origin": "https://evil.example", "X-Docs-CSRF": "bootstrap"},
                    {"Authorization": "Bearer " + access, "Origin": ORIGIN}]:
        assert (await ac.post(portal.PREFIX + "/session", headers=headers)).status_code == 403
    response, _ = await session(env, access)
    csrf = response.json()["csrfToken"]
    assert (await ac.delete(portal.PREFIX + "/session", headers={"Origin": ORIGIN})).status_code == 403
    assert (await ac.delete(portal.PREFIX + "/session", headers={"Origin": "https://evil.example", "X-Docs-CSRF": csrf})).status_code == 403
    logged_out = await ac.delete(portal.PREFIX + "/session", headers={"Origin": ORIGIN, "X-Docs-CSRF": csrf})
    assert logged_out.status_code == 204 and "Max-Age=0" in logged_out.headers["set-cookie"]
    assert (await ac.get(portal.PREFIX + "/ui")).status_code == 401
    with pytest.raises(HTTPException) as denied: await identity.verify_partner_access_token(access, env["db"])
    assert denied.value.status_code == 401


async def test_separate_configured_client_and_scope_gate(env):
    ac = env["client"]
    for access in [env["core"], await token(env, ["objects:read"])]:
        response = await ac.post(portal.PREFIX + "/session", headers={"Origin": ORIGIN, "X-Docs-CSRF": "bootstrap", "Authorization": "Bearer " + access})
        assert response.status_code in {401, 403}
    other = await register(env)
    access = await token(env, client_id=other["clientId"])
    response = await ac.post(portal.PREFIX + "/session", headers={"Origin": ORIGIN, "X-Docs-CSRF": "bootstrap", "Authorization": "Bearer " + access})
    assert response.status_code == 403


async def test_no_override_no_cdn_defaultoff_and_read_only_sandbox_metadata(env, monkeypatch):
    await session(env)
    ac = env["client"]
    for path in ["/ui?url=https://evil.example", "/openapi.json?server=evil", "/assets/swagger-ui.css?configUrl=x"]:
        assert (await ac.get(portal.PREFIX + path)).status_code == 400
    assert (await ac.get(portal.PREFIX + "/assets/manifest.json")).status_code == 404
    html = (await ac.get(portal.PREFIX + "/ui")).text
    assert "https://cdn" not in html and "validator.swagger.io" not in html
    for environment in ["unconfigured", "production"]:
        monkeypatch.setattr(portal.settings, "partner_docs_environment", environment)
        metadata = await ac.get(portal.PREFIX + "/metadata", headers={"Authorization": "Bearer " + env["core"]})
        assert metadata.status_code == 200 and not metadata.json()["sandboxReady"] and metadata.json()["ready"]
        assert "sandbox-api" in metadata.json()["setupRequired"]
    monkeypatch.setattr(portal.settings, "partner_docs_enabled", False)
    assert (await ac.get(portal.PREFIX + "/ui")).status_code == 503


async def test_setup_required_and_missing_pinned_assets_fail_closed(env, monkeypatch, tmp_path):
    await session(env)
    ac = env["client"]
    wrong_method = await ac.post(portal.PREFIX + "/ui")
    assert wrong_method.status_code == 405 and wrong_method.headers["cache-control"] == "no-store"
    monkeypatch.setattr(portal, "ASSETS", tmp_path)
    response = await ac.get(portal.PREFIX + "/assets/swagger-ui-bundle.js")
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    monkeypatch.setattr(portal.settings, "partner_docs_client_id", "")
    metadata = await ac.get(portal.PREFIX + "/metadata", headers={"Authorization": "Bearer " + env["core"]})
    assert metadata.status_code == 200 and not metadata.json()["ready"]
    assert "docs-client" in metadata.json()["setupRequired"]
    assert (await ac.get(portal.PREFIX + "/openapi.json")).status_code == 401
