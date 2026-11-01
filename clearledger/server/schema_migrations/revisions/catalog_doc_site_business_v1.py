"""Revision7 owns its exact cumulative6+7 catalogue; SELECT only.

Frozen inspect6 receives ONLY its original spec and only for history<=6.
This module uses honest revision7 specs and shared low-level readers, never a
projection or modified contract passed into an old inspect function.
"""
import re

from schema_migrations.revisions.catalog_partner_contract_create_v1 import (
    acl, header, prerequisites,
)
from schema_migrations.revisions.catalog_site_authority_v1 import _tenant_keys, own_table
from schema_migrations.revisions.catalog_v1 import (
    columns, constraints, constraint_flags, indexes, require, verify_columns,
)


def expression(source, types):
    """Finite SQL expression parser, preserving CASE barriers and grouping.

    Only redundant PG textual coercions are ignored. Integer/date casts stay
    significant; the two PG spellings of the one literal interval coincide.
    Unknown syntax, identifiers, functions and namespaces are rejected.
    """
    if source is None:
        return None
    scanner = re.compile(r'''\s+|'(?:[^']|'')*'|"[a-z_][a-z_0-9]*"|::|<=|>=|<>|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[().,=~<>+]''')
    tokens, end = [], 0
    for match in scanner.finditer(source):
        require(match.start() == end, "dsite_expression")
        end = match.end()
        value = match.group()
        if not value.isspace():
            tokens.append(value if value.startswith("'") else value.strip('"').lower())
    require(end == len(source), "dsite_expression")
    position = 0

    def peek():
        return tokens[position] if position < len(tokens) else None

    def take(wanted=None):
        nonlocal position
        value = peek()
        require(value is not None and (wanted is None or value == wanted), "dsite_expression")
        position += 1
        return value

    def interval(value):
        require(value in {"'1 month - 1 day'", "'1 mon -1 days'"}, "dsite_interval")
        return ("interval", "one_month_minus_one_day")

    def atom():
        token = take()
        if token == "(":
            value = parse(0)
            take(")")
        elif token == "case":
            branches = []
            while peek() == "when":
                take("when")
                condition = parse(0)
                take("then")
                branches.append((condition, parse(0)))
            take("else")
            otherwise = parse(0)
            take("end")
            value = ("case", tuple(branches), otherwise)
        elif token == "interval":
            value = interval(take())
        elif token.startswith("'"):
            value = ("literal", token)
        elif token.isdigit():
            value = ("number", token)
        elif token in {"true", "false"}:
            value = ("boolean", token)
        else:
            if peek() == ".":
                require(token == "pg_catalog", "dsite_namespace")
                take(".")
                token = take()
            if peek() == "(":
                require(token in {"substring", "make_date", "extract", "coalesce"}, "dsite_function")
                take("(")
                if token == "extract":
                    take("day")
                    take("from")
                    args = [parse(0)]
                else:
                    args = [parse(0)]
                    while peek() == ",":
                        take(",")
                        args.append(parse(0))
                take(")")
                value = ("call", token, tuple(args))
            else:
                require(token in types, "dsite_column")
                value = ("column", token)
        while peek() == "::":
            take("::")
            cast = take()
            if cast == "pg_catalog":
                take(".")
                cast = take()
            if cast == "character":
                take("varying")
                cast = "varchar"
            require(cast in {"text", "varchar", "integer", "date", "interval", "numeric"}, "dsite_cast")
            if cast == "interval":
                require(value[0] == "literal", "dsite_interval")
                value = interval(value[1])
            elif cast in {"text", "varchar"} and (value[0] == "literal" or (
                    value[0] == "column" and types[value[1]] in {"varchar", "text"})):
                pass
            elif cast == "numeric" and value[0:2] == ("cast", "integer"):
                pass  # PG integer->numeric comparison coercion, exact integers
            else:
                value = ("cast", cast, value)
        return value

    def parse(minimum):
        left = atom()
        precedence = {"or": 1, "and": 2, "=": 3, "<>": 3, "<": 3, ">": 3,
                      "<=": 3, ">=": 3, "~": 3, "is": 3, "+": 4}
        while peek() in precedence and precedence[peek()] >= minimum:
            op = take()
            if op == "is":
                negated = peek() == "not"
                if negated:
                    take("not")
                take("null")
                left = ("is not null" if negated else "is null", left)
            else:
                left = (op, left, parse(precedence[op] + 1))
        return left

    result = parse(0)
    require(position == len(tokens), "dsite_expression_tail")
    return result


