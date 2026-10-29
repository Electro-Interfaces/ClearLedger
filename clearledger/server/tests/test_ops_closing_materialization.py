"""HTTP/SQL proof of read-only closing and explicit, serialized preparation."""
import asyncio
import os
import re
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text

from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_OPS_CLOSING_TESTS") != "1":
    pytest.skip("Opt in with RUN_OPS_CLOSING_TESTS=1", allow_module_level=True)
error = partner_test_safety_error(os.environ, flag="RUN_OPS_CLOSING_TESTS")
if error:
    raise pytest.UsageError("Refusing closing test database: " + error)

from app.auth import token_for
from app.models import (Company, User, UserCompany, CompanyRole, Counterparty, Organization, Contract,
    ServiceLocation, OpsContractTerm, OpsPeriodCharge, OpsPeriodClose, OpsCounterpartyDoc,
    OpsPayment, StationEnergyPeriod, DataEntry)
from app.services import ops_closing, ops_expectations
from tests.conftest import _test_session_factory, _test_engine

pytestmark = pytest.mark.asyncio(loop_scope="session")
PERIOD = "2026-06-01"
DOMAIN = (OpsContractTerm, OpsPeriodCharge, OpsPeriodClose, OpsCounterpartyDoc, OpsPayment,
          Contract, StationEnergyPeriod, DataEntry)


@pytest_asyncio.fixture(loop_scope="session")
async def closing_env(client, db):
    suffix = uuid.uuid4().hex[:12]
    company = Company(name="Synthetic closing", slug="closing-" + suffix, profile_id="energy")
    foreign = Company(name="Synthetic foreign closing", slug="foreign-" + suffix, profile_id="energy")
    db.add_all([company, foreign])
    await db.flush()
    user = User(company_id=company.id, email=suffix + "@example.invalid", name="Synthetic closer",
        password_hash="synthetic-no-login", role="user", last_seen_at=datetime.now(timezone.utc))
    cp = Counterparty(company_id=company.id, name="Synthetic supplier")
    org = Organization(company_id=company.id, name="Synthetic organization", inn="0000000000")
    location = ServiceLocation(id="closing-" + suffix, company_id=company.id, code="TEST", name="Synthetic object")
    db.add_all([user, cp, org, location])
    await db.flush()
    member = UserCompany(user_id=user.id, company_id=company.id, role="admin")
    contract = Contract(company_id=company.id, number="TEST-" + suffix, date="2026-01-01",
        type="rent", organization_id=org.id, counterparty_id=cp.id)
    db.add_all([member, contract])
    await db.flush()
    term = OpsContractTerm(company_id=company.id, contract_id=contract.id, cost_item="rent",
        location_id=location.id, scope_type="location", periodicity="monthly", valid_from="2026-01-01",
        amount_gross=1200, vat_pct=20, estimate_basis="contract", doc_due_day=10)
    db.add(term)
    await db.commit()
    return dict(client=client, db=db, company=company, foreign=foreign, user=user, member=member,
        contract=contract, term=term, location=location, org=org,
        headers={"Authorization": "Bearer " + token_for(user)})


async def view(env, **params):
    return await env["client"].get("/api/ops/closing", headers=env["headers"],
        params={"company_id": str(env["company"].id), "period": PERIOD, "scope": "all", **params})


async def command(env, verb="materialize", period=PERIOD, **kwargs):
    return await env["client"].post(f"/api/ops/closing/{period}/{verb}", headers=env["headers"],
        params={"company_id": str(env["company"].id), **kwargs.pop("params", {})}, **kwargs)


async def assert_advisory_waiter(owner):
    for _ in range(100):
        await owner.execute(text("SELECT pg_stat_clear_snapshot()"))
        waiting = await owner.scalar(text("SELECT count(*) FROM pg_stat_activity "
            "WHERE datname=current_database() AND wait_event='advisory'"))
        if waiting:
            return
        await asyncio.sleep(0.01)
    pytest.fail("Concurrent command did not reach the transaction barrier")


async def domain_state():
    async with _test_session_factory() as db:
        return {model.__tablename__: (await db.execute(select(model.__table__).order_by(*model.__table__.primary_key.columns))).all()
                for model in DOMAIN}


