"""M18 actual app.main ASGI/PG proposal; only the approved ROOT runner executes.

No current_user/verifier/handler overrides, no fabricated tokens, no shared
conftest/production seed. All credentials are issued by actual HTTP handlers.
"""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

if os.environ.get("RUN_PARTNER_MAIN_COMPOSITION_TESTS") != "1":
    pytest.skip("ROOT-only M18 composition suite", allow_module_level=True)
if os.environ.get("ROOT_APPROVED_PARTNER_MAIN_COMPOSITION") != "1":
    raise pytest.UsageError("Use the immutable ROOT-approved M18 runner")

import jwt
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text

from app import database, main
from app.auth import hash_password
from app.models import (Company, CompanyRole, Contract, ContractLocation, Counterparty,
                        DocCard, DocKind, DocVersion, EzsEquipmentUnit, Organization,
                        ServiceLocation, SourceFile, User, UserCompany)
from app.models_partner import PartnerCode, PartnerGrant

pytestmark = pytest.mark.asyncio(loop_scope="session")
ISSUER = "https://m18-space.example.invalid"
REDIRECT = "https://m18-partner.example.invalid/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
PASSWORD = "M18-synthetic-password-only-20261030!"
DOC_PREFIX = "/api/developer/docs"
DOC_PATHS = ("/session", "/ui", "/openapi.json", "/openapi.server.json",
             "/assets/swagger-ui-bundle.js", "/assets/swagger-ui.css", "/assets/portal-init.js",
             "/assets/oauth-callback.js", "/oauth2-redirect")
# Exact auth/registry tables, not a wildcard that hides future business tables.
AUTH_TABLES = frozenset("public." + name for name in (
    "eco_apps", "eco_company_apps", "audit_events", "partner_clients", "partner_credentials",
    "partner_installations", "partner_installation_locations", "partner_resource_scopes",
    "partner_resource_items", "partner_grants", "partner_authorization_requests", "partner_subjects",
    "partner_codes", "partner_token_families", "partner_tokens", "partner_docs_sessions"))
USER_AUTH_FIELDS = ("last_seen_at", "failed_logins", "locked_until")


def evidence(name, value):
    path = Path(os.environ["M18_EVIDENCE_DIR"]) / name
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def quote(value):
    return '"' + value.replace('"', '""') + '"'


async def persisted_snapshot():
    """Independent read-only database oracle; no ORM identity map/projection.

    Every ordinary public/edge relation is included, even tables not mapped in
    Base.metadata. Rows are canonical PG jsonb text, sorted before hashing.
    users retain ALL fields in the business half except three explicit login
    fields, which also receive a separate full-row keyed auth fingerprint.
    """
    async with database.engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            assert await conn.scalar(text("SHOW transaction_read_only")) == "on"
            tables = (await conn.execute(text(
                "SELECT n.nspname, c.relname FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname IN ('public','edge') AND c.relkind IN ('r','p') "
                "ORDER BY n.nspname,c.relname"))).all()
            assert tables and len(tables) <= 700
            business, auth = {}, {}
            for schema, table in tables:
                name = schema + "." + table
                relation = quote(schema) + "." + quote(table)
                row = "to_jsonb(t)"
                if name == "public.users":
                    row += " - ARRAY['last_seen_at','failed_logins','locked_until']::text[]"
                result = (await conn.execute(text(
                    "SELECT count(*), md5(COALESCE(string_agg(r::text, E'\\n' ORDER BY r::text), '')) "
                    f"FROM (SELECT {row} AS r FROM {relation} t) rows"))).one()
                (auth if name in AUTH_TABLES else business)[name] = list(result)
                if name == "public.users":
                    result = (await conn.execute(text(
                        "SELECT count(*), md5(COALESCE(string_agg(r::text, E'\\n' ORDER BY r::text), '')) "
                        "FROM (SELECT jsonb_build_object('id', id, 'last_seen_at', last_seen_at, "
                        "'failed_logins', failed_logins, 'locked_until', locked_until) r FROM public.users) rows"
                    ))).one()
                    auth["public.users.login_fields"] = list(result)
            assert AUTH_TABLES <= set(auth), "the explicit auth inventory must exist"
            assert await conn.scalar(text("SELECT pg_database_size(current_database())")) < 256 * 1024 * 1024
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(Path(os.environ["UPLOAD_DIR"]).iterdir()) if p.is_file()}
    return {"business": business, "auth": auth, "files": files}


