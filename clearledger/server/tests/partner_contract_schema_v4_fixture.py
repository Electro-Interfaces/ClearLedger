"""Authored native schema4 fixture, SOURCE-only / runtime NOTRUN.

ROOT admits first, imports this module second, and supplies a new disposable PG16
namespace. No container/DB/role creation, reset, fallback target or CLI runner.
"""
from contextlib import asynccontextmanager
import ast
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

from tests.partner_contract_schema_v4_approval import (
    EXACT_DSN, TARGET, require_active_approval, require_running_approval,
)

require_active_approval()

VERSIONED = frozenset({
    'partner_contract_create_profiles', 'partner_contract_create_principals',
    'partner_contract_create_refs', 'partner_contract_create_types',
    'partner_contract_success_intents', 'partner_contract_intent_locations',
})
REGISTRY_SHA256 = 'd865202f524ccd2b43d48d05a931cfea8e42316e3aba982fbec80642594fb52a'
# Real database.create_all raw owners in this empty-edge energy baseline.
# SKU/MATRIX/MARK_GROUP sets require edge.item and therefore are NOT executed.
RAW_TABLES = frozenset({
    ('core', 'accounting_adjustments'), ('core', 'accounting_closing_date'),
    ('core', 'contract_types'), ('core', 'edge_packet_revision_decisions'),
    ('edge', 'nsi_proposal'), ('core', 'core_schema_versions'),
})


def _require(condition, reason):
    if not condition:
        raise RuntimeError('schema4 native fixture refused: ' + reason)


def _identifier(value):
    _require(re.fullmatch('[a-z_][a-z0-9_]*', value) is not None, 'catalogue identifier')
    return '"' + value + '"'


def _source_models(root):
    rows = []
    for path in sorted((root / 'app').rglob('*.py')):
        for node in ast.parse(path.read_bytes()).body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.Assign) and any(
                            isinstance(target, ast.Name) and target.id == '__tablename__'
                            for target in item.targets):
                        rows.append([str(path.relative_to(root)),
                                     '.'.join(path.relative_to(root).with_suffix('').parts) + '.' + node.name,
                                     ast.literal_eval(item.value)])
    digest = hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()
    _require(digest == REGISTRY_SHA256, 'complete source model registry differs')
    return rows


def _origins(root):
    for name, module in tuple(sys.modules.items()):
        if name == 'app' or name.startswith(('app.', 'schema_migrations')):
            path = getattr(module, '__file__', None)
            expected = root.joinpath(*name.split('.'))
            if path is None:
                # bootstrap is a real PEP420 namespace in this frozen source.
                _require(expected.is_dir() and not expected.is_symlink()
                         and list(getattr(module, '__path__', ())) == [str(expected)],
                         'runtime namespace imported from another tree: ' + name)
                continue
            actual = Path(path).resolve()
            _require(actual in {expected.with_suffix('.py'), expected / '__init__.py'},
                     'runtime module imported from another tree: ' + name)


