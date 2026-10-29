"""Partner HTTP conformance and live-revocation tests, isolated PostgreSQL only.

Run with TEST_DATABASE_URL ending in /api_identity_test and a dedicated UPLOAD_DIR.
The repository's conftest exercises the real bootstrap, including repeatable DDL.
"""
import asyncio
import base64
import os
import uuid
from dataclasses import FrozenInstanceError
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
import pytest_asyncio
from authlib.oauth2.rfc7636.challenge import create_s256_code_challenge
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

# Guard before any database fixture can drop schemas. The rest of the repository
# also uses conftest, so skip this opt-in suite on an unrelated test database.
_target = urlsplit(os.environ.get("TEST_DATABASE_URL", ""))
if (_target.hostname != "127.0.0.1" or _target.port != 33546 or _target.path != "/api_identity_test"
        or "partner" not in os.environ.get("UPLOAD_DIR", "")):
    pytest.skip("Partner identity requires its isolated database and upload directory", allow_module_level=True)

from app.auth import token_for
from app.models import App, Company, CompanyApp, ServiceLocation, User, UserCompany
from app.models_partner import (PartnerAuthorizationRequest, PartnerClient, PartnerCode, PartnerCredential,
    PartnerGrant, PartnerInstallation, PartnerResourceItem, PartnerResourceScope, PartnerSubject, PartnerToken, PartnerTokenFamily)
from app.services import partner_identity as identity
from app.routers import partner_oauth_router
from tests.conftest import _test_session_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")
REDIRECT = "https://partner.example/callback?fixed=1"
# RFC 7636 Appendix B, not generated from implementation under test.
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
SCOPES = ["openid", "profile", "email", "offline_access", "docs:read"]


@pytest.fixture(scope="module")
def rsa_key():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())


@pytest_asyncio.fixture(loop_scope="session")
async def env(client, db, monkeypatch, rsa_key):
    assert urlsplit(os.environ["TEST_DATABASE_URL"]).path == "/api_identity_test"
    assert os.environ.get("UPLOAD_DIR") and "partner" in os.environ["UPLOAD_DIR"]
    monkeypatch.setattr(identity.settings, "partner_oauth_enabled", True)
    monkeypatch.setattr(identity.settings, "partner_oauth_issuer", "https://identity.example")
    monkeypatch.setattr(identity.settings, "partner_oauth_audience", "urn:elsyplus:partner-api:test")
    monkeypatch.setattr(identity.settings, "partner_oauth_signing_key", base64.b64encode(rsa_key).decode())
    monkeypatch.setattr(identity.settings, "partner_oauth_kid", "partner-test/1")
    partner_oauth_router._hits.clear()
    suffix = uuid.uuid4().hex
    company = Company(name="OAuth synthetic company", slug="oauth-" + suffix[:12], profile_id="energy")
    other = Company(name="Other synthetic company", slug="other-" + suffix[:12], profile_id="energy")
    db.add_all([company, other])
    await db.flush()
    user = User(email=suffix + "@example.invalid", name="Synthetic admin", password_hash="not-used-for-login",
        company_id=company.id, role="user", is_superadmin=False)
    outsider = User(email="other-" + suffix + "@example.invalid", name="Synthetic member", password_hash="not-used-for-login",
        company_id=company.id, role="user", is_superadmin=False)
    db.add_all([user, outsider])
    await db.flush()
    db.add_all([UserCompany(user_id=user.id, company_id=company.id, role="admin"),
        UserCompany(user_id=outsider.id, company_id=company.id, role="user", modules=[])])
    loc = ServiceLocation(id="oauth-" + suffix[:20], company_id=company.id, code="synthetic", name="Synthetic station")
    foreign_loc = ServiceLocation(id="other-" + suffix[:20], company_id=other.id, code="foreign", name="Foreign station")
    db.add_all([loc, foreign_loc])
    await db.commit()
    bearer = token_for(user, expires_at=identity.now() + timedelta(minutes=20))
    return {"client": client, "db": db, "user": user, "member": outsider, "company": company, "other": other,
        "location": loc, "foreign_location": foreign_loc, "bearer": bearer, "headers": {"Authorization": "Bearer " + bearer}}