class Proof:
    def __init__(self, name, baseline):
        self.name, self.baseline, self.previous = name, baseline, baseline
        self.phases = []

    async def check(self, phase, allowed=(), required=()):
        current = await persisted_snapshot()
        # Write observations BEFORE assertions so a failure preserves its cause.
        changed = sorted(k for k in set(current["auth"]) | set(self.previous["auth"])
                         if current["auth"].get(k) != self.previous["auth"].get(k))
        self.phases.append({"phase": phase, "changed_auth_tables": changed,
                            "allowed_auth_tables": sorted(allowed), "required_auth_tables": sorted(required),
                            "snapshot": current})
        evidence(self.name + "-" + str(len(self.phases)) + ".json", self.phases[-1])
        assert current["business"] == self.baseline["business"], "persisted business rows changed"
        assert current["files"] == self.baseline["files"], "fixture bytes changed"
        assert set(changed) <= set(allowed), "unexpected persisted auth/registry writes"
        assert set(required) <= set(changed), "expected auth transition was not persisted"
        self.previous = current


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def composed(request):
    boundary = request.config._m18_boundary
    assert main is boundary.application and main.app.dependency_overrides == {}
    assert main.app.state.product_api.dependency_overrides == {}

    def limits(dbapi_connection, record):
        cursor = dbapi_connection.cursor()
        for statement in ("SET statement_timeout='20000'", "SET lock_timeout='2000'",
                          "SET idle_in_transaction_session_timeout='30000'"):
            cursor.execute(statement)
        cursor.close()
    event.listen(database.engine.sync_engine, "connect", limits)
    try:
        async with database.engine.begin() as conn:
            assert await conn.scalar(text("SELECT current_database()")) == "api_partner_main_test_20261030"
            assert await conn.scalar(text("SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                                          "ON n.oid=c.relnamespace WHERE n.nspname IN ('public','edge') "
                                          "AND c.relkind IN ('r','p','v','m','f')")) == 0
            assert await conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                                          "AND backend_type='client backend' AND pid<>pg_backend_pid()")) == 0
            await conn.execute(text("CREATE SCHEMA edge"))
        # Actual application DDL/migrations, no Base.create_all surrogate/seed.
        await database.create_all()
        async with main.app.router.lifespan_context(main.app):
            await asyncio.sleep(0)
            assert len(boundary.jobs) == 8
            yield boundary
        await asyncio.gather(*boundary.jobs, return_exceptions=True)
        assert all(job.cancelled() for job in boundary.jobs)
    finally:
        event.remove(database.engine.sync_engine, "connect", limits)
        await database.engine.dispose()
    # Database removal belongs to ROOT; no DROP SCHEMA/DATABASE in this suite.


