"""Finite native source acceptance. Author runtime NOT RUN; ROOT owns admission."""
import os
from urllib.parse import urlsplit

import pytest

FLAG = "RUN_RUSHYDRO_TERM_CLOSED_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip("Explicit native term/closed admission required", allow_module_level=True)
from tests.partner_test_safety import partner_test_safety_error
if partner_test_safety_error(os.environ, flag=FLAG):
    raise pytest.UsageError("Native term/closed pre-import safety refused")
_target = urlsplit(os.environ["TEST_DATABASE_URL"])
if (os.environ.get("RUN_RUSHYDRO_PRODUCT_READS_TESTS") != "1"
        or os.environ.get("ROOT_APPROVED_RUSHYDRO_PRODUCT_READS") != "1"
        or os.environ.get("APP_ENV") != "test"
        or os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL")
        or (_target.hostname, _target.port, _target.path, _target.username) != (
            "127.0.0.1", 5432, "/api_rushydro_reads25_test_20261101", "clearledger")):
    raise pytest.UsageError("Exact external native term/closed admission required")

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import event, select, text

from app.models import (Company, Contract, Counterparty, OpsContractTerm,
    OpsCostItem, OpsCounterpartyDoc, OpsPeriodCharge, OpsPeriodClose, Organization)
from app.services.ops_closing import close_period, reopen_period
from app.services.ops_terms import create_term, delete_term, update_term
from tests.test_rushydro_product_reads_native_pg import TYPE, read_world

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Frozen 26 functional IDs. Every date, action and expected horizon is literal;
# NULL means unbounded except create, which retains native contract defaults.
# id, action, old range, new range, closed month, status, company index, allowed,
# expected old end after successful versioning.
FUNCTIONAL_CASES = [
    ("01-create-closed", "create", None, ("2026-06-01", "2026-06-30"), "2026-06-01", "closed", 0, False, None),
    ("02-create-first-day", "create", None, ("2026-05-31", "2026-06-01"), "2026-06-01", "closed", 0, False, None),
    ("03-create-last-day", "create", None, ("2026-06-30", "2026-07-01"), "2026-06-01", "closed", 0, False, None),
    ("04-create-after", "create", None, ("2026-07-01", "2026-07-31"), "2026-06-01", "closed", 0, True, None),
    ("05-create-before", "create", None, ("2026-05-01", "2026-05-31"), "2026-06-01", "closed", 0, True, None),
    ("06-create-unbounded-far", "create", None, ("2020-01-01", None), "2035-01-01", "closed", 0, False, None),
    ("07-create-contract-defaults", "create-defaults", None, None, "2026-06-01", "closed", 0, False, None),
    ("08-create-foreign-close", "create", None, ("2026-06-01", "2026-06-30"), "2026-06-01", "closed", 1, True, None),
    ("09-create-reopened", "create", None, ("2026-06-01", "2026-06-30"), "2026-06-01", "reopened", 0, True, None),
    ("10-inplace-closed-amount", "update", ("2026-06-01", "2026-06-30"), ("2026-06-01", "2026-06-30"), "2026-06-01", "closed", 0, False, None),
    ("11-inplace-move-out", "update", ("2026-06-01", "2026-06-30"), ("2026-07-01", "2026-07-31"), "2026-06-01", "closed", 0, False, None),
    ("12-inplace-move-in", "update", ("2026-05-01", "2026-05-31"), ("2026-06-01", "2026-06-30"), "2026-06-01", "closed", 0, False, None),
    ("13-inplace-shrink-out", "update", ("2026-05-01", "2026-06-30"), ("2026-05-01", "2026-05-31"), "2026-06-01", "closed", 0, False, None),
    ("14-inplace-union-gap", "update", ("2026-05-01", "2026-05-31"), ("2026-07-01", "2026-07-31"), "2026-06-01", "closed", 0, True, None),
    ("15-inplace-unbounded-far", "update", ("2020-01-01", None), ("2026-07-01", None), "2035-01-01", "closed", 0, False, None),
    ("16-inplace-open", "update", ("2026-07-01", "2026-07-31"), ("2026-07-01", "2026-07-31"), "2026-06-01", "closed", 0, True, None),
    ("17-delete-closed-range", "delete", ("2026-06-01", "2026-06-30"), None, "2026-06-01", "closed", 0, False, None),
    ("18-delete-closed-charge-fk", "delete", ("2026-07-01", "2026-07-31"), None, "2026-06-01", "closed", 0, False, None),
    ("19-delete-closed-in-period-fk", "delete", ("2026-07-01", "2026-07-31"), None, "2026-06-01", "closed", 0, False, None),
    ("20-delete-open-native", "delete", ("2026-07-01", "2026-07-31"), None, "2026-06-01", "closed", 0, True, None),
    ("21-delete-reopened", "delete", ("2026-06-01", "2026-06-30"), None, "2026-06-01", "reopened", 0, True, None),
    ("22-version-closed-past", "version", ("2026-01-01", None), ("2026-07-01", None), "2026-06-01", "closed", 0, True, "2026-06-30"),
    ("23-version-effective-closed", "version", ("2026-01-01", None), ("2026-06-15", None), "2026-06-01", "closed", 0, False, None),
    ("24-version-cut-tail-closed", "version", ("2026-01-01", "2026-12-31"), ("2026-07-01", "2026-07-31"), "2026-09-01", "closed", 0, False, None),
    ("25-version-expired-gap", "version", ("2026-01-01", "2026-05-31"), ("2026-07-01", "2026-07-31"), "2026-06-01", "closed", 0, True, "2026-05-31"),
    ("26-version-empty-tail", "version", ("2026-01-01", "2026-06-30"), ("2026-07-01", "2026-07-31"), "2026-06-01", "closed", 0, True, "2026-06-30"),
]
NATIVE_CASES = [
    "27-term-first-close-waits", "28-close-first-term-denied",
    "29-reopen-first-fresh-term", "30-other-company-independent",
    "31-shared-writers-independent", "32-no-shared-upgrade",
    "33-new-root-transaction", "34-refusal-no-autoflush",
]