async def registration(env, *, confidential=False, scopes=None, installation=True, resources=None):
    ac = env["client"]
    body = {"companyId": str(env["company"].id), "name": "Synthetic partner", "redirectUris": [REDIRECT],
        "scopes": scopes or SCOPES, "authMethod": "client_secret_basic" if confidential else "none"}
    response = await ac.post("/api/developer/clients", json=body, headers=env["headers"])
    assert response.status_code == 201, response.text
    client = response.json()
    client_id = client["clientId"]
    response = await ac.post(f"/api/developer/clients/{client_id}/status", json={"enabled": True}, headers=env["headers"])
    assert response.status_code == 200, response.text
    result = {"client_id": client_id, "app_id": uuid.UUID(client["appId"])}
    if confidential:
        response = await ac.post(f"/api/developer/clients/{client_id}/credentials", headers=env["headers"])
        assert response.status_code == 201, response.text
        result.update(secret=response.json()["clientSecret"], credential_id=uuid.UUID(response.json()["credentialId"]))
    if installation:
        body = {"companyId": str(env["company"].id), "scopes": scopes or SCOPES, "locationIds": None,
            "resourceScopes": resources or {}}
        response = await ac.post(f"/api/developer/clients/{client_id}/installations", json=body, headers=env["headers"])
        assert response.status_code == 201, response.text
        result["installation_id"] = uuid.UUID(response.json()["installationId"])
    return result


async def pending(env, app, **overrides):
    params = {"client_id": app["client_id"], "response_type": "code", "redirect_uri": REDIRECT,
        "scope": " ".join(SCOPES), "state": "opaque-state" + uuid.uuid4().hex,
        "nonce": "nonce-" + uuid.uuid4().hex, "code_challenge": CHALLENGE, "code_challenge_method": "S256"}
    params.update(overrides)
    response = await env["client"].get("/api/oauth2/authorize", params=params)
    assert response.status_code == 302, response.text
    assert response.headers["location"].startswith("/developer/authorize?requestId=")
    return parse_qs(urlsplit(response.headers["location"]).query)["requestId"][0], params


async def consent(env, app, *, scopes=None):
    rid, params = await pending(env, app, scope=" ".join(scopes or SCOPES))
    detail = await env["client"].get(f"/api/developer/authorization-requests/{rid}", headers=env["headers"])
    assert detail.status_code == 200, detail.text
    response = await env["client"].post(f"/api/developer/authorization-requests/{rid}/approve",
        json={"companyId": str(env["company"].id), "scopes": scopes or SCOPES}, headers=env["headers"])
    assert response.status_code == 200, response.text
    callback = response.json()["redirectUrl"]
    query = parse_qs(urlsplit(callback).query)
    assert query["state"] == [params["state"]]
    assert query["fixed"] == ["1"]
    assert "access_token" not in query and "id_token" not in query
    return query["code"][0], params, rid


async def exchange(env, app, code, **overrides):
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": VERIFIER}
    form.update(overrides)
    auth = (app["client_id"], app["secret"]) if "secret" in app else None
    if auth is None:
        form["client_id"] = app["client_id"]
    return await env["client"].post("/api/oauth2/token", data=form, auth=auth)


async def tokens(env, app, scopes=None):
    code, params, rid = await consent(env, app, scopes=scopes)
    response = await exchange(env, app, code)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json(), params


async def refresh(env, app, value, **extra):
    form = {"grant_type": "refresh_token", "refresh_token": value, **extra}
    auth = (app["client_id"], app["secret"]) if "secret" in app else None
    if auth is None:
        form["client_id"] = app["client_id"]
    return await env["client"].post("/api/oauth2/token", data=form, auth=auth)


async def verify(value):
    async with _test_session_factory() as db:
        return await identity.verify_partner_access_token(value, db)