@pytest_asyncio.fixture(loop_scope="session")
async def fixture(composed, request):
    suffix = uuid.uuid4().hex[:12]
    async with database.async_session_factory() as db:
        companies = [Company(name="M18 synthetic " + str(i), slug="m18-" + suffix + str(i),
                             profile_id="energy") for i in range(2)]
        db.add_all(companies)
        await db.flush()
        cid, foreign_cid = [c.id for c in companies]
        users = [User(company_id=cid, name="M18 " + name, email=suffix + name + "@example.com",
                      password_hash=hash_password(PASSWORD), role="user", is_superadmin=False, mail_only=False)
                 for name in ("owner", "employee", "docs-employee")]
        db.add_all(users)
        await db.flush()
        locations = [ServiceLocation(id="m18-" + suffix + "-" + str(i),
                     company_id=(foreign_cid if i == 3 else cid), name="M18 object " + str(i),
                     code="M18-" + str(i), type="ev_charging", status="active",
                     extra_metadata={"secret": "M18-PRIVATE-BUSINESS"}) for i in range(4)]
        db.add_all(locations)
        role = CompanyRole(company_id=cid, name="M18 explicit documents employee", modules=["docs", "equipment"])
        db.add(role)
        await db.flush()
        db.add_all([UserCompany(user_id=users[0].id, company_id=cid, role="admin", modules=None),
                    UserCompany(user_id=users[1].id, company_id=cid, role="user", modules=["equipment"],
                                object_scope=[locations[0].id]),
                    UserCompany(user_id=users[2].id, company_id=cid, role="user", role_id=role.id,
                                modules=[], object_scope=[locations[0].id])])
        orgs = [Organization(company_id=c.id, name="M18 organization", inn="9999999999") for c in companies]
        parties = [Counterparty(company_id=p.company_id, name="M18 party " + str(i),
                                raw={"secret": "M18-PRIVATE-BUSINESS"}) for i, p in enumerate(locations)]
        db.add_all([*orgs, *parties])
        await db.flush()
        contracts = [Contract(company_id=p.company_id, number="M18-" + str(i), date="2026-10-30", type="service",
                     counterparty_id=parties[i].id, organization_id=orgs[1 if i == 3 else 0].id,
                     scope_type="locations") for i, p in enumerate(locations)]
        equipment = [EzsEquipmentUnit(company_id=p.company_id, kind="station", vendor="M18 synthetic",
                     model="Fixture", current_location_id=p.id, state="in_operation") for p in locations]
        db.add_all([*contracts, *equipment])
        await db.flush()
        db.add_all([ContractLocation(company_id=c.company_id, contract_id=c.id, location_id=p.id)
                    for c, p in zip(contracts, locations)])
        kinds = [DocKind(company_id=c.id, code="m18", name="M18 kind", fields=[], route=[]) for c in companies]
        db.add_all(kinds)
        await db.flush()
        docs = [DocCard(company_id=foreign_cid if i == 3 else cid, kind_id=kinds[1 if i == 3 else 0].id,
                title="M18 document " + str(i), confidentiality="private" if i == 1 else "company",
                author_id=users[0].id if i != 3 else None, object_id=locations[0 if i < 2 else i].id,
                current_revision=1) for i in range(4)]
        db.add_all(docs)
        await db.flush()
        files, versions, contents = [], [], []
        for i, doc in enumerate(docs):
            fid = uuid.uuid4()
            content = b"M18 KNOWN SYNTHETIC BYTES\x00\xff\n" + bytes([i])
            path = Path(os.environ["UPLOAD_DIR"]) / (str(fid) + ".txt")
            path.write_bytes(content)
            path.chmod(0o600)
            source = SourceFile(id=fid, company_id=doc.company_id, file_name="m18.txt", mime_type="text/plain",
                                size=len(content), storage_path=str(path), fingerprint=hashlib.sha256(content).hexdigest())
            version = DocVersion(company_id=doc.company_id, doc_id=doc.id, revision=1, role="body",
                                 file_id=fid, file_name="m18.txt", mime="text/plain", size_bytes=len(content),
                                 sha256=hashlib.sha256(content).hexdigest())
            db.add(source)
            files.append(source)
            versions.append(version)
            contents.append(content)
        await db.flush()
        db.add_all(versions)
        await db.commit()
    baseline = await persisted_snapshot()
    evidence(request.node.name + "-baseline.json", baseline)
    ip = "192.0.2." + str(10 + list(request.session.items).index(request.node))
    async with AsyncClient(transport=ASGITransport(app=main.app, client=(ip, 41018)),
                           base_url=ISSUER, follow_redirects=False) as client:
        try:
            yield {"client": client, "companies": companies, "users": users, "locations": locations,
                   "equipment": equipment, "parties": parties, "contracts": contracts, "docs": docs,
                   "files": files, "versions": versions, "contents": contents,
                   "proof": Proof(request.node.name, baseline), "settings": composed.settings}
        finally:
            final = await persisted_snapshot()
            evidence(request.node.name + "-final.json", final)
            assert final["business"] == baseline["business"], "final persisted business rows changed"
            assert final["files"] == baseline["files"], "final fixture bytes changed"


def checked(response, status):
    # Never put a successful token/callback body in logs on assertion failure.
    assert response.status_code == status, (response.request.method, response.request.url.path,
                                          response.status_code, response.headers.get("x-request-id"))
    return response


def bearer(raw):
    return {"Authorization": "Bearer " + raw}


async def login(f, index):
    user = f["users"][index]
    response = checked(await f["client"].post("/api/auth/login", json={"email": user.email, "password": PASSWORD}), 200)
    token = response.json()["access_token"]
    assert response.json()["user"]["id"] == str(user.id)
    checked(await f["client"].get("/api/auth/me", headers=bearer(token)), 200)
    checked(await f["client"].post("/api/auth/gate", headers=bearer(token)), 204)
    checked(await f["client"].get("/api/auth/gate-check"), 204)
    await f["proof"].check("native-login-" + str(index),
                           {"public.users.login_fields", "public.audit_events"}, {"public.users.login_fields"})
    f.setdefault("core_subjects", {})[token] = user.id
    return token


async def register(f, owner, scopes, *, portal=False, auth_method="none"):
    headers = bearer(owner)
    redirects = [ISSUER + "/developer/api/callback", ISSUER + DOC_PREFIX + "/oauth2-redirect"] if portal else [REDIRECT]
    cid = str(f["companies"][0].id)
    response = checked(await f["client"].post("/api/developer/clients", headers=headers, json={
        "companyId": cid, "name": "M18 synthetic external", "redirectUris": redirects,
        "scopes": scopes, "authMethod": auth_method}), 201)
    client_id = response.json()["clientId"]
    checked(await f["client"].post(f"/api/developer/clients/{client_id}/status", headers=headers,
                                    json={"enabled": True}), 200)
    installation = checked(await f["client"].post(f"/api/developer/clients/{client_id}/installations", headers=headers, json={
        "companyId": cid, "scopes": scopes, "locationIds": [p.id for p in f["locations"][:2]],
        "resourceScopes": {"objects": {"mode": "SET", "ids": [p.id for p in f["locations"][:2]]},
            **{kind: {"mode": "ALL", "ids": []} for kind in ("equipment", "counterparties", "contracts", "documents")}}}), 201)
    f["installation_id"] = installation.json()["installationId"]
    await f["proof"].check("admin-registration-installation", {
        "public.eco_apps", "public.eco_company_apps", "public.partner_clients", "public.partner_installations",
        "public.partner_installation_locations", "public.partner_resource_scopes", "public.partner_resource_items"},
        {"public.eco_apps", "public.partner_clients", "public.partner_installations"})
    return client_id, redirects[0]


