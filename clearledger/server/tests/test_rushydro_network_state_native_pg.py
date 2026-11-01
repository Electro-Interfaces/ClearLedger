"""Network-state native acceptance AUTHORSHIP ONLY: NOT COLLECTED / NOT RUN.

Root's external --noconftest plugin owns schema, actual factory and disposal.
Admission MUST precede every app/fixture/helper import. No positive auth, SQL,
session or business-response mock is used; only the domain clock is fixed.
"""
import os
from urllib.parse import urlsplit

import pytest

if os.environ.get("RUN_RUSHYDRO_NETWORK_SQL_TESTS") != "1":
    pytest.skip("Explicit network SQL admission required", allow_module_level=True)
if os.environ.get("RUN_RUSHYDRO_PRODUCT_READS_TESTS") != "1":
    raise pytest.UsageError("Native READ admission also required")
from tests.partner_test_safety import partner_test_safety_error
if partner_test_safety_error(os.environ, flag="RUN_RUSHYDRO_NETWORK_SQL_TESTS"):
    raise pytest.UsageError("Network pre-import safety refused")
_target = urlsplit(os.environ["TEST_DATABASE_URL"])
if (os.environ.get("ROOT_APPROVED_RUSHYDRO_PRODUCT_READS") != "1"
        or os.environ.get("APP_ENV") != "test"
        or os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL")
        or (_target.hostname, _target.port, _target.path, _target.username) != (
            "127.0.0.1", 5432, "/api_rushydro_reads25_test_20261101", "clearledger")):
    raise pytest.UsageError("Exact Root-owned network SQL target required")

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import delete, event, select, text, update

from app.models import ChargeSession, ContractLocation, ServiceLocation, UserCompany
from app.models_partner import (PartnerClient, PartnerCredential, PartnerGrant,
    PartnerInstallation, PartnerResourceScope, PartnerToken,
    PartnerTokenFamily)
from app.services import partner_identity as identity
from app.services import ops_monitor_context
from tests.test_rushydro_product_reads_native_pg import read_world, wire, bearer

pytestmark = pytest.mark.asyncio(loop_scope="session")
PATH = "/api/v1/monitoring/network-state"
O1, O2, OF = "Учебная Ё O1", "Скрытая Ё O2", "Чужая Ё O3"
SCOPES = ["objects:read", "monitoring:read"]
NOW = datetime(2026, 11, 1, 10, tzinfo=timezone(timedelta(hours=3)))
COUNTS = {"working": 1, "no_link": 0, "disabled": 0, "decommissioned": 0,
          "on_repair": 0, "maintenance": 0, "not_working": 0, "unknown": 0}
# Finite named groups; parameter variants are counted from AST in the handoff.
CASE_MATRIX = [
    "NS01-user-golden-current-asOf", "NS02-approved-service-two-scopes",
    "NS03-hidden-foreign-org-watermark", "NS04-empty-None-boundary",
    "NS05-independent-authority-denials", "NS06-money-invariance",
    "NS07-region-types-status-fallback", "NS08-exact-ID-pages",
    "NS09-cursor-bindings-revocation", "NS10-cap-before-owner-region",
    "NS11-timeout-local-reset-cancel", "NS12-strict-request",
]