async def test_full_code_pkce_oidc_and_discovery(env, rsa_key):
    assert create_s256_code_challenge(VERIFIER) == CHALLENGE
    app = await registration(env)
    issued, params = await tokens(env, app)
    jwks = (await env["client"].get("/api/oauth2/jwks")).json()
    assert not {"d", "p", "q", "dp", "dq", "qi"} & jwks["keys"][0].keys()
    assert jwks["keys"][0]["kty"] == "RSA" and jwks["keys"][0]["use"] == "sig"
    public = jwt.algorithms.RSAAlgorithm.from_jwk(jwks["keys"][0])
    access = jwt.decode(issued["access_token"], public, algorithms=["RS256"], audience=identity.settings.partner_oauth_audience,
        issuer=identity.settings.partner_oauth_issuer)
    id_claims = jwt.decode(issued["id_token"], public, algorithms=["RS256"], audience=app["client_id"], issuer=identity.settings.partner_oauth_issuer)
    assert id_claims["nonce"] == params["nonce"]
    assert id_claims["token_use"] == "partner_id" and access["token_use"] == "partner_access"
    assert id_claims["email"] == env["user"].email
    assert id_claims["name"] == env["user"].name
    assert id_claims["sub"] == access["sub"] and id_claims["sub"] != str(env["user"].id)
    assert "email_verified" not in id_claims and id_claims["at_hash"]
    assert jwt.get_unverified_header(issued["access_token"])["typ"] == "at+jwt"
    verified = await verify(issued["access_token"])
    assert verified.user_id == env["user"].id and verified.company_id == env["company"].id
    assert verified.resource_scopes["documents"].mode == "EMPTY"
    with pytest.raises(FrozenInstanceError):
        verified.company_id = env["other"].id
    with pytest.raises(TypeError):
        verified.resource_scopes["documents"] = None
    info = await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + issued["access_token"]})
    assert info.json() == {"sub": verified.subject, "email": env["user"].email, "name": env["user"].name}
    metadata = await env["client"].get("/api/oauth2/.well-known/openid-configuration")
    assert metadata.status_code == 200
    assert metadata.json()["code_challenge_methods_supported"] == ["S256"]
    assert metadata.json()["issuer"] == identity.settings.partner_oauth_issuer


@pytest.mark.parametrize("change", ["redirect", "pkce", "verifier", "nonce", "duplicate", "response", "scope", "state", "prompt"])
async def test_invalid_authorization_request(env, change):
    app = await registration(env)
    params = {"client_id": app["client_id"], "response_type": "code", "redirect_uri": REDIRECT,
        "scope": "openid", "state": "state", "nonce": "nonce", "code_challenge": CHALLENGE, "code_challenge_method": "S256"}
    if change == "redirect": params["redirect_uri"] += "attacker"
    if change == "pkce": params.pop("code_challenge")
    if change == "verifier": params["code_challenge_method"] = "plain"
    if change == "nonce": params.pop("nonce")
    if change == "response": params["response_type"] = "token"
    if change == "scope": params["scope"] = "openid new:unreviewed"
    if change == "state": params.pop("state")
    if change == "prompt": params["prompt"] = "none"
    pairs = list(params.items())
    if change == "duplicate": pairs.append(("client_id", app["client_id"]))
    response = await env["client"].get("/api/oauth2/authorize", params=pairs)
    assert response.status_code == 400 and "location" not in response.headers
    assert "error" in response.json() and response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bad_redirect", ["https://partner.example/*", "https://user@partner.example/cb", "https://partner.example/cb#x", "http://partner.example/cb", "http://localhost/cb", "https://[invalid/cb", "https://@partner.example/cb"])
async def test_redirect_registration_policy(env, bad_redirect):
    response = await env["client"].post("/api/developer/clients", headers=env["headers"], json={
        "companyId": str(env["company"].id), "name": "Invalid", "redirectUris": [bad_redirect], "scopes": ["openid"]})
    assert response.status_code == 400


async def test_code_exact_redirect_wrong_client_and_one_use(env):
    app = await registration(env)
    other = await registration(env)
    code, _, _ = await consent(env, app)
    assert (await exchange(env, other, code)).status_code == 400
    assert (await exchange(env, app, code, redirect_uri=REDIRECT + "x")).status_code == 400
    assert (await exchange(env, app, code, code_verifier="x" * 43)).status_code == 400
    assert (await exchange(env, app, code)).status_code == 200
    assert (await exchange(env, app, code)).json()["error"] == "invalid_grant"
    stored = await env["db"].get(PartnerCode, identity.digest(code))
    assert stored.consumed and stored.code_hash != code


async def test_concurrent_code_consume(env):
    app = await registration(env)
    code, _, _ = await consent(env, app)
    replies = await asyncio.gather(exchange(env, app, code), exchange(env, app, code))
    assert sorted(r.status_code for r in replies) == [200, 400]
    successful = next(r for r in replies if r.status_code == 200).json()
    assert (await verify(successful["access_token"])).client_id == app["client_id"]


