"""Real AsyncSession/PG definitions, AUTHORED/NOTRUN.

Root owner must arrange pre-import conftest isolation, native schema bootstrap,
synthetic data and database teardown. No DDL, migrations or schema weakening here.
The module guard alone cannot protect against an earlier conftest import.
"""
import os

import pytest

if os.environ.get("AUDIT_ROOT_COMMIT_ISOLATED") != "1":
    pytest.skip("requires owner-provided pre-import isolation", allow_module_level=True)

import asyncio
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.audit import log_audit
from app.models import AuditEvent, Company, User
from app.services import after_root_commit as deferred, notify

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def audit_pg_factory():
    # This is an additional guard, not a replacement for ROOT's earlier isolation.
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("owner must explicitly provide isolated TEST_DATABASE_URL")
    engine = create_async_engine(url, pool_size=5, max_overflow=2)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def audit_pg_company(audit_pg_factory):
    cid = uuid4()
    async with audit_pg_factory() as db:
        db.add(Company(id=cid, slug=f"audit-{cid.hex}", name="Синтетическая компания",
                       profile_id="energy"))
        await db.commit()
    # ROOT owns teardown of the disposable native database, including these rows.
    return cid


@pytest.fixture
def audit_dispatch_spy(monkeypatch, audit_pg_factory):
    calls, attempts, failures = [], [], []
    engine = audit_pg_factory.kw["bind"].sync_engine

    def verify_and_record(cid, action, who=None, details=None):
        # Runs in SQLAlchemy's real commit greenlet: a separate connection sees
        # committed native data BEFORE this callback records a notification.
        with Session(engine) as independent:
            rows = independent.scalars(select(AuditEvent).where(
                AuditEvent.company_id == cid, AuditEvent.action == action)).all()
            assert any(row.details == details for row in rows)
        calls.append((cid, action, who, details))

    def record(cid, action, who=None, details=None):
        attempts.append((cid, action, who, details))
        try:
            verify_and_record(cid, action, who, details)
        except BaseException as error:
            # Production deliberately catches scheduler Exception. Preserve
            # oracle failures outside that catch, including negative paths.
            failures.append(error)
            raise

    monkeypatch.setattr(notify, "dispatch_async", record)
    yield calls
    assert failures == [], f"callback oracle failures: {failures!r}; attempts={attempts!r}"
    assert attempts == calls, "every callback attempt must pass independent visibility"


async def _enqueue(db, cid, label):
    await log_audit(db, actor=None, company_id=cid, action=f"sample.{label}",
                    target=label, notification_timing="after_root_commit")


def _empty(db):
    assert deferred._STATE not in db.sync_session.info


async def test_physical_root_visibility_flush_and_dependency_second_commit(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy):
    async with audit_pg_factory() as db:
        await _enqueue(db, audit_pg_company, "A")
        root = db.sync_session.get_transaction()
        await db.flush()  # Real flush subtransaction end must not release anything.
        assert not audit_dispatch_spy and db.sync_session.get_transaction() is root
        async with audit_pg_factory() as independent:
            assert not list(await independent.scalars(select(AuditEvent).where(
                AuditEvent.company_id == audit_pg_company)))
        await db.commit()
        assert [c[1] for c in audit_dispatch_spy] == ["sample.A"]
        _empty(db)
        await db.commit()  # get_db's later empty logical commit cannot redeliver.
        assert len(audit_dispatch_spy) == 1
        _empty(db)


@pytest.mark.parametrize("end", ["rollback", "close", "invalidate", "exception"])
async def test_abandoned_root_and_same_session_reuse(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy, end):
    db = audit_pg_factory()
    try:
        await _enqueue(db, audit_pg_company, "lost")
        await db.flush()
        if end == "exception":
            try:
                raise RuntimeError("synthetic owner failure")
            finally:
                await db.rollback()
        else:
            await getattr(db, end)()
    except RuntimeError:
        assert end == "exception"
    _empty(db)
    assert not audit_dispatch_spy
    await db.execute(text("SELECT 1"))
    await db.commit()
    assert not audit_dispatch_spy
    async with audit_pg_factory() as independent:
        assert not list(await independent.scalars(select(AuditEvent).where(
            AuditEvent.company_id == audit_pg_company)))
    await db.close()


async def test_actual_constraint_flush_failure_clears_root(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy):
    async with audit_pg_factory() as db:
        await _enqueue(db, audit_pg_company, "bad")
        row, = db.new
        row.action = None  # Native NOT NULL; no fake commit or event manager.
        with pytest.raises(IntegrityError):
            await db.commit()
        assert not audit_dispatch_spy
        await db.rollback()
        _empty(db)
        await db.execute(text("SELECT 1"))
        await db.commit()
        assert not audit_dispatch_spy