async def test_repeated_get_has_no_domain_dml_and_does_not_prepare(closing_env, monkeypatch):
    env = closing_env
    before = await domain_state()
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if re.search(r"\b(insert\s+into|update|delete\s+from)\b", statement, re.I):
            statements.append(statement.lower())
    async def forbidden(*args, **kwargs):
        raise AssertionError("GET must not call expansion/get_or_create")
    monkeypatch.setattr(ops_expectations, "expand", forbidden)
    monkeypatch.setattr(ops_closing, "get_or_create", forbidden)
    event.listen(_test_engine.sync_engine, "before_cursor_execute", capture)
    try:
        replies = [await view(env) for _ in range(3)]
    finally:
        event.remove(_test_engine.sync_engine, "before_cursor_execute", capture)
    assert all(r.status_code == 200 for r in replies), [r.text for r in replies]
    assert all(r.json() == replies[0].json() for r in replies)
    data = replies[0].json()
    assert data["charges"] == [] and data["counters"]["totalGross"] == 0
    assert data["preparation"] == {"required": True, "missing": 1, "stale": 0}
    assert await domain_state() == before
    assert not [s for s in statements if any(m.__tablename__ in s for m in DOMAIN)], statements


async def test_materialize_get_repeat_real_amount_and_shared_plan(closing_env):
    env = closing_env
    result = await command(env)
    assert result.status_code == 200 and result.json()["created"] == 1, result.text
    data = (await view(env)).json()
    assert data["preparation"]["required"] is False
    assert data["counters"]["totalGross"] == 1200
    assert data["charges"][0]["expectedGross"] == 1200
    assert data["charges"][0]["expectedNet"] == 1000
    assert data["charges"][0]["expectedBasis"] == "contract"
    assert data["charges"][0]["counterpartyId"]
    assert data["charges"][0]["docDueOn"] == "2026-07-10"
    before = await domain_state()
    repeat = await command(env)
    assert repeat.json()["created"] == repeat.json()["updated"] == 0
    assert await domain_state() == before
    env["term"].amount_gross = 2400
    await env["db"].commit()
    stale = (await view(env)).json()
    assert stale["preparation"] == {"required": True, "missing": 0, "stale": 1}
    assert stale["charges"][0]["expectedGross"] == 1200
    assert (await command(env)).json()["updated"] == 1
    assert (await view(env)).json()["counters"]["totalGross"] == 2400


async def test_concurrent_materializations_do_not_duplicate_or_fail(closing_env):
    env = closing_env
    results = await asyncio.gather(*(command(env) for _ in range(4)))
    assert [r.status_code for r in results] == [200] * 4, [r.text for r in results]
    assert sum(r.json()["created"] for r in results) == 1
    async with _test_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(OpsPeriodCharge).where(
            OpsPeriodCharge.company_id == env["company"].id)) == 1
        assert await db.scalar(select(func.count()).select_from(OpsPeriodClose).where(
            OpsPeriodClose.company_id == env["company"].id)) == 1


async def test_close_prepares_and_closed_period_stays_frozen_then_reopens(closing_env):
    env = closing_env
    closed = await command(env, "close")
    assert closed.status_code == 200 and closed.json()["ok"], closed.text
    env["term"].amount_gross = 2500
    await env["db"].commit()
    before = await domain_state()
    assert (await command(env)).status_code == 409
    data = (await view(env)).json()
    assert data["status"] == "closed" and not data["preparation"]["required"]
    assert data["charges"][0]["expectedGross"] == 1200
    assert await domain_state() == before
    reopened = await command(env, "reopen", json={"reason": "Synthetic correction"})
    assert reopened.status_code == 200 and reopened.json()["status"] == "reopened"
    assert (await command(env)).status_code == 200
    # Settled/accrued rows remain immutable when reopened too.
    assert (await view(env)).json()["charges"][0]["expectedGross"] == 1200


