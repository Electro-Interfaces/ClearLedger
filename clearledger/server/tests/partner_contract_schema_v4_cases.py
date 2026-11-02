"""Написаны, NOT RUN: PG16 cases только ROOT, без pytest/conftest entrypoint.

ROOT предоставляет проверенный disposable native world и замораживает новый
execution envelope. Текущий fixed helper отказывает этим новым source bytes;
здесь он не меняется. При импорте нет connections/provisioning/application
imports/очистки fixtures. SQL ниже предназначен только для синтетики.
"""
import asyncio
from contextlib import asynccontextmanager
import os
from urllib.parse import unquote, urlsplit
import uuid
from unittest.mock import patch

TARGET = 'api_partner_contract_schema_v4_test_20261101'
EXACT_DSN = 'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/' + TARGET
REVISION = '0004_partner_contract_create'
PROFILE = uuid.UUID('c4000000-0000-4000-8000-000000000041')
INTENT = uuid.UUID('c4000000-0000-4000-8000-000000000042')
KEY = uuid.UUID('c4000000-0000-4000-8000-000000000043')
CASE_REQUIREMENTS = {
    'fresh-continuation-repeat': 'native parents, prefix0/1/2/3 (separate worlds)',
    'old-prefix-required': 'native parents, prefix1/2/3/4 (separate worlds)',
    'occupied-no-adopt': 'prefix3; occupied/partial/exact-unrecorded4 variants',
    'catalogue-drift': 'prefix4; isolated drift variants',
    'prerequisite-drift': 'prefix3; isolated native header/type/key variants',
    'history-drift': 'prefix4; unknown future/foreign/adopted history variants',
    'rollback-cancel': 'native parents prefix0/3; fault after real revision4 DDL',
    'unknown-commit': 'native parents prefix3; real commit then lost acknowledgement',
    'principal-xor-typed-ref-unique': 'prefix4 and isolated native world',
    'success-namespace-immutable': 'prefix4 and isolated native world',
    'current-fk-tombstones': 'prefix4 and safe-to-delete native world',
    'approval-ref-deletes': 'prefix4 and safe-to-delete native world',
    'parent-history-retention': 'prefix4 and safe-to-delete native world',
}


def admit(config):
    """Точный DSN проверяется ДО project/ORM/helper imports, без redirects."""
    raw = os.environ.get('TEST_DATABASE_URL')
    if raw != EXACT_DSN or os.environ.get('DATABASE_URL') != raw:
        raise RuntimeError('ROOT exact disposable target required')
    parsed = urlsplit(raw)
    if (parsed.scheme, parsed.hostname, parsed.port, unquote(parsed.path), parsed.query, parsed.fragment,
        parsed.username, parsed.password) != ('postgresql+asyncpg', '127.0.0.1', 33546, '/' + TARGET, '', '', 'clearledger', 'api_test_only'):
        raise RuntimeError('ROOT exact disposable target required')
    # Новый native profile требует независимый private contract ROOT.
    # До него нет project/ORM/driver/fixture imports или соединений.
    from tests.partner_contract_schema_v4_approval import require_running_approval
    require_running_approval()
    config.validate()
    expected = EXACT_DSN.replace('postgresql+asyncpg:', 'postgresql:', 1)
    if config.dsn != expected or (config.database, config.user, config.namespace) != (TARGET, 'clearledger', 'core'):
        raise RuntimeError('ROOT connection config mismatch')


async def identity(conn):
    result = await conn.fetchrow("SELECT current_database() AS db,current_user AS usr,current_schema() AS ns,current_setting('server_version_num')::int AS version")
    assert (result['db'], result['usr'], result['ns']) == (TARGET, 'clearledger', 'core')
    assert 160000 <= result['version'] < 170000


@asynccontextmanager
async def rejected_sql(conn, state):
    """Настоящий отказ PG в savepoint: посторонние exceptions не дают PASS."""
    import asyncpg
    transaction = conn.transaction()
    await transaction.start()
    try:
        yield
    except asyncpg.PostgresError as error:
        assert error.sqlstate == state, (error.sqlstate, state)
        await transaction.rollback()
    else:
        await transaction.rollback()
        raise AssertionError('expected PostgreSQL rejection')