async def test_expired_code_and_request(env):
    app = await registration(env)
    code, _, _ = await consent(env, app)
    row = await env["db"].get(PartnerCode, identity.digest(code))
    row.expires_at = identity.now() - timedelta(seconds=1)
    await env["db"].commit()
    assert (await exchange(env, app, code)).json()["error"] == "invalid_grant"
    rid, _ = await pending(env, app)
    request = await env["db"].get(PartnerAuthorizationRequest, uuid.UUID(rid))
    request.expires_at = identity.now() - timedelta(seconds=1)
    await env["db"].commit()
    response = await env["client"].get(f"/api/developer/authorization-requests/{rid}", headers=env["headers"])
    assert response.status_code == 410 and response.json()["code"] == "AUTH_REQUEST_EXPIRED"


async def test_selection_escalation_tenant_spoof_and_member_permissions(env):
    app = await registration(env)
    rid, _ = await pending(env, app)
    route = f"/api/developer/authorization-requests/{rid}"
    assert (await env["client"].get(route, headers=env["headers"])).status_code == 200
    for body in ({"companyId": str(env["other"].id), "scopes": ["openid"]},
                 {"companyId": str(env["company"].id), "scopes": ["openid", "objects:read"]},
                 {"companyId": str(env["company"].id), "scopes": []},
                 {"companyId": str(env["company"].id), "scopes": ["docs:read"]}):
        response = await env["client"].post(route + "/approve", headers=env["headers"], json=body)
        assert response.status_code == 422 and response.json()["code"] == "INVALID_AUTHORIZATION_SELECTION"
    other_headers = {"Authorization": "Bearer " + token_for(env["member"])}
    response = await env["client"].get(route, headers=other_headers)
    assert response.status_code == 404
    rid2, _ = await pending(env, app)
    detail = await env["client"].get(f"/api/developer/authorization-requests/{rid2}", headers=other_headers)
    assert "docs:read" not in detail.json()["companies"][0]["eligibleScopes"]
    response = await env["client"].post(f"/api/developer/authorization-requests/{rid2}/approve", headers=other_headers,
        json={"companyId": str(env["company"].id), "scopes": ["openid", "docs:read"]})
    assert response.status_code == 422
    response = await env["client"].post("/api/developer/clients", headers=other_headers,
        json={"companyId": str(env["company"].id), "name": "Not admin", "redirectUris": [REDIRECT], "scopes": ["openid"]})
    assert response.status_code == 403


async def test_installation_required_and_deny_has_no_side_effects(env):
    app = await registration(env, installation=False)
    rid, _ = await pending(env, app)
    response = await env["client"].get(f"/api/developer/authorization-requests/{rid}", headers=env["headers"])
    assert response.status_code == 403
    db = env["db"]
    async def counts():
        return [await db.scalar(select(func.count()).select_from(model)) for model in (PartnerGrant, PartnerCode, PartnerToken, PartnerTokenFamily, PartnerSubject)]
    before = await counts()
    response = await env["client"].post(f"/api/developer/authorization-requests/{rid}/deny", headers=env["headers"])
    assert response.status_code == 200, response.text
    query = parse_qs(urlsplit(response.json()["redirectUrl"]).query)
    assert query["error"] == ["access_denied"] and "code" not in query
    assert await counts() == before
    repeat = await env["client"].post(f"/api/developer/authorization-requests/{rid}/deny", headers=env["headers"])
    assert repeat.status_code == 409 and repeat.json()["code"] == "AUTH_REQUEST_CONSUMED"