async def pending(f, client_id, redirect, scopes):
    state, nonce = uuid.uuid4().hex, uuid.uuid4().hex
    response = checked(await f["client"].get("/api/oauth2/authorize", params={"response_type": "code",
        "client_id": client_id, "redirect_uri": redirect, "scope": " ".join(scopes), "state": state,
        "nonce": nonce, "code_challenge": CHALLENGE, "code_challenge_method": "S256"}), 302)
    target = urlsplit(response.headers["location"])
    assert target.path == "/developer/authorize"
    rid = parse_qs(target.query)["requestId"][0]
    await f["proof"].check("authorize-pending", {"public.partner_authorization_requests"},
                           {"public.partner_authorization_requests"})
    return rid, state, nonce


async def consent(f, core, client_id, redirect, scopes):
    rid, state, nonce = await pending(f, client_id, redirect, scopes)
    path = "/api/developer/authorization-requests/" + rid
    page = checked(await f["client"].get(path, headers=bearer(core)), 200).json()
    assert page["companies"] and {v["id"] for v in page["companies"]} == {str(f["companies"][0].id)}
    assert set(scopes) <= set(page["companies"][0]["eligibleScopes"])
    response = checked(await f["client"].post(path + "/approve", headers=bearer(core), json={
        "companyId": str(f["companies"][0].id), "scopes": scopes}), 200)
    callback = urlsplit(response.json()["redirectUrl"])
    assert callback.scheme + "://" + callback.netloc + callback.path == redirect
    values = parse_qs(callback.query)
    assert values["state"] == [state]
    await f["proof"].check("consent-post", {"public.partner_authorization_requests", "public.partner_grants", "public.partner_codes"},
                           {"public.partner_authorization_requests", "public.partner_grants", "public.partner_codes"})
    exchange = {"grant_type": "authorization_code", "client_id": client_id, "redirect_uri": redirect,
                "code": values["code"][0], "code_verifier": VERIFIER}
    tokens = checked(await f["client"].post("/api/oauth2/token", data=exchange), 200).json()
    await f["proof"].check("token-exchange", {"public.partner_codes", "public.partner_token_families",
                           "public.partner_tokens", "public.partner_subjects"},
                           {"public.partner_codes", "public.partner_token_families", "public.partner_tokens", "public.partner_subjects"})
    async with database.async_session_factory() as db:
        code_row = await db.get(PartnerCode, hashlib.sha256(values["code"][0].encode()).hexdigest())
        grant_row = await db.get(PartnerGrant, code_row.grant_id)
        assert code_row.consumed and grant_row.kind == "user" and grant_row.approved
        assert grant_row.user_id == f["core_subjects"][core] and grant_row.company_id == f["companies"][0].id
        assert set(grant_row.scopes) == set(scopes)
    # Actual signed tokens validated independently from HTTP JWKS, not decoded
    # with verification disabled or constructed from a test signing helper.
    keys = checked(await f["client"].get("/api/oauth2/jwks"), 200).json()["keys"]
    key = jwt.PyJWK.from_dict(next(k for k in keys if k["kid"] == jwt.get_unverified_header(tokens["id_token"])["kid"]))
    identity = jwt.decode(tokens["id_token"], key.key, algorithms=["RS256"], issuer=ISSUER, audience=client_id,
                          options={"require": ["iss", "aud", "sub", "iat", "exp", "nonce", "auth_time", "at_hash"]})
    assert identity["nonce"] == nonce and identity["token_use"] == "partner_id"
    expected_hash = base64.urlsafe_b64encode(hashlib.sha256(tokens["access_token"].encode()).digest()[:16]).rstrip(b"=").decode()
    assert identity["at_hash"] == expected_hash
    access = jwt.decode(tokens["access_token"], key.key, algorithms=["RS256"], issuer=ISSUER,
                        audience="urn:elsyplus:m18:synthetic", options={"require": ["iss", "aud", "sub", "iat", "exp"]})
    assert access["sub"] == identity["sub"] and access["token_use"] == "partner_access"
    info = checked(await f["client"].get("/api/oauth2/userinfo", headers=bearer(tokens["access_token"])), 200).json()
    assert info["sub"] == identity["sub"]
    checked(await f["client"].post("/api/oauth2/token", data=exchange), 400)
    await f["proof"].check("jwks-signature-userinfo-code-replay")
    return tokens