async def snapshot(conn):
    relations = await conn.fetch("""SELECT c.relname,c.relkind::text,c.oid FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='core'
        AND (c.relname LIKE 'partner_contract_%' OR c.relname IN ('core_schema_versions','product_api_budgets','pulse_view_role_grants'))
        ORDER BY c.relname""")
    exists = await conn.fetchval("SELECT to_regclass('core.core_schema_versions') IS NOT NULL")
    history = await conn.fetch('SELECT row_to_json(v)::text AS value FROM core.core_schema_versions v ORDER BY ordinal') if exists else []
    return ([dict(r) for r in relations], [dict(r) for r in history])


async def profile(conn, w):
    # w — реальная native fixture ROOT, не проекция десяти таблиц Base.metadata.
    await conn.execute('''INSERT INTO core.partner_contract_create_profiles
        (id,installation_id,client_id,company_id,user_enabled,service_enabled)
        VALUES ($1,$2,$3,$4,true,true)''', PROFILE, w['installation'], w['client'], w['company'])


async def intent(conn, w, *, user=True, intent_id=INTENT, key=KEY):
    await conn.execute('''INSERT INTO core.partner_contract_success_intents
        (id,company_id,app_id,installation_id,original_grant_id,create_profile_id,client_id,
         operation,creation_key,actor_kind,actor_key,current_user_id,newborn_id,current_contract_id,
         request_hash,created_organization_id,created_counterparty_id,created_type_code)
        VALUES ($1,$2,$3,$4,$5,$6,$7,'createContract',$8,$9,$10,$11,$12,$12,$13,$14,$15,$16)''',
        intent_id,w['company'],w['app'],w['installation'],w['grant'],PROFILE,w['client'],key,
        'user' if user else 'machine',str(w['user']) if user else w['client'],w['user'] if user else None,
        w['contract'],'a'*64,w['organization'],w['counterparty'],w['type_code'])
    await conn.execute('INSERT INTO core.partner_contract_intent_locations VALUES ($1,$2)', intent_id, w['location'])


class TraceConnection:
    """Узкий прозрачный fault injector поверх настоящего asyncpg connection."""
    def __init__(self, conn, trace, lose_commit=False):
        self.conn,self.trace,self.lose_commit = conn,trace,lose_commit

    def __getattr__(self, name):
        return getattr(self.conn, name)

    @asynccontextmanager
    async def transaction(self, **kwargs):
        writing = not kwargs.get('readonly', False)
        self.trace.append(('transaction', writing))
        async with self.conn.transaction(**kwargs):
            yield
        if writing and self.lose_commit:
            raise ConnectionResetError('synthetic acknowledgement lost AFTER real COMMIT')

    async def execute(self, sql, *args, **kwargs):
        if sql.lstrip().startswith(('CREATE TABLE', '-- Revision0004', 'INSERT INTO core.core_schema_versions')):
            self.trace.append(('write', self.conn.get_server_pid(), await self.conn.fetchval('SELECT pg_current_xact_id()::text')))
        return await self.conn.execute(sql, *args, **kwargs)


async def fresh_continuation_repeat(conn, config, prefix):
    admit(config)
    await identity(conn)
    from schema_migrations import manifest, runner
    import asyncpg
    assert prefix in (0,1,2,3)
    before = await snapshot(conn)
    real_connect, trace, opened = asyncpg.connect, [], []

    async def connect(*args, **kwargs):
        actual = await real_connect(*args, **kwargs)
        opened.append(actual)
        return TraceConnection(actual, trace)

    with patch.object(asyncpg, 'connect', connect):
        receipt = await runner.execute(config, 'apply', revision=REVISION, legacy_sent_before=2000000000)
    assert len(opened) == 1 and opened[0].is_closed()
    assert trace.count(('transaction', True)) == 1
    writes = [event for event in trace if event[0] == 'write']
    assert writes and len({event[1:] for event in writes}) == 1, 'all ancestors and4 must share backend/top-level transaction'
    assert receipt['revision'] == REVISION and receipt['prefix_before'] == prefix
    assert [a['revision'] for a in receipt['actions']] == [runner._packages(manifest.load_known_head())[i].entry['id'] for i in range(prefix+1,5)]
    assert (await runner.execute(config, 'check', revision=REVISION))['action'] == 'verified'
    after = await snapshot(conn)
    repeat = await runner.execute_sequence(config, target_revision=REVISION, legacy_sent_before=2000000000)
    assert repeat['actions'] == [] and await snapshot(conn) == after and before != after


