"""Real verifier/product HTTP A/B SQL counts; synthetic PostgreSQL, opt-in only.

RUN_PARTNER_RESOURCE_TESTS=1 TEST_DATABASE_URL=<owned synthetic test DB>
UPLOAD_DIR=/absolute/resource-budget-test-uploads python -m pytest
  tests/test_partner_resource_query_budget.py -q

The baseline is the exact resource_scopes function from immutable BASELINE,
executed with the same actual verifier/models/transactions as the batch loader.
No fake verifier, permissions, DB counters, customer env or external keys.
"""
import ast
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
import uuid

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event, select

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_PARTNER_RESOURCE_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip("Opt in with RUN_PARTNER_RESOURCE_TESTS=1", allow_module_level=True)
error = partner_test_safety_error(os.environ, flag=FLAG)
if error:
    raise pytest.UsageError("Refusing resource budget database: " + error)

from app.models import (App, Company, CompanyApp, CompanyRole, Contract, Counterparty,
    DocCard, DocKind, EzsEquipmentUnit, Organization, ServiceLocation, User, UserCompany)
from app.models_partner import (PartnerClient, PartnerCredential, PartnerGrant, PartnerInstallation,
    PartnerResourceItem, PartnerResourceScope, PartnerSubject, PartnerToken, PartnerTokenFamily)
from app.product_api import create_product_api
from app.services import partner_identity as identity
from tests.conftest import _test_session_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")
BASELINE = "9e9170da553d38313c4f23498c8c13634d79ad98"
RESOURCES = tuple(identity.RESOURCE_MODELS)
SCOPES = frozenset({"openid"} | {kind + ":read" for kind in RESOURCES})


@pytest.fixture(scope="module")
def loaders():
    # Only this owned function differs from BASELINE in the runtime patch.
    # Extract source, not a hand-written reimplementation of the old algorithm.
    repo = Path(__file__).resolve().parents[3]
    source = subprocess.check_output(["git", "show", BASELINE +
        ":clearledger/server/app/services/partner_identity.py"], cwd=repo, text=True)
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "resource_scopes")
    namespace = dict(identity.__dict__)
    exec(compile(ast.Module(body=[function], type_ignores=[]), BASELINE, "exec"), namespace)
    return {"baseline": namespace["resource_scopes"], "batch": identity.resource_scopes}


@pytest.fixture(scope="module")
def signing_pem():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


@contextmanager
def sql_calls(engine):
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        # SQL text only: do not persist credential/token values or query IDs.
        statements.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)


def table_reads(statements, table):
    return sum("from " + table in statement.lower().replace('"', "") for statement in statements)


