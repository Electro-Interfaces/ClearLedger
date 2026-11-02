"""Guarded, bounded actual PG16 contract tests. Requires an exclusive root SQL grant.

No pytest/conftest/application/ORM imports; no fake catalog, lock or SQL execution.
Parent fixtures are small synthetic prerequisites, not full legacy bootstrap proof.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import unittest
import uuid

SERVER = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER))
from tests.partner_test_safety import partner_test_safety_error

FLAG = 'RUN_SCHEMA_MIGRATION_RUNNER_TESTS'
TARGET = 'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_schema_migration_runner_test'
RAW = TARGET.replace('postgresql+asyncpg:', 'postgresql:', 1)
BASE = Path('/srv/projects/api-modernization-test-env-20261029')
EMPTY = BASE/'schema-migration-runner-empty-test'
UPLOAD = BASE/'schema-migration-runner-test-uploads'
EVIDENCE = BASE/'private-schema-migration-runner-20261030'
SOURCE_PINS = {
    'schema_migrations/__init__.py': 'e0fef5357ac1b25431474416a569994d118e4907d83fde1e6460bfb334dc7fea',
    'schema_migrations/catalog.py': '6460f815ecb53436981c3633769a5792642824923197f5cf15277c31f356a242',
    'schema_migrations/errors.py': 'f746049fc8579a22f3d15c0c0764dc3db30ac74754c43c2851ba75eb6045504b',
    'schema_migrations/journal.py': '16394ef23a5074c5c42c7780b30e15389c5eb4e6b03fb79a0afc1539db18fe39',
    'schema_migrations/manifest.json': 'ef4189a61f162c81dda01b6602eae3a362c242e95ee954c6c971db9ff6404116',
    'schema_migrations/manifest.py': '55e5d7caca47c6bbd243f1e02e9e8a764b163067b16cd8eb41052967e4c78a09',
    'schema_migrations/revisions/0001_contract.json': '19450cd978b88df859aa6f4d33ad745f48fb4f0b55a17850aa875e75b66a0194',
    'schema_migrations/revisions/0001_product_api_budgets.sql': '98da0597f9e4d6a3d21326a310496b790753a5d9e766cfec8005d84641dd2ac9',
    'schema_migrations/revisions/__init__.py': '1a89417e8d0ed0684ad1055568dacea57b108b38b20ba76470871e5faad2c146',
    'schema_migrations/revisions/catalog_v1.py': 'ae3c42d51a7e7e37ee293b2c64f73addd421cf792b63af6bed6c36b1ed5f24f5',
    'schema_migrations/revisions/journal_v1.sql': 'c872f3746c0df17c03bb6c87db8b8bebd22713bc326fca83b43e3aa9f8dfed5a',
    'schema_migrations/runner.py': '375a6f68ca9024895e463584b7f79201b48500ab527d9cdcab16fdc0b2f41504',
    'schema_migrations/tests/__init__.py': 'b75801b2fdeac6f92ffe4796227b1c5ea85419d8f938040221e6e3924b492db5',
    'schema_migrations/tests/test_pure.py': '635291c1e14b3c6a18ab8371a53d7e7ff63be48e51f0b1cd1b5d2e16bb8722fc',
    'tests/partner_test_safety.py': '43de791a8f0b418f03d4cdc155c2d8cc2d923757134f88b91870a539609eafb1',
}


def guard():
    error = partner_test_safety_error(os.environ, flag=FLAG)
    if error:
        raise RuntimeError('Refusing schema runner tests: '+error)
    if (any(os.environ.get(key) != TARGET for key in ['TEST_DATABASE_URL','DATABASE_URL'])
            or os.environ.get('SCHEMA_MIGRATION_TEST_DSN') != RAW
            or os.environ.get('APP_ENV') != 'test' or os.environ.get('UPLOAD_DIR') != str(UPLOAD)
            or Path.cwd() != EMPTY or any(EMPTY.iterdir()) or sys.version_info[:3] != (3,13,7)
            or not EVIDENCE.is_dir() or EVIDENCE.stat().st_mode & 0o077):
        raise RuntimeError('Refusing schema runner tests: exact owned targets/flags/dirs/Python required')
    if any(hashlib.sha256((SERVER/name).read_bytes()).hexdigest()!=digest for name,digest in SOURCE_PINS.items()):
        raise RuntimeError('Refusing schema runner tests: source pin mismatch')
    from schema_migrations.tests.approved_postgres import verify_approval
    verify_approval()
    manifest.load()


# Importing the harness does not connect; direct execution always guards first.
from schema_migrations import manifest, runner
from schema_migrations.errors import MigrationError

ID1 = uuid.UUID('00000000-0000-4000-8000-000000000001')
ID2 = uuid.UUID('00000000-0000-4000-8000-000000000002')
COMPANY = uuid.UUID('00000000-0000-4000-8000-000000000003')


def config(**overrides):
    return runner.Config(RAW,'api_schema_migration_runner_test','clearledger','core',**overrides)


class ActualFoundation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        guard()
        import asyncpg
        self.conn = await asyncpg.connect(RAW, timeout=5, command_timeout=5,
            server_settings={'search_path':'pg_catalog','statement_timeout':'5000','lock_timeout':'1000'})
        self.addAsyncCleanup(self.conn.close)
        existing = await self.conn.fetch("""SELECT n.nspname,c.relname FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
            AND n.nspname NOT LIKE 'pg_temp%' AND c.relkind IN ('r','p','v','m','S','f')""")
        self.assertEqual(existing, [], 'Own test database must be fresh after previous cleanup')
        self.addAsyncCleanup(self.cleanup)
        await self.conn.execute('CREATE SCHEMA core')
        await self.conn.execute('''CREATE TABLE core.partner_installations (
            id uuid PRIMARY KEY, client_id varchar(64) NOT NULL, company_id uuid NOT NULL,
            CONSTRAINT uq_partner_install_client_company UNIQUE(id,client_id,company_id))''')
        await self.conn.execute('INSERT INTO core.partner_installations VALUES ($1,$2,$3),($4,$5,$3)',
            ID1,'synthetic-a',COMPANY,ID2,'synthetic-b')

    async def cleanup(self):
        # Only the explicitly owned fixture names, no CASCADE, FORCE or other DBs.
        for schema,name in [('core','product_api_budgets'),('core','core_schema_versions'),
                ('core','partner_installations'),('public','partner_installations')]:
            kind = await self.conn.fetchval('''SELECT c.relkind::text FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=$1 AND c.relname=$2''', schema,name)
            if kind is not None:
                self.assertIn(kind, ['r','v','m'])
                noun={'r':'TABLE','v':'VIEW','m':'MATERIALIZED VIEW'}[kind]
                await self.conn.execute(f'DROP {noun} {schema}.{name}')
        await self.conn.execute('DROP SCHEMA core')
        other = await self.conn.fetchval("""SELECT count(*) FROM pg_catalog.pg_stat_activity
            WHERE backend_type='client backend' AND pid<>pg_catalog.pg_backend_pid()""")
        self.assertEqual(other,0,'All runner/blocker/child connections must close before cleanup completes')

    async def exists(self,name):
        return await self.conn.fetchval('SELECT pg_catalog.to_regclass($1)::oid', 'core.'+name)

    async def snapshot(self):
        result={}
        for name in ['partner_installations','product_api_budgets','core_schema_versions']:
            oid=await self.exists(name)
            if oid is not None:
                rows=await self.conn.fetch(f'SELECT xmin::text AS tuple_xmin,ctid::text AS tuple_ctid,* FROM core.{name} ORDER BY 1,2')
                result[name]=(oid,[tuple(row) for row in rows])
        return result

    async def reject(self,code,mode='apply'):
        before=await self.snapshot()
        with self.assertRaises(MigrationError) as err:
            await runner.execute(config(),mode)
        self.assertEqual(err.exception.code,code)
        self.assertEqual(await self.snapshot(),before)

    async def populate_budget(self):
        await self.conn.execute("""INSERT INTO core.product_api_budgets
            VALUES ($1,$2,'synthetic-a',1,'2026-10-30T12:00:00+00',10,60),
                   ($1,$3,'synthetic-b',2,'2026-10-30T12:01:00+00',10,60)""",COMPANY,ID1,ID2)

    async def test_01_create_repeat_readonly_check_and_populated_rows(self):
        self.assertIsNone(await self.exists('product_api_budgets'))
        self.assertEqual((await runner.execute(config(),'apply'))['action'],'created')
        await self.populate_budget()
        before=await self.snapshot()
        self.assertEqual((await runner.execute(config(),'apply'))['action'],'verified')
        self.assertEqual((await runner.execute(config(),'check'))['action'],'verified')
        self.assertEqual(await self.snapshot(),before)

    async def test_02_exact_adoption_keeps_oid_rows_and_repeat(self):
        await self.conn.execute(manifest.load().sql)
        await self.populate_budget()
        before=await self.snapshot()
        self.assertEqual((await runner.execute(config(),'apply'))['action'],'adopted')
        after=await self.snapshot()
        for name,value in before.items(): self.assertEqual(after[name],value)
        self.assertEqual(await self.conn.fetchval('SELECT action FROM core.core_schema_versions'),'adopted')
        self.assertEqual((await runner.execute(config(),'apply'))['action'],'verified')
        self.assertEqual(await self.snapshot(),after)

    async def test_03_readonly_check_unapplied_never_creates_journal(self):
        await self.reject(4,'check')
        self.assertIsNone(await self.exists('core_schema_versions'))
        self.assertIsNone(await self.exists('product_api_budgets'))

    async def test_04_missing_prerequisite_and_wrong_namespace_refuse(self):
        await self.conn.execute('DROP TABLE core.partner_installations')
        await self.reject(4)
        with self.assertRaises(MigrationError) as err:
            await runner.execute(runner.Config(RAW,config().database,'clearledger','public'),'apply')
        self.assertEqual(err.exception.code,3)
        self.assertIsNone(await self.exists('core_schema_versions'))

    async def test_05_malformed_budget_columns_checks_and_index_refuse(self):
        alterations=[
            'ALTER TABLE core.product_api_budgets ALTER COLUMN used TYPE bigint',
            'ALTER TABLE core.product_api_budgets ALTER COLUMN used DROP NOT NULL',
            'ALTER TABLE core.product_api_budgets ALTER COLUMN used SET DEFAULT 1',
            'ALTER TABLE core.product_api_budgets DROP CONSTRAINT ck_product_budget_used',
            'ALTER TABLE core.product_api_budgets ADD COLUMN unexpected integer',
            'DROP INDEX core.ix_product_api_budgets_reset',
            'CREATE INDEX unexpected ON core.product_api_budgets(used)',
        ]
        for sql in alterations:
            with self.subTest(alteration=sql.split()[0:4]):
                await self.conn.execute(manifest.load().sql)
                await self.conn.execute(sql)
                await self.reject(4)
                self.assertIsNone(await self.exists('core_schema_versions'))
                await self.conn.execute('DROP TABLE core.product_api_budgets')

    async def test_06_public_fk_shadow_rejected_by_oid(self):
        await self.conn.execute('''CREATE TABLE public.partner_installations
            (id uuid PRIMARY KEY,client_id varchar(64) NOT NULL,company_id uuid NOT NULL,
            UNIQUE(id,client_id,company_id))''')
        await self.conn.execute('INSERT INTO public.partner_installations SELECT * FROM core.partner_installations')
        # Deliberately wrong persisted fixture FK, not substituted runner SQL/catalog.
        sql=manifest.load().sql.replace('REFERENCES core.partner_installations','REFERENCES public.partner_installations')
        await self.conn.execute(sql)
        sentinel=await self.conn.fetch('SELECT * FROM public.partner_installations ORDER BY id')
        await self.reject(4)
        self.assertEqual(await self.conn.fetch('SELECT * FROM public.partner_installations ORDER BY id'),sentinel)
        self.assertIsNone(await self.exists('core_schema_versions'))

    async def test_07_wrong_journal_contract_and_action_literals_refuse(self):
        await self.conn.execute(manifest.load().sql)
        for literal in ['CREATED','cre ated']:
            with self.subTest(literal=literal):
                sql=manifest.load().journal_sql.replace("'created'", "'"+literal+"'")
                await self.conn.execute(sql)
                await self.reject(4)
                self.assertEqual(await self.conn.fetchval('SELECT count(*) FROM core.core_schema_versions'),0)
                await self.conn.execute('DROP TABLE core.core_schema_versions')
        await self.conn.execute('CREATE TABLE core.core_schema_versions (revision text PRIMARY KEY)')
        # snapshot works for arbitrary table shape; refusal must precede journal insertion.
        await self.reject(4)

    async def test_08_applied_history_corruption_unknown_head_and_gap_refuse(self):
        for field,value in [('artifact_sha256','0'*64),('contract_sha256','1'*64),
                ('revision','9999_unknown'),('ordinal',2),('parent_revision','unknown'),('second_row',None)]:
            with self.subTest(field=field):
                await runner.execute(config(),'apply')
                if field == 'second_row':
                    await self.conn.execute("""INSERT INTO core.core_schema_versions
                        SELECT '0002_unknown',2,revision,artifact_sha256,contract_sha256,
                            artifact_sha256,'created',now(),applied_by,app_commit,runner_format
                        FROM core.core_schema_versions""")
                else:
                    await self.conn.execute(f'UPDATE core.core_schema_versions SET {field}=$1',value)
                await self.reject(4)
                await self.reject(4,'check')
                await self.conn.execute('DROP TABLE core.core_schema_versions,core.product_api_budgets')

    async def test_09_failure_after_journal_create_rolls_back_whole_revision(self):
        import asyncpg
        before=await self.snapshot()
        blocker=await asyncpg.connect(RAW,timeout=5)
        try:
            async with blocker.transaction():
                # Real PostgreSQL lock contention, not an injected fake verifier/SQL result.
                await blocker.execute('LOCK TABLE core.partner_installations IN ACCESS EXCLUSIVE MODE')
                with self.assertRaises(MigrationError) as err:
                    await runner.execute(config(),'apply')
                self.assertEqual(err.exception.code,6)
                self.assertIsNone(await self.exists('core_schema_versions'))
                self.assertIsNone(await self.exists('product_api_budgets'))
        finally:
            await blocker.close()
        # Reading parent data while its blocker holds ACCESS EXCLUSIVE would self-wait.
        self.assertEqual(await self.snapshot(),before)

    async def test_10_two_actual_runners_serialize_and_recheck_head(self):
        async with asyncio.TaskGroup() as group:
            tasks=[group.create_task(runner.execute(config(),'apply')) for _ in range(2)]
        results=[task.result() for task in tasks]
        self.assertEqual(sorted(value['action'] for value in results),['created','verified'])
        self.assertEqual(await self.conn.fetchval('SELECT count(*) FROM core.core_schema_versions'),1)

    async def test_11_legacy_xact_lock_conflicts_and_check_does_not_lock(self):
        import asyncpg
        blocker=await asyncpg.connect(RAW,timeout=5)
        try:
            async with blocker.transaction():
                await blocker.fetchval('SELECT pg_advisory_xact_lock($1::int,$2::int)',*runner.LOCK)
                before=await self.snapshot()
                with self.assertRaises(MigrationError) as err:
                    await runner.execute(config(lock_seconds=0.1),'apply')
                self.assertEqual(err.exception.code,5)
                self.assertEqual(await self.snapshot(),before)
            await runner.execute(config(),'apply')
            async with blocker.transaction():
                await blocker.fetchval('SELECT pg_advisory_xact_lock($1::int,$2::int)',*runner.LOCK)
                # check is read-only and must succeed while the separate owner lock is held.
                self.assertEqual((await runner.execute(config(lock_seconds=0.1),'check'))['action'],'verified')
        finally:
            await blocker.close()

    async def test_12_actual_cli_apply_and_check_no_secret_output(self):
        child_env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8',
            'HOME':os.environ['HOME'],'SCHEMA_MIGRATION_TEST_DSN':RAW}
        for mode in ['apply','check']:
            proc=await asyncio.create_subprocess_exec(sys.executable,'-I',str(SERVER/'schema_migrations/runner.py'),mode,
                '--dsn-env','SCHEMA_MIGRATION_TEST_DSN','--database',config().database,'--user','clearledger','--namespace','core',
                env=child_env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            try:
                stdout,stderr=await asyncio.wait_for(proc.communicate(),timeout=25)
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.communicate()
            self.assertEqual(proc.returncode,0,stdout)
            self.assertEqual(stderr,b'')
            self.assertNotIn(b'api_test_only',stdout+stderr)
            self.assertTrue(json.loads(stdout)['ok'])

    async def test_13_disabled_internal_fk_triggers_refuse_before_journal(self):
        # PostgreSQL requires pre-provisioned superuser rights for disabling internal
        # triggers. Never create/alter a role or try a privilege escalation here.
        if not await self.conn.fetchval('SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user'):
            self.skipTest('DISABLE internal FK triggers requires pre-provisioned synthetic role privilege')
        await self.conn.execute(manifest.load().sql)
        await self.conn.execute('ALTER TABLE core.product_api_budgets DISABLE TRIGGER ALL')
        await self.reject(4)
        self.assertIsNone(await self.exists('core_schema_versions'))


async def preflight():
    guard()
    import asyncpg
    conn=await asyncpg.connect(RAW,timeout=5,server_settings={'search_path':'pg_catalog','statement_timeout':'5000'})
    try:
        row=dict(await conn.fetchrow("""SELECT current_database() AS db,current_user AS usr,
            current_setting('server_version_num')::int AS version,current_setting('max_locks_per_transaction')::int AS maxlocks,
            pg_database_size(current_database()) AS bytes,
            (SELECT datdba=(SELECT oid FROM pg_roles WHERE rolname=current_user)
             FROM pg_database WHERE datname=current_database()) AS owns,
            (SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend'
                AND pid<>pg_backend_pid()) AS other_clients"""))
        if (row['db']!=config().database or row['usr']!='clearledger' or not row['owns']
                or not 160000<=row['version']<170000 or row['maxlocks']!=64
                or row['other_clients']!=0 or row['bytes']>=64*1024*1024):
            raise RuntimeError('Synthetic preflight refused')
        (EVIDENCE/'preflight.json').write_text(json.dumps(row,sort_keys=True)+'\n')
    finally:
        await conn.close()


if __name__=='__main__':
    guard()
    if sys.argv[1:]!=['--execute-approved-contract-tests']:
        raise SystemExit('Explicit root SQL grant and exact runner argument required')
    signal.signal(signal.SIGALRM,lambda *_:sys.exit('120s harness deadline exceeded'))
    signal.alarm(120)
    manifest.load()  # Pinned artifact integrity before the first driver import/connect.
    asyncio.run(preflight())
    started=time.monotonic()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ActualFoundation)
    result=unittest.TextTestRunner(verbosity=2,failfast=True).run(suite)
    summary=dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        skips=len(result.skipped),seconds=time.monotonic()-started,source_only=False)
    (EVIDENCE/'summary.json').write_text(json.dumps(summary,sort_keys=True)+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
