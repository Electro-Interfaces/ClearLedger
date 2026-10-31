"""ROOT-only real pooled PostgreSQL lease tests; no SMTP, scheduler or working DB.

Synchronization is via Events, never sleeps. Fault hooks raise errors or pause
cleanup only; lock results, backend PIDs, transactions and audit rows are real.
"""
import os
if os.environ.get('RUN_PULSE_DIGEST_LOCK_OWNER_TESTS') != '1':
    raise RuntimeError('ROOT-approved digest lock gate required')

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app import database
from app.models import AuditEvent, Company, PulseTarget, User, UserCompany
from app.services import pulse_day, pulse_digest
from tests.test_pulse_day_query_owner import tickets_contract

pytestmark = pytest.mark.asyncio(loop_scope='session')
TARGET = 'api_pulse_digest_lock_owner_test_20261031'
CID = uuid.UUID('c9100000-0000-4000-8000-000000000001')
UID = uuid.UUID('c9100000-0000-4000-8000-000000000002')
EMAIL = 'p9-reader@example.test'
LOCKS = text("""select pid from pg_locks where locktype='advisory'
 and database=(select oid from pg_database where datname=current_database())
 and classid=0 and objid=cast(:key as oid) and objsubid=1 and granted order by pid""")


def approved_target(raw):
    u = make_url(raw)
    return (u.drivername == 'postgresql+asyncpg' and u.host == '127.0.0.1'
            and u.port == 33546 and u.database == TARGET and not u.query
            and u.username == 'clearledger' and u.password == 'api_test_only')


async def pids(conn, key=None):
    return list((await conn.execute(LOCKS, {'key': pulse_digest.LOCK_KEY if key is None else key})).scalars())


async def bounded(awaitable):
    return await asyncio.wait_for(awaitable, 8)


@pytest.fixture
async def pooled(setup_database):
    url = os.environ['TEST_DATABASE_URL']
    assert approved_target(url)
    engine = create_async_engine(url, pool_size=2, max_overflow=0, pool_timeout=3,
        connect_args={'timeout': 5, 'command_timeout': 10,
                      'server_settings': {'statement_timeout': '8000', 'lock_timeout': '1500',
                                          'idle_in_transaction_session_timeout': '15000',
                                          'application_name': 'p9-owned-synthetic'}})
    assert isinstance(engine.sync_engine.pool, AsyncAdaptedQueuePool)
    assert engine.pool.size() == 2 and engine.pool._max_overflow == 0
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text('select current_database()')) == TARGET
        yield SimpleNamespace(engine=engine, factory=factory)
    finally:
        assert engine.pool.checkedout() == 0
        async with engine.connect() as conn:
            assert await pids(conn) == []
        await engine.dispose()


@pytest.fixture
async def world(db, pooled, tickets_contract, monkeypatch, pytestconfig):
    db.add(Company(id=CID, name='P9 synthetic', slug='p9-owned-lock', profile_id='energy'))
    await db.flush()
    db.add(User(id=UID, company_id=CID, name='P9 reader', email=EMAIL,
                password_hash='!synthetic', role='user', last_seen_at=datetime.now(timezone.utc)))
    await db.flush()
    db.add(UserCompany(user_id=UID, company_id=CID, role='user', modules=['pulse'], party_type='internal'))
    db.add(PulseTarget(company_id=CID, key='digest_hour', value=datetime.now(pulse_digest.TZ).hour))
    await db.commit()
    monkeypatch.setattr(pulse_digest, 'async_session_factory', pooled.factory)
    native_due = pulse_digest._companies_due
    trace = []; delivered = []
    async def due(session):
        trace.append('due')
        return [(cid, name) for cid, name in await native_due(session) if cid == str(CID)]
    async def send(emails, subject, body):
        trace.append('send'); delivered.append((emails, subject, body))
        pytestconfig._pulse_digest_lock_owner_boundary.record('synthetic.p9.send_notice')
    monkeypatch.setattr(pulse_digest, '_companies_due', due)
    monkeypatch.setattr(pulse_digest, 'send_notice', send)
    w = SimpleNamespace(**vars(pooled), trace=trace, delivered=delivered, observer=db)
    yield w
    await db.rollback()
    await db.execute(text('delete from audit_events where company_id=:cid'), {'cid': CID})
    await db.delete(await db.get(UserCompany, (UID, CID)))
    await db.delete(await db.get(User, UID))
    await db.execute(text('delete from pulse_targets where company_id=:cid'), {'cid': CID})
    await db.delete(await db.get(Company, CID)); await db.commit()