async def old_prefix_required(conn, config, prefix):
    admit(config)
    await identity(conn)
    from schema_migrations import manifest, runner
    from schema_migrations.errors import MigrationError
    head = manifest.load_known_head()
    for ordinal, package in runner._packages(head).items():
        if ordinal <= prefix:
            await runner.require_applied_prefix(conn, config, head, required_revision=package.entry['id'])
        else:
            try:
                await runner.require_applied_prefix(conn, config, head, required_revision=package.entry['id'])
            except MigrationError as error:
                assert (error.code,error.phase) == (4,'unapplied')
            else:
                raise AssertionError('required successor accepted without history')
    if prefix == 3:
        before = await snapshot(conn)
        receipt = await runner.execute_sequence(config,target_revision=manifest.PULSE_ID,legacy_sent_before=2000000000)
        assert receipt['revision'] == manifest.PULSE_ID and receipt['actions'] == []
        assert await snapshot(conn) == before, 'explicit3 must never execute4'


async def occupied_no_adopt(conn, config, variant):
    admit(config)
    await identity(conn)
    from schema_migrations import manifest, runner
    from schema_migrations.errors import MigrationError
    sql = {'partial': 'CREATE TABLE core.partner_contract_create_profiles (unexpected integer)',
           'index-name': 'CREATE TABLE core.ix_pc_success_profile (unexpected integer)',
           'type-name': 'CREATE TYPE core.partner_contract_create_types AS (unexpected integer)',
           'array-name': 'CREATE TYPE core._partner_contract_create_types AS (unexpected integer)',
           'function-name': "CREATE FUNCTION core.pc_contract_success_immutable(integer) RETURNS integer LANGUAGE sql AS 'SELECT $1'",
           'exact-unrecorded': manifest.load_known_head().sql}[variant]
    await conn.execute(sql)
    before = await snapshot(conn)
    try:
        await runner.execute(config,'apply',revision=REVISION,legacy_sent_before=2000000000)
    except MigrationError as error:
        assert error.code == 4 and error.phase in ('pc_unrecorded_occupancy','pc_relation')
    else:
        raise AssertionError('occupied revision4 adopted')
    assert await snapshot(conn) == before