@asynccontextmanager
async def changed(w, model, key, **values):
    """Real committed fixture DML, restored after each scenario, including FAIL."""
    async with w.factory() as db:
        row = await db.get(model, key)
        assert row is not None
        original = {name: deepcopy(getattr(row, name)) for name in values}
        for name, value in values.items():
            setattr(row, name, value)
        await db.commit()
    try:
        yield
    finally:
        async with w.factory() as db:
            row = await db.get(model, key)
            for name, value in original.items():
                setattr(row, name, value)
            await db.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def network_world(read_world, monkeypatch):
    w = read_world

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    # Only domain time; verifier/issuer clocks and real DB/HTTP stay untouched.
    monkeypatch.setattr(ops_monitor_context, "datetime", FixedClock)
    async with changed(w, ServiceLocation, O1, owner="РусГидро", is_test=False,
                       operational_status="working", extra_metadata={"federalSubject": "R1"}):
        async with w.factory() as db:
            original = (await db.execute(select(ChargeSession.id, ChargeSession.started_at).where(
                ChargeSession.company_id == w.companies[0], ChargeSession.location_id == O1)
                .order_by(ChargeSession.started_at))).all()
            assert len(original) == 4
            stamps = [datetime(2026, 10, 20, 10), datetime(2026, 10, 20, 10),
                      datetime(2026, 10, 30, 10), datetime(2026, 10, 31, 10)]
            for (identifier, _), stamp in zip(original, stamps):
                await db.execute(update(ChargeSession).where(ChargeSession.id == identifier).values(started_at=stamp))
            await db.commit()
        try:
            yield w
        finally:
            async with w.factory() as db:
                for identifier, stamp in original:
                    await db.execute(update(ChargeSession).where(ChargeSession.id == identifier).values(started_at=stamp))
                await db.commit()


async def get(w, params=None, headers=None, **kwargs):
    return await wire(w, "GET", PATH, headers=w.user_headers if headers is None else headers,
                      params=params, **kwargs)


def data(response):
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]
    value = response.json()
    assert set(value) == {"items", "summary", "context", "nextCursor"}
    for item in value["items"]:
        assert set(item) == {"objectId", "status", "lastChargeAt", "silentDays", "mismatch"}
    assert set(value["summary"]) == {"stations", "mismatch", "byStatus"}
    assert set(value["summary"]["byStatus"]) == set(COUNTS)
    assert set(value["context"]) == {"asOf", "dataThrough", "dataLagHours", "requestedDate",
                                     "catalogMode", "boundaryScope", "availability"}
    return value


def problem(response, status, code):
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    value = response.json()
    assert value["code"] == code and value["status"] == status
    assert response.headers["cache-control"] == "no-store"
    assert value["requestId"] == response.headers["x-request-id"]
    if status in (401, 403):
        assert response.headers["www-authenticate"].startswith("Bearer ")


@asynccontextmanager
async def trace(w):
    """Observe actual driver SQL and settings, never replace results or Session."""
    async with w.factory() as db:
        engine = db.bind.sync_engine
    records, local_settings = [], []

    def before(connection, cursor, statement, parameters, context, many):
        records.append((statement, parameters))
        if "LIMIT" in statement and "service_locations" in statement:
            cursor.execute("SELECT current_setting('statement_timeout'), current_setting('transaction_read_only')")
            local_settings.append(cursor.fetchone())

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield records, local_settings
    finally:
        event.remove(engine, "before_cursor_execute", before)


async def test_NS01_user_golden_current_and_asof(network_world):
    w = network_world
    async with trace(w) as (records, settings):
        current = data(await get(w))
    assert current == {
        "items": [{"objectId": O1, "status": "working", "lastChargeAt": "2026-10-20T10:00:00+03:00",
                   "silentDays": 11, "mismatch": True}],
        "summary": {"stations": 1, "mismatch": 1, "byStatus": COUNTS}, "nextCursor": None,
        "context": {"asOf": "2026-10-31T10:00:00+03:00", "dataThrough": "2026-10-31T10:00:00+03:00",
                    "dataLagHours": 24.0, "requestedDate": None, "catalogMode": "current",
                    "boundaryScope": "authorizedOperatedRegion", "availability": "observed"}}
    assert settings == [("5s", "on")]
    session_sql = [sql for sql, _ in records if "charge_sessions" in sql]
    assert len(session_sql) == 2
    assert all("company_id" in sql and "location_id IN" in sql and "max(" in sql.lower() for sql in session_sql)
    assert all(word not in " ".join(session_sql) for word in ("amount", "visit_key", "sum(", "user_id"))
    assert all(O1 in args and O2 not in args and OF not in args
               for sql, args in records if "charge_sessions" in sql)
    historical = data(await get(w, {"asOf": "2026-10-25"}))
    assert historical["items"][0]["silentDays"] == 5
    assert historical["items"][0]["mismatch"] is False
    assert historical["context"] == current["context"] | {
        "asOf": "2026-10-25T23:59:59.999999+03:00", "requestedDate": "2026-10-25"}
    # asOfUTC in TARGET is an auxiliary conversion oracle, never a DTO field.
    assert "asOfUTC" not in historical["context"]
    async with changed(w, ServiceLocation, O1, operational_status="no_link"):
        assert data(await get(w, {"asOf": "2026-10-25"}))["items"][0]["status"] == "no_link"


