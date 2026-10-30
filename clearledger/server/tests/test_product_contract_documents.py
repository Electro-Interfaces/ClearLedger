"""Opt-in NEXT-R2 real OAuth/HTTP/PostgreSQL acceptance on one fresh exact DB.

Collected once by the ROOT runner with --noconftest; no schema DROP/seed,
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

FLAG = "RUN_PRODUCT_CONTRACT_DOCUMENTS_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip("ROOT opt-in NEXT-R2 runner required", allow_module_level=True)
from tests.partner_test_safety import partner_test_safety_error
if partner_test_safety_error(os.environ, flag=FLAG):
    raise pytest.UsageError("NEXT-R2 pre-import target guard refused")
_target = urlsplit(os.environ["TEST_DATABASE_URL"])
if (_target.hostname != "127.0.0.1" or _target.port != 33546
        or _target.path != "/api_contract_documents_test_20261030"
        or os.environ.get("ROOT_APPROVED_PRODUCT_CONTRACT_DOCUMENTS") != "1"):
    raise pytest.UsageError("Use immutable NEXT-R2 ROOT runner and exact fresh database")

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from app import database
from app.auth import hash_password
from app.models import (Company, CompanyRole, Contract, ContractLocation, Counterparty,
                        Organization, ServiceLocation, User, UserCompany, DocCard, DocKind, DocAccessGrant,
                        DocVersion, SourceFile, DocRelation, Task, TaskAttachment)
from app.models_partner import (PartnerClient, PartnerCredential, PartnerGrant,
                                PartnerInstallation, PartnerResourceScope, PartnerTokenFamily)
from app.product_api import create_product_api, curated_openapi, export_runtime_registry
from app.product_api.app import public_client_openapi
from app.product_api.queries import Query
from app.routers import auth_router, partner_admin_router, partner_oauth_router, references_router, docs_router
from app.services import partner_identity as identity

pytestmark = pytest.mark.asyncio(loop_scope="session")
ORIGIN = "https://contract-documents.example.invalid"
REDIRECT = "https://contract-documents-client.example.invalid/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
SCOPES = ["contracts:read", "documents:read"]
PASSWORD = "Contract-Objects-Synthetic-2026!"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def contract_documents_database(request):
    assert request.config._contract_documents_boundary.active
    async with database.engine.begin() as conn:
        assert await conn.scalar(text("SELECT current_database()")) == "api_contract_documents_test_20261030"
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
async def db(contract_documents_database):
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
    boundary = request.config._contract_documents_boundary
    suffix = uuid.uuid4().hex[:10]
    companies = [Company(name=f"R2 synthetic {i}", slug=f"r2-{suffix}-{i}", profile_id="energy") for i in range(2)]
    db.add_all(companies)
    await db.flush()
    ca, cb = companies
    orgs = [Organization(company_id=ca.id, name=f"R2 own {i}", inn=str(9900000000 + i)) for i in range(2)]
    foreign_org = Organization(company_id=cb.id, name="R2 foreign own", inn="9900000002")
    party = Counterparty(company_id=ca.id, name="R2 synthetic counterparty")
    foreign_party = Counterparty(company_id=cb.id, name="R2 foreign counterparty")
    users = [User(company_id=ca.id, name="R2 " + name, email=f"{suffix}-{name}@example.com",
                  password_hash=password_hash, role="user", is_superadmin=False, mail_only=False)
             for name in ("admin", "employee")]
    foreign_user = User(company_id=cb.id, name="R2 foreign admin", email=f"{suffix}-foreign@example.com",
                        password_hash=password_hash, role="user", is_superadmin=False, mail_only=False)
    db.add_all([*orgs, foreign_org, party, foreign_party, *users, foreign_user])
    await db.flush()
    at = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    points = [ServiceLocation(id=(f"r2-{suffix}-{i}" if i != 2 else f" Точка Ё {suffix} "),
        company_id=ca.id, code=f"R2-{i}", name=f"Synthetic R2 point {i}", type="ev_charging",
        created_at=at, extra_metadata={"private": "R2-NEVER-EXPOSE"}) for i in range(4)]
    alien = ServiceLocation(id=f"r2-foreign-{suffix}", company_id=cb.id, code="R2-ALIEN", name="Synthetic alien", created_at=at)
    db.add_all([*points, alien])
    await db.flush()
    members = [UserCompany(user_id=users[0].id, company_id=ca.id, role="admin"),
               UserCompany(user_id=users[1].id, company_id=ca.id, role="user", modules=["equipment", "references", "docs"],
                           object_scope=[points[0].id])]
    foreign_member = UserCompany(user_id=foreign_user.id, company_id=cb.id, role="admin")
    contracts = [Contract(company_id=ca.id, number=f"R2-{i}", date="2026-10-01", type="service",
        counterparty_id=party.id, organization_id=orgs[1 if i == 1 else 0].id,
        scope_type="company" if i == 2 else "unassigned" if i == 3 else "locations") for i in range(5)]
    foreign_contract = Contract(company_id=cb.id, number="R2-FOREIGN", date="2026-10-01", type="service",
        counterparty_id=foreign_party.id, organization_id=foreign_org.id, scope_type="locations")
    db.add_all([*members, foreign_member, *contracts, foreign_contract])
    await db.flush()
    db.add_all([ContractLocation(company_id=ca.id, contract_id=contracts[0].id, location_id=p.id) for p in points[:3]])
    db.add_all([ContractLocation(company_id=ca.id, contract_id=contracts[1].id, location_id=points[1].id),
                ContractLocation(company_id=ca.id, contract_id=contracts[2].id, location_id=points[0].id),
                ContractLocation(company_id=cb.id, contract_id=foreign_contract.id, location_id=alien.id)])
    kinds = [DocKind(company_id=c.id, code="r2-synthetic", name="R2 synthetic kind", fields=[], route=[])
             for c in companies]
    db.add_all(kinds)
    await db.flush()
    # Three explicit readable refs share a timestamp; hidden rows precede limits.
    docs = [DocCard(company_id=ca.id, kind_id=kinds[0].id, title="R2 synthetic paper",
        subject_ref=(f"contract:{contracts[0].id}" if i == 0 else None), object_id=points[i].id,
        organization_id=orgs[0].id, confidentiality="company", author_id=foreign_user.id,
        created_at=at, attrs={"private": "R2-NEVER-EXPOSE"}, source_ref="R2-NEVER-EXPOSE")
        for i in range(3)]
    private = DocCard(company_id=ca.id, kind_id=kinds[0].id, title="R2-NEVER-EXPOSE",
        subject_ref=None, object_id=points[0].id,
        organization_id=orgs[0].id, confidentiality="private", author_id=foreign_user.id, created_at=at)
    strict = DocCard(company_id=ca.id, kind_id=kinds[0].id, title="R2 strict paper",
        subject_ref=None, object_id=points[0].id,
        organization_id=orgs[0].id, confidentiality="strict", author_id=foreign_user.id, created_at=at)
    decoys = [DocCard(company_id=ca.id, kind_id=kinds[0].id, title=str(contracts[0].id),
        subject_ref=ref, object_id=points[0].id, organization_id=orgs[0].id,
        confidentiality="company", attrs={"contract_id": str(contracts[0].id)},
        source_ref=f"contract:{contracts[0].id}", created_at=at)
        for ref in (None, "contract:not-a-uuid", f"contract:{uuid.uuid4()}",
                    f"contract:{foreign_contract.id}", f"counterparty:{contracts[0].id}")]
    second_doc = DocCard(company_id=ca.id, kind_id=kinds[0].id, title="R2 second paper",
        subject_ref=f"contract:{contracts[1].id}", object_id=points[1].id,
        organization_id=orgs[1].id, confidentiality="company", created_at=at)
    alien_doc = DocCard(company_id=cb.id, kind_id=kinds[1].id, title="R2 foreign paper",
        subject_ref=f"contract:{foreign_contract.id}", object_id=alien.id,
        organization_id=foreign_org.id, confidentiality="company", created_at=at)
    cross_doc = DocCard(company_id=cb.id, kind_id=kinds[1].id, title="R2 cross tenant ref",
        subject_ref=f"contract:{contracts[0].id}", confidentiality="company", created_at=at)
    db.add_all([*docs, private, strict, *decoys, second_doc, alien_doc, cross_doc])
    await db.flush()
    # Native graph links are equal authority; duplicate edges must not multiply rows.
    db.add(DocRelation(company_id=ca.id, doc_id=decoys[0].id, kind="annex_of",
                       target_ref=f"contract:{contracts[0].id}"))
    db.add_all([DocRelation(company_id=ca.id, doc_id=docs[0].id, kind=kind,
                            target_ref=f"contract:{contracts[0].id}") for kind in ("basis", "annex_of")])
    # Mismatched relation tenant cannot expose a local document.
    db.add(DocRelation(company_id=cb.id, doc_id=decoys[1].id, kind="annex_of",
                       target_ref=f"contract:{contracts[0].id}"))
    # Native schema permits one subject card per company/ref. Other papers
    # belong through graph edges, including private/strict ACL controls.
    db.add_all([DocRelation(company_id=ca.id, doc_id=doc.id, kind="related",
                            target_ref=f"contract:{contracts[0].id}")
                for doc in [*docs[1:], private, strict]])
    linked = [*docs, decoys[0]]
    data = b"R2 synthetic immutable document bytes\x00\xff"
    sources, versions = [], []
    for doc in [docs[0], strict]:
        path = Path(os.environ["UPLOAD_DIR"]) / f"{doc.id}.bin"
        path.write_bytes(data)
        source = SourceFile(company_id=ca.id, file_name="r2.bin", mime_type="application/octet-stream",
            size=len(data), storage_path=str(path), fingerprint=hashlib.sha256(data).hexdigest())
        db.add(source)
        await db.flush()
        version = DocVersion(company_id=ca.id, doc_id=doc.id, revision=1, role="body",
            file_id=source.id, file_name="r2.bin", mime="application/octet-stream", size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest())
        sources.append(source)
        versions.append(version)
    db.add_all(versions)
    await db.commit()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_exception_handler(identity.PartnerProblem, identity.problem_handler)
    for router in (auth_router.router, partner_admin_router.router, partner_oauth_router.router,
                   partner_oauth_router.consent_router, references_router.router, docs_router.router):
        app.include_router(router, prefix="/api")
    # Real dependency, transaction and token verification; only the app assembly is bounded.
    product = create_product_api(session_factory=database.async_session_factory, issuer=ORIGIN,
                                 source_revision="next-r2-synthetic", cursor_key=b"r2-fixed-synthetic-cursor-key-32bytes")
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
        "name": "R2 synthetic application", "redirectUris": [REDIRECT], "scopes": scopes,
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
            "documents": {"mode": "ALL", "ids": []}, "contracts": {"mode": "ALL", "ids": []}}})
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
            "redirect_uri": REDIRECT, "scope": " ".join(scopes), "state": state, "nonce": "r2-" + state,
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
        response = await env.ac.request("GET", f"/api/v1/contracts/{identifier}/documents", params=params,
                                       content=content, headers=auth.headers if headers is None else headers)
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", capture)
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP")) for s in observed)
    assert response.headers["content-type"].startswith("application/json" if response.status_code == 200 else "application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    assert "R2-NEVER-EXPOSE" not in response.text
    if response.status_code != 200:
        assert response.json()["requestId"] == response.headers["x-request-id"]
    return response


def assert_page(response, contract, documents):
    assert response.status_code == 200, response.text
    value = response.json()
    assert set(value) == {"contractId", "items", "total", "nextCursor"}
    assert value["contractId"] == str(contract.id)
    assert value["total"] == len(documents) and value["nextCursor"] is None
    assert {item["documentId"] for item in value["items"]} == {str(doc.id) for doc in documents}
    assert all(set(item) == {"documentId"} for item in value["items"])

async def test_explicit_subject_and_graph_goldens_and_persisted_read_immutability(env, record_property):
    auth = await issue(env)
    before = await snapshot()
    for _ in range(2):
        assert_page(await read(env, auth), env.contracts[0], env.linked)
    after = await snapshot()
    assert before == after  # Auth setup writes precede capture; quota OFF for GETs.
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
    assert_page(await read(env, auth), env.contracts[0], env.linked)
    assert counts == {"verify": 1, "quota": 1}


@pytest.mark.parametrize("resource,mode", [(r, m) for r in ("contracts", "documents") for m in ("ALL", "SET", "EMPTY", "MISSING")])
async def test_each_typed_resource_grant_is_independent_before_detail(env, resource, mode):
    resources = {r: {"mode": "ALL", "ids": []} for r in ("contracts", "documents")}
    if mode == "MISSING":
        del resources[resource]
    else:
        resources[resource] = {"mode": mode, "ids": [str(env.contracts[0].id if resource == "contracts" else env.docs[1].id)] if mode == "SET" else []}
    auth = await issue(env, resources=resources)
    env.detailed.clear()
    response = await read(env, auth)
    if mode in ("EMPTY", "MISSING"):
        assert response.status_code == 403, response.text
        assert not env.detailed
    else:
        assert_page(response, env.contracts[0], [env.docs[1]] if resource == "documents" and mode == "SET" else env.linked)


@pytest.mark.parametrize("missing", SCOPES)
async def test_each_oauth_scope_required_before_detail(env, missing):
    auth = await issue(env, scopes=[s for s in SCOPES if s != missing])
    env.detailed.clear()
    assert (await read(env, auth)).status_code == 403
    assert not env.detailed


@pytest.mark.parametrize("parent", ["missing", "malformed", "foreign", "ungranted"])
async def test_parent_denials_are_same_404(env, parent):
    auth = await issue(env, resources={"documents": {"mode": "ALL", "ids": []},
        "contracts": {"mode": "SET", "ids": [str(env.contracts[0].id)]}})
    identifier = uuid.uuid4() if parent == "missing" else "not-a-uuid" if parent == "malformed" else env.foreign_contract.id if parent == "foreign" else env.contracts[1].id
    response = await read(env, auth, identifier)
    assert response.status_code == 404 and response.json()["code"] == "not_found"


async def test_employee_object_ceiling_and_independently_hidden_document(env):
    auth = await issue(env, employee=True)
    assert_page(await read(env, auth), env.contracts[0], [env.docs[0], env.decoys[0]])
    # Parent remains visible through point zero; its paper on point one is hidden.
    assert (await env.ac.get(f"/api/v1/contracts/{env.contracts[0].id}", headers=auth.headers)).status_code == 200
    assert (await env.ac.get(f"/api/v1/documents/{env.docs[1].id}", headers=auth.headers)).status_code == 404
    env.members[1].object_scope = []
    await env.db.commit()
    assert (await read(env, auth)).status_code == 404


async def test_own_organization_filters_parent_and_documents_independently(env):
    auth = await issue(env, employee=True)
    env.members[1].own_organization_id = env.orgs[0].id
    env.members[1].object_scope = None
    env.docs[2].organization_id = env.orgs[1].id
    await env.db.commit()
    assert_page(await read(env, auth), env.contracts[0], [env.docs[0], env.docs[1], env.decoys[0]])
    assert (await read(env, auth, 1)).status_code == 404
    env.members[1].own_organization_id = env.orgs[1].id
    await env.db.commit()
    assert (await read(env, auth)).status_code == 404
    assert_page(await read(env, auth, 1), env.contracts[1], [env.second_doc])


async def test_foreign_organization_denied_before_detail(env):
    auth = await issue(env, employee=True)
    env.members[1].own_organization_id = env.foreign_org.id
    await env.db.commit()
    env.detailed.clear()
    assert (await read(env, auth)).status_code == 403
    assert not env.detailed


async def test_two_companies_installations_and_users_cannot_transfer_cursor(env):
    local, foreign, employee, other_install = await issue(env), await issue(env, foreign=True), await issue(env, employee=True), await issue(env)
    first = await read(env, local, params={"pageSize": 1})
    assert first.status_code == 200 and first.json()["nextCursor"]
    assert (await read(env, foreign)).status_code == 404
    assert_page(await read(env, foreign, env.foreign_contract.id), env.foreign_contract, [env.alien_doc])
    for auth, parent in ((foreign, env.foreign_contract.id), (employee, env.contracts[0].id), (other_install, env.contracts[0].id)):
        denied = await read(env, auth, parent, params={"pageSize": 1, "cursor": first.json()["nextCursor"]})
        assert denied.status_code == 400


async def test_doc_role_allow_then_explicit_deny_is_current(env):
    auth = await issue(env, employee=True)
    role = CompanyRole(company_id=env.ca.id, name="R2 documents reader", modules=["references", "docs"])
    env.db.add(role)
    await env.db.flush()
    env.members[1].role_id = role.id
    acl = DocAccessGrant(company_id=env.ca.id, scope_type="doc", scope_id=env.private.id,
        subject_type="role", subject_id=role.id, permissions=["read"], denied_permissions=[])
    env.db.add(acl)
    await env.db.commit()
    assert_page(await read(env, auth), env.contracts[0], [env.docs[0], env.decoys[0], env.private])
    acl.denied_permissions = ["read"]
    await env.db.commit()
    assert_page(await read(env, auth), env.contracts[0], [env.docs[0], env.decoys[0]])


async def test_link_does_not_grant_file_bytes_or_download_permission(env):
    read_only = await issue(env)
    assert_page(await read(env, read_only), env.contracts[0], env.linked)
    path = f"/api/v1/documents/{env.docs[0].id}/versions/{env.versions[0].id}/content"
    assert (await env.ac.get(path, headers=read_only.headers)).status_code == 403
    acl = DocAccessGrant(company_id=env.ca.id, scope_type="doc", scope_id=env.strict.id,
        subject_type="user", subject_id=env.users[0].id, permissions=["read"], denied_permissions=[])
    env.db.add(acl)
    await env.db.commit()
    full = await issue(env, scopes=[*SCOPES, "documents.files:download"])
    assert_page(await read(env, full), env.contracts[0], [*env.linked, env.strict])
    path = f"/api/v1/documents/{env.strict.id}/versions/{env.versions[1].id}/content"
    assert (await env.ac.get(path, headers=full.headers)).status_code == 404
    acl.permissions = ["read", "download"]
    await env.db.commit()
    response = await env.ac.get(path, headers=full.headers)
    assert response.status_code == 200 and response.content == env.data
    acl.denied_permissions = ["read"]
    await env.db.commit()
    assert (await env.ac.get(path, headers=full.headers)).status_code == 404
    assert_page(await read(env, full), env.contracts[0], env.linked)


async def test_subject_graph_duplicate_and_mismatched_refs_match_native_read(env):
    auth = await issue(env)
    # Null subject plus explicit annex is valid; a differing subject does not
    # invalidate an explicit graph edge to a second contract.
    env.db.add(DocRelation(company_id=env.ca.id, doc_id=env.second_doc.id, kind="basis",
                           target_ref=f"contract:{env.contracts[0].id}"))
    await env.db.commit()
    expected = [*env.linked, env.second_doc]
    assert_page(await read(env, auth), env.contracts[0], expected)
    response = await env.ac.get("/api/docs", headers=env.core[0], params={"company_id": str(env.ca.id),
        "ref": f"contract:{env.contracts[0].id}"})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["count"] == len(expected)
    assert {str(d["id"]) for d in value["docs"]} == {str(d.id) for d in expected}
    assert (await env.ac.get("/api/docs", headers=auth.headers, params={"company_id": str(env.ca.id)})).status_code == 401


async def test_equal_timestamp_pages_have_no_hidden_counts_or_duplicates(env):
    auth = await issue(env)
    params, seen = {"pageSize": 1}, []
    for _ in env.linked:
        response = await read(env, auth, params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 4 and len(page["items"]) == 1
        seen.extend(i["documentId"] for i in page["items"])
        params["cursor"] = page["nextCursor"]
    assert params["cursor"] is None and len(set(seen)) == 4
    assert set(seen) == {str(d.id) for d in env.linked}


@pytest.mark.parametrize("change", ["parent", "pageSize", "documents", "contracts", "member", "installation", "own_org"])
async def test_cursor_binding_changes_with_parent_or_current_ceilings(env, change):
    auth = await issue(env)
    first = await read(env, auth, params={"pageSize": 1})
    assert first.status_code == 200 and first.json()["nextCursor"]
    params = {"pageSize": 1, "cursor": first.json()["nextCursor"]}
    parent = 1 if change == "parent" else 0
    if change == "pageSize":
        params["pageSize"] = 2
    elif change in ("documents", "contracts"):
        resources = {"documents": {"mode": "ALL", "ids": []}, "contracts": {"mode": "ALL", "ids": []}}
        resources[change] = {"mode": "SET", "ids": [str(d.id) for d in env.linked[:2]] if change == "documents" else [str(env.contracts[0].id)]}
        response = await env.ac.post(f"/api/developer/clients/{auth.client_id}/installations", headers=env.core[0], json={
            "companyId": str(env.ca.id), "scopes": ["openid", *SCOPES], "locationIds": None, "resourceScopes": resources})
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
    if change == "parent":
        # Establish independent destination visibility before interpreting cursor denial.
        assert_page(await read(env, auth, parent), env.contracts[1], [env.second_doc])
    response = await read(env, auth, parent, params=params)
    assert response.status_code == 400 and response.json()["code"] == "invalid_cursor", response.text

    if change == "parent":
        env.members[0].own_organization_id = env.orgs[0].id
        await env.db.commit()
        hidden = await read(env, auth, parent, params=params)
        assert hidden.status_code == 404 and hidden.json()["code"] == "not_found"


@pytest.mark.parametrize("target", ["membership", "user", "installation", "grant", "client", "references_module", "docs_module"])
async def test_live_user_module_and_authority_revoke_denies_cursor(env, target):
    auth = await issue(env, employee=target.endswith("_module"))
    first = await read(env, auth, params={"pageSize": 1})
    assert first.status_code == 200 and first.json()["nextCursor"]
    if target == "membership":
        await env.db.delete(env.members[0])
    elif target == "user":
        env.users[0].mail_only = True
    elif target == "installation":
        (await env.db.get(PartnerInstallation, uuid.UUID(auth.installation_id))).approved = False
    elif target == "grant":
        (await env.db.get(PartnerGrant, uuid.UUID(auth.grant_id))).approved = False
    elif target == "client":
        (await env.db.get(PartnerClient, auth.client_id)).enabled = False
    else:
        role = CompanyRole(company_id=env.ca.id, name="R2 revoked module", modules=["docs"] if target == "references_module" else ["references"])
        env.db.add(role)
        await env.db.flush()
        env.members[1].role_id = role.id
    await env.db.commit()
    env.detailed.clear()
    assert (await read(env, auth, params={"pageSize": 1, "cursor": first.json()["nextCursor"]})).status_code == 401
    assert not env.detailed


@pytest.mark.parametrize("params", [{"q": "x"}, {"dateFrom": "2026-01-01"}, {"companyId": "foreign"},
    {"objectId": "hidden"}, {"pageSize": 0}, {"pageSize": 201}, {"cursor": ""}, {"cursor": "x" * 4097}])
async def test_unknown_queries_and_bounded_inputs(env, params):
    auth = await issue(env)
    env.detailed.clear()
    assert (await read(env, auth, params=params)).status_code == 422
    assert not env.detailed


@pytest.mark.parametrize("content", [b"{}", b"null", b"x"])
async def test_body_rejected_before_detail(env, content):
    auth = await issue(env)
    env.detailed.clear()
    assert (await read(env, auth, content=content)).status_code == 422
    assert not env.detailed


@pytest.mark.parametrize("kind", ["none", "core", "id_token", "docs_cookie", "machine"])
async def test_other_credentials_never_reach_detail(env, kind):
    auth = await issue(env, machine=True, scopes=["contracts:read"]) if kind == "machine" else await issue(env)
    headers = {} if kind in ("none", "docs_cookie") else env.core[0] if kind == "core" else {
        "Authorization": "Bearer " + auth.tokens["id_token"]} if kind == "id_token" else auth.headers
    if kind == "docs_cookie":
        headers = {"Cookie": "elsy_docs=synthetic-only-not-a-business-credential"}
    env.detailed.clear()
    assert (await read(env, auth, headers=headers)).status_code == (403 if kind == "machine" else 401)
    assert not env.detailed


async def test_feature_off_precedes_verification_and_detail(env, monkeypatch):
    monkeypatch.setattr(identity.settings, "partner_api_enabled", False)
    env.detailed.clear()
    response = await read(env, SimpleNamespace(headers={"Authorization": "Bearer invalid"}))
    assert response.status_code == 503 and not env.detailed


async def test_cursor_literal_null_invalid(env):
    auth = await issue(env)
    assert (await read(env, auth, params={"cursor": "null"})).status_code == 400


async def test_schema_has_fourteen_routes_and_user_only_document_relation(env):
    schema = curated_openapi(env.product)
    registry = export_runtime_registry(env.product)
    assert len(registry["operations"]) == 14
    operation = schema["paths"]["/contracts/{contractId}/documents"]["get"]
    assert operation["operationId"] == "listContractDocuments"
    assert operation["security"] == [{"ProductOAuth": SCOPES}]
    assert {p["name"] for p in operation["parameters"]} == {"contractId", "pageSize", "cursor"}
    assert "requestBody" not in operation
    browser = public_client_openapi(schema)
    assert browser["paths"]["/contracts/{contractId}/documents"]["get"]["security"] == [{"ProductOAuth": SCOPES}]
    assert set(browser["components"]["securitySchemes"]) == {"ProductOAuth"}


async def test_fully_hidden_document_set_does_not_hide_authorized_parent(env):
    auth = await issue(env, resources={"contracts": {"mode": "ALL", "ids": []},
        "documents": {"mode": "SET", "ids": [str(env.private.id)]}})
    assert_page(await read(env, auth), env.contracts[0], [])


@pytest.mark.parametrize("parent", [2, 3])
async def test_explicit_paper_for_company_or_unassigned_parent(env, parent):
    auth = await issue(env)
    env.docs[0].subject_ref = f"contract:{env.contracts[parent].id}"
    await env.db.commit()
    assert_page(await read(env, auth, parent), env.contracts[parent], [env.docs[0]])


async def test_shared_source_task_policy_is_not_expanded_by_contract_link(env):
    auth = await issue(env, scopes=[*SCOPES, "documents.files:download"])
    task = Task(company_id=env.ca.id, title="R2 private task", author_id=env.foreign_user.id, visibility="private")
    env.db.add(task)
    await env.db.flush()
    env.db.add(TaskAttachment(task_id=task.id, file_id=env.sources[0].id))
    await env.db.commit()
    assert_page(await read(env, auth), env.contracts[0], env.linked)
    path = f"/api/v1/documents/{env.docs[0].id}/versions/{env.versions[0].id}/content"
    assert (await env.ac.get(path, headers=auth.headers)).status_code == 404