def problem(response, status):
    checked(response, status)
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["status"] == status
    uuid.UUID(response.json()["requestId"])
    uuid.UUID(response.headers["x-request-id"])


async def test_main_problem_request_id_matches_outer_security_context(fixture):
    # ROOT reproduced M18-RID-01 on the frozen baseline. Preserve that equality
    # for the corrective retest, without xfail/skip or middleware overrides.
    response = checked(await fixture["client"].get("/api/v1/objects"), 401)
    assert response.json()["requestId"] == response.headers["x-request-id"]
    forged = "00000000-0000-4000-8000-000000000018"
    async def request():
        response = checked(await fixture["client"].get("/api/v1/objects",
                           headers={"X-Request-Id": forged}), 401)
        assert response.json()["requestId"] == response.headers["x-request-id"]
        assert response.headers["x-request-id"] != forged
        assert uuid.UUID(response.headers["x-request-id"]).version == 4
        return response.headers["x-request-id"]
    assert await request() != response.headers["x-request-id"]
    concurrent = await asyncio.gather(*(request() for _ in range(8)))
    assert len(set(concurrent)) == 8 and response.headers["x-request-id"] not in concurrent
    await fixture["proof"].check("main-trusted-request-ID-forgery-concurrency")


async def test_standalone_child_unavailable_problem_request_id_without_sql(record_property):
    from app.product_api import create_product_api
    from app.security_context import current
    assert current.get() is None
    child = create_product_api(issuer=ISSUER, enabled=False)
    attempted = []
    def no_sql(conn, cursor, statement, parameters, context, executemany):
        attempted.append(True)
        raise AssertionError("standalone disabled child must not execute SQL")
    event.listen(database.engine.sync_engine, "before_cursor_execute", no_sql)
    try:
        async with AsyncClient(transport=ASGITransport(app=child), base_url=ISSUER) as client:
            ids = []
            for _ in range(2):
                response = checked(await client.get("/objects", headers={
                    "X-Request-Id": "00000000-0000-4000-8000-000000000018"}), 503)
                assert response.json()["requestId"] == response.headers["x-request-id"]
                assert uuid.UUID(response.headers["x-request-id"]).version == 4
                assert response.headers["x-request-id"] != "00000000-0000-4000-8000-000000000018"
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["content-type"].startswith("application/problem+json")
                ids.append(response.headers["x-request-id"])
            assert len(set(ids)) == 2
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", no_sql)
        record_property("standalone_sql_attempts", len(attempted))
        evidence("standalone-request-id-no-sql.json", {"sql_attempts": len(attempted), "responses": 2})
    assert not attempted and current.get() is None


async def test_main_mount_order_anonymous_docs_and_version_guards(fixture):
    f = fixture
    from starlette.routing import Mount
    mounts = [r for r in main.app.routes if isinstance(r, Mount)]
    assert mounts[0].path == "/api/v1" and mounts[0].app is main.app.state.product_api
    assert list(main.app.routes).index(mounts[0]) < next(i for i, r in enumerate(main.app.routes) if r.path == "/api/auth/login")
    assert [m.cls.__name__ for m in main.app.user_middleware] == [
        "SecurityContextMiddleware", "CORSMiddleware", "BaseHTTPMiddleware", "BaseHTTPMiddleware", "BaseHTTPMiddleware"]
    assert [m.kwargs["dispatch"].__name__ for m in main.app.user_middleware if "dispatch" in m.kwargs] == [
        "organization_context", "conditional_get", "rate_limit_public"]
    for path in DOC_PATHS:
        denied = checked(await f["client"].get(DOC_PREFIX + path), 401)
        assert denied.headers["cache-control"] == "no-store"
        assert denied.headers["x-content-type-options"] == "nosniff"
    for path in ("/openapi.json", "/docs", "/redoc", "/api/v1/openapi.json", "/api/v1/docs", "/api/v2/objects"):
        checked(await f["client"].get(path), 404)
    problem(await f["client"].get("/api/v1/objects"), 401)
    problem(await f["client"].get("/api/v1/objects", params={"access_token": "not-a-token"}), 401)
    checked(await f["client"].get("/api/auth/gate-check"), 401)
    assert checked(await f["client"].get("/api/sso/jwks.json"), 200).json() == {"keys": []}
    metadata = checked(await f["client"].get("/.well-known/openid-configuration"), 200).json()
    assert metadata["issuer"] == ISSUER and metadata["token_endpoint"] == ISSUER + "/api/oauth2/token"
    await f["proof"].check("anonymous-main-guards")


