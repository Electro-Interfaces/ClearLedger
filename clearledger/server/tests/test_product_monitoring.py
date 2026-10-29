"""Opt-in HTTP/SQL acceptance: real M10 issuance, no verifier/response overrides.

Only synthetic fixtures. This module guards destructive conftest setup before
any database fixture is requested; it is portable to loopback or CI PostgreSQL.
"""
import base64
from datetime import datetime, timedelta
import os
from urllib.parse import parse_qs, urlsplit
import uuid

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_MONITORING_SQL_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(FLAG + "=1 is required", allow_module_level=True)
_error = partner_test_safety_error(os.environ, flag=FLAG)
if _error:
    raise pytest.UsageError("Refusing monitoring database: " + _error)

from app.auth import hash_password
from app.api_contracts import policy_registry
from app.database import get_db
from app.models import (ChargeSession, Company, CompanyRole, Contract, ContractLocation,
                        Counterparty, Organization, ServiceLocation, User, UserCompany)
from app.models_partner import (PartnerClient, PartnerGrant, PartnerInstallation,
    PartnerResourceScope, PartnerTokenFamily)
from app.product_api import create_product_api
from app.routers import auth_router, partner_admin_router, partner_oauth_router
from app.services import partner_identity as identity, notify
from app.services.ops_monitor_context import visit_summary
from tests.conftest import _test_session_factory, _test_engine

pytestmark = pytest.mark.asyncio(loop_scope="session")
ORIGIN = "https://monitoring.example.test"
REDIRECT = "https://synthetic-partner.example/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
BUSINESS = ["objects:read", "monitoring:read"]