async def preflight_identity(conn):
    """Read-only live identity validation AFTER admission; caller owns connection.

    ROOT attests the actual container independently; SQL verifies actual PG
    identity and OIDs, not a container label or the name of an approval file.
    This function does not start/finish transactions, set options or acquire locks.
    """
    approval = require_running_approval()
    target = approval['target']
    row = await conn.fetchrow("""SELECT current_database() AS db,current_user AS usr,
        current_schema() AS ns,current_setting('search_path') AS path,
        current_setting('server_version_num')::int AS version,
        current_setting('session_replication_role') AS replication,
        pg_catalog.host(pg_catalog.inet_server_addr()) AS host,inet_server_port() AS port,
        d.oid::int AS database_oid,d.datdba::int AS database_owner,
        r.oid::int AS role_oid,r.rolsuper,r.rolcreatedb,r.rolcreaterole,
        r.rolreplication,r.rolbypassrls,
        n.oid::int AS core_oid,n.nspowner::int AS core_owner,
        e.oid::int AS edge_oid,e.nspowner::int AS edge_owner
        FROM pg_catalog.pg_database d JOIN pg_catalog.pg_roles r ON r.rolname=current_user
        JOIN pg_catalog.pg_namespace n ON n.nspname='core'
        JOIN pg_catalog.pg_namespace e ON e.nspname='edge'
        WHERE d.datname=current_database()""")
    _require(row is not None, 'actual database/role/namespaces')
    _require((row['db'], row['usr'], row['ns'], row['path'], row['host'], row['port'])
             == (TARGET, 'clearledger', 'core', 'core', '127.0.0.1', 33546),
             'actual exact PG target/search_path')
    _require(160000 <= row['version'] < 170000 and row['replication'] == 'origin',
             'PG16 with enabled native constraints/triggers')
    _require(all(row[key] == target[key] for key in
                 ('database_oid', 'role_oid', 'core_oid', 'edge_oid')), 'ROOT-attested actual OIDs')
    _require(all(not row[key] for key in
                 ('rolsuper', 'rolcreatedb', 'rolcreaterole', 'rolreplication', 'rolbypassrls')),
             'non-superuser role without administrative bypass')
    _require(row['core_owner'] == row['edge_owner'] == target['role_oid'], 'namespace owners')
    extensions = await conn.fetch("""SELECT e.extname,n.nspname FROM pg_catalog.pg_extension e
        JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace
        WHERE e.extname IN ('btree_gist','pgcrypto','uuid-ossp')""")
    _require({r['extname'] for r in extensions} == {'btree_gist', 'pgcrypto', 'uuid-ossp'}
             and all(r['nspname'] != 'core' for r in extensions), 'administrator-installed extensions')
    return dict(row)


async def _empty(conn):
    occupied = await conn.fetchval("""SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('core','edge') UNION ALL
        SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname IN ('core','edge') UNION ALL
        SELECT 1 FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
        WHERE n.nspname IN ('core','edge'))""")
    _require(not occupied, 'new owned empty core/edge required; fixture never resets a world')


async def _absent_four(conn):
    occupied = await conn.fetchval("""SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='core' AND c.relname=ANY($1::text[]))""", sorted(VERSIONED))
    _require(not occupied, 'native create_all must leave all six revision4 tables absent')


