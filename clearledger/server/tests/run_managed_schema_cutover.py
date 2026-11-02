"""Isolated managed-cutover contract harness; no app/DB imports before root guards.

--source-check is AST/Git-bytes only. SQL execution requires an independently
approved wrapper and an exclusive root window; repository conftest is never used.
"""
import ast
import asyncio
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
import uuid

SERVER=Path(__file__).resolve().parents[1]
REPO=SERVER.parents[1]
sys.path.insert(0,str(SERVER))
BASELINE='0f847b6f9bd94e1faff1476913ace2219749ced4'
FLAG='RUN_MANAGED_SCHEMA_CUTOVER_TESTS'
TARGET='postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_managed_schema_cutover_test'
RAW=TARGET.replace('postgresql+asyncpg:','postgresql:',1)
BASE=Path('/srv/projects/api-modernization-test-env-20261029')
EMPTY=BASE/'managed-schema-cutover-empty-test'
UPLOAD=BASE/'managed-schema-cutover-test-uploads'
EVIDENCE=BASE/'private-managed-schema-cutover-20261030'
FROZEN='c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e'
FLAG_NAME='managed_core_budget_enabled'


def tree_digest(root, *, suffix=None):
    paths=[p for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
        and (suffix is None or p.suffix==suffix)]
    if len(paths)>1024 or sum(p.stat().st_size for p in paths)>32*1024*1024:
        raise RuntimeError('Source bounds exceeded')
    files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return hashlib.sha256(('\n'.join(name+'\0'+sha for name,sha in files.items())+'\n').encode()).hexdigest()


def source_check():
    """Semantic AST parity of the entire legacy modules when new flag guards are off."""
    class Legacy(ast.NodeTransformer):
        def visit_If(self,node):
            self.generic_visit(node)
            if ast.dump(node.test)==ast.dump(ast.Attribute(value=ast.Name(id='settings',ctx=ast.Load()),attr=FLAG_NAME,ctx=ast.Load())):
                return node.orelse
            return node
    fields={FLAG_NAME,'managed_core_budget_expected_database','managed_core_budget_expected_user'}
    for name in ['config.py','database.py','main.py']:
        path=SERVER/'app'/name
        actual=ast.parse(path.read_text())
        before=ast.parse(subprocess.check_output(['git','-C',str(REPO),'show',BASELINE+':clearledger/server/app/'+name],text=True))
        restored=Legacy().visit(copy.deepcopy(actual))
        if name=='config.py':
            settings=next(n for n in restored.body if isinstance(n,ast.ClassDef) and n.name=='Settings')
            removed=[n for n in settings.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id in fields]
            assert len(removed)==3
            enabled=next(n for n in removed if n.target.id==FLAG_NAME)
            assert isinstance(enabled.value,ast.Constant) and enabled.value.value is False
            settings.body=[n for n in settings.body if n not in removed]
        assert ast.dump(restored)==ast.dump(before),name+' legacy AST changed'
    assert tree_digest(SERVER/'schema_migrations')==FROZEN
    docker=(SERVER/'Dockerfile').read_text().splitlines()
    assert 'WORKDIR /app' in docker and 'COPY app ./app' in docker
    assert 'COPY schema_migrations ./schema_migrations' in docker
    assert not any('schema_migrations' in line for line in (SERVER/'.dockerignore').read_text().splitlines())
    # Static constructor compatibility is only a source control, not an ORM proof.
    declarations={}
    for file in ['models.py','models_partner.py']:
        tree=ast.parse((SERVER/'app'/file).read_text())
        for node in tree.body:
            if isinstance(node,ast.ClassDef):
                declarations[node.name]={n.target.id for n in node.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name)}
    own=ast.parse(Path(__file__).read_text())
    fixture=next(n for n in ast.walk(own) if isinstance(n,ast.AsyncFunctionDef) and n.name=='fixture_budget')
    for node in ast.walk(fixture):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in declarations:
            assert {k.arg for k in node.keywords}<=declarations[node.func.id],node.func.id
    for path in [SERVER/'app'/n for n in ['config.py','database.py','main.py','services/schema_version_gate.py']]:
        compile(ast.parse(path.read_text()),str(path),'exec')
    print('PASS legacy-off entire-module AST parity (3 files), defaultOFF, frozen16 SHA, own compile; NO app/DB imports')


