"""Opt-in native term-scope acceptance source; execution belongs to ROOT."""
import os
from urllib.parse import urlsplit

import pytest

FLAG = "RUN_RUSHYDRO_TERM_SCOPE_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip("Explicit native term-scope admission required", allow_module_level=True)
from tests.partner_test_safety import partner_test_safety_error
if partner_test_safety_error(os.environ, flag=FLAG):
    raise pytest.UsageError("Native term-scope pre-import safety refused")
_target = urlsplit(os.environ["TEST_DATABASE_URL"])
if (os.environ.get("RUN_RUSHYDRO_PRODUCT_READS_TESTS") != "1"
        or os.environ.get("ROOT_APPROVED_RUSHYDRO_PRODUCT_READS") != "1"
        or os.environ.get("APP_ENV") != "test"
        or os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL")
        or (_target.hostname, _target.port, _target.path, _target.username) != (
            "127.0.0.1", 5432, "/api_rushydro_reads25_test_20261101", "clearledger")):
    raise pytest.UsageError("Exact external native READ admission required")

from contextlib import contextmanager
from decimal import Decimal
import re
from uuid import UUID, uuid4

from sqlalchemy import event, select

from app.models import (Contract, ContractLocation, OpsContractTerm, OpsCostItem,
                        OpsPeriodCharge, OpsPeriodClose)
from app.services import ops_expectations as expectations
from app.services import ops_terms
from tests.test_rushydro_product_reads_native_pg import O1, O2, P1, TYPE, read_world

pytestmark = pytest.mark.asyncio(loop_scope="session")
PERIOD = "2026-06-01"
NO_COVERAGE = "у договора не заполнен охват по объектам"
MULTI_COVERAGE = "у условия несколько объектов; укажите объект в условии"

# ID, boundary scope, explicit location, native coverage count, scope result,
# planner blocked reason. None is a nonpersisted legacy domain boundary only.
SCOPE_CASES = [
    ("company-null", "company", None, 2, [None], None),
    ("company-explicit", "company", O1, 2, [None], None),
    ("location-explicit", "location", O1, 2, [O1], None),
    ("location-zero", "location", None, 0, [], NO_COVERAGE),
    ("location-one", "location", None, 1, [O1], None),
    ("location-multi", "location", None, 2, [O1, O2], MULTI_COVERAGE),
    ("legacy-none-explicit", None, O1, 2, [O1], None),
    ("legacy-none-one", None, None, 1, [O1], None),
    ("legacy-none-multi", None, None, 2, [O1, O2], MULTI_COVERAGE),
    ("legacy-empty-explicit", "", O1, 2, [O1], None),
    ("legacy-empty-zero", "", None, 0, [], NO_COVERAGE),
    ("legacy-empty-multi", "", None, 2, [O1, O2], MULTI_COVERAGE),
]
UNSUPPORTED_CASES = [
    ("site-null", "site", None),
    ("site-explicit", "site", O1),
    ("unknown-null", "future-scope", None),
    ("unknown-explicit", "future-scope", O1),
]
ELIGIBILITY_CASES = [
    ("future", {"valid_from": "2026-07-01"}, True),
    ("expired", {"valid_to": "2026-05-31"}, True),
    ("quarterly-off", {"periodicity": "quarterly"}, True),
    ("annual-off", {"periodicity": "annual"}, True),
    ("inactive", {}, False),
]
FLOW_CASES = [
    ("mixed-history-repeat", "mixed"),
    ("closed-unchanged", "closed"),
]


def blocked(term, reason):
    return {"termId": str(term.id), "contractId": str(term.contract_id),
            "costItem": term.cost_item, "reason": reason}


def unsupported_reason(scope):
    return f"неподдерживаемый охват {scope}; требуется распределение"


async def seed_terms(w, specs, *, coverage=2, active=True):
    """Own synthetic contracts/cost item; FK parents come from shared read_world.

    No ServiceLocation stands in for Site. Each term has its own contract so
    uq_ops_term(contract,cost_item,coalesce(location,''),valid_from) stays real.
    All fixture DML commits before listeners; ROOT owns whole-DB disposal.
    """
    code = "term-scope-" + uuid4().hex
    identifiers = []
    async with w.factory() as db:
        db.add(OpsCostItem(code=code, label="Учебная статья scope", measure="fixed",
                           default_estimate_basis="contract", is_active=active, sort_order=100))
        await db.flush()
        for spec in specs:
            contract_id, term_id = uuid4(), uuid4()
            db.add(Contract(id=contract_id, company_id=w.companies[0],
                organization_id=w.orgs[0], counterparty_id=UUID(P1), number="SYN-SCOPE",
                date="2026-01-01", type="service", type_code=TYPE,
                scope_type="locations", is_closed=False))
            await db.flush()
            db.add_all([ContractLocation(company_id=w.companies[0], contract_id=contract_id,
                        location_id=location) for location in (O1, O2)[:coverage]])
            values = dict(id=term_id, company_id=w.companies[0], contract_id=contract_id,
                cost_item=code, scope_type="location", location_id=None,
                periodicity="monthly", valid_from="2026-01-01", amount_gross=1200,
                vat_pct=20, estimate_basis="contract", doc_due_day=10, source="synthetic-term-scope")
            values.update(spec)
            db.add(OpsContractTerm(**values))
            identifiers.append(term_id)
        await db.commit()
    return identifiers