@pytest_asyncio.fixture(loop_scope="session")
async def budget(db, monkeypatch, signing_pem, request):
    assert partner_test_safety_error(os.environ, flag=FLAG) is None
    for field, value in {"partner_oauth_enabled": True, "partner_api_enabled": True,
        "partner_oauth_issuer": "https://resource-budget.example.invalid",
        "partner_oauth_audience": "urn:elsyplus:resource-budget:test",
        "partner_oauth_signing_key": base64.b64encode(signing_pem).decode(),
        "partner_oauth_kid": "resource-budget/1"}.items():
        monkeypatch.setattr(identity.settings, field, value)
    suffix = uuid.uuid4().hex
    company, other = [Company(id=uuid.uuid4(), name="Synthetic budget company",
        slug="budget-" + suffix + str(i), profile_id="energy") for i in range(2)]
    db.add_all([company, other])
    await db.flush()
    user = User(id=uuid.uuid4(), company_id=company.id, name="Synthetic budget user",
        email=suffix + "@example.invalid", password_hash="synthetic-not-for-login", is_superadmin=False)
    role = CompanyRole(id=uuid.uuid4(), company_id=company.id, name="Synthetic full role", modules=None)
    db.add_all([user, role])
    await db.flush()
    member = UserCompany(user_id=user.id, company_id=company.id, role="user", role_id=role.id,
        modules=None, object_scope=None)
    db.add(member)
    # HTTP cardinality really changes with pageSize for all five resources.
    count = 201 if "http_page_budget" in request.node.name else 3
    at = datetime(2026, 1, 2, 3, tzinfo=timezone.utc)
    data, foreign = {}, {}
    for index, tenant in enumerate((company, other)):
        n = count if index == 0 else 1
        org = Organization(id=uuid.uuid4(), company_id=tenant.id, name="Synthetic organization", inn="9999999999")
        kind = DocKind(id=uuid.uuid4(), company_id=tenant.id, code="budget", name="Synthetic kind", fields=[], route=[])
        locations = [ServiceLocation(id=f"budget-{suffix[:20]}-{index}-{i}", company_id=tenant.id,
            code=f"B-{i}", name=f"Synthetic object {i}", type="ezs", created_at=at) for i in range(n)]
        parties = [Counterparty(id=uuid.uuid4(), company_id=tenant.id,
            name=f"Synthetic party {i}", created_at=at) for i in range(n)]
        db.add_all([org, kind, *locations, *parties])
        await db.flush()
        contracts = [Contract(id=uuid.uuid4(), company_id=tenant.id, number=f"B-{i}", date="2026-01-02",
            type="service", counterparty_id=parties[i].id, organization_id=org.id,
            scope_type="company", created_at=at) for i in range(n)]
        equipment = [EzsEquipmentUnit(id=uuid.uuid4(), company_id=tenant.id, kind="station",
            current_location_id=locations[i].id, state="in_operation", created_at=at) for i in range(n)]
        docs = [DocCard(id=uuid.uuid4(), company_id=tenant.id, kind_id=kind.id,
            title=f"Synthetic document {i}", confidentiality="company", author_id=user.id,
            object_id=locations[i].id, counterparty_id=parties[i].id, created_at=at) for i in range(n)]
        db.add_all([*contracts, *equipment, *docs])
        await db.flush()
        values = dict(zip(RESOURCES, (locations, equipment, parties, contracts, docs)))
        if index == 0:
            data = values
        else:
            foreign = {key: values[key][0] for key in RESOURCES}
    app = App(id=uuid.uuid4(), code="budget-" + suffix, name="Synthetic partner", kind="partner", is_active=True)
    db.add(app)
    await db.flush()
    client = PartnerClient(id="budget-" + suffix, app_id=app.id, owner_company_id=company.id,
        redirect_uris=["https://budget.example.invalid/callback"], allowed_scopes=sorted(SCOPES),
        auth_method="client_secret_basic", enabled=True)
    installed = CompanyApp(id=uuid.uuid4(), company_id=company.id, app_id=app.id, enabled=True)
    db.add_all([client, installed])
    await db.flush()
    installation = PartnerInstallation(id=installed.id, company_id=company.id, client_id=client.id,
        approved=True, scopes=sorted(SCOPES), all_locations=True)
    db.add(installation)
    await db.flush()
    grant = PartnerGrant(id=uuid.uuid4(), installation_id=installation.id, client_id=client.id,
        company_id=company.id, user_id=user.id, kind="user", scopes=sorted(SCOPES), approved=True)
    secret = "synthetic-" + suffix
    credential = PartnerCredential(id=uuid.uuid4(), client_id=client.id, secret_hash=identity.digest(secret),
        enabled=True, expires_at=identity.now() + timedelta(days=1))
    subject = PartnerSubject(user_id=user.id, client_id=client.id, subject="pairwise-" + suffix)
    db.add_all([grant, credential, subject])
    await db.flush()
    family = PartnerTokenFamily(id=uuid.uuid4(), grant_id=grant.id, credential_id=credential.id,
        token_version=user.token_version, auth_time=int(time.time()), expires_at=identity.now() + timedelta(minutes=20))
    db.add(family)
    await db.flush()
    expires = identity.now() + timedelta(minutes=5)
    token_id = uuid.uuid4()
    payload = {"iss": identity.settings.partner_oauth_issuer, "aud": identity.settings.partner_oauth_audience,
        "sub": subject.subject, "client_id": client.id, "jti": str(token_id), "iat": int(time.time()),
        "exp": int(expires.timestamp()), "token_use": "partner_access", "scope": " ".join(sorted(SCOPES))}
    raw = jwt.encode(payload, signing_pem, algorithm="RS256",
        headers={"typ": "at+jwt", "kid": identity.settings.partner_oauth_kid})
    token = PartnerToken(id=token_id, family_id=family.id, access_hash=identity.digest(raw),
        scope=payload["scope"], expires_at=expires)
    db.add(token)
    await db.commit()
    product = create_product_api(session_factory=_test_session_factory, enabled=True,
        upload_dir=os.environ["UPLOAD_DIR"], cursor_key=b"synthetic-budget-cursor-key-32bytes",
        issuer=identity.settings.partner_oauth_issuer)
    async with AsyncClient(transport=ASGITransport(app=product), base_url="http://test",
        headers={"Authorization": "Bearer " + raw}) as http:
        yield SimpleNamespace(**locals(), factory=_test_session_factory, engine=db.bind)


