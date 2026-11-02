"""Source-authored only; runtime/collection UNKNOWN until separate admission.

The caller supplies partner_contract_issuer_factory to issuer_world. Parent
conftest imports app/engines before module guards; these guards cannot authorize
collection. Only an independently admitted isolated PostgreSQL composition may
run this module. No live server, password login, browser, ingress or SSO proof.
"""
import os

import pytest
from tests.partner_test_safety import partner_test_safety_error

for _flag in ("RUN_DOCS_PORTAL_TESTS", "RUN_PARTNER_IDENTITY_TESTS"):
    if os.environ.get(_flag) != "1":
        pytest.skip("Existing docs and partner opt-ins required", allow_module_level=True)
    if _error := partner_test_safety_error(os.environ, flag=_flag):
        raise RuntimeError(_error)
if os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL"):
    raise RuntimeError("Matching explicitly admitted isolated test target required")

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import jwt
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.auth import token_for
from app.database import get_db
from app.models import App, CompanyApp, CompanyRole, User, UserCompany
from app.models_docs_portal import DocsPortalSession
from app.models_partner import (PartnerAuthorizationRequest, PartnerClient, PartnerCode,
    PartnerCredential, PartnerGrant, PartnerInstallation, PartnerResourceScope,
    PartnerSubject, PartnerToken, PartnerTokenFamily)
from app.models_partner_contracts import (PartnerContractCreateProfile as Profile,
    PartnerContractCreatePrincipal as Principal, PartnerContractCreateRef as Ref,
    PartnerContractCreateType as Type)
from app.services.partner_contract_authority import require_coarse_create
from app.product_api import create_product_api
from app.api_contracts import policy_registry
from app.routers import docs_portal_router, partner_oauth_router
from app.services import docs_portal as portal, partner_identity as identity
from tests.partner_contract_issuer_fixture import issuer_world, state

pytestmark = pytest.mark.asyncio(loop_scope="session")
ORIGIN = "https://issuer.synthetic.invalid"
CALLBACK = ORIGIN + "/developer/api/callback"
SCOPES = ["openid", "docs:read"]
# RFC 7636 Appendix B; independent of the application implementation.
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
SURFACES = ("/ui", "/openapi.json", "/openapi.server.json",
    "/assets/swagger-ui-bundle.js", "/assets/swagger-ui.css",
    "/assets/portal-init.js", "/assets/oauth-callback.js", "/oauth2-redirect")
OPERATIONS = {
    ("/objects", "get"): "listObjects",
    ("/objects/{objectId}", "get"): "getObject",
    ("/objects/{objectId}/monitoring", "get"): "getObjectMonitoring",
    ("/monitoring/network-state", "get"): "getNetworkState",
    ("/equipment", "get"): "listEquipment",
    ("/equipment/{equipmentId}", "get"): "getEquipment",
    ("/counterparties", "get"): "listCounterparties",
    ("/counterparties/{counterpartyId}", "get"): "getCounterparty",
    ("/contracts", "post"): "createContract",
    ("/contracts/create-options", "get"): "getContractCreateOptions",
    ("/contracts", "get"): "listContracts",
    ("/contract-types", "get"): "getContractTypeMetadata",
    ("/contracts/{contractId}", "get"): "getContract",
    ("/contracts/{contractId}/objects", "get"): "listContractObjects",
    ("/contracts/{contractId}/documents", "get"): "listContractDocuments",
    ("/documents", "get"): "listDocuments",
    ("/documents/{docId}", "get"): "getDocument",
    ("/documents/{docId}/versions/{versionId}/content", "get"): "downloadDocumentVersion",
}