async def load_terms(db, ids):
    rows = (await db.scalars(select(OpsContractTerm).where(OpsContractTerm.id.in_(ids)))).all()
    by_id = {row.id: row for row in rows}
    return [by_id[identifier] for identifier in ids]


async def state(db, ids):
    """Native selected tables, including timestamps and historical seq rows."""
    snapshots = []
    for model, column in ((OpsContractTerm, OpsContractTerm.id),
                          (OpsPeriodCharge, OpsPeriodCharge.term_id)):
        rows = await db.execute(select(model.__table__).where(column.in_(ids)).order_by(model.id))
        snapshots.append(tuple(rows.all()))
    return tuple(snapshots)


@contextmanager
def sql_trace(db):
    statements = []
    engine = db.bind.sync_engine
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def assert_read_sql(statements):
    assert any(re.search(r"\bselect\b", sql, re.I) for sql in statements)
    assert not any(re.search(r"\b(insert|update|delete|merge|create|alter|drop|truncate)\b",
                             sql, re.I) for sql in statements), statements


async def checked_plan(db, company, ids, terms):
    # Even a caller's dirty ORM input must not trigger autoflush. No interception
    # of SQL results, Query, owner or factory; the listener only observes SQL.
    with db.no_autoflush:
        before = await state(db, ids)
        unit = (set(db.new), set(db.dirty), set(db.deleted))
        with sql_trace(db) as statements:
            plan = await expectations.plan_expectations(db, company, PERIOD, terms=terms)
        assert_read_sql(statements)
        assert unit == (set(db.new), set(db.dirty), set(db.deleted))
        assert await state(db, ids) == before
    return plan


@pytest.mark.parametrize("case_id,scope,location,coverage,expected,reason", SCOPE_CASES,
                         ids=[row[0] for row in SCOPE_CASES])
async def test_scope_plan(read_world, case_id, scope, location, coverage, expected, reason):
    w = read_world
    ids = await seed_terms(w, [{"scope_type": scope if scope is not None else "location",
                               "location_id": location}], coverage=coverage)
    async with w.factory() as db:
        terms = await load_terms(db, ids)
        term = terms[0]
        if scope is None:
            # NOT NULL native column: never persist/flush a NULL scope.
            term.scope_type = None
        with db.no_autoflush:
            ctx = await expectations.build_ctx(db, w.companies[0])
            assert set(ctx.scope(term)) == set(expected)
        plan = await checked_plan(db, w.companies[0], ids, terms)
        assert plan.skipped == plan.stale == 0
        if reason:
            assert plan.changes == () and plan.blocked == (blocked(term, reason),)
            assert plan.missing == 0
        else:
            assert plan.blocked == () and plan.missing == 1
            assert len(plan.changes) == 1
            change = plan.changes[0]
            assert change.row_id is None and change.changed
            assert change.values["location_id"] == expected[0]
            assert (change.values["expected_gross"], change.values["expected_net"],
                    change.values["expected_basis"], change.values["doc_due_on"]) == (
                        Decimal("1200.00"), Decimal("1000.00"), "contract", "2026-07-10")
        await db.rollback()


@pytest.mark.parametrize("case_id,scope,location", UNSUPPORTED_CASES,
                         ids=[row[0] for row in UNSUPPORTED_CASES])
async def test_unsupported_plan_and_expand(read_world, case_id, scope, location):
    w = read_world
    ids = await seed_terms(w, [{"scope_type": scope, "location_id": location}])
    async with w.factory() as db:
        terms = await load_terms(db, ids)
        term = terms[0]
        ctx = await expectations.build_ctx(db, w.companies[0])
        assert set(ctx.locations[term.contract_id]) == {O1, O2}
        assert ctx.scope(term) == []
        with pytest.raises(ValueError, match="Неизвестный охват"):
            ops_terms._validate({"scope_type": scope})
        plan = await checked_plan(db, w.companies[0], ids, terms)
        expected = blocked(term, unsupported_reason(scope))
        assert plan.blocked == (expected,) and plan.changes == ()
        assert plan.missing == plan.stale == plan.skipped == 0
        before = await state(db, ids)
        with sql_trace(db) as statements:
            result = await expectations.expand(db, w.companies[0], PERIOD, terms=terms)
            await db.commit()
        assert result == {"period": PERIOD, "created": 0, "updated": 0,
                          "skipped": 0, "blocked": [expected]}
        assert_read_sql(statements)
        assert await state(db, ids) == before


