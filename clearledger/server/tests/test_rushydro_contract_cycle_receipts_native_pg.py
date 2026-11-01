"""SOURCE ONLY / AUTHOR NOTRUN: exactly34 finite native SQL acceptance groups.

Do not collect through ordinary server/conftest.py (it imports app/engine and
drops schemas before test-module guards). ROOT must review this source, compose
an external pytest controller without that conftest, then inject the module
`rushydro_receipts_root_admission` BEFORE collection. Its no-argument
require_running_approval() validates ROOT's live private lease, exact readonly
source and disposable native PG16 target; this source never grants admission.

External receipt_root_factory(prefix=3|4|5, managed=bool) is an async context
manager creating a NEW native Core/edge world with real app.main registration,
database startup/create_all and actual frozen1..3 or explicit4/5. It yields:
  conn: actual asyncpg.Connection (core search_path, autocommit between cases);
  config: actual runner.Config; factory: actual async_sessionmaker;
  database: original app.database; stranger: actual nonowner asyncpg connection
    to the SAME DB, core USAGE only, no table/function rights/admin bypass;
  bootstrap_probe(namespace, managed): async; calls ORIGINAL create_all using
    ROOT-owned target/settings, captures SQL, restores settings/connection;
    returns {sql: tuple[str], error: {class: str, message: str}|None,
      metadata_stage: bool}. metadata_stage observes the original metadata
    create_all invocation, never a fabricated projection. Probes core/public/receipt_private
    run in ROOT-owned disposable namespaces; foreign guard refusal is expected.
    Foreign probe uses existing receipt_private and search_path receipt_private,
    core: visible Core names exercise the original ownership guard. A custom
    namespace without fallback is not claimed to be forbidden by that guard.
ROOT validates target identity/OIDs BEFORE fixtures/imports and owns all pool,
connection and database disposal. No fixture creates approvals from source pins.
No URL/env selection, container runner, fake sessions, schema repair or cleanup
is supplied here. Fresh5 = fresh full-native3 -> explicit4+5, not empty bootstrap.
"""
import ast
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

import pytest

_admission = sys.modules.get('rushydro_receipts_root_admission')
if _admission is None:
    pytest.skip('ROOT-owned native receipts admission required before collection', allow_module_level=True)
_admission.require_running_approval()

# Only after the externally validated private lease. AUTHOR never imports these.
import asyncpg
from app.models import Company
from app.models_partner_contract_cycle_receipts import (
    PartnerContractCycleReceipt, PartnerContractCycleReceiptRef,
)
from schema_migrations.errors import MigrationError
from schema_migrations.manifest import (
    CONTRACT_CREATE_ID, CONTRACT_CYCLE_RECEIPTS_ID as REVISION, load_known_head,
)
from schema_migrations.runner import execute, execute_sequence, require_applied_prefix

pytestmark = pytest.mark.asyncio(loop_scope='session')
ROOT = Path(__file__).resolve().parents[1]
PARENT = 'core.partner_contract_cycle_receipts'
CHILD = 'core.partner_contract_cycle_receipt_refs'
TABLES = ('partner_contract_cycle_receipts', 'partner_contract_cycle_receipt_refs')
TARGETS = {
    'v2.contract.create': 'contract', 'v2.contract.patch': 'contract',
    'v2.contract.location.link': 'contract', 'v2.term.create': 'term',
    'v2.term.version': 'term', 'v2.term.coverage': 'term',
    'v2.site.contract.link': 'site', 'v2.site.location.link': 'site',
    'v2.document.draft.create': 'document', 'v2.document.contract.link': 'document',
    'v2.document.register': 'document', 'v2.document.version.upload': 'version',
}
KINDS = ('organization', 'counterparty', 'location', 'site', 'contract', 'term', 'document', 'version')
FROZEN_ARTIFACTS = (
    '301b88799018e0123f40a8bbbfec1415184147ba31bf43bb9432e9140ff15ab1',
    '203ee350a47fb3e12d2e2fb6d292fc0e1a19b4cd3cd348b507551cf233cae2f0',
    'c98bc5d27c6aa710618bb5d209d0ef0adfd11a6a4825dcd0831c7403e872cc3d',
    '58ff7a0cf33f7fb55fa080e4efe60c1a4aece67588cf1bfe8b44bc75e92c7e31',
)
CASES = (
    'registration-flags-off', 'registration-flags-on', 'frozen-source-pins',
    'fresh-prefix5', 'upgrade4-to5', 'repeat5', 'required4-vs5',
    'public-default-deny', 'foreign-namespace-untouched', 'namespace-five-dimensions',
    'snapshot-without-authority', 'closed12-target-map', 'strict-hash-versions',
    'result-object', 'ascii128KiB', 'multibyte128KiB', 'typed-refs-xor',
    'typed-refs-unique', 'opaque-location40', 'db-owned-txid-time',
    'parent-immutable', 'child-immutable', 'same-topTX-savepoint',
    'laterTX-ref-denied', 'key-reuse-denied', 'atomic-malformed-rollback',
    'restrict-retention', 'drift-index', 'drift-trigger', 'drift-function',
    'drift-acl', 'drift-default', 'unlogged-collision', 'function-collision',
)
assert len(CASES) == len(set(CASES)) == 34