async def catalogue_coverage(conn, database, *, prefix):
    """Match source registry → actual metadata → actual catalogue by names/FKs.

    Native legacy DDL may add columns/FKs absent from ORM: these are returned
    explicitly as catalogue extras, not silently counted as mapped definitions.
    Revision4's exact types/defaults/triggers/etc remain its native verifier's job.
    """
    root = Path(__file__).resolve().parents[1]
    expected_models = _source_models(root)
    _origins(root)
    actual_models = sorted((m.class_.__module__ + '.' + m.class_.__name__, m.local_table.name)
                           for m in database.Base.registry.mappers)
    _require(actual_models == sorted((row[1], row[2]) for row in expected_models),
             'app.main registration must include every actual source model')
    metadata = {(table.schema or 'core', table.name): table
                for table in database.Base.metadata.tables.values()}
    _require(len(metadata) == len(expected_models), 'metadata/mapper table set')
    wanted = {key for key in metadata if prefix == 4 or key[1] not in VERSIONED} | RAW_TABLES
    relations = await conn.fetch("""SELECT n.nspname,c.relname,c.oid::int AS oid,
        c.relkind::text AS kind,pg_catalog.pg_get_userbyid(c.relowner) AS owner
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('core','edge') AND c.relkind IN ('r','p','f','v','m')
        ORDER BY n.nspname,c.relname""")
    found = {(r['nspname'], r['relname']) for r in relations}
    _require(found == wanted, 'physical native table set differs: missing=' + repr(sorted(wanted-found))
             + ', extra=' + repr(sorted(found-wanted)))
    _require(all(r['kind'] == 'r' and r['owner'] == 'clearledger' for r in relations),
             'native ordinary table ownership')
    columns = await conn.fetch("""SELECT n.nspname,c.relname,a.attname,
        pg_catalog.format_type(a.atttypid,a.atttypmod) AS type,a.attnotnull
        FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('core','edge') AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY n.nspname,c.relname,a.attnum""")
    keys = await conn.fetch("""SELECT n.nspname,c.relname,k.oid::int AS constraint_oid,k.conname,k.contype::text AS kind,
        k.convalidated,k.confdeltype::text AS delete_action,tn.nspname AS target_schema,
        tc.relname AS target_table,
        ARRAY(SELECT a.attname::text FROM unnest(k.conkey) WITH ORDINALITY x(num,pos)
          JOIN pg_catalog.pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=x.num ORDER BY x.pos) AS columns,
        ARRAY(SELECT a.attname::text FROM unnest(k.confkey) WITH ORDINALITY x(num,pos)
          JOIN pg_catalog.pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=x.num ORDER BY x.pos) AS target_columns
        FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_catalog.pg_class tc ON tc.oid=k.confrelid
        LEFT JOIN pg_catalog.pg_namespace tn ON tn.oid=tc.relnamespace
        WHERE n.nspname IN ('core','edge') AND k.contype IN ('p','f') ORDER BY n.nspname,c.relname,k.conname""")
    triggers = await conn.fetch("""SELECT t.tgrelid::int AS relation,t.tgconstraint::int AS constraint_oid,
        t.tgname,t.tgenabled::text AS enabled,t.tgisinternal,
        k.conname FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_constraint k ON k.oid=t.tgconstraint
        JOIN pg_catalog.pg_namespace n ON n.oid=k.connamespace
        WHERE n.nspname IN ('core','edge') AND k.contype='f' ORDER BY k.oid,t.tgname""")
    _require(all(r['convalidated'] for r in keys), 'native PK/FK validation')
    _require(all(r['enabled'] in ('O', 'A') and r['tgisinternal'] for r in triggers), 'native RI trigger enabled')
    actual_fks = {(r['nspname'], r['relname'], tuple(r['columns']), r['target_schema'],
                   r['target_table'], tuple(r['target_columns']), r['delete_action'])
                  for r in keys if r['kind'] == 'f'}
    expected_fks = set()
    extras = []
    actions = {None: 'a', 'NO ACTION': 'a', 'CASCADE': 'c', 'SET NULL': 'n', 'RESTRICT': 'r', 'SET DEFAULT': 'd'}
    for key, table in metadata.items():
        if key not in wanted:
            continue
        actual_columns = {r['attname'] for r in columns if (r['nspname'], r['relname']) == key}
        _require(set(table.columns.keys()) <= actual_columns, 'native mapped columns: ' + str(key))
        extras.extend([*key, name] for name in sorted(actual_columns - set(table.columns.keys())))
        primary = [tuple(r['columns']) for r in keys if (r['nspname'], r['relname']) == key and r['kind'] == 'p']
        _require(primary == [tuple(c.name for c in table.primary_key.columns)], 'native primary key: ' + str(key))
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            refs = [element.target_fullname.split('.') for element in elements]
            target_schema = refs[0][-3] if len(refs[0]) == 3 else 'core'
            expected_fks.add((*key, tuple(e.parent.name for e in elements), target_schema,
                              refs[0][-2], tuple(r[-1] for r in refs), actions[constraint.ondelete]))
    _require(expected_fks <= actual_fks, 'native model FK/action coverage missing: '
             + repr(sorted(expected_fks-actual_fks)))
    # Every physical FK must have its four real internal RI triggers.
    for row in keys:
        if row['kind'] == 'f':
            _require(sum(t['constraint_oid'] == row['constraint_oid'] for t in triggers) == 4,
                     'physical FK RI trigger coverage')
    return {'source_registry_sha256': REGISTRY_SHA256, 'models': expected_models,
            'tables': [dict(r) for r in relations], 'columns': [dict(r) for r in columns],
            'primary_and_foreign_keys': [dict(r) for r in keys],
            'ri_triggers': [dict(r) for r in triggers], 'native_extra_columns': extras,
            'native_extra_fks': sorted(actual_fks - expected_fks)}


