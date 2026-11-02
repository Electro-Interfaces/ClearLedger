"""Замороженный каталог PG16 для revision0004: только SELECT, без ORM imports.

У native parents проверяются только нужные0004 headers/types/keys. Свои шесть
таблиц, функции и триггеры имеют точный закрытый каталог.
"""
import re

from schema_migrations.revisions.catalog_v1 import (
    columns, constraints, constraint_flags, indexes, require, verify_columns,
)


def expression(value):
    """Сравнить ограниченную boolean-грамматику с сохранением групп AND/OR.

    PG добавляет casts и лишние скобки к простым атомам. Арифметика, подзапросы,
    другая collation и произвольный SQL не допускаются. Строковые токены сохраняют
    точный регистр, пробелы и скобки.
    """
    if value is None:
        return None
    tokens = re.findall(r"'(?:[^']|'')*'|::|[A-Za-z_][A-Za-z_0-9]*|\d+|<>|>=|<=|[^\s]", value)
    # PG16 отображает аргументы varchar/bpchar как text для этих функций.
    tokens = [t.lower() if not t.startswith("'") else t for t in tokens]
    tokens = [t for i, t in enumerate(tokens) if not (
        (t == '::' and i + 1 < len(tokens) and tokens[i + 1] == 'text')
        or (t == 'text' and i > 0 and tokens[i - 1] == '::'))]

    def parse(items):
        while items and items[0] == '(' and items[-1] == ')':
            depth = 0
            for i, token in enumerate(items):
                depth += (token == '(') - (token == ')')
                if depth == 0:
                    break
            if i != len(items) - 1:
                break
            items = items[1:-1]
        for operator in ('or', 'and'):
            depth, start, pieces = 0, 0, []
            for i, token in enumerate(items):
                depth += (token == '(') - (token == ')')
                if token == operator and depth == 0:
                    pieces.append(parse(items[start:i]))
                    start = i + 1
            if pieces:
                return operator, tuple(pieces + [parse(items[start:])])
        return 'atom', tuple(t for t in items if t not in ('(', ')'))
    return parse(tokens)


async def header(conn, name, owner):
    row = await conn.fetchrow("""SELECT c.oid,c.relkind::text AS kind,
        c.relpersistence::text AS persistence,pg_catalog.pg_get_userbyid(c.relowner) AS owner,
        c.relrowsecurity,c.relforcerowsecurity,c.reloptions,c.reltablespace,c.relreplident::text AS replica,
        NOT EXISTS(SELECT 1 FROM pg_catalog.pg_inherits i
          WHERE i.inhrelid=c.oid OR i.inhparent=c.oid) AS no_inheritance
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='core' AND c.relname=$1""", name)
    if row is None:
        return None
    require(row['kind'] == 'r' and row['persistence'] == 'p' and row['owner'] == owner
        and not row['relrowsecurity'] and not row['relforcerowsecurity']
        and row['no_inheritance'], 'pc_relation')
    return dict(row)


async def acl(conn, oid, owner):
    rows = await conn.fetch("""SELECT pg_catalog.pg_get_userbyid(a.grantor) AS grantor,
        CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_catalog.pg_get_userbyid(a.grantee) END AS grantee,
        a.privilege_type AS privilege,a.is_grantable
        FROM pg_catalog.pg_class c CROSS JOIN LATERAL
        pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
        WHERE c.oid=$1""", oid)
    require(len(rows) == 7 and {r['privilege'] for r in rows} == {
        'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'}
        and all(r['grantor'] == r['grantee'] == owner and not r['is_grantable'] for r in rows), 'pc_acl')
    require(not await conn.fetchval("""SELECT
        EXISTS(SELECT 1 FROM pg_catalog.pg_attribute WHERE attrelid=$1 AND attnum>0 AND attacl IS NOT NULL)
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_policy WHERE polrelid=$1)
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_rewrite WHERE ev_class=$1)
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_seclabel WHERE classoid='pg_catalog.pg_class'::regclass AND objoid=$1)
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_publication_rel WHERE prrelid=$1)""", oid), 'pc_relation_options')


