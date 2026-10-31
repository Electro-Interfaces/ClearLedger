"""ROOT-only real catalogue/migration/native audience goldens; synthetic fixed IDs."""
import os
if os.environ.get('RUN_PULSE_VIEW_ROLE_SCHEMA_TESTS')!='1':
    raise RuntimeError('ROOT-approved pulse role schema gate required')
import uuid
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import text,event
from sqlalchemy.ext.asyncio import create_async_engine

from app import database
from app.models import Company,CompanyRole,User,UserCompany,PulseView,PulseViewBlock,PulseViewRoleGrant
from app.auth import create_access_token
from app.main import app
from app.services.pulse_view_role_schema import require_connection
from schema_migrations.errors import MigrationError
from schema_migrations.manifest import PULSE_ID,load
from schema_migrations.runner import execute
from tests.pulse_view_role_schema_support import target_url,prepare_parents,apply_parents,migration_config

pytestmark=pytest.mark.asyncio(loop_scope='session')
A=uuid.UUID('c2100000-0000-4000-8000-000000000001');B=uuid.UUID('c2100000-0000-4000-8000-000000000002')
RA=uuid.UUID('c2100000-0000-4000-8000-000000000011');RB=uuid.UUID('c2100000-0000-4000-8000-000000000012')
VA=uuid.UUID('c2100000-0000-4000-8000-000000000021');VB=uuid.UUID('c2100000-0000-4000-8000-000000000022')
UA=uuid.UUID('c2100000-0000-4000-8000-000000000031');UB=uuid.UUID('c2100000-0000-4000-8000-000000000032');ADMIN=uuid.UUID('c2100000-0000-4000-8000-000000000033')

@pytest.fixture
async def world(db):
    db.add_all([Company(id=A,name='C2 A',slug='c2-a',profile_id='energy'),Company(id=B,name='C2 B',slug='c2-b',profile_id='energy')]);await db.flush()
    db.add_all([CompanyRole(id=RA,company_id=A,name='C2 role A',modules=['pulse']),CompanyRole(id=RB,company_id=B,name='C2 role B',modules=['pulse'])])
    db.add_all([User(id=u,company_id=c,name=n,email=n+'@example.test',password_hash='!',role='user') for u,c,n in [(UA,A,'c2-reader'),(UB,B,'c2-other'),(ADMIN,A,'c2-admin')]]);await db.flush()
    db.add_all([UserCompany(user_id=UA,company_id=A,role='user',role_id=RA),UserCompany(user_id=UB,company_id=B,role='user',role_id=RB),UserCompany(user_id=ADMIN,company_id=A,role='admin')])
    db.add_all([PulseView(id=VA,company_id=A,name='C2 view A',status='published',feedback_mode='none'),PulseView(id=VB,company_id=B,name='C2 view B',status='published',feedback_mode='none')]);await db.flush()
    db.add(PulseViewBlock(view_id=VA,block_key='net.sales',sort=0));await db.commit()
    from httpx import ASGITransport,AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        def headers(uid):return {'Authorization':'Bearer '+create_access_token(str(uid),str(uid)+'@example.test')}
        yield NS(db=db,c=client,h=headers)
    await db.rollback()
    for sql in ('delete from pulse_views where company_id in (:a,:b)','delete from audit_events where company_id in (:a,:b)','delete from user_companies where company_id in (:a,:b)','delete from users where id in (:u,:v,:w)','delete from company_roles where company_id in (:a,:b)','delete from companies where id in (:a,:b)'):
        await db.execute(text(sql),{'a':A,'b':B,'u':UA,'v':UB,'w':ADMIN})
    await db.commit()

async def request(w,method,path,uid=UA,cid=A,**kw):
    return await w.c.request(method,path,headers=w.h(uid),params={'company_id':str(cid)},**kw)

async def grants(db):return (await db.execute(text('select view_id,role_id from pulse_view_role_grants where view_id=:v order by role_id'),{'v':VA})).all()