async def _populate(database):
    """Real ORM defaults/mapping and a raw type row; no seed/service/HTTP calls."""
    from sqlalchemy import text
    from app.models import (App, Company, CompanyApp, Contract, ContractLocation,
                            Counterparty, Organization, ServiceLocation, User, UserCompany)
    from app.models_partner import PartnerClient, PartnerGrant, PartnerInstallation, PartnerInstallationLocation
    w = {key: uuid.uuid4() for key in ('company', 'app', 'installation', 'grant', 'user',
                                      'organization', 'counterparty', 'contract', 'contract_location')}
    w.update(client='schema4-native-client', location='schema4-native-location', type_code='schema4_native_test')
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


async def _orm_four(database):
    from sqlalchemy import select
    checked = []
    async with database.async_session_factory() as session:
        for mapper in sorted(database.Base.registry.mappers, key=lambda m: m.local_table.name):
            if mapper.local_table.name in VERSIONED:
                # Six empty real owner-created tables: SELECT all mapped columns
                # checks the mapped SELECT shape against actual PG DDL; empty
                # tables do not claim a six-model write/materialisation proof.
                _require((await session.scalars(select(mapper.class_).limit(1))).first() is None,
                         'new revision4 table must be empty before case')
                checked.append(mapper.local_table.name)
    _require(set(checked) == VERSIONED, 'all six actual revision4 ORM mappings')
    return checked


async def _safe_deletes(conn, w):
    """Inspect ALL actual incoming FKs before handing native delete cases to ROOT.

    No FK is removed and no row is deleted here. New cases write only into this
    fresh world; after each destructive/drift case ROOT disposes that namespace.
    """
    allowed = {'users': {'user_companies', 'contracts'}, 'contracts': {'contract_locations'},
               'service_locations': {'contract_locations', 'partner_installation_locations'},
               'partner_grants': set(), 'partner_installations': {'partner_grants', 'partner_installation_locations'},
               'eco_apps': {'eco_company_apps', 'partner_clients'}}
    parents = {'users': w['user'], 'contracts': w['contract'], 'service_locations': w['location'],
               'partner_grants': w['grant'], 'partner_installations': w['installation'], 'eco_apps': w['app']}
    observed = []
    for parent, ident in parents.items():
        fks = await conn.fetch("""SELECT sn.nspname AS schema,sc.relname AS child,k.conname,
            k.confdeltype::text AS action,
            ARRAY(SELECT a.attname::text FROM unnest(k.conkey) WITH ORDINALITY x(num,pos)
              JOIN pg_catalog.pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=x.num ORDER BY x.pos) AS columns,
            ARRAY(SELECT a.attname::text FROM unnest(k.confkey) WITH ORDINALITY x(num,pos)
              JOIN pg_catalog.pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=x.num ORDER BY x.pos) AS target_columns
            FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class sc ON sc.oid=k.conrelid
            JOIN pg_catalog.pg_namespace sn ON sn.oid=sc.relnamespace
            WHERE k.contype='f' AND k.confrelid=to_regclass('core.'||$1)""", parent)
        for fk in fks:
            predicates = ' AND '.join('c.' + _identifier(c) + '=p.' + _identifier(t)
                                      for c,t in zip(fk['columns'], fk['target_columns']))
            count = await conn.fetchval('SELECT count(*) FROM ' + _identifier(fk['schema']) + '.'
                + _identifier(fk['child']) + ' c JOIN core.' + _identifier(parent) + ' p ON '
                + predicates + ' WHERE p.id=$1', ident)
            _require(count == 0 or (fk['schema'] == 'core' and fk['child'] in allowed[parent]
                                   and count == 1 and fk['action'] in ('c', 'n')),
                     'unowned or blocking native dependent: ' + parent + '/' + fk['child'])
            observed.append({'parent': parent, **dict(fk), 'matching_rows': count})
    return observed