async def profiles(b, mode="ALL", set_count=0):
    await b.db.execute(delete(PartnerResourceScope).where(PartnerResourceScope.installation_id == b.installation.id))
    for index, (kind, (_, column)) in enumerate(identity.RESOURCE_MODELS.items()):
        actual = "SET" if index < set_count else mode
        b.db.add(PartnerResourceScope(installation_id=b.installation.id, kind=kind, mode=actual))
        await b.db.flush()
        if actual == "SET":
            b.db.add_all([PartnerResourceItem(installation_id=b.installation.id, kind=kind, **{column: row.id})
                          for row in b.data[kind]])
    await b.db.commit()


async def verify(b):
    async with b.factory() as session:
        return await identity.verify_partner_access_token(b.raw, session)


@pytest.mark.parametrize("mode,set_count", [("ALL", n) for n in range(6)] + [("EMPTY", 0)])
async def test_full_verifier_actual_sql_delta(budget, loaders, monkeypatch, mode, set_count, record_property):
    b = budget
    await profiles(b, mode, set_count)
    counts, values = {}, {}
    for name, loader in loaders.items():
        monkeypatch.setattr(identity, "resource_scopes", loader)
        with sql_calls(b.engine) as calls:
            values[name] = await verify(b)
        counts[name] = len(calls)
        assert table_reads(calls, "partner_resource_scopes") == (5 if name == "baseline" else 1)
        assert table_reads(calls, "partner_resource_items") == (set_count if name == "baseline" else int(set_count > 0))
    assert values["baseline"] == values["batch"]
    assert counts["baseline"] - counts["batch"] == 4 + max(0, set_count - 1)
    record_property("verifier_sql", json.dumps({"baselineRevision": BASELINE, "mode": mode,
        "setProfiles": set_count, **counts}, sort_keys=True))