async def test_ordinary_employee_scoped_entities_refresh_and_revoke(fixture):
    f = fixture
    owner = await login(f, 0)
    scopes = ["openid", "profile", "email", "offline_access", "objects:read", "equipment:read"]
    client_id, redirect = await register(f, owner, scopes)
    employee = await login(f, 1)
    tokens = await consent(f, employee, client_id, redirect, scopes)
    headers = bearer(tokens["access_token"])
    for kind in ("objects", "equipment"):
        expected = f["locations" if kind == "objects" else "equipment"]
        for size in (1, 200):
            page = checked(await f["client"].get("/api/v1/" + kind, params={"pageSize": size}, headers=headers), 200).json()
            assert page["total"] == 1 and [v["id"] for v in page["items"]] == [str(expected[0].id)]
            assert page["nextCursor"] is None
        for row in expected[1:]:
            problem(await f["client"].get("/api/v1/" + kind + "/" + str(row.id), headers=headers), 404)
    problem(await f["client"].get("/api/v1/objects", headers=headers,
                                 params={"companyId": str(f["companies"][1].id)}), 422)
    overridden = checked(await f["client"].get("/api/v1/objects", headers={**headers,
        "X-Company-Id": str(f["companies"][1].id), "X-Organization-Id": str(uuid.uuid4())}), 200).json()
    assert [v["id"] for v in overridden["items"]] == [f["locations"][0].id]
    for raw in (employee, tokens["id_token"]):
        problem(await f["client"].get("/api/v1/objects", headers=bearer(raw)), 401)
    checked(await f["client"].get("/api/files/" + str(f["files"][0].id), headers=headers), 401)
    await f["proof"].check("employee-read-tenant-pagination-native-file-guards")
    rotated = checked(await f["client"].post("/api/oauth2/token", data={"grant_type": "refresh_token",
        "client_id": client_id, "refresh_token": tokens["refresh_token"]}), 200).json()
    assert rotated["refresh_token"] != tokens["refresh_token"]
    await f["proof"].check("refresh-post", {"public.partner_tokens"}, {"public.partner_tokens"})
    checked(await f["client"].get("/api/v1/objects", headers=bearer(rotated["access_token"])), 200)
    checked(await f["client"].post("/api/oauth2/revoke", data={"client_id": client_id,
        "token": rotated["refresh_token"], "token_type_hint": "refresh_token"}), 200)
    await f["proof"].check("revoke-post", {"public.partner_token_families"}, {"public.partner_token_families"})
    problem(await f["client"].get("/api/v1/objects", headers=bearer(rotated["access_token"])), 401)
    checked(await f["client"].get("/api/oauth2/userinfo", headers=bearer(rotated["access_token"])), 401)
    checked(await f["client"].post("/api/oauth2/token", data={"grant_type": "refresh_token",
        "client_id": client_id, "refresh_token": rotated["refresh_token"]}), 400)
    await f["proof"].check("post-revoke-live-denial")


async def test_ordinary_employee_document_eligibility_denial_is_not_owner_consent(fixture):
    f = fixture
    owner = await login(f, 0)
    scopes = ["openid", "docs:read", "documents:read", "documents.files:download"]
    client_id, redirect = await register(f, owner, scopes)
    employee = await login(f, 1)
    rid, _, _ = await pending(f, client_id, redirect, scopes)
    path = "/api/developer/authorization-requests/" + rid
    response = checked(await f["client"].get(path, headers=bearer(employee)), 200).json()
    assert response["companies"] == [{"id": str(f["companies"][0].id),
        "name": f["companies"][0].name, "eligibleScopes": ["openid"]}]
    await f["proof"].check("employee-subject-binding", {"public.partner_authorization_requests"},
                           {"public.partner_authorization_requests"})
    denied = checked(await f["client"].post(path + "/approve", headers=bearer(employee), json={
        "companyId": str(f["companies"][0].id), "scopes": scopes}), 422)
    assert denied.json()["code"] == "INVALID_AUTHORIZATION_SELECTION"
    checked(await f["client"].get(path, headers=bearer(owner)), 404)
    checked(await f["client"].post("/api/developer/clients", headers=bearer(employee), json={
        "companyId": str(f["companies"][0].id), "name": "M18 denied employee client", "redirectUris": [REDIRECT],
        "scopes": scopes, "authMethod": "none"}), 403)
    await f["proof"].check("eligibility-selection-admin-denials-no-grant-code")
    async with database.async_session_factory() as db:
        assert not (await db.scalars(select(PartnerGrant).where(PartnerGrant.client_id == client_id))).all()
        assert not (await db.scalars(select(PartnerCode).where(PartnerCode.client_id == client_id))).all()