async def test_close_and_materialize_share_transaction_barrier(closing_env):
    env = closing_env
    async with _test_session_factory() as owner:
        await ops_expectations.lock_period(owner, env["company"].id, PERIOD)
        waiting = asyncio.create_task(command(env))
        try:
            await assert_advisory_waiter(owner)
            assert not waiting.done()
            closed = await ops_closing.close_period(owner, env["company"].id, PERIOD, user_id=env["user"].id)
            assert closed["ok"]
            await owner.commit()
            response = await waiting
            assert response.status_code == 409, response.text
        finally:
            await owner.rollback()
            if not waiting.done(): waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)


async def test_reopen_and_materialize_share_transaction_barrier(closing_env):
    env = closing_env
    assert (await command(env, "close")).json()["ok"]
    async with _test_session_factory() as owner:
        await ops_closing.reopen_period(owner, env["company"].id, PERIOD, "Synthetic reopen")
        waiting = asyncio.create_task(command(env))
        try:
            await assert_advisory_waiter(owner)
            assert not waiting.done()
            await owner.commit()
            assert (await waiting).status_code == 200
        finally:
            await owner.rollback()
            if not waiting.done(): waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)


async def test_manual_rows_and_linked_manual_amounts_are_preserved(closing_env):
    env = closing_env
    manual = OpsPeriodCharge(company_id=env["company"].id, period=PERIOD, cost_item="rent", seq=0,
        expected_gross=777, expected_basis="manual", status="expected")
    linked = OpsPeriodCharge(company_id=env["company"].id, period=PERIOD, cost_item="rent", seq=0,
        term_id=env["term"].id, contract_id=env["contract"].id, location_id=env["location"].id,
        expected_gross=999, expected_basis="manual", status="expected")
    env["db"].add_all([manual, linked])
    await env["db"].commit()
    assert (await command(env)).json()["updated"] == 0
    assert (await command(env, "close")).json()["ok"]
    data = (await view(env)).json()
    assert sorted(c["expectedGross"] for c in data["charges"]) == [777, 999]
    assert all(c["expectedBasis"] == "manual" for c in data["charges"])


async def test_blocked_is_computed_without_preparing_or_flushing(closing_env):
    env = closing_env
    env["term"].location_id = None
    await env["db"].commit()
    before = await domain_state()
    data = (await view(env)).json()
    assert data["blocked"][0]["reason"] == "у договора не заполнен охват по объектам"
    assert data["charges"] == []
    assert await domain_state() == before
    result = await command(env)
    assert result.json()["blocked"] == data["blocked"]


@pytest.mark.parametrize("change", ["foreign", "unknown", "unknown_role", "no_module", "other_module", "objects", "empty_objects", "organization", "foreign_role"])
async def test_membership_domain_and_narrowed_contexts_cannot_materialize(closing_env, change):
    env = closing_env
    if change == "unknown_role": env["member"].role = "unknown"
    if change == "no_module": env["member"].role, env["member"].modules = "user", []
    if change == "other_module": env["member"].role, env["member"].modules = "user", ["ops:ops_overview"]
    if change in {"objects", "empty_objects"}:
        env["member"].role = "user"
        env["member"].object_scope = [env["location"].id] if change == "objects" else []
    if change == "organization":
        env["member"].role, env["member"].own_organization_id = "user", env["org"].id
    if change == "foreign_role":
        role = CompanyRole(company_id=env["foreign"].id, name="Foreign role", modules=None)
        env["db"].add(role)
        await env["db"].flush()
        env["member"].role, env["member"].role_id = "user", role.id
    await env["db"].commit()
    before = await domain_state()
    params = {"company_id": str(env["foreign"].id)} if change == "foreign" else (
        {"company_id": str(uuid.uuid4())} if change == "unknown" else {})
    response = await command(env, params=params)
    assert response.status_code in {400, 403, 404}, response.text
    assert await domain_state() == before


async def test_explicit_closing_module_is_real_server_permission(closing_env):
    env = closing_env
    env["member"].role, env["member"].modules = "user", ["ops:ops_closing"]
    await env["db"].commit()
    assert (await command(env)).status_code == 200