@pytest.mark.parametrize("state", ["mail_only", "locked", "deleted_user", "tv", "membership", "grant", "client", "app", "installation", "company_app", "credential"])
async def test_actual_state_revocation_on_next_call_and_refresh(env, state):
    app = await registration(env, confidential=True)
    issued, _ = await tokens(env, app)
    verified = await verify(issued["access_token"])
    db = env["db"]
    if state == "mail_only": env["user"].mail_only = True
    if state == "locked": env["user"].locked_until = identity.now() + timedelta(minutes=1)
    if state == "deleted_user": await db.delete(env["user"])
    if state == "tv": env["user"].token_version += 1
    if state == "membership": await db.delete(await db.get(UserCompany, (env["user"].id, env["company"].id)))
    if state == "grant": (await db.get(PartnerGrant, verified.grant_id)).approved = False
    if state == "client": (await db.get(PartnerClient, app["client_id"])).enabled = False
    if state == "app": (await db.get(App, app["app_id"])).is_active = False
    if state == "installation": (await db.get(PartnerInstallation, app["installation_id"])).approved = False
    if state == "company_app": (await db.get(CompanyApp, app["installation_id"])).enabled = False
    if state == "credential": (await db.get(PartnerCredential, app["credential_id"])).enabled = False
    await db.commit()
    info = await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + issued["access_token"]})
    assert info.status_code == 401, info.text
    response = await refresh(env, app, issued["refresh_token"])
    assert response.status_code in {400, 401} and "access_token" not in response.json()


async def test_refresh_rotation_reuse_and_family_revoke(env):
    app = await registration(env)
    issued, _ = await tokens(env, app)
    next_response = await refresh(env, app, issued["refresh_token"])
    assert next_response.status_code == 200, next_response.text
    next_tokens = next_response.json()
    assert next_tokens["refresh_token"] != issued["refresh_token"]
    assert "id_token" not in next_tokens
    assert (await verify(next_tokens["access_token"])).client_id == app["client_id"]
    replay = await refresh(env, app, issued["refresh_token"])
    assert replay.json()["error"] == "invalid_grant"
    assert (await refresh(env, app, next_tokens["refresh_token"])).status_code == 400
    for access in (issued["access_token"], next_tokens["access_token"]):
        response = await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + access})
        assert response.status_code == 401


async def test_concurrent_refresh_reuse_revokes_winner(env):
    app = await registration(env)
    issued, _ = await tokens(env, app)
    replies = await asyncio.gather(refresh(env, app, issued["refresh_token"]), refresh(env, app, issued["refresh_token"]))
    assert sorted(r.status_code for r in replies) == [200, 400]
    winner = next(r for r in replies if r.status_code == 200).json()
    assert (await refresh(env, app, winner["refresh_token"])).status_code == 400


async def test_offline_access_explicit_parent_session_cap_and_no_scope_expansion(env):
    app = await registration(env)
    issued, _ = await tokens(env, app, ["openid"])
    assert "refresh_token" not in issued
    claims = jwt.decode(issued["id_token"], options={"verify_signature": False})
    assert "email" not in claims and "name" not in claims
    env["headers"] = {"Authorization": "Bearer " + token_for(env["user"], expires_at=identity.now() + timedelta(seconds=45))}
    issued, _ = await tokens(env, app)
    verified = await verify(issued["access_token"])
    assert verified.expires_at <= identity.now() + timedelta(seconds=45)
    response = await refresh(env, app, issued["refresh_token"], scope="openid objects:read")
    assert response.json()["error"] == "invalid_scope"
    row = await env["db"].get(PartnerToken, verified.token_id)
    family = await env["db"].get(PartnerTokenFamily, row.family_id)
    assert family.expires_at <= identity.now() + timedelta(seconds=45)
    family.expires_at = identity.now() - timedelta(seconds=1)
    await env["db"].commit()
    assert (await refresh(env, app, issued["refresh_token"])).status_code == 400


async def test_token_type_issuer_audience_algorithm_confusion(env, rsa_key):
    app = await registration(env)
    issued, _ = await tokens(env, app)
    payload = jwt.decode(issued["access_token"], options={"verify_signature": False})
    wrong = [issued["id_token"], env["bearer"]]
    for field, value in (("iss", "https://other.example"), ("aud", app["client_id"]), ("token_use", "handoff")):
        wrong.append(jwt.encode({**payload, field: value}, rsa_key, algorithm="RS256",
            headers={"typ": "at+jwt", "kid": "partner-test/1"}))
    for field in ("iss", "aud", "token_use", "jti", "exp", "iat"):
        altered = dict(payload)
        altered.pop(field)
        wrong.append(jwt.encode(altered, rsa_key, algorithm="RS256", headers={"typ": "at+jwt", "kid": "partner-test/1"}))
    wrong.append(jwt.encode(payload, "not-a-real-partner-key", algorithm="HS256", headers={"typ": "at+jwt", "kid": "partner-test/1"}))
    for value in wrong:
        response = await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + value})
        assert response.status_code == 401, response.text
    # Partner access/id tokens cannot authenticate as ordinary Core users.
    for value in (issued["access_token"], issued["id_token"]):
        response = await env["client"].get("/api/auth/me", headers={"Authorization": "Bearer " + value})
        assert response.status_code == 401