@asynccontextmanager
async def native_world(*, prefix=3):
    """Concrete ROOT API: yields {conn, config, w, evidence}; no implicit case run.

    prefix3: real frozen provision3 → full native create_all → real ORM parents.
    prefix4: same world → explicit runner4, never metadata.create_all for six.
    Prefix0–2 have no proven full-native recipe here and fail BEFORE imports/I/O.
    Resource destruction belongs to ROOT; exit only closes owned connections.
    """
    approval = require_running_approval()
    _require(type(prefix) is int and prefix in (3, 4),
             'prefix0/1/2 NOTRUN: current native Core create_all requires recorded Pulse3; '
             'no journal deletion/calendar relabeling recipe is admitted')
    root = Path(__file__).resolve().parents[1]
    import asyncpg
    from schema_migrations import manifest, runner
    config = runner.Config(EXACT_DSN.replace('postgresql+asyncpg:', 'postgresql:', 1), TARGET,
                           'clearledger', 'core', total_seconds=120)
    config.validate()
    conn, database = None, None
    try:
        async with asyncio.timeout(approval['runtime_seconds']):
            conn = await asyncpg.connect(config.dsn, timeout=5, command_timeout=120,
                                        server_settings={'search_path': 'core'})
            identity = await preflight_identity(conn)
            await _empty(conn)
            await _absent_four(conn)
            # Same frozen source/owner sequence as the proven Core3 recipe.
            # This ten-table stage is explicitly NOT the complete native world.
            provision = await runner.execute_sequence(config, target_revision=manifest.PULSE_ID,
                fresh_prerequisites='core_prerequisites_v1', legacy_sent_before=2000000000)
            _require(provision['fresh_created'] and provision['prefix_before'] == 0,
                     'fresh frozen provision3 receipt')
            from app import database, main
            _origins(root)
            _require(Path(main.__file__).resolve() == root / 'app/main.py'
                     and main.create_all is database.create_all, 'actual native startup DDL composition')
            _require(database.settings.database_url == EXACT_DSN
                     and main.settings.app_env == 'test'
                     and database.settings.managed_core_budget_enabled,
                     'native settings exact target')
            database.preflight_startup_sources()
            await database.require_startup_schema()
            async with database.database_startup_lock():
                # No patched DDL, no _prepare_database_once, seed or lifespan.
                await database.create_all()
            await _absent_four(conn)
            await runner.require_applied_prefix(conn, config, manifest.load_known_head(),
                                                required_revision=manifest.PULSE_ID)
            # Explicit ID, never head.parent.contract (head's parent is Pulse3).
            await runner.catalog.inspect_calendar(conn, manifest.load(revision=manifest.CALENDAR_ID).contract, config.user)
            coverage3 = await catalogue_coverage(conn, database, prefix=3)
            w = await _populate(database)
            deletes = await _safe_deletes(conn, w)
            await runner.catalog.contract_create_prerequisites(conn, manifest.load_known_head().contract, config.user)
            application4 = None
            coverage4 = None
            orm4 = None
            if prefix == 4:
                application4 = await runner.execute(config, 'apply', revision=manifest.CONTRACT_CREATE_ID,
                                                     legacy_sent_before=2000000000)
                _require(application4['prefix_before'] == 3, 'explicit3→4 owner sequence')
                coverage4 = await catalogue_coverage(conn, database, prefix=4)
                orm4 = await _orm_four(database)
            yield {'conn': conn, 'config': config, 'w': w,
                   'evidence': {'prefix': prefix, 'identity': identity, 'provision3': provision,
                                'native_prefix3': coverage3, 'native_prefix4': coverage4,
                                'native_parent_orm_readback': True, 'revision4_orm_selects': orm4,
                                'native_delete_dependents': deletes, 'application4': application4,
                                'seed_or_lifespan_called': False}}
    finally:
        try:
            if database is not None:
                await database.engine.dispose()
        finally:
            if conn is not None:
                await conn.close(timeout=2)