async def test_explicit_docs_role_employee_allowed_bytes_hidden_and_foreign_404(fixture):
    f = fixture
    owner = await login(f, 0)
    scopes = ["openid", "documents:read", "documents.files:download"]
    client_id, redirect = await register(f, owner, scopes)
    employee = await login(f, 2)
    tokens = await consent(f, employee, client_id, redirect, scopes)
    headers = bearer(tokens["access_token"])
    for size in (1, 200):
        page = checked(await f["client"].get("/api/v1/documents", headers=headers, params={"pageSize": size}), 200).json()
        assert page["total"] == 1 and [v["id"] for v in page["items"]] == [str(f["docs"][0].id)]
    for i, doc in enumerate(f["docs"]):
        path = "/api/v1/documents/" + str(doc.id)
        if i == 0:
            detail = checked(await f["client"].get(path, headers=headers), 200).json()
            assert [v["id"] for v in detail["versions"]] == [str(f["versions"][0].id)]
            body = checked(await f["client"].get(path + "/versions/" + str(f["versions"][i].id) + "/content", headers=headers), 200)
            assert body.content == f["contents"][i]
            assert hashlib.sha256(body.content).hexdigest() == f["versions"][i].sha256
        else:
            problem(await f["client"].get(path, headers=headers), 404)
            problem(await f["client"].get(path + "/versions/" + str(f["versions"][i].id) + "/content", headers=headers), 404)
    mismatch = f"/api/v1/documents/{f['docs'][0].id}/versions/{f['versions'][1].id}/content"
    problem(await f["client"].get(mismatch, headers=headers), 404)
    await f["proof"].check("ordinary-docs-role-ACL-version-content")


async def test_main_swagger_canonical_projection_assets_session_csrf_and_live_revoke(fixture):
    f = fixture
    owner = await login(f, 0)
    scopes = ["openid", "docs:read", "objects:read", "equipment:read", "counterparties:read", "contracts:read", "monitoring:read"]
    client_id, redirect = await register(f, owner, scopes, portal=True)
    f["settings"].partner_docs_client_id = client_id  # deployment config seam; no policy/verifier change
    tokens = await consent(f, owner, client_id, redirect, scopes)
    headers = {**bearer(tokens["access_token"]), "Origin": ISSUER, "X-Docs-CSRF": "bootstrap"}
    checked(await f["client"].post(DOC_PREFIX + "/session", headers={**headers, "Origin": "https://foreign.example.invalid"}), 403)
    checked(await f["client"].post(DOC_PREFIX + "/session", headers=bearer(tokens["access_token"])), 403)
    for path in DOC_PATHS:
        checked(await f["client"].get(DOC_PREFIX + path, headers=bearer(tokens["access_token"])), 401)
    created = checked(await f["client"].post(DOC_PREFIX + "/session", headers=headers), 200)
    cookie = created.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie and "path=" + DOC_PREFIX in cookie
    csrf = created.json()["csrfToken"]
    original_cookie = f["client"].cookies.get("__Secure-elsy_docs")
    assert original_cookie
    await f["proof"].check("docs-session-post", {"public.partner_docs_sessions"}, {"public.partner_docs_sessions"})
    schemas = {}
    for path in DOC_PATHS:
        response = checked(await f["client"].get(DOC_PREFIX + path), 200)
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        if path in ("/openapi.json", "/openapi.server.json"):
            schemas[path] = response.json()
    for schema in schemas.values():
        assert schema["servers"] == [{"url": ISSUER + "/api/v1"}]
        assert sum("get" in methods for methods in schema["paths"].values()) == 14
        assert not any("/auth" in p or "/developer" in p for p in schema["paths"])
    canonical = schemas["/openapi.server.json"]["components"]["securitySchemes"]
    browser = schemas["/openapi.json"]["components"]["securitySchemes"]
    assert set(canonical) == {"ProductOAuth", "ProductServiceOAuth"}
    assert set(canonical["ProductOAuth"]["flows"]) == {"authorizationCode"}
    assert set(canonical["ProductServiceOAuth"]["flows"]) == {"clientCredentials"}
    assert set(browser) == {"ProductOAuth"}
    assert set(browser["ProductOAuth"]["flows"]) == {"authorizationCode"}
    checked(await f["client"].get(DOC_PREFIX + "/openapi.server.json", params={"url": "https://foreign.example.invalid"}), 400)
    checked(await f["client"].delete(DOC_PREFIX + "/session", headers={"Origin": ISSUER}), 403)
    # Owner broad grant really paginates through two visible rows in main.
    for kind, source in (("objects", "locations"), ("equipment", "equipment"),
                         ("counterparties", "parties"), ("contracts", "contracts")):
        seen, cursor = [], None
        for _ in range(3):
            params = {"pageSize": 1, **({"cursor": cursor} if cursor else {})}
            page = checked(await f["client"].get("/api/v1/" + kind, params=params,
                                                 headers=bearer(tokens["access_token"])), 200).json()
            assert page["total"] == 2
            seen.extend(v["id"] for v in page["items"])
            cursor = page["nextCursor"]
            if not cursor:
                break
        assert not cursor and len(seen) == len(set(seen)) == 2
        assert set(seen) == {str(v.id) for v in f[source][:2]}
        if kind == "objects":
            bad = await f["client"].get("/api/v1/equipment", params={"cursor": "broken", "pageSize": 1},
                                        headers=bearer(tokens["access_token"]))
            problem(bad, 400)
    for i, location in enumerate(f["locations"]):
        monitored = await f["client"].get(f"/api/v1/objects/{location.id}/monitoring",
            params={"asOf": "2026-10-30", "days": 1}, headers=bearer(tokens["access_token"]))
        if i < 2:
            assert checked(monitored, 200).json()["pointId"] == location.id
        else:
            problem(monitored, 404)
    await f["proof"].check("swagger-read-pagination-no-DML")
    checked(await f["client"].delete(DOC_PREFIX + "/session", headers={"Origin": ISSUER, "X-Docs-CSRF": csrf}), 204)
    await f["proof"].check("docs-csrf-close", {"public.partner_docs_sessions", "public.partner_token_families"},
                           {"public.partner_docs_sessions", "public.partner_token_families"})
    for path in DOC_PATHS:
        checked(await f["client"].get(DOC_PREFIX + path), 401)
        checked(await f["client"].get(DOC_PREFIX + path,
                      headers={"Cookie": "__Secure-elsy_docs=" + original_cookie}), 401)
    problem(await f["client"].get("/api/v1/objects", headers=bearer(tokens["access_token"])), 401)
    await f["proof"].check("docs-session-and-token-live-revoked")