@pytest.mark.parametrize("child_commit", [True, False])
async def test_savepoint_success_merges_and_rollback_discards_only_child(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy, child_commit):
    async with audit_pg_factory() as db:
        await _enqueue(db, audit_pg_company, "A")
        child = await db.begin_nested()
        await _enqueue(db, audit_pg_company, "B")
        await db.flush()
        await (child.commit() if child_commit else child.rollback())
        assert not audit_dispatch_spy
        await _enqueue(db, audit_pg_company, "D")
        await db.commit()
        expected = ["sample.A", "sample.B", "sample.D"] if child_commit else ["sample.A", "sample.D"]
        assert [c[1] for c in audit_dispatch_spy] == expected
        _empty(db)


async def test_deep_subtree_rollback_and_committed_sibling_order(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy):
    async with audit_pg_factory() as db:
        await _enqueue(db, audit_pg_company, "A")
        outer = await db.begin_nested()
        await _enqueue(db, audit_pg_company, "B")
        inner = await db.begin_nested()
        await _enqueue(db, audit_pg_company, "C")
        await inner.commit()
        await outer.rollback()  # C already merged into B must also be removed.
        async with db.begin_nested():
            await _enqueue(db, audit_pg_company, "D")
        rolled = await db.begin_nested()
        await _enqueue(db, audit_pg_company, "E")
        await rolled.rollback()
        assert not audit_dispatch_spy
        await db.commit()
        assert [c[1] for c in audit_dispatch_spy] == ["sample.A", "sample.D"]
        _empty(db)


async def test_root_rollback_clears_already_merged_child(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy):
    async with audit_pg_factory() as db:
        await _enqueue(db, audit_pg_company, "A")
        async with db.begin_nested():
            await _enqueue(db, audit_pg_company, "B")
        await db.rollback()
        _empty(db)
        await db.execute(text("SELECT 1"))
        await db.commit()
        assert not audit_dispatch_spy