async def test_machine_grant_separate_confidential_only(env):
    scopes = ["docs:read", "objects:read", "documents:read"]
    public = await registration(env, scopes=scopes)
    route = f'/api/developer/installations/{public["installation_id"]}/machine-grants'
    assert (await env["client"].post(route, json={"scopes": ["docs:read"]}, headers=env["headers"])).status_code == 422
    app = await registration(env, confidential=True, scopes=scopes)
    route = f'/api/developer/installations/{app["installation_id"]}/machine-grants'
    for forbidden in (["openid"], ["documents:read"]):
        assert (await env["client"].post(route, json={"scopes": forbidden}, headers=env["headers"])).status_code == 422
    response = await env["client"].post(route, json={"scopes": ["docs:read"]}, headers=env["headers"])
    assert response.status_code == 201
    grant_id = response.json()["grantId"]
    form = {"grant_type": "client_credentials", "grant_id": grant_id, "scope": "docs:read"}
    response = await env["client"].post("/api/oauth2/token", data=form, auth=(app["client_id"], app["secret"]))
    assert response.status_code == 200, response.text
    issued = response.json()
    assert "refresh_token" not in issued and "id_token" not in issued
    verified = await verify(issued["access_token"])
    assert verified.is_machine and verified.user_id is None
    assert (await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + issued["access_token"]})).status_code == 403
    form.pop("grant_id")
    assert (await env["client"].post("/api/oauth2/token", data=form, auth=(app["client_id"], app["secret"])) ).status_code == 400
    form["grant_id"] = grant_id
    form["scope"] = "objects:read"
    assert (await env["client"].post("/api/oauth2/token", data=form, auth=(app["client_id"], app["secret"])) ).status_code == 400


async def test_revocation_endpoint(env):
    app = await registration(env)
    issued, _ = await tokens(env, app)
    response = await env["client"].post("/api/oauth2/revoke", data={"client_id": app["client_id"], "token": issued["refresh_token"]})
    assert response.status_code == 200, response.text
    assert (await refresh(env, app, issued["refresh_token"])).status_code == 400
    response = await env["client"].post("/api/oauth2/revoke", data={"client_id": app["client_id"], "token": "unknown-token"})
    assert response.status_code == 200


async def test_pairwise_stability_and_userinfo_scope(env):
    first = await registration(env)
    second = await registration(env)
    one, _ = await tokens(env, first, ["openid"])
    two, _ = await tokens(env, first, ["openid"])
    three, _ = await tokens(env, second, ["openid"])
    v1, v2, v3 = [await verify(v["access_token"]) for v in (one, two, three)]
    assert v1.subject == v2.subject and v1.subject != v3.subject
    info = await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + one["access_token"]})
    assert info.json() == {"sub": v1.subject}


async def test_resource_grants_typed_company_and_empty_distinct(env):
    resources = {"objects": {"mode": "SET", "ids": [env["location"].id]}, "contracts": {"mode": "ALL", "ids": []}}
    app = await registration(env, resources=resources)
    issued, _ = await tokens(env, app)
    verified = await verify(issued["access_token"])
    assert verified.resource_scopes["objects"].mode == "SET"
    assert verified.resource_scopes["objects"].ids == frozenset({env["location"].id})
    assert verified.resource_scopes["contracts"].mode == "ALL"
    assert verified.resource_scopes["documents"].mode == "EMPTY"
    response = await env["client"].post(f'/api/developer/clients/{app["client_id"]}/installations', headers=env["headers"],
        json={"companyId": str(env["company"].id), "scopes": SCOPES, "resourceScopes": {
            "objects": {"mode": "SET", "ids": [env["foreign_location"].id]}}})
    assert response.status_code == 422
    # A member's current restriction narrows the stored grant on the next call.
    member = await env["db"].get(UserCompany, (env["user"].id, env["company"].id))
    member.role, member.modules, member.object_scope = "user", None, ["no-longer-authorized"]
    await env["db"].commit()
    verified = await verify(issued["access_token"])
    assert verified.resource_scopes["objects"].mode == "EMPTY"