async def test_fresh_proof_precedes_main_import(pytestconfig):
    assert pytestconfig._pulse_view_role_schema_boundary.preparation=={'without_app_main':True,'parent_count':10,'actions':['created','adopted','created'],'readonly_guard':True}

@pytest.mark.parametrize('payload,expected',[
 ({'roles':[str(RA),str(RA),str(RB),'bad']},{'roles':1,'skipped':3}),
 ({'roles':[str(RB)]},{'roles':0,'skipped':1}),({}, {'roles':0,'skipped':0}),
 ({'roles':None},{'roles':0,'skipped':0}),
],ids=['duplicate-foreign-invalid','foreign-clears','missing-clears','null-clears'])
async def test_native_setter_fixed_counts_and_replace(world,payload,expected):
    w=world;await w.db.execute(text('insert into pulse_view_role_grants values(:v,:r)'),{'v':VA,'r':RA});await w.db.commit()
    r=await request(w,'PUT',f'/api/pulse/views/{VA}/roles',uid=ADMIN,json=payload)
    assert r.status_code==200 and r.json()==expected
    assert await grants(w.db)==([(VA,RA)] if expected['roles'] else [])
    assert await w.db.scalar(text("select count(*) from audit_events where company_id=:c"),{'c':A})==0

@pytest.mark.parametrize('change', ['role','member','product','draft','user-or-role','new-member'],ids=['role','member','product','draft','user-or-role','new-member'])
async def test_current_audience_read_revoke_and_tenant(world,change):
    w=world;await w.db.execute(text('insert into pulse_view_role_grants values(:v,:r)'),{'v':VA,'r':RA});await w.db.commit()
    r=await request(w,'GET','/api/pulse/my-views');assert r.status_code==200 and [v['id'] for v in r.json()['views']]==[str(VA)]
    assert (await request(w,'GET',f'/api/pulse/views/{VA}/data')).status_code==200
    assert (await request(w,'GET',f'/api/pulse/views/{VA}',uid=UB)).status_code==403
    assert (await request(w,'GET',f'/api/pulse/views/{VB}',uid=ADMIN)).status_code==404
    assert (await request(w,'GET','/api/pulse/my-views',uid=ADMIN)).json()=={'views':[]}
    if change=='role':await w.db.execute(text('update user_companies set role_id=NULL,modules=\'["pulse"]\'::jsonb where user_id=:u'),{'u':UA})
    if change=='member':await w.db.execute(text('delete from user_companies where user_id=:u'),{'u':UA})
    if change=='product':await w.db.execute(text('update company_roles set modules=\'["docs"]\'::jsonb where id=:r'),{'r':RA})
    if change=='draft':await w.db.execute(text("update pulse_views set status='draft' where id=:v"),{'v':VA})
    if change=='new-member':
        w.db.add(UserCompany(user_id=UB,company_id=A,role='user',role_id=RA))
    if change=='user-or-role':
        await w.db.execute(text('insert into pulse_view_grants values(:v,:u)'),{'v':VA,'u':UA})
        await w.db.execute(text('delete from pulse_view_role_grants where view_id=:v'),{'v':VA})
    await w.db.commit()
    r=await request(w,'GET',f'/api/pulse/views/{VA}/data')
    if change=='new-member':
        assert (await request(w,'GET',f'/api/pulse/views/{VA}/data',uid=UB)).status_code==200
        assert await grants(w.db)==[(VA,RA)]
    assert r.status_code==({'role':404,'member':403,'product':403,'draft':404,'user-or-role':200,'new-member':200}[change])