@pytest.fixture(scope="module")
def signing_key():
    return base64.b64encode(rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode()


async def registration(env, *, machine=False, scopes=None, mode="SET"):
    scopes = scopes if scopes is not None else BUSINESS + ([] if machine else ["openid"])
    ac, core = env["client"], env["core"]
    response = await ac.post("/api/developer/clients", headers=core, json={
        "companyId": str(env["company"].id), "name": "Synthetic monitoring consumer",
        "redirectUris": [REDIRECT], "scopes": scopes,
        "authMethod": "client_secret_basic" if machine else "none"})
    assert response.status_code == 201, response.text
    client_id = response.json()["clientId"]
    response = await ac.post(f"/api/developer/clients/{client_id}/status", headers=core, json={"enabled": True})
    assert response.status_code == 200, response.text
    secret = None
    if machine:
        response = await ac.post(f"/api/developer/clients/{client_id}/credentials", headers=core)
        assert response.status_code == 201, response.text
        secret = response.json()["clientSecret"]
    response = await ac.post(f"/api/developer/clients/{client_id}/installations", headers=core, json={
        "companyId": str(env["company"].id), "scopes": scopes, "locationIds": None,
        "resourceScopes": {"objects": {"mode": mode, "ids": [v.id for v in env["points"][:2]] if mode == "SET" else []}}})
    assert response.status_code == 201, response.text
    return dict(client_id=client_id, installation_id=uuid.UUID(response.json()["installationId"]), secret=secret, scopes=scopes)


async def issue(env, registration, *, machine=False):
    ac, scopes = env["client"], registration["scopes"]
    if machine:
        response = await ac.post(f'/api/developer/installations/{registration["installation_id"]}/machine-grants',
            headers=env["core"], json={"scopes": scopes})
        assert response.status_code == 201, response.text
        form = {"grant_type": "client_credentials", "grant_id": response.json()["grantId"], "scope": " ".join(scopes)}
        response = await ac.post("/api/oauth2/token", data=form, auth=(registration["client_id"], registration["secret"]))
    else:
        state = uuid.uuid4().hex
        response = await ac.get("/api/oauth2/authorize", params={"response_type": "code", "client_id": registration["client_id"],
            "redirect_uri": REDIRECT, "scope": " ".join(scopes), "state": state, "nonce": "nonce-" + state,
            "code_challenge": CHALLENGE, "code_challenge_method": "S256"})
        assert response.status_code == 302, response.text
        rid = parse_qs(urlsplit(response.headers["location"]).query)["requestId"][0]
        response = await ac.get(f"/api/developer/authorization-requests/{rid}", headers=env["core"])
        assert response.status_code == 200, response.text
        response = await ac.post(f"/api/developer/authorization-requests/{rid}/approve", headers=env["core"],
            json={"companyId": str(env["company"].id), "scopes": scopes})
        assert response.status_code == 200, response.text
        callback = parse_qs(urlsplit(response.json()["redirectUrl"]).query)
        assert callback["state"] == [state]
        response = await ac.post("/api/oauth2/token", data={"grant_type": "authorization_code",
            "client_id": registration["client_id"], "redirect_uri": REDIRECT,
            "code": callback["code"][0], "code_verifier": VERIFIER})
    assert response.status_code == 200, response.text
    return response.json()


@pytest_asyncio.fixture(loop_scope="session")
async def env(db, monkeypatch, signing_key):
    assert partner_test_safety_error(os.environ, flag=FLAG) is None
    for key, value in {"partner_oauth_enabled": True, "partner_api_enabled": True,
        "partner_oauth_issuer": ORIGIN, "partner_oauth_audience": "urn:monitoring:synthetic",
        "partner_oauth_signing_key": signing_key, "sso_signing_key": signing_key}.items():
        monkeypatch.setattr(identity.settings, key, value)
    # External delivery is outside this acceptance. All auth/API responses stay real.
    async def no_email(*args, **kwargs): pass
    monkeypatch.setattr(auth_router.email_service, "send_notice", no_email)
    monkeypatch.setattr(notify, "dispatch_async", lambda *args, **kwargs: None)
    partner_oauth_router._hits.clear()
    suffix = uuid.uuid4().hex[:12]
    companies = [Company(name=f"Synthetic monitoring {i}", slug=f"monitor-{suffix}-{i}", profile_id="energy") for i in range(2)]
    db.add_all(companies); await db.flush()
    company, foreign = companies
    password = "Synthetic-Monitor-2026!"
    user = User(company_id=company.id, name="Synthetic user", email=suffix + "@example.com",
                password_hash=hash_password(password), is_superadmin=False, role="user")
    db.add(user); await db.flush()
    member = UserCompany(user_id=user.id, company_id=company.id, role="admin")
    db.add(member)
    points = [ServiceLocation(id=f"mon-{suffix}-{i}", company_id=company.id, code=f"M-{i}", name=f"Synthetic point {i}",
        type="ev_charging", operational_status="working", extra_metadata={"private": "NEVER-RAW"}) for i in range(4)]
    alien = ServiceLocation(id=f"alien-{suffix}", company_id=foreign.id, code="ALIEN", name="Foreign point")
    db.add_all([*points, alien]); await db.flush()
    # Four attempts, three visits, two successful visits, raw energy 1.5 kWh.
    attempts = [(points[0], datetime(2026, 10, 16, 10), "visit-a", 0),
        (points[0], datetime(2026, 10, 16, 10, 1), "visit-a", 1.25),
        (points[0], datetime(2026, 10, 16, 11), "visit-b", 0),
        (points[0], datetime(2026, 10, 17, 12), None, .25),
        (points[1], datetime(2026, 10, 18, 12), "other", 20),
        (points[2], datetime(2030, 1, 1), "outside", 500),
        (alien, datetime(2040, 1, 1), "foreign", 999)]
    for i, (point, at, visit, energy) in enumerate(attempts):
        db.add(ChargeSession(company_id=point.company_id, session_ext_id=f"synthetic-{suffix}-{i}", location_id=point.id,
            started_at=at, visit_key=visit, energy_kwh=energy, user_id="NEVER-PHONE", amount=987654,
            result="CompleteError"))
    await db.commit()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_exception_handler(identity.PartnerProblem, identity.problem_handler)
    for router in (auth_router.router, partner_admin_router.router, partner_oauth_router.router, partner_oauth_router.consent_router):
        app.include_router(router, prefix="/api")
    async def database():
        async with _test_session_factory() as session:
            yield session
    app.dependency_overrides[get_db] = database
    product = create_product_api(session_factory=_test_session_factory, enabled=True, issuer=ORIGIN)
    policy_registry(product); app.mount("/api/v1", product)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as ac:
        response = await ac.post("/api/auth/login", json={"email": user.email, "password": password})
        assert response.status_code == 200, response.text
        core = {"Authorization": "Bearer " + response.json()["access_token"]}
        result = dict(client=ac, db=db, company=company, foreign_company=foreign, user=user, member=member,
            points=points, alien=alien, core=core, app=app, product=product)
        reg = await registration(result)
        tokens = await issue(result, reg)
        result.update(reg=reg, tokens=tokens, headers={"Authorization": "Bearer " + tokens["access_token"]})
        yield result


async def read(env, point=0, headers=None, **params):
    identifier = env["points"][point].id if isinstance(point, int) else point
    return await env["client"].get(f"/api/v1/objects/{identifier}/monitoring", params=params,
                                  headers=env["headers"] if headers is None else headers)


async def test_real_pkce_status_aggregate_boundary_and_no_pii_or_dml(env):
    statements = []
    def capture(conn, cursor, statement, *args): statements.append(statement)
    event.listen(_test_engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await read(env, days=2)
        again = await read(env, days=2)
    finally:
        event.remove(_test_engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == again.status_code == 200, response.text
    value = response.json()
    assert value["totals"] == {"sessions": 4, "visits": 3, "successfulVisits": 2, "unsuccessfulVisits": 1, "energyKwh": 1.5}
    assert value["provenance"]["dataThrough"] == "2026-10-17T12:00:00+03:00"
    assert value["window"]["start"] == "2026-10-15T12:00:00+03:00"
    assert response.headers["cache-control"] == "no-store" and response.headers["x-request-id"]
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER")) for s in statements)
    assert not any(secret in response.text for secret in ("NEVER-PHONE", "NEVER-RAW", "987654", "userId", "revenue", "ticket", "amount", "statusRaw"))
    assert set(value) == {"pointId", "status", "window", "totals", "lastSeenAt", "provenance"}


async def test_historical_msk_window_round_after_sum_and_last_seen(env):
    response = await read(env, days=2, asOf="2026-10-16")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["window"]["end"] == "2026-10-16T23:59:59.999999+03:00"
    assert data["provenance"]["asOf"] == data["window"]["end"]
    assert data["provenance"]["dataThrough"] == "2026-10-17T12:00:00+03:00"
    assert data["totals"] == {"sessions": 3, "visits": 2, "successfulVisits": 1, "unsuccessfulVisits": 1, "energyKwh": 1.3}
    assert data["lastSeenAt"] == "2026-10-16T11:00:00+03:00"
    before = (await read(env, asOf="2026-10-15")).json()
    assert before["lastSeenAt"] is None and before["totals"]["visits"] == 0


async def test_unknown_and_no_data_are_honest(env):
    env["points"][1].operational_status = "future_vendor_state"
    await env["db"].commit()
    assert (await read(env, 1)).json()["status"] == "unknown"
    # A separate, explicitly approved ALL installation covers the empty point.
    reg = await registration(env, mode="ALL")
    token = await issue(env, reg)
    empty = await read(env, 3, headers={"Authorization": "Bearer " + token["access_token"]})
    assert empty.status_code == 200, empty.text
    assert empty.json()["provenance"]["dataThrough"] is None
    assert empty.json()["provenance"]["dataLagHours"] is None
    assert empty.json()["lastSeenAt"] is None
    assert empty.json()["totals"]["sessions"] == 0


@pytest.mark.parametrize("point", [2, "alien", "missing"])
async def test_forbidden_objects_404_without_session_reads(env, point):
    if point == "alien": point = env["alien"].id
    statements = []
    def capture(conn, cursor, statement, *args): statements.append(statement)
    event.listen(_test_engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await read(env, point)
    finally:
        event.remove(_test_engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 404, response.text
    assert not any("charge_sessions" in statement for statement in statements)


@pytest.mark.parametrize("params", [{"days": 0}, {"days": 367}, {"asOf": "20261016"}, {"asOf": "2026-10-16T00:00:00Z"},
    {"asOf": "2026-02-30"}, {"cursor": "opaque"}, {"q": "any"}, {"companyId": "foreign"}, {"locationIds": "any"}])
async def test_strict_parameters(env, params):
    response = await read(env, **params)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("kind", ["none", "core", "id_token", "query", "sso"])
async def test_no_core_sso_or_query_bearer(env, kind):
    headers = {"Authorization": "Bearer " + env["tokens"]["id_token"]} if kind == "id_token" else env["core"] if kind == "core" else {}
    if kind == "sso":
        from app.services.sso import sign_sso_token
        token = sign_sso_token(user=env["user"], company_id=env["company"].id, companies=[], aud="support")
        headers = {"Authorization": "Bearer " + token}
    params = {"access_token": env["tokens"]["access_token"]} if kind == "query" else {}
    response = await read(env, headers=headers, **params)
    assert response.status_code == 401, response.text


@pytest.mark.parametrize("target", ["client", "installation", "grant", "role", "membership", "account", "family"])
async def test_live_revocation_closes_existing_token(env, target):
    assert (await read(env)).status_code == 200
    db = env["db"]
    if target == "client":
        (await db.get(PartnerClient, env["reg"]["client_id"])).enabled = False
    elif target == "installation":
        (await db.get(PartnerInstallation, env["reg"]["installation_id"])).approved = False
    elif target == "grant":
        grant = await db.scalar(select(PartnerGrant).where(PartnerGrant.client_id == env["reg"]["client_id"]))
        grant.approved = False
    elif target == "role":
        role = CompanyRole(company_id=env["company"].id, name="Synthetic revoked role", modules=["equipment", "ops:ops_overview"])
        db.add(role); await db.flush()
        env["member"].role, env["member"].role_id = "user", role.id
    elif target == "membership":
        await db.delete(env["member"])
    elif target == "account":
        env["user"].token_version += 1
    else:
        family = await db.scalar(select(PartnerTokenFamily).join(PartnerGrant).where(PartnerGrant.client_id == env["reg"]["client_id"]))
        family.revoked = True
    await db.commit()
    assert (await read(env)).status_code == 401


async def test_member_object_scope_and_own_org_are_current(env):
    db = env["db"]
    env["member"].object_scope = [env["points"][1].id]
    await db.commit()
    assert (await read(env)).status_code == 404
    assert (await read(env, 1)).status_code == 200
    env["member"].object_scope = None
    org = Organization(company_id=env["company"].id, name="Synthetic own org", inn="0000000000")
    party = Counterparty(company_id=env["company"].id, name="Synthetic party")
    db.add_all([org, party]); await db.flush()
    contract = Contract(company_id=env["company"].id, number="MONITOR", date="2026-10-01", type="service",
        organization_id=org.id, counterparty_id=party.id, scope_type="locations")
    db.add(contract); await db.flush()
    db.add(ContractLocation(company_id=env["company"].id, contract_id=contract.id, location_id=env["points"][1].id))
    env["member"].own_organization_id = org.id
    await db.commit()
    assert (await read(env)).status_code == 404
    assert (await read(env, 1)).status_code == 200


async def test_independent_machine_is_approved_and_not_a_core_user(env):
    reg = await registration(env, machine=True)
    token = await issue(env, reg, machine=True)
    headers = {"Authorization": "Bearer " + token["access_token"]}
    # Machine remains independent of the registering administrator account.
    env["user"].token_version += 1
    await env["db"].commit()
    assert (await read(env, headers=headers)).status_code == 200
    assert (await read(env, 2, headers=headers)).status_code == 404
    assert "id_token" not in token
    (await env["db"].get(PartnerInstallation, reg["installation_id"])).approved = False
    await env["db"].commit()
    assert (await read(env, headers=headers)).status_code == 401


@pytest.mark.parametrize("scopes", [["openid", "objects:read"], ["openid", "monitoring:read"]])
async def test_both_scopes_explicit_and_old_grants_not_expanded(env, scopes):
    reg = await registration(env, scopes=scopes)
    token = await issue(env, reg)
    response = await read(env, headers={"Authorization": "Bearer " + token["access_token"]})
    assert response.status_code == 403, response.text
    row = await env["db"].get(PartnerClient, reg["client_id"])
    assert set(row.allowed_scopes) == set(scopes)
    install = await env["db"].get(PartnerInstallation, reg["installation_id"])
    assert set(install.scopes) == set(scopes)
    grant = await env["db"].scalar(select(PartnerGrant).where(PartnerGrant.client_id == reg["client_id"]))
    assert set(grant.scopes) == set(scopes)


async def test_empty_objects_denied_and_non_energy_404(env):
    scope = await env["db"].get(PartnerResourceScope, (env["reg"]["installation_id"], "objects"))
    scope.mode = "EMPTY"
    await env["db"].commit()
    assert (await read(env)).status_code == 403
    scope.mode = "SET"
    env["company"].profile_id = "fuel"
    await env["db"].commit()
    assert (await read(env)).status_code == 404


async def test_foreign_ungranted_boundary_has_no_influence_and_old_helper_unchanged(env):
    before = (await read(env)).json()
    db, company = env["db"], env["company"]
    db.add(ChargeSession(company_id=company.id, session_ext_id="future-" + uuid.uuid4().hex, location_id=env["points"][2].id,
        started_at=datetime(2050, 1, 1), visit_key="visit-a", energy_kwh=9999))
    await db.commit()
    after = (await read(env)).json()
    assert before == after
    start, end = datetime(2026, 1, 1), datetime(2051, 1, 1)
    native = await visit_summary(db, company.id, start, end)
    assert set(native) == {p.id for p in env["points"][:3]}
    selected = await visit_summary(db, company.id, start, end, location_ids={env["points"][0].id})
    assert set(selected) == {env["points"][0].id}
    assert selected[env["points"][0].id] == native[env["points"][0].id]
    assert await visit_summary(db, company.id, start, end, location_ids=set()) == {}
    native_again = await visit_summary(db, company.id, start, end)
    assert native == native_again
