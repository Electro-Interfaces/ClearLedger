"""Opt-in M06-R3 real OAuth/HTTP/PostgreSQL acceptance on one fresh exact DB.

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

FLAG = "RUN_PRODUCT_CONTRACT_CLASSIFICATION_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip("ROOT opt-in M06-R3 runner required", allow_module_level=True)
from tests.partner_test_safety import partner_test_safety_error
if partner_test_safety_error(os.environ, flag=FLAG):
    raise pytest.UsageError("M06-R3 pre-import target guard refused")
_target = urlsplit(os.environ["TEST_DATABASE_URL"])
if (_target.hostname != "127.0.0.1" or _target.port != 33546
        or _target.path != "/api_contract_classification_test_20261031"
        or os.environ.get("ROOT_APPROVED_PRODUCT_CONTRACT_CLASSIFICATION") != "1"):
    raise pytest.UsageError("Use immutable M06-R3 ROOT runner and exact fresh database")

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
ORIGIN = "https://contract-classification.example.invalid"
REDIRECT = "https://contract-classification-client.example.invalid/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
SCOPES = ["contracts:read"]
PASSWORD = "Contract-Objects-Synthetic-2026!"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def contract_classification_database(request):
    assert request.config._contract_classification_boundary.active
    async with database.engine.begin() as conn:
        assert await conn.scalar(text("SELECT current_database()")) == "api_contract_classification_test_20261031"
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
async def db(contract_classification_database):
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
    boundary = request.config._contract_classification_boundary
    suffix = uuid.uuid4().hex[:10]
    companies = [Company(name=f"R3 synthetic {i}", slug=f"r3-{suffix}-{i}", profile_id="energy") for i in range(2)]
    db.add_all(companies)
    await db.flush()
    ca, cb = companies
    orgs = [Organization(company_id=ca.id, name=f"R3 own {i}", inn=str(9900000000 + i)) for i in range(2)]
    foreign_org = Organization(company_id=cb.id, name="R3 foreign own", inn="9900000002")
    party = Counterparty(company_id=ca.id, name="R3 synthetic counterparty")
    foreign_party = Counterparty(company_id=cb.id, name="R3 foreign counterparty")
    users = [User(company_id=ca.id, name="R3 " + name, email=f"{suffix}-{name}@example.com",
                  password_hash=password_hash, role="user", is_superadmin=False, mail_only=False)
             for name in ("admin", "employee")]
    foreign_user = User(company_id=cb.id, name="R3 foreign admin", email=f"{suffix}-foreign@example.com",
                        password_hash=password_hash, role="user", is_superadmin=False, mail_only=False)
    db.add_all([*orgs, foreign_org, party, foreign_party, *users, foreign_user])
    await db.flush()
    at = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    points = [ServiceLocation(id=(f"r3-{suffix}-{i}" if i != 2 else f" Точка Ё {suffix} "),
        company_id=ca.id, code=f"R3-{i}", name=f"Synthetic R3 point {i}", type="ev_charging",
        created_at=at, extra_metadata={"private": "R3-NEVER-EXPOSE"}) for i in range(4)]
    alien = ServiceLocation(id=f"r3-foreign-{suffix}", company_id=cb.id, code="R3-ALIEN", name="Synthetic alien", created_at=at)
    db.add_all([*points, alien])
    await db.flush()
    members = [UserCompany(user_id=users[0].id, company_id=ca.id, role="admin"),
               UserCompany(user_id=users[1].id, company_id=ca.id, role="user", modules=["equipment", "references"],
                           object_scope=[points[0].id])]
    foreign_member = UserCompany(user_id=foreign_user.id, company_id=cb.id, role="admin")
    custom_code = " Custom Ё /Energy:01 "
    # These are source values, not legal classifications inferred from their text.
    codes = ["rent", "energy_supply", custom_code, None, "unknown-retired", "rent",
             "hidden-only", "rent", "", "retired", "null"]
    expiries = ["2030-12-31", None, "31.12.2030", "", "2026-02-30", "2026-01-01T00:00:00",
                None, None, None, None, None]
    contracts = [Contract(company_id=ca.id, number=f"R3-{i}", date="2026-10-01", type="СПоставщиком",
        title="Аренда и энергоснабжение", kind="supplier", basis="разрешение",
        type_code=code, valid_until=expiries[i], raw={"TypeCode": "rent", "secret": "R3-NEVER-EXPOSE"},
        counterparty_id=party.id, organization_id=orgs[1 if i in (1, 6) else 0].id,
        scope_type="locations", created_at=at if i != 7 else datetime(2026, 10, 2, 12, tzinfo=timezone.utc))
        for i, code in enumerate(codes)]
    foreign_contract = Contract(company_id=cb.id, number="R3-FOREIGN", date="2026-10-01", type="service",
        type_code="foreign-only", valid_until="2040-01-01", created_at=at,
        counterparty_id=foreign_party.id, organization_id=foreign_org.id, scope_type="locations")
    db.add_all([*members, foreign_member, *contracts, foreign_contract])
    await db.flush()
    db.add_all([ContractLocation(company_id=ca.id, contract_id=c.id,
                                location_id=points[1 if i in (1, 6, 7) else 0].id)
                for i, c in enumerate(contracts)])
    db.add(ContractLocation(company_id=cb.id, contract_id=foreign_contract.id, location_id=alien.id))
    # Synthetic catalog setup is separate from product GETs; schema is unchanged.
    for code, label, active in [("rent", "Synthetic rent", True), ("energy_supply", "Synthetic energy", True),
                                (custom_code, "Synthetic custom", True), ("retired", "Synthetic old label", False),
                                ("hidden-only", "Synthetic hidden label", True), ("foreign-only", "Synthetic foreign label", True),
                                ("global-only", "Synthetic unused global label", True)]:
        await db.execute(text("INSERT INTO contract_types(code,label,gk_basis,direction,is_active) "
            "VALUES (:code,:label,:basis,:direction,:active) ON CONFLICT(code) DO UPDATE "
            "SET label=EXCLUDED.label,gk_basis=EXCLUDED.gk_basis,direction=EXCLUDED.direction,is_active=EXCLUDED.is_active"),
            {"code": code, "label": label, "basis": "Synthetic basis", "direction": "any", "active": active})
    await db.commit()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_exception_handler(identity.PartnerProblem, identity.problem_handler)
    for router in (auth_router.router, partner_admin_router.router, partner_oauth_router.router,
                   partner_oauth_router.consent_router, references_router.router):
        app.include_router(router, prefix="/api")
    # Real dependency, transaction and token verification; only the app assembly is bounded.
    product = create_product_api(session_factory=database.async_session_factory, issuer=ORIGIN,
                                 source_revision="next-r3-synthetic", cursor_key=b"r3-fixed-synthetic-cursor-key-32bytes")
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
        "name": "R3 synthetic application", "redirectUris": [REDIRECT], "scopes": scopes,
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
            "redirect_uri": REDIRECT, "scope": " ".join(scopes), "state": state, "nonce": "r3-" + state,
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


async def read(env, auth, path="/api/v1/contracts", *, params=None, content=None, headers=None):
    observed = []
    def capture(conn, cursor, statement, *args):
        observed.append(statement.lstrip().upper())
        assert len(observed) <= 100, "bounded product GET SQL count exceeded"
    event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await env.ac.request("GET", path, params=params, content=content,
                                       headers=auth.headers if headers is None else headers)
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", capture)
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP")) for s in observed)
    assert response.headers["content-type"].startswith("application/json" if response.status_code == 200 else "application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    assert "R3-NEVER-EXPOSE" not in response.text
    if response.status_code != 200:
        assert response.json()["requestId"] == response.headers["x-request-id"]
    response.extensions["r3_sql"] = observed
    return response


def assert_items(response, expected):
    assert response.status_code == 200, response.text
    value = response.json()
    assert set(value) == {"items", "total", "nextCursor"}
    assert value["total"] == len(expected) and value["nextCursor"] is None
    assert {d["id"] for d in value["items"]} == {str(c.id) for c in expected}
    return value["items"]


async def metadata(env, auth, code, **kwargs):
    return await read(env, auth, "/api/v1/contract-types", params={"typeCode": code}, **kwargs)


@pytest.mark.parametrize("machine", [False, True])
async def test_source_valued_required_fields_in_list_and_detail(env, machine):
    auth = await issue(env, machine=machine)
    items = assert_items(await read(env, auth), env.contracts)
    indexed = {d["id"]: d for d in items}
    expected = [("rent", "2030-12-31"), ("energy_supply", None), (" Custom Ё /Energy:01 ", "31.12.2030"),
                (None, ""), ("unknown-retired", "2026-02-30"), ("rent", "2026-01-01T00:00:00"),
                ("hidden-only", None), ("rent", None), ("", None), ("retired", None), ("null", None)]
    for index, (code, expiry) in enumerate(expected):
        row = indexed[str(env.contracts[index].id)]
        assert set(row) == {"id", "number", "date", "title", "isClosed", "scopeType", "counterpartyId", "typeCode", "validUntil"}
        assert row["typeCode"] == code and row["validUntil"] == expiry
        assert row["counterpartyId"] is None
        detail = await read(env, auth, f"/api/v1/contracts/{env.contracts[index].id}")
        assert detail.status_code == 200 and detail.json() == row
    assert indexed[str(env.contracts[3].id)]["typeCode"] is None  # Title/type/raw never infer a classifier.


@pytest.mark.parametrize("machine", [False, True])
@pytest.mark.parametrize("code,indexes", [("rent", [0, 5, 7]), ("energy_supply", [1]),
    (" Custom Ё /Energy:01 ", [2]), ("unknown-retired", [4]), ("retired", [9]), ("null", [10]),
    ("RENT", []), ("Custom Ё /Energy:01", []), ("global-only", []), ("%_", [])])
async def test_type_filter_is_exact_source_equality_before_count(env, machine, code, indexes):
    auth = await issue(env, machine=machine)
    assert_items(await read(env, auth, params={"typeCode": code}), [env.contracts[i] for i in indexes])


@pytest.mark.parametrize("machine", [False, True])
async def test_filter_composes_with_existing_q_and_created_date_window(env, machine):
    auth = await issue(env, machine=machine)
    assert_items(await read(env, auth, params={"typeCode": "rent", "q": "R3", "dateFrom": "2026-10-02", "dateTo": "2026-10-02"}), [env.contracts[7]])
    assert_items(await read(env, auth, params={"typeCode": "rent", "q": "R3-1"}), [])
    assert_items(await read(env, auth, params={"q": "R3-1"}), [env.contracts[1], env.contracts[10]])


@pytest.mark.parametrize("machine", [False, True])
@pytest.mark.parametrize("code,label,active", [("rent", "Synthetic rent", True),
    (" Custom Ё /Energy:01 ", "Synthetic custom", True), ("retired", "Synthetic old label", False),
    ("unknown-retired", None, None), ("null", None, None)])
async def test_scoped_metadata_literal_goldens_keep_unknown_and_inactive(env, machine, code, label, active):
    auth = await issue(env, machine=machine)
    response = await metadata(env, auth, code)
    assert response.status_code == 200, response.text
    assert response.json() == {"typeCode": code, "label": label,
        "gkBasis": "Synthetic basis" if label else None, "direction": "any" if label else None, "isActive": active}
    assert any("FROM CONTRACT_TYPES" in sql for sql in response.extensions["r3_sql"])


@pytest.mark.parametrize("hidden", ["global_only", "foreign_only", "missing", "typed_set", "own_org", "object", "installation"])
async def test_no_catalog_lookup_without_independently_visible_contract(env, hidden):
    resources = {"contracts": {"mode": "SET", "ids": [str(env.contracts[0].id)]}} if hidden == "typed_set" else None
    locations = [env.points[0].id] if hidden == "installation" else None
    auth = await issue(env, employee=hidden == "object", resources=resources, locations=locations)
    if hidden == "own_org":
        env.members[0].own_organization_id = env.orgs[0].id
        await env.db.commit()
    code = {"global_only": "global-only", "foreign_only": "foreign-only", "missing": "never-stored",
            "typed_set": "energy_supply", "own_org": "hidden-only", "object": "hidden-only", "installation": "hidden-only"}[hidden]
    response = await metadata(env, auth, code)
    assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert not any("FROM CONTRACT_TYPES" in sql for sql in response.extensions["r3_sql"])


@pytest.mark.parametrize("machine", [False, True])
@pytest.mark.parametrize("mode", ["ALL", "SET", "EMPTY", "MISSING"])
async def test_current_typed_contract_grant_is_required_for_filter_and_metadata(env, machine, mode):
    resources = {} if mode == "MISSING" else {"contracts": {"mode": mode,
        "ids": [str(env.contracts[0].id)] if mode == "SET" else []}}
    auth = await issue(env, machine=machine, resources=resources)
    result = await read(env, auth, params={"typeCode": "rent"})
    label = await metadata(env, auth, "rent")
    if mode in ("EMPTY", "MISSING"):
        assert result.status_code == label.status_code == 403
        assert not any("FROM CONTRACT_TYPES" in sql for sql in label.extensions["r3_sql"])
    else:
        assert_items(result, [env.contracts[0]] if mode == "SET" else [env.contracts[i] for i in (0, 5, 7)])
        assert label.status_code == 200
        if mode == "SET":
            assert (await metadata(env, auth, "energy_supply")).status_code == 404


@pytest.mark.parametrize("machine", [False, True])
async def test_missing_contract_oauth_scope_is_not_replaced_by_other_resource(env, machine):
    auth = await issue(env, machine=machine, scopes=["objects:read"])
    assert (await read(env, auth, params={"typeCode": "rent"})).status_code == 403
    assert (await metadata(env, auth, "rent")).status_code == 403


@pytest.mark.parametrize("machine", [False, True])
async def test_installation_object_ceiling_filters_company_scope_before_totals(env, machine):
    auth = await issue(env, machine=machine, locations=[env.points[0].id])
    assert_items(await read(env, auth, params={"typeCode": "rent"}), [env.contracts[0], env.contracts[5]])
    assert (await metadata(env, auth, "hidden-only")).status_code == 404


async def test_own_organization_and_user_object_ceiling_remain_current(env):
    auth = await issue(env, employee=True)
    assert_items(await read(env, auth, params={"typeCode": "rent"}), [env.contracts[0], env.contracts[5]])
    env.members[1].object_scope = None
    env.members[1].own_organization_id = env.orgs[1].id
    await env.db.commit()
    assert_items(await read(env, auth), [env.contracts[1], env.contracts[6]])
    assert (await metadata(env, auth, "rent")).status_code == 404
    assert (await metadata(env, auth, "hidden-only")).status_code == 200
    env.members[1].own_organization_id = env.foreign_org.id
    await env.db.commit()
    assert (await read(env, auth)).status_code == 403
    assert (await metadata(env, auth, "hidden-only")).status_code == 403


async def test_two_company_metadata_and_contracts_are_independent(env):
    local, foreign = await issue(env), await issue(env, foreign=True)
    assert (await metadata(env, local, "foreign-only")).status_code == 404
    assert (await metadata(env, foreign, "rent")).status_code == 404
    assert_items(await read(env, foreign, params={"typeCode": "foreign-only"}), [env.foreign_contract])
    response = await metadata(env, foreign, "foreign-only")
    assert response.status_code == 200 and response.json()["label"] == "Synthetic foreign label"
    assert (await read(env, foreign, f"/api/v1/contracts/{env.contracts[0].id}")).status_code == 404


async def test_equal_timestamp_filtered_cursor_pages_have_no_loss_or_hidden_counts(env):
    auth = await issue(env)
    seen, params = [], {"pageSize": 1, "typeCode": "rent"}
    for _ in range(3):
        response = await read(env, auth, params=params)
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["total"] == 3 and len(value["items"]) == 1
        seen.append(value["items"][0]["id"])
        params["cursor"] = value["nextCursor"]
    assert params["cursor"] is None and len(set(seen)) == 3
    assert set(seen) == {str(env.contracts[i].id) for i in (0, 5, 7)}


@pytest.mark.parametrize("change", ["typeCode", "q", "dateFrom", "dateTo", "pageSize", "grant", "member", "installation", "own_org", "actor", "client"])
async def test_cursor_binds_filter_actor_installation_and_current_authority(env, change):
    auth = await issue(env)
    first = await read(env, auth, params={"pageSize": 1, "typeCode": "rent"})
    assert first.status_code == 200 and first.json()["nextCursor"]
    params = {"pageSize": 1, "typeCode": "rent", "cursor": first.json()["nextCursor"]}
    next_auth = auth
    if change in ("typeCode", "q", "dateFrom", "dateTo", "pageSize"):
        params[change] = {"typeCode": "energy_supply", "q": "R3", "dateFrom": "2026-10-01",
                          "dateTo": "2026-10-02", "pageSize": 2}[change]
    elif change == "grant":
        response = await env.ac.post(f"/api/developer/clients/{auth.client_id}/installations", headers=env.core[0], json={
            "companyId": str(env.ca.id), "scopes": ["openid", *SCOPES], "locationIds": None,
            "resourceScopes": {"contracts": {"mode": "SET", "ids": [str(c.id) for c in env.contracts[:6]]}}})
        assert response.status_code == 201, response.text
    elif change == "member":
        env.members[0].object_scope = [env.points[0].id]
        await env.db.commit()
    elif change == "installation":
        install = await env.db.get(PartnerInstallation, uuid.UUID(auth.installation_id))
        install.all_locations = False
        from app.models_partner import PartnerInstallationLocation
        env.db.add(PartnerInstallationLocation(installation_id=install.id, location_id=env.points[0].id))
        await env.db.commit()
    elif change == "own_org":
        env.members[0].own_organization_id = env.orgs[0].id
        await env.db.commit()
    elif change == "actor":
        next_auth = await issue(env, employee=True)
    elif change == "client":
        next_auth = await issue(env)
    response = await read(env, next_auth, params=params)
    assert response.status_code == 400 and response.json()["code"] == "invalid_cursor", response.text


@pytest.mark.parametrize("target", ["membership", "user", "client", "installation", "grant", "module", "credential"])
async def test_revoke_denies_existing_cursor_and_metadata_before_catalog(env, target):
    auth = await issue(env, employee=target == "module", machine=target == "credential")
    first = await read(env, auth, params={"typeCode": "rent", "pageSize": 1})
    assert first.status_code == 200 and first.json()["nextCursor"]
    if target == "membership":
        await env.db.delete(env.members[0])
    elif target == "user":
        env.users[0].mail_only = True
    elif target == "client":
        (await env.db.get(PartnerClient, auth.client_id)).enabled = False
    elif target == "installation":
        (await env.db.get(PartnerInstallation, uuid.UUID(auth.installation_id))).approved = False
    elif target == "grant":
        (await env.db.get(PartnerGrant, uuid.UUID(auth.grant_id))).approved = False
    elif target == "module":
        role = CompanyRole(company_id=env.ca.id, name="R3 revoked references", modules=["docs"])
        env.db.add(role)
        await env.db.flush()
        env.members[1].role_id = role.id
    elif target == "credential":
        (await env.db.get(PartnerCredential, uuid.UUID(auth.credential_id))).enabled = False
    await env.db.commit()
    response = await read(env, auth, params={"typeCode": "rent", "pageSize": 1, "cursor": first.json()["nextCursor"]})
    assert response.status_code == 401
    label = await metadata(env, auth, "rent")
    assert label.status_code == 401
    assert not any("FROM CONTRACT_TYPES" in sql for sql in label.extensions["r3_sql"])


async def test_product_gets_do_not_mutate_persisted_business_auth_or_files(env, record_property):
    auth = await issue(env)
    sentinel = Path(os.environ["UPLOAD_DIR"]) / "r3-synthetic-sentinel.bin"
    sentinel.write_bytes(b"R3 immutable synthetic bytes\x00\xff")
    before = await snapshot()
    for _ in range(2):
        assert_items(await read(env, auth, params={"typeCode": "rent"}), [env.contracts[i] for i in (0, 5, 7)])
        assert (await metadata(env, auth, "rent")).status_code == 200
    after = await snapshot()
    assert before == after
    record_property("persisted_before", json.dumps(before, sort_keys=True))
    record_property("persisted_after", json.dumps(after, sort_keys=True))


async def test_identity_and_quota_are_each_enforced_once_per_endpoint(env, monkeypatch):
    from app.product_api import budget
    auth = await issue(env)
    counts = {"verify": 0, "quota": 0}
    verify, enforce = identity.verify_partner_access_token, budget.enforce
    async def actual_verify(*args, **kwargs):
        counts["verify"] += 1
        return await verify(*args, **kwargs)
    async def actual_enforce(*args, **kwargs):
        counts["quota"] += 1
        return await enforce(*args, **kwargs)
    monkeypatch.setattr(identity, "verify_partner_access_token", actual_verify)
    monkeypatch.setattr(budget, "enforce", actual_enforce)
    await read(env, auth, params={"typeCode": "rent"})
    assert counts == {"verify": 1, "quota": 1}
    await metadata(env, auth, "rent")
    assert counts == {"verify": 2, "quota": 2}


@pytest.mark.parametrize("params", [{}, {"typeCode": ""}, {"typeCode": "x" * 257}, {"typeCode": "\x00"},
    {"typeCode": "rent", "companyId": "foreign"}, {"typeCode": "rent", "q": "x"}, {"typeCode": "rent", "cursor": "x"}])
async def test_metadata_query_is_required_exact_and_bounded(env, params):
    auth = await issue(env)
    response = await read(env, auth, "/api/v1/contract-types", params=params)
    assert response.status_code == 422
    assert not any("FROM CONTRACT_TYPES" in sql for sql in response.extensions["r3_sql"])


@pytest.mark.parametrize("params", [{"typeCode": ""}, {"typeCode": "x" * 257}, {"typeCode": "\x00"},
    {"typeCode": "rent", "pageSize": 0}, {"typeCode": "rent", "dateFrom": "2026-02-30"},
    {"typeCode": "rent", "dateFrom": "2026-10-02", "dateTo": "2026-10-01"}])
async def test_contract_filter_preserves_existing_query_negatives(env, params):
    auth = await issue(env)
    assert (await read(env, auth, params=params)).status_code == 422


@pytest.mark.parametrize("path", ["/api/v1/objects", "/api/v1/equipment", "/api/v1/counterparties", "/api/v1/documents"])
async def test_type_filter_does_not_expand_other_resource_queries(env, path):
    auth = await issue(env, scopes=["objects:read", "equipment:read", "counterparties:read", "documents:read"],
        resources={r: {"mode": "ALL", "ids": []} for r in ("objects", "equipment", "counterparties", "documents")})
    assert (await read(env, auth, path, params={"typeCode": "rent"})).status_code == 422


@pytest.mark.parametrize("content", [b"{}", b"null", b"x"])
async def test_metadata_body_rejected_before_catalog(env, content):
    auth = await issue(env)
    response = await metadata(env, auth, "rent", content=content)
    assert response.status_code == 422
    assert not any("FROM CONTRACT_TYPES" in sql for sql in response.extensions["r3_sql"])


@pytest.mark.parametrize("kind", ["none", "core", "id_token", "docs_cookie"])
async def test_metadata_other_credential_classes_are_rejected(env, kind):
    auth = await issue(env)
    headers = {} if kind in ("none", "docs_cookie") else env.core[0] if kind == "core" else {
        "Authorization": "Bearer " + auth.tokens["id_token"]}
    if kind == "docs_cookie":
        headers = {"Cookie": "elsy_docs=synthetic-not-a-business-credential"}
    assert (await metadata(env, auth, "rent", headers=headers)).status_code == 401


async def test_feature_off_precedes_verification(env, monkeypatch):
    monkeypatch.setattr(identity.settings, "partner_api_enabled", False)
    auth = SimpleNamespace(headers={"Authorization": "Bearer invalid"})
    assert (await read(env, auth, params={"typeCode": "rent"})).status_code == 503
    assert (await metadata(env, auth, "rent")).status_code == 503


async def test_schema_required_nullability_format_and_fifteen_auth_profiles(env):
    from app.api_contracts import policy_registry
    schema = curated_openapi(env.product)
    model = schema["components"]["schemas"]["Contract"]
    assert {"typeCode", "validUntil"} <= set(model["required"])
    for name in ("typeCode", "validUntil"):
        field = model["properties"][name]
        assert "default" not in field and "format" not in field
        assert {t["type"] for t in field["anyOf"]} == {"string", "null"}
        assert all("format" not in t for t in field["anyOf"])
    assert next(t for t in model["properties"]["validUntil"]["anyOf"] if t["type"] == "string")["maxLength"] == 20
    for path in ("/contracts", "/contract-types"):
        params = schema["paths"][path]["get"]["parameters"]
        field = next(p for p in params if p["name"] == "typeCode")
        assert field["required"] is (path == "/contract-types")
    operation = schema["paths"]["/contract-types"]["get"]
    assert operation["operationId"] == "getContractTypeMetadata"
    assert operation["security"] == [{"ProductOAuth": SCOPES}, {"ProductServiceOAuth": SCOPES}]
    assert "requestBody" not in operation
    entries = policy_registry(env.product)
    assert len(entries) == 15
    assert sum("service" in e["principalKinds"] for e in entries) == 11
    assert sum("service" not in e["principalKinds"] for e in entries) == 4
    browser = public_client_openapi(schema)
    assert browser["paths"]["/contract-types"]["get"]["security"] == [{"ProductOAuth": SCOPES}]


async def test_native_string_boundaries_are_preserved_without_date_validation(env):
    auth = await issue(env)
    code, expiry = "X" * 256, "Y" * 20
    env.contracts[4].type_code, env.contracts[4].valid_until = code, expiry
    await env.db.commit()
    response = await read(env, auth, params={"typeCode": code})
    item = assert_items(response, [env.contracts[4]])[0]
    assert item["typeCode"] == code and item["validUntil"] == expiry
    response = await metadata(env, auth, code)
    assert response.status_code == 200 and response.json() == {
        "typeCode": code, "label": None, "gkBasis": None, "direction": None, "isActive": None}