@pytest_asyncio.fixture(loop_scope="session")
async def term_world(read_world):
    """Reuse the exact READ factory/cache, but never its business companies/rows."""
    factory = read_world.factory
    assert getattr(factory, "_rushydro_native_reads_world") is read_world
    w = SimpleNamespace(factory=factory, companies=(uuid4(), uuid4()),
        orgs=(uuid4(), uuid4()), parties=(uuid4(), uuid4()),
        contracts=(uuid4(), uuid4(), uuid4()), terms=(uuid4(), uuid4()),
        doc=uuid4(), charges=(uuid4(), uuid4()), cost="term-closed-" + uuid4().hex)
    async with factory() as db:
        assert (await db.scalar(text("SHOW transaction_isolation"))) == "read committed"
        db.add_all([Company(id=cid, name="Synthetic closed term", slug="term-" + cid.hex,
                            profile_id="energy", tz="Europe/Moscow") for cid in w.companies])
        await db.flush()
        db.add_all([Organization(id=oid, company_id=cid, name="Synthetic organization", inn="")
                    for oid, cid in zip(w.orgs, w.companies)])
        db.add_all([Counterparty(id=pid, company_id=cid, name="Synthetic party", is_group=False)
                    for pid, cid in zip(w.parties, w.companies)])
        db.add(OpsCostItem(code=w.cost, label="Synthetic closed term", measure="fixed",
                          default_estimate_basis="contract", is_active=True))
        await db.flush()
        for index, company_index in ((0, 0), (1, 0), (2, 1)):
            db.add(Contract(id=w.contracts[index], company_id=w.companies[company_index],
                organization_id=w.orgs[company_index], counterparty_id=w.parties[company_index],
                number="SYN-TERM-" + str(index), date="2026-01-01", valid_until="2030-12-31",
                type="service", type_code=TYPE, scope_type="company", is_closed=False))
        await db.flush()
        db.add(OpsCounterpartyDoc(id=w.doc, company_id=w.companies[0], contract_id=w.contracts[0],
            doc_type="act", period="2026-06-01", amount_gross=100, parse_status="manual",
            match_status="manual"))
        await db.commit()
    yield w
    # ROOT owns whole-database disposal; no shared fixtures or rows are deleted.