def private(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


def bearer(value):
    return {"Authorization": "Bearer " + value}


async def cleanup_owned(w):
    """Only new IDs; children before parents and before issuer_world teardown."""
    async with w.factory() as db:
        grants = select(PartnerGrant.id).where(PartnerGrant.client_id.in_(w.clients))
        families = select(PartnerTokenFamily.id).where(PartnerTokenFamily.grant_id.in_(grants))
        tokens = select(PartnerToken.id).where(PartnerToken.family_id.in_(families))
        await db.execute(delete(DocsPortalSession).where(DocsPortalSession.token_id.in_(tokens)))
        await db.execute(delete(PartnerToken).where(PartnerToken.family_id.in_(families)))
        await db.execute(delete(PartnerTokenFamily).where(PartnerTokenFamily.grant_id.in_(grants)))
        await db.execute(delete(PartnerCode).where(PartnerCode.client_id.in_(w.clients)))
        await db.execute(delete(PartnerGrant).where(PartnerGrant.client_id.in_(w.clients)))
        for model in (PartnerAuthorizationRequest, PartnerSubject, PartnerCredential):
            await db.execute(delete(model).where(model.client_id.in_(w.clients)))
        await db.execute(delete(Profile).where(Profile.id == w.profile))
        await db.execute(delete(PartnerResourceScope).where(PartnerResourceScope.installation_id.in_(w.installations)))
        await db.execute(delete(PartnerInstallation).where(PartnerInstallation.id.in_(w.installations)))
        await db.execute(delete(CompanyApp).where(CompanyApp.id.in_(w.installations)))
        await db.execute(delete(PartnerClient).where(PartnerClient.id.in_(w.clients)))
        await db.execute(delete(App).where(App.id.in_(w.apps)))
        await db.execute(delete(UserCompany).where(UserCompany.user_id == w.employee))
        await db.execute(delete(User).where(User.id == w.employee))
        await db.execute(delete(CompanyRole).where(CompanyRole.id == w.role))
        await db.commit()
    async with w.factory() as db:
        for model, key, values in ((App, App.id, w.apps), (PartnerClient, PartnerClient.id, w.clients),
                (CompanyApp, CompanyApp.id, w.installations), (User, User.id, (w.employee,)),
                (CompanyRole, CompanyRole.id, (w.role,)), (Profile, Profile.id, (w.profile,))):
            assert await db.scalar(select(func.count()).select_from(model).where(key.in_(values))) == 0


@pytest_asyncio.fixture(loop_scope="session")
async def native_docs(issuer_world, monkeypatch):
    base = issuer_world
    suffix = uuid4().hex
    w = SimpleNamespace(factory=base.factory, company=base.company, base=base,
        employee=uuid4(), role=uuid4(), profile=uuid4(), apps=(uuid4(), uuid4()),
        clients=("docs-" + suffix, "machine-docs-" + suffix),
        installations=(uuid4(), uuid4()), machine_grant=uuid4(), secret=uuid4().hex + uuid4().hex)
    w.client_id, w.installation = w.clients[0], w.installations[0]
    # Configuration only: no auth, policy, verifier, SQL or route replacement.
    for name, value in {"partner_docs_enabled": True, "partner_api_enabled": True,
            "partner_docs_client_id": w.client_id, "partner_docs_environment": "sandbox",
            "partner_docs_sandbox_api_url": ORIGIN + "/api/v1"}.items():
        monkeypatch.setattr(portal.settings, name, value)
    try:
        async with w.factory() as db:
            role = CompanyRole(id=w.role, company_id=w.company, name="Synthetic docs employee",
                modules=["developer:docs", "equipment", "references"])
            user = User(id=w.employee, company_id=w.company, email=suffix + "@employee.invalid",
                name="Synthetic ordinary employee", password_hash="unused-no-password-login",
                role="user", is_superadmin=False, mail_only=False, last_seen_at=identity.now())
            db.add_all([role, user]); await db.flush()
            db.add(UserCompany(user_id=w.employee, company_id=w.company, role="user", role_id=w.role,
                modules=[], object_scope=[base.loc]))
            for index in range(2):
                db.add(App(id=w.apps[index], code=f"nd-{index}-{suffix}", name="Synthetic docs setup",
                    kind="partner", is_active=True))
            await db.flush()
            db.add_all([PartnerClient(id=w.client_id, app_id=w.apps[0], owner_company_id=w.company,
                auth_method="none", enabled=True,
                redirect_uris=[CALLBACK, ORIGIN + portal.PREFIX + "/oauth2-redirect"],
                allowed_scopes=[*SCOPES, "objects:read", "contracts:create"]),
                PartnerClient(id=w.clients[1], app_id=w.apps[1], owner_company_id=w.company,
                    auth_method="client_secret_basic", enabled=True, redirect_uris=[], allowed_scopes=["docs:read"])])
            await db.flush()
            db.add_all([CompanyApp(id=iid, company_id=w.company, app_id=aid, enabled=True)
                for iid, aid in zip(w.installations, w.apps)])
            await db.flush()
            db.add_all([PartnerInstallation(id=iid, client_id=cid, company_id=w.company,
                approved=True, all_locations=True, scopes=[*SCOPES, "objects:read", "contracts:create"] if index == 0 else ["docs:read"])
                for index, (iid, cid) in enumerate(zip(w.installations, w.clients))])
            await db.flush()
            db.add_all([PartnerResourceScope(installation_id=w.installation, kind="objects", mode="ALL"),
                PartnerResourceScope(installation_id=w.installation, kind="counterparties", mode="ALL"),
                PartnerCredential(id=uuid4(), client_id=w.clients[1], secret_hash=identity.digest(w.secret),
                    enabled=True, expires_at=identity.now() + timedelta(minutes=10)),
                PartnerGrant(id=w.machine_grant, installation_id=w.installations[1], client_id=w.clients[1],
                    company_id=w.company, kind="machine", user_id=None, approved=True, scopes=["docs:read"])])
            db.add(Profile(id=w.profile, installation_id=w.installation, client_id=w.client_id,
                company_id=w.company, user_enabled=True, service_enabled=False, revoked=False, policy_generation=1))
            await db.flush()
            db.add_all([Principal(id=uuid4(), profile_id=w.profile, actor_kind="user", user_id=w.employee),
                Ref(id=uuid4(), profile_id=w.profile, kind="organization", organization_id=base.org),
                Ref(id=uuid4(), profile_id=w.profile, kind="counterparty", counterparty_id=base.cp),
                Ref(id=uuid4(), profile_id=w.profile, kind="location", location_id=base.loc),
                Type(profile_id=w.profile, type_code=base.code)])
            await db.commit()
            w.native = token_for(user, expires_at=identity.now() + timedelta(minutes=10))
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        app.add_exception_handler(identity.PartnerProblem, identity.problem_handler)
        for router in (partner_oauth_router.router, partner_oauth_router.consent_router, docs_portal_router.router):
            app.include_router(router, prefix="/api")
        async def actual_sessions():
            async with w.factory() as db:
                yield db
        app.dependency_overrides[get_db] = actual_sessions
        child = create_product_api(session_factory=w.factory, enabled=True, issuer=ORIGIN,
            source_revision="synthetic-native-docs")
        policy_registry(child)
        app.state.product_api = child
        app.mount("/api/v1", child)
        w.app = app
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=True),
                base_url=ORIGIN, timeout=5, follow_redirects=False) as http:
            w.http = http
            yield w
    finally:
        async with asyncio.timeout(20):
            await cleanup_owned(w)


