"""Opt-in NEXT-R1 real OAuth/HTTP/PostgreSQL acceptance on one fresh exact DB.

Loaded as a ROOT-runner fixture plugin with --noconftest; no schema DROP/seed,
application main, lifespan, schedulers or external delivery. Goldens are fixture
IDs and literal expectations, never a second implementation of Query predicates.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import uuid

import pytest
import pytest_asyncio

FLAG = "RUN_PRODUCT_CONTRACT_OBJECTS_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip("ROOT opt-in NEXT-R1 runner required", allow_module_level=True)
from tests.partner_test_safety import partner_test_safety_error
if partner_test_safety_error(os.environ, flag=FLAG):
    raise pytest.UsageError("NEXT-R1 pre-import target guard refused")
_target = urlsplit(os.environ["TEST_DATABASE_URL"])
if (_target.hostname != "127.0.0.1" or _target.port != 33546
        or _target.path != "/api_contract_objects_test_20261030"
        or os.environ.get("ROOT_APPROVED_PRODUCT_CONTRACT_OBJECTS") != "1"):
    raise pytest.UsageError("Use immutable NEXT-R1 ROOT runner and exact fresh database")

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from app import database
from app.auth import hash_password
from app.models import (Company, CompanyRole, Contract, ContractLocation, Counterparty,
                        Organization, ServiceLocation, User, UserCompany)
from app.models_partner import (PartnerClient, PartnerCredential, PartnerGrant,
                                PartnerInstallation, PartnerResourceScope, PartnerTokenFamily)
from app.product_api import create_product_api, curated_openapi, export_runtime_registry
from app.product_api.app import public_client_openapi
from app.product_api.queries import Query
from app.routers import auth_router, partner_admin_router, partner_oauth_router, references_router
from app.services import partner_identity as identity

pytestmark = pytest.mark.asyncio(loop_scope="session")
ORIGIN = "https://contract-objects.example.invalid"
REDIRECT = "https://contract-objects-client.example.invalid/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
SCOPES = ["contracts:read", "objects:read"]
PASSWORD = "Contract-Objects-Synthetic-2026!"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def contract_objects_database(request):
    assert request.config._contract_objects_boundary.active
    async with database.engine.begin() as conn:
        assert await conn.scalar(text("SELECT current_database()")) == "api_contract_objects_test_20261030"
        assert await conn.scalar(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                      "WHERE n.nspname IN ('public','edge') AND c.relkind IN ('r','p','v','m','f')")) == 0
        assert await conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                                      "AND backend_type='client backend' AND pid<>pg_backend_pid()")) == 0
        await conn.execute(text("CREATE SCHEMA edge"))
    # Actual application schema/migrations on a brand-new empty ROOT-created DB.
    await database.create_all()
    try:
        yield
    finally:
        await database.engine.dispose()
    # ROOT checks fresh connections/relations and owns normal DROP DATABASE.


@pytest_asyncio.fixture(loop_scope="session")
async def db(contract_objects_database):
    async with database.async_session_factory() as session:
        yield session


@pytest.fixture(scope="session")
def password_hash():
    return hash_password(PASSWORD)


async def snapshot():
    """Fresh read-only connection; persisted PG JSONB rows, not ORM identity maps."""
    async with database.engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            assert await conn.scalar(text("SHOW transaction_read_only")) == "on"
            tables = (await conn.execute(text("SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n "
                "ON n.oid=c.relnamespace WHERE n.nspname IN ('public','edge') AND c.relkind IN ('r','p') "
                "ORDER BY n.nspname,c.relname"))).all()
            assert 1 <= len(tables) <= 700
            business, auth = {}, {}
            # Explicit exact authentication/registry inventory, no wildcard hiding new tables.
            auth_names = {"eco_apps", "eco_company_apps", "audit_events", "partner_clients", "partner_credentials",
                "partner_installations", "partner_installation_locations", "partner_resource_scopes",
                "partner_resource_items", "partner_grants", "partner_authorization_requests", "partner_subjects",
                "partner_codes", "partner_token_families", "partner_tokens", "partner_docs_sessions"}
            for schema, name in tables:
                relation = '"' + schema.replace('"', '""') + '"."' + name.replace('"', '""') + '"'
                rows = (await conn.execute(text("SELECT to_jsonb(t)::text FROM " + relation + " t"))).scalars().all()
                assert len(rows) <= 10000 and sum(len(r) for r in rows) <= 8 * 1024 * 1024
                value = [len(rows), hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()]
                (auth if name in auth_names else business)[schema + "." + name] = value
            assert await conn.scalar(text("SELECT pg_database_size(current_database())")) < 256 * 1024 * 1024
    files = {str(p.relative_to(os.environ["UPLOAD_DIR"])): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(Path(os.environ["UPLOAD_DIR"]).rglob("*")) if p.is_file()}
    return dict(business=business, auth=auth, files=files)


@pytest_asyncio.fixture(loop_scope="session")
async def env(db, password_hash, request, monkeypatch):
    boundary = request.config._contract_objects_boundary
    suffix = uuid.uuid4().hex[:10]
    companies = [Company(name=f"R1 synthetic {i}", slug=f"r1-{suffix}-{i}", profile_id="energy") for i in range(2)]
    db.add_all(companies)
    await db.flush()
    ca, cb = companies
    orgs = [Organization(company_id=ca.id, name=f"R1 own {i}", inn=str(9900000000 + i)) for i in range(2)]
    foreign_org = Organization(company_id=cb.id, name="R1 foreign own", inn="9900000002")
    party = Counterparty(company_id=ca.id, name="R1 synthetic counterparty")
    foreign_party = Counterparty(company_id=cb.id, name="R1 foreign counterparty")
    users = [User(company_id=ca.id, name="R1 " + name, email=f"{suffix}-{name}@example.com",
                  password_hash=password_hash, role="user", is_superadmin=False, mail_only=False)
             for name in ("admin", "employee")]
    foreign_user = User(company_id=cb.id, name="R1 foreign admin", email=f"{suffix}-foreign@example.com",
                        password_hash=password_hash, role="user", is_superadmin=False, mail_only=False)
    db.add_all([*orgs, foreign_org, party, foreign_party, *users, foreign_user])
    await db.flush()
    at = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    points = [ServiceLocation(id=(f"r1-{suffix}-{i}" if i != 2 else f" Точка Ё {suffix} "),
        company_id=ca.id, code=f"R1-{i}", name=f"Synthetic R1 point {i}", type="ev_charging",
        created_at=at, extra_metadata={"private": "R1-NEVER-EXPOSE"}) for i in range(4)]
    alien = ServiceLocation(id=f"r1-foreign-{suffix}", company_id=cb.id, code="R1-ALIEN", name="Synthetic alien", created_at=at)
    db.add_all([*points, alien])
    await db.flush()
    members = [UserCompany(user_id=users[0].id, company_id=ca.id, role="admin"),
               UserCompany(user_id=users[1].id, company_id=ca.id, role="user", modules=["equipment", "references"],
                           object_scope=[points[0].id])]
    foreign_member = UserCompany(user_id=foreign_user.id, company_id=cb.id, role="admin")
    contracts = [Contract(company_id=ca.id, number=f"R1-{i}", date="2026-10-01", type="service",
        counterparty_id=party.id, organization_id=orgs[1 if i == 1 else 0].id,
        scope_type="company" if i == 2 else "unassigned" if i == 3 else "locations") for i in range(5)]
    foreign_contract = Contract(company_id=cb.id, number="R1-FOREIGN", date="2026-10-01", type="service",
        counterparty_id=foreign_party.id, organization_id=foreign_org.id, scope_type="locations")
    db.add_all([*members, foreign_member, *contracts, foreign_contract])
    await db.flush()
    db.add_all([ContractLocation(company_id=ca.id, contract_id=contracts[0].id, location_id=p.id) for p in points[:3]])
    db.add_all([ContractLocation(company_id=ca.id, contract_id=contracts[1].id, location_id=points[1].id),
                ContractLocation(company_id=ca.id, contract_id=contracts[2].id, location_id=points[0].id),
                ContractLocation(company_id=cb.id, contract_id=foreign_contract.id, location_id=alien.id)])
    await db.commit()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_exception_handler(identity.PartnerProblem, identity.problem_handler)
    for router in (auth_router.router, partner_admin_router.router, partner_oauth_router.router,
                   partner_oauth_router.consent_router, references_router.router):
        app.include_router(router, prefix="/api")
    # Real dependency, transaction and token verification; only the app assembly is bounded.
    product = create_product_api(session_factory=database.async_session_factory, issuer=ORIGIN,
                                 source_revision="next-r1-synthetic", cursor_key=b"r1-fixed-synthetic-cursor-key-32bytes")
    app.mount("/api/v1", product)
    boundary.fixture_count += 1
    peer = (f"198.18.{boundary.fixture_count // 250}.{boundary.fixture_count % 250 + 1}", 12000 + boundary.fixture_count)
    detailed = []
    original_detail = Query.detail
    async def counted_detail(query, resource, identifier):
        detailed.append(resource)
        return await original_detail(query, resource, identifier)
    monkeypatch.setattr(Query, "detail", counted_detail)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False, client=peer), base_url=ORIGIN) as ac:
        core = []
        for user in users:
            response = await ac.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
            assert response.status_code == 200, response.text
            core.append({"Authorization": "Bearer " + response.json()["access_token"]})
        response = await ac.post("/api/auth/login", json={"email": foreign_user.email, "password": PASSWORD})
        assert response.status_code == 200, response.text
        foreign_core = {"Authorization": "Bearer " + response.json()["access_token"]}
        yield SimpleNamespace(**locals())
    assert boundary.active and "app.main" not in __import__("sys").modules


async def issue(env, *, machine=False, employee=False, foreign=False, scopes=None, resources=None, locations=None):
    scopes = list(SCOPES if scopes is None else scopes) + ([] if machine else ["openid"])
    ac, core = env.ac, env.foreign_core if foreign else env.core[0]
    company_id = env.cb.id if foreign else env.ca.id
    response = await ac.post("/api/developer/clients", headers=core, json={"companyId": str(company_id),
        "name": "R1 synthetic application", "redirectUris": [REDIRECT], "scopes": scopes,
        "authMethod": "client_secret_basic" if machine else "none"})
    assert response.status_code == 201, response.text
    client_id = response.json()["clientId"]
    assert (await ac.post(f"/api/developer/clients/{client_id}/status", headers=core, json={"enabled": True})).status_code == 200
    secret = credential_id = None
    if machine:
        response = await ac.post(f"/api/developer/clients/{client_id}/credentials", headers=core)
        assert response.status_code == 201, response.text
        secret, credential_id = response.json()["clientSecret"], response.json()["credentialId"]
    response = await ac.post(f"/api/developer/clients/{client_id}/installations", headers=core, json={
        "companyId": str(company_id), "scopes": scopes, "locationIds": locations,
        "resourceScopes": resources if resources is not None else {
            "objects": {"mode": "ALL", "ids": []}, "contracts": {"mode": "ALL", "ids": []}}})
    assert response.status_code == 201, response.text
    installation_id = response.json()["installationId"]
    if machine:
        response = await ac.post(f"/api/developer/installations/{installation_id}/machine-grants", headers=core,
                                 json={"scopes": scopes})
        assert response.status_code == 201, response.text
        grant_id = response.json()["grantId"]
        response = await ac.post("/api/oauth2/token", auth=(client_id, secret), data={
            "grant_type": "client_credentials", "grant_id": grant_id, "scope": " ".join(scopes)})
    else:
        state = uuid.uuid4().hex
        response = await ac.get("/api/oauth2/authorize", params={"response_type": "code", "client_id": client_id,
            "redirect_uri": REDIRECT, "scope": " ".join(scopes), "state": state, "nonce": "r1-" + state,
            "code_challenge": CHALLENGE, "code_challenge_method": "S256"})
        assert response.status_code == 302, response.text
        rid = parse_qs(urlsplit(response.headers["location"]).query)["requestId"][0]
        response = await ac.post(f"/api/developer/authorization-requests/{rid}/approve",
            headers=env.foreign_core if foreign else env.core[1 if employee else 0], json={"companyId": str(company_id), "scopes": scopes})
        assert response.status_code == 200, response.text
        code = parse_qs(urlsplit(response.json()["redirectUrl"]).query)["code"][0]
        response = await ac.post("/api/oauth2/token", data={"grant_type": "authorization_code",
            "client_id": client_id, "redirect_uri": REDIRECT, "code": code, "code_verifier": VERIFIER})
        grant_id = str((await env.db.scalar(select(PartnerGrant).where(PartnerGrant.client_id == client_id))).id)
    assert response.status_code == 200, response.text
    return SimpleNamespace(headers={"Authorization": "Bearer " + response.json()["access_token"]},
        tokens=response.json(), client_id=client_id, installation_id=installation_id, grant_id=grant_id,
        credential_id=credential_id, machine=machine)


async def read(env, auth, parent=0, *, params=None, content=None, headers=None):
    identifier = str(env.contracts[parent].id) if isinstance(parent, int) else str(parent)
    observed = []
    def capture(conn, cursor, statement, *args):
        observed.append(statement.lstrip().upper())
        assert len(observed) <= 100, "bounded product GET SQL count exceeded"
    event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await env.ac.request("GET", f"/api/v1/contracts/{identifier}/objects", params=params,
                                       content=content, headers=auth.headers if headers is None else headers)
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", capture)
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP")) for s in observed)
    assert response.headers["content-type"].startswith("application/json" if response.status_code == 200 else "application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    assert "R1-NEVER-EXPOSE" not in response.text
    if response.status_code != 200:
        assert response.json()["requestId"] == response.headers["x-request-id"]
    return response


def assert_page(response, contract, points):
    assert response.status_code == 200, response.text
    value = response.json()
    assert set(value) == {"contractId", "scopeType", "items", "total", "nextCursor"}
    assert value["contractId"] == str(contract.id) and value["scopeType"] == contract.scope_type
    assert value["total"] == len(points) and value["nextCursor"] is None
    assert {item["objectId"] for item in value["items"]} == {point.id for point in points}
    assert all(set(item) == {"objectId"} for item in value["items"])


async def test_real_user_and_machine_goldens_and_persisted_read_immutability(env, record_property):
    user, machine = await issue(env), await issue(env, machine=True)
    sentinel = Path(os.environ["UPLOAD_DIR"]) / "r1-synthetic-sentinel.bin"
    sentinel.write_bytes(b"R1 immutable synthetic bytes\x00\xff")
    before = await snapshot()
    for auth in (user, machine):
        for _ in range(2):
            assert_page(await read(env, auth), env.contracts[0], env.points[:3])
    after = await snapshot()
    assert before == after  # Includes separately inventoried auth tables; quota OFF here.
    record_property("persisted_before", json.dumps(before, sort_keys=True))
    record_property("persisted_after", json.dumps(after, sort_keys=True))


async def test_identity_and_quota_ownership_remains_one_call(env, monkeypatch):
    from app.product_api import budget
    auth = await issue(env)
    counts = {"verify": 0, "quota": 0}
    verify, enforce = identity.verify_partner_access_token, budget.enforce
    async def real_verify(*args, **kwargs):
        counts["verify"] += 1
        return await verify(*args, **kwargs)
    async def real_enforce(*args, **kwargs):
        counts["quota"] += 1
        return await enforce(*args, **kwargs)
    monkeypatch.setattr(identity, "verify_partner_access_token", real_verify)
    monkeypatch.setattr(budget, "enforce", real_enforce)
    assert_page(await read(env, auth), env.contracts[0], env.points[:3])
    assert counts == {"verify": 1, "quota": 1}


@pytest.mark.parametrize("resource,mode", [(r, m) for r in ("contracts", "objects") for m in ("ALL", "SET", "EMPTY", "MISSING")])
@pytest.mark.parametrize("machine", [False, True])
async def test_each_resource_grant_is_independent_before_detail(env, resource, mode, machine):
    resources = {r: {"mode": "ALL", "ids": []} for r in ("contracts", "objects")}
    if mode == "MISSING":
        del resources[resource]
    else:
        resources[resource] = {"mode": mode, "ids": [str(env.contracts[0].id) if resource == "contracts" else env.points[1].id] if mode == "SET" else []}
    auth = await issue(env, resources=resources, machine=machine)
    env.detailed.clear()
    response = await read(env, auth)
    if mode in ("EMPTY", "MISSING"):
        assert response.status_code == 403, response.text
        assert not env.detailed
    else:
        assert_page(response, env.contracts[0], [env.points[1]] if resource == "objects" and mode == "SET" else env.points[:3])


@pytest.mark.parametrize("missing", SCOPES)
@pytest.mark.parametrize("machine", [False, True])
async def test_each_oauth_scope_is_required_before_detail(env, missing, machine):
    auth = await issue(env, scopes=[s for s in SCOPES if s != missing], machine=machine)
    env.detailed.clear()
    assert (await read(env, auth)).status_code == 403
    assert not env.detailed


@pytest.mark.parametrize("parent", ["missing", "malformed", "foreign", "ungranted"])
async def test_parent_denials_are_same_404(env, parent):
    auth = await issue(env, resources={"objects": {"mode": "ALL", "ids": []},
        "contracts": {"mode": "SET", "ids": [str(env.contracts[0].id)]}})
    identifier = uuid.uuid4() if parent == "missing" else "not-a-uuid" if parent == "malformed" else env.foreign_contract.id if parent == "foreign" else env.contracts[1].id
    response = await read(env, auth, identifier)
    assert response.status_code == 404 and response.json()["code"] == "not_found"


async def test_employee_one_object_and_admin_narrow_set(env):
    employee = await issue(env, employee=True)
    assert_page(await read(env, employee), env.contracts[0], env.points[:1])
    narrow = await issue(env, resources={"contracts": {"mode": "SET", "ids": [str(env.contracts[0].id)]},
        "objects": {"mode": "SET", "ids": [env.points[1].id]}})
    assert_page(await read(env, narrow), env.contracts[0], env.points[1:2])
    assert (await read(env, narrow, 1)).status_code == 404


async def test_current_own_organization_and_hidden_parent(env):
    env.members[1].own_organization_id = env.orgs[0].id
    env.members[1].object_scope = None
    await env.db.commit()
    auth = await issue(env, employee=True)
    assert_page(await read(env, auth), env.contracts[0], env.points[:3])
    assert (await read(env, auth, 1)).status_code == 404
    env.members[1].own_organization_id = env.orgs[1].id
    await env.db.commit()
    assert (await read(env, auth)).status_code == 404
    assert_page(await read(env, auth, 1), env.contracts[1], env.points[1:2])


async def test_other_tenant_can_read_only_its_parent_and_cursor_is_not_transferable(env):
    local, foreign = await issue(env), await issue(env, foreign=True)
    first = await read(env, local, params={"pageSize": 1})
    assert first.status_code == 200 and first.json()["nextCursor"]
    assert (await read(env, foreign)).status_code == 404
    assert_page(await read(env, foreign, env.foreign_contract.id), env.foreign_contract, [env.alien])
    denied = await read(env, foreign, env.foreign_contract.id, params={"pageSize": 1, "cursor": first.json()["nextCursor"]})
    assert denied.status_code == 400


async def test_foreign_own_organization_context_is_denied_before_detail(env):
    auth = await issue(env, employee=True)
    env.members[1].own_organization_id = env.foreign_org.id
    await env.db.commit()
    env.detailed.clear()
    assert (await read(env, auth)).status_code == 403
    assert not env.detailed


async def test_invalid_cross_company_relation_is_not_a_visible_id_or_count(env):
    # Real FKs individually allow these deliberately inconsistent tenant relations.
    env.db.add_all([ContractLocation(company_id=env.cb.id, contract_id=env.contracts[0].id, location_id=env.points[3].id),
                    ContractLocation(company_id=env.ca.id, contract_id=env.contracts[0].id, location_id=env.alien.id)])
    await env.db.commit()
    auth = await issue(env)
    assert_page(await read(env, auth), env.contracts[0], env.points[:3])


@pytest.mark.parametrize("scope", ["company", "unassigned", "empty_locations", "hidden_objects"])
async def test_no_implicit_company_coverage_or_hidden_counts(env, scope):
    parent = {"company": 2, "unassigned": 3, "empty_locations": 4, "hidden_objects": 0}[scope]
    resources = {"contracts": {"mode": "ALL", "ids": []}, "objects": {"mode": "SET", "ids": [env.points[3].id]}} if scope == "hidden_objects" else None
    auth = await issue(env, resources=resources)
    assert_page(await read(env, auth, parent), env.contracts[parent], [])


async def test_stable_equal_timestamp_pages_and_opaque_object_id(env):
    auth = await issue(env)
    params, seen = {"pageSize": 1}, []
    for _ in range(3):
        response = await read(env, auth, params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 3 and len(page["items"]) == 1
        seen.extend(i["objectId"] for i in page["items"])
        params["cursor"] = page["nextCursor"]
    assert params["cursor"] is None and len(set(seen)) == 3
    assert set(seen) == {p.id for p in env.points[:3]}
    assert env.points[2].id.startswith(" ") and env.points[2].id.endswith(" ")


@pytest.mark.parametrize("change", ["parent", "pageSize", "objects", "contracts", "member", "installation", "own_org"])
async def test_cursor_binding_rejects_changed_parent_or_ceilings(env, change):
    auth = await issue(env)
    first = await read(env, auth, params={"pageSize": 1})
    assert first.status_code == 200 and first.json()["nextCursor"]
    params = {"pageSize": 1, "cursor": first.json()["nextCursor"]}
    parent = 1 if change == "parent" else 0
    if change == "pageSize":
        params["pageSize"] = 2
    elif change in ("objects", "contracts"):
        # ALL→EMPTY is an authorization denial, tested separately; same valid content
        # with a narrower SET is reapproved through the actual administrative path.
        response = await env.ac.post(f"/api/developer/clients/{auth.client_id}/installations", headers=env.core[0], json={
            "companyId": str(env.ca.id), "scopes": ["openid", *SCOPES], "locationIds": None,
            "resourceScopes": {"objects": {"mode": "SET", "ids": [p.id for p in env.points[:2]]} if change == "objects" else {"mode": "ALL", "ids": []},
                "contracts": {"mode": "SET", "ids": [str(env.contracts[0].id)]} if change == "contracts" else {"mode": "ALL", "ids": []}}})
        assert response.status_code == 201, response.text
    elif change == "member":
        env.members[0].object_scope = [p.id for p in env.points[:2]]
        await env.db.commit()
    elif change == "installation":
        install = await env.db.get(PartnerInstallation, uuid.UUID(auth.installation_id))
        install.all_locations = False
        from app.models_partner import PartnerInstallationLocation
        env.db.add_all([PartnerInstallationLocation(installation_id=install.id, location_id=p.id) for p in env.points[:2]])
        await env.db.commit()
    elif change == "own_org":
        env.members[0].own_organization_id = env.orgs[0].id
        await env.db.commit()
    response = await read(env, auth, parent, params=params)
    assert response.status_code == 400 and response.json()["code"] == "invalid_cursor", response.text


@pytest.mark.parametrize("target", ["membership", "installation", "grant", "client", "credential", "role"])
async def test_live_revoke_denies_next_read(env, target):
    auth = await issue(env, machine=target == "credential", employee=target == "role")
    assert (await read(env, auth)).status_code == 200
    if target == "membership":
        await env.db.delete(env.members[0])
    elif target == "installation":
        (await env.db.get(PartnerInstallation, uuid.UUID(auth.installation_id))).approved = False
    elif target == "grant":
        (await env.db.get(PartnerGrant, uuid.UUID(auth.grant_id))).approved = False
    elif target == "client":
        (await env.db.get(PartnerClient, auth.client_id)).enabled = False
    elif target == "credential":
        (await env.db.get(PartnerCredential, uuid.UUID(auth.credential_id))).enabled = False
    else:
        role = CompanyRole(company_id=env.ca.id, name="R1 revoked role", modules=["equipment"])
        env.db.add(role)
        await env.db.flush()
        env.members[1].role_id = role.id
    await env.db.commit()
    env.detailed.clear()
    assert (await read(env, auth)).status_code == 401
    assert not env.detailed


@pytest.mark.parametrize("params", [{"q": "x"}, {"dateFrom": "2026-01-01"}, {"companyId": "foreign"},
    {"objectId": "hidden"}, {"pageSize": 0}, {"pageSize": 201}, {"cursor": ""}, {"cursor": "x" * 4097}])
async def test_unknown_queries_and_bounded_inputs(env, params):
    auth = await issue(env)
    env.detailed.clear()
    assert (await read(env, auth, params=params)).status_code == 422
    assert not env.detailed


@pytest.mark.parametrize("content", [b"{}", b"null", b"x"])
async def test_body_is_rejected_before_detail(env, content):
    auth = await issue(env)
    env.detailed.clear()
    assert (await read(env, auth, content=content)).status_code == 422
    assert not env.detailed


@pytest.mark.parametrize("kind", ["none", "core", "id_token", "docs_cookie"])
async def test_wrong_token_classes_never_reach_detail(env, kind):
    auth = await issue(env)
    headers = {} if kind in ("none", "docs_cookie") else env.core[0] if kind == "core" else {
        "Authorization": "Bearer " + auth.tokens["id_token"]}
    if kind == "docs_cookie":
        headers = {"Cookie": "elsy_docs=synthetic-only-not-a-business-credential"}
    env.detailed.clear()
    assert (await read(env, auth, headers=headers)).status_code == 401
    assert not env.detailed


async def test_disabled_feature_precedes_verifier_and_detail(env, monkeypatch):
    monkeypatch.setattr(identity.settings, "partner_api_enabled", False)
    env.detailed.clear()
    response = await read(env, SimpleNamespace(headers={"Authorization": "Bearer invalid"}))
    assert response.status_code == 503 and not env.detailed


async def test_cursor_null_string_is_invalid_not_clear_intent(env):
    auth = await issue(env)
    assert (await read(env, auth, params={"cursor": "null"})).status_code == 400


async def test_empty_current_employee_ceiling_hides_parent(env):
    auth = await issue(env, employee=True)
    assert (await read(env, auth)).status_code == 200
    env.members[1].object_scope = []
    await env.db.commit()
    assert (await read(env, auth)).status_code == 404


async def test_native_contract_locations_is_unchanged_and_partner_not_native(env):
    auth = await issue(env)
    path = f"/api/references/contracts/{env.contracts[0].id}/locations"
    result = await env.ac.get(path, headers=env.core[0])
    assert result.status_code == 200, result.text
    assert {i["id"] for i in result.json()} == {p.id for p in env.points[:3]}
    assert all(set(i) == {"id", "code", "name", "type"} for i in result.json())
    assert (await env.ac.get(path, headers=auth.headers)).status_code == 401


async def test_canonical_and_browser_profiles_and_old_object_id_refs(env):
    schema = curated_openapi(env.product)
    registry = export_runtime_registry(env.product)
    assert len(registry["operations"]) == 14
    operation = schema["paths"]["/contracts/{contractId}/objects"]["get"]
    assert operation["operationId"] == "listContractObjects"
    assert operation["security"] == [{"ProductOAuth": SCOPES}, {"ProductServiceOAuth": SCOPES}]
    assert {p["name"] for p in operation["parameters"]} == {"contractId", "pageSize", "cursor"}
    assert "requestBody" not in operation
    browser = public_client_openapi(schema)
    assert browser["paths"]["/contracts/{contractId}/objects"]["get"]["security"] == [{"ProductOAuth": SCOPES}]
    assert set(browser["components"]["securitySchemes"]) == {"ProductOAuth"}
    for path in ("/objects/{objectId}", "/objects/{objectId}/monitoring"):
        parameter = next(p for p in schema["paths"][path]["get"]["parameters"] if p["name"] == "objectId")
        assert parameter["schema"] == {"$ref": "#/components/schemas/ObjectId"}