@pytest.mark.parametrize('kind',['view','role','system-role'],ids=['view','role','system-role'])
async def test_native_deletion_cascade_and_default_modules(world,kind):
    w=world;await w.db.execute(text('insert into pulse_view_role_grants values(:v,:r)'),{'v':VA,'r':RA});await w.db.commit()
    if kind=='view':
        r=await request(w,'DELETE',f'/api/pulse/views/{VA}',uid=ADMIN);assert r.status_code==400
        await w.db.execute(text("update pulse_views set status='draft' where id=:v"),{'v':VA});await w.db.commit()
        assert (await request(w,'DELETE',f'/api/pulse/views/{VA}',uid=ADMIN)).json()=={'deleted':True}
    else:
        if kind=='system-role':await w.db.execute(text('update company_roles set is_system=true where id=:r'),{'r':RA});await w.db.commit()
        r=await request(w,'DELETE',f'/api/roles/{RA}',uid=ADMIN)
        assert r.status_code==(403 if kind=='system-role' else 204)
        if kind=='role':
            row=(await w.db.execute(text('select role_id,modules from user_companies where user_id=:u'),{'u':UA})).one()
            assert tuple(row)==(None,None)
    assert await grants(w.db)==([(VA,RA)] if kind=='system-role' else [])

@pytest.mark.parametrize('bad',['duplicate','null','unknown-parent'],ids=['duplicate','null','unknown-parent'])
async def test_real_constraints_rollback_preserves_previous_grant(world,bad):
    w=world;await w.db.execute(text('insert into pulse_view_role_grants values(:v,:r)'),{'v':VA,'r':RA});await w.db.commit()
    with pytest.raises(Exception):
        async with w.db.begin_nested():
            await w.db.execute(text('insert into pulse_view_role_grants values(:v,:r)'),{'v':VA,'r':RA if bad=='duplicate' else None if bad=='null' else uuid.UUID(int=9)})
    assert await grants(w.db)==[(VA,RA)]

@pytest.fixture
async def core(setup_database):
    engine=create_async_engine(target_url(),pool_size=2,max_overflow=0,connect_args={'server_settings':{'search_path':'core, public'}})
    async with engine.begin() as conn:
        assert await conn.scalar(text("select count(*) from pg_namespace where nspname='core'"))==0
        await conn.execute(text('CREATE SCHEMA core'))
    try:yield engine
    finally:
        async with engine.begin() as conn:await conn.execute(text('DROP SCHEMA core CASCADE'))
        await engine.dispose()