DRIFTS = {
    'default': "ALTER TABLE core.partner_contract_create_profiles ALTER COLUMN user_enabled SET DEFAULT true",
    'null': "ALTER TABLE core.partner_contract_success_intents ALTER COLUMN actor_key DROP NOT NULL",
    'check': "ALTER TABLE core.partner_contract_success_intents DROP CONSTRAINT ck_pc_intent_actor",
    'fk': "ALTER TABLE core.partner_contract_success_intents DROP CONSTRAINT fk_pc_intent_user",
    'index': "DROP INDEX core.ix_pc_success_profile",
    'predicate': "DROP INDEX core.ix_pc_success_principal_contract; CREATE INDEX ix_pc_success_principal_contract ON core.partner_contract_success_intents (company_id,installation_id,app_id,client_id,original_grant_id,actor_kind,actor_key,current_contract_id)",
    'trigger': "ALTER TABLE core.partner_contract_success_intents DISABLE TRIGGER tr_pc_success_immutable",
    'function-path': "ALTER FUNCTION core.pc_contract_success_immutable() SET search_path=public",
    'function-security': "ALTER FUNCTION core.pc_contract_success_immutable() SECURITY DEFINER",
    'acl': "GRANT SELECT ON core.partner_contract_success_intents TO PUBLIC",
    'rls': "ALTER TABLE core.partner_contract_create_refs ENABLE ROW LEVEL SECURITY",
    'options': "ALTER TABLE core.partner_contract_create_refs SET (fillfactor=80)",
    'column': "ALTER TABLE core.partner_contract_success_intents ADD COLUMN unexpected integer",
    'column-type': "ALTER TABLE core.partner_contract_success_intents ALTER COLUMN actor_key TYPE varchar(63)",
    'unknown-check': "ALTER TABLE core.partner_contract_success_intents ADD CONSTRAINT synthetic_unknown CHECK (true)",
    'check-inheritance': "ALTER TABLE core.partner_contract_create_profiles DROP CONSTRAINT ck_pc_profile_generation; ALTER TABLE core.partner_contract_create_profiles ADD CONSTRAINT ck_pc_profile_generation CHECK (policy_generation > 0) NO INHERIT",
    'fk-action': "ALTER TABLE core.partner_contract_success_intents DROP CONSTRAINT fk_pc_intent_user; ALTER TABLE core.partner_contract_success_intents ADD CONSTRAINT fk_pc_intent_user FOREIGN KEY (current_user_id) REFERENCES core.users(id) ON DELETE CASCADE",
    'extra-index': "CREATE INDEX synthetic_pc_extra ON core.partner_contract_success_intents (newborn_id)",
    'function-acl': "GRANT EXECUTE ON FUNCTION core.pc_contract_success_immutable() TO PUBLIC",
    'function-overload': "CREATE FUNCTION core.pc_contract_success_immutable(integer) RETURNS integer LANGUAGE sql AS 'SELECT $1'",
    'extra-trigger': "CREATE TRIGGER synthetic_pc_extra BEFORE UPDATE ON core.partner_contract_success_intents FOR EACH ROW EXECUTE FUNCTION core.pc_contract_success_immutable()",
    'foreign-namespace': "ALTER TABLE core.partner_contract_create_types SET SCHEMA public",
}


async def catalogue_drift(conn, config, variant):
    admit(config)
    await identity(conn)
    from schema_migrations import runner
    from schema_migrations.errors import MigrationError
    await conn.execute(DRIFTS[variant])
    before = await snapshot(conn)
    for mode in ('check','apply'):
        try:
            await runner.execute(config,mode,revision=REVISION,legacy_sent_before=2000000000 if mode=='apply' else None)
        except MigrationError as error:
            assert error.code == 4, (error.code,error.phase)
        else:
            raise AssertionError('catalogue drift was accepted/repaired')
    assert await snapshot(conn) == before


async def prerequisite_drift(conn, config, variant):
    admit(config)
    await identity(conn)
    from schema_migrations import runner
    from schema_migrations.errors import MigrationError
    sql = {
        'missing': 'ALTER TABLE core.contract_types RENAME TO synthetic_contract_types_missing',
        'null': 'ALTER TABLE core.organizations ALTER COLUMN company_id DROP NOT NULL',
        'type': 'ALTER TABLE core.contract_types ALTER COLUMN is_active DROP DEFAULT; ALTER TABLE core.contract_types ALTER COLUMN is_active TYPE text USING is_active::text',
        'key': 'ALTER TABLE core.partner_installations DROP CONSTRAINT uq_partner_install_client_company CASCADE',
    }[variant]
    await conn.execute(sql)
    before = await snapshot(conn)
    try:
        await runner.execute(config,'apply',revision=REVISION,legacy_sent_before=2000000000)
    except MigrationError as error:
        assert error.code == 4 and error.phase in ('pc_prerequisite','columns','pc_prerequisite_key')
    else:
        raise AssertionError('invalid real native prerequisite accepted')
    assert await snapshot(conn) == before