async def request(w, method, path, **kwargs):
    # Bound the real ASGI call, including handler SQL; no decision replacement.
    async with asyncio.timeout(8):
        return await w.http.request(method, path, **kwargs)


async def pending(w, scopes=None, **changes):
    params = dict(client_id=w.client_id, response_type="code", redirect_uri=CALLBACK,
        scope=" ".join(scopes or SCOPES), state=uuid4().hex, nonce=uuid4().hex,
        code_challenge=CHALLENGE, code_challenge_method="S256", prompt="consent")
    params.update(changes)
    response = await request(w, "GET", "/api/oauth2/authorize", params=params)
    return response, params


async def approved_code(w, scopes=None):
    scopes = scopes or SCOPES
    response, params = await pending(w, scopes)
    assert response.status_code == 302
    target = urlsplit(response.headers["location"])
    assert target.path == "/developer/authorize" and not target.netloc
    rid = parse_qs(target.query)["requestId"][0]
    detail = await request(w, "GET", "/api/developer/authorization-requests/" + rid, headers=bearer(w.native))
    assert detail.status_code == 200
    assert detail.json()["companies"] == [{"id": str(w.company), "name": "Synthetic issuer", "eligibleScopes": sorted(scopes)}]
    response = await request(w, "POST", "/api/developer/authorization-requests/" + rid + "/approve",
        headers=bearer(w.native), json={"companyId": str(w.company), "scopes": scopes})
    assert response.status_code == 200
    callback = urlsplit(response.json()["redirectUrl"])
    assert (callback.scheme, callback.netloc, callback.path) == ("https", "issuer.synthetic.invalid", "/developer/api/callback")
    query = parse_qs(callback.query)
    assert query["state"] == [params["state"]] and set(query) == {"state", "code"}
    code = query["code"][0]
    async with w.factory() as db:
        row = await db.get(PartnerCode, identity.digest(code))
        auth_request = await db.get(PartnerAuthorizationRequest, UUID(rid))
        grant = await db.get(PartnerGrant, row.grant_id)
        assert auth_request.finished and auth_request.user_id == w.employee
        assert row.nonce == params["nonce"] and row.code_challenge == CHALLENGE
        assert row.code_challenge_method == "S256" and not row.consumed
        assert grant.user_id == w.employee and grant.installation_id == w.installation and grant.kind == "user"
    return code, params