@asynccontextmanager
async def rollback(conn):
    tx = conn.transaction()
    await tx.start()
    try:
        yield
    finally:
        await tx.rollback()


async def reject(conn, sql, *args, codes=('23514',)):
    """Real PG statement/savepoint failure; never manufacture a rejection."""
    async with rollback(conn):
        with pytest.raises(asyncpg.PostgresError) as error:
            await conn.execute(sql, *args)
        assert error.value.sqlstate in codes


async def seed_companies(w):
    ids = (uuid4(), uuid4())
    async with w.factory() as db:
        db.add_all([Company(id=i, name='Synthetic receipt owner', slug='receipt-'+i.hex,
                            profile_id='energy') for i in ids])
        await db.commit()
    return ids


def values(company, **changes):
    row = dict(id=uuid4(), company_id=company, app_id=uuid4(), installation_id=uuid4(),
        operation='v2.contract.create', command_key=uuid4(), client_id=' Original Client  ',
        user_id=uuid4(), grant_id=uuid4(), profile_id=uuid4(), operation_version=2,
        request_hash='a'*64, hash_version=1, target_kind='contract', target_id=uuid4(), result='{}')
    row.update(changes)
    return row


def insert_sql(row):
    allowed = set(values(uuid4())) | {'created_at', 'created_txid'}
    assert set(row) <= allowed  # Source-owned names only, never caller identifiers.
    keys = list(row)
    return ('INSERT INTO '+PARENT+' ('+', '.join(keys)+') VALUES ('+
            ', '.join('$'+str(i) for i in range(1, len(keys)+1))+') RETURNING *', list(row.values()))


async def receipt(conn, row):
    sql, args = insert_sql(row)
    return await conn.fetchrow(sql, *args)


async def reject_receipt(conn, row, *, codes=('23514',)):
    sql, args = insert_sql(row)
    await reject(conn, sql, *args, codes=codes)


async def ref(conn, parent, kind='site', uid=None, location=None):
    return await conn.fetchrow('INSERT INTO '+CHILD+
        ' (id,receipt_id,kind,uuid_value,location_value) VALUES ($1,$2,$3,$4,$5) RETURNING *',
        uuid4(), parent, kind, uid, location)


async def reject_ref(conn, parent, kind, uid, location, *, codes=('23514',)):
    await reject(conn, 'INSERT INTO '+CHILD+
        ' (id,receipt_id,kind,uuid_value,location_value) VALUES ($1,$2,$3,$4,$5)',
        uuid4(), parent, kind, uid, location, codes=codes)


async def history(conn):
    return [dict(r) for r in await conn.fetch('SELECT * FROM core.core_schema_versions ORDER BY ordinal')]


async def contents(conn):
    return tuple(tuple(dict(r) for r in await conn.fetch('SELECT * FROM '+table+' ORDER BY id'))
                 for table in (PARENT, CHILD))


async def gate(w, required=REVISION):
    async with w.conn.transaction(isolation='repeatable_read', readonly=True):
        return await require_applied_prefix(w.conn, w.config, load_known_head(), required_revision=required)


