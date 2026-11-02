"""Closed PG16 receipt catalogue for revision0005; SELECT only, no ORM imports.

This verifier has its own expression parser. It preserves boolean grouping,
function arguments and casts; it does not reuse frozen0001/0004 SQL munging.
Only the frozen low-level catalogue row readers are shared.
"""
import re

from schema_migrations.errors import MigrationError
from schema_migrations.revisions.catalog_v1 import columns, constraints, indexes


def require(value, phase="pcc_catalog"):
    if not value:
        raise MigrationError(4, phase)


def expression(source, types):
    """Parse exactly this revision's expression subset, rejecting unknown syntax.

The only discarded casts are PG's text coercion of already textual values and
literal name coercion (convert_to encoding). JSONB-to-text remains significant.
Parentheses are parsed, never deleted from a flat token stream.
"""
    if source is None:
        return None
    scanner = re.compile(r"\s+|'(?:[^']|'')*'|::|<=|>=|<>|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[().,=~<>]")
    tokens, end = [], 0
    for match in scanner.finditer(source):
        require(match.start() == end, "pcc_expression")
        end = match.end()
        value = match.group()
        if not value.isspace():
            tokens.append(value if value.startswith("'") else value.lower())
    require(end == len(source) and bool(tokens), "pcc_expression")
    position = 0

    def peek():
        return tokens[position] if position < len(tokens) else None

    def take(wanted=None):
        nonlocal position
        value = peek()
        require(value is not None and (wanted is None or value == wanted), "pcc_expression")
        position += 1
        return value

    def atom():
        token = take()
        if token == "(":
            value = parse(0)
            take(")")
        elif token.startswith("'"):
            value = ("literal", token)
        elif token.isdigit():
            value = ("number", token)
        else:
            require(re.fullmatch(r"[a-z_][a-z_0-9]*", token) is not None, "pcc_expression")
            if peek() == ".":
                take(".")
                require(token == "pg_catalog", "pcc_expression_namespace")
                token = take()
            if peek() == "(":
                require(token in {"length", "jsonb_typeof", "octet_length", "convert_to", "now", "pg_current_xact_id"}, "pcc_expression_function")
                take("(")
                args = []
                if peek() != ")":
                    args.append(parse(0))
                    while peek() == ",":
                        take(",")
                        args.append(parse(0))
                take(")")
                value = ("call", token, tuple(args))
            else:
                require(token in types, "pcc_expression_column")
                value = ("column", token)
        while peek() == "::":
            take("::")
            cast = take()
            if cast == "pg_catalog":
                take(".")
                cast = take()
            require(cast in {"text", "name"}, "pcc_expression_cast")
            redundant = (value[0] == "literal" or (
                cast == "text" and value[0] == "column" and types[value[1]] in {"varchar", "text"}))
            if not redundant:
                value = ("cast", cast, value)
        return value

    def parse(minimum):
        left = atom()
        precedence = {"or": 1, "and": 2, "=": 3, "<>": 3, "<": 3,
                      ">": 3, "<=": 3, ">=": 3, "~": 3, "is": 3}
        while peek() in precedence and precedence[peek()] >= minimum:
            operator = take()
            if operator == "is":
                negated = peek() == "not"
                if negated:
                    take("not")
                take("null")
                left = ("is not null" if negated else "is null", left)
            else:
                right = parse(precedence[operator] + 1)
                left = (operator, left, right)
        return left

    result = parse(0)
    require(position == len(tokens), "pcc_expression_tail")
    return result


async def header(conn, name, owner):
    row = await conn.fetchrow("""SELECT c.oid,c.relkind::text AS kind,
        c.relpersistence::text AS persistence,pg_catalog.pg_get_userbyid(c.relowner) AS owner,
        c.relrowsecurity,c.relforcerowsecurity,c.reloptions,c.reltablespace,
        c.relreplident::text AS replica,
        NOT EXISTS(SELECT 1 FROM pg_catalog.pg_inherits i
          WHERE i.inhrelid=c.oid OR i.inhparent=c.oid) AS no_inheritance
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='core' AND c.relname=$1""", name)
    if row is None:
        return None
    require(row['kind'] == 'r' and row['persistence'] == 'p' and row['owner'] == owner
        and not row['relrowsecurity'] and not row['relforcerowsecurity'] and row['no_inheritance'], 'pcc_relation')
    return dict(row)