@pytest.mark.parametrize('end', ['rollback', 'commit'])
async def test_legacy_session_returns_locked_backend_to_pool(pooled, db, end):
    """Minimal old ownership pattern; controlled checkout makes the leak deterministic."""
    async with pooled.factory() as first:
        owner_pid = await first.scalar(text('select pg_backend_pid()'))
        assert await first.scalar(text('select pg_try_advisory_lock(:k)'), {'k': pulse_digest.LOCK_KEY}) is True
        await getattr(first, end)()
        # Only one physical connection existed: the borrower takes the locked PID.
        async with pooled.engine.connect() as borrower:
            assert await borrower.scalar(text('select pg_backend_pid()')) == owner_pid
            async with pooled.factory() as other:
                other_pid = await other.scalar(text('select pg_backend_pid()'))
                assert other_pid != owner_pid
                assert await other.scalar(text('select pg_try_advisory_lock(:k)'), {'k': pulse_digest.LOCK_KEY}) is False
                assert await other.scalar(text('select pg_advisory_unlock(:k)'), {'k': pulse_digest.LOCK_KEY}) is False
                assert await pids(db) == [owner_pid]
            assert await borrower.scalar(text('select pg_advisory_unlock(:k)'), {'k': pulse_digest.LOCK_KEY}) is True
            await borrower.commit()
    assert await pids(db) == []


@pytest.mark.parametrize('end', ['rollback', 'commit'])
async def test_concurrent_digest_owns_same_backend_across_day_transaction(world, monkeypatch, end):
    w = world; entered = asyncio.Event(); release = asyncio.Event(); identities = []
    real_day = pulse_day.pulse_day_data
    async def day(session, cid):
        before = await session.scalar(text('select pg_backend_pid()'))
        await getattr(session, end)()
        after = await session.scalar(text('select pg_backend_pid()'))
        identities.append((before, after)); entered.set(); await release.wait()
        return await real_day(session, cid)
    monkeypatch.setattr(pulse_day, 'pulse_day_data', day)
    first = asyncio.create_task(pulse_digest.run_once())
    try:
        await bounded(entered.wait())
        assert identities[0][0] == identities[0][1]
        assert await pids(w.observer) == [identities[0][0]]
        # A different key and a different lease cannot release or impersonate this owner.
        async with w.engine.connect() as other:
            assert await other.scalar(text('select pg_backend_pid()')) != identities[0][0]
            assert await other.scalar(text('select pg_advisory_unlock(:k)'), {'k': pulse_digest.LOCK_KEY}) is False
            assert await other.scalar(text('select pg_try_advisory_lock(:k)'), {'k': pulse_digest.LOCK_KEY + 1}) is True
            assert await other.scalar(text('select pg_advisory_unlock(:k)'), {'k': pulse_digest.LOCK_KEY + 1}) is True
            await other.commit()
        assert await bounded(pulse_digest.run_once()) == 0
        assert w.trace == ['due'] and w.delivered == [] and len(identities) == 1
        release.set(); assert await bounded(first) == 1
        assert await pids(w.observer) == []
        assert len(w.delivered) == 1 and w.delivered[0][0] == [EMAIL]
        assert w.delivered[0][1] == 'P9 synthetic: 1 на экране дня, из них тревожных 1'
        assert 'Данных о сессиях нет' in w.delivered[0][2]
        rows = (await w.observer.execute(select(AuditEvent.action, AuditEvent.details).where(AuditEvent.company_id == CID))).all()
        assert rows == [('pulse.digest', 'карточек: 1, адресатов: 1')]
        # Same-day native due predicate now excludes it, but the third worker got the lock.
        assert await bounded(pulse_digest.run_once()) == 0
        assert w.trace == ['due', 'send', 'due'] and len(w.delivered) == 1
    finally:
        release.set()
        if not first.done(): first.cancel()
        await asyncio.gather(first, return_exceptions=True)