@pytest.mark.parametrize('mode',['fresh','adopt','bad-adopt','drift','missing-ready','managed-on'],ids=['fresh','adopt','bad-adopt','drift','missing-ready','managed-on'])
async def test_versioned_core_and_startup_boundary(core,monkeypatch,mode):
    statements=[]
    def record(conn,cursor,sql,params,context,many):statements.append(sql.strip().lower())
    event.listen(core.sync_engine,'before_cursor_execute',record)
    try:
        monkeypatch.setattr(database,'engine',core)
        with pytest.raises(RuntimeError,match='^Database schema ownership check failed; review namespace provisioning$'):
            await database.create_all()
        assert not any(s.startswith(('create ','alter ','insert ','update ','delete ')) for s in statements)
        await prepare_parents(core);await apply_parents()
        if mode=='bad-adopt':
            async with core.begin() as conn:
                await conn.execute(text('CREATE TABLE core.pulse_view_role_grants(view_id UUID,role_id UUID)'))
                await conn.execute(text('INSERT INTO core.pulse_view_role_grants VALUES(NULL,NULL)'))
            with pytest.raises(MigrationError):await execute(migration_config(),'apply',revision=PULSE_ID)
            async with core.connect() as conn:
                assert (await conn.execute(text('SELECT view_id,role_id FROM core.pulse_view_role_grants'))).all()==[(None,None)]
                assert await conn.scalar(text('SELECT count(*) FROM core.core_schema_versions'))==2
            return
        if mode=='adopt':
            async with core.begin() as conn:
                await conn.execute(text(load(revision=PULSE_ID).sql))
                from sqlalchemy.ext.asyncio import AsyncSession
                async with AsyncSession(bind=conn,expire_on_commit=False) as session:
                    session.add(Company(id=A,name='C2 adopted',slug='c2-adopt',profile_id='energy'));await session.flush()
                    session.add_all([CompanyRole(id=RA,company_id=A,name='C2 adoptedrole',modules=['pulse']),PulseView(id=VA,company_id=A,name='C2 adoptedview')]);await session.flush()
                await conn.execute(text('INSERT INTO core.pulse_view_role_grants VALUES(:v,:r)'),{'v':VA,'r':RA})
                await conn.execute(text('GRANT SELECT ON core.pulse_view_role_grants TO clearledger'))
        a=await execute(migration_config(),'apply',revision=PULSE_ID)
        assert a['action']==('adopted' if mode=='adopt' else 'created')
        if mode=='adopt':
            async with core.connect() as conn:
                assert (await conn.execute(text('SELECT view_id,role_id FROM core.pulse_view_role_grants'))).all()==[(VA,RA)]
        assert (await execute(migration_config(),'apply',revision=PULSE_ID))['action']=='verified'
        async with core.connect() as conn:await require_connection(conn)
        if mode in ('drift','missing-ready'):
            async with core.begin() as conn:
                await conn.execute(text('ALTER TABLE core.pulse_view_role_grants ADD COLUMN unexpected text' if mode=='drift' else 'DROP TABLE core.pulse_view_role_grants'))
            async with core.connect() as conn:
                with pytest.raises(RuntimeError,match='Pulse audience schema'):await require_connection(conn)
            with pytest.raises(MigrationError):await execute(migration_config(),'check',revision=PULSE_ID)
        if mode=='managed-on':
            from app.config import Settings
            from app.services.schema_version_gate import require_connection as budget_guard
            settings=Settings(_env_file=None,database_url=target_url(),SECRET_KEY='c2-synthetic-guard-test-only-long-key',managed_core_budget_enabled=True,managed_core_budget_expected_database=migration_config().database,managed_core_budget_expected_user='clearledger')
            async with core.connect() as conn:
                with pytest.raises(RuntimeError,match='Managed Core budget schema'):await budget_guard(conn,settings)
    finally:event.remove(core.sync_engine,'before_cursor_execute',record)


@pytest.mark.parametrize('damage',['missing','drift'])
async def test_readiness_refuses_post_startup_damage(world,damage):
    w=world
    await w.db.execute(text('DROP TABLE public.pulse_view_role_grants' if damage=='missing' else 'ALTER TABLE public.pulse_view_role_grants ADD COLUMN unwanted text'));await w.db.commit()
    try:
        assert (await w.c.get('/api/ready')).status_code==503
    finally:
        await w.db.rollback()
        if damage=='missing':
            conn=await w.db.connection();await conn.run_sync(lambda sync:PulseViewRoleGrant.__table__.create(sync))
        else:await w.db.execute(text('ALTER TABLE public.pulse_view_role_grants DROP COLUMN unwanted'))
        await w.db.commit()