async def test_feature_disabled_no_grants_and_default_off(env, monkeypatch):
    from app.config import Settings
    assert Settings(_env_file=None).partner_oauth_enabled is False
    assert Settings(_env_file=None).partner_api_enabled is False
    before = await env["db"].scalar(select(func.count()).select_from(PartnerGrant))
    monkeypatch.setattr(identity.settings, "partner_oauth_enabled", False)
    response = await env["client"].get("/api/oauth2/jwks")
    assert response.status_code == 503 and response.json()["code"] == "PARTNER_API_DISABLED"
    response = await env["client"].post("/api/developer/clients", headers=env["headers"], json={
        "companyId": str(env["company"].id), "name": "Disabled", "redirectUris": [REDIRECT], "scopes": ["openid"]})
    assert response.status_code == 503
    assert await env["db"].scalar(select(func.count()).select_from(PartnerGrant)) == before


async def test_token_transport_size_rate_and_password_grant(env):
    response = await env["client"].post("/api/oauth2/token", json={"grant_type": "password"})
    assert response.status_code == 400
    response = await env["client"].post("/api/oauth2/token", data={"grant_type": "password"})
    assert response.json()["error"] == "unsupported_grant_type"
    response = await env["client"].post("/api/oauth2/token?client_id=untrusted", data={"grant_type": "authorization_code"})
    assert response.status_code == 400
    response = await env["client"].post("/api/oauth2/token", content="x=" + "a" * 17000,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 400
    partner_oauth_router._hits.clear()
    for _ in range(120):
        response = await env["client"].post("/api/oauth2/token", data={"grant_type": "password"})
    response = await env["client"].post("/api/oauth2/token", data={"grant_type": "password"})
    assert response.status_code == 429 and response.headers["cache-control"] == "no-store"


async def test_current_version_and_membership_checked_before_code_exchange(env):
    app = await registration(env)
    code, _, _ = await consent(env, app)
    env["user"].token_version += 1
    await env["db"].commit()
    response = await exchange(env, app, code)
    assert response.status_code == 400 and response.json()["error"] == "invalid_grant"


async def test_credential_expiry_and_wrong_refresh_client(env):
    app = await registration(env, confidential=True)
    other = await registration(env, confidential=True)
    issued, _ = await tokens(env, app)
    wrong = await refresh(env, other, issued["refresh_token"])
    assert wrong.status_code == 400
    assert (await verify(issued["access_token"])).client_id == app["client_id"]
    credential = await env["db"].get(PartnerCredential, app["credential_id"])
    credential.expires_at = identity.now() - timedelta(seconds=1)
    await env["db"].commit()
    info = await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + issued["access_token"]})
    assert info.status_code == 401
    assert (await refresh(env, app, issued["refresh_token"])).status_code == 401


async def test_revoke_approval_before_consent_and_missing_request(env):
    app = await registration(env)
    rid, _ = await pending(env, app)
    route = f"/api/developer/authorization-requests/{rid}"
    assert (await env["client"].get(route, headers=env["headers"])).status_code == 200
    revoked = await env["client"].delete(f'/api/developer/installations/{app["installation_id"]}', headers=env["headers"])
    assert revoked.status_code == 200
    response = await env["client"].post(route + "/approve", headers=env["headers"],
        json={"companyId": str(env["company"].id), "scopes": ["openid"]})
    assert response.status_code == 403 and response.json()["code"] == "AUTHORIZATION_REVOKED"
    response = await env["client"].get(f"/api/developer/authorization-requests/{uuid.uuid4()}", headers=env["headers"])
    assert response.status_code == 404 and response.json()["code"] == "AUTH_REQUEST_NOT_FOUND"


async def test_nonce_replay_and_real_legacy_handoff_confusion(env, monkeypatch, rsa_key):
    from app.services import sso
    app = await registration(env)
    _, params, _ = await consent(env, app)
    response = await env["client"].get("/api/oauth2/authorize", params=params)
    assert response.status_code == 400 and response.json()["error"] == "invalid_request"
    monkeypatch.setattr(sso.settings, "sso_signing_key", base64.b64encode(rsa_key).decode())
    handoff = sso.sign_sso_token(user=env["user"], company_id=env["company"].id,
        companies=[], aud=identity.settings.partner_oauth_audience)
    response = await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + handoff})
    assert response.status_code == 401