@pytest.mark.parametrize('failure', ['query', 'send', 'acquire', 'unlock', 'unlock-false', 'audit-commit', 'invalidate', 'reconnect', 'abort-once', 'query-unlock'])
async def test_failure_releases_owned_backend_and_preserves_audit(world, monkeypatch, failure):
    w = world; real_day = pulse_day.pulse_day_data; blocked_sql = []; owner_pids = []; aborts = []
    async def day(session, cid):
        owner_pids.append(await session.scalar(text('select pg_backend_pid()')))
        if failure in ('query', 'query-unlock'):
            # An actual aborted transaction must be rolled back before cleanup SQL.
            await session.execute(text('select * from p9_intentionally_absent_relation'))
        if failure in ('invalidate', 'reconnect'):
            conn = await session.connection(); await conn.invalidate(); await session.rollback()
            if failure == 'reconnect':
                # SQLAlchemy attempts a replacement lease; scoped listener must reject BEFORE execution.
                await session.execute(text("select 'p9_reconnect_domain_sql'"))
            raise RuntimeError('synthetic invalidated day')
        if failure == 'unlock-false':
            assert await session.scalar(text('select pg_advisory_unlock(:k)'), {'k': pulse_digest.LOCK_KEY}) is True
            return {'cards': [], 'as_of': None}
        return await real_day(session, cid)
    async def send(*args):
        w.trace.append('send'); raise RuntimeError('synthetic sender error')
    monkeypatch.setattr(pulse_day, 'pulse_day_data', day)
    if failure == 'send': monkeypatch.setattr(pulse_digest, 'send_notice', send)
    def before(conn, cursor, sql, params, context, many):
        if failure in ('unlock', 'abort-once', 'query-unlock') and 'pg_advisory_unlock' in sql: raise RuntimeError('synthetic unlock error')
    def after(conn, cursor, sql, params, context, many):
        if 'p9_reconnect_domain_sql' in sql: blocked_sql.append(sql)
        if failure == 'acquire' and 'pg_try_advisory_lock' in sql: raise RuntimeError('synthetic acquisition response error')
    def commit(conn):
        if failure == 'audit-commit' and 'send' in w.trace: raise RuntimeError('synthetic audit commit error')
    def invalidation(dbapi_connection, record, error):
        if failure == 'abort-once' and not aborts:
            aborts.append('one-shot invalidate hook error'); raise RuntimeError('synthetic invalidate hook error')
    event.listen(w.engine.sync_engine, 'invalidate', invalidation)
    event.listen(w.engine.sync_engine, 'before_cursor_execute', before)
    event.listen(w.engine.sync_engine, 'after_cursor_execute', after)
    event.listen(w.engine.sync_engine, 'commit', commit)
    try:
        with pytest.raises(Exception) as caught: await bounded(pulse_digest.run_once())
        if failure == 'send': assert str(caught.value) == 'synthetic sender error'
        if failure in ('query', 'query-unlock'): assert 'p9_intentionally_absent_relation' in str(caught.value)
        if failure == 'reconnect': assert 'physical connection changed' in str(caught.value) and blocked_sql == []
    finally:
        event.remove(w.engine.sync_engine, 'before_cursor_execute', before)
        event.remove(w.engine.sync_engine, 'after_cursor_execute', after)
        event.remove(w.engine.sync_engine, 'commit', commit)
        event.remove(w.engine.sync_engine, 'invalidate', invalidation)
    assert await pids(w.observer) == []
    audits = list((await w.observer.execute(select(AuditEvent.action).where(AuditEvent.company_id == CID))).scalars())
    assert audits == (['pulse.digest'] if failure in ('unlock', 'abort-once') else [])
    if failure == 'abort-once':
        assert aborts == ['one-shot invalidate hook error']
        assert await w.observer.scalar(text('select count(*) from pg_stat_activity where pid=:pid'), {'pid': owner_pids[0]}) == 0
    # Real third acquisition after all error paths; no forced lock result.
    async with w.engine.connect() as probe:
        assert await probe.scalar(text('select pg_try_advisory_lock(:k)'), {'k': pulse_digest.LOCK_KEY}) is True
        assert await probe.scalar(text('select pg_advisory_unlock(:k)'), {'k': pulse_digest.LOCK_KEY}) is True
        await probe.commit()


