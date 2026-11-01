"""SOURCE-only: two separately ROOT-admitted native epochs, never a CLI.

ROOT freezes both new files independently, supplies both private contracts and
terminates the historical process before starting the current one. This module
does not create contracts, archives, processes, namespaces or execution authority.
The existing three schema4 helpers and their current admission are unchanged.
"""
import ast
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

PROFILE = 'partner-contract-schema4-historical-v1'
CONTROLS = {
    'historical-prepare': Path('/test/control/partner-schema4-historical-approval.json'),
    'current-continue': Path('/test/control/partner-schema4-historical-current-approval.json'),
}
HELPERS = ('tests/partner_contract_schema_v4_historical.py',
           'tests/partner_contract_schema_v4_historical_sources.json')
TARGET = 'api_partner_contract_schema_v4_test_20261101'
EXACT_DSN = 'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/' + TARGET
HISTORICAL_COMMIT = 'ba9fc30be815a554cb0c646a6c75f59e17c19fb0'
HISTORICAL_MANIFEST = 'df9e52fc1f6c5a20c2dead7b81a4c957b3642afca4483f28ac3e416df5b445ab'
CURRENT_COMMIT = 'aaf472b8123bf1d01538049ef8b5308c9b72fd6b'
DTO_OVERLAY = 'be49c4e688c80b3d7c40aedc6b283b477732b01e'
CURRENT_MANIFEST = '040e2004298eecbc415d7d24c5c8ed783f3fe4c9e42676706b1bbaf8fe6bdc56'
_active = None
_scope = None
_UNSET = object()


_HIST_KEYS_SQL = """SELECT n.nspname,c.relname,k.oid::int AS constraint_oid,k.conname,
        k.contype::text AS kind,k.convalidated,k.confdeltype::text AS delete_action,
        tn.nspname AS target_schema,tc.relname AS target_table,
        ARRAY(SELECT a.attname::text FROM unnest(k.conkey) WITH ORDINALITY x(num,pos)
          JOIN pg_catalog.pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=x.num ORDER BY x.pos) AS columns,
        ARRAY(SELECT a.attname::text FROM unnest(k.confkey) WITH ORDINALITY x(num,pos)
          JOIN pg_catalog.pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=x.num ORDER BY x.pos) AS target_columns
        FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_catalog.pg_class tc ON tc.oid=k.confrelid
        LEFT JOIN pg_catalog.pg_namespace tn ON tn.oid=tc.relnamespace
        WHERE n.nspname IN ('core','edge') AND k.contype IN ('p','f') ORDER BY n.nspname,c.relname,k.conname"""
_HIST_TRIGGERS_SQL = """SELECT t.tgconstraint::int AS constraint_oid,t.tgname,
        t.tgenabled::text AS enabled,t.tgisinternal FROM pg_catalog.pg_trigger t
        JOIN pg_catalog.pg_constraint k ON k.oid=t.tgconstraint
        JOIN pg_catalog.pg_namespace n ON n.oid=k.connamespace
        WHERE n.nspname IN ('core','edge') AND k.contype='f' ORDER BY k.oid,t.tgname"""


def _require(value, reason):
    if not value:
        raise RuntimeError('schema4 historical fixture refused: ' + reason)


def _canonical(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=True).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def _file(path, *, private=False):
    _require(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)),
             'absolute nonsymlink path')
    info = path.stat()
    _require(stat.S_ISREG(info.st_mode), 'regular file')
    if private:
        for parent in path.parents:
            p = parent.stat()
            _require(p.st_uid == 0 and not p.st_mode & 0o022, 'ROOT-owned private ancestors')
        _require(info.st_uid == 0 and info.st_mode & 0o777 == 0o444,
                 'ROOT-owned mode0444 contract/receipt')
    return path.read_bytes()


def _lease(lease):
    _require(set(lease) == {'run_id', 'nonce', 'pid', 'process_start_ticks',
                           'issued_at', 'expires_at'}, 'lease shape')
    ticks = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]
    _require(type(lease['pid']) is int and lease['pid'] == os.getpid()
             and lease['process_start_ticks'] == ticks, 'lease process identity')
    _require(isinstance(lease['run_id'], str) and len(lease['run_id']) >= 16
             and isinstance(lease['nonce'], str) and len(lease['nonce']) >= 32, 'lease nonce')
    now = time.time()
    _require(type(lease['issued_at']) in (int, float)
             and type(lease['expires_at']) in (int, float)
             and lease['issued_at'] <= now < lease['expires_at']
             and 0 < lease['expires_at'] - lease['issued_at'] <= 1800, 'live bounded lease')


def _verify_files(root, rows, *, whole_app):
    _require(root.is_absolute() and root.is_dir()
             and not any(p.is_symlink() for p in (root, *root.parents)), 'source root')
    entries = []
    for directory in (('app',) if whole_app else ('app', 'schema_migrations')):
        for path in sorted((root / directory).rglob('*')):
            _require(not path.is_symlink() and path.name != '__pycache__'
                     and path.suffix not in {'.pyc', '.pyo'}
                     and not path.name.startswith('.env'), 'source path/cache/dotenv')
            if path.is_file() and (whole_app or path.suffix in {'.py', '.sql', '.json', '.yml', '.yaml'}):
                raw = _file(path)
                entries.append([str(path.relative_to(root)), len(raw), _sha(raw)])
    _require(sorted(entries) == rows, 'complete epoch source/assets differ')