async def unrecorded(conn, contract):
    """Reject any partial7 before ancestor DDL, including the replaced old index."""
    names = ["uq_site_context_organization", "uq_ops_term_site"]
    names += [n for t in contract["native_tables"].values() for n in (*t["checks"], *t["foreign_keys"])]
    require(not await conn.fetchval("""SELECT
        EXISTS(SELECT 1 FROM pg_catalog.pg_attribute a
          JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
          JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='core' AND NOT a.attisdropped AND
            ((c.relname='contracts' AND a.attname='validity_kind') OR
             (c.relname IN ('doc_cards','ops_contract_terms') AND a.attname='site_id')))
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_constraint k
          JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='core' AND k.conname=ANY($1::text[]))
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='core' AND c.relname=ANY($1::text[]))
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
          WHERE n.nspname='core' AND t.typname=ANY($1::text[]))""", names), "dsite_unrecorded")


async def native_prerequisites(conn, contract, owner, *, applied):
    parents = {}
    for name, spec in contract["native_tables"].items():
        row = await header(conn, name, owner)
        require(row is not None, "dsite_native_parent")
        wanted = spec["columns"] if applied else [c for c in spec["columns"] if c["name"] != spec["new_column"]]
        attrs = verify_columns(await columns(conn, row["oid"]), wanted, exact=False)
        parents[name] = {**row, "attributes": attrs}
    return parents


async def _index(conn, row, wanted, attrs, types, *, old=False):
    require(row["namespace"] == "core" and row["method"] == "btree" and row["kind"] == "i"
        and row["persistence"] == "p" and row["default_acl"] and row["valid"] and row["ready"]
        and row["live"] and row["immediate"] and not row["exclusion"] and not row["nulls_not_distinct"]
        and row["unique"] and not row["primary"] and row["default_collations"]
        and row["key_count"] == row["total_count"] == len(wanted["columns"])
        and [attrs.get(n) for n in row["keys"]] == wanted["columns"]
        and row["options"] == [0] * len(wanted["columns"])
        and row["opclasses"] == wanted["opclasses"], "dsite_index")
    detail = await conn.fetchrow("""SELECT pg_catalog.pg_get_expr(i.indexprs,i.indrelid,false) AS expr,
        pg_catalog.pg_get_expr(i.indpred,i.indrelid,false) AS predicate,c.reloptions,c.reltablespace,
        pg_catalog.pg_get_userbyid(c.relowner)=current_user AS owned
        FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid WHERE i.indexrelid=$1""", row["oid"])
    coalesce = "coalesce(location_id,'')" if row["name"] == "uq_ops_term" else None
    predicate = None if old else ("site_id IS NULL" if row["name"] == "uq_ops_term" else "site_id IS NOT NULL")
    require(detail["owned"] and detail["reloptions"] is None and detail["reltablespace"] == 0
        and expression(detail["expr"], types) == expression(coalesce, types)
        and expression(detail["predicate"], types) == expression(predicate, types), "dsite_index_expression")


async def prepare(conn, contract, owner):
    await unrecorded(conn, contract)
    parents = await native_prerequisites(conn, contract, owner, applied=False)
    row = parents["ops_contract_terms"]
    actual = [i for i in await indexes(conn, row["oid"]) if i["name"] == "uq_ops_term"]
    require(len(actual) == 1, "dsite_old_index")
    await _index(conn, actual[0], contract["native_tables"]["ops_contract_terms"]["indexes"]["uq_ops_term"],
                 row["attributes"], {c["name"]: c["type"] for c in contract["native_tables"]["ops_contract_terms"]["columns"]}, old=True)


async def _new_fk(conn, key, child, parent, wanted):
    constraint_flags(key)
    require(key["kind"] == "f" and key["target_oid"] == parent["oid"]
        and [child["attributes"].get(n) for n in key["keys"]] == wanted["columns"]
        and [parent["attributes"].get(n) for n in key["target_keys"]] == wanted["target_columns"]
        and key["delete_action"] == key["update_action"] == "a" and key["match"] == "s", "dsite_fk")
    triggers = await conn.fetch("""SELECT t.tgrelid,t.tgconstrrelid,t.tgtype,t.tgenabled::text AS enabled,
        t.tgisinternal,t.tgdeferrable,t.tginitdeferred,t.tgqual IS NULL AS plain,
        p.proname,n.nspname FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
        JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE t.tgconstraint=$1""", key["oid"])
    expected = {(child["oid"], parent["oid"], 5, "RI_FKey_check_ins"), (child["oid"], parent["oid"], 17, "RI_FKey_check_upd"),
                (parent["oid"], child["oid"], 9, "RI_FKey_noaction_del"), (parent["oid"], child["oid"], 17, "RI_FKey_noaction_upd")}
    require(len(triggers) == 4 and {(r["tgrelid"], r["tgconstrrelid"], r["tgtype"], r["proname"]) for r in triggers} == expected
        and all(r["enabled"] == "O" and r["tgisinternal"] and not r["tgdeferrable"] and not r["tginitdeferred"]
                and r["plain"] and r["nspname"] == "pg_catalog" for r in triggers), "dsite_fk_triggers")
    # Root's actual PG16.15 probe: p/u/f are non-inheritable; ordinary CHECK is not.
    require(not await conn.fetchval("SELECT NOT connoinherit OR conparentid<>0 OR confdelsetcols IS NOT NULL FROM pg_catalog.pg_constraint WHERE oid=$1", key["oid"]), "dsite_fk_flags")


