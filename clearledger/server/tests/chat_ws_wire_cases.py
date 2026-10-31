"""Six finite ROOT-only native TCP/PG cases; no pytest/main/lifespan/child processes.

Imported only after chat_ws_wire_approved approval/source/environment/network gates.
All tokens and wire JSON remain memory-only; receipts store enum facts and correlation IDs.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import time
import uuid

DB_NAME = "api_chat_ws_wire_test_20261031"
DSN = "postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33547/" + DB_NAME
RAW_DSN = DSN.replace("postgresql+asyncpg", "postgresql", 1)
NOTIFY_CHANNEL = "clearledger_chat_ws"
CASE_IDS = (
    "CP01-WIRE-01-NORMAL-PEER-CLEANUP",
    "CP01-WIRE-02-SIGNED-IDLE-EXPIRY",
    "CP01-WIRE-03-CURRENT-TV-REVOKE",
    "CP01-WIRE-04-ROOM-ACL-DROP",
    "CP01-WIRE-05-CROSSWORKER-PG-OWN-ORIGIN",
    "CP01-WIRE-06-STOP-DRAIN",
)
MODEL_ROOTS = ("Company", "CompanyRole", "User", "UserCompany", "ChatRoom", "ChatParticipant",
               "PartnerSpace", "Task", "TaskParticipant", "TaskWatcher", "ChatMessage")
TABLES = ('chat_messages', 'chat_participants', 'chat_rooms', 'companies', 'company_roles',
          'counterparties', 'eco_partner_spaces', 'org_departments', 'organizations', 'regions',
          'service_locations', 'task_participants', 'task_projects', 'task_sprints', 'task_types',
          'task_versions', 'task_watchers', 'tasks', 'user_companies', 'users')
# Separate synthetic service fixture, never a production migration or domain table.
CONTROL_DDL = """CREATE SCHEMA service_fixture;
CREATE TABLE service_fixture.wire_control (
 lease uuid NOT NULL,
 stage char(64) NOT NULL CHECK (stage ~ '^[0-9a-f]{64}$'),
 seq smallint NOT NULL CHECK (seq BETWEEN 0 AND 3),
 command varchar(16) NOT NULL CHECK (command IN ('ready','room_drop','own_publish','stop')),
 correlation uuid NOT NULL,
 status varchar(8) NOT NULL CHECK (status IN ('pending','done','failed')),
 result jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (octet_length(result::text) <= 2048),
 PRIMARY KEY (lease,stage,seq), UNIQUE (seq), UNIQUE (lease,correlation),
 CHECK ((seq=0 AND command='ready') OR (seq=1 AND command='room_drop')
     OR (seq=2 AND command='own_publish') OR (seq=3 AND command='stop'))
);
CREATE TABLE service_fixture.wire_lease (
 lease uuid PRIMARY KEY,
 singleton boolean NOT NULL DEFAULT true UNIQUE CHECK (singleton),
 stage char(64) NOT NULL CHECK (stage ~ '^[0-9a-f]{64}$'),
 receipt jsonb NOT NULL CHECK (octet_length(receipt::text) <= 20000),
 UNIQUE (lease,stage)
);
ALTER TABLE service_fixture.wire_control ADD CONSTRAINT wire_control_lease
 FOREIGN KEY (lease,stage) REFERENCES service_fixture.wire_lease(lease,stage);"""
# Copied exact native manager _ensure_presence_table DDL; pinned source reviewed separately.
PRESENCE_DDL = (
    "CREATE UNLOGGED TABLE IF NOT EXISTS chat_ws_presence ( connection_id uuid PRIMARY KEY, worker_id uuid NOT NULL, user_id text NOT NULL, seen_at timestamptz NOT NULL DEFAULT now())",
    "CREATE INDEX IF NOT EXISTS idx_chat_ws_presence_user_seen ON chat_ws_presence (user_id, seen_at)",
)
SCHEMA_SQL = """SELECT n.nspname,c.relname,c.relkind,c.relpersistence,c.relowner::bigint AS relation_owner_oid,n.nspowner::bigint AS schema_owner_oid,
 COALESCE((SELECT jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
  pg_get_expr(d.adbin,d.adrelid),a.attgenerated) ORDER BY a.attnum)
  FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
  WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),'[]'::jsonb)::text AS columns,
 COALESCE((SELECT jsonb_agg(pg_get_constraintdef(x.oid,true) ORDER BY x.conname)
  FROM pg_constraint x WHERE x.conrelid=c.oid),'[]'::jsonb)::text AS constraints,
 COALESCE((SELECT jsonb_agg(pg_get_indexdef(i.indexrelid) ORDER BY ic.relname)
  FROM pg_index i JOIN pg_class ic ON ic.oid=i.indexrelid WHERE i.indrelid=c.oid),'[]'::jsonb)::text AS indexes
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('public','service_fixture') AND c.relkind IN ('r','p') ORDER BY n.nspname,c.relname"""
DB_ID_SQL = """SELECT d.oid::bigint AS oid,d.datdba::bigint AS owner_oid,current_database() AS name,
 current_user AS db_user,current_setting('server_version_num')::int AS version,
 (SELECT oid::bigint FROM pg_roles WHERE rolname=current_user) AS session_user_oid,
 pg_database_size(current_database())::bigint AS database_bytes,pg_current_wal_lsn()::text AS wal_lsn,
 pg_current_snapshot()::text AS transaction_snapshot
 FROM pg_database d WHERE d.datname=current_database()"""


def require(condition, code):
    if not condition:
        raise RuntimeError(code)  # codes are fixed; never include exception/URI/claims


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def lease():
    return uuid.UUID(os.environ["CHAT_WS_WIRE_DB_LEASE"])


def stage():
    return os.environ["CHAT_WS_WIRE_STAGE_PLAN_SHA256"]


def correlation(label):
    return uuid.uuid5(lease(), label)


async def until(check, seconds, code):
    deadline = asyncio.timeout(seconds)
    try:
        async with deadline:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                value = await check()
                if value:
                    return value
                await asyncio.sleep(0.05)
    except TimeoutError:
        if not deadline.expired():
            raise  # A check's unrelated timeout remains an unknown failure.
        require(False, code)
    require(False, code)


async def identity(connection):
    row = dict(await connection.fetchrow(DB_ID_SQL))
    require(row['name'] == DB_NAME and row['db_user'] == 'clearledger'
            and row['oid'] == int(os.environ['CHAT_WS_WIRE_DB_OID'])
            and 160000 <= row['version'] < 170000, 'db_identity')
    return row


async def schema_snapshot(connection):
    rows = [dict(row) for row in await connection.fetch(SCHEMA_SQL)]
    functions = [dict(row) for row in await connection.fetch("""SELECT n.nspname,p.proname,
     pg_get_function_identity_arguments(p.oid) AS args,pg_get_functiondef(p.oid) AS definition
     FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
     WHERE n.nspname IN ('public','service_fixture') ORDER BY n.nspname,p.proname,args""")]
    sequences = [dict(row) for row in await connection.fetch("""SELECT schemaname,sequencename,sequenceowner,
      data_type::text,start_value,min_value,max_value,increment_by,cycle,cache_size
      FROM pg_sequences WHERE schemaname IN ('public','service_fixture') ORDER BY schemaname,sequencename""")]
    return {'relations': rows, 'functions': functions,'sequences':sequences}


async def resource_oracle(raw, baseline):
    # Own dedicated ROOT PG only: WAL is cluster-wide and is not attributed to a tenant.
    row = dict(await raw.fetchrow("""SELECT pg_database_size(current_database())::bigint AS db_bytes,
        pg_wal_lsn_diff(pg_current_wal_lsn(),$1::text::pg_lsn)::bigint AS wal_bytes""", baseline['wal_lsn']))
    require(0 <= row['db_bytes'] - baseline['database_bytes'] <= 64*1024*1024
            and 0 <= row['wal_bytes'] <= 128*1024*1024, 'fixture_growth_target')
    require(await raw.fetchval('SELECT count(*) FROM service_fixture.wire_lease') == 1
            and await raw.fetchval('SELECT count(*) FROM service_fixture.wire_control') <= 4, 'fixture_row_caps')
    return row


async def connect_raw():
    import asyncpg
    return await asyncpg.connect(RAW_DSN)


async def close_raw(connection):
    if connection is not None:
        async with asyncio.timeout(5):
            await connection.close(timeout=5)
        require(connection.is_closed(), 'raw_pg_not_closed')


def schema_admission():
    """Metadata-only, no engine/connect/SQL; ROOT independently compiles this sealed recipe."""
    from sqlalchemy import Sequence
    from sqlalchemy.schema import CreateTable, CreateIndex, CreateSequence, AddConstraint
    from sqlalchemy.sql.ddl import sort_tables_and_constraints
    from sqlalchemy.dialects.postgresql import dialect
    from app import models
    from app.services.phone_e164 import PHONE_FUNCTION_DDL
    selected = set()
    def visit(table):
        if table in selected:
            return
        selected.add(table)
        for fk in table.foreign_keys:
            visit(fk.column.table)
    for name in MODEL_ROOTS:
        visit(getattr(models, name).__table__)
    require(tuple(sorted(t.name for t in selected)) == TABLES, 'canonical_fk_closure')
    pg = dialect()
    canonical = [PHONE_FUNCTION_DDL]
    sequences = {c.default for t in selected for c in t.columns if isinstance(c.default,Sequence)}
    require({seq.name for seq in sequences} == {'tasks_number_seq'}, 'canonical_sequences')
    canonical.extend(str(CreateSequence(seq).compile(dialect=pg)) for seq in sorted(sequences,key=lambda x:x.name))
    for table, fks in sort_tables_and_constraints(sorted(selected,key=lambda t:t.name)):
        if table is None:
            canonical.extend(str(AddConstraint(fk).compile(dialect=pg)) for fk in
                sorted(fks,key=lambda fk:(fk.table.fullname, str(fk.name),str(fk.column_keys))))
        else:
            canonical.append(str(CreateTable(table,include_foreign_key_constraints=fks).compile(dialect=pg)))
            canonical.extend(str(CreateIndex(index).compile(dialect=pg)) for index in sorted(table.indexes,key=lambda i:i.name or ''))
    canonical.extend(PRESENCE_DDL)
    # Full ordered statement stream, including phone/sequence/deferred FK/control DDL.
    full = [*canonical, CONTROL_DDL]
    seal = digest(full)
    require(seal == os.environ['CHAT_WS_WIRE_SCHEMA_DDL_SHA256'], 'ROOT_full_schema_DDL_seal')
    return {'canonical':canonical,'control':CONTROL_DDL,'full':full,'seal':seal}


async def prepare(evidence, recipe):
    """ROOT explicit separate stage, empty own DB only; no drop/create_database/global create_all."""
    require(os.environ['CHAT_WS_WIRE_PREPARE_JSON'] == '{}', 'prepare_input')
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from app import database, models
    engine = create_async_engine(DSN, pool_size=1, max_overflow=0)
    raw = None
    try:
        raw = await connect_raw()
        ident = await identity(raw)
        count = await raw.fetchval("""SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname IN ('public','service_fixture') AND c.relkind IN ('r','p','v','m','S','f')""")
        require(count == 0 and not await raw.fetchval("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='service_fixture')"), 'nonempty_fixture_database')
        async with engine.begin() as conn:
            for statement in recipe['canonical']:
                await conn.execute(text(statement))
        await raw.execute(recipe['control'])
        ids = {key: str(correlation('fixture:' + key)) for key in ('company_a','company_b','user_a','user_b','room_a','room_b')}
        from sqlalchemy.ext.asyncio import async_sessionmaker
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            companies = [models.Company(id=uuid.UUID(ids['company_' + k]), name='Synthetic wire ' + k,
                          slug='wire-' + lease().hex + '-' + k, profile_id='energy') for k in ('a','b')]
            db.add_all(companies)
            await db.flush()
            users = [models.User(id=uuid.UUID(ids['user_' + k]), company_id=uuid.UUID(ids['company_' + k]),
                     email='wire-' + k + '@example.test', name='Synthetic wire ' + k,
                     password_hash='!synthetic', token_version=0, is_superadmin=False) for k in ('a','b')]
            db.add_all(users)
            await db.flush()
            for k in ('a','b'):
                db.add(models.UserCompany(user_id=uuid.UUID(ids['user_' + k]), company_id=uuid.UUID(ids['company_' + k]), role='user', modules=['docs']))
                db.add(models.ChatRoom(id=uuid.UUID(ids['room_' + k]), company_id=uuid.UUID(ids['company_' + k]),
                       type='group', name='Synthetic wire room ' + k, created_by=uuid.UUID(ids['user_' + k]), is_active=True))
            await db.flush()
            for k in ('a','b'):
                db.add(models.ChatParticipant(room_id=uuid.UUID(ids['room_' + k]), user_id=uuid.UUID(ids['user_' + k]), role='member'))
            await db.commit()
        snapshot = await schema_snapshot(raw)
        receipt = {'version': 1, 'lease': str(lease()), 'stage': stage(), 'database': ident,
                   'control_ddl_sha256': hashlib.sha256(CONTROL_DDL.encode()).hexdigest(),
                   'canonical_compiled_ddl_sha256': recipe['seal'], 'schema_sha256': digest(snapshot),
                   'schema_snapshot': snapshot, 'ids': ids, 'table_names': list(TABLES),
                   'cases_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        # Persist only a compact identity seal; full schema snapshot remains private evidence.
        compact = {key: value for key, value in receipt.items() if key != 'schema_snapshot'}
        require(len(json.dumps(compact)) <= 20000 and len(json.dumps(snapshot)) <= 1024*1024, 'prepare_receipt_bound')
        await raw.execute('INSERT INTO service_fixture.wire_lease(lease,stage,receipt) VALUES($1,$2,$3::jsonb)', lease(), stage(), json.dumps(compact))
        await resource_oracle(raw, ident)
        (evidence / 'prepare-schema.json').write_text(json.dumps(snapshot, sort_keys=True))
        (evidence / 'prepare-handoff.json').write_text(json.dumps(compact, sort_keys=True))
        return compact
    finally:
        await close_raw(raw)
        async with asyncio.timeout(5):
            await engine.dispose()
            await database.engine.dispose()


async def verify_handoff(raw):
    require(len(os.environ['CHAT_WS_WIRE_PREPARE_JSON']) <= 20000, 'handoff_bound')
    receipt = json.loads(os.environ['CHAT_WS_WIRE_PREPARE_JSON'])
    require(receipt['lease'] == str(lease()) and receipt['stage'] == stage()
            and receipt['cases_source_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            and receipt['control_ddl_sha256'] == hashlib.sha256(CONTROL_DDL.encode()).hexdigest()
            and receipt['table_names'] == list(TABLES)
            and receipt['canonical_compiled_ddl_sha256'] == os.environ['CHAT_WS_WIRE_SCHEMA_DDL_SHA256'], 'handoff_source_stage')
    ident = await identity(raw)
    require(all(ident[k] == receipt['database'][k] for k in ('oid','owner_oid','session_user_oid','name','db_user','version')), 'handoff_database')
    stored = await raw.fetchval('SELECT receipt::text FROM service_fixture.wire_lease WHERE lease=$1 AND stage=$2', lease(), stage())
    require(stored is not None and json.loads(stored) == receipt, 'handoff_lease')
    require(digest(await schema_snapshot(raw)) == receipt['schema_sha256'], 'handoff_schema_snapshot')
    require(receipt['ids'] == {key: str(correlation('fixture:' + key)) for key in ('company_a','company_b','user_a','user_b','room_a','room_b')}, 'handoff_rows')
    # Also prove synthetic data exists and no prepare app clients survive into either role.
    require(await raw.fetchval("SELECT count(*) FROM users") == 2
            and await raw.fetchval("SELECT count(*) FROM companies") == 2
            and await raw.fetchval("SELECT count(*) FROM pg_stat_activity WHERE datid=$1 AND application_name LIKE 'wire_prepare_%'", ident['oid']) == 0,
            'handoff_fixture_or_prepare_client')
    return receipt


async def command(raw, seq, name, expected):
    cid = correlation('control:' + name)
    await raw.execute("""INSERT INTO service_fixture.wire_control(lease,stage,seq,command,correlation,status)
      VALUES($1,$2,$3,$4,$5,'pending') ON CONFLICT(lease,stage,seq) DO NOTHING""", lease(), stage(), seq, name, cid)
    async def completed():
        row = await raw.fetchrow('SELECT command,correlation,status,result::text AS result FROM service_fixture.wire_control WHERE lease=$1 AND stage=$2 AND seq=$3', lease(), stage(), seq)
        require(row is not None and row['command'] == name and row['correlation'] == cid, 'control_identity')
        require(row['status'] != 'failed', 'receiver_command_failed')
        return json.loads(row['result']) if row['status'] == 'done' else None
    result = await until(completed, 35, 'control_timeout')
    require(result == expected, 'control_golden')
    return result


async def native_runtime():
    from app import database, scope
    from app.api_access_logging import install_oauth_access_filters
    from app.services import chat_ws, chat_ws_session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine(DSN, pool_size=2, max_overflow=0,
      connect_args={'server_settings': {'statement_timeout':'20000','lock_timeout':'2000','idle_in_transaction_session_timeout':'30000'}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # Test resource binding only, same real AsyncSession/current verifier/SQL.
    database.async_session_factory = factory
    chat_ws.async_session_factory = factory
    chat_ws_session.async_session_factory = factory
    from app.config import get_settings
    settings = get_settings()
    require(not any(getattr(settings, name) for name in ('partner_oauth_enabled','partner_api_enabled',
        'partner_api_budget_enabled','partner_docs_enabled','managed_core_budget_enabled')), 'feature_flags_off')
    scope.install_orm_scope()
    install_oauth_access_filters()
    require(chat_ws_session.CHECK_CADENCE == 20 and chat_ws_session.CHECK_TIMEOUT == 5
            and chat_ws_session.SEND_TIMEOUT == 5 and chat_ws_session.DRAIN_TIMEOUT == 5, 'native_targets_changed')
    return engine, factory, chat_ws.manager


def manager_clean(manager):
    return (not manager._sessions and not manager._closing and not manager._meta and not manager._socket_channels
            and not manager._channels and not manager._online and not manager._connection_ids
            and not any(not t.done() for t in (*manager._owned_tasks, *manager._delivery_tasks))
            and manager._listener is None and manager._listener_task is None and manager._presence_task is None
            and not manager._drain_failed)


async def receiver(evidence):
    import uvicorn
    from fastapi import FastAPI
    from app import database
    from app.routers import chat_router
    from app.services import chat_ws
    raw, engine, server_task, server, sock, manager = None, None, None, None, None, None
    observations = {}
    acknowledged = []
    try:
        raw = await connect_raw()
        receipt = await verify_handoff(raw)
        engine, _, manager = await native_runtime()
        require(chat_router.manager is manager and chat_ws.manager is manager, 'actual_singleton')
        await manager.start(DSN)
        require(manager._listener is not None and not manager._listener.is_closed() and manager._presence_ready, 'receiver_real_listener')
        listening = await manager._listener.fetchval('SELECT $1=ANY(array(SELECT pg_listening_channels()))', NOTIFY_CHANNEL)
        require(listening, 'receiver_listen_channel')
        # Additional observation on the SAME actual asyncpg listener, no production callback replacement.
        def observed(_connection, _pid, _channel, payload):
            item = json.loads(payload)
            marker = (item.get('payload') or {}).get('wireId')
            allowed = {str(correlation(label)) for label in ('cross','own')}
            if marker in allowed:
                require(item.get('channel') == 'user:'+receipt['ids']['user_a'], 'pg_observer_channel')
                origin = str(uuid.UUID(item.get('origin')))
                require((origin == manager._instance_id) == (marker == str(correlation('own'))), 'pg_observer_origin')
                observations[marker] = observations.get(marker, 0) + 1
                require(sum(observations.values()) <= 4, 'pg_observer_bound')
        await manager._listener.add_listener(NOTIFY_CHANNEL, observed)
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        app.include_router(chat_router.router, prefix='/api')
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1',33548))
        sock.listen(8)
        config = uvicorn.Config(app, host='127.0.0.1', port=33548, loop='asyncio', http='h11', ws='websockets',
            lifespan='off', log_config=None, access_log=False, log_level='warning', workers=1,
            ws_max_size=65536, ws_max_queue=8, ws_per_message_deflate=False, timeout_graceful_shutdown=5)
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve(sockets=[sock]), name='wire-uvicorn')
        async def started():
            require(not server_task.done(), 'server_start_failed')
            return server.started
        await until(started, 15, 'server_start_timeout')
        await raw.execute("INSERT INTO service_fixture.wire_control(lease,stage,seq,command,correlation,status,result) VALUES($1,$2,0,'ready',$3,'done',$4::jsonb)", lease(), stage(), correlation('control:ready'), json.dumps({'ready':True}))
        deadline, next_seq = time.monotonic()+240, 1
        while next_seq <= 3 and time.monotonic() < deadline:
            require(not server_task.done(), 'server_early_exit')
            row = await raw.fetchrow("SELECT seq,command,correlation,status FROM service_fixture.wire_control WHERE lease=$1 AND stage=$2 AND seq=$3", lease(), stage(), next_seq)
            if row is None:
                await asyncio.sleep(.05)
                continue
            expected_name = {1:'room_drop',2:'own_publish',3:'stop'}[next_seq]
            require(row['command'] == expected_name and row['correlation'] == correlation('control:'+expected_name) and row['status']=='pending', 'receiver_control_identity')
            try:
                if expected_name == 'room_drop':
                    async def dropped():
                        channel = 'chat:'+receipt['ids']['room_a']
                        return bool(manager._sessions) and channel not in manager._channels
                    await until(dropped, 30, 'room_unsubscribe_timeout')
                    result = {'room_unsubscribed':True,'tenant_live':bool(manager._sessions)}
                elif expected_name == 'own_publish':
                    own_id = str(correlation('own'))
                    await manager.broadcast('user:'+receipt['ids']['user_a'], {'type':'wire:probe','wireId':own_id})
                    async def delivered():
                        return observations.get(own_id) == 1 and not any(not task.done() for task in manager._delivery_tasks)
                    await until(delivered, 10, 'own_pg_not_observed')
                    require(observations.get(str(correlation('cross'))) == 1, 'cross_pg_not_observed')
                    result = {'own_pg_observed':1,'cross_pg_observed':1,'delivery_pending':0}
                else:
                    await manager.stop()
                    require(manager_clean(manager), 'manager_stop_incomplete')
                    require(await raw.fetchval('SELECT count(*) FROM chat_ws_presence')==0, 'stop_presence')
                    server.should_exit = True
                    async with asyncio.timeout(10):
                        await server_task
                    require(not server.server_state.tasks and not server.server_state.connections, 'asgi_drain')
                    async with asyncio.timeout(5):
                        await engine.dispose()
                        await database.engine.dispose()
                    result = {'manager_clean':True,'asgi_tasks':0,'asgi_connections':0,'presence':0}
                await raw.execute("UPDATE service_fixture.wire_control SET status='done',result=$4::jsonb WHERE lease=$1 AND stage=$2 AND seq=$3 AND status='pending'", lease(),stage(),next_seq,json.dumps(result))
                acknowledged.append(expected_name)
            except BaseException:
                await raw.execute("UPDATE service_fixture.wire_control SET status='failed',result='{}'::jsonb WHERE lease=$1 AND stage=$2 AND seq=$3",lease(),stage(),next_seq)
                raise
            next_seq += 1
        require(next_seq==4, 'receiver_case_plan_timeout')
        await resource_oracle(raw, receipt['database'])
        require(digest(await schema_snapshot(raw)) == receipt['schema_sha256'], 'receiver_schema_changed')
        return {'commands':acknowledged,'actual_pg_observed':observations,'listener_closed':True,'manager_clean':True}
    finally:
        # Same owners on all exits; failures propagate and never become a successful receipt.
        if manager is not None:
            async with asyncio.timeout(15):
                await manager.stop()
        if server is not None:
            server.should_exit = True
        if server_task is not None and not server_task.done():
            async with asyncio.timeout(10):
                await server_task
        if sock is not None:
            sock.close()
        if engine is not None:
            async with asyncio.timeout(5):
                await engine.dispose()
                await database.engine.dispose()
        await close_raw(raw)


class Peer:
    """Real websockets.asyncio client; frame assertions never record bearer/URI/payload."""
    def __init__(self, connection, ids):
        self.connection = connection
        self.ids = ids
        self.frames = 0
        self.types = []

    def presence_frame(self, value):
        if value.get('type') != 'presence':
            return False
        require(set(value) <= {'type','channel','userId','userName','online'}
                and value.get('channel') == 'company:'+self.ids['company_a']
                and value.get('userId') == self.ids['user_a']
                and isinstance(value.get('online'),bool)
                and ('userName' not in value or value['userName']=='Synthetic wire a'), 'presence_tenant_shape')
        return True

    async def next(self, timeout=5):
        async with asyncio.timeout(timeout):
            raw = await self.connection.recv()
        require(isinstance(raw,str) and len(raw.encode())<=65536, 'text_frame_bound')
        self.frames += 1
        require(self.frames<=64, 'frame_count_bound')
        value = json.loads(raw)
        require(isinstance(value,dict), 'json_frame_shape')
        self.types.append(value.get('type'))
        return value

    async def expect(self, golden, timeout=5):
        # Presence is native asynchronous background traffic, not silently arbitrary frames.
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            value = await self.next(max(.01,end-time.monotonic()))
            if self.presence_frame(value):
                continue
            require(value==golden,'golden_frame')
            return
        require(False,'golden_timeout')

    async def send(self, value):
        raw = json.dumps(value,separators=(',',':'))
        require(len(raw.encode())<=2048, 'client_payload_bound')
        async with asyncio.timeout(5):
            await self.connection.send(raw)

    async def quiet(self, seconds, forbidden=None):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            try:
                value=await self.next(max(.01,end-time.monotonic()))
            except TimeoutError:
                return
            require(self.presence_frame(value),'unexpected_quiet_frame')
            require(forbidden is None or value.get('wireId')!=forbidden,'protected_frame')

    async def closed(self, code, reason, timeout=35):
        from websockets.exceptions import ConnectionClosed
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                value=await self.next(max(.01,end-time.monotonic()))
                require(self.presence_frame(value), 'frame_after_terminal_boundary')
            except ConnectionClosed as exc:
                require(exc.rcvd is not None and exc.rcvd.code==code and exc.rcvd.reason==reason, 'wire_close_golden')
                return
        require(False,'wire_close_timeout')


async def open_peer(factory, ids, *, expires_seconds=None):
    from websockets.asyncio.client import connect
    from sqlalchemy import select
    from app.auth import token_for
    from app.models import User
    async with factory() as db:
        user = (await db.execute(select(User).where(User.id==uuid.UUID(ids['user_a'])))).scalar_one()
        kwargs = {} if expires_seconds is None else {'expires_at':datetime.now(timezone.utc)+timedelta(seconds=expires_seconds)}
        token=token_for(user,**kwargs)
    # No signature/shape/session-policy bypass; actual production router decodes/verifies.
    connection=await connect('ws://127.0.0.1:33548/api/chat/ws?token='+token+'&company_id='+ids['company_a'],
        proxy=None,open_timeout=15,close_timeout=5,max_size=65536,max_queue=8,compression=None,ping_interval=None)
    token=''
    peer=Peer(connection,ids)
    await peer.expect({'type':'connected','userId':ids['user_a']})
    return peer


async def presence(raw, ids, count, *, last_seen=False):
    async def matches():
        actual=await raw.fetchval('SELECT count(*) FROM chat_ws_presence WHERE user_id=$1',ids['user_a'])
        seen=await raw.fetchval('SELECT last_seen_at IS NOT NULL FROM users WHERE id=$1',uuid.UUID(ids['user_a']))
        return actual==count and (not last_seen or seen)
    await until(matches,10,'presence_or_last_seen_timeout')


async def publisher(evidence):
    from app import database
    raw,engine,manager,peer=None,None,None,None
    facts=[]
    try:
        raw=await connect_raw()
        receipt=await verify_handoff(raw)
        ids=receipt['ids']
        engine,factory,manager=await native_runtime()
        await manager.start(DSN)
        require(manager._listener is not None and not manager._listener.is_closed(), 'publisher_listener')
        async def ready():
            row=await raw.fetchrow("SELECT status,result::text AS result FROM service_fixture.wire_control WHERE lease=$1 AND stage=$2 AND seq=0 AND command='ready'",lease(),stage())
            return row is not None and row['status']=='done' and json.loads(row['result'])=={'ready':True}
        await until(ready,30,'receiver_ready_timeout')
        # 01: actual upgrade, connected and application ping, real peer-origin normal close.
        peer=await open_peer(factory,ids)
        await presence(raw,ids,1)
        await peer.send({'type':'ping'})
        await peer.expect({'type':'pong'})
        await peer.connection.close(code=1000,reason='')
        await peer.closed(1000,'',5)
        await presence(raw,ids,0,last_seen=True)
        facts.append({'id':CASE_IDS[0],'wire':'101/connected/pong/1000','presence':0,'last_seen':True})
        peer=None
        # 02: finite fresh native exp, idle peer. No clock/policy/cadence monkeypatch.
        peer=await open_peer(factory,ids,expires_seconds=8)
        await peer.closed(1008,'session_expired',15)
        await presence(raw,ids,0,last_seen=True)
        facts.append({'id':CASE_IDS[1],'close_code':1008,'close_reason':'session_expired','idle':True})
        peer=None
        # 03: real committed tv revoke and real C20 watchdog. No instantaneous-revoke claim.
        peer=await open_peer(factory,ids)
        changed=await raw.execute('UPDATE users SET token_version=token_version+1 WHERE id=$1',uuid.UUID(ids['user_a']))
        require(changed=='UPDATE 1','revoke_row_count')
        require(await raw.fetchval('SELECT token_version FROM users WHERE id=$1',uuid.UUID(ids['user_a']))==1,'revoke_committed')
        await peer.closed(1008,'session_revoked',35)
        marker=str(correlation('blocked'))
        await manager.broadcast('user:'+ids['user_a'],{'type':'wire:probe','wireId':marker})
        from websockets.exceptions import ConnectionClosed
        try:
            await peer.next(1)
        except ConnectionClosed:
            pass
        else:
            require(False,'protected_frame_after_close')
        await presence(raw,ids,0,last_seen=True)
        facts.append({'id':CASE_IDS[2],'close_code':1008,'close_reason':'session_revoked','blocked_correlation':marker,'tv':1})
        peer=None
        # 04: real explicit subscription, current ordinary-room ACL delete; tenant stays live.
        peer=await open_peer(factory,ids)
        room='chat:'+ids['room_a']
        await peer.send({'type':'subscribe','channel':room})
        await peer.send({'type':'ping'})
        await peer.expect({'type':'pong'})  # same endpoint loop => explicit ACL completed
        marker=str(correlation('room_allowed'))
        await manager.broadcast(room,{'type':'wire:probe','wireId':marker})
        await peer.expect({'type':'wire:probe','wireId':marker,'channel':room})
        changed=await raw.execute('DELETE FROM chat_participants WHERE room_id=$1 AND user_id=$2',uuid.UUID(ids['room_a']),uuid.UUID(ids['user_a']))
        require(changed=='DELETE 1','room_revoke_row_count')
        require(await raw.fetchval('SELECT count(*) FROM chat_participants WHERE room_id=$1 AND user_id=$2',uuid.UUID(ids['room_a']),uuid.UUID(ids['user_a']))==0,'room_revoke_committed')
        denied=str(correlation('room_denied'))
        await manager.broadcast(room,{'type':'wire:probe','wireId':denied})
        await peer.quiet(11,denied)  # check5+cleanup5 plus test observation margin; not an SLA
        await command(raw,1,'room_drop',{'room_unsubscribed':True,'tenant_live':True})
        await peer.send({'type':'subscribe','channel':room})
        await peer.expect({'type':'subscribe:denied','channel':room})
        foreign='company:'+ids['company_b']
        await peer.send({'type':'subscribe','channel':foreign})
        await peer.expect({'type':'subscribe:denied','channel':foreign})
        await peer.send({'type':'ping'})
        await peer.expect({'type':'pong'})
        facts.append({'id':CASE_IDS[3],'room_unsubscribed':True,'tenant_live':True,'foreign_subscribe':'denied','dropped_correlation':denied})
        # 05: publisher native singleton has NO local sockets, real PG -> other PID TCP socket.
        require(not manager._sessions and not manager._meta,'publisher_must_have_no_local_sockets')
        marker=str(correlation('cross'))
        await manager.broadcast('user:'+ids['user_a'],{'type':'wire:probe','wireId':marker})
        await peer.expect({'type':'wire:probe','wireId':marker,'channel':'user:'+ids['user_a']})
        await command(raw,2,'own_publish',{'own_pg_observed':1,'cross_pg_observed':1,'delivery_pending':0})
        own=str(correlation('own'))
        await peer.expect({'type':'wire:probe','wireId':own,'channel':'user:'+ids['user_a']})
        await peer.quiet(.5,own)
        facts.append({'id':CASE_IDS[4],'cross_correlation':marker,'own_correlation':own,'own_wire_copies':1,'same_actual_listener_observed_own':True})
        # 06: native manager stop sends safe 1001; actual ASGI drains; receiver PG clients disappear.
        await command(raw,3,'stop',{'manager_clean':True,'asgi_tasks':0,'asgi_connections':0,'presence':0})
        await peer.closed(1001,'server_shutdown',10)
        peer=None
        async def no_receiver_clients():
            return await raw.fetchval("SELECT count(*) FROM pg_stat_activity WHERE datid=$1 AND application_name=$2",receipt['database']['oid'],'wire_receiver_'+str(lease())[:8])==0
        await until(no_receiver_clients,10,'receiver_pg_clients_residual')
        await manager.stop()
        require(manager_clean(manager),'publisher_manager_stop_incomplete')
        require(await raw.fetchval('SELECT count(*) FROM chat_ws_presence')==0,'final_presence')
        require(await raw.fetchval("SELECT count(*) FROM service_fixture.wire_control WHERE lease=$1 AND stage=$2 AND status='done'",lease(),stage())==4,'control_complete')
        resources = await resource_oracle(raw, receipt['database'])
        require(digest(await schema_snapshot(raw))==receipt['schema_sha256'],'publisher_schema_changed')
        facts.append({'id':CASE_IDS[5],'close_code':1001,'close_reason':'server_shutdown','receiver_pg_clients':0,'presence':0,'publisher_manager_clean':True})
        require(tuple(x['id'] for x in facts)==CASE_IDS,'six_exact_cases')
        return {'cases':facts,'count':6,'fixture_resource_observation':resources,'frontend24':'DEFERRED_NOT_RUN','106_complete':False}
    finally:
        if peer is not None:
            async with asyncio.timeout(5):
                await peer.connection.close()
        if manager is not None:
            async with asyncio.timeout(15):
                await manager.stop()
        if engine is not None:
            async with asyncio.timeout(5):
                await engine.dispose()
                await database.engine.dispose()
        await close_raw(raw)


async def execute(role, evidence, recipe):
    require(os.environ.get('ROOT_APPROVED_CHAT_WS_WIRE')=='1' and os.environ.get('RUN_CHAT_WS_WIRE')=='1', 'ROOT_only')
    # Whole role is bounded cooperatively; ROOT supervisor owns actual hard wall/exit evidence.
    async with asyncio.timeout(270):
        if role=='prepare':
            async with asyncio.timeout(60):
                return await prepare(evidence, recipe)
        if role=='receiver':
            return await receiver(evidence)
        if role=='publisher':
            return await publisher(evidence)
    require(False,'unknown_role')