def term_row(w, *, index=0, start="2026-07-01", end="2026-07-31"):
    return OpsContractTerm(id=w.terms[index], company_id=w.companies[0],
        contract_id=w.contracts[index], cost_item=w.cost, scope_type="company",
        periodicity="monthly", valid_from=start, valid_to=end,
        amount_gross=100, estimate_basis="contract", source="manual")


def payload(w, start="2026-07-01", end="2026-07-31"):
    return {"contractId": str(w.contracts[0]), "costItem": w.cost, "scopeType": "company",
            "amountGross": 200, "validFrom": start, "validTo": end}


async def snapshot(w, db=None):
    """Full persisted rows of just our two companies; includes history and FKs."""
    if db is None:
        async with w.factory() as owned:
            return await snapshot(w, owned)
    with db.no_autoflush:
        result = {}
        for model in (Contract, OpsContractTerm, OpsCounterpartyDoc, OpsPeriodCharge, OpsPeriodClose):
            rows = (await db.execute(select(model.__table__).where(
                model.company_id.in_(w.companies)).order_by(model.id))).mappings().all()
            result[model.__name__] = [dict(row) for row in rows]
        return result


async def seed_case(w, case):
    identifier, action, old, new, month, status, company_index, allowed, old_end = case
    async with w.factory() as db:
        db.add(OpsPeriodClose(company_id=w.companies[company_index], period=month, status=status,
            summary={"syntheticFrozen": [100, "history"]}, total_expected_gross=100))
        if identifier == "06-create-unbounded-far":
            contract = await db.get(Contract, w.contracts[0])
            contract.valid_until = None  # Native create inherits a finite default otherwise.
        if old is not None:
            db.add(term_row(w, start=old[0], end=old[1]))
            await db.flush()
            charge_period = "2026-06-01" if action == "version" else old[0][:7] + "-01"
            if identifier == "18-delete-closed-charge-fk":
                charge_period = "2026-06-01"
            db.add(OpsPeriodCharge(id=w.charges[1], company_id=w.companies[0],
                contract_id=w.contracts[0], term_id=w.terms[0], cost_item=w.cost,
                period=charge_period, seq=1, status="matched", doc_id=w.doc,
                closed_in_period="2026-06-01" if identifier == "19-delete-closed-in-period-fk" else None,
                expected_gross=100, actual_gross=100, expected_basis="contract"))
            if action == "delete":
                db.add(OpsPeriodCharge(id=w.charges[0], company_id=w.companies[0],
                    contract_id=w.contracts[0], term_id=w.terms[0], cost_item=w.cost,
                    period=old[0][:7] + "-01", seq=0, status="expected", doc_id=None,
                    expected_gross=100, expected_basis="contract"))
        await db.commit()