@pytest.mark.parametrize("set_count", [0, 5])
async def test_machine_verifier_and_http_keep_unused_profile_checks(budget, loaders, monkeypatch, set_count, record_property):
    b = budget
    await profiles(b, set_count=set_count)
    scopes = sorted(SCOPES - {"openid", "documents:read"})
    b.grant.kind, b.grant.user_id, b.grant.scopes = "machine", None, scopes
    b.family.token_version = b.family.auth_time = None
    b.family.expires_at = identity.now() + timedelta(minutes=5)
    b.payload.update(sub="client:" + b.client.id, scope=" ".join(scopes))
    b.raw = jwt.encode(b.payload, b.signing_pem, algorithm="RS256",
        headers={"typ": "at+jwt", "kid": identity.settings.partner_oauth_kid})
    b.token.access_hash, b.token.scope = identity.digest(b.raw), b.payload["scope"]
    await b.db.commit()
    b.http.headers["Authorization"] = "Bearer " + b.raw
    counts = {}
    for name, loader in loaders.items():
        monkeypatch.setattr(identity, "resource_scopes", loader)
        with sql_calls(b.engine) as calls:
            assert (await verify(b)).is_machine
        counts[name] = len(calls)
        assert (await b.http.get("/objects")).status_code == 200
        assert (await b.http.get("/documents")).status_code == 403
    assert counts["baseline"] - counts["batch"] == (8 if set_count else 4)
    record_property("machine_sql", json.dumps({"setProfiles": set_count, **counts}, sort_keys=True))
    if set_count:
        item = await b.db.scalar(select(PartnerResourceItem).where(
            PartnerResourceItem.installation_id == b.installation.id, PartnerResourceItem.kind == "documents"))
        item.document_id = b.foreign["documents"].id
        await b.db.commit()
        # documents is absent from machine OAuth scopes and from this endpoint;
        # an invalid stored profile must still invalidate the whole grant.
        for loader in loaders.values():
            monkeypatch.setattr(identity, "resource_scopes", loader)
            assert (await b.http.get("/objects")).status_code == 401


@pytest.mark.parametrize("resource", RESOURCES)
@pytest.mark.parametrize("mode", ["ALL", "SET", "EMPTY"])
async def test_http_page_budget_is_constant_with_real_verifier(budget, loaders, monkeypatch, resource, mode, record_property):
    b = budget
    set_count = 5 if mode == "SET" else 0
    await profiles(b, "EMPTY" if mode == "EMPTY" else "ALL", set_count)
    counts, results = {}, {}
    for name, loader in loaders.items():
        monkeypatch.setattr(identity, "resource_scopes", loader)
        counts[name], results[name] = [], []
        for size in (1, 50, 200):
            with sql_calls(b.engine) as calls:
                response = await b.http.get("/" + resource, params={"pageSize": size})
            assert response.status_code == (403 if mode == "EMPTY" else 200), response.text
            value = response.json()
            value.pop("requestId", None)
            if mode != "EMPTY":
                assert len(value["items"]) == size and value["total"] == 201
                assert value["nextCursor"]
            counts[name].append(len(calls))
            results[name].append(value)
        assert len(set(counts[name])) == 1, counts
    assert results["baseline"] == results["batch"]
    assert [a - b for a, b in zip(counts["baseline"], counts["batch"])] == [8 if set_count else 4] * 3
    record_property("http_sql", json.dumps({"resource": resource, "mode": mode, "sizes": [1, 50, 200], **counts}, sort_keys=True))


@pytest.mark.parametrize("loader_name", ["baseline", "batch"])
@pytest.mark.parametrize("change", ["role", "member", "mail_only", "locked", "tv", "client", "app", "company_app",
    "installation", "grant", "credential", "credential_expired", "family", "token", "family_expired", "token_expired",
    "parent_limit", "client_scopes", "installation_scopes", "grant_scopes"])