@asynccontextmanager
async def machine(w, scopes=SCOPES):
    """Actual SQL credential/grant ceilings and actual Authlib client_credentials."""
    secret, credential_id = uuid4().hex + uuid4().hex, uuid4()
    async with changed(w, PartnerClient, w.clients[1], allowed_scopes=list(SCOPES)):
        async with changed(w, PartnerInstallation, w.installations[1], scopes=list(SCOPES)):
            async with changed(w, PartnerGrant, w.machine_grant, scopes=list(SCOPES)):
                async with w.factory() as db:
                    db.add(PartnerCredential(id=credential_id, client_id=w.clients[1],
                        secret_hash=identity.digest(secret), enabled=True,
                        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
                    await db.commit()
                try:
                    response = await wire(w, "POST", "/api/oauth2/token", auth=(w.clients[1], secret), data={
                        "grant_type": "client_credentials", "grant_id": str(w.machine_grant), "scope": " ".join(scopes)})
                    assert response.status_code == 200
                    payload = response.json()
                    assert set(payload["scope"].split()) == set(scopes) and "id_token" not in payload
                    async with w.factory() as db:
                        token = await db.scalar(select(PartnerToken).where(
                            PartnerToken.access_hash == identity.digest(payload["access_token"])))
                        assert token is not None
                        family = await db.get(PartnerTokenFamily, token.family_id)
                        grant = await db.get(PartnerGrant, family.grant_id)
                        assert family.credential_id == credential_id
                        assert grant.approved and grant.kind == "machine" and grant.user_id is None
                    yield bearer(payload["access_token"])
                finally:
                    async with w.factory() as db:
                        row = await db.get(PartnerCredential, credential_id)
                        row.enabled = False
                        await db.commit()


async def test_NS02_approved_service(network_world):
    w = network_world
    async with machine(w) as headers:
        value = data(await get(w, headers=headers))
        assert {item["objectId"] for item in value["items"]} == {O1, O2}
        assert value["summary"]["stations"] == 2
        assert value["context"]["dataThrough"] == "2030-01-01T00:00:00+03:00"


async def test_NS03_hidden_foreign_org_invariance(network_world):
    w = network_world
    # Remove the seed's second link of O2 to allowed org C1: now O2 is G9-only.
    async with w.factory() as db:
        link = await db.scalar(select(ContractLocation).where(
            ContractLocation.company_id == w.companies[0],
            ContractLocation.contract_id == UUID("50000000-0000-4000-8000-000000000001"),
            ContractLocation.location_id == O2))
        old_link = {c.name: getattr(link, c.name) for c in ContractLocation.__table__.columns}
        await db.delete(link)
        await db.commit()
    try:
        async with changed(w, UserCompany, (w.user, w.companies[0]), object_scope=[O1, O2]):
            baseline = data(await get(w))
            async with changed(w, ServiceLocation, O2, operational_status="no_link", extra_metadata={"federalSubject": "R9"}):
                async with changed(w, ServiceLocation, OF, operational_status="disabled"):
                    async with w.factory() as db:
                        rows = (await db.scalars(select(ChargeSession).where(ChargeSession.location_id.in_([O2, OF])))).all()
                        old = [(r.id, r.started_at, r.amount) for r in rows]
                        for row in rows:
                            row.started_at = datetime(2090, 1, 1)
                            row.amount = Decimal("99999999")
                        await db.commit()
                    try:
                        assert data(await get(w)) == baseline
                        assert [item["objectId"] for item in baseline["items"]] == [O1]
                    finally:
                        async with w.factory() as db:
                            for identifier, stamp, amount in old:
                                await db.execute(update(ChargeSession).where(ChargeSession.id == identifier)
                                                 .values(started_at=stamp, amount=amount))
                            await db.commit()
    finally:
        async with w.factory() as db:
            db.add(ContractLocation(**old_link))
            await db.commit()


@pytest.mark.parametrize("variant", ["member-empty", "owner-empty", "network-empty", "region-empty", "no-observation"])
async def test_NS04_empty_and_none_boundary(network_world, variant):
    w = network_world
    if variant == "no-observation":
        async with w.factory() as db:
            old = (await db.execute(select(ChargeSession.id, ChargeSession.location_id).where(
                ChargeSession.company_id == w.companies[0], ChargeSession.location_id == O1))).all()
            await db.execute(update(ChargeSession).where(ChargeSession.id.in_([r.id for r in old])).values(location_id=None))
            await db.commit()
        try:
            value = data(await get(w))
            assert value["items"] == [{"objectId": O1, "status": "working", "lastChargeAt": None,
                                       "silentDays": None, "mismatch": True}]
        finally:
            async with w.factory() as db:
                for identifier, location in old:
                    await db.execute(update(ChargeSession).where(ChargeSession.id == identifier).values(location_id=location))
                await db.commit()
    elif variant == "member-empty":
        # BASE live_grant tests object_scope truthiness; [] does not narrow the
        # typed SET there. access.resolve independently applies is-not-None,
        # giving Facts.objects=EMPTY and an admitted SQL-empty selector here.
        async with changed(w, UserCompany, (w.user, w.companies[0]), object_scope=[]):
            value = data(await get(w))
        assert value["items"] == []
    elif variant == "owner-empty":
        async with changed(w, ServiceLocation, O1, owner="СНК"):
            value = data(await get(w))
        assert value["items"] == []
    elif variant == "network-empty":
        async with changed(w, ServiceLocation, O1, operational_status="decommissioned"):
            value = data(await get(w))
        assert value["items"] == []
    else:
        value = data(await get(w, {"region": "R2"}))
        assert value["items"] == []
    assert value["context"] == {"asOf": "2026-11-01T10:00:00+03:00", "dataThrough": None,
        "dataLagHours": None, "requestedDate": None, "catalogMode": "current",
        "boundaryScope": "authorizedOperatedRegion", "availability": "unknown"}
    assert value["summary"]["stations"] == (1 if variant == "no-observation" else 0)


@pytest.mark.parametrize("missing", ["monitoring:read", "objects:read", "resource", "grant", "membership"])
async def test_NS05_independent_denials(network_world, missing):
    w = network_world
    if missing in SCOPES:
        async with machine(w, [scope for scope in SCOPES if scope != missing]) as headers:
            async with trace(w) as (records, _):
                response = await get(w, headers=headers)
            problem(response, 403, "access_denied")
    elif missing == "resource":
        async with changed(w, PartnerResourceScope, (w.installations[0], "objects"), mode="EMPTY"):
            async with trace(w) as (records, _):
                response = await get(w)
            problem(response, 403, "access_denied")
    elif missing == "grant":
        async with machine(w) as headers:
            async with changed(w, PartnerGrant, w.machine_grant, approved=False):
                async with trace(w) as (records, _):
                    response = await get(w, headers=headers)
                problem(response, 401, "invalid_credentials")
                assert 'error="invalid_token"' in response.headers["www-authenticate"]
    else:
        async with w.factory() as db:
            row = await db.get(UserCompany, (w.user, w.companies[0]))
            original = {c.name: getattr(row, c.name) for c in UserCompany.__table__.columns}
            await db.delete(row)
            await db.commit()
        try:
            async with trace(w) as (records, _):
                response = await get(w)
            problem(response, 401, "invalid_credentials")
            assert 'error="invalid_token"' in response.headers["www-authenticate"]
        finally:
            async with w.factory() as db:
                db.add(UserCompany(**original))
                await db.commit()
    assert not any("charge_sessions" in sql for sql, _ in records)


async def test_NS06_money_invariance(network_world):
    w = network_world
    async with machine(w) as headers:
        for status in ("working", "no_link"):
            async with changed(w, ServiceLocation, O1, operational_status=status):
                async with w.factory() as db:
                    old = (await db.execute(select(ChargeSession.id, ChargeSession.amount, ChargeSession.client_amount).where(
                        ChargeSession.company_id == w.companies[0], ChargeSession.location_id.in_([O1, O2])))).all()
                    await db.execute(update(ChargeSession).where(ChargeSession.id.in_([r.id for r in old]))
                                     .values(amount=0, client_amount=0))
                    await db.commit()
                try:
                    requests = [{"onlyProblems": "true"}, {"onlyProblems": "false"}, {"pageSize": 1}]
                    before = [data(await get(w, params, headers)) for params in requests]
                    assert [item["objectId"] for item in before[1]["items"]] == [O2, O1]
                    assert before[2]["nextCursor"] is not None
                    async with w.factory() as db:
                        await db.execute(update(ChargeSession).where(ChargeSession.id.in_([r.id for r in old]))
                                         .values(amount=99999999, client_amount=99999999))
                        await db.commit()
                    for params, expected in zip(requests, before):
                        assert data(await get(w, params, headers)) == expected
                    assert before[0]["summary"]["stations"] == (1 if status == "working" else 0)
                finally:
                    async with w.factory() as db:
                        for identifier, amount, client_amount in old:
                            await db.execute(update(ChargeSession).where(ChargeSession.id == identifier)
                                             .values(amount=amount, client_amount=client_amount))
                        await db.commit()


@pytest.mark.parametrize("fallback", [{"private": "R1"}, ["R1"], 7, None, "R1", "R" * 200 + "private" * 10000])
async def test_NS07_nonstring_region_and_unknown_status(network_world, fallback):
    w = network_world
    async with changed(w, ServiceLocation, O1, operational_status="private-unrecognized",
                       extra_metadata={"federalSubject": fallback}):
        selection = "R" * 200 if isinstance(fallback, str) and len(fallback) > 200 else "R1"
        value = data(await get(w, {"region": selection}))
        assert len(value["items"]) == (1 if fallback == "R1" else 0)
        value = data(await get(w))
        assert value["items"][0]["status"] == "unknown" and value["items"][0]["mismatch"] is False


@asynccontextmanager
async def added_network(w, identifiers, *, owner="РусГидро", observed=True):
    """Only owned synthetic rows; no DDL, provider, fabricated SQL or auth result."""
    ids = list(identifiers)
    async with w.factory() as db:
        db.add_all([ServiceLocation(id=identifier, company_id=w.companies[0],
            code="NS-" + uuid4().hex, name="Учебная станция NS", type="ev_charging",
            status="active", operational_status="working", is_test=False, owner=owner,
            extra_metadata={"federalSubject": "R-PAGE"}) for identifier in ids])
        await db.flush()
        if observed:
            db.add_all([ChargeSession(company_id=w.companies[0], location_id=identifier,
                session_ext_id="ns-" + uuid4().hex, started_at=datetime(2026, 10, 31, 10),
                energy_kwh=Decimal("1"), amount=0) for identifier in ids])
        await db.commit()
    try:
        yield ids
    finally:
        async with w.factory() as db:
            await db.execute(delete(ChargeSession).where(ChargeSession.company_id == w.companies[0],
                                                        ChargeSession.location_id.in_(ids)))
            await db.execute(delete(ServiceLocation).where(ServiceLocation.company_id == w.companies[0],
                                                          ServiceLocation.id.in_(ids)))
            await db.commit()


@pytest.mark.parametrize("observed", [True, False])
async def test_NS08_exact_unicode_multipage(network_world, observed, monkeypatch):
    w = network_world
    # Literal UTF-8/C order; leading space, case and NFC/NFD remain distinct.
    expected = [" a", "A", "a", "e\u0301", "é"]
    async with machine(w) as headers:
        async with changed(w, PartnerResourceScope, (w.installations[1], "objects"), mode="ALL"):
            async with added_network(w, reversed(expected), observed=observed):
                params = {"region": "R-PAGE", "pageSize": 2}
                seen, summary = [], None
                for _ in range(3):
                    value = data(await get(w, params, headers))
                    if summary is None:
                        summary = value["summary"]
                    assert value["summary"] == summary
                    seen.extend(item["objectId"] for item in value["items"])
                    if value["nextCursor"] is None:
                        break
                    params["cursor"] = value["nextCursor"]
                    if not observed:
                        class LaterClock(datetime):
                            @classmethod
                            def now(cls, tz=None):
                                later = NOW + timedelta(hours=1)
                                return later.astimezone(tz) if tz else later.replace(tzinfo=None)
                        monkeypatch.setattr(ops_monitor_context, "datetime", LaterClock)
                assert seen == expected and value["nextCursor"] is None
                assert summary["stations"] == 5
                assert summary["mismatch"] == (0 if observed else 5)


@pytest.mark.parametrize("variant", ["tamper", "pageSize", "region", "onlyProblems", "boundary", "binding", "revoke"])
async def test_NS09_cursor_binding_boundary_and_revoke(network_world, variant):
    w = network_world
    async with machine(w) as headers:
        async with changed(w, PartnerResourceScope, (w.installations[1], "objects"), mode="ALL"):
            async with added_network(w, ["ns-cursor-a", "ns-cursor-b"]):
                params = {"region": "R-PAGE", "pageSize": 1}
                first = data(await get(w, params, headers))
                assert first["nextCursor"] is not None
                params["cursor"] = first["nextCursor"]
                if variant == "tamper":
                    params["cursor"] = ("B" if params["cursor"][0] == "A" else "A") + params["cursor"][1:]
                    problem(await get(w, params, headers), 400, "invalid_cursor")
                elif variant in ("pageSize", "region", "onlyProblems"):
                    params[variant] = {"pageSize": 2, "region": "r-page", "onlyProblems": "true"}[variant]
                    problem(await get(w, params, headers), 400, "invalid_cursor")
                elif variant == "boundary":
                    async with w.factory() as db:
                        await db.execute(update(ChargeSession).where(ChargeSession.company_id == w.companies[0],
                            ChargeSession.location_id == "ns-cursor-b").values(started_at=datetime(2026, 11, 1, 9)))
                        await db.commit()
                    problem(await get(w, params, headers), 400, "invalid_cursor")
                elif variant == "binding":
                    # Existing signed token is still valid, but the LIVE typed ceiling changes.
                    async with changed(w, PartnerResourceScope, (w.installations[1], "objects"), mode="SET"):
                        problem(await get(w, params, headers), 400, "invalid_cursor")
                else:
                    async with changed(w, PartnerGrant, w.machine_grant, approved=False):
                        # Denial must precede even decoding a deliberately malformed cursor.
                        params["cursor"] = "deliberately-bad"
                        async with trace(w) as (records, _):
                            response = await get(w, params, headers)
                        problem(response, 401, "invalid_credentials")
                        assert 'error="invalid_token"' in response.headers["www-authenticate"]
                        assert not any("charge_sessions" in sql for sql, _ in records)


async def test_NS10_cap_before_owner_and_region(network_world):
    w = network_world
    async with machine(w) as headers:
        async with changed(w, PartnerResourceScope, (w.installations[1], "objects"), mode="ALL"):
            async with added_network(w, [f"ns-cap-{i:05d}" for i in range(10001)], owner="СНК", observed=False):
                async with trace(w) as (records, _):
                    response = await get(w, {"region": "no-such-region"}, headers)
                problem(response, 503, "api_unavailable")
                assert not any("charge_sessions" in sql for sql, _ in records)
                candidates = [(sql, args) for sql, args in records if "LIMIT" in sql and "service_locations" in sql]
                assert len(candidates) == 1
                assert "owner" in candidates[0][0] and "jsonb_typeof" in candidates[0][0]
                assert 10001 in candidates[0][1] and 201 in candidates[0][1]
                # Same DB has >10000 foreign-to-user candidates; authorized cap is narrow.
                assert data(await get(w))["summary"]["stations"] == 1


@pytest.mark.parametrize("variant", ["deadline", "sql-timeout", "cancel"])
async def test_NS11_deadline_timeout_reset_cancel(network_world, variant):
    w = network_world
    # Nondestructive control: hold the session table lock in the Root-owned test
    # DB only. Auth/catalog remain available; no DDL, schema changes or triggers.
    async with w.factory() as probe:
        engine = probe.bind.sync_engine
        previous_timeout = await probe.scalar(text("SHOW statement_timeout"))
    entered = asyncio.Event()
    hook_settings = []

    def before(connection, cursor, statement, parameters, context, many):
        if "charge_sessions" in statement and "max(" in statement.lower():
            cursor.execute("SELECT current_setting('statement_timeout'), current_setting('transaction_read_only')")
            hook_settings.append(cursor.fetchone())
            assert hook_settings[-1] == ("5s", "on")
            if variant == "deadline":
                # Test-only negative control: SQL cannot supply the expected
                # 503 before the 8s outer wait; the business 5s deadline must.
                cursor.execute("SET LOCAL statement_timeout = '10s'")
            elif variant == "sql-timeout":
                # A shorter REAL local timeout makes PG cancellation distinct
                # from the unchanged production 5s asyncio admission deadline.
                cursor.execute("SET LOCAL statement_timeout = '150ms'")
            entered.set()

    event.listen(engine, "before_cursor_execute", before)
    try:
        async with w.factory() as blocker:
            async with blocker.begin():
                await blocker.execute(text("LOCK TABLE charge_sessions IN ACCESS EXCLUSIVE MODE"))
                started = asyncio.get_running_loop().time()
                pending = asyncio.create_task(get(w))
                await asyncio.wait_for(entered.wait(), 3)
                if variant == "cancel":
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                else:
                    response = await asyncio.wait_for(pending, 8)
                    problem(response, 503, "api_unavailable")
                    elapsed = asyncio.get_running_loop().time() - started
                    assert elapsed < (3 if variant == "sql-timeout" else 8)
                    assert "SELECT" not in response.text and "charge_sessions" not in response.text
                assert hook_settings == [("5s", "on")]
    finally:
        event.remove(engine, "before_cursor_execute", before)
    # Exercise actual reused connections and transactions after timeout/cancel.
    for _ in range(3):
        async with w.factory() as db:
            assert await db.scalar(text("SELECT 1")) == 1
            assert await db.scalar(text("SHOW statement_timeout")) == previous_timeout
            assert await db.scalar(text("SHOW transaction_read_only")) == "off"
        assert data(await get(w))["summary"]["stations"] == 1


@pytest.mark.parametrize("params,body", [
    ({"companyId": "foreign"}, None), ({"organizationId": "foreign"}, None), ({"unknownKey": "x"}, None),
    ({"pageSize": 0}, None), ({"pageSize": 201}, None), ({"asOf": "1999-12-31"}, None),
    ({"asOf": "9999-12-31"}, None), ({"asOf": "null"}, None),
    ({"asOf": "2026-10-25T00:00:00Z"}, None), ({"onlyProblems": "1"}, None),
    ({"onlyProblems": "TRUE"}, None), ({"region": ""}, None), ({"region": "R1||R2"}, None),
    ({"region": "|".join(["R1"] * 21)}, None), ({"region": "x" * 201}, None), ({}, b"x"), ({}, "streamed"),
])
async def test_NS12_strict_request(network_world, params, body):
    w = network_world
    consumed_second = False
    if body == "streamed":
        async def chunks():
            nonlocal consumed_second
            yield b"x"
            consumed_second = True
            yield b"y" * 1000000
        body = chunks()
    async with trace(w) as (records, _):
        response = await get(w, params, content=body)
    problem(response, 422, "invalid_request")
    assert not any("charge_sessions" in sql for sql, _ in records)
    assert not consumed_second