@pytest.mark.parametrize('prefix',['one','two','three','future','gap','hash','missing-catalog','require-later'],ids=['one','two','three','future','gap','hash','missing-catalog','require-later'])
async def test_readonly_applied_prefix_public_api(core,prefix):
    from schema_migrations.manifest import load_known_head
    from schema_migrations.runner import require_applied_prefix
    await prepare_parents(core)
    await execute(migration_config(),'apply')
    if prefix in ('two','three','gap','missing-catalog'):
        await execute(migration_config(),'apply',revision='0002_calendar_protocol_sequence',legacy_sent_before=2000000000)
    if prefix in ('three','missing-catalog'):
        await execute(migration_config(),'apply',revision=PULSE_ID)
    async with core.begin() as conn:
        if prefix=='one':
            # These source-head prerequisites are NOT applied and must not be required.
            await conn.execute(text('DROP TABLE core.calendar_events,core.pulse_views,core.company_roles'))
        if prefix=='future':
            await conn.execute(text("INSERT INTO core.core_schema_versions(revision,ordinal,parent_revision,artifact_sha256,contract_sha256,predecessor_sha256,action,applied_by,app_commit,runner_format) SELECT '0004_future',4,revision,artifact_sha256,contract_sha256,artifact_sha256,action,applied_by,app_commit,runner_format FROM core.core_schema_versions WHERE ordinal=1"))
        if prefix=='gap':await conn.execute(text('DELETE FROM core.core_schema_versions WHERE ordinal=1'))
        if prefix=='hash':await conn.execute(text("UPDATE core.core_schema_versions SET artifact_sha256=repeat('0',64) WHERE ordinal=1"))
        if prefix=='missing-catalog':await conn.execute(text('DROP TABLE core.pulse_view_role_grants'))
    async with core.connect() as conn:
        # SQLAlchemy establishes the caller's transaction; API must retain it.
        await conn.execute(text('SELECT 1'))
        raw=await conn.get_raw_connection();driver=raw.driver_connection
        before=(driver.is_in_transaction(),await driver.fetchval("SELECT current_setting('search_path')"))
        if prefix in ('future','gap','hash','missing-catalog','require-later'):
            with pytest.raises(MigrationError):
                await require_applied_prefix(driver,migration_config(),load_known_head(),required_revision=PULSE_ID if prefix=='require-later' else '0001_product_api_budgets')
        else:await require_applied_prefix(driver,migration_config(),load_known_head())
        assert (driver.is_in_transaction(),await driver.fetchval("SELECT current_setting('search_path')"))==before
        rows=await driver.fetchval('SELECT count(*) FROM core.core_schema_versions')
        assert rows==({'one':1,'two':2,'three':3,'future':2,'gap':1,'hash':1,'missing-catalog':3,'require-later':1}[prefix])


@pytest.mark.parametrize('namespace,path,expected',[
 ('public','"$user", public',True),('public',' public ',True),('public','"public"',True),
 ('core','core, public',True),('public','core, public',False),
 ('public',' "core" , public ',False),('public','public, core',False),
 ('public','"ambiguous,path", public',False),('public','',False),
],ids=['legacy-default','public-whitespace','public-quoted','core','missing-core','quoted-core','core-later','ambiguous','empty'])
async def test_namespace_literal_controls(namespace,path,expected):
    from app.services.pulse_view_role_schema import namespace_path_is_explicit
    assert namespace_path_is_explicit(namespace,path) is expected


async def test_missing_core_does_not_accept_canonical_public(setup_database,monkeypatch):
    from httpx import ASGITransport,AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker
    engine=create_async_engine(target_url(),pool_size=2,max_overflow=0,connect_args={'server_settings':{'search_path':'"core", public'}})
    statements=[]
    def record(conn,cursor,sql,params,context,many):statements.append(sql.strip().lower())
    event.listen(engine.sync_engine,'before_cursor_execute',record)
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text('SELECT current_schema()'))=='public'
            assert await conn.scalar(text("SELECT to_regclass('public.pulse_view_role_grants')")) is not None
            with pytest.raises(RuntimeError,match='Pulse audience schema'):await require_connection(conn)
        monkeypatch.setattr(database,'engine',engine)
        with pytest.raises(RuntimeError,match='schema ownership'):await database.create_all()
        assert not any(sql.startswith(('create ','alter ','insert ','update ','delete ')) for sql in statements)
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async def borrow():
            async with factory() as session:yield session
        with monkeypatch.context() as local:
            local.setitem(app.dependency_overrides,database.get_db,borrow)
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                assert (await client.get('/api/ready')).status_code==503
    finally:
        event.remove(engine.sync_engine,'before_cursor_execute',record)
        await engine.dispose()