async def history_drift(conn, config, variant):
    admit(config)
    await identity(conn)
    from schema_migrations import manifest,runner
    from schema_migrations.errors import MigrationError
    if variant == 'future':
        await conn.execute('''INSERT INTO core.core_schema_versions
            (revision,ordinal,parent_revision,artifact_sha256,contract_sha256,predecessor_sha256,
             action,applied_by,app_commit,runner_format)
            SELECT '0005_unknown_future',5,revision,artifact_sha256,contract_sha256,artifact_sha256,
                'created',applied_by,app_commit,runner_format FROM core.core_schema_versions WHERE ordinal=4''')
    else:
        column,value = {'foreign-owner':('applied_by','foreign'), 'adopted4':('action','adopted'),
                        'foreign4':('revision','0004_foreign')}[variant]
        await conn.execute('UPDATE core.core_schema_versions SET '+column+'=$1 WHERE ordinal=4',value)
    before = await snapshot(conn)
    try:
        await runner.require_applied_prefix(conn,config,manifest.load_known_head(),required_revision=manifest.ID)
    except MigrationError as error:
        assert error.code == 4 and error.phase in ('history','parent_history')
    else:
        raise AssertionError('foreign/future/adopted0004 history accepted by older required gate')
    assert await snapshot(conn) == before


async def rollback_cancel(conn, config, cancel):
    admit(config)
    await identity(conn)
    from schema_migrations import runner
    from schema_migrations.errors import MigrationError
    before = await snapshot(conn)
    original = runner.catalog.inspect_contract_create

    async def after_real_ddl(*args, **kwargs):
        result = await original(*args, **kwargs)
        if kwargs['applied']:
            raise asyncio.CancelledError() if cancel else RuntimeError('synthetic known pre-COMMIT fault')
        return result

    with patch.object(runner.catalog,'inspect_contract_create',after_real_ddl):
        try:
            await runner.execute(config,'apply',revision=REVISION,legacy_sent_before=2000000000)
        except asyncio.CancelledError:
            assert cancel
        except MigrationError as error:
            assert not cancel and (error.code,error.phase) == (6,'database')
        else:
            raise AssertionError('fault did not interrupt owner')
    assert await snapshot(conn) == before, 'all real ancestor and4 DDL/history must roll back'


async def unknown_commit(conn, config):
    admit(config)
    await identity(conn)
    from schema_migrations import runner
    from schema_migrations.errors import MigrationError
    import asyncpg
    actual_connect,trace,opened = asyncpg.connect,[],[]

    async def connect(*args,**kwargs):
        actual = await actual_connect(*args,**kwargs)
        opened.append(actual)
        return TraceConnection(actual,trace,lose_commit=True)

    with patch.object(asyncpg,'connect',connect):
        try:
            await runner.execute(config,'apply',revision=REVISION,legacy_sent_before=2000000000)
        except MigrationError as error:
            assert (error.code,error.phase) == (6,'database')
        else:
            raise AssertionError('lost acknowledgement must not claim confirmed success')
    assert len(opened) == 1 and opened[0].is_closed(), 'no implicit retry'
    assert (await runner.execute(config,'check',revision=REVISION))['action'] == 'verified'
    before = await snapshot(conn)
    receipt = await runner.execute(config,'apply',revision=REVISION,legacy_sent_before=2000000000)
    assert receipt['actions'] == [] and await snapshot(conn) == before