def guard():
    from tests.partner_test_safety import partner_test_safety_error
    error=partner_test_safety_error(os.environ,flag=FLAG)
    if error:
        raise RuntimeError('Refusing managed cutover tests: '+error)
    allowed={'HOME','PATH','LANG','APP_ENV','SECRET_KEY','HOSTNAME','ECOSYSTEM_COMPANIES',
        'DATABASE_URL','TEST_DATABASE_URL','SCHEMA_MIGRATION_TEST_DSN','UPLOAD_DIR',FLAG,'PYTHONDONTWRITEBYTECODE'}
    if set(os.environ)-allowed:
        raise RuntimeError('Refusing managed cutover tests: environment is not scrubbed')
    if (any(os.environ.get(k)!=TARGET for k in ['DATABASE_URL','TEST_DATABASE_URL'])
            or os.environ.get('SCHEMA_MIGRATION_TEST_DSN')!=RAW or os.environ.get('APP_ENV')!='test'
            or os.environ.get('UPLOAD_DIR')!=str(UPLOAD) or Path.cwd()!=EMPTY or any(EMPTY.iterdir())
            or sys.version_info[:3]!=(3,13,7) or not EVIDENCE.is_dir() or EVIDENCE.stat().st_mode & 0o077
            or os.environ.get('ECOSYSTEM_COMPANIES')!='managed-test|Synthetic company|Synthetic|energy'
            or os.environ.get('HOSTNAME')!='managed-cutover-test'
            or os.environ.get('SECRET_KEY')!='managed-cutover-synthetic-secret-key-only'
            or os.environ.get('PYTHONDONTWRITEBYTECODE')!='1'):
        raise RuntimeError('Refusing managed cutover tests: exact target/flags/directories required')
    from tests.managed_schema_cutover_approved import verify_approval
    verify_approval()