def _admit(phase):
    """Strict validation only; ROOT externally writes/seals every contract byte."""
    global _active
    _require(phase in CONTROLS and sys.version_info[:2] == (3, 13)
             and not sys.flags.optimize and sys.dont_write_bytecode, 'phase/Python3.13')
    raw = _file(CONTROLS[phase], private=True)
    _require(len(raw) <= 32768, 'bounded contract')
    contract = json.loads(raw, object_pairs_hook=_unique)
    _require(set(contract) == {'profile', 'phase', 'source_root', 'working_directory',
        'execution_closure', 'historical_source', 'current_source', 'target', 'run_lease',
        'disposable_namespace', 'runtime_seconds', 'historical_preparation'}, 'contract shape')
    _require(contract['profile'] == PROFILE and contract['phase'] == phase, 'distinct ROOT profile/phase')
    _lease(contract['run_lease'])
    helper_root = Path(__file__).resolve().parents[1]
    _require(set(contract['execution_closure']) == set(HELPERS), 'separately ROOT-pinned new closure')
    for name in HELPERS:
        data = _file(helper_root / name)
        _require(contract['execution_closure'][name] == {'sha256': _sha(data), 'bytes': len(data)},
                 'ROOT-reviewed helper/source bytes')
    sources = json.loads(_file(helper_root / HELPERS[1]), object_pairs_hook=_unique)
    h, c = sources['historical'], sources['current']
    _require(h['commit'] == HISTORICAL_COMMIT and h['manifest_sha256'] == HISTORICAL_MANIFEST
             and h['file_count'] == len(h['files']) == 498
             and h['bytes'] == sum(row[1] for row in h['files']) == 17153808
             and _sha(_canonical(h['files'])) == HISTORICAL_MANIFEST, 'historical Git source pin')
    _require(c['app_commit'] == CURRENT_COMMIT and c['dto_overlay_commit'] == DTO_OVERLAY
             and c['immutable_sha256'] == CURRENT_MANIFEST
             and c['immutable_file_count'] == len(c['immutable_files']) == 535
             and c['immutable_bytes'] == sum(row[1] for row in c['immutable_files']) == 14634482
             and _sha(_canonical(c['immutable_files'])) == CURRENT_MANIFEST, 'unchanged current535/source pair')
    _require(len(h['models']) == 334 and _sha(_canonical(h['models'])) == h['registry_sha256']
             == '62467fdd0b55dd7817b198e4e6b25cb1182092beea273f7e20f35eb2246ba59d'
             and len(c['models']) == 341 and _sha(_canonical(c['models'])) == c['registry_sha256']
             == 'd865202f524ccd2b43d48d05a931cfea8e42316e3aba982fbec80642594fb52a',
             'separate complete epoch registries')
    _require(contract['historical_source'] == {'commit': HISTORICAL_COMMIT,
        'manifest_sha256': HISTORICAL_MANIFEST, 'files': 498, 'bytes': 17153808}, 'historical contract binding')
    _require(contract['current_source'] == {'app_commit': CURRENT_COMMIT, 'dto_overlay_commit': DTO_OVERLAY,
        'immutable_sha256': CURRENT_MANIFEST, 'files': 535, 'bytes': 14634482}, 'current contract binding')
    root = Path(contract['source_root'])
    _require(contract['working_directory'] == str(Path.cwd()) and not Path('.env').exists()
             and not (root / '.env').exists() and os.getuid() != 0, 'synthetic cwd/nonroot')
    _require(os.environ.get('DATABASE_URL') == EXACT_DSN
             and os.environ.get('TEST_DATABASE_URL') == EXACT_DSN
             and os.environ.get('APP_ENV') == 'test'
             and os.environ.get('MANAGED_CORE_BUDGET_ENABLED') == ('false' if phase == 'historical-prepare' else 'true')
             and os.environ.get('MANAGED_CORE_BUDGET_EXPECTED_DATABASE') == TARGET
             and os.environ.get('MANAGED_CORE_BUDGET_EXPECTED_USER') == 'clearledger', 'exact phase environment')
    _require(not any(k in os.environ for k in ('PYTHONPATH', 'PYTHONHOME', 'PGHOST', 'PGPORT',
        'PGDATABASE', 'PGUSER', 'PGPASSWORD', 'PGSERVICE', 'PGSERVICEFILE', 'PGPASSFILE')), 'no target/import fallback')
    target = contract['target']
    _require(set(target) == {'database', 'user', 'host', 'port', 'database_oid', 'role_oid', 'core_oid', 'edge_oid'}
             and (target['database'], target['user'], target['host'], target['port'])
             == (TARGET, 'clearledger', '127.0.0.1', 33546)
             and all(type(target[k]) is int and target[k] > 0
                     for k in ('database_oid', 'role_oid', 'core_oid', 'edge_oid')), 'exact target/OIDs')
    ns = contract['disposable_namespace']
    _require(set(ns) == {'container_id', 'published_ports', 'source_read_only', 'independently_verified_by_root'}
             and isinstance(ns['container_id'], str) and re.fullmatch('[0-9a-f]{64}', ns['container_id'])
             and ns['published_ports'] == [] and ns['source_read_only'] is True
             and ns['independently_verified_by_root'] is True, 'ROOT disposable/RO attestation')
    _require(type(contract['runtime_seconds']) is int and 1 <= contract['runtime_seconds'] <= 1200,
             'bounded ROOT runtime')
    if phase == 'historical-prepare':
        _require(contract['historical_preparation'] is None, 'historical fresh-only phase')
        _verify_files(root, h['files'], whole_app=True)
    else:
        _require(root == helper_root, 'current original helper origin')
        _verify_files(root, c['immutable_files'], whole_app=False)
    if _active is None:
        _require(not any(name == 'app' or name.startswith(('app.', 'schema_migrations', 'sqlalchemy', 'asyncpg'))
                         for name in sys.modules), 'admission before any runtime imports')
    else:
        _require(contract == _active, 'contract/phase changed during process')
    if _active is None:
        _active = contract
    if _scope is not None:
        return _scope['contract'], _scope['sources'], _scope['root']
    return _active, sources, root


def _live(*phases, conn=_UNSET, database=_UNSET, world=_UNSET, root=_UNSET, sources=_UNSET,
          contract=_UNSET, target=True):
    """No admission, imports or caller callbacks: only an already owned LIVE phase.

    A private contract validator is not an activation API. Only the two public
    context owners install _scope, bind their own objects and revoke it in finally.
    The first checks deliberately precede even proc/file/origin inspection.
    """
    scope = _scope
    _require(scope is not None and _active is scope['contract']
             and scope['phase'] in phases, 'no owned live runtime phase')
    lease = scope['contract']['run_lease']
    now = time.time()
    _require(lease['issued_at'] <= now < lease['expires_at'], 'expired/not-yet-live runtime lease')
    _require(scope['task'] is asyncio.current_task(), 'foreign runtime task')
    _require(contract is _UNSET or contract is scope['contract'], 'foreign contract')
    _require(conn is _UNSET or conn is scope['conn'], 'foreign connection')
    _require(database is _UNSET or database is scope['database'], 'foreign database')
    _require(root is _UNSET or root is scope['root'], 'foreign source root')
    _require(sources is _UNSET or sources is scope['sources'], 'foreign source arrays')
    if world is not _UNSET:
        _require(world is not None and world is scope['world'] and world['conn'] is scope['conn']
                 and world['config'] is scope['config'] and world['w'] is scope['w'], 'foreign world objects')
    _lease(lease)
    if conn is not _UNSET:
        _require(type(conn) is sys.modules['asyncpg'].Connection, 'actual owned asyncpg connection')
    if database is not _UNSET:
        _module_path = getattr(database, '__file__', None)
        _require(_module_path is not None and Path(_module_path).resolve() == scope['root'] / 'app/database.py',
                 'actual database source origin')
    if target:
        _require(scope['target_verified'] and scope['conn'] is not None
                 and not scope['conn'].is_closed(), 'actual owned target not verified')
    if database is not _UNSET:
        _require(database is sys.modules.get('app.database')
                 and database.settings.database_url == EXACT_DSN
                 and str(database.engine.url) == EXACT_DSN.replace('api_test_only', '***')
                 and database.async_session_factory.kw['bind'] is database.engine,
                 'actual epoch database/session engine binding')
    historical = scope['phase'] == 'historical-prepare'
    for name, module in tuple(sys.modules.items()):
        if historical:
            _require(not name.startswith('schema_migrations'), 'historical phase never loads current owners')
        if name == 'app' or name.startswith('app.') or name == 'schema_migrations' or name.startswith('schema_migrations.'):
            path = getattr(module, '__file__', None)
            expected = scope['root'].joinpath(*name.split('.'))
            if path is None:
                spec = getattr(module, '__spec__', None)
                # The pinned current archive has exactly this PEP420 package;
                # do not permit arbitrary namespace packages or path overlays.
                _require(not historical and name == 'schema_migrations.bootstrap'
                         and expected.is_dir() and not expected.is_symlink()
                         and expected.resolve() == expected
                         and not (expected / '__init__.py').exists()
                         and list(getattr(module, '__path__', ())) == [str(expected)]
                         and spec is not None and spec.origin is None
                         and list(spec.submodule_search_locations or ()) == [str(expected)],
                         'whole epoch namespace origin: ' + name)
                continue
            _require(path is not None and Path(path).resolve() in
                     {expected.with_suffix('.py'), expected / '__init__.py'}, 'whole epoch runtime origins: ' + name)
    if not historical:
        # The original no-I/O active guard rechecks its independently admitted
        # lease. Full current535/budgetTRUE/closure3 validation still occurs at
        # every public phase API through require_running_approval, unchanged.
        scope['original_guard']()
    return scope


def _origins(root, *, historical):
    _live('historical-prepare' if historical else 'current-continue', root=root, target=False)


