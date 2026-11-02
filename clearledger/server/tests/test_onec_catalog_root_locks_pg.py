"""AUTHORED / NOTRUN: joint OneC + native R1 composition, real PostgreSQL.

ROOT must freeze both source candidates and review a separate preimport runner.
The repository conftest imports the application and can DROP schemas BEFORE
this guard; ordinary pytest/collection is not safe or authorized by this file.
ROOT provisions and destroys the disposable synthetic DB; no DDL here.
Only the external OneC client is replaced, never service/guards/ORM/core locks.
"""
import os
from urllib.parse import urlsplit

_URL = os.environ.get("ONEC_CATALOG_ROOT_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (
    _URL and _URL == os.environ.get("ONEC_CATALOG_ROOT_APPROVED_URL")
    and _URL == os.environ.get("DATABASE_URL") == os.environ.get("TEST_DATABASE_URL")
    and os.environ.get("ONEC_CATALOG_ROOT_APPROVAL") == "ROOT-reviewed-joint-onec-r1-v1"
    and _TARGET.scheme == "postgresql+asyncpg" and _TARGET.hostname == "127.0.0.1"
    and _TARGET.port and _TARGET.password
    and _TARGET.path == "/onec_catalog_root_synthetic_20261101"
    and not _TARGET.query and not _TARGET.fragment
):
    raise RuntimeError("Separate ROOT-reviewed joint OneC/R1 preimport composition required")

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import native_claims_context
from app.models import Company, Contract, Counterparty, OneCConnection, OneCSyncLog, Organization, User, UserCompany
from app.routers import references_router
from app.schemas import ContractCreate, ContractUpdate
from app.scope import set_request_organization, set_request_scope
from app.services import contract_write_locks as locks
from app.services.native_contract_commands import create_native_contract
from app.services.onec.catalog_root_locks import prepare_catalog_root, require_catalog_root
from app.services.onec.sync_service import OneCSyncService
from app.services.onec.odata_client import ENTITY_CONTRACTS, ENTITY_COUNTERPARTIES, ENTITY_ORGANIZATIONS

pytestmark = pytest.mark.asyncio(loop_scope="session")
S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE


@pytest_asyncio.fixture(loop_scope="session")
async def world():
    engine = create_async_engine(_URL, pool_size=8, max_overflow=0, isolation_level="READ COMMITTED")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex[:16]
    async with factory() as db:
        company = Company(id=uuid4(), name="Synthetic OneC", slug=f"oc-{token}", profile_id="energy")
        other = Company(id=uuid4(), name="Synthetic other", slug=f"oo-{token}", profile_id="energy")
        db.add_all([company, other])
        await db.flush()
        actor = User(id=uuid4(), company_id=company.id, email=f"{token}@onec.invalid",
                     name="Synthetic ordinary member", password_hash="synthetic-noncredential", is_superadmin=False)
        cp = Counterparty(id=uuid4(), company_id=company.id, name="Synthetic CP old", aliases=[],
                          external_ref=str(uuid4()), raw={})
        orgs = [Organization(id=uuid4(), company_id=company.id, name=f"Synthetic org old {i}",
                             inn="", external_ref=str(uuid4())) for i in range(2)]
        connection = OneCConnection(id=uuid4(), company_id=company.id, name="Synthetic OneC connection",
            mode="odata", odata_url="https://synthetic.invalid", username="synthetic",
            password_encrypted="synthetic-noncredential")
        db.add_all([actor, cp, *orgs, connection])
        await db.flush()
        db.add(UserCompany(user_id=actor.id, company_id=company.id, role="user"))
        contract = Contract(id=uuid4(), company_id=company.id, counterparty_id=cp.id,
            organization_id=orgs[0].id, number="Synthetic contract old", date="2026-01-02",
            type="Прочее", external_ref=str(uuid4()), raw={}, scope_type="unassigned")
        db.add(contract)
        await db.commit()
        w = SimpleNamespace(engine=engine, factory=factory, cid=company.id, other=other.id,
            uid=actor.id, cp=cp.id, orgs=tuple(o.id for o in orgs), connection=connection.id,
            contract=contract.id, cp_ref=cp.external_ref, org_refs=tuple(o.external_ref for o in orgs),
            contract_ref=contract.external_ref)
    set_request_scope(None)
    set_request_organization(None)
    try:
        with native_claims_context(None, None):
            yield w
    finally:
        set_request_scope(None)
        set_request_organization(None)
        await engine.dispose()