async def verify_index(conn, row, wanted, names, types, owner):
    require(row['namespace'] == 'core' and row['owner'] == owner and row['method'] == 'btree'
        and row['kind'] == 'i' and row['persistence'] == 'p' and row['default_acl']
        and row['valid'] and row['ready'] and row['live'] and row['immediate']
        and not row['exclusion'] and not row['nulls_not_distinct'] and row['no_expression']
        and row['default_collations'] and row['key_count'] == row['total_count'] == len(wanted['columns'])
        and [names.get(k) for k in row['keys']] == wanted['columns']
        and row['options'] == [0] * len(wanted['columns'])
        and row['unique'] == wanted['unique'] and row['primary'] == wanted['primary'], 'pc_index')
    ops = {'uuid': 'uuid_ops', 'text': 'text_ops', 'varchar': 'text_ops', 'bpchar': 'bpchar_ops'}
    require(row['opclasses'] == ['pg_catalog.' + ops[types[n]] for n in wanted['columns']], 'pc_index_ops')
    actual = await conn.fetchrow("""SELECT pg_catalog.pg_get_expr(i.indpred,i.indrelid,false) AS predicate,
        c.reloptions,c.reltablespace FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid WHERE i.indexrelid=$1""", row['oid'])
    require(actual['reloptions'] is None and actual['reltablespace'] == 0
        and expression(actual['predicate']) == expression(wanted['predicate']), 'pc_index_predicate')


async def prerequisites(conn, contract, owner):
    parents = {}
    for name, spec in contract['prerequisites'].items():
        row = await header(conn, name, owner)
        require(row is not None, 'pc_prerequisite')
        names = verify_columns(await columns(conn, row['oid']), spec['columns'], exact=False)
        keys = await constraints(conn, row['oid'])
        required = [('p', None, spec['primary'])]
        if 'unique' in spec:
            required.append(('u', spec['unique']['name'], spec['unique']['columns']))
        for kind, key_name, key_columns in required:
            found = [k for k in keys if k['kind'] == kind and
                [names.get(n) for n in k['keys']] == key_columns and (key_name is None or k['name'] == key_name)]
            require(len(found) == 1, 'pc_prerequisite_key')
            constraint_flags(found[0])
            indices = [i for i in await indexes(conn, row['oid']) if i['oid'] == found[0]['index_oid']]
            require(len(indices) == 1, 'pc_prerequisite_key')
            await verify_index(conn, indices[0], {'columns': key_columns, 'unique': True,
                'primary': kind == 'p', 'predicate': None}, names,
                {c['name']: c['type'] for c in spec['columns']}, owner)
        parents[name] = {**row, 'attributes': names}
    return parents


async def foreign_key_triggers(conn, key, child, parent, delete):
    rows = await conn.fetch("""SELECT t.tgrelid,t.tgconstrrelid,t.tgtype,t.tgenabled::text AS enabled,
        t.tgisinternal,t.tgdeferrable,t.tginitdeferred,t.tgqual IS NULL AS no_qualifier,
        p.proname,n.nspname FROM pg_catalog.pg_trigger t
        JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
        JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE t.tgconstraint=$1""", key['oid'])
    expected = {(child, parent, 5, 'RI_FKey_check_ins'), (child, parent, 17, 'RI_FKey_check_upd'),
        (parent, child, 9, {'c': 'RI_FKey_cascade_del', 'n': 'RI_FKey_setnull_del'}[delete]),
        (parent, child, 17, 'RI_FKey_noaction_upd')}
    require(len(rows) == 4 and {(r['tgrelid'], r['tgconstrrelid'], r['tgtype'], r['proname']) for r in rows} == expected
        and all(r['enabled'] == 'O' and r['tgisinternal'] and not r['tgdeferrable']
            and not r['tginitdeferred'] and r['no_qualifier'] and r['nspname'] == 'pg_catalog' for r in rows), 'pc_fk_triggers')
    # SET NULL по отдельным колонкам и дрейф deletion metadata также запрещены.
    require(not await conn.fetchval("SELECT confdelsetcols IS NOT NULL FROM pg_catalog.pg_constraint WHERE oid=$1", key['oid']), 'pc_fk_columns')