async def test_current_authority_change_denies_next_http_call(budget, loaders, monkeypatch, loader_name, change):
    b = budget
    await profiles(b)
    monkeypatch.setattr(identity, "resource_scopes", loaders[loader_name])
    assert (await b.http.get("/objects")).status_code == 200
    if change == "role": b.role.modules = []
    elif change == "member": await b.db.delete(b.member)
    elif change == "mail_only": b.user.mail_only = True
    elif change == "locked": b.user.locked_until = identity.now() + timedelta(hours=1)
    elif change == "tv": b.user.token_version += 1
    elif change == "client": b.client.enabled = False
    elif change == "app": b.app.is_active = False
    elif change == "company_app": b.installed.enabled = False
    elif change == "installation": b.installation.approved = False
    elif change == "grant": b.grant.approved = False
    elif change == "credential": b.credential.enabled = False
    elif change == "credential_expired": b.credential.expires_at = identity.now() - timedelta(seconds=1)
    elif change == "family": b.family.revoked = True
    elif change == "token": b.token.revoked = True
    elif change == "family_expired": b.family.expires_at = identity.now() - timedelta(seconds=1)
    elif change == "token_expired": b.token.expires_at = identity.now() - timedelta(seconds=1)
    elif change == "parent_limit": b.family.auth_time = int(time.time()) - 8 * 86400
    elif change == "client_scopes": b.client.allowed_scopes = []
    elif change == "installation_scopes": b.installation.scopes = []
    elif change == "grant_scopes": b.grant.scopes = []
    await b.db.commit()
    response = await b.http.get("/objects")
    assert response.status_code == 401, response.text


@pytest.mark.parametrize("loader_name", ["baseline", "batch"])
async def test_membership_object_scope_remains_live_and_empty_denies(budget, loaders, monkeypatch, loader_name):
    b = budget
    await profiles(b)
    monkeypatch.setattr(identity, "resource_scopes", loaders[loader_name])
    assert (await b.http.get("/objects")).json()["total"] == 3
    b.member.object_scope = [b.data["objects"][0].id]
    await b.db.commit()
    value = (await b.http.get("/objects")).json()
    assert [item["id"] for item in value["items"]] == b.member.object_scope
    b.member.object_scope = []
    await b.db.commit()
    # Existing domain behavior is a successful empty projection, not a new
    # status-code contract; the membership restriction still grants no rows.
    response = await b.http.get("/objects")
    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["total"] == 0


@pytest.mark.parametrize("loader_name", ["baseline", "batch"])
async def test_empty_installation_locations_do_not_expand_all_profile(budget, loaders, monkeypatch, loader_name):
    b = budget
    await profiles(b)
    monkeypatch.setattr(identity, "resource_scopes", loaders[loader_name])
    assert (await verify(b)).resource_scopes["objects"].mode == "ALL"
    b.installation.all_locations = False  # No approved location rows exist.
    await b.db.commit()
    value = await verify(b)
    assert value.resource_scopes["objects"].mode == "EMPTY"
    assert value.resource_scopes["objects"].ids == frozenset()
    assert (await b.http.get("/objects")).status_code == 403


@pytest.mark.parametrize("loader_name", ["baseline", "batch"])
@pytest.mark.parametrize("kind", RESOURCES)
async def test_foreign_resource_in_unused_profile_denies_whole_grant(budget, loaders, monkeypatch, loader_name, kind):
    b = budget
    await profiles(b, set_count=5)
    monkeypatch.setattr(identity, "resource_scopes", loaders[loader_name])
    endpoint = "equipment" if kind == "objects" else "objects"
    assert (await b.http.get("/" + endpoint)).status_code == 200
    _, column = identity.RESOURCE_MODELS[kind]
    item = await b.db.scalar(select(PartnerResourceItem).where(
        PartnerResourceItem.installation_id == b.installation.id, PartnerResourceItem.kind == kind))
    setattr(item, column, b.foreign[kind].id)
    await b.db.commit()
    assert (await b.http.get("/" + endpoint)).status_code == 401