async def principal_typed_refs_unique(conn, config, w):
    admit(config)
    await identity(conn)
    async with conn.transaction():
        async with rejected_sql(conn,'23503'):
            await conn.execute('''INSERT INTO core.partner_contract_create_profiles
                (id,installation_id,client_id,company_id) VALUES ($1,$2,$3,$4)''',
                PROFILE,w['installation'],w['client'],uuid.uuid4())
        await profile(conn,w)
        defaults = await conn.fetchrow('SELECT revoked,policy_generation FROM core.partner_contract_create_profiles WHERE id=$1',PROFILE)
        assert defaults['revoked'] is False and defaults['policy_generation'] == 1
        async with rejected_sql(conn,'23514'):
            await conn.execute('UPDATE core.partner_contract_create_profiles SET policy_generation=0 WHERE id=$1',PROFILE)
        for kind,user,grant in [('user',w['user'],None),('machine',None,w['grant'])]:
            await conn.execute('INSERT INTO core.partner_contract_create_principals VALUES ($1,$2,$3,$4,$5)',uuid.uuid4(),PROFILE,kind,user,grant)
            async with rejected_sql(conn,'23505'):
                await conn.execute('INSERT INTO core.partner_contract_create_principals VALUES ($1,$2,$3,$4,$5)',uuid.uuid4(),PROFILE,kind,user,grant)
        for kind,user,grant in [('machine',w['user'],w['grant']),('user',None,None),('user',None,w['grant']),('service',None,w['grant'])]:
            async with rejected_sql(conn,'23514'):
                await conn.execute('INSERT INTO core.partner_contract_create_principals VALUES ($1,$2,$3,$4,$5)',uuid.uuid4(),PROFILE,kind,user,grant)
        for kind,org,cp,location in [('organization',w['organization'],None,None),('counterparty',None,w['counterparty'],None),('location',None,None,w['location'])]:
            await conn.execute('INSERT INTO core.partner_contract_create_refs VALUES ($1,$2,$3,$4,$5,$6)',uuid.uuid4(),PROFILE,kind,org,cp,location)
            async with rejected_sql(conn,'23505'):
                await conn.execute('INSERT INTO core.partner_contract_create_refs VALUES ($1,$2,$3,$4,$5,$6)',uuid.uuid4(),PROFILE,kind,org,cp,location)
        for kind,org,cp,location in [('organization',None,w['counterparty'],None),('location',w['organization'],None,w['location']),('organization',None,None,None),('foreign',w['organization'],None,None)]:
            async with rejected_sql(conn,'23514'):
                await conn.execute('INSERT INTO core.partner_contract_create_refs VALUES ($1,$2,$3,$4,$5,$6)',uuid.uuid4(),PROFILE,kind,org,cp,location)
        await conn.execute('INSERT INTO core.partner_contract_create_types VALUES ($1,$2)',PROFILE,w['type_code'])
        async with rejected_sql(conn,'23505'):
            await conn.execute('INSERT INTO core.partner_contract_create_types VALUES ($1,$2)',PROFILE,w['type_code'])
        async with rejected_sql(conn,'23503'):
            await conn.execute('INSERT INTO core.partner_contract_create_types VALUES ($1,$2)',PROFILE,'synthetic-missing-type')
        async with rejected_sql(conn,'23514'):
            await conn.execute('INSERT INTO core.partner_contract_create_types VALUES ($1,$2)',PROFILE,' ')
        async with rejected_sql(conn,'23514'):
            await conn.execute("INSERT INTO core.partner_contract_create_refs VALUES ($1,$2,'location',NULL,NULL,' ')",uuid.uuid4(),PROFILE)


async def success_namespace_immutable(conn, config, w):
    admit(config)
    await identity(conn)
    async with conn.transaction():
        await profile(conn,w)
        await intent(conn,w)
        async with rejected_sql(conn,'23505'):
            await intent(conn,w,intent_id=uuid.uuid4())
        async with rejected_sql(conn,'23505'):
            await conn.execute('INSERT INTO core.partner_contract_intent_locations VALUES ($1,$2)',INTENT,w['location'])
        # Проверить настоящие INSERT constraints отдельно от UPDATE trigger.
        # JSON только копирует существующую синтетическую typed row в SQL.
        for changes in ({'request_hash':'A'*64},{'hash_version':2},{'succeeded':False},
                        {'operation':'other'}, {'actor_kind':'service'}, {'actor_key':'not-a-user-uuid'},
                        {'current_user_id':None}, {'current_contract_id':None}):
            import json
            changes = {**changes,'id':str(uuid.uuid4()),'creation_key':str(uuid.uuid4())}
            async with rejected_sql(conn,'23514'):
                await conn.execute('''INSERT INTO core.partner_contract_success_intents
                    SELECT (pg_catalog.jsonb_populate_record(NULL::core.partner_contract_success_intents,
                      pg_catalog.to_jsonb(i) || $2::jsonb)).*
                    FROM core.partner_contract_success_intents i WHERE id=$1''',INTENT,json.dumps(changes))
        for column,value in [('company_id',uuid.uuid4()),('newborn_id',uuid.uuid4()),('actor_key','different'),('request_hash','b'*64),('created_type_code','different'),('create_profile_id',uuid.uuid4())]:
            async with rejected_sql(conn,'23514'):
                # Закрытый список буквальных идентификаторов этой матрицы.
                await conn.execute('UPDATE core.partner_contract_success_intents SET '+column+'=$1 WHERE id=$2',value,INTENT)
        async with rejected_sql(conn,'23514'):
            await conn.execute("UPDATE core.partner_contract_intent_locations SET location_id='other' WHERE intent_id=$1",INTENT)
        async with rejected_sql(conn,'23514'):
            await conn.execute('DELETE FROM core.partner_contract_intent_locations WHERE intent_id=$1',INTENT)
    # Поздняя транзакция не может дополнить provenance завершённой строки.
    async with rejected_sql(conn,'23514'):
        await conn.execute("INSERT INTO core.partner_contract_intent_locations VALUES ($1,'synthetic-later')",INTENT)
    # Machine intent не имеет native human FK, включая tombstone.
    async with conn.transaction():
        await intent(conn,w,user=False,intent_id=uuid.uuid4(),key=uuid.uuid4())
    assert await conn.fetchval('SELECT count(*) FROM core.partner_contract_success_intents') == 2