@pytest.mark.parametrize('cleanup', ['normal', 'repeat-cancel', 'deadline'])
async def test_cancel_waits_for_bounded_cleanup_without_orphan_task(world, monkeypatch, cleanup):
    w = world; entered = asyncio.Event(); cleaning = asyncio.Event(); release = asyncio.Event()
    async def day(session, cid):
        await session.rollback(); entered.set(); await asyncio.Event().wait()
    monkeypatch.setattr(pulse_day, 'pulse_day_data', day)
    rollback = AsyncSession.rollback
    calls = 0
    async def paused_rollback(session):
        nonlocal calls
        calls += 1
        if calls == 2 and cleanup != 'normal':
            cleaning.set(); await release.wait()
        await rollback(session)
    monkeypatch.setattr(AsyncSession, 'rollback', paused_rollback)
    if cleanup == 'deadline': monkeypatch.setattr(pulse_digest, 'LOCK_CLEANUP_SECONDS', 0.15)
    first = asyncio.create_task(pulse_digest.run_once())
    try:
        await bounded(entered.wait()); first.cancel()
        if cleanup != 'normal':
            await bounded(cleaning.wait()); first.cancel(); first.cancel()
            if cleanup == 'repeat-cancel': release.set()
        with pytest.raises(asyncio.CancelledError): await bounded(first)
        assert await pids(w.observer) == [] and w.delivered == []
        assert await w.observer.scalar(select(AuditEvent.id).where(AuditEvent.company_id == CID)) is None
        assert not [t for t in asyncio.all_tasks() if not t.done() and t.get_name() == 'pulse-digest-lock-cleanup']
        # Third worker can genuinely enter; choose empty day to avoid a synthetic send.
        async def empty(session, cid): return {'cards': [], 'as_of': None}
        monkeypatch.setattr(pulse_day, 'pulse_day_data', empty)
        assert await bounded(pulse_digest.run_once()) == 0
        assert w.trace == ['due', 'due']
    finally:
        release.set()
        if not first.done(): first.cancel()
        await asyncio.gather(first, return_exceptions=True)


@pytest.mark.parametrize('raw', [
    'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/wrong_test',
    'postgresql+asyncpg://clearledger:api_test_only@localhost:33546/'+TARGET,
    'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:5432/'+TARGET,
    'postgresql+asyncpg://other:api_test_only@127.0.0.1:33546/'+TARGET,
    'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/'+TARGET+'?options=x',
], ids=['database', 'host', 'port', 'role', 'options'])
async def test_fixture_refuses_foreign_target_without_connect(raw):
    assert approved_target(raw) is False


async def test_factory_bind_unsupported_fails_before_sql(monkeypatch):
    monkeypatch.setattr(pulse_digest, 'async_session_factory', async_sessionmaker(bind=None))
    with pytest.raises(RuntimeError, match='AsyncEngine'):
        await pulse_digest.run_once()
