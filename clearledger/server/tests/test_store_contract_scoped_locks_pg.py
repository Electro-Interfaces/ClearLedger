"""AUTHORED / NOTRUN: actual Store callers + frozen helper on disposable PG.

ROOT must review a separate database, schema and isolated execution composition
BEFORE importing this module, app, helper or repository conftest. Ordinary
pytest is unsafe: conftest may run first and drop schemas. No runner, DDL,
installer, working-data fallback or claim of executed cases is supplied here.
Schema prerequisite: reviewed app schema including core contract columns and
edge.partner/partner_station, provisioned by ROOT in the named disposable DB.
"""
import os
from urllib.parse import urlsplit

_URL = os.environ.get("STORE_CONTRACT_SCOPED_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (
    _URL and _URL == os.environ.get("STORE_CONTRACT_SCOPED_PG_ROOT_APPROVED_URL")
    and _URL == os.environ.get("DATABASE_URL")
    and _URL == os.environ.get("TEST_DATABASE_URL")
    and os.environ.get("STORE_CONTRACT_SCOPED_PG_APPROVAL") == "ROOT-approved-synthetic-store-b-v1"
    and _TARGET.scheme == "postgresql+asyncpg"
    and _TARGET.hostname == "127.0.0.1" and _TARGET.port and _TARGET.password
    and _TARGET.path == "/api_store_contract_scoped_test_20261101"
    and not _TARGET.query and not _TARGET.fragment
):
    raise RuntimeError("Separate ROOT-reviewed disposable Store-B composition required before imports")

# All non-stdlib and application imports are below the explicit target guard.
import asyncio
from contextlib import asynccontextmanager
from copy import copy
from dataclasses import replace
from time import monotonic
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Company, Contract, Counterparty, Organization, User, UserCompany
from app.routers import store_router as router
from app.services import contract_write_locks as locks
from app.services import store_contract_commands as commands

pytestmark = pytest.mark.asyncio(loop_scope="session")
S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE


@pytest_asyncio.fixture(loop_scope="session")
async def world():
    # Independent pool/leases: never bind two callers to a fixture savepoint.
    engine = create_async_engine(_URL, pool_size=6, max_overflow=0,
                                 isolation_level="READ COMMITTED")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex
    async with factory() as db:
        company = Company(id=uuid4(), name="Synthetic Store B", slug=f"store-b-{token}", profile_id="energy")
        other = Company(id=uuid4(), name="Synthetic foreign Store B", slug=f"other-b-{token}", profile_id="energy")
        db.add_all([company, other])
        await db.flush()
        cp = Counterparty(id=uuid4(), company_id=company.id, name="Synthetic CP", aliases=[])
        org = Organization(id=uuid4(), company_id=company.id, name="Synthetic Org", inn="", prefix="S")
        admin = User(id=uuid4(), company_id=company.id, email=f"{token}@store-b.invalid",
                     name="Synthetic admin", password_hash="synthetic-noncredential", is_superadmin=True)
        station_user = User(id=uuid4(), company_id=company.id, email=f"s-{token}@store-b.invalid",
                            name="Synthetic station", password_hash="synthetic-noncredential", is_superadmin=False)
        db.add_all([cp, org, admin, station_user])
        await db.flush()
        db.add(UserCompany(user_id=station_user.id, company_id=company.id, business_grants=[{
            "role": "station_administrator", "scope_type": "station", "scope_id": "3"}]))
        await db.commit()
        yield_data = dict(engine=engine, factory=factory, cid=company.id, foreign=other.id,
                          cp=cp.id, org=org.id, uid=admin.id, station_uid=station_user.id)
    from types import SimpleNamespace
    try:
        yield SimpleNamespace(**yield_data)
    finally:
        # No schema drops or automatic destructive cleanup. ROOT owns disposable DB teardown.
        await engine.dispose()