async def own_table(conn, spec, row, parents, owner):
    oid = row['oid']
    require(row['reloptions'] is None and row['reltablespace'] == 0 and row['replica'] == 'd', 'pc_table_options')
    await acl(conn, oid, owner)
    require(await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_am a ON a.oid=c.relam WHERE c.oid=$1 AND a.amname='heap')
        AND EXISTS(SELECT 1 FROM pg_catalog.pg_type t
          JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
          JOIN pg_catalog.pg_type ar ON ar.oid=t.typarray
          WHERE t.typrelid=$1 AND t.typname=$2 AND ar.typname='_'||$2
            AND t.typtype='c' AND t.typisdefined AND t.typacl IS NULL
            AND n.nspname='core' AND pg_catalog.pg_get_userbyid(t.typowner)=current_user
            AND ar.typacl IS NULL AND ar.typowner=t.typowner AND ar.typnamespace=t.typnamespace)""", oid, spec['name']), 'pc_owned_type')
    names = verify_columns(await columns(conn, oid), spec['columns'])
    keys = await constraints(conn, oid)
    expected = {spec['name'] + '_pkey': ('p', spec['primary'])}
    expected.update({n: ('u', c) for n, c in spec['unique'].items()})
    expected.update({n: ('c', c) for n, c in spec['checks'].items()})
    expected.update({n: ('f', f) for n, f in spec['foreign_keys'].items()})
    require(len(keys) == len(expected) and {k['name'] for k in keys} == set(expected), 'pc_constraints')
    for key in keys:
        constraint_flags(key)
        kind, wanted = expected[key['name']]
        require(key['kind'] == kind, 'pc_constraint_kind')
        if kind in {'p', 'u'}:
            require([names.get(k) for k in key['keys']] == wanted, 'pc_key')
        elif kind == 'c':
            require(expression(key['expression']) == expression(wanted), 'pc_check')
            extra = await conn.fetchrow('SELECT connoinherit,conparentid FROM pg_catalog.pg_constraint WHERE oid=$1', key['oid'])
            require(not extra['connoinherit'] and extra['conparentid'] == 0, 'pc_check_flags')
        else:
            parent = parents[wanted['table']]
            require(key['target_oid'] == parent['oid'] and [names.get(k) for k in key['keys']] == wanted['columns']
                and [parent['attributes'].get(k) for k in key['target_keys']] == wanted['target_columns']
                and key['delete_action'] == wanted['delete'] and key['update_action'] == 'a' and key['match'] == 's', 'pc_fk')
            await foreign_key_triggers(conn, key, oid, parent['oid'], wanted['delete'])
    indices = await indexes(conn, oid)
    require(len(indices) == len(spec['indexes']) and {i['name'] for i in indices} == set(spec['indexes']), 'pc_indexes')
    for index in indices:
        await verify_index(conn, index, spec['indexes'][index['name']], names,
            {c['name']: c['type'] for c in spec['columns']}, owner)


async def functions(conn, contract, owner):
    ids = {}
    for name, body in contract['functions'].items():
        rows = await conn.fetch("""SELECT p.oid,pg_catalog.pg_get_userbyid(p.proowner) AS owner,
            p.prosrc,p.probin,p.prosecdef,p.proleakproof,p.proisstrict,p.proretset,p.prokind::text,
            p.provolatile::text,p.proparallel::text,p.pronargs,p.pronargdefaults,p.proconfig,
            p.prorettype='pg_catalog.trigger'::regtype AS trigger_return,l.lanname,
            p.procost,p.prorows,p.prosupport::oid AS prosupport,p.proacl,p.proargnames,p.proargmodes,p.proallargtypes,
            p.prosqlbody IS NULL AS no_sql_body
            FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            JOIN pg_catalog.pg_language l ON l.oid=p.prolang WHERE n.nspname='core' AND p.proname=$1""", name)
        require(len(rows) == 1, 'pc_function')
        p = rows[0]
        require(p['owner'] == owner and p['prosrc'] == body and p['probin'] is None
            and not p['prosecdef'] and not p['proleakproof'] and not p['proisstrict'] and not p['proretset']
            and p['prokind'] == 'f' and p['provolatile'] == 'v' and p['proparallel'] == 'u'
            and p['pronargs'] == p['pronargdefaults'] == 0 and p['trigger_return'] and p['lanname'] == 'plpgsql'
            and p['proconfig'] == ['search_path=pg_catalog, core'] and p['procost'] == 100
            and p['prorows'] == 0 and p['prosupport'] == 0 and p['proargnames'] is None
            and p['proargmodes'] is None and p['proallargtypes'] is None and p['no_sql_body'], 'pc_function')
        rights = await conn.fetch("""SELECT a.grantor,a.grantee,a.privilege_type,a.is_grantable
            FROM pg_catalog.pg_proc p CROSS JOIN LATERAL
            pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE p.oid=$1""", p['oid'])
        require(len(rights) == 1 and rights[0]['grantor'] == rights[0]['grantee']
            and rights[0]['grantee'] == await conn.fetchval('SELECT oid FROM pg_catalog.pg_roles WHERE rolname=$1', owner)
            and rights[0]['privilege_type'] == 'EXECUTE' and not rights[0]['is_grantable'], 'pc_function_acl')
        ids[name] = p['oid']
    return ids


async def inspect(conn, contract, owner, *, applied):
    """Отказать на занятых/неучтённых/неполных именах; без adopt/repair0004."""
    headers = {n: await header(conn, n, owner) for n in contract['tables']}
    present = [r for r in headers.values() if r is not None]
    if not applied:
        reserved = list(contract['tables']) + ['_' + n for n in contract['tables']]
        reserved += [n for t in contract['tables'].values() for n in t['indexes']]
        occupied = await conn.fetchval("""SELECT
            EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='core' AND c.relname=ANY($1::text[]))
            OR EXISTS(SELECT 1 FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
                WHERE n.nspname='core' AND t.typname=ANY($1::text[]))
            OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname='core' AND p.proname=ANY($2::text[]))""", reserved, list(contract['functions']))
        require(not present and not occupied, 'pc_unrecorded_occupancy')
        return None
    require(len(present) == len(headers), 'pc_missing_applied_table')
    parents = await prerequisites(conn, contract, owner)
    for name, row in headers.items():
        parents[name] = {**row, 'attributes': verify_columns(await columns(conn, row['oid']), contract['tables'][name]['columns'])}
    for name, row in headers.items():
        await own_table(conn, contract['tables'][name], row, parents, owner)
    own_ids = [r['oid'] for r in headers.values()]
    require(not await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint
        WHERE confrelid=ANY($1::oid[]) AND conrelid<>ALL($1::oid[]))""", own_ids), 'pc_foreign_dependents')
    function_ids = await functions(conn, contract, owner)
    triggers = await conn.fetch("""SELECT t.tgname,t.tgrelid,t.tgfoid,t.tgtype,t.tgenabled::text AS enabled,
        t.tgconstraint,t.tgdeferrable,t.tginitdeferred,t.tgnargs,t.tgattr::smallint[] AS attrs,
        t.tgqual IS NULL AS no_qualifier,t.tgoldtable,t.tgnewtable,t.tgparentid,
        t.tgconstrrelid,t.tgconstrindid,pg_catalog.octet_length(t.tgargs) AS argument_bytes
        FROM pg_catalog.pg_trigger t WHERE NOT t.tgisinternal
        AND (t.tgrelid=ANY($1::oid[]) OR t.tgfoid=ANY($2::oid[]))""", own_ids, list(function_ids.values()))
    require(len(triggers) == len(contract['triggers']) and {t['tgname'] for t in triggers} == set(contract['triggers']), 'pc_triggers')
    for t in triggers:
        wanted = contract['triggers'][t['tgname']]
        require(t['tgrelid'] == headers[wanted['table']]['oid'] and t['tgfoid'] == function_ids[wanted['function']]
            and t['tgtype'] == wanted['type'] and t['enabled'] == 'O' and t['tgconstraint'] == 0
            and not t['tgdeferrable'] and not t['tginitdeferred'] and t['tgnargs'] == 0
            and not t['attrs'] and t['no_qualifier'] and t['tgoldtable'] is None and t['tgnewtable'] is None
            and t['tgparentid'] == t['tgconstrrelid'] == t['tgconstrindid'] == t['argument_bytes'] == 0, 'pc_trigger')
    return headers
