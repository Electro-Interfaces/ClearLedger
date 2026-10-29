"""Actual Core login -> OAuth consent/PKCE -> mounted product HTTP/SQL.

No verifier override, synthetic database fixtures only, no customer credentials.
"""
import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest
import pytest_asyncio

from app.auth import hash_password
from app.config import get_settings
from app.models import Company, ServiceLocation, User, UserCompany
from app.models_partner import PartnerClient, PartnerGrant, PartnerInstallation
from app.routers import partner_oauth_router

pytestmark = pytest.mark.asyncio(loop_scope="session")
REDIRECT = "https://synthetic-partner.example/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.fixture(scope="module")
def signing_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return base64.b64encode(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode()


@pytest_asyncio.fixture(loop_scope="session")
async def flow(client, db, monkeypatch, signing_key, request):
    settings = get_settings()
    redirect = getattr(request, "param", REDIRECT)
    if redirect.startswith("http:"):
        monkeypatch.setattr(settings, "app_env", "dev")
        monkeypatch.setattr(settings, "partner_oauth_allow_localhost", True)
    for key, value in {"partner_oauth_enabled": True, "partner_api_enabled": True,
        "partner_oauth_issuer": "https://synthetic-space.example",
        "partner_oauth_audience": "urn:elsyplus:partner:test",
        "partner_oauth_signing_key": signing_key}.items():
        monkeypatch.setattr(settings, key, value)
    partner_oauth_router._hits.clear()
    suffix = uuid.uuid4().hex
    companies = [Company(name="Synthetic integration", slug="int-" + suffix[:16], profile_id="energy"),
        Company(name="Foreign integration", slug="foreign-" + suffix[:16], profile_id="energy")]
    db.add_all(companies)
    await db.flush()
    company, foreign_company = companies
    password = "Synthetic-Login-2026!"
    user = User(email=suffix + "@example.com", name="Synthetic owner", company_id=company.id,
        role="user", is_superadmin=False, password_hash=hash_password(password))
    db.add(user)
    await db.flush()
    member = UserCompany(user_id=user.id, company_id=company.id, role="admin")
    db.add(member)
    now = datetime.now(timezone.utc)
    locations = [ServiceLocation(id="int-" + suffix[:16] + str(i), company_id=company.id,
        name="Synthetic station " + str(i), code="INT-" + str(i), type="ezs", status="active",
        created_at=now + timedelta(seconds=i), extra_metadata={"secret": "PRIVATE-SOURCE"}) for i in range(3)]
    foreign = ServiceLocation(id="foreign-" + suffix[:16], company_id=foreign_company.id,
        name="Forbidden foreign station", code="FOREIGN", type="ezs", status="active")
    db.add_all([*locations, foreign])
    await db.commit()
    response = await client.post("/api/auth/login", json={"email": user.email, "password": password})
    assert response.status_code == 200, response.text
    core = response.json()["access_token"]
    headers = {"Authorization": "Bearer " + core}
    scopes = ["openid", "objects:read"]
    response = await client.post("/api/developer/clients", headers=headers, json={
        "companyId": str(company.id), "name": "Synthetic external application",
        "redirectUris": [redirect], "scopes": scopes, "authMethod": "none"})
    assert response.status_code == 201, response.text
    client_id = response.json()["clientId"]
    response = await client.post(f"/api/developer/clients/{client_id}/status", headers=headers, json={"enabled": True})
    assert response.status_code == 200, response.text
    response = await client.post(f"/api/developer/clients/{client_id}/installations", headers=headers, json={
        "companyId": str(company.id), "scopes": scopes, "locationIds": None,
        "resourceScopes": {"objects": {"mode": "SET", "ids": [v.id for v in locations[:2]]}}})
    assert response.status_code == 201, response.text
    installation_id = uuid.UUID(response.json()["installationId"])
    response = await client.get("/api/oauth2/authorize", params={"response_type": "code", "client_id": client_id,
        "redirect_uri": redirect, "scope": " ".join(scopes), "state": suffix,
        "nonce": "nonce-" + suffix, "code_challenge": CHALLENGE, "code_challenge_method": "S256"})
    assert response.status_code == 302, response.text
    request_id = parse_qs(urlsplit(response.headers["location"]).query)["requestId"][0]
    response = await client.get(f"/api/developer/authorization-requests/{request_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["companies"]] == [str(company.id)]
    response = await client.post(f"/api/developer/authorization-requests/{request_id}/approve", headers=headers,
        json={"companyId": str(company.id), "scopes": scopes})
    assert response.status_code == 200, response.text
    callback = parse_qs(urlsplit(response.json()["redirectUrl"]).query)
    assert callback["state"] == [suffix]
    response = await client.post("/api/oauth2/token", data={"grant_type": "authorization_code", "client_id": client_id,
        "redirect_uri": redirect, "code": callback["code"][0], "code_verifier": VERIFIER})
    assert response.status_code == 200, response.text
    tokens = response.json()
    return {"client": client, "db": db, "settings": settings, "user": user, "member": member,
        "locations": locations, "foreign": foreign, "company": company, "foreign_company": foreign_company,
        "client_id": client_id, "installation_id": installation_id, "core": core, "tokens": tokens,
        "headers": {"Authorization": "Bearer " + tokens["access_token"]},
        "core_headers": headers, "redirect": redirect}


async def test_real_pkce_chain_limits_total_detail_and_pagination(flow):
    ac, headers = flow["client"], flow["headers"]
    response = await ac.get("/api/v1/objects?pageSize=1", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2 and len(data["items"]) == 1 and data["nextCursor"]
    assert response.headers["cache-control"] == "no-store" and response.headers["x-request-id"]
    assert "PRIVATE-SOURCE" not in response.text and "extraMetadata" not in response.text
    page = await ac.get("/api/v1/objects", params={"pageSize": 1, "cursor": data["nextCursor"]}, headers=headers)
    assert page.status_code == 200, page.text
    assert {data["items"][0]["id"], page.json()["items"][0]["id"]} == {v.id for v in flow["locations"][:2]}
    for location in [flow["locations"][2], flow["foreign"]]:
        denied = await ac.get("/api/v1/objects/" + location.id, headers=headers)
        assert denied.status_code == 404 and denied.headers["content-type"].startswith("application/problem+json")
    allowed = await ac.get("/api/v1/objects/" + flow["locations"][0].id, headers=headers)
    assert allowed.status_code == 200


@pytest.mark.parametrize("token_kind", ["core", "id_token"])
async def test_core_session_and_id_token_cannot_be_product_bearer(flow, token_kind):
    token = flow["core"] if token_kind == "core" else flow["tokens"]["id_token"]
    response = await flow["client"].get("/api/v1/objects", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "invalid_credentials"


@pytest.mark.parametrize("target", ["client", "installation", "account"])
async def test_live_revoke_closes_previously_successful_product_token(flow, target):
    ac, db = flow["client"], flow["db"]
    assert (await ac.get("/api/v1/objects", headers=flow["headers"])).status_code == 200
    if target == "client":
        row = await db.get(PartnerClient, flow["client_id"])
        row.enabled = False
    elif target == "installation":
        row = await db.get(PartnerInstallation, flow["installation_id"])
        row.approved = False
    else:
        flow["user"].token_version += 1
    await db.commit()
    denied = await ac.get("/api/v1/objects", headers=flow["headers"])
    assert denied.status_code == 401, denied.text


async def test_current_member_scope_and_changed_cursor_are_enforced(flow):
    ac, headers = flow["client"], flow["headers"]
    first = await ac.get("/api/v1/objects?pageSize=1", headers=headers)
    assert first.status_code == 200, first.text
    cursor = first.json()["nextCursor"]
    flow["member"].object_scope = [flow["locations"][0].id]
    await flow["db"].commit()
    narrowed = await ac.get("/api/v1/objects", headers=headers)
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json()["total"] == 1
    invalid_cursor = await ac.get("/api/v1/objects", params={"pageSize": 1, "cursor": cursor}, headers=headers)
    assert invalid_cursor.status_code == 400
    override = await ac.get("/api/v1/objects", params={"companyId": str(flow["foreign_company"].id)}, headers=headers)
    assert override.status_code == 422
    flow["member"].object_scope = []
    await flow["db"].commit()
    empty = await ac.get("/api/v1/objects", headers=headers)
    assert empty.status_code == 200 and empty.json()["total"] == 0


async def test_independent_feature_gates_fail_before_domain_projection(flow, monkeypatch):
    monkeypatch.setattr(flow["settings"], "partner_api_enabled", False)
    response = await flow["client"].get("/api/v1/objects", headers=flow["headers"])
    assert response.status_code == 503, response.text
    monkeypatch.setattr(flow["settings"], "partner_api_enabled", True)
    monkeypatch.setattr(flow["settings"], "partner_oauth_enabled", False)
    response = await flow["client"].get("/api/v1/objects", headers=flow["headers"])
    assert response.status_code == 503 and response.json()["status"] == 503
    assert "traceback" not in response.text.lower()


async def next_authorization(flow):
    response = await flow["client"].get("/api/oauth2/authorize", params={
        "response_type": "code", "client_id": flow["client_id"], "redirect_uri": flow["redirect"],
        "scope": "openid objects:read", "state": uuid.uuid4().hex, "nonce": uuid.uuid4().hex,
        "code_challenge": CHALLENGE, "code_challenge_method": "S256"})
    return response


@pytest.mark.parametrize("flow", ["http://localhost:3000/callback"], indirect=True)
@pytest.mark.parametrize("change", ["production", "flag_off"])
async def test_persisted_development_callback_is_reclassified_at_authorize_and_consent(flow, monkeypatch, change):
    # Existing consent/token proves this registered URI was legitimate in dev.
    pending = await next_authorization(flow)
    assert pending.status_code == 302
    request_id = parse_qs(urlsplit(pending.headers["location"]).query)["requestId"][0]
    if change == "production":
        monkeypatch.setattr(flow["settings"], "app_env", "prod")
    else:
        monkeypatch.setattr(flow["settings"], "partner_oauth_allow_localhost", False)
    denied = await next_authorization(flow)
    assert denied.status_code == 400 and "location" not in denied.headers
    base = f"/api/developer/authorization-requests/{request_id}"
    attempts = [await flow["client"].get(base, headers=flow["core_headers"]),
        await flow["client"].post(base + "/approve", headers=flow["core_headers"],
            json={"companyId": str(flow["company"].id), "scopes": ["openid", "objects:read"]}),
        await flow["client"].post(base + "/deny", headers=flow["core_headers"])]
    for response in attempts:
        assert response.status_code == 400, response.text
        assert "redirectUrl" not in response.text and "location" not in response.headers


@pytest.mark.parametrize("flow", ["http://localhost:3000/callback"], indirect=True)
async def test_unredeemed_development_code_is_closed_after_policy_change(flow, monkeypatch):
    pending = await next_authorization(flow)
    assert pending.status_code == 302
    request_id = parse_qs(urlsplit(pending.headers["location"]).query)["requestId"][0]
    approved = await flow["client"].post(f"/api/developer/authorization-requests/{request_id}/approve",
        headers=flow["core_headers"], json={"companyId": str(flow["company"].id), "scopes": ["openid", "objects:read"]})
    assert approved.status_code == 200, approved.text
    code = parse_qs(urlsplit(approved.json()["redirectUrl"]).query)["code"][0]
    monkeypatch.setattr(flow["settings"], "app_env", "prod")
    token = await flow["client"].post("/api/oauth2/token", data={"grant_type": "authorization_code",
        "client_id": flow["client_id"], "redirect_uri": flow["redirect"], "code": code, "code_verifier": VERIFIER})
    assert token.status_code == 400 and token.json()["error"] == "invalid_grant"
    assert "access_token" not in token.json()


@pytest.mark.parametrize("issuer", ["https://synthetic-space.example:99999", "https://synthetic-space.example:invalid",
    "https://synthetic-space.example:0", "https://synthetic-space.exa\nmple", "https://synthetic-space.example\t",
    "https://synthetic-space.example\\suffix", "https://synthetic-space.example\u00a0"])
async def test_invalid_issuer_is_closed_before_registration_or_discovery(flow, monkeypatch, issuer):
    from sqlalchemy import func, select
    before = await flow["db"].scalar(select(func.count()).select_from(PartnerClient))
    monkeypatch.setattr(flow["settings"], "partner_oauth_issuer", issuer)
    registration = await flow["client"].post("/api/developer/clients", headers=flow["core_headers"], json={
        "companyId": str(flow["company"].id), "name": "Invalid issuer registration",
        "redirectUris": [REDIRECT], "scopes": ["openid"], "authMethod": "none"})
    assert registration.status_code == 503, registration.text
    discovery = await flow["client"].get("/api/oauth2/.well-known/openid-configuration")
    assert discovery.status_code == 503, discovery.text
    after = await flow["db"].scalar(select(func.count()).select_from(PartnerClient))
    assert after == before
    from app.product_api import create_product_api, curated_openapi
    with pytest.raises(ValueError, match="Configured HTTPS space issuer"):
        curated_openapi(create_product_api(issuer=issuer))


async def test_valid_explicit_https_port_preserves_discovery(flow, monkeypatch):
    issuer = "https://synthetic-space.example:443"
    monkeypatch.setattr(flow["settings"], "partner_oauth_issuer", issuer)
    response = await flow["client"].get("/api/oauth2/.well-known/openid-configuration")
    assert response.status_code == 200 and response.json()["issuer"] == issuer
    from app.product_api import create_product_api, curated_openapi
    assert curated_openapi(create_product_api(issuer=issuer))["servers"][0]["url"] == issuer + "/api/v1"
