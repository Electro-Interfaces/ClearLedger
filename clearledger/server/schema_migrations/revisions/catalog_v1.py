"""Frozen PG16 catalog verifier for revision 0001, with no application imports.

CHECK normalization is intentionally limited to this frozen contract's simple
numeric bounds and literal action alternatives; it is not a general SQL prover.
"""
import re

from schema_migrations.errors import MigrationError


def require(value, phase="catalog"):
    if not value:
        raise MigrationError(4, phase)


def normalize_check(value):
    # Preserve every byte within SQL string literals, including case/whitespace.
    # Only discard outside whitespace/parentheses and PG16's literal ::text cast.
    tokens = re.findall(r"'(?:[^']|'')*'|::|\s+|[()]|[^\s()':]+|.", value)
    tokens = [token for token in tokens if not token.isspace() and token not in {"(", ")"}]
    output = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if (token == "::" and index + 1 < len(tokens) and tokens[index + 1] == "text"
                and output and output[-1].startswith("'")):
            index += 2
            continue
        output.append(token)
        index += 1
    return "".join(output)


async def relation(conn, name, owner):
    row = await conn.fetchrow("""SELECT c.oid, n.oid AS namespace_oid, c.relkind::text AS relkind,
        c.relpersistence::text AS relpersistence, pg_catalog.pg_get_userbyid(c.relowner) AS owner,
        c.relrowsecurity, c.relforcerowsecurity, c.relacl IS NULL AS default_acl,
        NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger t
            WHERE t.tgrelid=c.oid AND NOT t.tgisinternal) AS no_triggers,
        NOT EXISTS (SELECT 1 FROM pg_catalog.pg_inherits i
            WHERE i.inhrelid=c.oid OR i.inhparent=c.oid) AS no_inheritance
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='core' AND c.relname=$1""", name)
    if row is None:
        return None
    require(row["relkind"] == "r" and row["relpersistence"] == "p"
        and row["owner"] == owner and not row["relrowsecurity"] and not row["relforcerowsecurity"]
        and row["default_acl"] and row["no_triggers"] and row["no_inheritance"], "relation")
    return dict(row)


async def columns(conn, oid):
    return [dict(row) for row in await conn.fetch("""SELECT a.attnum, a.attname AS name,
        t.typname AS type, tn.nspname AS type_schema, a.atttypmod AS typmod,
        a.attnotnull AS not_null, a.attidentity::text AS identity, a.attgenerated::text AS generated,
        a.attisdropped AS dropped, a.attcollation=t.typcollation AS default_collation,
        pg_catalog.pg_get_expr(d.adbin,d.adrelid,false) AS default_expr
        FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_type t ON t.oid=a.atttypid
        JOIN pg_catalog.pg_namespace tn ON tn.oid=t.typnamespace
        LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid=$1 AND a.attnum>0 ORDER BY a.attnum""", oid)]


def verify_columns(actual, expected, *, exact=True):
    by_name = {row["name"]: row for row in actual}
    require(len(actual) == len(expected) if exact else len(actual) >= len(expected), "columns")
    for position, wanted in enumerate(expected, 1):
        row = by_name.get(wanted["name"])
        require(row is not None, "columns")
        require(row["type_schema"] == "pg_catalog" and row["type"] == wanted["type"]
            and row["typmod"] == wanted["typmod"] and row["not_null"] == wanted["not_null"]
            and row["default_expr"] == wanted["default"] and row["identity"] == ""
            and row["generated"] == "" and not row["dropped"] and row["default_collation"], "columns")
        if exact:
            require(row["attnum"] == position, "column_order")
    return {row["attnum"]: row["name"] for row in actual}


async def constraints(conn, oid):
    return [dict(row) for row in await conn.fetch("""SELECT oid, conname AS name, contype::text AS kind,
        conkey AS keys, confrelid AS target_oid, confkey AS target_keys,
        confupdtype::text AS update_action, confdeltype::text AS delete_action, confmatchtype::text AS match,
        convalidated AS validated, condeferrable AS deferrable, condeferred AS deferred,
        conislocal AS local, coninhcount AS inherited, conindid AS index_oid,
        pg_catalog.pg_get_expr(conbin,conrelid,false) AS expression
        FROM pg_catalog.pg_constraint WHERE conrelid=$1 ORDER BY contype,conname""", oid)]


async def indexes(conn, oid):
    return [dict(row) for row in await conn.fetch("""SELECT ic.oid, ic.relname AS name,
        ns.nspname AS namespace, pg_catalog.pg_get_userbyid(ic.relowner) AS owner,
        am.amname AS method, ic.relkind::text AS kind, ic.relpersistence::text AS persistence,
        ic.relacl IS NULL AS default_acl, i.indisvalid AS valid, i.indisready AS ready,
        i.indislive AS live, i.indisunique AS "unique", i.indisprimary AS "primary",
        i.indisexclusion AS exclusion, i.indimmediate AS immediate,
        i.indnullsnotdistinct AS nulls_not_distinct, i.indnkeyatts AS key_count,
        i.indnatts AS total_count, i.indkey::smallint[] AS keys, i.indoption::smallint[] AS options,
        i.indexprs IS NULL AS no_expression, i.indpred IS NULL AS no_predicate,
        NOT EXISTS (SELECT 1 FROM unnest(i.indkey::smallint[],i.indcollation::oid[]) u(attnum,coll)
            JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=u.attnum
            WHERE u.coll<>a.attcollation) AS default_collations,
        ARRAY(SELECT pn.nspname||'.'||p.opcname FROM unnest(i.indclass::oid[]) WITH ORDINALITY u(id,n)
            JOIN pg_catalog.pg_opclass p ON p.oid=u.id
            JOIN pg_catalog.pg_namespace pn ON pn.oid=p.opcnamespace ORDER BY u.n) AS opclasses
        FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class ic ON ic.oid=i.indexrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid=ic.relnamespace
        JOIN pg_catalog.pg_am am ON am.oid=ic.relam
        WHERE i.indrelid=$1 ORDER BY ic.relname""", oid)]