class ManagedCutover(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        guard()  # Also protects import + direct unittest loader paths.
        import asyncpg
        from sqlalchemy import event,text
        from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
        from app import database,main
        from app.config import get_settings
        self.event,self.text=event,text
        self.database,self.main=database,main
        self.settings=get_settings()
        self.settings.managed_core_budget_enabled=False
        self.settings.managed_core_budget_expected_database='api_managed_schema_cutover_test'
        self.settings.managed_core_budget_expected_user='clearledger'
        self.settings.app_env='test'
        self.create_engine,self.make_factory=create_async_engine,async_sessionmaker
        self.engines=[]
        # No startup/lifespan: imported application only registers its actual models/routes.
        await database.engine.dispose()
        self.control=await asyncpg.connect(RAW,timeout=5,command_timeout=15,
            server_settings={'search_path':'pg_catalog','statement_timeout':'15000','lock_timeout':'1000'})
        self.addAsyncCleanup(self.control.close)
        self.addAsyncCleanup(self.cleanup)
        objects=await self.relations()
        self.assertEqual(objects,[], 'Dedicated DB must be empty before each profile')
        await self.control.execute('CREATE SCHEMA core')
        await self.control.execute('CREATE SCHEMA edge')

    async def relations(self):
        return [dict(r) for r in await self.control.fetch("""SELECT n.nspname AS schema,c.relname AS name,c.relkind::text AS kind
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
              AND n.nspname NOT LIKE 'pg_temp%' AND c.relkind IN ('r','p','v','m','S','f') ORDER BY 1,2""")]

    async def cleanup(self):
        # Close all own app pools/sessions before bounded DDL cleanup. No maxlocks changes.
        for engine in self.engines:
            await engine.dispose()
        objects=await self.relations()
        self.assertLessEqual(sum(r['kind'] in ('r','p') for r in objects),400)
        self.assertTrue(all(r['schema'] in {'core','public','edge'} for r in objects))
        quote=lambda s:'"'+s.replace('"','""')+'"'
        for kind,noun in [('v','VIEW'),('m','MATERIALIZED VIEW'),('f','FOREIGN TABLE')]:
            for row in objects:
                if row['kind']==kind:
                    await self.control.execute('DROP '+noun+' IF EXISTS '+quote(row['schema'])+'.'+quote(row['name'])+' CASCADE')
        tables=[row for row in objects if row['kind'] in ('r','p')]
        for offset in range(0,len(tables),8):
            batch=','.join(quote(r['schema'])+'.'+quote(r['name']) for r in tables[offset:offset+8])
            await self.control.execute('DROP TABLE IF EXISTS '+batch+' CASCADE')
        # Table drops remove owned serial sequences. Remaining own namespace functions/types
        # are discarded only after all large table/index/FK batches committed.
        for schema in ['edge','core','public']:
            await self.control.execute('DROP SCHEMA '+schema+' CASCADE')
        await self.control.execute('CREATE SCHEMA public')
        self.assertEqual(await self.relations(),[])
        self.assertEqual(await self.control.fetchval("SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()"),0)

    async def bind(self,path):
        for engine in self.engines:
            await engine.dispose()
        engine=self.create_engine(TARGET,pool_size=3,max_overflow=0,pool_timeout=10,
            connect_args={'server_settings':{'search_path':path,'statement_timeout':'30000','lock_timeout':'1000'}})
        self.engines.append(engine)
        factory=self.make_factory(engine,expire_on_commit=False)
        self.database.engine=engine
        self.database.async_session_factory=factory
        self.main.async_session_factory=factory
        self.engine,self.factory=engine,factory

    @contextmanager
    def observations(self):
        value={'writes':[],'probe_count':0,'metadata_budget_checks':0,'legacy_ready_probes':0}
        def before(conn,cursor,statement,params,context,many):
            sql=' '.join(statement.lower().split())
            if sql.split(' ',1)[0] in {'create','alter','drop','do','insert','update','delete','truncate'}:
                value['writes'].append(sql.split(' ',1)[0])
            if sql.startswith('select count(*) = 20'):
                value['legacy_ready_probes']+=1
            if "current_setting('transaction_read_only')" in sql:
                value['probe_count']+=1
            # Real SQLAlchemy has_table query only, not the namespace ANY-array guard.
            if 'pg_catalog.pg_class.relname =' in sql and 'product_api_budgets' in repr(params):
                value['metadata_budget_checks']+=1
        self.event.listen(self.engine.sync_engine,'before_cursor_execute',before)
        try: yield value
        finally: self.event.remove(self.engine.sync_engine,'before_cursor_execute',before)
        # Raw frozen verifier SELECTs do not traverse this observer. Never report full SQL counts.

    async def size(self):
        size=await self.control.fetchval('SELECT pg_database_size(current_database())')
        self.assertLess(size,256*1024*1024)
        self.assertLessEqual(sum(r['kind'] in ('r','p') for r in await self.relations()),400)
        return size

    async def budget_state(self):
        result={}
        for name in ['product_api_budgets','core_schema_versions']:
            oid=await self.control.fetchval('SELECT to_regclass($1)::oid','core.'+name)
            rows=None if oid is None else [tuple(r) for r in await self.control.fetch(f'SELECT xmin::text,ctid::text,* FROM core.{name} ORDER BY 1,2')]
            result[name]=(oid,rows)
        return result

    async def assert_no_write(self,call):
        before=await self.budget_state()
        with self.observations() as observed:
            with self.assertRaises(RuntimeError): await call()
        self.assertEqual(observed['writes'],[])
        self.assertEqual(await self.budget_state(),before)

    async def assert_ready_gate_refuses(self):
        from fastapi import HTTPException
        previous=self.settings.app_env
        self.settings.app_env='test'
        try:
            with self.observations() as observed:
                with self.assertRaises(HTTPException) as failed:
                    await self.ready()
            self.assertEqual(failed.exception.status_code,503)
            self.assertEqual(observed['legacy_ready_probes'],0)
        finally:
            self.settings.app_env=previous

    async def startup(self):
        async with self.database.database_startup_lock():
            await self.main._prepare_database_once(datetime.now(timezone.utc))

    async def fixture_budget(self):
        from app.models import App,Company,CompanyApp
        from app.models_partner import PartnerClient,PartnerInstallation
        async with self.factory() as session:
            company=Company(id=uuid.uuid4(),name='Synthetic company',slug='managed-test',profile_id='energy')
            app=App(id=uuid.uuid4(),code='managed-test-app',name='Synthetic app',kind='partner',is_active=True)
            session.add_all([company,app]);await session.flush()
            client=PartnerClient(id='managed-test-client',app_id=app.id,owner_company_id=company.id,
                redirect_uris=['https://example.invalid/callback'],allowed_scopes=[],auth_method='client_secret_basic',enabled=True)
            installed=CompanyApp(id=uuid.uuid4(),company_id=company.id,app_id=app.id,enabled=True)
            session.add_all([client,installed]);await session.flush()
            session.add(PartnerInstallation(id=installed.id,company_id=company.id,client_id=client.id,
                approved=True,scopes=[],all_locations=True))
            await session.commit()
        await self.control.execute("INSERT INTO core.product_api_budgets VALUES ($1,$2,$3,1,'2026-10-30T12:00:00+00',10,60)",company.id,installed.id,client.id)

    async def ready(self):
        async with self.factory() as session:
            return await self.main.readiness_check(session)

    async def test_01_legacy_public_fresh_repeat_default_off(self):
        await self.bind('public')
        with self.observations() as first:
            await self.database.create_all()
        self.assertEqual(first['probe_count'],0)
        self.assertGreater(first['metadata_budget_checks'],0)
        count=sum(r['schema']=='public' and r['kind']=='r' for r in await self.relations())
        self.assertGreater(count,300)
        self.assertIsNotNone(await self.control.fetchval("SELECT to_regclass('public.product_api_budgets')::oid"))
        self.assertIsNone(await self.control.fetchval("SELECT to_regclass('public.core_schema_versions')::oid"))
        with self.observations() as repeat:
            await self.database.create_all()
        self.assertEqual(repeat['probe_count'],0)
        self.assertEqual(count,sum(r['schema']=='public' and r['kind']=='r' for r in await self.relations()))
        await self.size()

    async def test_02_core_managed_startup_marker_ready_and_negatives(self):
        await self.bind('core')
        with self.observations() as legacy:
            await self.database.create_all()
            await self.database.create_all()
        self.assertEqual(legacy['probe_count'],0)
        self.assertGreater(legacy['metadata_budget_checks'],0)
        await self.fixture_budget()
        from schema_migrations.runner import Config,execute
        cfg=Config(RAW,'api_managed_schema_cutover_test','clearledger','core')
        self.assertEqual((await execute(cfg,'apply'))['action'],'adopted')
        await self.control.execute('CREATE TABLE public.product_api_budgets (id integer PRIMARY KEY,marker text NOT NULL)')
        await self.control.execute("INSERT INTO public.product_api_budgets VALUES (1,'synthetic sentinel')")
        sentinel=await self.control.fetchval("SELECT to_regclass('public.product_api_budgets')::oid"),[tuple(r) for r in await self.control.fetch('SELECT * FROM public.product_api_budgets')]
        await self.bind('core, public')
        self.settings.managed_core_budget_enabled=True
        from app.services.schema_version_gate import require_connection,require_engine
        receipt=await require_engine(self.engine,self.settings)
        self.assertTrue(receipt.read_only and receipt.driver_in_transaction)
        self.assertEqual(receipt.isolation,'repeatable read')
        async with self.engine.begin() as connection:
            receipt=await require_connection(connection,self.settings)
            self.assertFalse(receipt.read_only)
            self.assertEqual(receipt.isolation,'read committed')
            raw=await connection.get_raw_connection()
            self.assertTrue(raw.driver_connection.is_in_transaction())
            self.assertEqual(await connection.scalar(self.text("SELECT current_setting('transaction_read_only')")),'off')
        # An unapplied head must refuse before even the first marker CREATE.
        self.settings.app_env='prod'
        self.assertIsNone(await self.control.fetchval("SELECT to_regclass('core.app_startup_runs')::oid"))
        saved=[tuple(r) for r in await self.control.fetch('SELECT * FROM core.core_schema_versions')]
        await self.control.execute('DELETE FROM core.core_schema_versions')
        try:
            await self.assert_no_write(self.startup)
            self.assertIsNone(await self.control.fetchval("SELECT to_regclass('core.app_startup_runs')::oid"))
        finally:
            for row in saved:
                await self.control.execute('INSERT INTO core.core_schema_versions VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)',*row)
        before=await self.budget_state()
        with self.observations() as managed:
            await self.database.create_all()
        self.assertGreater(managed['probe_count'],0)
        self.assertEqual(managed['metadata_budget_checks'],0)
        self.assertEqual(await self.budget_state(),before)
        # Real startup preparation/seed, not full lifespan/background schedulers.
        self.settings.app_env='prod'
        await self.startup()
        self.assertEqual(await self.control.fetchval('SELECT count(*) FROM core.app_startup_runs'),1)
        self.assertGreater(await self.control.fetchval('SELECT count(*) FROM core.eco_apps'),1)
        self.assertEqual(await self.budget_state(),before)
        self.settings.app_env='test'
        self.assertEqual((await self.ready())['status'],'ready')
        # Valid existing marker should still run a gate and skip preparation writes.
        self.settings.app_env='prod'
        with self.observations() as completed:
            await self.startup()
        self.assertGreater(completed['probe_count'],0)
        self.assertNotIn('alter',completed['writes'])
        marker=await self.control.fetch('SELECT * FROM core.app_startup_runs')
        # Each mutation is a real persisted bad journal/catalog, restored without a fake checker.
        for mutation,restore in [
            ("UPDATE core.core_schema_versions SET artifact_sha256=repeat('0',64)",None),
            ("UPDATE core.core_schema_versions SET revision='9999_unknown'",None),
            ('DELETE FROM core.core_schema_versions',None),
            ('ALTER TABLE core.product_api_budgets ALTER COLUMN used SET DEFAULT 1','ALTER TABLE core.product_api_budgets ALTER COLUMN used DROP DEFAULT')]:
            with self.subTest(mutation=mutation.split()[0:4]):
                old=[tuple(r) for r in await self.control.fetch('SELECT * FROM core.core_schema_versions')]
                await self.control.execute(mutation)
                await self.assert_no_write(self.startup)
                await self.assert_no_write(self.database.create_all)
                self.assertEqual(await self.control.fetch('SELECT * FROM core.app_startup_runs'),marker)
                await self.assert_ready_gate_refuses()
                if restore:
                    await self.control.execute(restore)
                else:
                    await self.control.execute('DELETE FROM core.core_schema_versions')
                    for row in old:
                        await self.control.execute('INSERT INTO core.core_schema_versions VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)',*row)
        # Missing journal, with no renamed-index collision to mask its cause.
        from schema_migrations.manifest import load
        old=[tuple(r) for r in await self.control.fetch('SELECT * FROM core.core_schema_versions')]
        await self.control.execute('DROP TABLE core.core_schema_versions')
        try:
            await self.assert_no_write(self.startup)
            await self.assert_no_write(self.database.create_all)
            await self.assert_ready_gate_refuses()
            self.assertEqual(await self.control.fetch('SELECT * FROM core.app_startup_runs'),marker)
        finally:
            await self.control.execute(load().journal_sql)
            for row in old:
                await self.control.execute('INSERT INTO core.core_schema_versions VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)',*row)
        # Managed-only config failure cannot silently discard TLS/query options.
        for field,value in [('managed_core_budget_expected_database','wrong_test'),
                ('managed_core_budget_expected_user','wrong_user'),('database_url',TARGET+'?ssl=require')]:
            with self.subTest(configuration=field):
                previous=getattr(self.settings,field)
                setattr(self.settings,field,value)
                try:
                    await self.assert_no_write(self.startup)
                    await self.assert_no_write(self.database.create_all)
                    await self.assert_ready_gate_refuses()
                finally:
                    setattr(self.settings,field,previous)
        # Explicit absent PostgreSQL port is normalized, not replaced by a hidden target.
        from app.services.schema_version_gate import _config
        from urllib.parse import urlsplit
        previous=self.settings.database_url
        self.settings.database_url=TARGET.replace(':33546','')
        self.assertEqual(urlsplit(_config(self.settings).dsn).port,5432)
        self.settings.database_url=previous
        namespace_before=await self.budget_state()
        # Valid forced-core Foundation check cannot excuse an application's public connection.
        self.assertEqual((await execute(cfg,'check'))['action'],'verified')
        await self.bind('public')
        await self.assert_no_write(self.startup)
        await self.assert_no_write(self.database.create_all)
        await self.assert_ready_gate_refuses()
        self.assertEqual((await self.control.fetchval("SELECT to_regclass('public.product_api_budgets')::oid"),[tuple(r) for r in await self.control.fetch('SELECT * FROM public.product_api_budgets')]),sentinel)
        self.assertEqual(await self.budget_state(),namespace_before)
        self.assertEqual((await self.budget_state())['product_api_budgets'],before['product_api_budgets'])
        # A valid applied row must never allow metadata to recreate a missing managed table.
        await self.bind('core, public')
        await self.control.execute('DROP TABLE core.product_api_budgets')
        await self.assert_no_write(self.startup)
        await self.assert_no_write(self.database.create_all)
        await self.assert_ready_gate_refuses()
        self.assertIsNone(await self.control.fetchval("SELECT to_regclass('core.product_api_budgets')::oid"))
        await self.size()


async def packaging_import_proof():
    # Simulate only Docker COPY layout. No docker build, pip install or outbound I/O.
    guard()
    with TemporaryDirectory(prefix='managed-image-copy-',dir=EVIDENCE) as tmp:
        target=Path(tmp)
        for name in ['app','schema_migrations']:
            shutil.copytree(SERVER/name,target/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        assert tree_digest(target/'schema_migrations')==FROZEN
        code="""import sys
from pathlib import Path
sys.path.insert(0,RUNTIME)
from app import main,database,config
from app.services import schema_version_gate
from schema_migrations.manifest import load
root=Path(RUNTIME)
for module in [main,database,config,schema_version_gate]:
    assert Path(module.__file__).is_relative_to(root)
assert config.get_settings().managed_core_budget_enabled is False
assert load().entry['id']=='0001_product_api_budgets'
print('PASS copied runtime import/defaultOFF/frozen artifacts; no lifespan or DB calls')
""".replace('RUNTIME',repr(str(target)))
        # Inherit only the already scrubbed, explicitly guarded synthetic environment.
        proc=await asyncio.create_subprocess_exec(sys.executable,'-I','-c',code,
            env=dict(os.environ),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            stdout,stderr=await asyncio.wait_for(proc.communicate(),timeout=30)
        finally:
            if proc.returncode is None:
                proc.kill();await proc.communicate()
        if proc.returncode!=0:
            (EVIDENCE/'packaging-import.log').write_bytes(stdout+stderr)
            raise RuntimeError('Copied runtime import proof failed')
        (EVIDENCE/'packaging-import.log').write_bytes(stdout+stderr)


async def preflight():
    guard()
    import asyncpg
    conn=await asyncpg.connect(RAW,timeout=5,server_settings={'search_path':'pg_catalog','statement_timeout':'5000'})
    try:
        row=dict(await conn.fetchrow("""SELECT current_database() AS db,current_user AS usr,
            current_setting('server_version_num')::int AS version,current_setting('max_locks_per_transaction')::int AS maxlocks,
            pg_database_size(current_database()) AS bytes,
            (SELECT datdba=(SELECT oid FROM pg_roles WHERE rolname=current_user) FROM pg_database WHERE datname=current_database()) AS owns,
            (SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()) AS other_clients"""))
        if row['db']!='api_managed_schema_cutover_test' or row['usr']!='clearledger' or not 160000<=row['version']<170000 or row['maxlocks']!=64 or not row['owns'] or row['other_clients']!=0 or row['bytes']>=256*1024*1024:
            raise RuntimeError('Owned cutover preflight refused')
        (EVIDENCE/'preflight.json').write_text(json.dumps(row,sort_keys=True)+'\n')
    finally: await conn.close()


if __name__=='__main__':
    if sys.argv[1:]==['--source-check']:
        source_check()
        raise SystemExit(0)
    guard()
    if sys.argv[1:]!=['--execute-approved-cutover-tests']:
        raise SystemExit('Explicit root cutover grant and approved wrapper required')
    signal.signal(signal.SIGALRM,lambda *_:sys.exit('300s cutover harness deadline exceeded'))
    signal.alarm(300)
    source_check()
    asyncio.run(preflight())
    asyncio.run(packaging_import_proof())
    started=time.monotonic()
    result=unittest.TextTestRunner(verbosity=2,failfast=True).run(unittest.defaultTestLoader.loadTestsFromTestCase(ManagedCutover))
    (EVIDENCE/'summary.json').write_text(json.dumps(dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),seconds=time.monotonic()-started),sort_keys=True)+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