@pytest.fixture
def sql_log(world):
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(world.engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(world.engine.sync_engine, "before_cursor_execute", record)


def body(w, **changes):
    return {"counterparty_id": str(w.cp), "organization_id": str(w.org),
            "number": "Synthetic-B-1", "date": "2026-02-03", **changes}


def mixed(w, **changes):
    return {"name": "Synthetic mixed CP", "contract": {
        "organization_id": str(w.org), "number": "Synthetic-mixed-1", "date": "2026-02-03"}, **changes}


def future_create_protocol(w):
    # Synthetic protocol participant ONLY. No implemented future HTTP/native CREATE claim.
    return locks.LockPlan((locks.LockRequest(locks.CompanyKey(w.cid), S),
                           locks.LockRequest(locks.RefCompositeKey(w.cid), S)))


async def pid(db):
    return await db.scalar(text("SELECT pg_backend_pid()"))


async def rows(observer, key):
    namespace, lock_key = locks.advisory_key(key)
    return (await observer.execute(text("""
        SELECT pid, mode, granted FROM pg_locks
        WHERE locktype='advisory' AND classid=:ns AND objid=:key AND objsubid=2
          AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
    """), {"ns": namespace, "key": lock_key & 0xFFFFFFFF})).all()


async def blocked(observer, waiter, owner, key, mode):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        blockers = await observer.scalar(text("SELECT pg_blocking_pids(:p)"), {"p": waiter})
        actual = await rows(observer, key)
        if owner in blockers and (waiter, mode, False) in actual:
            assert any(row.pid == owner and row.granted for row in actual)
            return
        await asyncio.sleep(.01)
    raise AssertionError("No actual blocking_pids + ungranted two-int pg_locks evidence")


@asynccontextmanager
async def running(factory, invoke):
    ready, details = asyncio.Event(), {}

    async def call():
        async with factory() as db:
            details["pid"] = await pid(db)
            details["db"] = db
            ready.set()
            return await invoke(db)

    task = asyncio.create_task(call())
    try:
        await asyncio.wait_for(ready.wait(), 10)
        yield details, task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("route", ["contract", "mixed"])
async def test_actual_router_waits_behind_synthetic_future_create_before_any_write(world, sql_log, route):
    w = world
    seen = []

    async def invoke(db):
        user = await db.get(User, w.uid)
        if route == "contract":
            # Forged selectors/capability in body must not become the authority/key.
            return await router.store_contract_save(body(w, company_id=str(w.foreign), capability="forged"), user, db)
        return await router.store_partner_create(mixed(w, company_id=str(w.foreign)), user, db)

    async with w.factory() as owner, w.factory() as observer:
        declaration = future_create_protocol(w)
        capability = await locks.acquire_scoped_locks_async(owner, declaration)
        owner_pid = await pid(owner)
        async with running(w.factory, invoke) as (details, task):
            await blocked(observer, details["pid"], owner_pid, locks.RefCompositeKey(w.cid), "ExclusiveLock")
            waiting_db = details["db"]
            assert not waiting_db.new and not waiting_db.dirty and not waiting_db.deleted
            assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in sql_log)
            assert (details["pid"], "ShareLock", True) in await rows(observer, locks.CompanyKey(w.cid))
            # Observer sees no CP/edge/contract writes before B completes.
            assert await observer.scalar(select(func.count()).select_from(Contract).where(Contract.company_id == w.cid)) == 0
            assert await observer.scalar(select(func.count()).select_from(Counterparty).where(Counterparty.company_id == w.cid)) == 1
            locks.require_scoped_locks(owner.sync_session, capability, declaration.requests)
            await owner.rollback()
            response = await asyncio.wait_for(task, 10)
            seen.append(response)
        uid = UUID(seen[0]["id"] if route == "contract" else seen[0]["contract_id"])
        card = await observer.get(Contract, uid, populate_existing=True)
        assert card.company_id == w.cid and card.organization_id == w.org
        assert card.scope_type == "unassigned" and card.is_closed is False
        assert card.raw["source"] == "center_manual"
        scoped_sql = [i for i, sql in enumerate(sql_log) if "pg_advisory_xact_lock" in sql and "CAST" in sql]
        legacy_sql = [i for i, sql in enumerate(sql_log) if "pg_advisory_xact_lock" in sql and "CAST" not in sql]
        writes = [i for i, sql in enumerate(sql_log) if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        assert scoped_sql and len(legacy_sql) == 2 and writes
        assert max(scoped_sql) < min(legacy_sql) < max(legacy_sql) < min(writes)


@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_actual_store_command_holds_full_plan_until_caller_end_then_future_protocol_reads(world, finish):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        prepared = await commands.prepare_store_contract(owner, w.cid, body(w))
        root = owner.sync_session.get_transaction()
        owner_pid = await pid(owner)

        async def future_protocol(db):
            declaration = future_create_protocol(w)
            cap = await locks.acquire_scoped_locks_async(db, declaration)
            locks.require_scoped_locks(db.sync_session, cap, declaration.requests)
            cards = (await db.scalars(select(Contract).where(Contract.company_id == w.cid))).all()
            return [(c.number, c.counterparty_id, c.organization_id) for c in cards]

        async with running(w.factory, future_protocol) as (details, task):
            await blocked(observer, details["pid"], owner_pid, locks.RefCompositeKey(w.cid), "ShareLock")
            card = await commands.save_store_contract(owner, w.cid, body(w), prepared=prepared)
            await owner.flush()
            assert owner.sync_session.get_transaction() is root
            commands.require_store_contract_write(owner, w.cid, prepared)
            assert not task.done()
            assert await observer.get(Contract, card.id) is None
            await getattr(owner, finish)()
            assert await asyncio.wait_for(task, 10) == (
                [("Synthetic-B-1", w.cp, w.org)] if finish == "commit" else [])


@pytest.mark.parametrize("end", ["commit", "rollback", "savepoint"])
async def test_actual_commands_reject_stale_cap_before_reads_or_mutation_without_late_acquire(world, end):
    w = world
    async with w.factory() as db:
        plan = await commands.prepare_store_partner_contract(db, w.cid, mixed(w)["contract"])
        if end == "savepoint":
            nested = await db.begin_nested()
            await nested.rollback()
        else:
            await getattr(db, end)()
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(w.engine.sync_engine, "before_cursor_execute", record)
        try:
            with pytest.raises(locks.ScopedLockError):
                await commands.save_store_contract(db, w.cid, body(w), prepared=plan.prepared)
            with pytest.raises(locks.ScopedLockError):
                await commands.create_store_partner_contract(db, w.cid, w.cp, plan)
            assert statements == [] and not db.new and not db.dirty
        finally:
            event.remove(w.engine.sync_engine, "before_cursor_execute", record)
            await db.rollback()


async def test_actual_commands_reject_foreign_copied_forged_and_undercovered_receipts(world):
    w = world
    async with w.factory() as issuer, w.factory() as foreign:
        prepared = await commands.prepare_store_contract(issuer, w.cid, body(w))
        for db, candidate in [
            (foreign, prepared),
            (issuer, replace(prepared, capability=copy(prepared.capability))),
            (issuer, replace(prepared, capability=locks.ScopedLockCapability(prepared.capability.plan))),
            (issuer, replace(prepared, company_id=w.foreign)),
        ]:
            with pytest.raises(locks.ScopedLockError):
                await commands.save_store_contract(db, w.cid, body(w), prepared=candidate)
            assert not db.new and not db.dirty
        # Foreign/copy attempts do not poison the valid issuer's own receipt.
        commands.require_store_contract_write(issuer, w.cid, prepared)
        await issuer.rollback()
    async with w.factory() as db:
        cap = await locks.acquire_scoped_locks_async(db, future_create_protocol(w))
        undercovered = commands.PreparedStoreContractWrite(w.cid, cap)
        with pytest.raises(locks.ScopedLockError, match="not declared"):
            await commands.save_store_contract(db, w.cid, body(w), prepared=undercovered)
        assert not db.new and not db.dirty
        await db.rollback()


async def test_actual_preparation_partial_acquisition_poison_and_no_reentry(world):
    w = world
    class Interrupted(BaseException):
        pass

    async with w.factory() as db, w.factory() as observer:
        connection = (await db.connection()).sync_connection
        db_pid = await pid(db)
        lock_sql = []
        def interrupt(conn, cursor, statement, parameters, context, executemany):
            if "pg_advisory_xact_lock" in statement:
                lock_sql.append(statement)
                if len(lock_sql) == 2:
                    raise Interrupted()
        event.listen(connection, "before_cursor_execute", interrupt)
        try:
            with pytest.raises(Interrupted):
                await commands.prepare_store_contract(db, w.cid, body(w))
            assert len(lock_sql) == 2
            assert (db_pid, "ShareLock", True) in await rows(observer, locks.CompanyKey(w.cid))
            for prepare in [
                lambda: commands.prepare_store_contract(db, w.cid, body(w)),
                lambda: commands.prepare_store_partner_contract(db, w.cid, mixed(w)["contract"]),
            ]:
                with pytest.raises(locks.ScopedLockError, match="already attempted"):
                    await prepare()
            assert len(lock_sql) == 2 and not db.new and not db.dirty
        finally:
            event.remove(connection, "before_cursor_execute", interrupt)
            await db.rollback()
        prepared = await commands.prepare_store_contract(db, w.cid, body(w))
        await commands.save_store_contract(db, w.cid, body(w), prepared=prepared)
        await db.rollback()


@pytest.mark.parametrize("route", ["contract", "mixed", "no_contract"])
@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
async def test_actual_router_pending_entry_rejects_before_first_discovery_or_autoflush(world, route, pending):
    w = world
    async with w.factory() as db:
        user = await db.get(User, w.uid)
        if pending == "new":
            db.add(Counterparty(company_id=w.cid, name="Pending synthetic CP", aliases=[]))
        else:
            cp = await db.get(Counterparty, w.cp)
            if pending == "dirty":
                cp.name = "Pending synthetic change"
            else:
                await db.delete(cp)
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(w.engine.sync_engine, "before_cursor_execute", record)
        try:
            with pytest.raises(locks.ScopedLockError, match="clean entry"):
                if route == "contract":
                    await router.store_contract_save(body(w), user, db)
                else:
                    await router.store_partner_create(mixed(w, contract={} if route == "no_contract" else mixed(w)["contract"]), user, db)
            assert statements == []
            assert getattr(db, pending)  # Pending state was refused, never cleared by a fake flush.
        finally:
            event.remove(w.engine.sync_engine, "before_cursor_execute", record)
            await db.rollback()


@pytest.mark.parametrize("contract", [None, {}])
async def test_actual_partner_absent_empty_contract_keeps_cp_pipeline_without_b_acquire(world, contract):
    w = world
    async with w.factory() as db:
        user = await db.get(User, w.uid)
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(w.engine.sync_engine, "before_cursor_execute", record)
        try:
            data = {"name": "Synthetic no-contract CP"}
            if contract is not None:
                data["contract"] = contract
            response = await router.store_partner_create(data, user, db)
            assert response["created"] is True and response["contract_id"] is None
            # Actual SQL proves absence of B (two-int CAST); legacy CP bigint remains.
            lock_sql = [s for s in statements if "pg_advisory_xact_lock" in s]
            assert len(lock_sql) == 1 and "CAST" not in lock_sql[0]
            assert await db.get(Counterparty, UUID(response["supplier_id"])) is not None
        finally:
            event.remove(w.engine.sync_engine, "before_cursor_execute", record)


async def test_actual_partner_existing_inn_returns_early_even_with_invalid_contract(world):
    w = world
    async with w.factory() as db:
        user = await db.get(User, w.uid)
        first = await router.store_partner_create({"name": "Synthetic existing INN", "inn": "0000000000"}, user, db)
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(w.engine.sync_engine, "before_cursor_execute", record)
        try:
            result = await router.store_partner_create(mixed(w, inn="0000000000", contract={"organization_id": "invalid"}), user, db)
            assert result == {"id": first["id"], "name": "Synthetic existing INN", "created": False}
            assert not any("pg_advisory" in sql or sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
        finally:
            event.remove(w.engine.sync_engine, "before_cursor_execute", record)
            await db.rollback()


async def test_actual_legacy_order_and_missing_prepared_never_late_acquire(world, monkeypatch):
    w = world
    async with w.factory() as db:
        events = []
        acquire, legacy = commands.acquire_scoped_locks_async, commands.lock_manual_creation
        async def scoped(db, declaration):
            events.append(("B", declaration.requests))
            return await acquire(db, declaration)
        async def old(db, cid, entity):
            events.append(("legacy", entity))
            return await legacy(db, cid, entity)
        monkeypatch.setattr(commands, "acquire_scoped_locks_async", scoped)
        monkeypatch.setattr(commands, "lock_manual_creation", old)
        with pytest.raises(locks.ScopedLockError):
            await commands.save_store_contract(db, w.cid, body(w), prepared=None)
        assert events == [] and not db.new
        prepared = await commands.prepare_store_contract(db, w.cid, body(w))
        assert events == [("B", (locks.LockRequest(locks.CompanyKey(w.cid), S),
                                  locks.LockRequest(locks.RefCompositeKey(w.cid), X))),
                          ("legacy", "counterparty"), ("legacy", "contract")]
        await commands.save_store_contract(db, w.cid, body(w), prepared=prepared)
        assert len(events) == 3
        with pytest.raises(locks.ScopedLockError):
            await commands.prepare_store_contract(db, w.cid, body(w))
        await db.rollback()


async def test_actual_command_revalidates_after_legacy_wait_boundary_on_same_root(world, monkeypatch):
    w = world
    legacy = commands.lock_manual_creation
    async def ended_while_waiting(db, cid, entity):
        await legacy(db, cid, entity)
        await db.rollback()
    monkeypatch.setattr(commands, "lock_manual_creation", ended_while_waiting)
    async with w.factory() as db:
        with pytest.raises(locks.ScopedLockError):
            await commands.prepare_store_contract(db, w.cid, body(w))
        assert not db.new and not db.dirty


async def test_actual_preparation_retains_company404_after_acquisition(world):
    w = world
    async with w.factory() as db:
        with pytest.raises(HTTPException) as missing:
            await commands.prepare_store_contract(db, uuid4(), body(w))
        assert missing.value.status_code == 404
        assert not db.new and not db.dirty and not db.deleted
        await db.rollback()


async def test_actual_router_access_and_inn_discovery_are_no_autoflush(world, monkeypatch):
    w = world
    actual = router._receipt_access
    calls = []
    async def access(user, db):
        assert db.autoflush is False and not db.new and not db.dirty and not db.deleted
        calls.append("access")
        return await actual(user, db)
    monkeypatch.setattr(router, "_receipt_access", access)
    async with w.factory() as db:
        user = await db.get(User, w.uid)
        connection = (await db.connection()).sync_connection
        def discovery(conn, cursor, statement, parameters, context, executemany):
            if "regexp_replace" in statement:
                assert db.autoflush is False
                calls.append("inn")
        event.listen(connection, "before_cursor_execute", discovery)
        try:
            await router.store_partner_create(mixed(w, inn="0000000001"), user, db)
            assert calls == ["access", "inn"]
        finally:
            event.remove(connection, "before_cursor_execute", discovery)


@pytest.mark.parametrize("route", ["contract", "mixed"])
async def test_actual_router_keeps_network403_and_required400_before_plan(world, route):
    w = world
    async with w.factory() as db:
        station = await db.get(User, w.station_uid)
        with pytest.raises(HTTPException) as forbidden:
            if route == "contract":
                await router.store_contract_save({}, station, db)
            else:
                await router.store_partner_create({}, station, db)
        assert forbidden.value.status_code == 403 and not db.new
        await db.rollback()
        admin = await db.get(User, w.uid)
        with pytest.raises(HTTPException) as missing:
            if route == "contract":
                await router.store_contract_save({}, admin, db)
            else:
                await router.store_partner_create({}, admin, db)
        assert missing.value.status_code == 400 and not db.new
        # Neither 400/403 attempted B: real helper can enter the same clean root.
        cap = await locks.acquire_scoped_locks_async(db, future_create_protocol(w))
        locks.require_scoped_locks(db.sync_session, cap, future_create_protocol(w).requests)
        await db.rollback()