async def exchange(w, code, **changes):
    form = dict(grant_type="authorization_code", client_id=w.client_id, code=code,
        redirect_uri=CALLBACK, code_verifier=VERIFIER)
    form.update(changes)
    return await request(w, "POST", "/api/oauth2/token", data=form)


async def issue(w, scopes=None):
    code, params = await approved_code(w, scopes)
    response = await exchange(w, code)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    tokens = response.json()
    assert set(tokens["scope"].split()) == set(scopes or SCOPES)
    if "openid" in (scopes or SCOPES):
        key = jwt.algorithms.RSAAlgorithm.from_jwk(identity.public_jwks()["keys"][0])
        claims = jwt.decode(tokens["id_token"], key, algorithms=["RS256"], audience=w.client_id, issuer=ORIGIN)
        assert claims["nonce"] == params["nonce"]
    async with w.factory() as db:
        verified = await identity.verify_partner_access_token(tokens["access_token"], db)
        assert verified.user_id == w.employee and not verified.is_machine
        assert verified.installation_id == w.installation and verified.company_id == w.company
        assert (await db.get(PartnerCode, identity.digest(code))).consumed
    return tokens["access_token"], verified


async def bootstrap(w, access):
    return await request(w, "POST", portal.PREFIX + "/session", headers={**bearer(access),
        "Origin": ORIGIN, "X-Docs-CSRF": "bootstrap"})


async def opened(w):
    access, verified = await issue(w)
    response = await bootstrap(w, access)
    assert response.status_code == 200
    raw = w.http.cookies.get(portal.COOKIE)
    assert raw and response.json()["csrfToken"] == portal.csrf(raw)
    return access, verified, raw, response


async def test_native_employee_code_pkce_cookie_and_exact_product_projection(native_docs):
    w = native_docs
    access, verified, raw, response = await opened(w)
    cookie = response.headers["set-cookie"]
    assert all(value in cookie for value in ("Secure", "HttpOnly", "SameSite=strict", "Path=" + portal.PREFIX))
    assert access not in cookie and w.native not in cookie
    async with w.factory() as db:
        user = await db.get(User, w.employee)
        member = await db.get(UserCompany, (w.employee, w.company))
        row = await db.get(DocsPortalSession, identity.digest(raw))
        assert not user.is_superadmin and user.role == member.role == "user"
        assert row.token_id == verified.token_id and not row.revoked
        assert row.expires_at <= verified.expires_at and row.expires_at <= identity.now() + timedelta(seconds=180)
    for path in SURFACES:
        response = await request(w, "GET", portal.PREFIX + path)
        assert response.status_code == 200, path
        assert response.content
        private(response)
    info = await request(w, "GET", portal.PREFIX + "/session")
    assert info.json()["userId"] == str(w.employee) and info.json()["companyId"] == str(w.company)
    browser = (await request(w, "GET", portal.PREFIX + "/openapi.json")).json()
    server = (await request(w, "GET", portal.PREFIX + "/openapi.server.json")).json()
    for schema in (browser, server):
        actual = {(path, method): operation["operationId"] for path, item in schema["paths"].items()
            for method, operation in item.items() if isinstance(operation, dict) and "operationId" in operation}
        assert actual == OPERATIONS
        assert len(actual) == 18 and len(schema["paths"]) == 17
        assert schema["servers"] == [{"url": ORIGIN + "/api/v1"}]
    assert set(browser["components"]["securitySchemes"]) == {"ProductOAuth"}
    assert set(server["components"]["securitySchemes"]) == {"ProductOAuth", "ProductServiceOAuth"}
    assert set(browser["components"]["securitySchemes"]["ProductOAuth"]["flows"]) == {"authorizationCode"}
    projection = browser["x-elsy-authentication-projection"]
    assert projection["kind"] == "public-code-pkce"
    assert projection["serverOnlyProfiles"]["ProductServiceOAuth"] == server["components"]["securitySchemes"]["ProductServiceOAuth"]
    for path, method in OPERATIONS:
        canonical = server["paths"][path][method]
        public = browser["paths"][path][method]
        assert public["security"] == [value for value in canonical["security"] if set(value) == {"ProductOAuth"}]
        assert {k: v for k, v in public.items() if k != "security"} == {k: v for k, v in canonical.items() if k != "security"}