@pytest.mark.parametrize("case_id,overrides,active", ELIGIBILITY_CASES,
                         ids=[row[0] for row in ELIGIBILITY_CASES])
async def test_eligibility_precedes_unsupported(read_world, case_id, overrides, active):
    w = read_world
    ids = await seed_terms(w, [{"scope_type": "site", "location_id": O1, **overrides}], active=active)
    async with w.factory() as db:
        terms = await load_terms(db, ids)
        plan = await checked_plan(db, w.companies[0], ids, terms)
        assert plan.changes == plan.blocked == ()
        assert plan.skipped == plan.missing == plan.stale == 0


@pytest.mark.parametrize("case_id,mode", FLOW_CASES, ids=[row[0] for row in FLOW_CASES])
async def test_apply_history_and_closed(read_world, case_id, mode):
    w = read_world
    target_period = PERIOD if mode == "mixed" else "2026-08-01"
    ids = await seed_terms(w, [
        {"scope_type": "location", "location_id": O1, "amount_gross": None,
         "estimate_basis": "prev_period"},
        {"scope_type": "site", "location_id": O1},
        {"scope_type": "future-scope", "location_id": None},
    ])
    async with w.factory() as db:
        terms = await load_terms(db, ids)
        def charge(term, period, **values):
            return OpsPeriodCharge(company_id=w.companies[0], period=period,
                cost_item=term.cost_item, term_id=term.id, contract_id=term.contract_id,
                location_id=term.location_id, seq=0, **values)
        db.add(charge(terms[0], "2026-05-01", status="matched", actual_gross=330,
                      expected_gross=300, expected_basis="contract", note="history"))
        # An old mutable invalid-scope row must neither move nor be recalculated.
        db.add(charge(terms[1], target_period, status="expected", expected_gross=777,
                      expected_basis="contract", note="preserve invalid"))
        close_id = uuid4()
        if mode == "closed":
            db.add(OpsPeriodClose(id=close_id, company_id=w.companies[0], period=target_period,
                status="closed", total_actual_gross=330, summary={"synthetic": "frozen"}))
        await db.commit()
        terms = await load_terms(db, ids)
        before = await state(db, ids)
        if mode == "closed":
            close_before = (await db.execute(select(OpsPeriodClose.__table__).where(
                OpsPeriodClose.id == close_id))).one()
            with sql_trace(db) as statements:
                result = await expectations.expand(db, w.companies[0], target_period, terms=terms)
                await db.commit()
            assert_read_sql(statements)
            assert result == {"period": target_period, "created": 0, "updated": 0, "skipped": 0, "blocked": []}
            assert await state(db, ids) == before
            assert (await db.execute(select(OpsPeriodClose.__table__).where(
                OpsPeriodClose.id == close_id))).one() == close_before
            return
        plan = await checked_plan(db, w.companies[0], ids, terms)
        expected_blocked = tuple(blocked(t, unsupported_reason(t.scope_type)) for t in terms[1:])
        assert plan.blocked == expected_blocked and len(plan.changes) == plan.missing == 1
        assert plan.changes[0].values["term_id"] == ids[0]
        assert plan.changes[0].values["expected_gross"] == Decimal("330.00")
        assert plan.changes[0].values["expected_net"] == Decimal("275.00")
        assert plan.changes[0].values["expected_basis"] == "prev_period"
        first = await expectations.expand(db, w.companies[0], PERIOD, terms=terms)
        await db.commit()
        assert first == {"period": PERIOD, "created": 1, "updated": 0,
                         "skipped": 0, "blocked": list(expected_blocked)}
        after = await state(db, ids)
        assert before[0] == after[0]
        assert all(row in after[1] for row in before[1])  # history + invalid byte-for-byte values
        assert len(after[1]) == len(before[1]) + 1
        repeat_plan = await checked_plan(db, w.companies[0], ids, terms)
        assert repeat_plan.missing == repeat_plan.stale == 0
        repeat = await expectations.expand(db, w.companies[0], PERIOD, terms=terms)
        await db.commit()
        assert repeat == {**first, "created": 0}
        assert await state(db, ids) == after