@pytest.mark.parametrize("params", [{"period": "2026-06"}, {"period": "2026-06-02"}, {"period": "2026-99-01"},
    {"period": "9999-12-01"}, {"scope": "unknown"}, {"status": "unknown"}, {"location_ids": "somewhere"}])
async def test_strict_get_parameters(closing_env, params):
    before = await domain_state()
    assert (await view(closing_env, **params)).status_code == 422
    assert await domain_state() == before


async def test_strict_command_parameters_and_organization_header(closing_env):
    env = closing_env
    before = await domain_state()
    assert (await command(env, params={"scope": "all"})).status_code == 422
    assert (await command(env, json={"company_id": str(env["foreign"].id)})).status_code == 422
    assert (await command(env, "close", params={"force": "1"})).status_code == 422
    assert (await command(env, period="9999-12-01")).status_code == 422
    for org in (str(env["org"].id), "invalid"):
        response = await env["client"].post(f"/api/ops/closing/{PERIOD}/materialize",
            headers={**env["headers"], "X-Organization-Id": org}, params={"company_id": str(env["company"].id)})
        assert response.status_code == 403
    assert await domain_state() == before


async def test_periods_default_is_read_only_and_explicit_legacy_is_deprecated(closing_env):
    env = closing_env
    before = await domain_state()
    params = {"company_id": str(env["company"].id), "months": "1", "ahead": "0"}
    response = await env["client"].get("/api/ops/periods", params=params, headers=env["headers"])
    assert response.status_code == 200 and "Deprecation" not in response.headers
    assert await domain_state() == before
    legacy = await env["client"].get("/api/ops/periods", params={**params, "expand_all": "true"}, headers=env["headers"])
    assert legacy.status_code == 200, legacy.text
    assert legacy.headers["deprecation"].startswith("@")
    assert legacy.headers["warning"].startswith("299") and legacy.headers["cache-control"] == "no-store"
    async with _test_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(OpsPeriodCharge).where(
            OpsPeriodCharge.company_id == env["company"].id)) == 1
    env["member"].role, env["member"].object_scope = "user", [env["location"].id]
    await env["db"].commit()
    before = await domain_state()
    denied = await env["client"].get("/api/ops/periods", params={**params, "expand_all": "true"}, headers=env["headers"])
    assert denied.status_code == 403
    assert await domain_state() == before


async def test_no_basis_is_not_zero_and_force_keeps_waived_provenance(closing_env):
    env = closing_env
    env["term"].amount_gross = None
    await env["db"].commit()
    rejected = await command(env, "close")
    assert rejected.status_code == 200 and rejected.json()["ok"] is False
    assert len(rejected.json()["blocking"]) == 1
    forced = await command(env, "close", params={"force": "true"})
    assert forced.json()["ok"] and forced.json()["waived"] == 1
    row = (await view(env)).json()["charges"][0]
    assert row["status"] == "waived" and row["expectedGross"] is None and row["expectedBasis"] == "none"


async def test_late_document_keeps_closed_expectation_and_snapshot(closing_env):
    from app.services import ops_terms
    env = closing_env
    assert (await command(env, "close")).json()["ok"]
    charge = (await view(env)).json()["charges"][0]
    doc = await ops_terms.create_doc(env["db"], env["company"].id, {"docType": "act",
        "period": PERIOD, "number": "SYNTHETIC-LATE", "docDate": "2026-07-15", "amountGross": 1500},
        user_id=env["user"].id)
    attached = await ops_closing.attach_doc(env["db"], env["company"].id, uuid.UUID(charge["id"]),
        uuid.UUID(doc["id"]), user_id=env["user"].id)
    assert attached["periodClosed"] and attached["correctionOffered"]
    await env["db"].commit()
    before = await domain_state()
    data = (await view(env)).json()
    assert data["charges"][0]["expectedGross"] == 1200
    assert data["charges"][0]["actualGross"] == 1500 and data["charges"][0]["variance"] == 300
    assert await domain_state() == before
    async with _test_session_factory() as db:
        period_row = await db.scalar(select(OpsPeriodClose).where(
            OpsPeriodClose.company_id == env["company"].id, OpsPeriodClose.period == PERIOD))
        assert period_row.summary["counters"]["totalGross"] == 1200