async def inspect(conn, contract, owner):
    inherited = contract["inherited_site"]  # honest revision7 cumulative spec
    parents = await prerequisites(conn, inherited, owner)
    await _tenant_keys(conn, inherited, owner, parents, True)
    specs = {**inherited["altered_tables"], **inherited["tables"]}
    headers = {name: await header(conn, name, owner) for name in specs}
    require(all(headers.values()), "dsite_missing_inherited")
    for name, row in headers.items():
        parents[name] = {**row, "attributes": verify_columns(await columns(conn, row["oid"]), specs[name]["columns"])}
    for name, row in headers.items():
        await own_table(conn, specs[name], row, parents, owner)
        require(not await conn.fetchval("""SELECT
            EXISTS(SELECT 1 FROM pg_catalog.pg_trigger WHERE tgrelid=$1 AND NOT tgisinternal)
            OR EXISTS(SELECT 1 FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_depend d
                ON d.classid='pg_catalog.pg_constraint'::regclass AND d.objid=c.oid
                JOIN pg_catalog.pg_proc p ON d.refclassid='pg_catalog.pg_proc'::regclass AND d.refobjid=p.oid
                JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                WHERE c.conrelid=$1 AND c.contype='c' AND n.nspname<>'pg_catalog')""", row["oid"]), "dsite_inherited_extras")
    parents.update(await native_prerequisites(conn, contract, owner, applied=True))
    for name, spec in contract["native_tables"].items():
        row = parents[name]
        require(not await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_attribute
            WHERE attrelid=$1 AND attname=$2 AND attacl IS NOT NULL)""",
            row["oid"], spec["new_column"]), "dsite_column_acl")
        keys = {k["name"]: k for k in await constraints(conn, row["oid"])}
        types = {c["name"]: c["type"] for c in spec["columns"]}
        for key_name, check in spec["checks"].items():
            require(key_name in keys, "dsite_missing_check")
            key = keys[key_name]
            constraint_flags(key)
            require(key["kind"] == "c" and expression(key["expression"], types) == expression(check, types), "dsite_check")
            require(not await conn.fetchval("""SELECT c.connoinherit OR c.conparentid<>0 OR EXISTS(
                SELECT 1 FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_proc p ON p.oid=d.refobjid
                JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE d.classid='pg_catalog.pg_constraint'::regclass
                AND d.objid=c.oid AND d.refclassid='pg_catalog.pg_proc'::regclass AND n.nspname<>'pg_catalog') OR EXISTS(
                SELECT 1 FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_operator op ON op.oid=d.refobjid
                JOIN pg_catalog.pg_namespace n ON n.oid=op.oprnamespace WHERE d.classid='pg_catalog.pg_constraint'::regclass
                AND d.objid=c.oid AND d.refclassid='pg_catalog.pg_operator'::regclass AND n.nspname<>'pg_catalog')
                FROM pg_catalog.pg_constraint c WHERE c.oid=$1""", key["oid"]), "dsite_check_dependencies")
        for key_name, wanted in spec["foreign_keys"].items():
            require(key_name in keys, "dsite_missing_fk")
            await _new_fk(conn, keys[key_name], row, parents[wanted["table"]], wanted)
        actual_indexes = {i["name"]: i for i in await indexes(conn, row["oid"])}
        for index_name, wanted in spec["indexes"].items():
            require(index_name in actual_indexes, "dsite_missing_index")
            await _index(conn, actual_indexes[index_name], wanted, row["attributes"], types)
    ids = [headers[n]["oid"] for n in inherited["tables"]]
    inbound = await conn.fetch("""SELECT k.conrelid,k.conname FROM pg_catalog.pg_constraint k
        WHERE k.confrelid=ANY($1::oid[]) AND k.conrelid<>ALL($1::oid[])""", ids)
    require(len(inbound) == 1 and inbound[0]["conrelid"] == parents["doc_cards"]["oid"]
        and inbound[0]["conname"] == "fk_doc_cards_site_context", "dsite_foreign_dependents")
    return headers
