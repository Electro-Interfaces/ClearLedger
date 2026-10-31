"""ROOT-only fresh prerequisite proof, invoked before conftest/app.main imports."""
import os
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

TARGET='api_pulse_view_role_schema_test_20261031'
PARENTS=('companies','users','organizations','eco_apps','eco_company_apps','partner_clients',
         'partner_installations','calendar_events','company_roles','pulse_views')


def target_url():
    raw=os.environ['TEST_DATABASE_URL']; u=make_url(raw)
    assert (u.drivername,u.host,u.port,u.database,u.username,u.password,u.query)==(
        'postgresql+asyncpg','127.0.0.1',33546,TARGET,'clearledger','api_test_only',{})
    return raw


async def prepare_parents(engine):
    """Fresh-only literal parents; no generic discovery or legacy ALTER/seed."""
    from app import database,models,models_partner
    from app.services.phone_e164 import PHONE_FUNCTION_DDL
    async with engine.begin() as conn:
        assert await conn.scalar(text('select current_schema()'))=='core'
        assert not await conn.scalar(text("select exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='core' and c.relkind in ('r','p','v','m','f'))"))
        await conn.execute(text('select pg_advisory_xact_lock(434532,1)'))
        await conn.execute(text(PHONE_FUNCTION_DDL))
        tables=[database.Base.metadata.tables[name] for name in PARENTS]
        await conn.run_sync(lambda sync: database.Base.metadata.create_all(sync,tables=tables,checkfirst=False))
        assert await conn.scalar(text("select to_regclass('core.pulse_view_role_grants')")) is None
        assert await conn.scalar(text("select to_regclass('core.product_api_budgets')")) is None


def migration_config():
    from schema_migrations.runner import Config
    return Config(make_url(target_url()).set(drivername='postgresql').render_as_string(hide_password=False),TARGET,'clearledger','core')


async def apply_parents():
    from schema_migrations.runner import execute
    a=await execute(migration_config(),'apply')
    b=await execute(migration_config(),'apply',revision='0002_calendar_protocol_sequence',legacy_sent_before=2000000000)
    return [a['action'],b['action']]


async def prepare_without_main():
    assert 'app.main' not in sys.modules
    engine=create_async_engine(target_url(),pool_size=2,max_overflow=0,
        connect_args={'server_settings':{'search_path':'core, public'}})
    owned=False
    try:
        async with engine.begin() as conn:
            assert await conn.scalar(text("select count(*) from pg_namespace where nspname='core'"))==0
            await conn.execute(text('CREATE SCHEMA core'));owned=True
        await prepare_parents(engine)
        actions=await apply_parents()
        from schema_migrations.runner import execute
        actions.append((await execute(migration_config(),'apply',revision='0003_pulse_view_role_grants'))['action'])
        async with engine.connect() as conn:
            from app.services.pulse_view_role_schema import require_connection
            await require_connection(conn)
            rows=(await conn.execute(text('select revision from core.core_schema_versions order by ordinal'))).scalars().all()
        assert actions==['created','adopted','created']
        assert list(rows)==['0001_product_api_budgets','0002_calendar_protocol_sequence','0003_pulse_view_role_grants']
        assert 'app.main' not in sys.modules
        return {'without_app_main':True,'parent_count':10,'actions':actions,'readonly_guard':True}
    finally:
        if owned:
            async with engine.begin() as conn:await conn.execute(text('DROP SCHEMA core CASCADE'))
        await engine.dispose()