async def test_database_company_and_typed_resource_constraints(env):
    app = await registration(env)
    db = env["db"]
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(PartnerGrant(installation_id=app["installation_id"], client_id=app["client_id"],
                company_id=env["other"].id, kind="user", user_id=env["user"].id, scopes=["openid"], approved=True))
            await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(PartnerResourceScope(installation_id=app["installation_id"], kind="objects", mode="SET"))
            await db.flush()
            db.add(PartnerResourceItem(installation_id=app["installation_id"], kind="objects", contract_id=uuid.uuid4()))
            await db.flush()


async def test_existing_schema_upgrade_and_repeat_bootstrap_preserve_core(env):
    from app import database
    from app.database import Base
    # Reproduce a pre-M10 schema using only this isolated test DB. Existing Core
    # rows and tables survive; bootstrap creates exclusively new partner tables.
    before = await env["db"].scalar(select(func.count()).select_from(User))
    from app.models import PartnerSpace
    legacy_partners = await env["db"].scalar(select(func.count()).select_from(PartnerSpace))
    new_tables = {mapper.local_table for mapper in Base.registry.mappers
                  if mapper.class_.__module__ == "app.models_partner"}
    await env["db"].commit()
    async with database.engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            if table in new_tables:
                await conn.run_sync(lambda sync, t=table: t.drop(sync))
    await database.create_all()
    await database.create_all()
    assert await env["db"].scalar(select(func.count()).select_from(User)) == before
    assert await env["db"].scalar(select(func.count()).select_from(PartnerSpace)) == legacy_partners
    app = await registration(env)
    issued, _ = await tokens(env, app)
    assert (await verify(issued["access_token"])).company_id == env["company"].id


async def test_transport_errors_remain_safe_and_no_store(env):
    for endpoint in ("token", "revoke"):
        response = await env["client"].post("/api/oauth2/" + endpoint,
            data={"grant_type": "client_credentials"}, headers={"Authorization": "Basic /w=="})
        assert response.status_code == 401 and response.json()["error"] == "invalid_client"
        assert response.headers["cache-control"] == "no-store"
    response = await env["client"].get("/api/developer/authorization-requests/not-a-uuid", headers=env["headers"])
    assert response.status_code == 404 and response.json()["code"] == "AUTH_REQUEST_NOT_FOUND"
    response = await env["client"].post(f"/api/developer/authorization-requests/{uuid.uuid4()}/approve",
        headers=env["headers"], json={"companyId": "untrusted", "scopes": []})
    assert response.status_code == 422 and response.json()["code"] == "INVALID_AUTHORIZATION_SELECTION"
    response = await env["client"].get(f"/api/developer/authorization-requests/{uuid.uuid4()}")
    assert response.status_code == 401 and response.headers["cache-control"] == "no-store"


async def test_localhost_requires_explicit_development_configuration(env, monkeypatch):
    body = {"companyId": str(env["company"].id), "name": "Synthetic localhost",
            "redirectUris": ["http://localhost:3000/callback"], "scopes": ["openid"]}
    monkeypatch.setattr(identity.settings, "partner_oauth_allow_localhost", True)
    monkeypatch.setattr(identity.settings, "app_env", "dev")
    assert (await env["client"].post("/api/developer/clients", headers=env["headers"], json=body)).status_code == 201
    monkeypatch.setattr(identity.settings, "app_env", "prod")
    assert (await env["client"].post("/api/developer/clients", headers=env["headers"], json=body)).status_code == 400


async def test_missing_issuer_configuration_fails_closed(env, monkeypatch):
    monkeypatch.setattr(identity.settings, "partner_oauth_issuer", "http://untrusted.example")
    response = await env["client"].get("/api/oauth2/jwks")
    assert response.status_code == 503
    before = await env["db"].scalar(select(func.count()).select_from(PartnerClient))
    response = await env["client"].post("/api/developer/clients", headers=env["headers"], json={
        "companyId": str(env["company"].id), "name": "Invalid configuration", "redirectUris": [REDIRECT], "scopes": ["openid"]})
    assert response.status_code == 503
    assert await env["db"].scalar(select(func.count()).select_from(PartnerClient)) == before