async def current_fk_tombstones(conn, config, w):
    admit(config)
    await identity(conn)
    async with conn.transaction():
        await profile(conn,w)
        await intent(conn,w)
    before = dict(await conn.fetchrow('SELECT * FROM core.partner_contract_success_intents WHERE id=$1',INTENT))
    await conn.execute('DELETE FROM core.contracts WHERE id=$1',w['contract'])
    await conn.execute('DELETE FROM core.users WHERE id=$1',w['user'])
    after = dict(await conn.fetchrow('SELECT * FROM core.partner_contract_success_intents WHERE id=$1',INTENT))
    assert after == {**before,'current_user_id':None,'current_contract_id':None}
    assert await conn.fetchval('SELECT location_id FROM core.partner_contract_intent_locations WHERE intent_id=$1',INTENT) == w['location']
    from schema_migrations import runner
    assert (await runner.execute(config,'check',revision=REVISION))['action'] == 'verified'


async def approval_ref_deletes(conn, config, w):
    admit(config)
    await identity(conn)
    async with conn.transaction():
        await profile(conn,w)
        await intent(conn,w)
        await conn.execute("INSERT INTO core.partner_contract_create_refs VALUES ($1,$2,'location',NULL,NULL,$3)",uuid.uuid4(),PROFILE,w['location'])
    # В world ROOT нет посторонних native ссылок, запрещающих удаление.
    await conn.execute('DELETE FROM core.contracts WHERE id=$1',w['contract'])
    await conn.execute('DELETE FROM core.service_locations WHERE id=$1',w['location'])
    assert await conn.fetchval('SELECT count(*) FROM core.partner_contract_create_refs WHERE profile_id=$1',PROFILE) == 0
    assert await conn.fetchval('SELECT location_id FROM core.partner_contract_intent_locations WHERE intent_id=$1',INTENT) == w['location']
    assert await conn.fetchval('SELECT newborn_id FROM core.partner_contract_success_intents WHERE id=$1',INTENT) == w['contract']


async def parent_history_retention(conn, config, w):
    admit(config)
    await identity(conn)
    async with conn.transaction():
        await profile(conn,w)
        await intent(conn,w)
    for table,ident in [('partner_contract_create_profiles',PROFILE),('partner_grants',w['grant']),('partner_installations',w['installation']),('eco_apps',w['app'])]:
        await conn.execute('DELETE FROM core.'+table+' WHERE id=$1',ident)
        assert await conn.fetchval('SELECT count(*) FROM core.partner_contract_success_intents WHERE id=$1',INTENT) == 1
    # В history нет company FK: новых ограничений native company owner нет.
    outgoing = await conn.fetch("""SELECT confrelid::regclass::text AS target FROM pg_catalog.pg_constraint
        WHERE conrelid='core.partner_contract_success_intents'::regclass AND contype='f'""")
    assert {r['target'].split('.')[-1] for r in outgoing} == {'users','contracts'}
    # Явное удаление history — приватное обслуживание, не profile cascade.
    await conn.execute('DELETE FROM core.partner_contract_success_intents WHERE id=$1',INTENT)
    assert await conn.fetchval('SELECT count(*) FROM core.partner_contract_intent_locations WHERE intent_id=$1',INTENT) == 0
