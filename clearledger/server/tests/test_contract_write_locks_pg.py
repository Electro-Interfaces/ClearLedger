"""Authored real-PG specifications; all NOTRUN, including import/collection.

ROOT must freeze a separate synthetic target and execution isolation first.
This module's guard runs before SQLAlchemy/app/driver imports, but cannot guard
the repository conftest that pytest may load earlier. No ordinary pytest safety
claim, no app schema, no credential discovery, no TEST_DATABASE_URL fallback.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from dataclasses import replace
import asyncio
import os
from threading import Event
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

import pytest


_URL = os.environ.get("CONTRACT_SCOPED_LOCKS_PG_URL", "")
_APPROVED_URL = os.environ.get("CONTRACT_SCOPED_LOCKS_PG_ROOT_APPROVED_URL", "")
_APPROVAL = os.environ.get("CONTRACT_SCOPED_LOCKS_PG_APPROVAL", "")
_TARGET = urlsplit(_URL)
if not (
    _URL and _URL == _APPROVED_URL
    and _APPROVAL == "ROOT-approved-synthetic-contract-scoped-locks-v1"
    and _TARGET.scheme == "postgresql+psycopg"
    and _TARGET.hostname
    and _TARGET.path.startswith("/contract_scoped_locks_synthetic_")
    and len(_TARGET.path) > len("/contract_scoped_locks_synthetic_")
    and not _TARGET.query and not _TARGET.fragment
):
    pytest.skip("Separate synthetic ROOT-approved scoped-lock target required", allow_module_level=True)

# Intentionally below the explicit target guard.
from sqlalchemy import Integer, String, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from app.services import contract_write_locks as locks


S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE
C1 = UUID("00000000-0000-0000-0000-000000000001")
C2 = UUID("00000000-0000-0000-0000-000000000002")


def plan(key, mode=S):
    return locks.LockPlan((locks.LockRequest(key, mode),))


@pytest.fixture
def engine():
    # Actual concurrent leases in an ordinary QueuePool. No NullPool proof.
    database = create_engine(_URL, pool_size=5, max_overflow=0, isolation_level="READ COMMITTED")
    try:
        yield database
    finally:
        database.dispose()


def pid(session):
    return session.scalar(text("SELECT pg_backend_pid()"))


def lock_rows(observer, lock):
    return observer.execute(text("""
        SELECT pid, mode, granted FROM pg_locks
        WHERE locktype = 'advisory' AND classid = :namespace
          AND objid = :key AND objsubid = 2
          AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
    """), {"namespace": lock.namespace, "key": lock.key & 0xFFFFFFFF}).all()


@contextmanager
def contender(engine, owner, requested):
    """Publish backend PID before acquisition; retain acquired locks for inspection."""
    ready, acquired, release = Event(), Event(), Event()
    details = {}

    def worker():
        with Session(engine) as other:
            details["pid"] = pid(other)
            ready.set()
            capability = locks.acquire_scoped_locks(other, requested)
            locks.require_scoped_locks(other, capability, requested.requests)
            acquired.set()
            if not release.wait(15):
                raise AssertionError("Observer failed to release contender")
            other.rollback()

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(worker)
    try:
        assert ready.wait(10), "Contender did not establish a real backend"
        yield details["pid"], acquired, future
    finally:
        # Always release the blocking root before joining, including assertion failures.
        owner.rollback()
        release.set()
        try:
            future.result(timeout=15)
        finally:
            executor.shutdown(wait=True)


def observe_blocking(observer, waiter_pid, owner_pid, actual_lock):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        blockers = observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid})
        rows = lock_rows(observer, actual_lock)
        if owner_pid in blockers and (waiter_pid, "ExclusiveLock", False) in rows:
            assert any(row.pid == owner_pid and row.granted for row in rows)
            return
    raise AssertionError("No observed pg_blocking_pids + ungranted pg_locks evidence")


def test_shared_coexists_and_exclusive_waits_on_actual_two_int_lock(engine):
    declaration = plan(locks.CompanyKey(C1))
    with Session(engine) as owner, engine.connect() as observer:
        cap = locks.acquire_scoped_locks(owner, declaration)
        owner_pid = pid(owner)
        with contender(engine, owner, declaration) as (other_pid, acquired, future):
            assert acquired.wait(10), "SHARED acquisition did not coexist"
            rows = lock_rows(observer, declaration.locks[0])
            assert (owner_pid, "ShareLock", True) in rows
            assert (other_pid, "ShareLock", True) in rows
            assert not future.done()
            locks.require_scoped_locks(owner, cap, declaration.requests)
        cap = locks.acquire_scoped_locks(owner, declaration)
        owner_pid = pid(owner)
        with contender(engine, owner, plan(locks.CompanyKey(C1), X)) as (other_pid, acquired, _):
            observe_blocking(observer, other_pid, owner_pid, declaration.locks[0])
            assert not acquired.is_set()
            owner.rollback()
            assert acquired.wait(10)


def test_disjoint_company_exclusive_keys_do_not_block(engine):
    first, second = plan(locks.CompanyKey(C1), X), plan(locks.CompanyKey(C2), X)
    assert first.locks[0].key != second.locks[0].key
    with Session(engine) as owner, engine.connect() as observer:
        locks.acquire_scoped_locks(owner, first)
        owner_pid = pid(owner)
        with contender(engine, owner, second) as (other_pid, acquired, _):
            assert acquired.wait(10)
            assert (owner_pid, "ExclusiveLock", True) in lock_rows(observer, first.locks[0])
            assert (other_pid, "ExclusiveLock", True) in lock_rows(observer, second.locks[0])
            assert observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": other_pid}) == []


def test_real_collision_waits_but_does_not_grant_another_logical_identity(engine):
    a, b = locks.ClientKey("collision-12634"), locks.ClientKey("collision-44041")
    declaration = plan(a)
    assert declaration.locks[0].key == -1045510226 == plan(b).locks[0].key
    with Session(engine) as owner, engine.connect() as observer:
        capability = locks.acquire_scoped_locks(owner, declaration)
        with pytest.raises(locks.ScopedLockError, match="not declared"):
            locks.require_scoped_locks(owner, capability, plan(b).requests)
        with pytest.raises(locks.ScopedLockError, match="not declared"):
            locks.require_scoped_locks(owner, capability, plan(a, X).requests)
        with pytest.raises(locks.ScopedLockError, match="already attempted"):
            locks.acquire_scoped_locks(owner, plan(b, X))
        owner_pid = pid(owner)
        with contender(engine, owner, plan(b, X)) as (other_pid, acquired, _):
            observe_blocking(observer, other_pid, owner_pid, declaration.locks[0])
            assert not acquired.is_set()
            owner.rollback()
            assert acquired.wait(10)


def test_colliding_plan_executes_once_with_strongest_mode_and_original_coverage(engine):
    a, b = locks.ClientKey("collision-12634"), locks.ClientKey("collision-44041")
    declaration = locks.LockPlan((locks.LockRequest(a, S), locks.LockRequest(b, X)))
    statements = []
    with Session(engine) as session:
        connection = session.connection()

        def capture(conn, cursor, statement, parameters, context, executemany):
            if "pg_advisory_xact_lock" in statement:
                statements.append(statement)

        event.listen(connection, "before_cursor_execute", capture)
        cap = locks.acquire_scoped_locks(session, declaration)
        assert len(statements) == 1
        assert "pg_advisory_xact_lock_shared" not in statements[0]
        locks.require_scoped_locks(session, cap, declaration.requests)
        with pytest.raises(locks.ScopedLockError, match="not declared"):
            locks.require_scoped_locks(session, cap, plan(a, X).requests)


@pytest.mark.parametrize("ending", ["commit", "rollback", "close"])
def test_session_end_invalidates_and_new_root_can_acquire(engine, ending):
    declaration = plan(locks.UserKey(C1))
    with Session(engine) as session:
        capability = locks.acquire_scoped_locks(session, declaration)
        getattr(session, ending)()
        with pytest.raises(locks.ScopedLockError):
            locks.require_scoped_locks(session, capability, declaration.requests)
        replacement = locks.acquire_scoped_locks(session, declaration)
        assert replacement is not capability
        locks.require_scoped_locks(session, replacement, declaration.requests)


@pytest.mark.parametrize("ending", ["commit", "rollback"])
def test_direct_connection_end_invalidates_even_with_live_session_root(engine, ending):
    declaration = plan(locks.UserKey(C1))
    with Session(engine) as session:
        capability = locks.acquire_scoped_locks(session, declaration)
        root = session.get_transaction()
        getattr(session.connection(), ending)()
        assert session.get_transaction() is root and root.is_active
        with pytest.raises(locks.ScopedLockError):
            locks.require_scoped_locks(session, capability, declaration.requests)
        with pytest.raises(locks.ScopedLockError):
            locks.acquire_scoped_locks(session, declaration)


@pytest.mark.parametrize("api", ["session", "connection"])
@pytest.mark.parametrize("ending", ["commit", "rollback"])
def test_savepoint_history_invalidates_after_nested_object_disappears(engine, api, ending):
    declaration = plan(locks.MemberKey(C1, C2))
    with Session(engine) as session:
        capability = locks.acquire_scoped_locks(session, declaration)
        root = session.get_transaction()
        source = session if api == "session" else session.connection()
        nested = source.begin_nested()
        getattr(nested, ending)()
        assert session.get_transaction() is root and root.is_active
        assert session.get_nested_transaction() is None
        assert session.connection().get_nested_transaction() is None
        with pytest.raises(locks.ScopedLockError):
            locks.require_scoped_locks(session, capability, declaration.requests)
        with pytest.raises(locks.ScopedLockError):
            locks.acquire_scoped_locks(session, declaration)


@pytest.mark.parametrize("api", ["session", "connection"])
def test_nested_entry_is_rejected_before_lock_sql(engine, api):
    with Session(engine) as session:
        source = session if api == "session" else session.connection()
        with source.begin_nested():
            with pytest.raises(locks.ScopedLockError):
                locks.acquire_scoped_locks(session, plan(locks.CompanyKey(C1)))


def test_foreign_copied_and_forged_capability_rejected_on_real_sessions(engine):
    declaration = plan(locks.RoleKey(C1, C2))
    with Session(engine) as issuer, Session(engine) as foreign:
        capability = locks.acquire_scoped_locks(issuer, declaration)
        for invalid in (copy(capability), deepcopy(capability), replace(capability),
                        locks.ScopedLockCapability(declaration)):
            with pytest.raises(locks.ScopedLockError, match="not issued"):
                locks.require_scoped_locks(issuer, invalid, declaration.requests)
        # Even the same physical Connection + DB transaction is not the issuer.
        with Session(issuer.connection(), join_transaction_mode="rollback_only") as borrowed:
            with pytest.raises(locks.ScopedLockError, match="not issued"):
                locks.require_scoped_locks(borrowed, capability, declaration.requests)
        with pytest.raises(locks.ScopedLockError, match="not issued"):
            locks.require_scoped_locks(foreign, capability, declaration.requests)


class ProbeBase(DeclarativeBase):
    pass


class Probe(ProbeBase):
    __tablename__ = "contract_scoped_lock_probe"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String)


@pytest.fixture
def probe_session(engine):
    # Test-local temporary relation only; helper never issues DDL.
    with engine.connect() as connection:
        connection.execute(text("CREATE TEMP TABLE contract_scoped_lock_probe (id integer PRIMARY KEY, label text)"))
        connection.execute(text("INSERT INTO contract_scoped_lock_probe VALUES (1, 'original')"))
        connection.commit()
        try:
            with Session(connection) as session:
                yield session
        finally:
            connection.rollback()
            connection.execute(text("DROP TABLE contract_scoped_lock_probe"))
            connection.commit()


@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
def test_actual_sqlalchemy_pending_state_sets_reject_entry(probe_session, pending):
    session = probe_session
    if pending == "new":
        session.add(Probe(id=2, label="pending"))
    else:
        row = session.get(Probe, 1)
        if pending == "dirty":
            row.label = "pending"
        else:
            session.delete(row)
    assert getattr(session, pending)
    with pytest.raises(locks.ScopedLockError, match="clean entry"):
        locks.acquire_scoped_locks(session, plan(locks.CompanyKey(C1)))


def test_authorized_dirty_validation_and_normal_flush_child_remain_valid(probe_session):
    session = probe_session
    declaration = plan(locks.CompanyKey(C1))
    capability = locks.acquire_scoped_locks(session, declaration)
    row = session.get(Probe, 1)
    row.label = "authorized"
    assert session.dirty
    locks.require_scoped_locks(session, capability, declaration.requests)
    session.flush()
    locks.require_scoped_locks(session, capability, declaration.requests)


def test_baseexception_after_partial_acquisition_poisons_until_outer_rollback(engine):
    class Interrupted(BaseException):
        pass

    declaration = locks.LockPlan((locks.LockRequest(locks.AppKey(C1), S),
                                  locks.LockRequest(locks.CompanyKey(C1), S)))
    with Session(engine) as session:
        connection = session.connection()
        count = 0

        def interrupt(conn, cursor, statement, parameters, context, executemany):
            nonlocal count
            if "pg_advisory_xact_lock" in statement:
                count += 1
                if count == 2:
                    raise Interrupted()

        event.listen(connection, "before_cursor_execute", interrupt)
        with pytest.raises(Interrupted):
            locks.acquire_scoped_locks(session, declaration)
        assert count == 2
        with pytest.raises(locks.ScopedLockError, match="already attempted"):
            locks.acquire_scoped_locks(session, declaration)
        session.rollback()
        event.remove(connection, "before_cursor_execute", interrupt)
        capability = locks.acquire_scoped_locks(session, declaration)
        locks.require_scoped_locks(session, capability, declaration.requests)


def test_inactive_session_entry_rejected(probe_session):
    from sqlalchemy.exc import IntegrityError

    probe_session.add(Probe(id=1, label="duplicate"))
    with pytest.raises(IntegrityError):
        probe_session.flush()
    assert not probe_session.is_active
    with pytest.raises(locks.ScopedLockError):
        locks.acquire_scoped_locks(probe_session, plan(locks.CompanyKey(C1)))


def test_connection_invalidation_rejects_live_root_capability(engine):
    declaration = plan(locks.CompanyKey(C1))
    with Session(engine) as session:
        capability = locks.acquire_scoped_locks(session, declaration)
        session.connection().invalidate()
        with pytest.raises(locks.ScopedLockError):
            locks.require_scoped_locks(session, capability, declaration.requests)


def test_multiple_enlisted_connections_rejected(engine):
    with Session(engine) as session:
        session.connection()
        session.connection(bind_arguments={"bind": engine.execution_options()})
        with pytest.raises(locks.ScopedLockError):
            locks.acquire_scoped_locks(session, plan(locks.CompanyKey(C1)))


def test_async_uses_actual_sync_session_and_same_capability_protocol():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    async def exercise():
        database = create_async_engine(_URL, pool_size=2, max_overflow=0)
        declaration = plan(locks.CompanyKey(C1))
        try:
            async with AsyncSession(database) as session, AsyncSession(database) as foreign:
                capability = await locks.acquire_scoped_locks_async(session, declaration)
                locks.require_scoped_locks(session.sync_session, capability, declaration.requests)
                with pytest.raises(locks.ScopedLockError):
                    locks.require_scoped_locks(foreign.sync_session, capability, declaration.requests)
                await session.rollback()
                with pytest.raises(locks.ScopedLockError):
                    locks.require_scoped_locks(session.sync_session, capability, declaration.requests)
        finally:
            await database.dispose()

    asyncio.run(exercise())


@contextmanager
def record_connection_sql(connection):
    """Observe real cursor dispatch, including any unexpected non-lock SQL."""
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", record)


@pytest.mark.parametrize("second_kind", ["upgrade", "numeric_reverse"])
def test_two_sessions_share_one_db_root_and_cannot_acquire_second_plan(engine, second_kind):
    first = plan(locks.CompanyKey(C1))
    second = (plan(locks.CompanyKey(C1), X) if second_kind == "upgrade"
              else plan(locks.AppKey(C1), X))
    with engine.connect() as connection, engine.connect() as observer:
        outer = connection.begin()
        try:
            with Session(connection, join_transaction_mode="rollback_only") as issuer, \
                    Session(connection, join_transaction_mode="rollback_only") as other:
                with record_connection_sql(connection) as statements:
                    cap = locks.acquire_scoped_locks(issuer, first)
                    owner_pid = pid(issuer)
                    assert pid(other) == owner_pid
                    assert issuer.get_transaction() is not other.get_transaction()
                    assert issuer.connection() is other.connection() is connection
                    assert connection.get_transaction() is outer and outer.is_active
                    before = tuple(statements)
                    with pytest.raises(locks.ScopedLockError, match="not issued"):
                        locks.require_scoped_locks(other, cap, first.requests)
                    with pytest.raises(locks.ScopedLockError, match="already attempted"):
                        locks.acquire_scoped_locks(other, second)
                    assert tuple(statements) == before
                    # Rejecting another Session's entrance does not revoke the issuer.
                    locks.require_scoped_locks(issuer, cap, first.requests)
                    assert connection.get_transaction() is outer and outer.is_active
                    assert (owner_pid, "ShareLock", True) in lock_rows(observer, first.locks[0])
                    assert not any(row.pid == owner_pid and row.mode == "ExclusiveLock"
                                   for row in lock_rows(observer, second.locks[0]))
        finally:
            outer.rollback()


@pytest.mark.parametrize("reuse_session", [True, False])
def test_rollback_only_commit_keeps_attempt_across_orm_roots(engine, reuse_session):
    declaration = plan(locks.CompanyKey(C1))
    with engine.connect() as connection, engine.connect() as observer:
        outer = connection.begin()
        try:
            with Session(connection, join_transaction_mode="rollback_only") as issuer, \
                    Session(connection, join_transaction_mode="rollback_only") as other:
                with record_connection_sql(connection) as statements:
                    cap = locks.acquire_scoped_locks(issuer, declaration)
                    orm_root, owner_pid = issuer.get_transaction(), pid(issuer)
                    issuer.commit()
                    assert issuer.get_transaction() is None and not orm_root.is_active
                    assert connection.get_transaction() is outer and outer.is_active
                    with pytest.raises(locks.ScopedLockError):
                        locks.require_scoped_locks(issuer, cap, declaration.requests)
                    target = issuer if reuse_session else other
                    before = tuple(statements)
                    with pytest.raises(locks.ScopedLockError, match="already attempted"):
                        locks.acquire_scoped_locks(target, plan(locks.CompanyKey(C1), X))
                    assert tuple(statements) == before
                    assert target.get_transaction() is not orm_root
                    assert target.connection().get_transaction() is outer
                    assert (owner_pid, "ShareLock", True) in lock_rows(observer, declaration.locks[0])
        finally:
            outer.rollback()


@pytest.mark.parametrize("reuse_session", [True, False])
def test_rollback_only_close_keeps_attempt_across_orm_roots(engine, reuse_session):
    declaration = plan(locks.CompanyKey(C1))
    with engine.connect() as connection, engine.connect() as observer:
        outer = connection.begin()
        try:
            with Session(connection, join_transaction_mode="rollback_only") as issuer, \
                    Session(connection, join_transaction_mode="rollback_only") as other:
                with record_connection_sql(connection) as statements:
                    cap = locks.acquire_scoped_locks(issuer, declaration)
                    orm_root, owner_pid = issuer.get_transaction(), pid(issuer)
                    issuer.close()
                    assert issuer.get_transaction() is None and not orm_root.is_active
                    assert connection.get_transaction() is outer and outer.is_active
                    with pytest.raises(locks.ScopedLockError):
                        locks.require_scoped_locks(issuer, cap, declaration.requests)
                    target = issuer if reuse_session else other
                    before = tuple(statements)
                    with pytest.raises(locks.ScopedLockError, match="already attempted"):
                        locks.acquire_scoped_locks(target, plan(locks.AppKey(C1), X))
                    assert tuple(statements) == before
                    assert target.get_transaction() is not orm_root
                    assert target.connection().get_transaction() is outer
                    assert (owner_pid, "ShareLock", True) in lock_rows(observer, declaration.locks[0])
        finally:
            outer.rollback()


@pytest.mark.parametrize("ending", ["commit", "close"])
@pytest.mark.parametrize("reuse_session", [True, False])
def test_partial_attempt_survives_rollback_only_orm_root_replacement(engine, ending, reuse_session):
    class Interrupted(BaseException):
        pass

    declaration = locks.LockPlan((locks.LockRequest(locks.AppKey(C1), S),
                                  locks.LockRequest(locks.CompanyKey(C1), S)))
    with engine.connect() as connection, engine.connect() as observer:
        outer = connection.begin()
        try:
            with Session(connection, join_transaction_mode="rollback_only") as issuer, \
                    Session(connection, join_transaction_mode="rollback_only") as other:
                count = 0

                def interrupt(conn, cursor, statement, parameters, context, executemany):
                    nonlocal count
                    if "pg_advisory_xact_lock" in statement:
                        count += 1
                        if count == 2:
                            raise Interrupted()

                owner_pid = pid(issuer)
                with record_connection_sql(connection) as statements:
                    event.listen(connection, "before_cursor_execute", interrupt)
                    try:
                        with pytest.raises(Interrupted):
                            locks.acquire_scoped_locks(issuer, declaration)
                    finally:
                        event.remove(connection, "before_cursor_execute", interrupt)
                    assert count == 2
                    assert (owner_pid, "ShareLock", True) in lock_rows(observer, declaration.locks[0])
                    assert not any(row.pid == owner_pid
                                   for row in lock_rows(observer, declaration.locks[1]))
                    orm_root = issuer.get_transaction()
                    getattr(issuer, ending)()
                    assert issuer.get_transaction() is None and not orm_root.is_active
                    assert connection.get_transaction() is outer and outer.is_active
                    target = issuer if reuse_session else other
                    before = tuple(statements)
                    with pytest.raises(locks.ScopedLockError, match="already attempted"):
                        locks.acquire_scoped_locks(target, declaration)
                    assert tuple(statements) == before
                    assert target.get_transaction() is not orm_root
                    assert target.connection().get_transaction() is outer
                    assert outer.is_active
        finally:
            outer.rollback()


@pytest.mark.parametrize("partial", [False, True])
def test_actual_outer_rollback_allows_new_db_root_on_same_connection(engine, partial):
    class Interrupted(BaseException):
        pass

    declaration = locks.LockPlan((locks.LockRequest(locks.AppKey(C1), S),
                                  locks.LockRequest(locks.CompanyKey(C1), S)))
    with engine.connect() as connection, engine.connect() as observer:
        outer = connection.begin()
        try:
            with Session(connection, join_transaction_mode="rollback_only") as issuer:
                owner_pid = pid(issuer)
                if partial:
                    count = 0

                    def interrupt(conn, cursor, statement, parameters, context, executemany):
                        nonlocal count
                        if "pg_advisory_xact_lock" in statement:
                            count += 1
                            if count == 2:
                                raise Interrupted()

                    event.listen(connection, "before_cursor_execute", interrupt)
                    try:
                        with pytest.raises(Interrupted):
                            locks.acquire_scoped_locks(issuer, declaration)
                    finally:
                        event.remove(connection, "before_cursor_execute", interrupt)
                    assert count == 2
                else:
                    cap = locks.acquire_scoped_locks(issuer, declaration)
                    locks.require_scoped_locks(issuer, cap, declaration.requests)
                issuer.close()
                assert connection.get_transaction() is outer and outer.is_active
            outer.rollback()
            assert not outer.is_active and connection.get_transaction() is None
            for actual in declaration.locks:
                assert not any(row.pid == owner_pid for row in lock_rows(observer, actual))
            fresh = connection.begin()
            try:
                assert fresh is not outer and fresh.is_active
                with Session(connection, join_transaction_mode="rollback_only") as replacement:
                    with record_connection_sql(connection) as statements:
                        new_cap = locks.acquire_scoped_locks(replacement, declaration)
                        locks.require_scoped_locks(replacement, new_cap, declaration.requests)
                        assert connection.get_transaction() is fresh
                        assert sum("pg_advisory_xact_lock" in sql for sql in statements) == len(declaration.locks)
                        for actual in declaration.locks:
                            assert (owner_pid, "ShareLock", True) in lock_rows(observer, actual)
            finally:
                fresh.rollback()
        finally:
            if outer.is_active:
                outer.rollback()