@pytest.fixture
def trace(world):
    labels, rows = {}, []
    def record(conn, cursor, statement, parameters, context, executemany):
        rows.append((labels.get(id(conn)), statement, parameters))
    event.listen(world.engine.sync_engine, "before_cursor_execute", record)
    try:
        yield SimpleNamespace(labels=labels, rows=rows)
    finally:
        event.remove(world.engine.sync_engine, "before_cursor_execute", record)


async def identify(db, trace, label):
    conn = await db.connection()
    trace.labels[id(conn.sync_connection)] = label
    return await db.scalar(text("SELECT pg_backend_pid()"))


def statements(trace, label):
    return [sql for owner, sql, _ in trace.rows if owner == label]


def assert_before_write(sql):
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in sql)
    assert not any("FOR SHARE" in s.upper() or "FOR UPDATE" in s.upper() for s in sql)
    # R1 must wait on the two-int Ref key before the historical one-bigint CP barrier.
    assert not any("pg_advisory_xact_lock(" in s and "CAST(" not in s for s in sql)


async def wait_ref(observer, waiter, owner, company, mode):
    ns, key = locks.advisory_key(locks.RefCompositeKey(company))
    deadline = monotonic() + 10
    while monotonic() < deadline:
        blockers = await observer.scalar(text("SELECT pg_blocking_pids(:p)"), {"p": waiter})
        row = (await observer.execute(text(
            "SELECT mode,granted FROM pg_locks WHERE pid=:p AND locktype='advisory' "
            "AND classid=:n AND objid=:k AND objsubid=2 "
            "AND database=(SELECT oid FROM pg_database WHERE datname=current_database())"),
            {"p": waiter, "n": ns, "k": key & 0xFFFFFFFF})).one_or_none()
        if owner in blockers and row == (mode, False):
            return
        await asyncio.sleep(.01)
    raise AssertionError("Missing actual Ref wait / pg_blocking_pids evidence")


class SyntheticClient:
    def __init__(self, w, *, pause=False, fail=False):
        self.w, self.pause, self.fail = w, pause, fail
        self.organizations_done, self.release = asyncio.Event(), asyncio.Event()
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def describe_entity(self, entity):
        return {}

    async def iter_entity(self, entity, **kwargs):
        w = self.w
        if entity == ENTITY_ORGANIZATIONS:
            for i, ref in enumerate(w.org_refs):
                yield {"Ref_Key": ref, "Description": f"Synthetic org fresh {i}", "ИНН": ""}
            # The second actual ORM SELECT has already autoflushed org 0.
            self.organizations_done.set()
            if self.pause:
                await asyncio.wait_for(self.release.wait(), 15)
            if self.fail:
                raise RuntimeError("Synthetic source failure")
        elif entity == ENTITY_COUNTERPARTIES:
            yield {"Ref_Key": w.cp_ref, "Description": "Synthetic CP fresh", "ИНН": "", "КПП": ""}
        elif entity == ENTITY_CONTRACTS:
            yield {"Ref_Key": w.contract_ref, "Description": "Synthetic contract fresh",
                   "Номер": "Synthetic contract fresh", "Дата": "2026-01-02",
                   "ВидДоговора": "Прочее", "Owner_Key": w.cp_ref, "Организация_Key": w.org_refs[0]}


def synthetic_client(monkeypatch, client):
    async def open_client(self, connection):
        assert connection.id == client.w.connection
        return client
    monkeypatch.setattr(OneCSyncService, "_open_client", open_client)