@pytest.mark.parametrize("credential", ["native", "product"])
async def test_bearers_cannot_replace_docs_cookie(native_docs, credential):
    w = native_docs
    access = w.native if credential == "native" else (await issue(w, ["objects:read"]))[0]
    for path in SURFACES:
        response = await request(w, "GET", portal.PREFIX + path, headers=bearer(access))
        assert response.status_code == 401
        private(response)


@pytest.mark.parametrize("invalid", ["redirect", "state", "nonce", "pkce", "scope"])
async def test_public_authorize_rejects_invalid_protocol_inputs(native_docs, invalid):
    w = native_docs
    changes = {"redirect": {"redirect_uri": "https://foreign.invalid/callback"}, "state": {"state": ""},
        "nonce": {"nonce": ""}, "pkce": {"code_challenge_method": "plain"}, "scope": {"scope": "openid documents:read"}}
    response, _ = await pending(w, **changes[invalid])
    assert response.status_code == 400 and "location" not in response.headers
    assert response.json()["error"] in {"invalid_request", "invalid_scope", "invalid_redirect_uri"}
    async with w.factory() as db:
        assert await db.scalar(select(func.count()).select_from(PartnerCode).where(PartnerCode.client_id == w.client_id)) == 0


@pytest.mark.parametrize("invalid", ["verifier", "redirect"])
async def test_code_exchange_rejects_wrong_binding_without_consumption(native_docs, invalid):
    w = native_docs
    code, _ = await approved_code(w)
    changes = {"code_verifier": "A" * 43} if invalid == "verifier" else {"redirect_uri": ORIGIN + portal.PREFIX + "/oauth2-redirect"}
    response = await exchange(w, code, **changes)
    assert response.status_code == 400 and response.json()["error"] == "invalid_grant"
    async with w.factory() as db:
        assert not (await db.get(PartnerCode, identity.digest(code))).consumed
    # Same actual code succeeds only with its original redirect/verifier.
    assert (await exchange(w, code)).status_code == 200


@pytest.mark.parametrize("revoked", ["member", "role"])
async def test_consent_rechecks_employee_authority_after_page_open(native_docs, revoked):
    w = native_docs
    response, _ = await pending(w)
    rid = parse_qs(urlsplit(response.headers["location"]).query)["requestId"][0]
    url = "/api/developer/authorization-requests/" + rid
    assert (await request(w, "GET", url, headers=bearer(w.native))).status_code == 200
    async with w.factory() as db:
        if revoked == "member":
            await db.delete(await db.get(UserCompany, (w.employee, w.company)))
        else:
            (await db.get(CompanyRole, w.role)).modules = []
        await db.commit()
    response = await request(w, "POST", url + "/approve", headers=bearer(w.native),
        json={"companyId": str(w.company), "scopes": SCOPES})
    assert response.status_code == 422 and response.json()["code"] == "INVALID_AUTHORIZATION_SELECTION"
    async with w.factory() as db:
        assert await db.scalar(select(func.count()).select_from(PartnerGrant).where(PartnerGrant.client_id == w.client_id)) == 0