async def test_cancelled_owner_rolls_back_before_session_reuse(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy):
    db = audit_pg_factory()
    ready = asyncio.Event()
    wait = asyncio.Event()

    async def owner():
        try:
            await _enqueue(db, audit_pg_company, "cancelled")
            await db.flush()
            ready.set()
            await wait.wait()  # Bounded cancellation BEFORE committing.
            await db.commit()
        finally:
            await db.rollback()

    task = asyncio.create_task(owner())
    await asyncio.wait_for(ready.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    assert not audit_dispatch_spy
    _empty(db)
    await _enqueue(db, audit_pg_company, "next")
    await db.commit()
    assert [c[1] for c in audit_dispatch_spy] == ["sample.next"]
    await db.close()


async def test_reentrant_new_root_has_no_old_payload(monkeypatch, audit_pg_factory, audit_pg_company):
    calls = []
    async with audit_pg_factory() as db:
        def reenter(cid, action, who=None, details=None):
            calls.append(action)
            assert deferred._STATE not in db.sync_session.info
            if action == "sample.A":
                # The old root is closed: a real add establishes a new root.
                db.add(AuditEvent(company_id=cid, action="sample.B", user_id="system",
                                  user_name="Платформа", details="B"))
                deferred.enqueue_audit_notification(db, company_id=cid, action="sample.B",
                                                    who=None, details="B")
        monkeypatch.setattr(notify, "dispatch_async", reenter)
        await _enqueue(db, audit_pg_company, "A")
        await db.commit()
        assert calls == ["sample.A"]
        await db.commit()
        assert calls == ["sample.A", "sample.B"]
        _empty(db)


async def test_scheduler_failure_is_log_only_after_commit(
        monkeypatch, caplog, audit_pg_factory, audit_pg_company):
    calls = []
    def broken(*args, **kwargs):
        calls.append(args[1])
        raise RuntimeError("synthetic scheduler failure")
    monkeypatch.setattr(notify, "dispatch_async", broken)
    async with audit_pg_factory() as db:
        await _enqueue(db, audit_pg_company, "A")
        await _enqueue(db, audit_pg_company, "B")
        await db.commit()  # Must return successfully; neither retry nor rollback.
        assert calls == ["sample.A", "sample.B"]
        assert "scheduling failed" in caplog.text
        _empty(db)
    async with audit_pg_factory() as independent:
        assert len(list(await independent.scalars(select(AuditEvent).where(
            AuditEvent.company_id == audit_pg_company)))) == 2


async def test_expiry_and_close_leave_primitive_actor_payload(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy):
    actor_id = uuid4()
    async with audit_pg_factory(expire_on_commit=True) as db:
        actor = User(id=actor_id, company_id=audit_pg_company,
                     email=f"{actor_id.hex}@example.invalid", password_hash="synthetic",
                     name="Исходное имя")
        db.add(actor)
        await db.flush()
        await log_audit(db, actor=actor, company_id=audit_pg_company,
                        action="sample.expiry", target="snapshot",
                        notification_timing="after_root_commit")
        actor.name = "Новое имя"
        await db.flush()
        db.expire(actor)
        await db.commit()
        assert audit_dispatch_spy == [(audit_pg_company, "sample.expiry", "Исходное имя", "snapshot")]
    assert len(audit_dispatch_spy) == 1


@pytest.mark.parametrize("join_mode", ["conditional_savepoint", "create_savepoint", "rollback_only", "control_fully"])
async def test_external_connection_rejected_before_add(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy, join_mode):
    engine = audit_pg_factory.kw["bind"]
    async with engine.connect() as connection:
        outer = await connection.begin()
        async with AsyncSession(connection, join_transaction_mode=join_mode) as db:
            with pytest.raises(ValueError):
                await _enqueue(db, audit_pg_company, "external")
            assert not db.new
            _empty(db)
        assert outer.is_active and not audit_dispatch_spy
        await outer.rollback()


async def test_scoped_lock_transaction_end_listener_coexists(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy):
    from app.services.contract_write_locks import (
        CompanyKey, LockMode, LockPlan, LockRequest, ScopedLockError,
        acquire_scoped_locks_async, require_scoped_locks,
    )
    async with audit_pg_factory() as db:
        plan = LockPlan((LockRequest(CompanyKey(audit_pg_company), LockMode.SHARED),))
        capability = await acquire_scoped_locks_async(db, plan)
        await _enqueue(db, audit_pg_company, "coexist")
        await db.flush()
        assert not audit_dispatch_spy
        require_scoped_locks(db.sync_session, capability, plan.requests)
        await db.commit()
        assert [c[1] for c in audit_dispatch_spy] == ["sample.coexist"]
        _empty(db)
        with pytest.raises(ScopedLockError):
            require_scoped_locks(db.sync_session, capability, plan.requests)


async def test_existing_per_statement_alternate_bind_rejected_before_add(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy):
    engine = audit_pg_factory.kw["bind"]
    alternate = create_async_engine(engine.url)
    try:
        async with audit_pg_factory() as db:
            await db.execute(text("SELECT 1"), bind_arguments={"bind": alternate.sync_engine})
            with pytest.raises(ValueError):
                await _enqueue(db, audit_pg_company, "alternate")
            assert not db.new and not audit_dispatch_spy
            _empty(db)
            await db.rollback()
    finally:
        await alternate.dispose()


async def test_core_savepoint_before_optin_rejects_before_add(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy):
    async with audit_pg_factory() as db:
        connection = await db.connection()
        core_savepoint = await connection.begin_nested()
        with pytest.raises(ValueError, match="Core SAVEPOINT"):
            await _enqueue(db, audit_pg_company, "core_before")
        assert not db.new and not audit_dispatch_spy
        _empty(db)
        await core_savepoint.rollback()
        await db.commit()
        _empty(db)
    async with audit_pg_factory() as independent:
        assert not list(await independent.scalars(select(AuditEvent).where(
            AuditEvent.company_id == audit_pg_company)))


async def test_late_core_savepoint_blocks_flush_and_poisons_root_until_rollback(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy):
    async with audit_pg_factory() as db:
        await _enqueue(db, audit_pg_company, "core_after")
        connection = await db.connection()
        core_savepoint = await connection.begin_nested()
        with pytest.raises(ValueError, match="Core SAVEPOINT"):
            await db.flush()  # Reject BEFORE AuditEvent SQL inside Core scope.
        await core_savepoint.rollback()
        with pytest.raises(ValueError, match="roll back the entire root"):
            await db.commit()  # Catching the first guard cannot revive this root.
        assert not audit_dispatch_spy
        await db.rollback()
        _empty(db)
        await db.execute(text("SELECT 1"))
        await db.commit()
        assert not audit_dispatch_spy
    async with audit_pg_factory() as independent:
        assert not list(await independent.scalars(select(AuditEvent).where(
            AuditEvent.company_id == audit_pg_company)))


@pytest.mark.parametrize("configuration", ["engine", "connection", "late_connection"])
async def test_autocommit_configuration_has_no_audit_or_notification_effect(
        audit_pg_factory, audit_pg_company, audit_dispatch_spy, configuration):
    engine = audit_pg_factory.kw["bind"]
    selected = create_async_engine(engine.url, isolation_level="AUTOCOMMIT") if configuration == "engine" else engine
    try:
        async with AsyncSession(selected) as db:
            if configuration == "connection":
                # Same Engine, but actual enlisted Connection has unsafe mode.
                await db.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
            if configuration == "late_connection":
                await _enqueue(db, audit_pg_company, "autocommit_late")
                with pytest.raises(ValueError, match="AUTOCOMMIT"):
                    await db.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
                with pytest.raises(ValueError, match="roll back the entire root"):
                    await db.commit()
                await db.rollback()
            else:
                with pytest.raises(ValueError, match="AUTOCOMMIT"):
                    await _enqueue(db, audit_pg_company, "autocommit")
                assert not db.new
                _empty(db)
                await db.rollback()
            _empty(db)
            assert not audit_dispatch_spy
    finally:
        if selected is not engine:
            await selected.dispose()
    async with audit_pg_factory() as independent:
        assert not list(await independent.scalars(select(AuditEvent).where(
            AuditEvent.company_id == audit_pg_company)))