async def _identity(conn, contract):
    scope = _live('historical-prepare', 'current-continue', conn=conn, contract=contract, target=False)
    row = await conn.fetchrow("""SELECT current_database() AS database,current_user AS usr,
        current_schema() AS ns,current_setting('search_path') AS path,
        current_setting('server_version_num')::int AS version,
        current_setting('session_replication_role') AS replication,
        pg_catalog.host(inet_server_addr()) AS host,inet_server_port() AS port,
        d.oid::int AS database_oid,r.oid::int AS role_oid,
        r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,r.rolbypassrls,
        n.oid::int AS core_oid,n.nspowner::int AS core_owner,
        e.oid::int AS edge_oid,e.nspowner::int AS edge_owner
        FROM pg_catalog.pg_database d JOIN pg_catalog.pg_roles r ON r.rolname=current_user
        JOIN pg_catalog.pg_namespace n ON n.nspname='core'
        JOIN pg_catalog.pg_namespace e ON e.nspname='edge' WHERE d.datname=current_database()""")
    _require(row is not None and (row['database'], row['usr'], row['ns'], row['path'], row['host'], row['port'])
             == (TARGET, 'clearledger', 'core', 'core', '127.0.0.1', 33546), 'actual exact PG target')
    _require(160000 <= row['version'] < 170000 and row['replication'] == 'origin'
             and all(not row[k] for k in ('rolsuper', 'rolcreatedb', 'rolcreaterole', 'rolreplication', 'rolbypassrls')),
             'native PG16 constraints/nonadmin')
    _require(all(row[k] == contract['target'][k] for k in ('database_oid', 'role_oid', 'core_oid', 'edge_oid'))
             and row['core_owner'] == row['edge_owner'] == row['role_oid'], 'actual ROOT-attested OIDs/owners')
    extensions = await conn.fetch("""SELECT e.extname,n.nspname FROM pg_catalog.pg_extension e
        JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace
        WHERE e.extname IN ('btree_gist','pgcrypto','uuid-ossp')""")
    _require({r['extname'] for r in extensions} == {'btree_gist', 'pgcrypto', 'uuid-ossp'}
             and all(r['nspname'] != 'core' for r in extensions), 'ROOT-prepared native extensions')
    scope['target_verified'] = True
    return dict(row)