async def apply5(w):
    return await execute_sequence(w.config, target_revision=REVISION, legacy_sent_before=2000000000)


async def physical_count(conn):
    return await conn.fetchval("""SELECT count(*) FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('core','edge') AND c.relkind='r'""")


def frozen_source():
    path = ROOT/'schema_migrations'
    entries = json.loads((path/'manifest.json').read_bytes())['revisions']
    assert len(entries) == 5
    for ordinal, (entry, digest) in enumerate(zip(entries[:4], FROZEN_ARTIFACTS), 1):
        assert entry['ordinal'] == ordinal and entry['artifact_sha256'] == digest
        metadata = {k:v for k,v in entry.items() if k != 'artifact_sha256'}
        pieces = [json.dumps(metadata,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()]
        for name in sorted(entry['files']):
            raw = (path/name).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == entry['files'][name]
            pieces.append(raw)
        assert hashlib.sha256(b''.join(len(p).to_bytes(8,'big')+p for p in pieces)).hexdigest() == digest


async def registration(w, managed):
    expected = []
    for path in sorted((ROOT/'app').rglob('*.py')):
        for cls in ast.parse(path.read_bytes()).body:
            if isinstance(cls, ast.ClassDef):
                for node in cls.body:
                    if isinstance(node, ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__tablename__' for t in node.targets):
                        expected.append(('.'.join(path.relative_to(ROOT).with_suffix('').parts)+'.'+cls.name,
                                         ast.literal_eval(node.value)))
    actual = [(m.class_.__module__+'.'+m.class_.__name__,m.local_table.name)
              for m in w.database.Base.registry.mappers]
    assert len(actual) == len(expected) == 343 and sorted(actual) == sorted(expected)
    assert len(w.database.Base.metadata.tables) == 343
    assert await physical_count(w.conn) == 341
    for namespace in ('core', 'public', 'receipt_private'):
        probe = await w.bootstrap_probe(namespace, managed)
        assert set(probe) == {'sql','error','metadata_stage'} and probe['sql']
        # PUBLIC+managedON cannot reach metadata: the existing managed gate
        # requires Core. Its specific refusal is not exclusion execution proof.
        expected_stage = namespace == 'core' or (namespace == 'public' and not managed)
        assert probe['metadata_stage'] is expected_stage
        if expected_stage:
            assert probe['error'] is None
        else:
            expected = ('Managed Core budget schema is not ready' if managed else
                        'Database schema ownership check failed; review namespace provisioning')
            assert probe['error'] == {'class':'builtins.RuntimeError','message':expected}
        assert not any(re.search(r'\bCREATE\s+TABLE\b[^;]*partner_contract_cycle_receipt', sql, re.I)
                       for sql in probe['sql'])
        assert not await w.conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relname=ANY($1::text[]) AND c.relkind IN ('r','p','f'))""", list(TABLES))
    assert await physical_count(w.conn) == 341


async def foreign_snapshot(conn):
    return (tuple(dict(r) for r in await conn.fetch("""SELECT n.nspname,c.relname,c.oid,c.relacl,
        c.relkind::text,c.relpersistence::text FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('public','receipt_private') ORDER BY n.nspname,c.relname""")),
        tuple(dict(r) for r in await conn.fetch("""SELECT n.nspname,p.oid,p.proname,p.proacl,
            pg_catalog.pg_get_functiondef(p.oid) AS definition FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname IN ('public','receipt_private') AND p.proname LIKE 'pcc_%'
            ORDER BY n.nspname,p.oid""")))


@pytest.mark.parametrize('case', CASES, ids=CASES)
async def test_receipt_storage_native(case, receipt_root_factory):
    _admission.require_running_approval()
    if case == 'frozen-source-pins':
        frozen_source()
        return
    prefix = 3 if case in {'registration-flags-off','registration-flags-on','fresh-prefix5'} else (
        4 if case in {'upgrade4-to5','required4-vs5','foreign-namespace-untouched',
                     'unlogged-collision','function-collision'} else 5)
    managed = case != 'registration-flags-off'
    async with receipt_root_factory(prefix=prefix, managed=managed) as w:
        conn = w.conn
        assert isinstance(conn, asyncpg.Connection) and not conn.is_in_transaction()
        assert await conn.fetchval('SHOW search_path') == 'core'
        assert await conn.fetchval('SELECT current_database()') == w.config.database
        assert await conn.fetchval('SELECT current_user') == w.config.user
        assert 160000 <= int(await conn.fetchval('SHOW server_version_num')) < 170000
        assert await conn.fetchval('SHOW session_replication_role') == 'origin'
        assert not await conn.fetchval("""SELECT rolsuper OR rolcreatedb OR rolcreaterole OR
            rolreplication OR rolbypassrls FROM pg_catalog.pg_roles WHERE rolname=current_user""")
        assert len(await history(conn)) == prefix
        assert await physical_count(conn) == {3:341,4:347,5:349}[prefix]
        if case.startswith('registration-'):
            await registration(w, managed)
            return
        if case in {'fresh-prefix5','upgrade4-to5'}:
            before = await history(conn)
            result = await apply5(w)
            assert result['prefix_before'] == prefix
            assert [a['revision'] for a in result['actions']] == (
                [CONTRACT_CREATE_ID,REVISION] if prefix == 3 else [REVISION])
            assert all(a['action']=='created' for a in result['actions'])
            assert (await history(conn))[:prefix] == before
            assert len(await history(conn)) == 5 and await physical_count(conn) == 349
            assert await gate(w) == 5
            return
        if case == 'repeat5':
            before = await history(conn), await contents(conn)
            assert (await apply5(w))['actions'] == []
            assert (await execute(w.config,'check',revision=REVISION))['action'] == 'verified'
            assert (await history(conn),await contents(conn)) == before
            return
        if case == 'required4-vs5':
            before = await history(conn)
            assert await gate(w, CONTRACT_CREATE_ID) == 4
            with pytest.raises(MigrationError) as error:
                await gate(w)
            assert error.value.code == 4 and await history(conn) == before
            await apply5(w)
            assert await gate(w, CONTRACT_CREATE_ID) == await gate(w) == 5
            assert (await execute(w.config,'check',revision=CONTRACT_CREATE_ID))['action'] == 'verified'
            return
        if case == 'public-default-deny':
            for table in (PARENT, CHILD):
                assert not await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
                    CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
                    WHERE c.oid=$1::regclass AND a.grantee<>c.relowner)""", table)
                await reject(w.stranger,'SELECT * FROM '+table,codes=('42501',))
            assert await w.stranger.fetchval("SELECT has_schema_privilege(current_user,'core','USAGE')")
            for function in ('pcc_receipt_immutable','pcc_ref_immutable'):
                await reject(w.stranger,'SELECT core.'+function+'()',codes=('42501',))
            assert await gate(w) == 5
            return
        if case == 'foreign-namespace-untouched':
            await conn.execute('CREATE SCHEMA receipt_private')
            for namespace in ('public','receipt_private'):
                for table in TABLES:
                    await conn.execute('CREATE TABLE '+namespace+'.'+table+' (payload text)')
                    await conn.execute('INSERT INTO '+namespace+'.'+table+" VALUES ('Synthetic foreign probe')")
                for function in ('pcc_receipt_immutable','pcc_ref_immutable'):
                    await conn.execute('CREATE FUNCTION '+namespace+'.'+function+"() RETURNS integer LANGUAGE sql AS 'SELECT 7'")
            before = await foreign_snapshot(conn)
            await apply5(w)
            assert await gate(w) == 5 and await foreign_snapshot(conn) == before
            for namespace in ('public','receipt_private'):
                for table in TABLES:
                    assert await conn.fetchval('SELECT payload FROM '+namespace+'.'+table) == 'Synthetic foreign probe'
            return
        if case in {'unlogged-collision','function-collision'}:
            if case == 'unlogged-collision':
                await conn.execute('CREATE UNLOGGED TABLE '+PARENT+' (id uuid)')
            else:
                await conn.execute("CREATE FUNCTION core.pcc_ref_immutable(integer) RETURNS integer LANGUAGE sql AS 'SELECT $1'")
            before = await history(conn)
            with pytest.raises(MigrationError) as error:
                await apply5(w)
            assert error.value.code == 4 and await history(conn) == before
            assert not await conn.fetchval("SELECT to_regclass('"+CHILD+"') IS NOT NULL")
            if case == 'unlogged-collision':
                assert await conn.fetchval("SELECT relpersistence::text FROM pg_catalog.pg_class WHERE oid=$1::regclass", PARENT) == 'u'
            else:
                assert not await conn.fetchval("SELECT to_regclass('"+PARENT+"') IS NOT NULL")
                assert await conn.fetchval('SELECT core.pcc_ref_immutable(7)') == 7
            return
        if case.startswith('drift-'):
            statements = {
                'drift-index':'DROP INDEX core.uq_pcc_ref_location',
                'drift-trigger':'ALTER TABLE '+CHILD+' DISABLE TRIGGER tr_pcc_ref_truncate',
                'drift-function':'ALTER FUNCTION core.pcc_ref_immutable() SET search_path=public',
                'drift-acl':'GRANT SELECT ON TABLE '+PARENT+' TO PUBLIC',
                'drift-default':'ALTER TABLE '+PARENT+" ALTER COLUMN created_txid SET DEFAULT 'forged'::text",
            }
            before = await history(conn), await contents(conn)
            await conn.execute(statements[case])
            with pytest.raises(MigrationError) as error:
                await gate(w)
            assert error.value.code == 4
            with pytest.raises(MigrationError) as error:
                await apply5(w)
            assert error.value.code == 4 and (await history(conn),await contents(conn)) == before
            return
        company, other = await seed_companies(w)
        if case == 'namespace-five-dimensions':
            base = values(company)
            async with rollback(conn):
                await receipt(conn,base)
                for dimension,new in [('company_id',other),('app_id',uuid4()),('installation_id',uuid4()),
                                      ('operation','v2.contract.patch'),('command_key',uuid4())]:
                    await receipt(conn,{**base,'id':uuid4(),dimension:new})
                    await reject_receipt(conn,{**base,'id':uuid4(),dimension:None},codes=('23502',))
                await reject_receipt(conn,{**base,'id':uuid4(),'user_id':uuid4()},codes=('23505',))
                assert await conn.fetchval('SELECT count(*) FROM '+PARENT) == 6
            return
        if case == 'snapshot-without-authority':
            row = values(company)
            async with rollback(conn):
                saved = await receipt(conn,row)
                for key in ('client_id','user_id','grant_id','profile_id','app_id','installation_id','target_id'):
                    assert saved[key] == row[key]
                for kind in KINDS:
                    await ref(conn,saved['id'],kind,uid=None if kind=='location' else uuid4(),
                              location=' No native location ' if kind=='location' else None)
                assert await conn.fetchval('SELECT count(*) FROM core.partner_clients WHERE id=$1',row['client_id']) == 0
                fks = await conn.fetch("""SELECT conrelid::regclass::text AS child,confrelid::regclass::text AS parent,
                    confdeltype::text AS deletion FROM pg_catalog.pg_constraint
                    WHERE contype='f' AND conrelid=ANY($1::regclass[])""", [PARENT,CHILD])
                assert len(fks)==2 and all(r['deletion']=='r' for r in fks)
            # Actual ORM INSERT/flush and new-session materialisation of both
            # mappings, independently of the literal SQL checks above.
            orm_values = {**row, 'result': {'synthetic':'snapshot'}}
            child_id, resource_id = uuid4(), uuid4()
            async with w.factory() as db:
                parent = PartnerContractCycleReceipt(**orm_values)
                db.add(parent)
                await db.flush()
                db.add(PartnerContractCycleReceiptRef(id=child_id,receipt_id=parent.id,
                    kind='site',uuid_value=resource_id))
                await db.commit()
            async with w.factory() as db:
                saved = await db.get(PartnerContractCycleReceipt,row['id'])
                saved_ref = await db.get(PartnerContractCycleReceiptRef,child_id)
                assert all(getattr(saved,key)==value for key,value in orm_values.items())
                assert saved.created_txid and saved.created_at
                assert (saved_ref.receipt_id,saved_ref.kind,saved_ref.uuid_value,saved_ref.location_value) == (
                    row['id'],'site',resource_id,None)
            return
        if case == 'closed12-target-map':
            async with rollback(conn):
                for operation,target in TARGETS.items():
                    await receipt(conn,values(company,operation=operation,target_kind=target))
                    wrong = 'site' if target != 'site' else 'contract'
                    await reject_receipt(conn,values(company,operation=operation,target_kind=wrong))
                for operation in ('createContract','v2.contract.delete','', 'v2.contract.create '):
                    await reject_receipt(conn,values(company,operation=operation))
                assert await conn.fetchval('SELECT count(*) FROM '+PARENT) == 12
            return
        if case == 'strict-hash-versions':
            for change,code in [({'request_hash':'A'*64},'23514'),({'request_hash':'a'*63},'23514'),
                ({'request_hash':'g'*64},'23514'),({'request_hash':'a'*65},'23514'),
                ({'request_hash':'a'*64+' '},'23514'),
                ({'request_hash':'a'*64+'\n'},'23514'),
                ({'request_hash':'a'*63+' '},'23514'),({'hash_version':0},'23514'),
                ({'hash_version':2},'23514'),({'operation_version':1},'23514'),
                ({'operation_version':3},'23514'),({'client_id':''},'23514')]:
                await reject_receipt(conn,values(company,**change),codes=(code,))
            return
        if case == 'result-object':
            for result in ('[]','null','true','42','"text"'):
                await reject_receipt(conn,values(company,result=result))
            await reject_receipt(conn,values(company,result=None),codes=('23502',))
            async with rollback(conn):
                await receipt(conn,values(company,result='{"ok": true}'))
            return
        if case in {'ascii128KiB','multibyte128KiB'}:
            # PG JSONB renders {"x": "..."}: nine UTF8 framing bytes.
            payload = 'a'*(131072-9) if case=='ascii128KiB' else 'я'*((131072-10)//2)+'a'
            encoded = json.dumps({'x':payload},ensure_ascii=False)
            assert len(encoded.encode('utf-8')) == 131072
            async with rollback(conn):
                row = await receipt(conn,values(company,result=encoded))
                assert await conn.fetchval('SELECT octet_length(convert_to(result::text,\'UTF8\')) FROM '+PARENT+' WHERE id=$1',row['id']) == 131072
                await reject_receipt(conn,values(company,result=json.dumps({'x':payload+'a'},ensure_ascii=False)))
            return
        if case == 'typed-refs-xor':
            async with rollback(conn):
                row = await receipt(conn,values(company))
                for kind in KINDS:
                    await ref(conn,row['id'],kind,uid=None if kind=='location' else uuid4(),location='X' if kind=='location' else None)
                    await reject_ref(conn,row['id'],kind,None,None)
                    await reject_ref(conn,row['id'],kind,uuid4(),'X')
                    await reject_ref(conn,row['id'],kind,uuid4() if kind=='location' else None,None if kind=='location' else 'X')
                await reject_ref(conn,row['id'],'unknown',uuid4(),None)
                assert await conn.fetchval('SELECT count(*) FROM '+CHILD) == 8
            return
        if case == 'typed-refs-unique':
            async with rollback(conn):
                first, second = await receipt(conn,values(company)), await receipt(conn,values(company))
                uid = uuid4()
                for kind in ('site','contract'):
                    await ref(conn,first['id'],kind,uid)
                    await reject_ref(conn,first['id'],kind,uid,None,codes=('23505',))
                await ref(conn,second['id'],'site',uid)
                await ref(conn,first['id'],'location',location='X')
                await reject_ref(conn,first['id'],'location',None,'X',codes=('23505',))
            return
        if case == 'opaque-location40':
            async with rollback(conn):
                row = await receipt(conn,values(company))
                locations = (' '*40,' a ','a','A','Я'*40,'\t','X'*40)
                for location in locations:
                    saved = await ref(conn,row['id'],'location',location=location)
                    assert saved['location_value'] == location
                await reject_ref(conn,row['id'],'location',None,'')
                for too_long in ('Я'*41,' '*41,'X'*40+' '):
                    await reject_ref(conn,row['id'],'location',None,too_long)
                # PG text cannot represent NUL; use a server-side expression,
                # avoiding a client-codec ValueError masquerading as SQL proof.
                await reject(conn,'INSERT INTO '+CHILD+" (id,receipt_id,kind,location_value) VALUES ($1,$2,'location',chr(0))",
                             uuid4(),row['id'],codes=('54000',))
            return
        if case == 'db-owned-txid-time':
            async with rollback(conn):
                now = await conn.fetchval('SELECT transaction_timestamp()')
                txid = await conn.fetchval('SELECT pg_current_xact_id()::text')
                for supplied in ('forged',None,txid+'0'):
                    row = await receipt(conn,values(company,created_txid=supplied,created_at=None))
                    assert row['created_txid'] == txid and row['created_at'] == now
            return
        if case in {'parent-immutable','child-immutable','key-reuse-denied','restrict-retention'}:
            async with rollback(conn):
                original = values(company)
                row = await receipt(conn,original)
                child = await ref(conn,row['id'],'site',uuid4())
                before = await contents(conn)
                if case == 'parent-immutable':
                    for sql in ('UPDATE '+PARENT+" SET result='{}'::jsonb WHERE id=$1",'DELETE FROM '+PARENT+' WHERE id=$1'):
                        await reject(conn,sql,row['id'])
                    await reject(conn,'TRUNCATE TABLE '+PARENT+' CASCADE')
                elif case == 'child-immutable':
                    for sql in ('UPDATE '+CHILD+' SET uuid_value=uuid_value WHERE id=$1','DELETE FROM '+CHILD+' WHERE id=$1'):
                        await reject(conn,sql,child['id'])
                    await reject(conn,'TRUNCATE TABLE '+CHILD)
                elif case == 'key-reuse-denied':
                    await reject(conn,'DELETE FROM '+PARENT+' WHERE id=$1',row['id'])
                    await reject_receipt(conn,{**original,'id':uuid4()},codes=('23505',))
                else:
                    await reject(conn,'DELETE FROM core.companies WHERE id=$1',company,codes=('23503',))
                    actions = await conn.fetch("""SELECT confdeltype::text AS deletion FROM pg_catalog.pg_constraint
                        WHERE contype='f' AND conrelid=ANY($1::regclass[])""",[PARENT,CHILD])
                    assert len(actions)==2 and all(r['deletion']=='r' for r in actions)
                assert await contents(conn) == before
            return
        if case == 'same-topTX-savepoint':
            async with rollback(conn):
                top = await conn.fetchval('SELECT pg_current_xact_id()::text')
                async with conn.transaction():
                    row = await receipt(conn,values(company))
                    assert row['created_txid'] == top
                    await ref(conn,row['id'],'site',uuid4())
                async with conn.transaction():
                    await ref(conn,row['id'],'contract',uuid4())
                await ref(conn,row['id'],'location',location=' exact ')
                assert await conn.fetchval('SELECT count(*) FROM '+CHILD+' WHERE receipt_id=$1',row['id']) == 3
            return
        if case == 'laterTX-ref-denied':
            # Commit the original successful parent; then real distinct top TX.
            async with conn.transaction():
                row = await receipt(conn,values(company))
                await ref(conn,row['id'],'site',uuid4())
            before = await contents(conn)
            async with conn.transaction():
                assert await conn.fetchval('SELECT pg_current_xact_id()::text') != row['created_txid']
                await reject_ref(conn,row['id'],'contract',uuid4(),None)
            assert await contents(conn) == before
            return
        if case == 'atomic-malformed-rollback':
            original = values(company)
            before = await contents(conn), await history(conn)
            with pytest.raises(asyncpg.CheckViolationError):
                async with conn.transaction():
                    row = await receipt(conn,original)
                    await ref(conn,row['id'],'site',uuid4())
                    await ref(conn,row['id'],'location',uid=uuid4())
            assert (await contents(conn),await history(conn)) == before
            assert not await conn.fetchval('SELECT EXISTS(SELECT 1 FROM '+PARENT+' WHERE id=$1)',original['id'])
            async with rollback(conn):
                # A failed transaction did not reserve a success namespace.
                await receipt(conn,original)
            return
        raise AssertionError('Unimplemented finite case: '+case)