@pytest.mark.parametrize("revoked", ["grant", "member", "client", "installation", "actor_mail_only", "actor_tv"])
async def test_current_authority_closes_existing_cookie_and_new_issuance(native_docs, revoked):
    w = native_docs
    access, verified, raw, _ = await opened(w)
    async with w.factory() as db:
        if revoked == "grant":
            (await db.get(PartnerGrant, verified.grant_id)).approved = False
        elif revoked == "member":
            await db.delete(await db.get(UserCompany, (w.employee, w.company)))
        elif revoked == "client":
            (await db.get(PartnerClient, w.client_id)).enabled = False
        elif revoked == "installation":
            (await db.get(CompanyApp, w.installation)).enabled = False
        elif revoked == "actor_mail_only":
            (await db.get(User, w.employee)).mail_only = True
        else:
            (await db.get(User, w.employee)).token_version += 1
        await db.commit()
    for path in (*SURFACES, "/session"):
        response = await request(w, "GET", portal.PREFIX + path)
        assert response.status_code == 401
        private(response)
    response = await bootstrap(w, access)
    assert response.status_code == 401 and "set-cookie" not in response.headers
    async with w.factory() as db:
        assert (await db.get(DocsPortalSession, identity.digest(raw))).token_id == verified.token_id


@pytest.mark.parametrize("credential,method", [("cookie", "GET"), ("cookie", "POST"), ("docs", "GET"), ("docs", "POST")],
    ids=["cookie-read", "cookie-write", "docs-read", "docs-write"])
async def test_docs_capabilities_grant_no_product_read_or_write(native_docs, credential, method):
    w = native_docs
    access, _, raw, _ = await opened(w)
    # Real business token and owned object establish an enabled READ composition.
    product, _ = await issue(w, ["objects:read"])
    positive = await request(w, "GET", "/api/v1/objects", headers=bearer(product))
    assert positive.status_code == 200 and any(item["id"] == w.base.loc for item in positive.json()["items"])
    # A live canonical profile accepts the same employee with actual write scope.
    # This is read-only preflight, never a successful POST or an activation proof.
    write_access, _ = await issue(w, ["contracts:create"])
    async with w.factory() as db:
        current = await identity.verify_partner_access_token(write_access, db)
        await require_coarse_create(db, current)
        assert (await db.get(Profile, w.profile)).user_enabled
    before = await state(w.base)
    body = w.base.body.model_dump(mode="json", by_alias=True)
    headers = bearer(access) if credential == "docs" else {"Cookie": portal.COOKIE + "=" + raw}
    response = await request(w, method, "/api/v1/objects" if method == "GET" else "/api/v1/contracts",
        headers=headers, **({"json": body} if method == "POST" else {}))
    expected = 401 if credential == "cookie" else 403
    assert response.status_code == expected
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == ("invalid_credentials" if expected == 401 else "access_denied")
    assert response.headers["cache-control"] == "no-store" and response.headers["www-authenticate"].startswith("Bearer")
    assert await state(w.base) == before


async def test_real_machine_docs_scope_cannot_bootstrap_browser_session(native_docs):
    w = native_docs
    response = await request(w, "POST", "/api/oauth2/token", auth=(w.clients[1], w.secret),
        data={"grant_type": "client_credentials", "grant_id": str(w.machine_grant), "scope": "docs:read"})
    assert response.status_code == 200
    access = response.json()["access_token"]
    async with w.factory() as db:
        verified = await identity.verify_partner_access_token(access, db)
        assert verified.is_machine and verified.user_id is None and verified.scopes == frozenset({"docs:read"})
    response = await bootstrap(w, access)
    assert response.status_code == 403 and "set-cookie" not in response.headers
    assert (await request(w, "GET", portal.PREFIX + "/ui", headers=bearer(access))).status_code == 401


async def test_employee_logout_with_origin_csrf_closes_next_access(native_docs):
    w = native_docs
    access, verified, raw, _ = await opened(w)
    response = await request(w, "DELETE", portal.PREFIX + "/session", headers={"Origin": ORIGIN, "X-Docs-CSRF": portal.csrf(raw)})
    assert response.status_code == 204 and response.content == b""
    private(response)
    assert "Max-Age=0" in response.headers["set-cookie"]
    # Explicit stale cookie tests server invalidation independently of cookie deletion.
    response = await request(w, "GET", portal.PREFIX + "/ui", headers={"Cookie": portal.COOKIE + "=" + raw})
    assert response.status_code == 401
    assert (await bootstrap(w, access)).status_code == 401
    async with w.factory() as db:
        assert (await db.get(DocsPortalSession, identity.digest(raw))).revoked
        token = await db.get(PartnerToken, verified.token_id)
        assert (await db.get(PartnerTokenFamily, token.family_id)).revoked
