"""Revision0006 closed PG16 catalogue; no application/ORM imports or repair.

Frozen0004 low-level exact table/FK/index verifiers remain unchanged. This
revision owns its new native tenant keys and complete altered resource tables;
it never supplies a modified contract to a frozen revision's inspect function.
"""
from copy import deepcopy
import re

from schema_migrations.revisions.catalog_partner_contract_create_v1 import (
    acl, expression, foreign_key_triggers, header, prerequisites as native_prerequisites,
    verify_index,
)
from schema_migrations.revisions.catalog_v1 import (
    columns, constraints, constraint_flags, indexes, require, verify_columns,
)


def _check_expression(source):
    # PG's varchar IN deparser may use a varchar[] -> text[] coercion.
    # Only textual casts are erased; boolean grouping remains in expression().
    # Function namespaces/dependencies are independently checked below.
    source = re.sub(r"'(?:[^']|'')*'|::(?:character varying|varchar|text)\b(?:\[\])?",
        lambda match: match.group() if match.group().startswith("'") else "", source)
    return expression(source)


async def own_table(conn, spec, row, parents, owner):
    oid = row['oid']
    require(row['reloptions'] is None and row['reltablespace'] == 0 and row['replica'] == 'd', 'site_table_options')
    await acl(conn, oid, owner)
    require(await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_am a ON a.oid=c.relam WHERE c.oid=$1 AND a.amname='heap')
        AND EXISTS(SELECT 1 FROM pg_catalog.pg_type t
          JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
          JOIN pg_catalog.pg_type ar ON ar.oid=t.typarray
          WHERE t.typrelid=$1 AND t.typname=$2 AND ar.typname='_'||$2
            AND t.typtype='c' AND t.typisdefined AND t.typacl IS NULL
            AND n.nspname='core' AND pg_catalog.pg_get_userbyid(t.typowner)=current_user
            AND ar.typacl IS NULL AND ar.typowner=t.typowner AND ar.typnamespace=t.typnamespace)""", oid, spec['name']), 'site_owned_type')
    names = verify_columns(await columns(conn, oid), spec['columns'])
    expected = {spec['name'] + '_pkey': ('p', spec['primary'])}
    expected.update({n: ('u', c) for n, c in spec['unique'].items()})
    expected.update({n: ('c', c) for n, c in spec['checks'].items()})
    expected.update({n: ('f', c) for n, c in spec['foreign_keys'].items()})
    keys = await constraints(conn, oid)
    require(len(keys) == len(expected) and {k['name'] for k in keys} == set(expected), 'site_constraints')
    for key in keys:
        constraint_flags(key)
        kind, wanted = expected[key['name']]
        require(key['kind'] == kind, 'site_constraint_kind')
        extra = await conn.fetchrow('SELECT connoinherit,conparentid FROM pg_catalog.pg_constraint WHERE oid=$1', key['oid'])
        require(not extra['connoinherit'] and extra['conparentid'] == 0, 'site_constraint_flags')
        if kind in {'p', 'u'}:
            require([names.get(n) for n in key['keys']] == wanted, 'site_key')
        elif kind == 'c':
            require(_check_expression(key['expression']) == _check_expression(wanted), 'site_check')
        else:
            parent = parents[wanted['table']]
            require(key['target_oid'] == parent['oid'] and [names.get(n) for n in key['keys']] == wanted['columns']
                and [parent['attributes'].get(n) for n in key['target_keys']] == wanted['target_columns']
                and key['delete_action'] == wanted['delete'] and key['update_action'] == 'a' and key['match'] == 's', 'site_fk')
            await foreign_key_triggers(conn, key, oid, parent['oid'], wanted['delete'])
    actual_indexes = await indexes(conn, oid)
    require(len(actual_indexes) == len(spec['indexes']) and {i['name'] for i in actual_indexes} == set(spec['indexes']), 'site_indexes')
    for index in actual_indexes:
        await verify_index(conn, index, spec['indexes'][index['name']], names,
            {c['name']: c['type'] for c in spec['columns']}, owner)


async def prerequisites(conn, contract, owner):
    return await native_prerequisites(conn, contract, owner)


async def _tenant_keys(conn, contract, owner, parents, applied):
    for table, spec in contract['tenant_keys'].items():
        row = parents[table]
        matches = [k for k in await constraints(conn, row['oid']) if k['name'] == spec['name']]
        if not applied:
            require(not matches, 'site_unrecorded_tenant_key')
            continue
        require(len(matches) == 1, 'site_tenant_key')
        key = matches[0]
        constraint_flags(key)
        require(key['kind'] == 'u' and [row['attributes'].get(n) for n in key['keys']] == spec['columns'], 'site_tenant_key')
        found = [i for i in await indexes(conn, row['oid']) if i['oid'] == key['index_oid']]
        require(len(found) == 1, 'site_tenant_index')
        await verify_index(conn, found[0], {'columns': spec['columns'], 'unique': True,
            'primary': False, 'predicate': None}, row['attributes'],
            {c['name']: c['type'] for c in contract['prerequisites'][table]['columns']}, owner)


async def _unapplied_occupancy(conn, contract):
    # Old prefixes may legitimately lack every native Site parent. Only names
    # and deltas owned by6 are inspected here; never require those parents.
    reserved = list(contract['tables']) + ['_' + n for n in contract['tables']]
    reserved += [n for t in contract['tables'].values() for n in t['indexes']]
    reserved += [s['name'] for s in contract['tenant_keys'].values()]
    require(not await conn.fetchval("""SELECT
        EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='core' AND c.relname=ANY($1::text[]))
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
            WHERE n.nspname='core' AND t.typname=ANY($1::text[]))
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='core' AND c.relname='partner_resource_items' AND a.attname='site_id' AND NOT a.attisdropped)
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='core' AND k.conname=ANY($2::text[]))""", reserved,
            ['ck_partner_sites_mode', 'fk_partner_resource_site'] + [s['name'] for s in contract['tenant_keys'].values()]), 'site_unrecorded_occupancy')
    # Detect a replaced existing CHECK even if no new table/column survived.
    for table, checks in contract['before_checks'].items():
        oid = await conn.fetchval("SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='core' AND c.relname=$1", table)
        if oid is not None:
            for key in await constraints(conn, oid):
                if key['name'] in checks:
                    require(key['kind'] == 'c' and _check_expression(key['expression']) == _check_expression(checks[key['name']]), 'site_unrecorded_check')


async def inspect(conn, contract, owner, *, applied, preparing=False):
    if not applied:
        await _unapplied_occupancy(conn, contract)
        if not preparing:
            return None
    parents = await prerequisites(conn, contract, owner)
    await _tenant_keys(conn, contract, owner, parents, applied)
    specs = deepcopy(contract['altered_tables'])
    if applied:
        specs.update(contract['tables'])
    else:
        # Exact native prefix5 predecessor. No adoption of a partially applied6.
        specs['partner_resource_items']['columns'] = [c for c in specs['partner_resource_items']['columns'] if c['name'] != 'site_id']
        del specs['partner_resource_items']['foreign_keys']['fk_partner_resource_site']
        for table, checks in contract['before_checks'].items():
            specs[table]['checks'] = checks
    headers = {name: await header(conn, name, owner) for name in specs}
    require(all(headers.values()), 'site_missing_table')
    for name, row in headers.items():
        parents[name] = {**row, 'attributes': verify_columns(await columns(conn, row['oid']), specs[name]['columns'])}
    for name, row in headers.items():
        await own_table(conn, specs[name], row, parents, owner)
        # No custom functions hidden in the finite CHECK grammar, custom row
        # triggers, rules/policies/ACL or additional dependencies on new tables.
        require(not await conn.fetchval("""SELECT
            EXISTS(SELECT 1 FROM pg_catalog.pg_trigger WHERE tgrelid=$1 AND NOT tgisinternal)
            OR EXISTS(SELECT 1 FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_depend d
                ON d.classid='pg_catalog.pg_constraint'::regclass AND d.objid=c.oid
                JOIN pg_catalog.pg_proc p ON d.refclassid='pg_catalog.pg_proc'::regclass AND d.refobjid=p.oid
                JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                WHERE c.conrelid=$1 AND c.contype='c' AND n.nspname<>'pg_catalog')""", row['oid']), 'site_table_extras')
    if applied:
        ids = [headers[n]['oid'] for n in contract['tables']]
        require(not await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint
            WHERE confrelid=ANY($1::oid[]) AND conrelid<>ALL($1::oid[]))""", ids), 'site_foreign_dependents')
    return headers if applied else None