@pytest.mark.parametrize("case", FUNCTIONAL_CASES, ids=[row[0] for row in FUNCTIONAL_CASES])
async def test_functional(term_world, case):
    w = term_world
    identifier, action, old, new, month, status, company_index, allowed, old_end = case
    await seed_case(w, case)
    before = await snapshot(w)
    async with w.factory() as db:
        root = await db.connection()
        transaction = db.sync_session.get_transaction()

        async def invoke():
            if action == "create-defaults":
                return await create_term(db, w.companies[0], {"contractId": str(w.contracts[0]),
                    "costItem": w.cost, "scopeType": "company", "amountGross": 200})
            if action == "create":
                return await create_term(db, w.companies[0], payload(w, *new))
            if action == "delete":
                return await delete_term(db, w.companies[0], w.terms[0])
            return await update_term(db, w.companies[0], w.terms[0], payload(w, *new),
                                     new_version=action == "version")

        if not allowed:
            reason = ("^Условие связано с историей закрытого периода$"
                      if identifier == "19-delete-closed-in-period-fk"
                      else "^Условие затрагивает закрытый период$")
            with pytest.raises(ValueError, match=reason):
                await invoke()
            assert db.sync_session.get_transaction() is transaction and root.in_transaction()
            assert not db.new and not db.dirty and not db.deleted
            assert await snapshot(w, db) == before
            assert await snapshot(w) == before
            await db.rollback()
            assert await snapshot(w) == before
            return

        result = await invoke()
        assert db.sync_session.get_transaction() is transaction and root.in_transaction()
        # Explicitly finish outside owners, then inspect real FK/unique effects.
        await db.commit()
    after = await snapshot(w)
    assert after["Contract"] == before["Contract"]
    assert after["OpsPeriodClose"] == before["OpsPeriodClose"]
    assert after["OpsCounterpartyDoc"] == before["OpsCounterpartyDoc"]
    async with w.factory() as db:
        terms = (await db.execute(select(OpsContractTerm).where(
            OpsContractTerm.company_id == w.companies[0]).order_by(OpsContractTerm.valid_from))).scalars().all()
        if action == "delete":
            assert result == {"ok": True, "removedCharges": 1} and terms == []
            assert await db.get(OpsPeriodCharge, w.charges[0]) is None
            retained = await db.get(OpsPeriodCharge, w.charges[1])
            assert retained.term_id is None and retained.doc_id == w.doc
            assert retained.status == "matched" and retained.actual_gross == Decimal("100.00")
        else:
            assert after["OpsPeriodCharge"] == before["OpsPeriodCharge"]
            expected_count = 2 if action == "version" else 1
            assert len(terms) == expected_count
            current = terms[-1]
            assert (current.valid_from, current.valid_to) == new
            assert current.amount_gross == Decimal("200.00")
            assert current.contract_id == w.contracts[0] and current.cost_item == w.cost
            assert current.company_id == w.companies[0] and current.location_id is None
            assert current.scope_type == "company" and str(current.id) == result["id"]
            if action == "version":
                assert current.id != w.terms[0] and terms[0].id == w.terms[0]
                assert (terms[0].valid_from, terms[0].valid_to, terms[0].amount_gross) == (
                    "2026-01-01", old_end, Decimal("100.00"))
                assert old_end < current.valid_from
            elif action == "update":
                assert current.id == w.terms[0]
            # A duplicate key cannot hide behind an ORM-only return value.
            assert len({(t.contract_id, t.cost_item, t.location_id or "", t.valid_from) for t in terms}) == expected_count
    if identifier == "21-delete-reopened":
        # Second independent term: reopened alone permits deletion, but an
        # un-cleared historical marker must preserve this different term's FK.
        historic_charge = uuid4()
        async with w.factory() as db:
            db.add(term_row(w, index=1, start="2026-06-01", end="2026-06-30"))
            await db.flush()
            db.add(OpsPeriodCharge(id=historic_charge, company_id=w.companies[0],
                contract_id=w.contracts[1], term_id=w.terms[1], cost_item=w.cost,
                period="2026-06-01", seq=0, status="accrued", doc_id=w.doc,
                expected_gross=100, closed_in_period="2026-06-01"))
            await db.commit()
        frozen = await snapshot(w)
        async with w.factory() as db:
            with pytest.raises(ValueError, match="историей закрытого периода"):
                await delete_term(db, w.companies[0], w.terms[1])
            assert await snapshot(w, db) == frozen
            linked = await db.get(OpsPeriodCharge, historic_charge)
            assert linked.term_id == w.terms[1] and linked.doc_id == w.doc
            assert linked.closed_in_period == "2026-06-01"
            await db.rollback()
        assert await snapshot(w) == frozen