@pytest.mark.parametrize("loader_name", ["baseline", "batch"])
async def test_profile_refresh_missing_and_deleted_set_remain_empty(budget, loaders, monkeypatch, loader_name):
    b = budget
    await profiles(b, set_count=5)
    monkeypatch.setattr(identity, "resource_scopes", loaders[loader_name])
    async with b.factory() as session:
        held = await session.get(PartnerResourceScope, (b.installation.id, "objects"))
        assert held.mode == "SET"
        assert (await identity.verify_partner_access_token(b.raw, session)).resource_scopes["objects"].ids
        # A second transaction changes a row still held in this identity map.
        profile = await b.db.get(PartnerResourceScope, (b.installation.id, "objects"))
        profile.mode = "EMPTY"
        await b.db.commit()
        fresh = await identity.verify_partner_access_token(b.raw, session)
        assert held.mode == "EMPTY" and fresh.resource_scopes["objects"].mode == "EMPTY"
        await b.db.delete(profile)
        await b.db.commit()
        assert (await identity.verify_partner_access_token(b.raw, session)).resource_scopes["objects"].mode == "EMPTY"
    # Deleting all canonical equipment cascades its typed items; SET must not
    # become ALL when the last allowed resource disappears.
    for row in b.data["equipment"]:
        await b.db.delete(row)
    await b.db.commit()
    assert (await verify(b)).resource_scopes["equipment"].mode == "EMPTY"
    assert (await b.http.get("/equipment")).status_code == 403


@pytest.mark.parametrize("loader_name", ["baseline", "batch"])
async def test_item_rows_ignore_other_installations_and_non_set_profiles(budget, loaders, monkeypatch, loader_name):
    b = budget
    await profiles(b, set_count=1)
    monkeypatch.setattr(identity, "resource_scopes", loaders[loader_name])
    ca = CompanyApp(id=uuid.uuid4(), company_id=b.other.id, app_id=b.app.id, enabled=True)
    b.db.add(ca)
    await b.db.flush()
    b.db.add(PartnerInstallation(id=ca.id, company_id=b.other.id, client_id=b.client.id,
        approved=True, scopes=sorted(SCOPES), all_locations=True))
    await b.db.flush()
    b.db.add(PartnerResourceScope(installation_id=ca.id, kind="objects", mode="SET"))
    await b.db.flush()
    b.db.add_all([
        PartnerResourceItem(installation_id=ca.id, kind="objects", object_id=b.foreign["objects"].id),
        PartnerResourceItem(installation_id=b.installation.id, kind="equipment", equipment_id=b.foreign["equipment"].id),
    ])
    await b.db.commit()
    value = await verify(b)
    assert value.resource_scopes["objects"].ids == frozenset(row.id for row in b.data["objects"])
    assert value.resource_scopes["equipment"].mode == "ALL"


@pytest.mark.parametrize("loader_name", ["baseline", "batch"])
async def test_typed_items_are_current_despite_held_orm_row(budget, loaders, monkeypatch, loader_name):
    b = budget
    await profiles(b, set_count=5)
    monkeypatch.setattr(identity, "resource_scopes", loaders[loader_name])
    async with b.factory() as session:
        item = await session.scalar(select(PartnerResourceItem).where(
            PartnerResourceItem.installation_id == b.installation.id, PartnerResourceItem.kind == "equipment"))
        await identity.verify_partner_access_token(b.raw, session)
        writer_item = await b.db.get(PartnerResourceItem, item.id)
        writer_item.equipment_id = b.foreign["equipment"].id
        await b.db.commit()
        # A cached ORM item still contains the old ID; SQL columns must win.
        assert item.equipment_id != writer_item.equipment_id
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as denied:
            await identity.verify_partner_access_token(b.raw, session)
        assert denied.value.status_code == 401


@pytest.mark.parametrize("loader_name", ["baseline", "batch"])
async def test_protocol_revoke_still_denies_next_product_request(budget, loaders, monkeypatch, loader_name):
    from app.main import app
    b = budget
    await profiles(b)
    monkeypatch.setattr(identity, "resource_scopes", loaders[loader_name])
    assert (await b.http.get("/objects")).status_code == 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as core:
        response = await core.post("/api/oauth2/revoke", data={"token": b.raw}, auth=(b.client.id, b.secret))
    assert response.status_code == 200, response.text
    assert (await b.http.get("/objects")).status_code == 401