@asynccontextmanager
async def contender(w, trace, call):
    ready, result = asyncio.Event(), {}
    async def run():
        async with w.factory() as db:
            result["db"] = db
            result["pid"] = await identify(db, trace, "waiter")
            result["connection"] = await db.get(OneCConnection, w.connection)
            result["cp"] = await db.get(Counterparty, w.cp)
            result["org"] = await db.get(Organization, w.orgs[0])
            result["contract"] = await db.get(Contract, w.contract)
            result["actor"] = await db.get(User, w.uid)
            result["root"] = db.sync_session.get_transaction()
            ready.set()
            return await call(db, result)
    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(ready.wait(), 10)
        yield result, task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("native_root", ["create", "update"])
@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_real_onec_autoflush_blocks_real_r1_before_cp(native_root, completion, world, trace, monkeypatch):
    w = world
    client = SyntheticClient(w, pause=True)
    synthetic_client(monkeypatch, client)
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await identify(owner, trace, "onec")
        conn = await owner.get(OneCConnection, w.connection)
        root = owner.sync_session.get_transaction()
        sync = asyncio.create_task(OneCSyncService(owner).sync_catalogs(conn))
        try:
            await asyncio.wait_for(client.organizations_done.wait(), 10)
            sql = statements(trace, "onec")
            b = [i for i, s in enumerate(sql) if "pg_advisory_xact_lock" in s and "CAST(" in s]
            log_write = next(i for i, s in enumerate(sql)
                             if s.lstrip().upper().startswith("INSERT INTO ONEC_SYNC_LOGS"))
            assert len(b) == 2 and max(b) < log_write
            assert any(s.lstrip().upper().startswith("UPDATE ORGANIZATIONS") for s in sql)
            assert not any("pg_advisory_xact_lock(" in s and "CAST(" not in s for s in sql)
            async def native(db, retained):
                if native_root == "create":
                    value = await create_native_contract(db, ContractCreate(
                        company_id=str(w.cid), creationKey=str(uuid4()), number=f"Synthetic new {uuid4()}",
                        date="2026-02-01", type="Прочее", counterpartyId=str(w.cp),
                        organizationId=str(w.orgs[0])), retained["actor"])
                    assert value.organization_id == w.orgs[0]
                else:
                    value = await references_router.update_contract(str(w.contract),
                        ContractUpdate(comment="Synthetic native edit"), db, retained["actor"])
                assert db.sync_session.get_transaction() is retained["root"]
                # Create has no target contract; explicitly read the retained
                # reference through ORM rather than synchronously loading it.
                current = await db.get(Contract, w.contract)
                assert current is retained["contract"]
                expected = "fresh" if completion == "commit" else "old"
                assert retained["cp"].name == f"Synthetic CP {expected}"
                assert retained["org"].name == f"Synthetic org {expected} 0"
                assert retained["contract"].number == f"Synthetic contract {expected}"
                await db.rollback()
                return value
            async with contender(w, trace, native) as (details, task):
                await wait_ref(observer, details["pid"], owner_pid, w.cid, "ShareLock")
                assert_before_write(statements(trace, "waiter"))
                assert not task.done()
                client.release.set()
                log = await asyncio.wait_for(sync, 10)
                assert log.status == "completed" and log.items_errors == 0 and client.closed
                assert owner.sync_session.get_transaction() is root
                # Service has neither committed its log nor completed the root.
                assert await observer.scalar(select(func.count()).select_from(OneCSyncLog)
                                             .where(OneCSyncLog.id == log.id)) == 0
                await getattr(owner, completion)()
                await asyncio.wait_for(task, 10)
                assert await observer.scalar(select(func.count()).select_from(OneCSyncLog)
                    .where(OneCSyncLog.id == log.id)) == (1 if completion == "commit" else 0)
        finally:
            client.release.set()
            if not sync.done():
                sync.cancel()
            await asyncio.gather(sync, return_exceptions=True)
            await owner.rollback()