async def table_acl(conn, oid, owner):
    rights = await conn.fetch("""SELECT pg_catalog.pg_get_userbyid(a.grantor) AS grantor,
        CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_catalog.pg_get_userbyid(a.grantee) END AS grantee,
        a.privilege_type,a.is_grantable FROM pg_catalog.pg_class c CROSS JOIN LATERAL
        pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
        WHERE c.oid=$1""", oid)
    require(len(rights) == 7 and {r['privilege_type'] for r in rights} == {
        'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'}
        and all(r['grantor'] == r['grantee'] == owner and not r['is_grantable'] for r in rights), 'pcc_acl')
    require(not await conn.fetchval("""SELECT
        EXISTS(SELECT 1 FROM pg_catalog.pg_attribute WHERE attrelid=$1 AND attnum>0 AND attacl IS NOT NULL)
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_policy WHERE polrelid=$1)
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_rewrite WHERE ev_class=$1)
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_seclabel WHERE classoid='pg_catalog.pg_class'::regclass AND objoid=$1)
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_publication_rel WHERE prrelid=$1)""", oid), 'pcc_relation_extras')


def flags(key):
    require(key['validated'] and not key['deferrable'] and not key['deferred']
            and key['local'] and key['inherited'] == 0, 'pcc_constraint_flags')


def verify_columns(actual, expected, *, exact=True):
    require(len(actual) == len(expected) if exact else len(actual) >= len(expected), 'pcc_columns')
    by_name = {c['name']: c for c in actual}
    types = {c['name']: c['type'] for c in expected}
    for position, wanted in enumerate(expected, 1):
        row = by_name.get(wanted['name'])
        require(row is not None and row['type_schema'] == 'pg_catalog'
            and row['type'] == wanted['type'] and row['typmod'] == wanted['typmod']
            and row['not_null'] == wanted['not_null'] and row['identity'] == row['generated'] == ''
            and not row['dropped'] and row['default_collation']
            and expression(row['default_expr'], types) == expression(wanted['default'], types), 'pcc_column')
        require(not exact or row['attnum'] == position, 'pcc_column_order')
    return {r['attnum']: r['name'] for r in actual}


async def verify_index(conn, row, wanted, names, types, owner):
    require(row['namespace'] == 'core' and row['owner'] == owner and row['method'] == 'btree'
        and row['kind'] == 'i' and row['persistence'] == 'p' and row['default_acl']
        and row['valid'] and row['ready'] and row['live'] and row['immediate']
        and not row['exclusion'] and not row['nulls_not_distinct'] and row['no_expression']
        and row['default_collations'] and row['key_count'] == row['total_count'] == len(wanted['columns'])
        and [names.get(k) for k in row['keys']] == wanted['columns']
        and row['options'] == [0] * len(wanted['columns'])
        and row['unique'] == wanted['unique'] and row['primary'] == wanted['primary'], 'pcc_index')
    ops = {'uuid': 'uuid_ops', 'text': 'text_ops', 'varchar': 'text_ops'}
    require(row['opclasses'] == ['pg_catalog.' + ops[types[n]] for n in wanted['columns']], 'pcc_index_ops')
    extra = await conn.fetchrow("""SELECT pg_catalog.pg_get_expr(i.indpred,i.indrelid,false) AS predicate,
        c.reloptions,c.reltablespace FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid WHERE i.indexrelid=$1""", row['oid'])
    require(extra['reloptions'] is None and extra['reltablespace'] == 0
        and expression(extra['predicate'], types) == expression(wanted['predicate'], types), 'pcc_index_predicate')


async def prerequisites(conn, contract, owner):
    spec = contract['prerequisites']['companies']
    row = await header(conn, 'companies', owner)
    require(row is not None, 'pcc_company_prerequisite')
    names = verify_columns(await columns(conn, row['oid']), spec['columns'], exact=False)
    keys = [k for k in await constraints(conn, row['oid'])
            if k['kind'] == 'p' and [names.get(n) for n in k['keys']] == ['id']]
    require(len(keys) == 1, 'pcc_company_key')
    flags(keys[0])
    found = [i for i in await indexes(conn, row['oid']) if i['oid'] == keys[0]['index_oid']]
    require(len(found) == 1, 'pcc_company_index')
    await verify_index(conn, found[0], {'columns': ['id'], 'unique': True, 'primary': True,
        'predicate': None}, names, {'id': 'uuid'}, owner)
    return {'companies': {**row, 'attributes': names}}


async def fk_triggers(conn, key, child, parent):
    rows = await conn.fetch("""SELECT t.tgrelid,t.tgconstrrelid,t.tgtype,t.tgenabled::text AS enabled,
        t.tgisinternal,t.tgdeferrable,t.tginitdeferred,t.tgqual IS NULL AS no_qualifier,
        p.proname,n.nspname FROM pg_catalog.pg_trigger t
        JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
        JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE t.tgconstraint=$1""", key['oid'])
    expected = {(child, parent, 5, 'RI_FKey_check_ins'), (child, parent, 17, 'RI_FKey_check_upd'),
                (parent, child, 9, 'RI_FKey_restrict_del'), (parent, child, 17, 'RI_FKey_noaction_upd')}
    require(len(rows) == 4 and {(r['tgrelid'], r['tgconstrrelid'], r['tgtype'], r['proname']) for r in rows} == expected
        and all(r['enabled'] == 'O' and r['tgisinternal'] and not r['tgdeferrable']
            and not r['tginitdeferred'] and r['no_qualifier'] and r['nspname'] == 'pg_catalog' for r in rows), 'pcc_fk_triggers')
    require(not await conn.fetchval("SELECT confdelsetcols IS NOT NULL FROM pg_catalog.pg_constraint WHERE oid=$1", key['oid']), 'pcc_fk_columns')