def verify_index(row, expected, names, owner):
    require(row["namespace"] == "core" and row["owner"] == owner and row["method"] == "btree"
        and row["valid"] and row["ready"] and row["live"] and not row["exclusion"]
        and row["immediate"] and not row["nulls_not_distinct"]
        and row["no_expression"] and row["no_predicate"] and row["default_collations"]
        and row["kind"] == "i" and row["persistence"] == "p" and row["default_acl"], "index")
    require(row["key_count"] == row["total_count"] == len(expected["columns"])
        and [names.get(key) for key in row["keys"]] == expected["columns"]
        and row["options"] == [0] * len(expected["columns"])
        and row["opclasses"] == expected["opclasses"]
        and row["unique"] == expected["unique"] and row["primary"] == expected["primary"], "index")
    if expected.get("name"):
        require(row["name"] == expected["name"], "index_name")


def constraint_flags(row):
    require(row["validated"] and not row["deferrable"] and not row["deferred"]
        and row["local"] and row["inherited"] == 0, "constraint")


async def verify_fk_triggers(conn, constraint_oid, child_oid, parent_oid):
    rows = await conn.fetch("""SELECT t.tgrelid, t.tgconstrrelid, t.tgenabled::text AS enabled,
        t.tgisinternal AS internal, t.tgdeferrable AS deferrable, t.tginitdeferred AS deferred,
        t.tgtype AS kind, t.tgqual IS NULL AS no_qualifier, n.nspname AS function_schema,
        p.proname AS function_name
        FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
        JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        WHERE t.tgconstraint=$1""", constraint_oid)
    wanted = {
        (child_oid,parent_oid,5,'RI_FKey_check_ins'),
        (child_oid,parent_oid,17,'RI_FKey_check_upd'),
        (parent_oid,child_oid,9,'RI_FKey_cascade_del'),
        (parent_oid,child_oid,17,'RI_FKey_noaction_upd'),
    }
    require(len(rows)==4 and {(r['tgrelid'],r['tgconstrrelid'],r['kind'],r['function_name'])
        for r in rows}==wanted, 'foreign_key_triggers')
    require(all(r['enabled']=='O' and r['internal'] and not r['deferrable'] and not r['deferred']
        and r['no_qualifier'] and r['function_schema']=='pg_catalog' for r in rows), 'foreign_key_triggers')


async def inspect_prerequisites(conn, contract, owner):
    parent = await relation(conn, "partner_installations", owner)
    require(parent is not None, "prerequisite")
    spec = contract["parent"]
    names = verify_columns(await columns(conn, parent["oid"]), spec["columns"], exact=False)
    keys = await constraints(conn, parent["oid"])
    expected = spec["unique"]
    found = [row for row in keys if row["kind"] == "u"
        and [names.get(key) for key in row["keys"]] == expected["columns"]]
    require(len(found) == 1, "parent_unique")
    constraint_flags(found[0])
    ix = [row for row in await indexes(conn, parent["oid"]) if row["oid"] == found[0]["index_oid"]]
    require(len(ix) == 1, "parent_unique")
    verify_index(ix[0], expected, names, owner)
    return {**parent, "attribute_names": names}


async def verify_table(conn, spec, owner, *, parent=None):
    header = await relation(conn, spec["name"], owner)
    if header is None:
        return None
    oid = header["oid"]
    names = verify_columns(await columns(conn, oid), spec["columns"])
    keys = await constraints(conn, oid)
    counts = {kind: len([row for row in keys if row["kind"] == kind]) for kind in {r["kind"] for r in keys}}
    require(counts == spec["constraint_counts"], "constraints")
    for row in keys:
        constraint_flags(row)
        if row["kind"] in {"p", "u"}:
            wanted = spec["primary"] if row["kind"] == "p" else spec["unique"]
            require([names.get(key) for key in row["keys"]] == wanted, "key")
        elif row["kind"] == "c":
            require(row["name"] in spec["checks"] and normalize_check(row["expression"]) ==
                normalize_check(spec["checks"][row["name"]]), "check")
        elif row["kind"] == "f":
            wanted = spec["foreign_key"]
            require(parent is not None and row["target_oid"] == parent["oid"]
                and [names.get(key) for key in row["keys"]] == wanted["columns"]
                and [parent["attribute_names"].get(key) for key in row["target_keys"]] == wanted["target_columns"]
                and row["delete_action"] == "c" and row["update_action"] == "a" and row["match"] == "s", "foreign_key")
            await verify_fk_triggers(conn, row["oid"], oid, parent["oid"])
    ix = await indexes(conn, oid)
    require(len(ix) == len(spec["indexes"]), "indexes")
    for expected in spec["indexes"]:
        matches = [row for row in ix if row["primary"] == expected["primary"]
            and row["unique"] == expected["unique"]
            and [names.get(key) for key in row["keys"]] == expected["columns"]]
        require(len(matches) == 1, "indexes")
        verify_index(matches[0], expected, names, owner)
    return header