@pytest.mark.parametrize("pending", ["dirty", "new", "deleted"])
async def test_dirty_root_refusal_keeps_pending_state_and_emits_no_sql(pending, world, trace):
    async with world.factory() as db:
        await identify(db, trace, "dirty")
        conn = await db.get(OneCConnection, world.connection)
        cp = await db.get(Counterparty, world.cp)
        if pending == "dirty":
            cp.name = "Synthetic pending edit"
        elif pending == "new":
            db.add(Counterparty(id=uuid4(), company_id=world.cid, name="Synthetic pending new"))
        else:
            await db.delete(cp)
        snapshot = (set(db.new), set(db.dirty), set(db.deleted))
        root, before = db.sync_session.get_transaction(), len(trace.rows)
        with pytest.raises(locks.ScopedLockError, match="clean entry"):
            await OneCSyncService(db).sync_catalogs(conn)
        assert (set(db.new), set(db.dirty), set(db.deleted)) == snapshot
        assert db.sync_session.get_transaction() is root
        assert len(trace.rows) == before


@pytest.mark.parametrize("origin", ["detached", "other_session"])
async def test_detached_persisted_connection_and_retained_references_reload(origin, world, trace):
    w = world
    async with w.factory() as external:
        detached = await external.get(OneCConnection, w.connection)
        if origin == "detached":
            external.expunge(detached)
        async with w.factory() as db, w.factory() as writer:
            old_org = await db.get(Organization, w.orgs[0])
            await writer.execute(update(Organization).where(Organization.id == w.orgs[0])
                                 .values(name="Synthetic externally changed"))
            await writer.execute(update(OneCConnection).where(OneCConnection.id == w.connection)
                                 .values(name="Synthetic fresh connection"))
            await writer.commit()
            # Supplied retained fields are not server authority, and must not
            # be flushed/discarded by a command using another session.
            detached.company_id = w.other
            prepared = await prepare_catalog_root(db, detached)
            assert prepared.company_id == w.cid and prepared.connection is not detached
            assert prepared.connection.name == "Synthetic fresh connection"
            assert detached.company_id == w.other
            refreshed = (await db.execute(select(Organization).where(Organization.id == w.orgs[0]))).scalar_one()
            assert refreshed is old_org and refreshed.name == "Synthetic externally changed"
            require_catalog_root(db, prepared)
            await db.rollback()
            with pytest.raises(locks.ScopedLockError):
                require_catalog_root(db, prepared)


@pytest.mark.parametrize("change", ["company", "delete", "settings"])
async def test_fresh_connection_after_wait_never_admits_unplanned_company(change, world, trace):
    w = world
    plan = locks.LockPlan((locks.LockRequest(locks.CompanyKey(w.cid), S),
                           locks.LockRequest(locks.RefCompositeKey(w.cid), X)))
    async with w.factory() as blocker, w.factory() as observer:
        blocker_pid = await identify(blocker, trace, "blocker")
        cap = await locks.acquire_scoped_locks_async(blocker, plan)
        async def prepare(db, retained):
            prepared = await prepare_catalog_root(db, retained["connection"])
            require_catalog_root(db, prepared)
            return prepared.connection.name
        async with contender(w, trace, prepare) as (details, task):
            await wait_ref(observer, details["pid"], blocker_pid, w.cid, "ExclusiveLock")
            assert_before_write(statements(trace, "waiter"))
            conn = await blocker.get(OneCConnection, w.connection)
            if change == "company":
                conn.company_id = w.other
            elif change == "delete":
                await blocker.delete(conn)
            else:
                conn.name = "Synthetic settings after wait"
            locks.require_scoped_locks(blocker.sync_session, cap, plan.requests)
            await blocker.commit()
            if change in ("company", "delete"):
                with pytest.raises(locks.ScopedLockError, match="company changed"):
                    await asyncio.wait_for(task, 10)
                assert_before_write(statements(trace, "waiter"))
            else:
                result = await asyncio.wait_for(task, 10)
                assert result == "Synthetic settings after wait"