async def own_table(conn, spec, row, parents, owner):
    oid = row['oid']
    require(row['reloptions'] is None and row['reltablespace'] == 0 and row['replica'] == 'd', 'pcc_table_options')
    await table_acl(conn, oid, owner)
    require(await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_am a ON a.oid=c.relam WHERE c.oid=$1 AND a.amname='heap')
        AND EXISTS(SELECT 1 FROM pg_catalog.pg_type t
          JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace JOIN pg_catalog.pg_type ar ON ar.oid=t.typarray
          WHERE t.typrelid=$1 AND t.typname=$2 AND ar.typname='_'||$2
            AND t.typtype='c' AND t.typisdefined AND t.typacl IS NULL AND n.nspname='core'
            AND pg_catalog.pg_get_userbyid(t.typowner)=current_user AND ar.typacl IS NULL
            AND ar.typowner=t.typowner AND ar.typnamespace=t.typnamespace)""", oid, spec['name']), 'pcc_table_type')
    names = verify_columns(await columns(conn, oid), spec['columns'])
    types = {c['name']: c['type'] for c in spec['columns']}
    expected = {spec['name'] + '_pkey': ('p', spec['primary'])}
    expected.update({n: ('u', v) for n, v in spec['unique'].items()})
    expected.update({n: ('c', v) for n, v in spec['checks'].items()})
    expected.update({n: ('f', v) for n, v in spec['foreign_keys'].items()})
    keys = await constraints(conn, oid)
    require(len(keys) == len(expected) and {k['name'] for k in keys} == set(expected), 'pcc_constraints')
    for key in keys:
        flags(key)
        kind, wanted = expected[key['name']]
        require(key['kind'] == kind, 'pcc_constraint_kind')
        extra = await conn.fetchrow('SELECT connoinherit,conparentid FROM pg_catalog.pg_constraint WHERE oid=$1', key['oid'])
        require(extra['conparentid'] == 0, 'pcc_constraint_parent')
        if kind in {'p', 'u'}:
            require([names.get(n) for n in key['keys']] == wanted, 'pcc_key')
        elif kind == 'c':
            require(not extra['connoinherit'], 'pcc_check_inheritance')
            require(expression(key['expression'], types) == expression(wanted, types), 'pcc_check')
            require(not await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_depend d
                JOIN pg_catalog.pg_proc p ON d.refclassid='pg_catalog.pg_proc'::regclass AND d.refobjid=p.oid
                JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                WHERE d.classid='pg_catalog.pg_constraint'::regclass AND d.objid=$1 AND n.nspname<>'pg_catalog')""", key['oid']), 'pcc_check_function_namespace')
        else:
            parent = parents[wanted['table']]
            require(key['target_oid'] == parent['oid'] and [names.get(n) for n in key['keys']] == wanted['columns']
                and [parent['attributes'].get(n) for n in key['target_keys']] == wanted['target_columns']
                and key['delete_action'] == 'r' and key['update_action'] == 'a' and key['match'] == 's', 'pcc_fk')
            await fk_triggers(conn, key, oid, parent['oid'])
    actual_indexes = await indexes(conn, oid)
    require(len(actual_indexes) == len(spec['indexes']) and {i['name'] for i in actual_indexes} == set(spec['indexes']), 'pcc_indexes')
    for index in actual_indexes:
        await verify_index(conn, index, spec['indexes'][index['name']], names, types, owner)