@asynccontextmanager
async def observed(db):
    """Observe real statements only; never replace SQL, results or owners."""
    connection = await db.connection()
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(connection.sync_connection, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", record)


async def blocked_by(observer, waiter_pid, holder_pid, mode):
    """A PG wait graph, not elapsed time, decides that the owner is blocked."""
    async with asyncio.timeout(15):
        while True:
            found = await observer.scalar(text(
                "SELECT :holder = ANY(pg_blocking_pids(:waiter)) AND EXISTS ("
                "SELECT 1 FROM pg_locks WHERE pid = :waiter AND locktype = 'advisory' "
                "AND NOT granted AND mode = :mode)"),
                {"holder": holder_pid, "waiter": waiter_pid, "mode": mode})
            if found:
                return
            # The awaited real SQL round trip yields the event loop. No sleep
            # duration or absence of an Event is ever used as a pass verdict.


async def start_call(ready, call):
    ready.set()
    return await call()


async def cleanup_tasks(tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    async with asyncio.timeout(10):
        await asyncio.gather(*tasks, return_exceptions=True)


async def seed_race(w, *, second=False):
    async with w.factory() as db:
        db.add(term_row(w))
        if second:
            db.add(term_row(w, index=1))
        await db.commit()


@pytest.mark.parametrize("identifier", NATIVE_CASES, ids=NATIVE_CASES)
async def test_native_protocol(term_world, identifier):
    w = term_world
    await seed_race(w, second=identifier == "31-shared-writers-independent")
    if identifier == "34-refusal-no-autoflush":
        await refusal_protocol(w)
        return
    if identifier == "32-no-shared-upgrade":
        async with w.factory() as db:
            await update_term(db, w.companies[0], w.terms[0], {"amountGross": 200})
            before = await snapshot(w, db)
            async with observed(db) as sql:
                with pytest.raises(ValueError, match="отдельных транзакций"):
                    await close_period(db, w.companies[0], "2026-07-01")
                assert not sql  # No upgrade attempt or get_or_create side effect.
            assert await snapshot(w, db) == before
            await db.rollback()
        return
    if identifier == "33-new-root-transaction":
        await transaction_protocol(w)
        return

    tasks = []
    async with w.factory() as holder, w.factory() as waiter, w.factory() as observer:
        try:
            async with asyncio.timeout(25):
                hp = await holder.scalar(text("SELECT pg_backend_pid()"))
                wp = await waiter.scalar(text("SELECT pg_backend_pid()"))
                assert hp != wp
                ready = asyncio.Event()
                if identifier == "27-term-first-close-waits":
                    async with observed(holder) as sql:
                        await update_term(holder, w.companies[0], w.terms[0], {"amountGross": 200})
                    assert "pg_advisory_xact_lock_shared" in sql[0]
                    assert "ops-term-window" not in sql[0]
                    assert "pg_advisory_xact_lock(" in sql[2]
                    assert "FOR UPDATE" in sql[3]
                    tasks.append(asyncio.create_task(start_call(ready, lambda: close_period(
                        waiter, w.companies[0], "2026-07-01"))))
                    await ready.wait()
                    await blocked_by(observer, wp, hp, "ExclusiveLock")
                    assert not tasks[0].done()
                    await holder.commit()
                    assert (await tasks[0])["ok"] is True
                    await waiter.commit()
                    charge = await observer.scalar(select(OpsPeriodCharge).where(
                        OpsPeriodCharge.company_id == w.companies[0],
                        OpsPeriodCharge.term_id == w.terms[0], OpsPeriodCharge.seq == 0))
                    assert charge.status == "accrued" and charge.expected_gross == Decimal("200.00")
                elif identifier in ("28-close-first-term-denied", "29-reopen-first-fresh-term"):
                    stale = await waiter.get(OpsContractTerm, w.terms[0])
                    if identifier == "29-reopen-first-fresh-term":
                        assert (await close_period(holder, w.companies[0], "2026-07-01"))["ok"]
                        await holder.commit()
                        stale_close = await waiter.scalar(select(OpsPeriodClose).where(
                            OpsPeriodClose.company_id == w.companies[0]))
                        assert stale_close.status == "closed"
                        assert (await reopen_period(holder, w.companies[0], "2026-07-01",
                                                    "Synthetic reopen"))["status"] == "reopened"
                    else:
                        assert (await close_period(holder, w.companies[0], "2026-07-01"))["ok"]
                    # Test the latest persisted term columns as well as close state.
                    # Holder already owns exclusive; a nested term operation cannot upgrade.
                    if identifier == "29-reopen-first-fresh-term":
                        await update_term(holder, w.companies[0], w.terms[0],
                                          {"note": "fresh-after-reopen", "validFrom": "2026-07-10"})
                        # commit above may have returned an earlier connection;
                        # identify the real backend of this new holder TX.
                        hp = await holder.scalar(text("SELECT pg_backend_pid()"))
                    tasks.append(asyncio.create_task(start_call(ready, lambda: update_term(
                        waiter, w.companies[0], w.terms[0], {"amountGross": 300}))))
                    await ready.wait()
                    await blocked_by(observer, wp, hp, "ShareLock")
                    assert not tasks[0].done()
                    await holder.commit()
                    frozen = await snapshot(w)
                    if identifier == "28-close-first-term-denied":
                        with pytest.raises(ValueError, match="закрытый период"):
                            await tasks[0]
                        assert stale.amount_gross == Decimal("100.00")
                        await waiter.rollback()
                        assert await snapshot(w) == frozen
                    else:
                        result = await tasks[0]
                        assert result["amountGross"] == 300 and result["note"] == "fresh-after-reopen"
                        assert result["validFrom"] == "2026-07-10" and result["validTo"] == "2026-07-31"
                        await waiter.commit()
                        assert stale.note == "fresh-after-reopen"
                        reopened = await observer.scalar(select(OpsPeriodClose).where(
                            OpsPeriodClose.company_id == w.companies[0]).execution_options(populate_existing=True))
                        assert reopened.status == "reopened"
                elif identifier in ("30-other-company-independent", "31-shared-writers-independent"):
                    if identifier == "30-other-company-independent":
                        assert (await close_period(holder, w.companies[1], "2026-07-01"))["ok"]
                        target = w.terms[0]
                    else:
                        await update_term(holder, w.companies[0], w.terms[0], {"amountGross": 200})
                        target = w.terms[1]
                    tasks.append(asyncio.create_task(start_call(ready, lambda: update_term(
                        waiter, w.companies[0], target, {"amountGross": 300}))))
                    await ready.wait()
                    assert (await tasks[0])["amountGross"] == 300
                    # Positive progress while the real holder TX and barrier remain open.
                    assert holder.in_transaction()
                    assert await observer.scalar(text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid "
                        "AND locktype='advisory' AND granted AND mode=:mode)"),
                        {"pid": hp, "mode": "ExclusiveLock" if identifier.startswith("30-") else "ShareLock"})
                    await waiter.commit()
                    await holder.commit()
                else:
                    raise AssertionError("Unknown frozen native case")
        finally:
            await cleanup_tasks(tasks)
            await waiter.rollback()
            await holder.rollback()
            await observer.rollback()


async def transaction_protocol(w):
    async with w.factory() as db:
        await update_term(db, w.companies[0], w.terms[0], {"amountGross": 200})
        first = db.sync_session.get_transaction()
        await db.commit()
        assert (await close_period(db, w.companies[0], "2026-07-01"))["ok"]
        assert db.sync_session.get_transaction() is not first
        await db.rollback()  # Close was not committed; July is still open.
        await update_term(db, w.companies[0], w.terms[0], {"amountGross": 250})
        second = db.sync_session.get_transaction()
        await db.rollback()
        assert (await close_period(db, w.companies[0], "2026-07-01"))["ok"]
        assert db.sync_session.get_transaction() is not second
        await db.commit()
        assert (await reopen_period(db, w.companies[0], "2026-07-01", "Synthetic reason"))["ok"]
        # Existing exclusive -> term shared needs no lock upgrade or downgrade.
        async with observed(db) as sql:
            assert (await update_term(db, w.companies[0], w.terms[0], {"amountGross": 300}))["amountGross"] == 300
        assert not any("pg_advisory_xact_lock_shared" in statement for statement in sql)
        await db.commit()
        row = await db.get(OpsContractTerm, w.terms[0], populate_existing=True)
        assert row.amount_gross == Decimal("300.00")
        # Savepoints fail closed before SQL; rolling them back cannot leave a
        # cached Python claim that a released PostgreSQL lock is still held.
        async with db.begin_nested():
            async with observed(db) as sql:
                with pytest.raises(ValueError, match="вложенную транзакцию"):
                    await update_term(db, w.companies[0], w.terms[0], {"amountGross": 400})
                assert not sql
        await db.rollback()


async def refusal_protocol(w):
    async with w.factory() as setup:
        assert (await close_period(setup, w.companies[0], "2026-07-01"))["ok"]
        await setup.commit()
    before = await snapshot(w)
    async with w.factory() as db:
        existing = await db.get(OpsContractTerm, w.terms[0])
        contract = await db.get(Contract, w.contracts[1])
        existing.note = "caller-dirty-do-not-refresh"
        contract.date = "2026-08-01"  # Dirty default must not influence create.
        pending = term_row(w, index=1, start="2026-08-01", end="2026-08-31")
        db.add(pending)
        dirty, new = set(db.dirty), set(db.new)
        transaction = db.sync_session.get_transaction()
        async with observed(db) as sql:
            for call in (
                lambda: update_term(db, w.companies[0], w.terms[0], {"amountGross": 200}),
                lambda: delete_term(db, w.companies[0], w.terms[0]),
                lambda: update_term(db, w.companies[0], w.terms[0],
                                    {"validFrom": "2026-07-15"}, new_version=True),
                lambda: create_term(db, w.companies[0], payload(w, "2026-07-01", "2026-07-31")),
            ):
                # create overlaps the native term slot; it must retain that
                # native error rather than reach the closed-period predicate.
                with pytest.raises(ValueError):
                    await call()
                assert set(db.dirty) == dirty and set(db.new) == new and not db.deleted
                assert existing.note == "caller-dirty-do-not-refresh"
                assert contract.date == "2026-08-01" and pending in db.new
                assert db.sync_session.get_transaction() is transaction
            # A different slot reaches the guard using FRESH contract defaults,
            # including January..2030 rather than the dirty August start.
            with pytest.raises(ValueError, match="закрытый период"):
                await create_term(db, w.companies[0], {"contractId": str(w.contracts[1]),
                    "costItem": w.cost, "scopeType": "company"})
            for invalid in ({"validFrom": "2026-99-01"},
                            {"validFrom": "2026-08-01", "validTo": "2026-07-01"}):
                with pytest.raises(ValueError):
                    await update_term(db, w.companies[0], w.terms[0], invalid)
            for call in (
                lambda: update_term(db, w.companies[1], w.terms[0], {}),
                lambda: delete_term(db, w.companies[1], w.terms[0]),
                lambda: create_term(db, w.companies[1], payload(w)),
            ):
                with pytest.raises(ValueError, match="не найден"):
                    await call()
        assert not any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "COMMIT"))
                       for statement in sql)
        assert set(db.dirty) == dirty and set(db.new) == new and not db.deleted
        assert existing.note == "caller-dirty-do-not-refresh" and contract.date == "2026-08-01"
        assert await snapshot(w, db) == before and await snapshot(w) == before
        await db.rollback()
    assert await snapshot(w) == before