@pytest.mark.parametrize("mutation", ["commit", "rollback", "savepoint", "connection_rollback", "pointer"])
async def test_real_capability_lifetime_and_connection_pointer(mutation, world):
    async with world.factory() as db:
        prepared = await prepare_catalog_root(db, await db.get(OneCConnection, world.connection))
        if mutation == "savepoint":
            await db.begin_nested()
        elif mutation == "connection_rollback":
            await (await db.connection()).rollback()
        elif mutation == "pointer":
            prepared.connection.company_id = world.other
        else:
            await getattr(db, mutation)()
        with pytest.raises(locks.ScopedLockError):
            require_catalog_root(db, prepared)
        if mutation == "pointer":
            assert prepared.connection in db.dirty  # no discarded caller state


async def test_real_capability_cannot_cross_session_or_plan(world):
    async with world.factory() as db, world.factory() as other:
        prepared = await prepare_catalog_root(db, await db.get(OneCConnection, world.connection))
        with pytest.raises(locks.ScopedLockError):
            require_catalog_root(other, prepared)
        # Uses a genuine issued capability; no forged cap or Session.info registry.
        changed = replace(prepared, company_id=world.other)
        with pytest.raises(locks.ScopedLockError, match="not declared"):
            require_catalog_root(db, changed)


async def test_second_attempt_is_refused_until_root_rollback(world):
    async with world.factory() as db:
        conn = await db.get(OneCConnection, world.connection)
        prepared = await prepare_catalog_root(db, conn)
        with pytest.raises(locks.ScopedLockError, match="already attempted"):
            await prepare_catalog_root(db, conn)
        await db.rollback()
        with pytest.raises(locks.ScopedLockError):
            require_catalog_root(db, prepared)
        next_root = await prepare_catalog_root(db, conn)
        require_catalog_root(db, next_root)


async def test_cancelled_partial_plan_requires_rollback_before_reuse(world, trace):
    w = world
    plan = locks.LockPlan((locks.LockRequest(locks.CompanyKey(w.cid), S),
                           locks.LockRequest(locks.RefCompositeKey(w.cid), X)))
    async with w.factory() as owner, w.factory() as waiter, w.factory() as observer:
        owner_pid = await identify(owner, trace, "owner")
        await locks.acquire_scoped_locks_async(owner, plan)
        waiter_pid = await identify(waiter, trace, "waiter")
        conn = await waiter.get(OneCConnection, w.connection)
        task = asyncio.create_task(prepare_catalog_root(waiter, conn))
        try:
            await wait_ref(observer, waiter_pid, owner_pid, w.cid, "ExclusiveLock")
            assert_before_write(statements(trace, "waiter"))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises((locks.ScopedLockError, PendingRollbackError)):
                await prepare_catalog_root(waiter, conn)
            await waiter.rollback()
            await owner.rollback()
            prepared = await prepare_catalog_root(waiter, conn)
            require_catalog_root(waiter, prepared)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_source_error_retains_historical_log_and_caller_rollback(world, trace, monkeypatch):
    client = SyntheticClient(world, fail=True)
    synthetic_client(monkeypatch, client)
    async with world.factory() as db, world.factory() as observer:
        conn = await db.get(OneCConnection, world.connection)
        root = db.sync_session.get_transaction()
        with pytest.raises(RuntimeError, match="Synthetic source failure"):
            await OneCSyncService(db).sync_catalogs(conn)
        assert db.sync_session.get_transaction() is root and client.closed
        log = (await db.execute(select(OneCSyncLog).where(
            OneCSyncLog.connection_id == world.connection))).scalar_one()
        assert log.status == "error" and "Synthetic source failure" in log.details["error"]
        assert await observer.scalar(select(func.count()).select_from(OneCSyncLog).where(
            OneCSyncLog.connection_id == world.connection)) == 0
        await db.rollback()
        assert await observer.scalar(select(func.count()).select_from(OneCSyncLog).where(
            OneCSyncLog.connection_id == world.connection)) == 0