async def functions(conn, contract, owner):
    ids = {}
    for name, body in contract['functions'].items():
        rows = await conn.fetch("""SELECT p.oid,pg_catalog.pg_get_userbyid(p.proowner) AS owner,
            p.prosrc,p.probin,p.prosecdef,p.proleakproof,p.proisstrict,p.proretset,p.prokind::text,
            p.provolatile::text,p.proparallel::text,p.pronargs,p.pronargdefaults,p.proconfig,
            p.prorettype='pg_catalog.trigger'::regtype AS trigger_return,l.lanname,
            p.procost,p.prorows,p.prosupport::oid AS prosupport,p.proargnames,p.proargmodes,p.proallargtypes,
            p.prosqlbody IS NULL AS no_sql_body FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            JOIN pg_catalog.pg_language l ON l.oid=p.prolang WHERE n.nspname='core' AND p.proname=$1""", name)
        require(len(rows) == 1, 'pcc_function')
        p = rows[0]
        require(p['owner'] == owner and p['prosrc'] == body and p['probin'] is None
            and not p['prosecdef'] and not p['proleakproof'] and not p['proisstrict'] and not p['proretset']
            and p['prokind'] == 'f' and p['provolatile'] == 'v' and p['proparallel'] == 'u'
            and p['pronargs'] == p['pronargdefaults'] == 0 and p['trigger_return'] and p['lanname'] == 'plpgsql'
            and p['proconfig'] == ['search_path=pg_catalog, core'] and p['procost'] == 100
            and p['prorows'] == 0 and p['prosupport'] == 0 and p['proargnames'] is None
            and p['proargmodes'] is None and p['proallargtypes'] is None and p['no_sql_body'], 'pcc_function_shape')
        rights = await conn.fetch("""SELECT pg_catalog.pg_get_userbyid(a.grantor) AS grantor,
            pg_catalog.pg_get_userbyid(a.grantee) AS grantee,a.privilege_type,a.is_grantable
            FROM pg_catalog.pg_proc p CROSS JOIN LATERAL
            pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE p.oid=$1""", p['oid'])
        require(len(rights) == 1 and rights[0]['grantor'] == rights[0]['grantee'] == owner
            and rights[0]['privilege_type'] == 'EXECUTE' and not rights[0]['is_grantable'], 'pcc_function_acl')
        ids[name] = p['oid']
    return ids


async def inspect(conn, contract, owner, *, applied):
    """Refuse unknown occupancy before DDL, verify every own object after apply."""
    reserved = list(contract['tables']) + ['_' + n for n in contract['tables']]
    reserved += [n for t in contract['tables'].values() for n in t['indexes']]
    if not applied:
        occupied = await conn.fetchval("""SELECT
            EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='core' AND c.relname=ANY($1::text[]))
            OR EXISTS(SELECT 1 FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
                WHERE n.nspname='core' AND t.typname=ANY($1::text[]))
            OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname='core' AND p.proname=ANY($2::text[]))""", reserved, list(contract['functions']))
        require(not occupied, 'pcc_unrecorded_occupancy')
        return None
    headers = {n: await header(conn, n, owner) for n in contract['tables']}
    require(all(headers.values()), 'pcc_missing_applied_table')
    parents = await prerequisites(conn, contract, owner)
    for name, row in headers.items():
        parents[name] = {**row, 'attributes': verify_columns(await columns(conn, row['oid']), contract['tables'][name]['columns'])}
    for name, row in headers.items():
        await own_table(conn, contract['tables'][name], row, parents, owner)
    own_ids = [r['oid'] for r in headers.values()]
    require(not await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint
        WHERE confrelid=ANY($1::oid[]) AND conrelid<>ALL($1::oid[]))""", own_ids), 'pcc_foreign_dependents')
    function_ids = await functions(conn, contract, owner)
    triggers = await conn.fetch("""SELECT t.tgname,t.tgrelid,t.tgfoid,t.tgtype,t.tgenabled::text AS enabled,
        t.tgconstraint,t.tgdeferrable,t.tginitdeferred,t.tgnargs,t.tgattr::smallint[] AS attrs,
        t.tgqual IS NULL AS no_qualifier,t.tgoldtable,t.tgnewtable,t.tgparentid,
        t.tgconstrrelid,t.tgconstrindid,pg_catalog.octet_length(t.tgargs) AS argument_bytes
        FROM pg_catalog.pg_trigger t WHERE NOT t.tgisinternal
        AND (t.tgrelid=ANY($1::oid[]) OR t.tgfoid=ANY($2::oid[]))""", own_ids, list(function_ids.values()))
    require(len(triggers) == len(contract['triggers']) and {t['tgname'] for t in triggers} == set(contract['triggers']), 'pcc_triggers')
    for t in triggers:
        wanted = contract['triggers'][t['tgname']]
        require(t['tgrelid'] == headers[wanted['table']]['oid'] and t['tgfoid'] == function_ids[wanted['function']]
            and t['tgtype'] == wanted['type'] and t['enabled'] == 'O' and t['tgconstraint'] == 0
            and not t['tgdeferrable'] and not t['tginitdeferred'] and t['tgnargs'] == 0
            and not t['attrs'] and t['no_qualifier'] and t['tgoldtable'] is None and t['tgnewtable'] is None
            and t['tgparentid'] == t['tgconstrrelid'] == t['tgconstrindid'] == t['argument_bytes'] == 0, 'pcc_trigger')
    return headers