async def test_main_confidential_registration_admin_machine_grant_and_live_revoke(fixture):
    f = fixture
    owner = await login(f, 0)
    scopes = ["objects:read", "equipment:read"]
    client_id, _ = await register(f, owner, scopes, auth_method="client_secret_basic")
    issued = checked(await f["client"].post(f"/api/developer/clients/{client_id}/credentials", headers=bearer(owner)), 201).json()
    grant = checked(await f["client"].post(f"/api/developer/installations/{f['installation_id']}/machine-grants",
        headers=bearer(owner), json={"scopes": scopes}), 201).json()
    await f["proof"].check("admin-credential-machine-grant", {"public.partner_credentials", "public.partner_grants"},
                           {"public.partner_credentials", "public.partner_grants"})
    basic = "Basic " + base64.b64encode((client_id + ":" + issued["clientSecret"]).encode()).decode()
    tokens = checked(await f["client"].post("/api/oauth2/token", headers={"Authorization": basic},
        data={"grant_type": "client_credentials", "scope": " ".join(scopes), "grant_id": grant["grantId"]}), 200).json()
    assert "id_token" not in tokens and "refresh_token" not in tokens
    await f["proof"].check("machine-token", {"public.partner_token_families", "public.partner_tokens"},
                           {"public.partner_token_families", "public.partner_tokens"})
    for kind, source in (("objects", "locations"), ("equipment", "equipment")):
        page = checked(await f["client"].get("/api/v1/" + kind, headers=bearer(tokens["access_token"])), 200).json()
        assert page["total"] == 2 and {v["id"] for v in page["items"]} == {str(v.id) for v in f[source][:2]}
    checked(await f["client"].get("/api/oauth2/userinfo", headers=bearer(tokens["access_token"])), 403)
    problem(await f["client"].get("/api/v1/documents", headers=bearer(tokens["access_token"])), 403)
    await f["proof"].check("machine-read-identity-document-denials")
    checked(await f["client"].delete("/api/developer/grants/" + grant["grantId"], headers=bearer(owner)), 200)
    await f["proof"].check("admin-grant-revoke", {"public.partner_grants"}, {"public.partner_grants"})
    problem(await f["client"].get("/api/v1/objects", headers=bearer(tokens["access_token"])), 401)
    checked(await f["client"].post("/api/oauth2/token", headers={"Authorization": basic},
        data={"grant_type": "client_credentials", "scope": " ".join(scopes), "grant_id": grant["grantId"]}), 400)
    await f["proof"].check("machine-post-revoke-denials")
