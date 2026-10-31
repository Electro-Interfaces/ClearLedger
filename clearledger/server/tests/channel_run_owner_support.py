"""ROOT-only fixtures: fresh bounded ORM contract, not application bootstrap/DDL proof."""
import os
from pathlib import Path
import uuid

import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TABLES = ('audit_events', 'channel_streams', 'channel_sync_logs', 'channels', 'companies',
          'company_roles', 'contract_locations', 'contracts', 'counterparties', 'data_entries',
          'eco_event_subscriptions', 'eco_outbox_events', 'org_departments', 'organizations',
          'regions', 'service_locations', 'source_files', 'sources',
          'station_contract_settlements', 'user_companies', 'users')
CID = uuid.UUID('b1100000-0000-4000-8000-000000000001')
OTHER = uuid.UUID('b1100000-0000-4000-8000-000000000002')
ENGINE = FACTORY = None
TRACE = None


def require_target():
    assert os.environ.get('RUN_CHANNEL_RUN_OWNER_TESTS') == '1'
    u = make_url(os.environ['TEST_DATABASE_URL'])
    assert (u.drivername, u.host, u.port, u.database, u.username, u.password, dict(u.query)) == (
        'postgresql+asyncpg', '127.0.0.1', 33546, 'api_channel_run_owner_test_20261031',
        'clearledger', 'api_test_only', {})
    return u


@pytest_asyncio.fixture(scope='session', loop_scope='session')
async def setup_database():
    global ENGINE, FACTORY
    from app import database, models
    from app.services.phone_e164 import PHONE_FUNCTION_DDL
    assert TRACE is not None
    engine = ENGINE = create_async_engine(require_target(), pool_size=2, max_overflow=0)
    factory = FACTORY = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # Import-created production pool remains unopened. Only this private test pool connects.
    old_engine, old_factory = database.engine, database.async_session_factory
    database.engine, database.async_session_factory = engine, factory
    tables = [database.Base.metadata.tables[name] for name in TABLES]
    try:
        async with engine.begin() as conn:
            assert await conn.scalar(text('select current_database()')) == 'api_channel_run_owner_test_20261031'
            assert await conn.scalar(text('select current_schema()')) == 'public'
            assert not await conn.scalar(text("select exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('r','p','v','m','f'))"))
            await conn.execute(text(PHONE_FUNCTION_DDL))
            await conn.run_sync(lambda sync: database.Base.metadata.create_all(sync, tables=tables, checkfirst=False))
        async with factory() as db:
            db.add_all([models.Company(id=CID, name='P11 ЭЗС', slug='gig', profile_id='energy'),
                        models.Company(id=OTHER, name='P11 Другая компания', slug='p11-other', profile_id='energy')])
            await db.commit()
        # Raw driver control complements prepared-path Engine.before_cursor_execute.
        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            assert await raw.driver_connection.fetchval('select current_database()') == 'api_channel_run_owner_test_20261031'
        assert TRACE.raw and TRACE.sqlalchemy
        assert engine.pool.size() == 2 and engine.pool._max_overflow == 0
        TRACE.record('fixture-ready')
        yield factory
    finally:
        assert engine.pool.checkedout() == 0
        await engine.dispose()
        await old_engine.dispose()
        database.engine, database.async_session_factory = old_engine, old_factory


@pytest_asyncio.fixture(loop_scope='session')
async def db(setup_database):
    async with setup_database() as session:
        yield session
        await session.rollback()


async def reset_world(factory):
    # Only this exact fresh DB's explicit fixture contract. No neighbouring schema or data.
    require_target()
    names = ', '.join('public.' + name for name in TABLES if name != 'companies')
    async with factory.begin() as db:
        await db.execute(text('TRUNCATE TABLE ' + names + ' CASCADE'))