async def _no_managed_history(conn, *, empty=False):
    _live('historical-prepare', 'current-continue', conn=conn)
    if empty:
        _require(not await conn.fetchval("""SELECT EXISTS(
            SELECT 1 FROM pg_catalog.pg_depend d WHERE d.refclassid='pg_namespace'::regclass
            AND d.classid<>'pg_default_acl'::regclass AND d.refobjid IN
              (SELECT oid FROM pg_catalog.pg_namespace WHERE nspname IN ('core','edge')))"""),
                 'new empty core/edge; no reset')
    _require(not await conn.fetchval("""SELECT to_regclass('core.core_schema_versions') IS NOT NULL
        OR to_regclass('core.pulse_view_role_grants') IS NOT NULL"""), 'historical prefix0 absent managed history/Pulse')
    if not empty:
        _require(not await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_attribute
            WHERE attrelid='core.calendar_events'::regclass AND attname='protocol_sequence' AND NOT attisdropped)"""),
                 'actual historical calendar has no managed column')


def _registry(root):
    rows = []
    for path in sorted((root / 'app').rglob('*.py')):
        for node in ast.parse(path.read_bytes()).body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__tablename__'
                                                          for t in item.targets):
                        rel = str(path.relative_to(root))
                        rows.append([rel, rel[:-3].replace('/', '.') + '.' + node.name, ast.literal_eval(item.value)])
    return rows


async def historical_catalogue(conn, database, sources, root):
    _live('historical-prepare', conn=conn, database=database, sources=sources, root=root)
    """All historical models and physical native FKs, never a projected parent set."""
    epoch = sources['historical']
    models = _registry(root)
    _require(models == epoch['models'] and _sha(_canonical(models)) == epoch['registry_sha256'],
             'complete historical source registry')
    _origins(root, historical=True)
    mappers = sorted((m.class_.__module__ + '.' + m.class_.__name__, m.local_table.name)
                     for m in database.Base.registry.mappers)
    _require(mappers == sorted((r[1], r[2]) for r in models), 'all334 actual historical mappers')
    metadata = {(t.schema or 'core', t.name): t for t in database.Base.metadata.tables.values()}
    _require(len(metadata) == len(models), 'all334 metadata tables')
    wanted = set(metadata) | {tuple(r) for r in epoch['raw_tables']}
    relations = await conn.fetch("""SELECT n.nspname,c.relname,c.oid::int AS oid,c.relkind::text AS kind,
        pg_catalog.pg_get_userbyid(c.relowner) AS owner FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('core','edge') AND c.relkind IN ('r','p','f','v','m')
        ORDER BY n.nspname,c.relname""")
    _require({(r['nspname'], r['relname']) for r in relations} == wanted
             and all(r['kind'] == 'r' and r['owner'] == 'clearledger' for r in relations), 'exact full historical physical tables/owners')
    columns = await conn.fetch("""SELECT n.nspname,c.relname,a.attname,
        pg_catalog.format_type(a.atttypid,a.atttypmod) AS type,a.attnotnull
        FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('core','edge') AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY n.nspname,c.relname,a.attnum""")
    keys = await conn.fetch(_HIST_KEYS_SQL)
    triggers = await conn.fetch(_HIST_TRIGGERS_SQL)
    _require(all(r['convalidated'] for r in keys)
             and all(t['enabled'] in ('O', 'A') and t['tgisinternal'] for t in triggers), 'native validated PK/FK/RI')
    actual_fks = {(r['nspname'], r['relname'], tuple(r['columns']), r['target_schema'], r['target_table'],
                   tuple(r['target_columns']), r['delete_action']) for r in keys if r['kind'] == 'f'}
    expected_fks = set()
    actions = {None: 'a', 'NO ACTION': 'a', 'CASCADE': 'c', 'SET NULL': 'n', 'RESTRICT': 'r', 'SET DEFAULT': 'd'}
    for key, table in metadata.items():
        found = {r['attname'] for r in columns if (r['nspname'], r['relname']) == key}
        _require(set(table.columns.keys()) <= found, 'all historical mapped columns: ' + repr(key))
        primary = [tuple(r['columns']) for r in keys if (r['nspname'], r['relname']) == key and r['kind'] == 'p']
        _require(primary == [tuple(c.name for c in table.primary_key.columns)], 'historical native PK: ' + repr(key))
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            refs = [e.target_fullname.split('.') for e in elements]
            namespace = refs[0][-3] if len(refs[0]) == 3 else 'core'
            expected_fks.add((*key, tuple(e.parent.name for e in elements), namespace,
                             refs[0][-2], tuple(r[-1] for r in refs), actions[constraint.ondelete]))
    _require(expected_fks <= actual_fks, 'every historical mapped FK/action')
    _require(all(sum(t['constraint_oid'] == r['constraint_oid'] for t in triggers) == 4
                 for r in keys if r['kind'] == 'f'), 'four native RI triggers per actual FK')
    return {'source_registry_sha256': epoch['registry_sha256'], 'models': models,
            'tables': [dict(r) for r in relations], 'columns': [dict(r) for r in columns],
            'primary_and_foreign_keys': [dict(r) for r in keys], 'ri_triggers': [dict(r) for r in triggers],
            'native_extra_fks': sorted(actual_fks - expected_fks)}


async def _all_orm_selects(database):
    _live('historical-prepare', 'current-continue', database=database)
    from sqlalchemy import select
    checked = []
    async with database.async_session_factory() as session:
        for mapper in sorted(database.Base.registry.mappers, key=lambda m: m.class_.__module__ + '.' + m.class_.__name__):
            # Executes SELECT of every real mapped column, including empty tables.
            # Materialisation of populated native parents is checked separately.
            (await session.scalars(select(mapper.class_).limit(1))).first()
            checked.append(mapper.class_.__module__ + '.' + mapper.class_.__name__)
    return checked


async def _native_snapshot(conn):
    _live('historical-prepare', 'current-continue', conn=conn)
    """Full native catalogue capture for all core/edge objects, not ten parents."""
    queries = {
        'relations': """SELECT c.oid::int,n.nspname,c.relname,c.relkind::text,c.relpersistence::text,
            c.relowner::int,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity,c.reloptions,
            c.reltablespace::int,c.relreplident::text,c.reltoastrelid::int FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('core','edge') ORDER BY n.nspname,c.relname""",
        'attributes': """SELECT n.nspname,c.relname,a.attnum,a.attname,a.atttypid::int,a.atttypmod,
            a.attnotnull,a.attidentity::text,a.attgenerated::text,a.attisdropped,a.attcollation::int,
            a.attacl::text,pg_catalog.pg_get_expr(d.adbin,d.adrelid,false) AS default_expr
            FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
            WHERE n.nspname IN ('core','edge') AND c.relkind='r' AND a.attnum>0
            ORDER BY n.nspname,c.relname,a.attnum""",
        'constraints': """SELECT k.oid::int,n.nspname,c.relname,k.conname,k.contype::text,
            k.convalidated,k.condeferrable,k.condeferred,k.conislocal,k.coninhcount,
            k.confrelid::int,k.conindid::int,k.conkey,k.confkey,k.confdeltype::text,
            k.confupdtype::text,k.confmatchtype::text,k.confdelsetcols,
            pg_catalog.pg_get_constraintdef(k.oid,false) AS definition
            FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('core','edge') ORDER BY n.nspname,c.relname,k.conname""",
        'indexes': """SELECT n.nspname,c.relname,i.indexrelid::int,i.indrelid::int,
            i.indisunique,i.indisprimary,i.indisvalid,i.indisready,i.indislive,
            i.indimmediate,i.indisreplident,i.indnullsnotdistinct,
            pg_catalog.pg_get_indexdef(i.indexrelid) AS definition
            FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('core','edge') ORDER BY n.nspname,c.relname""",
        'triggers': """SELECT t.oid::int,n.nspname,c.relname,t.tgname,t.tgconstraint::int,
            t.tgtype,t.tgfoid::int,pn.nspname AS function_schema,p.proname AS function_name,
            pg_catalog.pg_get_function_identity_arguments(p.oid) AS function_arguments,
            t.tgconstrrelid::int,t.tgenabled::text,t.tgisinternal,t.tgdeferrable,t.tginitdeferred,
            pg_catalog.pg_get_triggerdef(t.oid,false) AS definition
            FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
            JOIN pg_catalog.pg_namespace pn ON pn.oid=p.pronamespace
            WHERE n.nspname IN ('core','edge') ORDER BY n.nspname,c.relname,t.tgname""",
        'functions': """SELECT p.oid::int,n.nspname,p.proname,p.proowner::int,p.proacl::text,
            p.prokind::text,pg_catalog.pg_get_function_identity_arguments(p.oid) AS arguments,
            CASE WHEN p.prokind IN ('f','p') THEN pg_catalog.pg_get_functiondef(p.oid) END AS definition FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname IN ('core','edge') ORDER BY p.oid""",
        'types': """SELECT t.oid::int,n.nspname,t.typname,t.typtype::text,t.typowner::int,
            t.typacl::text,t.typrelid::int,t.typelem::int,t.typarray::int
            FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
            WHERE n.nspname IN ('core','edge') ORDER BY n.nspname,t.typname""",
        'sequences': """SELECT q.seqrelid::int,n.nspname,c.relname,c.relowner::int,
            q.seqtypid::int,q.seqstart,q.seqincrement,q.seqmax,q.seqmin,q.seqcache,q.seqcycle
            FROM pg_catalog.pg_sequence q JOIN pg_catalog.pg_class c ON c.oid=q.seqrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('core','edge') ORDER BY n.nspname,c.relname""",
        'dependencies': """WITH objects(classid,objid,objsubid,address) AS (
            SELECT 'pg_catalog.pg_namespace'::regclass,n.oid,0,ARRAY['namespace',n.nspname::text]
              FROM pg_catalog.pg_namespace n
            UNION ALL SELECT 'pg_catalog.pg_class'::regclass,c.oid,0,
                ARRAY['relation',n.nspname::text,c.relname::text]
              FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            UNION ALL SELECT 'pg_catalog.pg_class'::regclass,c.oid,a.attnum,
                ARRAY['column',n.nspname::text,c.relname::text,a.attname::text]
              FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
              JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum>0
            UNION ALL SELECT 'pg_catalog.pg_type'::regclass,t.oid,0,
                ARRAY['type',n.nspname::text,t.typname::text]
              FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
            UNION ALL SELECT 'pg_catalog.pg_constraint'::regclass,k.oid,0,
                ARRAY['constraint',n.nspname::text,c.relname::text,k.conname::text]
              FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_namespace n ON n.oid=k.connamespace
              JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
            UNION ALL SELECT 'pg_catalog.pg_attrdef'::regclass,d.oid,0,
                ARRAY['default',n.nspname::text,c.relname::text,a.attname::text]
              FROM pg_catalog.pg_attrdef d JOIN pg_catalog.pg_class c ON c.oid=d.adrelid
              JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
              JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum=d.adnum
            UNION ALL SELECT 'pg_catalog.pg_trigger'::regclass,t.oid,0,
                ARRAY['trigger',n.nspname::text,c.relname::text,t.tgname::text]
              FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
              JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            UNION ALL SELECT 'pg_catalog.pg_proc'::regclass,p.oid,0,
                ARRAY['function',n.nspname::text,p.proname::text,pg_catalog.pg_get_function_identity_arguments(p.oid)]
              FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            UNION ALL SELECT 'pg_catalog.pg_language'::regclass,l.oid,0,ARRAY['language',l.lanname::text]
              FROM pg_catalog.pg_language l
            ) SELECT d.classid::int,d.objid::int,d.objsubid,d.refclassid::int,d.refobjid::int,
                d.refobjsubid,d.deptype::text,
                coalesce(o.address,ARRAY['unclassified',d.classid::text,d.objid::text,d.objsubid::text]) AS dependent,
                coalesce(r.address,ARRAY['unclassified',d.refclassid::text,d.refobjid::text,d.refobjsubid::text]) AS referenced
              FROM pg_catalog.pg_depend d
              LEFT JOIN objects o ON (o.classid,o.objid,o.objsubid)=(d.classid,d.objid,d.objsubid)
              LEFT JOIN objects r ON (r.classid,r.objid,r.objsubid)=(d.refclassid,d.refobjid,d.refobjsubid)
              WHERE o.address[2] IN ('core','edge') OR r.address[2] IN ('core','edge')
              ORDER BY d.classid,d.objid,d.objsubid,d.refclassid,d.refobjid,d.refobjsubid,d.deptype""",
    }
    # Immutable definitions only. last_value/is_called are deliberately absent:
    # legitimate native nextval changes counters, never these pg_sequence rows.
    return {name: [dict(row) for row in await conn.fetch(sql)] for name, sql in queries.items()}


def _mapped_metadata(database):
    _live('historical-prepare', 'current-continue', database=database)
    """Record actual full metadata columns/types/defaults/keys alongside PG data."""
    from sqlalchemy.dialects import postgresql
    dialect = postgresql.dialect()
    result = []
    for mapper in sorted(database.Base.registry.mappers, key=lambda m: m.class_.__module__ + '.' + m.class_.__name__):
        table = mapper.local_table
        result.append({'model': mapper.class_.__module__ + '.' + mapper.class_.__name__,
            'schema': table.schema or 'core', 'table': table.name,
            'columns': [{'name': c.name, 'type': c.type.compile(dialect=dialect),
                'nullable': c.nullable, 'primary_key': c.primary_key,
                'server_default': (str(c.computed.sqltext) if c.computed is not None else
                    str(c.server_default.arg) if c.server_default is not None else None),
                'computed': c.computed is not None}
                for c in table.columns],
            'foreign_keys': sorted([list(e.parent.name for e in fk.elements),
                list(e.target_fullname for e in fk.elements), fk.ondelete or 'NO ACTION']
                for fk in table.foreign_key_constraints),
            'constraints': sorted([type(c).__name__, c.name or '', str(getattr(c, 'sqltext', '')),
                list(c.columns.keys())] for c in table.constraints),
            'indexes': sorted([i.name, i.unique, [str(e) for e in i.expressions]] for i in table.indexes)})
    return result


async def historical_prepare():
    """Phase1 API. Return evidence to ROOT; ROOT persists it and ends this process."""
    global _scope
    _require(_scope is None, 'runtime owner already active')
    contract, sources, root = _admit('historical-prepare')
    _scope = {'phase': 'historical-prepare', 'contract': contract, 'sources': sources,
              'root': root, 'task': asyncio.current_task(), 'conn': None, 'database': None,
              'world': None, 'config': None, 'w': None, 'target_verified': False}
    conn, database = None, None
    try:
        _live('historical-prepare', target=False)
        import asyncpg
        async with asyncio.timeout(contract['runtime_seconds']):
            conn = await asyncpg.connect(EXACT_DSN.replace('postgresql+asyncpg:', 'postgresql:', 1),
                timeout=5, command_timeout=120, server_settings={'search_path': 'core'})
            _scope['conn'] = conn
            identity = await _identity(conn, contract)
            await _no_managed_history(conn, empty=True)
            _live('historical-prepare')
            from app import database, main
            _scope['database'] = database
            _origins(root, historical=True)
            _require(main.create_all is database.create_all and database.settings.database_url == EXACT_DSN
                     and database.settings.managed_core_budget_enabled is False
                     and main.settings.app_env == 'test', 'actual historical native startup composition/OFF')
            _live('historical-prepare', database=database)
            async with database.database_startup_lock():
                _live('historical-prepare', database=database)
                await _identity(conn, contract)
                await database.create_all()
            await _no_managed_history(conn)
            coverage = await historical_catalogue(conn, database, sources, root)
            w = await _populate(database)
            _scope['w'] = w
            await _read_parents(database, w)
            selects = await _all_orm_selects(database)
            whole_catalogue = await _native_snapshot(conn)
            mapped_metadata = _mapped_metadata(database)
            await _no_managed_history(conn)
            _admit('historical-prepare')
            lease = contract['run_lease']
            return {'format': 1, 'status': 'HISTORICAL_PREPARED_NOT_CURRENT_ACCEPTED',
                'phase': 'historical-prepare', 'historical_commit': HISTORICAL_COMMIT,
                'historical_manifest_sha256': HISTORICAL_MANIFEST,
                'current_app_commit': CURRENT_COMMIT, 'dto_overlay_commit': DTO_OVERLAY,
                'execution_closure': contract['execution_closure'],
                'target': contract['target'], 'identity': identity,
                'process': {k: lease[k] for k in ('run_id', 'nonce', 'pid', 'process_start_ticks')},
                'prefix': 0, 'w': {k: str(v) for k, v in w.items()}, 'native': coverage,
                'whole_catalogue': whole_catalogue, 'mapped_metadata': mapped_metadata,
                'orm_selects': selects, 'native_parent_orm_readback': True,
                'seed_or_lifespan_called': False, 'current_create_all_called': False}
    finally:
        try:
            owned_database = database if database is not None else sys.modules.get('app.database')
            if owned_database is not None:
                await owned_database.engine.dispose()
        finally:
            try:
                if conn is not None:
                    await conn.close(timeout=2)
            finally:
                _scope = None


def _historical_receipt(contract):
    _live('current-continue', contract=contract, target=False)
    seal = contract['historical_preparation']
    _require(isinstance(seal, dict) and set(seal) == {'path', 'sha256', 'bytes', 'process', 'process_exited'}
             and seal['process_exited'] is True, 'ROOT-attested old process exit/receipt')
    raw = _file(Path(seal['path']), private=True)
    _require(type(seal['bytes']) is int and len(raw) == seal['bytes'] <= 32 * 1024 * 1024
             and _sha(raw) == seal['sha256'], 'ROOT-sealed actual historical result')
    receipt = json.loads(raw, object_pairs_hook=_unique)
    _require(receipt['format'] == 1 and receipt['status'] == 'HISTORICAL_PREPARED_NOT_CURRENT_ACCEPTED'
             and receipt['phase'] == 'historical-prepare' and receipt['prefix'] == 0
             and receipt['historical_commit'] == HISTORICAL_COMMIT
             and receipt['historical_manifest_sha256'] == HISTORICAL_MANIFEST
             and receipt['current_app_commit'] == CURRENT_COMMIT and receipt['dto_overlay_commit'] == DTO_OVERLAY
             and receipt['execution_closure'] == contract['execution_closure']
             and receipt['target'] == contract['target'] and receipt['process'] == seal['process']
             and receipt['native_parent_orm_readback'] is True
             and receipt['seed_or_lifespan_called'] is False and receipt['current_create_all_called'] is False,
             'actual paired historical result')
    old = seal['process']
    _require(set(old) == {'run_id', 'nonce', 'pid', 'process_start_ticks'}
             and type(old['pid']) is int and old['pid'] > 0
             and old['run_id'] != contract['run_lease']['run_id']
             and old['nonce'] != contract['run_lease']['nonce'], 'independent phase lease')
    # ROOT's positive exit attestation is authoritative; local PID reuse must not
    # accidentally admit an observable still-live historical process either.
    proc = Path('/proc') / str(old['pid']) / 'stat'
    if proc.exists():
        _require(proc.read_text().rsplit(')', 1)[1].split()[19] != old['process_start_ticks'], 'historical process still live')
    if 'receipt' not in _scope:
        _scope['receipt'] = receipt
    _require(receipt == _scope['receipt'], 'historical receipt changed during phase')
    return _scope['receipt']


def _world_ids(receipt):
    raw = receipt['w']
    uuids = ('company', 'app', 'installation', 'grant', 'user', 'organization', 'counterparty', 'contract', 'contract_location')
    _require(set(raw) == {*uuids, 'client', 'location', 'type_code'}, 'native parent identity shape')
    _require(raw['client'] == 'schema4-native-client' and raw['location'] == 'schema4-native-location'
             and raw['type_code'] == 'schema4_native_test', 'synthetic native text identities')
    return {**raw, **{k: uuid.UUID(raw[k]) for k in uuids}}


async def _read_parents(database, w):
    scope = _live('historical-prepare', 'current-continue', database=database)
    _require(w is scope['w'], 'owned native identities')
    from sqlalchemy import text
    from app.models import (App, Company, CompanyApp, Contract, ContractLocation,
                            Counterparty, Organization, ServiceLocation, User, UserCompany)
    from app.models_partner import PartnerClient, PartnerGrant, PartnerInstallation, PartnerInstallationLocation
    expected = {
        'company': {'slug': 'schema4-native', 'profile_id': 'energy'},
        'app': {'code': 'schema4_native'},
        'installation': {'company_id': w['company'], 'app_id': w['app'], 'enabled': True},
        'grant': {'installation_id': w['installation'], 'client_id': w['client'], 'company_id': w['company'],
                  'kind': 'machine', 'user_id': None, 'approved': True},
        'user': {'company_id': w['company'], 'email': 'schema4@example.invalid'},
        'organization': {'company_id': w['company'], 'inn': '0000000000'},
        'counterparty': {'company_id': w['company']},
        'contract': {'company_id': w['company'], 'organization_id': w['organization'],
                     'counterparty_id': w['counterparty'], 'creation_actor_id': w['user'],
                     'type_code': w['type_code'], 'number': 'SYNTHETIC-SCHEMA4', 'date': '2026-11-01'},
        'contract_location': {'company_id': w['company'], 'contract_id': w['contract'], 'location_id': w['location']},
        'client': {'app_id': w['app'], 'owner_company_id': w['company'], 'enabled': True},
        'location': {'company_id': w['company'], 'code': 'schema4-native'},
    }
    async with database.async_session_factory() as session:
        for key, model in (('company', Company), ('app', App), ('installation', CompanyApp),
                           ('grant', PartnerGrant), ('user', User), ('organization', Organization),
                           ('counterparty', Counterparty), ('contract', Contract),
                           ('contract_location', ContractLocation), ('client', PartnerClient), ('location', ServiceLocation)):
            row = await session.get(model, w[key])
            _require(row is not None and row.id == w[key], 'committed actual current native parent: ' + key)
            _require(all(getattr(row, field) == value for field, value in expected[key].items()),
                     'committed native mapped values/relations: ' + key)
        install = await session.get(PartnerInstallation, w['installation'])
        _require(install is not None and (install.client_id, install.company_id) == (w['client'], w['company']), 'native installation tuple')
        _require(await session.get(UserCompany, (w['user'], w['company'])) is not None, 'native membership')
        _require(await session.get(PartnerInstallationLocation, (w['installation'], w['location'])) is not None, 'native installation location')
        _require(await session.scalar(text('SELECT is_active FROM core.contract_types WHERE code=:code'),
                                      {'code': w['type_code']}) is True, 'native contract type')


@asynccontextmanager
async def current_world(*, prefix):
    """Phase2 API: yield original-case {conn, config, w, evidence} at honest0/1/2.

    ROOT first supplies a NEW current-phase lease and the unchanged original
    admission contract. There is no historical app import/process reuse here.
    Call verify_current_four AFTER a case actually commits4; rollback0 remains0.
    """
    global _scope
    _require(_scope is None, 'runtime owner already active')
    contract, sources, root = _admit('current-continue')
    _require(type(prefix) is int and prefix in (0, 1, 2), 'explicit historical prefix0/1/2')
    from tests.partner_contract_schema_v4_approval import require_running_approval, require_active_approval
    original = require_running_approval()
    _require(original['target'] == contract['target']
             and original['run_lease'] == contract['run_lease']
             and original['source_root'] == str(root)
             and original['runtime_seconds'] == contract['runtime_seconds']
             and original['disposable_namespace'] == contract['disposable_namespace'], 'same current ROOT authority/lease')
    _scope = {'phase': 'current-continue', 'contract': contract, 'sources': sources,
              'root': root, 'task': asyncio.current_task(), 'conn': None, 'database': None,
              'world': None, 'config': None, 'w': None, 'target_verified': False,
              'original_guard': require_active_approval}
    conn, database = None, None
    try:
        _live('current-continue', target=False)
        receipt = _historical_receipt(contract)
        from tests import partner_contract_schema_v4_fixture as fixture
        import asyncpg
        from schema_migrations import manifest, runner
        config = runner.Config(EXACT_DSN.replace('postgresql+asyncpg:', 'postgresql:', 1), TARGET,
                               'clearledger', 'core', total_seconds=120)
        config.validate()
        _scope['config'] = config
        async with asyncio.timeout(contract['runtime_seconds']):
            conn = await asyncpg.connect(config.dsn, timeout=5, command_timeout=120, server_settings={'search_path': 'core'})
            _scope['conn'] = conn
            identity = await _identity(conn, contract)
            await fixture.preflight_identity(conn)
            await _no_managed_history(conn)
            await fixture._absent_four(conn)
            # Recheck full physical historical state against its sealed capture,
            # before any owner writes. Current metadata is deliberately not used
            # to pretend that the seven later models existed in the old epoch.
            _live('current-continue')
            from app import database, main, models_product_budget, models_partner_contracts
            _scope['database'] = database
            _origins(root, historical=False)
            fixture._origins(root)
            _require(main.create_all is database.create_all and _registry(root) == sources['current']['models'], 'actual current app/models')
            _require(sorted((m.class_.__module__ + '.' + m.class_.__name__, m.local_table.name)
                for m in database.Base.registry.mappers) == sorted((r[1], r[2]) for r in sources['current']['models']), 'all341 current mappings')
            await _historical_state_unchanged(conn, receipt)
            w = _world_ids(receipt)
            _scope['w'] = w
            await _read_parents(database, w)
            await runner.catalog.contract_create_prerequisites(conn, manifest.load_known_head().contract, config.user)
            setup = []
            if prefix >= 1:
                step = await runner.execute(config, 'apply', revision=manifest.ID)
                _require(step['action'] == 'adopted', 'native historical budget adoption only')
                setup.append(step)
            if prefix == 2:
                step = await runner.execute(config, 'apply', revision=manifest.CALENDAR_ID, legacy_sent_before=2000000000)
                _require(step['action'] == 'created', 'real calendar owner creates counter')
                setup.append(step)
            if prefix:
                await runner.require_applied_prefix(conn, config, manifest.load_known_head(),
                    required_revision=manifest.ID if prefix == 1 else manifest.CALENDAR_ID)
            await fixture._absent_four(conn)
            _require(await runner.catalog.inspect_pulse(conn, manifest.load(revision=manifest.PULSE_ID).contract, config.user) is None,
                     'no invented Pulse3')
            evidence = {'prefix': prefix, 'identity': identity, 'historical_process': receipt['process'],
                'historical_receipt_sha256': contract['historical_preparation']['sha256'],
                'historical_registry_sha256': sources['historical']['registry_sha256'],
                'current_registry_sha256': sources['current']['registry_sha256'],
                'setup': setup, 'native_parent_orm_readback': True,
                'seed_or_lifespan_called': False, 'current_create_all_called': False}
            world = {'conn': conn, 'config': config, 'w': w, 'evidence': evidence}
            _scope['world'] = world
            evidence['native_pending_prefix'] = await verify_pending_prefix(world)
            yield world
            _admit('current-continue')
            require_running_approval()
    finally:
        try:
            owned_database = database if database is not None else sys.modules.get('app.database')
            if owned_database is not None:
                await owned_database.engine.dispose()
        finally:
            try:
                if conn is not None:
                    await conn.close(timeout=2)
            finally:
                _scope = None


async def _historical_state_unchanged(conn, receipt):
    scope = _live('current-continue', conn=conn)
    _require(receipt is scope['receipt'], 'owned sealed receipt')
    """Compare all recorded historical native relations/columns/keys/RI, not counts."""
    relations = await conn.fetch("""SELECT n.nspname,c.relname,c.oid::int AS oid,c.relkind::text AS kind,
        pg_catalog.pg_get_userbyid(c.relowner) AS owner FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('core','edge') AND c.relkind IN ('r','p','f','v','m') ORDER BY n.nspname,c.relname""")
    _require([dict(r) for r in relations] == receipt['native']['tables'], 'whole historical relation/OID preservation')
    columns = await conn.fetch("""SELECT n.nspname,c.relname,a.attname,
        pg_catalog.format_type(a.atttypid,a.atttypmod) AS type,a.attnotnull
        FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('core','edge') AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY n.nspname,c.relname,a.attnum""")
    _require([dict(r) for r in columns] == receipt['native']['columns'], 'whole historical native column preservation')
    for sql, field in ((_HIST_KEYS_SQL, 'primary_and_foreign_keys'),
                       (_HIST_TRIGGERS_SQL, 'ri_triggers')):
        rows = [dict(r) for r in await conn.fetch(sql)]
        _require(rows == receipt['native'][field], 'whole historical native ' + field)
    _require(await _native_snapshot(conn) == receipt['whole_catalogue'],
             'full historical native defaults/checks/indexes/functions/types/triggers preserved')



def _delta_identity(kind, row, snapshot):
    """SOURCE identity binding only; never erase fields from retained old rows."""
    _live('current-continue')
    ns, name = row['nspname'], row.get('relname')
    if kind == 'relations':
        return [ns, name, row['relkind']]
    if kind == 'attributes':
        return [ns, name, row['attname']]
    if kind == 'constraints':
        return [ns, name, row['conname'], row['contype']]
    if kind == 'indexes':
        parent = [r for r in snapshot['relations'] if r['oid'] == row['indrelid']]
        _require(len(parent) == 1 and parent[0]['nspname'] == ns, 'index relation binding')
        return [ns, name, parent[0]['relname']]
    if kind == 'functions':
        _require(row['prokind'] == 'f', 'only SOURCE functions')
        return [ns, row['proname'], row['arguments']]
    if kind == 'types':
        return [ns, row['typname'], row['typtype']]
    if kind == 'sequences':
        return [ns, name]
    _require(kind == 'triggers', 'known catalogue category')
    if not row['tgisinternal']:
        _require(row['function_schema'] == ns and row['function_arguments'] == '', 'source trigger function signature')
        return ['USER', ns, name, row['tgname'], row['function_name'], row['tgtype']]
    keys = [k for k in snapshot['constraints'] if k['oid'] == row['tgconstraint'] and k['contype'] == 'f']
    others = [r for r in snapshot['relations'] if r['oid'] == row['tgconstrrelid']]
    _require(len(keys) == len(others) == 1 and keys[0]['nspname'] == others[0]['nspname'] == ns
             and row['function_schema'] == 'pg_catalog' and row['function_arguments'] == ''
             and re.fullmatch(r'RI_ConstraintTrigger_[ac]_' + str(row['oid']), row['tgname']),
             'native RI name/OID/source FK binding')
    return ['RI', ns, keys[0]['relname'], keys[0]['conname'], name, others[0]['relname'],
            row['function_name'], row['tgtype']]


def _added_properties(added, snapshot, specification, expected):
    """Supplement unchanged owner verifiers with closed native headers/type links."""
    scope = _live('current-continue')
    owner_oid = scope['contract']['target']['role_oid']
    tables = {name: spec for owner in specification['owners'].values() for name, spec in owner['tables'].items()}
    rels = {(r['nspname'], r['relname']): r for r in snapshot['relations']}
    types = {(r['nspname'], r['typname']): r for r in snapshot['types']}
    for r in added['relations']:
        _require(r['relowner'] == owner_oid and r['relpersistence'] == 'p'
                 and r['relacl'] is None and not r['relrowsecurity'] and not r['relforcerowsecurity']
                 and r['reloptions'] is None and r['reltablespace'] == 0
                 and r['relreplident'] == ('d' if r['relkind'] == 'r' else 'n')
                 and bool(r['reltoastrelid']) == (r['relname'] in expected['toast_tables']),
                 'source relation header/default ACL/options')
    native_types = {'uuid': (2950, 0), 'text': (25, 100), 'varchar': (1043, 100),
                    'bpchar': (1042, 100), 'int4': (23, 0), 'int8': (20, 0),
                    'bool': (16, 0), 'timestamptz': (1184, 0)}
    for a in added['attributes']:
        specs = (tables[a['relname']]['columns'] if a['relname'] in tables else
                 specification['owners']['2']['calendar']['legacy_columns'] +
                 [specification['owners']['2']['calendar']['managed_column']])
        match = [(i, c) for i, c in enumerate(specs, 1) if c['name'] == a['attname']]
        _require(len(match) == 1, 'source attribute declaration')
        number, column = match[0]
        _require(a['attnum'] == number and (a['atttypid'], a['attcollation']) == native_types[column['type']]
                 and a['atttypmod'] == column['typmod'] and a['attnotnull'] == column['not_null']
                 and a['attidentity'] == a['attgenerated'] == '' and not a['attisdropped']
                 and a['attacl'] is None, 'source attribute properties')
        # Defaults/check expressions are checked by the unchanged pinned owner
        # verifiers, not rewritten or normalized by this SOURCE helper.
    for t in added['types']:
        table_name = t['typname'] if t['typtype'] == 'c' else t['typname'][1:]
        composite = types[('core', table_name)]
        array = types[('core', '_' + table_name)]
        _require(t['typowner'] == owner_oid and t['typacl'] is None
                 and composite['typrelid'] == rels[('core', table_name)]['oid']
                 and composite['typelem'] == 0 and composite['typarray'] == array['oid']
                 and array['typrelid'] == 0 and array['typelem'] == composite['oid']
                 and array['typarray'] == 0, 'source composite/array identities')
    for i in added['indexes']:
        _require(i['indexrelid'] == rels[(i['nspname'], i['relname'])]['oid']
                 and all(i[k] for k in ('indisvalid', 'indisready', 'indislive', 'indimmediate'))
                 and not i['indisreplident'] and not i['indnullsnotdistinct'], 'source index identity/flags')
    for t in added['triggers']:
        _require(t['tgenabled'] == 'O' and not t['tgdeferrable'] and not t['tginitdeferred'], 'source trigger flags')
    _require(not added['sequences'], 'no owner SQL creates a sequence')


async def _lineage(conn, receipt, *, prefix):
    scope = _live('current-continue', conn=conn)
    _require(receipt is scope['receipt'] and type(prefix) is int and prefix in (1, 2, 3, 4),
             'owned receipt/explicit owner prefix')
    from schema_migrations import runner, manifest
    revisions = (manifest.ID, manifest.CALENDAR_ID, manifest.PULSE_ID, manifest.CONTRACT_CREATE_ID)
    await runner.require_applied_prefix(conn, scope['config'], manifest.load_known_head(),
                                        required_revision=revisions[prefix - 1])
    _require(await conn.fetchval('SELECT count(*) FROM core.core_schema_versions') == prefix, 'exact owner delta prefix')
    snapshot = await _native_snapshot(conn)
    specification = scope['sources']['owner_delta']
    expected = specification['prefixes'][str(prefix)]
    _require(set(snapshot) == set(receipt['whole_catalogue']) == set(expected['identities']) | {'dependencies'},
             'closed snapshot category set, including immutable sequences/dependencies')
    added = {}
    for kind, old_rows in receipt['whole_catalogue'].items():
        current_rows = Counter(_canonical(row) for row in snapshot[kind])
        old = Counter(_canonical(row) for row in old_rows)
        _require(old <= current_rows, 'historical full properties/OIDs changed: ' + kind)
        remaining = current_rows - old
        added[kind] = []
        for row in snapshot[kind]:
            key = _canonical(row)
            if remaining[key]:
                added[kind].append(row)
                remaining[key] -= 1
        if kind != 'dependencies':
            actual = [_canonical(_delta_identity(kind, row, snapshot)) for row in added[kind]]
            wanted = [_canonical(identity) for identity in expected['identities'][kind]]
            _require(len(actual) == len(set(actual)) == len(wanted) and set(actual) == set(wanted),
                     'exact SOURCE owner additions: ' + kind)
    _added_properties(added, snapshot, specification, expected)
    # Native RI names embed allocated trigger OIDs. Bind each *enumerated* slot
    # using its source-known FK, relation, function signature and event flags;
    # never accept an arbitrary new FK or a name-prefix grant.
    ri = {tuple(['trigger', t['nspname'], t['relname'], t['tgname']]):
          _delta_identity('triggers', t, snapshot) for t in added['triggers'] if t['tgisinternal']}
    generated = dict(ri)
    for name in expected['toast_tables']:
        relation = next(r for r in snapshot['relations'] if r['nspname'] == 'core' and r['relname'] == name)
        toast_address = ['relation', 'pg_toast', 'pg_toast_' + str(relation['oid'])]
        generated[tuple(toast_address)] = ['TOAST', 'core', name]
        matches = [r for r in added['dependencies'] if r['dependent'] == toast_address]
        _require(len(matches) == 1 and matches[0]['objid'] == relation['reltoastrelid'],
                 'SOURCE table native TOAST OID/identity binding')
    actual_edges = []
    for row in added['dependencies']:
        actual_edges.append(_canonical({'dependent': generated.get(tuple(row['dependent']), row['dependent']),
            'referenced': generated.get(tuple(row['referenced']), row['referenced']), 'deptype': row['deptype']}))
    wanted_edges = [_canonical(row) for row in expected['dependencies']]
    _require(Counter(actual_edges) == Counter(wanted_edges),
             'exact SOURCE dependency endpoints/drop behavior/multiplicity')
    # Preserve OIDs/properties of owners already verified in this current phase,
    # too: a later owner cannot silently recreate even a legitimate predecessor.
    checkpoints = scope.setdefault('catalogue_checkpoints', {})
    for previous in checkpoints.values():
        for kind, rows in previous.items():
            current = Counter(_canonical(row) for row in snapshot[kind])
            _require(Counter(_canonical(row) for row in rows) <= current,
                     'prior owner properties/OIDs changed: ' + kind)
    checkpoints[prefix] = snapshot
    return snapshot


async def verify_pending_prefix(world):
    _live('current-continue', world=world)
    """Full native boundary for all seven historical cases, including rollback0.

    Called before yielding; ROOT also calls this AFTER old-required1/2 or either
    rollback0 variant. Successful fresh0/1/2 continuation instead calls the full
    verify_current_four after its original case commits4.
    """
    contract, sources, root = _admit('current-continue')
    from tests.partner_contract_schema_v4_approval import require_running_approval
    require_running_approval()
    from tests import partner_contract_schema_v4_fixture as fixture
    from schema_migrations import manifest, runner
    from app import database
    prefix = world['evidence']['prefix']
    _require(type(prefix) is int and prefix in (0, 1, 2), 'honest pending prefix')
    receipt = _historical_receipt(contract)
    await _identity(world['conn'], contract)
    await fixture._absent_four(world['conn'])
    if prefix == 0:
        await _no_managed_history(world['conn'])
        await _historical_state_unchanged(world['conn'], receipt)
        snapshot = receipt['whole_catalogue']
    else:
        await runner.require_applied_prefix(world['conn'], world['config'], manifest.load_known_head(),
            required_revision=manifest.ID if prefix == 1 else manifest.CALENDAR_ID)
        count = await world['conn'].fetchval('SELECT count(*) FROM core.core_schema_versions')
        _require(count == prefix, 'exact pending history count, never relabelled')
        snapshot = await _lineage(world['conn'], receipt, prefix=prefix)
    _require(await runner.catalog.inspect_pulse(world['conn'], manifest.load(revision=manifest.PULSE_ID).contract,
                                               world['config'].user) is None, 'pending native Pulse child absent')
    expected_tables = {(r['nspname'], r['relname']) for r in receipt['native']['tables']}
    if prefix:
        expected_tables.add(('core', 'core_schema_versions'))
    _require({(r['nspname'], r['relname']) for r in snapshot['relations'] if r['relkind'] in ('r', 'p', 'v', 'm', 'f')}
             == expected_tables, 'all historical native tables plus only the real journal')
    await _read_parents(database, world['w'])
    _origins(root, historical=False)
    return {'prefix': prefix, 'whole_catalogue': snapshot,
            'historical_registry_sha256': sources['historical']['registry_sha256'],
            'native_parent_orm_readback': True, 'current_startup_called': False}


async def verify_current_four(world):
    _live('current-continue', world=world)
    """Read-only full current341 catalogue/ORM proof, only AFTER actual owner4.

    No current create_all is needed: all333 unchanged classes and historical raw
    DDL are the same; Calendar counter/Pulse/six new classes belong to owners2/3/4.
    This explicit API is separate from destructive cases and their own oracles.
    """
    contract, sources, root = _admit('current-continue')
    from tests.partner_contract_schema_v4_approval import require_running_approval
    require_running_approval()
    from tests import partner_contract_schema_v4_fixture as fixture
    from schema_migrations import manifest, runner
    from app import database
    await runner.require_applied_prefix(world['conn'], world['config'], manifest.load_known_head(),
                                        required_revision=manifest.CONTRACT_CREATE_ID)
    _origins(root, historical=False)
    database.preflight_startup_sources()
    await database.require_startup_schema()
    coverage = await fixture.catalogue_coverage(world['conn'], database, prefix=4)
    receipt = _historical_receipt(contract)
    snapshot = await _lineage(world['conn'], receipt, prefix=4)
    # Every original native object/definition remains; owners may only add the
    # explicitly named successor objects. Current owner verifiers validate them.
    selects = await _all_orm_selects(database)
    await _read_parents(database, world['w'])
    _require(set(selects) == {r[1] for r in sources['current']['models']}, 'every current341 real mapped SELECT')
    await _identity(world['conn'], contract)
    _admit('current-continue')
    return {'native_current4': coverage, 'all_current_orm_selects': selects,
            'whole_catalogue': snapshot, 'mapped_metadata': _mapped_metadata(database),
            'native_parent_orm_readback': True, 'current_create_all_called': False,
            'additional_incremental_ddl_required': False}


async def _populate(database):
    scope = _live('historical-prepare', database=database)
    await _identity(scope['conn'], scope['contract'])
    _origins(scope['root'], historical=True)
    """Real ORM defaults/mapping and a raw type row; no seed/service/HTTP calls."""
    from sqlalchemy import text
    from app.models import (App, Company, CompanyApp, Contract, ContractLocation,
                            Counterparty, Organization, ServiceLocation, User, UserCompany)
    from app.models_partner import PartnerClient, PartnerGrant, PartnerInstallation, PartnerInstallationLocation
    w = {key: uuid.uuid4() for key in ('company', 'app', 'installation', 'grant', 'user',
                                      'organization', 'counterparty', 'contract', 'contract_location')}
    w.update(client='schema4-native-client', location='schema4-native-location', type_code='schema4_native_test')
    scope['w'] = w
    async with database.async_session_factory() as session:
        async with session.begin():
            session.add(Company(id=w['company'], name='Synthetic schema4 native', slug='schema4-native', profile_id='energy'))
            await session.flush()
            session.add_all([
                App(id=w['app'], code='schema4_native', name='Synthetic schema4 App'),
                User(id=w['user'], company_id=w['company'], email='schema4@example.invalid',
                     password_hash='synthetic-not-a-login-hash', name='Synthetic schema4 User'),
                Organization(id=w['organization'], company_id=w['company'], inn='0000000000', name='Synthetic own organization'),
                Counterparty(id=w['counterparty'], company_id=w['company'], name='Synthetic counterparty'),
                ServiceLocation(id=w['location'], company_id=w['company'], code='schema4-native', name='Synthetic location'),
            ])
            await session.flush()
            session.add_all([
                UserCompany(user_id=w['user'], company_id=w['company']),
                CompanyApp(id=w['installation'], company_id=w['company'], app_id=w['app'], enabled=True),
                PartnerClient(id=w['client'], app_id=w['app'], owner_company_id=w['company'], enabled=True),
            ])
            await session.flush()
            session.add(PartnerInstallation(id=w['installation'], client_id=w['client'],
                                           company_id=w['company'], approved=True, all_locations=False))
            await session.flush()
            session.add_all([
                PartnerGrant(id=w['grant'], installation_id=w['installation'], client_id=w['client'],
                             company_id=w['company'], kind='machine', user_id=None, approved=True),
                PartnerInstallationLocation(installation_id=w['installation'], location_id=w['location']),
            ])
            await session.execute(text('INSERT INTO core.contract_types (code,label) VALUES (:code,:label)'),
                                  {'code': w['type_code'], 'label': 'Synthetic native type'})
            session.add(Contract(id=w['contract'], company_id=w['company'], number='SYNTHETIC-SCHEMA4',
                                 date='2026-11-01', organization_id=w['organization'],
                                 counterparty_id=w['counterparty'], type='Synthetic native type', type_code=w['type_code'],
                                 creation_actor_id=w['user']))
            await session.flush()
            session.add(ContractLocation(id=w['contract_location'], company_id=w['company'],
                                         contract_id=w['contract'], location_id=w['location']))
            await session.flush()
    # A new session must read the committed native rows through their real ORM
    # mappings; an identity-map hit in the writer is not persistence evidence.
    async with database.async_session_factory() as session:
        for key, model in (('company', Company), ('app', App), ('installation', CompanyApp),
                           ('grant', PartnerGrant), ('user', User), ('organization', Organization),
                           ('counterparty', Counterparty), ('contract', Contract),
                           ('contract_location', ContractLocation), ('client', PartnerClient),
                           ('location', ServiceLocation)):
            row = await session.get(model, w[key])
            _require(row is not None and row.id == w[key], 'native ORM committed row: ' + key)
        install = await session.get(PartnerInstallation, w['installation'])
        _require(install is not None and (install.client_id, install.company_id)
                 == (w['client'], w['company']), 'native ORM installation tuple')
        _require(await session.get(UserCompany, (w['user'], w['company'])) is not None,
                 'native ORM membership child')
        _require(await session.get(PartnerInstallationLocation, (w['installation'], w['location'])) is not None,
                 'native ORM installation location child')
        _require(await session.scalar(text('SELECT is_active FROM core.contract_types WHERE code=:code'),
                                      {'code': w['type_code']}) is True, 'native raw type row')
    return w
