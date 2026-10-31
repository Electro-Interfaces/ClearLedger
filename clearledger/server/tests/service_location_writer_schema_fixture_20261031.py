"""Выбранная реальная схема PR83; SOURCE FROZEN / RUNTIME NOTRUN.

Этот модуль не является pytest fixture и ничего не провижинит при импорте.
Верхний уровень использует только stdlib. static_schema_manifest читает AST
замороженных файлов, не импортирует их и не исполняет даже default/lambda.
ROOT сначала утверждает manifest и собственный harness, затем в отдельном
процессе вызывает provision_selected_schema на свежем AsyncConnection.
Fixture владеет ровно своей транзакцией; соединением и engine владеет harness.
Тестовый процесс отдельно вызывает verify_schema с сохранённым receipt.

Объём: 80 исходных cases, 14 прямых таблиц, доказанные +7 FK-таблиц;
21 таблица / 458 mapped_column. Ни SLA, ни runtime PASS здесь не заявлены.
Не вызывать main/bootstrap/create_all, не подменять ORM упрощёнными таблицами,
не ALTER чужие таблицы, не DROP/cleanup/GRANT/GUC и не создавать БД.
FinalCompositionRepinPending: immutable parent не является финальным ROOT tree.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import CodeType
from urllib.parse import urlsplit
import uuid


BASE_COMMIT = "3ffe5ba27e694da4924df3a360fbb9bb02f9bb76"
TARGET_DATABASE = "api_service_location_writer_test_20261031"
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 33547
TARGET_SCHEMA = "public"
SOURCE_FREEZE = {
    "clearledger/server/app/models.py": "ffd2c8a1231ca306bf5d569481d3c8e13b81e8a13ce312f8d39978da0e682682",
    "clearledger/server/app/database.py": "30c01b44669729b0bc19210b44205092f61040aed9c1d5334c3a6f5feac106ec",
    "clearledger/server/app/config.py": "90c5da106f20fe90e31c899a88018ef741e6b3207a555fedbd58bafaa61780e8",
    "clearledger/server/app/services/phone_e164.py": "02556ab614fe3ece60bbe4f216fec5b8eceb9b118cb976c20acc3df5cf5a8c0e",
    "clearledger/server/app/routers/locations_router.py": "33d6ce2f89a8c348eff42d73eba860731178c56e9bac2027cdbf37153ec6f503",
    "clearledger/server/app/services/ezs_equipment.py": "9813f1ff7858d38a852109ec8b174bdfeee3a2e89bcbda49c10af7df85befc22",
    "clearledger/server/app/services/ezs_equipment_docs.py": "bf85fe837f153f9ab54b63739513bb80090ab037024ed4634e2fe4e11cef8a2b",
    "clearledger/server/app/services/location_commands.py": "28a02dfb18db53cdf615a20d895b9ad765b32530c90ea3457194b941ada33836",
    "clearledger/server/tests/test_service_location_writer_convergence_20261031.py": "b7e27f89f72f830606f6483d05475ec7571bb9d673ae8278ad88949d4d81d2e1",
    "clearledger/docs/api/SERVICE_LOCATION_WRITER_CONVERGENCE_20261031.json": "8629c09c9c01c06c84639b7fc432591b010e01bbc8e3d19612e2ecb2d61f25f7",
    "clearledger/docs/api/SERVICE_LOCATION_WRITER_CONVERGENCE_20261031.md": "0a7aae3566c2d64613a01f8adb2bc2d5823fdccdfa00d58c0488fb99e83b5729",
}
DIRECT_TABLES = (
    "companies", "users", "user_companies", "service_locations", "audit_events",
    "ezs_equipment_units", "ezs_equipment_movements", "ezs_equipment_documents",
    "ezs_spare_parts", "ezs_spare_part_stock", "ezs_spare_part_movements",
    "ezs_spare_documents", "ezs_supply_documents", "object_links",
)
EXPECTED_ADDITIONS = (
    "channels", "company_roles", "counterparties", "data_entries",
    "org_departments", "organizations", "regions",
)
EXPECTED_COLUMN_COUNTS = {
    "companies": 11, "users": 31, "user_companies": 15, "org_departments": 6,
    "company_roles": 8, "data_entries": 25, "audit_events": 8,
    "counterparties": 31, "organizations": 37, "channels": 15,
    "service_locations": 44, "regions": 8, "ezs_equipment_units": 58,
    "ezs_equipment_movements": 23, "ezs_equipment_documents": 28,
    "object_links": 15, "ezs_spare_parts": 18, "ezs_spare_part_stock": 7,
    "ezs_spare_part_movements": 20, "ezs_spare_documents": 32,
    "ezs_supply_documents": 18,
}
# Exact ordered source plan, independently extracted without importing this
# helper. Extension admission is explicit even when it is already installed.
SUPPLEMENTAL_DDL_FREEZE = (
    ("phone_to_e164", "4560f24aea6a08a62d24b9768b2e64aca64bacb5e420547179228659d6869d2b"),
    ("btree_gist", "2e448867f172d139814a5f2dd9270b9885faf0a627cf6f77a07a3ef76efb1e7e"),
    ("ix_counterparties_phone_e164", "d1afbff5b397ab182cff720122d2bb913268eb6283da34d56a81110f9a7d435d"),
    ("ix_users_phone_mobile_e164", "b43e8dfa440c14a8a04342d8e10e712120a843feffdc54c305c29a31a167d61c"),
    ("ix_users_phone_office_e164", "6acd8797171e01d46867f615747641692d9bee3b0dfbbd6e55b08256d49208c1"),
    ("ck_counterparty_lifecycle_status", "3bf518c127dfb85b0aa3e039d38c59bb59c6c83398f4f3c5cd2fb18d06f54b44"),
    ("uq_counterparties_inn_kpp", "8af80fd200addeb86514f39c87dca540f9f2a3e415b1c4ea86f552ae6e15d796"),
    ("protect_canonical_data_entry", "22bb31b692aa4bc7954d3b3056629a80827402c69319105cbf0f6cbcc597fa97"),
    ("canonical_data_entry_guard_trg", "7325ff230abe7cab9a3ede87f3603dc3cd251d43842e8955dc24601f3bce4a83"),
    ("idx_data_entries_layer", "a909c03a2651aa003bcc50db5cf6c6f1918acbd86e7369252a1ba5cd0cff56d1"),
    ("ix_data_entries_store", "e222a0be1e6b2145df9a202ede61fa66a83674c7ed868c540f69a07d7c1a09cc"),
    ("idx_user_companies_company", "89fefe9aa27a1b9e968165856260c7623207111a3f2618fba97eac152c65ab86"),
    ("idx_service_locations_type", "973f64c94f2c332b0e1b0effa69a6f5713bceb472364be2b7c6dcbdf28eba771"),
    ("idx_service_locations_region", "f3ca6e60231972417c64504e5a79c112d66850c809b2553303093f6a38c2ee42"),
    ("uq_ezs_unit_serial", "e9936743a485c174a3a96dea6dec95fe2d2885b5abeb34889b6e0d74ca0b5cfd"),
    ("uq_ezs_spare_name", "ff2fe3bb98b5f3793fc24de02fbaa8870f1650ee111972976d264234b4a0af91"),
    ("uq_service_locations_code", "e835fa51a9c6e8751db300fdab4d06c889a880e138e436e750f51e84ff7275d5"),
    ("uq_service_locations_serial", "d7e62d5a2ff4988cc87180c55a903b50c1863f3fcb20cd8b321248e2782673cd"),
    ("uq_data_entries_source_key", "3d60074e9c75f390b3e440ed57d9395e8984f742c49eaad385c8daebc649a8b3"),
    ("idx_counterparties_company", "93bad66890ce44e1397cb2f4159ac60f32697255980d6150ea9c909d89dc3835"),
    ("idx_organizations_company", "10fb8ae9e2febc8c04358e52948375d372d6f77e929d9051a5a48cd37ce06ce7"),
    ("object_links_no_overlap", "d3180be25f74f6ce513b930e93825ff3dd3a1b42ae8898e9212b89400b682247"),
    ("ix_ezs_equipment_units_unconfirmed", "9e0e6e60ab5b5af55d891404fe2dd2d5e10d4714c1365115466e34cf811aa958"),
    ("users_calendar_feed_token_uq", "6e824bea76312c7b114dd13afd7cf9d0f1327ec14725ddd7329108f886866b54"),
)
LIMITATIONS = (
    "NOTRUN: worker performed only source reading, AST/hash and in-memory compile; no module execution.",
    "AST closure is not runtime metadata/catalog acceptance; ROOT must execute both guarded stages separately.",
    "Source manifest covers selected outgoing FK closure, not whole bootstrap/import/write closure or incoming soft references.",
    "database.py:2953/stations_normalize.py:304 mention uq_regions_company_name_ci, but no DDL declaration was found; actual frozen Region declares uq_regions_company_name only. CI regional uniqueness is UNKNOWN and is not invented here.",
    "Fresh ORM regions.msk_offset is INTEGER; legacy ADD IF NOT EXISTS says SMALLINT at database.py:3261 and does not change an existing fresh ORM column.",
    "Selected ADD COLUMN IF NOT EXISTS migrations do not retrofit their extra server defaults onto columns already created by the frozen ORM; ORM defaults remain authoritative for fresh tables.",
    "Extension internal SQL, server hooks and driver startup are outside a SQLAlchemy cursor fence; ROOT owns trusted PostgreSQL/extension/resource isolation evidence.",
    "Boundary booleans are attestations supplied by reviewed ROOT harness, not authentication against a hostile Python caller.",
    "Receipt proves schema provision/catalog stability, not test outcomes, auth/HTTP acceptance, performance, races or global history closure.",
    "FinalCompositionRepinPending: ROOT must separately freeze/review its final composition; no automatic HEAD/source repin.",
)


def _require(ok, message):
    if not ok:
        raise RuntimeError(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def manifest_sha256(value):
    """Canonical JSON digest; deliberately does not execute fixture/app code."""
    return _sha(json.dumps(value, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _root(repo_root=None):
    return Path(repo_root).resolve() if repo_root is not None else Path(__file__).resolve().parents[3]


def _source(root, relative):
    data = (root / relative).read_bytes()
    _require(_sha(data) == SOURCE_FREEZE[relative], "Frozen source mismatch: " + relative)
    return data.decode("utf-8")


def _anchor(relative, node, source):
    segment = ast.get_source_segment(source, node)
    _require(segment is not None, "Source segment unavailable")
    return {"path": relative, "line": node.lineno, "end_line": node.end_lineno,
            "sha256": _sha(segment.encode("utf-8")),
            "ast_sha256": _sha(ast.dump(node, include_attributes=False).encode("utf-8"))}


def _name(node):
    return ast.unparse(node)


def _literal(node):
    # literal_eval accepts literals only; no eval/exec/import of source expressions.
    return ast.literal_eval(node)


def _kwargs(call, allowed):
    keys = [kw.arg for kw in call.keywords]
    _require(None not in keys and len(set(keys)) == len(keys) and set(keys) <= set(allowed),
             "Unreviewed keyword/expansion in " + _name(call))
    return {kw.arg: kw.value for kw in call.keywords}


def _type(node):
    kind = _name(node.func) if isinstance(node, ast.Call) else _name(node)
    args = list(node.args) if isinstance(node, ast.Call) else []
    kw = _kwargs(node, {"as_uuid", "timezone"}) if isinstance(node, ast.Call) else {}
    if kind in {"String", "CHAR", "Numeric"}:
        _require(not kw and all(isinstance(a, ast.Constant) for a in args), "Unreviewed type args")
        values = [_literal(a) for a in args]
        _require((kind == "Numeric" and len(values) == 2) or
                 (kind in {"String", "CHAR"} and len(values) <= 1), "Unreviewed type arity")
        sql = {"String": "VARCHAR", "CHAR": "CHAR", "Numeric": "NUMERIC"}[kind]
        if values:
            sql += "(" + ", ".join(str(v) for v in values) + ")"
        return {"kind": kind, "sql": sql, "args": values}
    if kind == "ARRAY":
        _require(len(args) == 1 and not kw, "Unreviewed ARRAY")
        item = _type(args[0])
        return {"kind": kind, "sql": item["sql"] + "[]", "item": item}
    if kind in {"UUID", "DateTime", "Time"}:
        _require(not args, "Unreviewed scalar type args")
        flags = {k: _literal(v) for k, v in kw.items()}
        _require(set(flags) <= ({"as_uuid"} if kind == "UUID" else {"timezone"}), "Type flag")
        if kind == "UUID":
            _require(flags == {"as_uuid": True}, "UUID representation drift")
            return {"kind": kind, "sql": "UUID", "as_uuid": True}
        tz = flags.get("timezone", False)
        _require(type(tz) is bool, "timezone must be bool")
        sql = ("TIMESTAMP" if kind == "DateTime" else "TIME") + (
            " WITH TIME ZONE" if tz else " WITHOUT TIME ZONE")
        return {"kind": kind, "sql": sql, "timezone": tz}
    _require(kind in {"Text", "Integer", "Float", "Boolean", "Date", "JSONB"}
             and not args and not kw, "Unknown selected type: " + _name(node))
    return {"kind": kind, "sql": {"Text": "TEXT", "Integer": "INTEGER", "Float": "FLOAT",
            "Boolean": "BOOLEAN", "Date": "DATE", "JSONB": "JSONB"}[kind]}


def _code_signature(code):
    def value(item):
        if isinstance(item, CodeType):
            return {"code": _code_signature(item)}
        if isinstance(item, tuple):
            return {"tuple": [value(v) for v in item]}
        _require(item is None or type(item) in {str, bool, int, float}, "Unknown code constant")
        return {"type": type(item).__name__, "value": item}
    return {"bytecode": code.co_code.hex(), "consts": [value(v) for v in code.co_consts],
            "names": list(code.co_names), "varnames": list(code.co_varnames),
            "freevars": list(code.co_freevars), "cellvars": list(code.co_cellvars),
            "argcount": code.co_argcount, "posonly": code.co_posonlyargcount,
            "kwonly": code.co_kwonlyargcount}


def _default(node):
    if isinstance(node, ast.Constant):
        return {"kind": "scalar", "value": node.value, "value_type": type(node.value).__name__}
    if isinstance(node, ast.Lambda):
        # Keep the approval manifest independent of Python bytecode version.
        return {"kind": "lambda", "source": _name(node)}
    if _name(node) in {"uuid.uuid4", "dict", "list"}:
        module, name = ("uuid", "uuid4") if _name(node) == "uuid.uuid4" else ("builtins", _name(node))
        return {"kind": "callable", "module": module, "name": name}
    if isinstance(node, ast.Call) and _name(node.func) == "func.now" and not node.args and not node.keywords:
        return {"kind": "sql", "sql": "now()"}
    if isinstance(node, ast.Call) and _name(node.func) == "text" and len(node.args) == 1 and not node.keywords:
        return {"kind": "sql", "sql": _literal(node.args[0])}
    raise RuntimeError("Unreviewed default: " + _name(node))


def _fk(node, column):
    _require(len(node.args) == 1, "Nonliteral/composite ForeignKey needs review")
    kw = _kwargs(node, {"name", "ondelete", "onupdate", "deferrable", "initially", "use_alter"})
    target = _literal(node.args[0])
    _require(isinstance(target, str) and target.count(".") == 1, "Qualified/unresolved FK")
    out = {"columns": [column], "target": target, "name": None, "ondelete": None,
           "onupdate": None, "deferrable": None, "initially": None, "use_alter": False}
    out.update({k: _literal(v) for k, v in kw.items()})
    _require(not out["use_alter"], "Selected FK requires foreign ALTER")
    return out


def _table(node, source):
    relative = "clearledger/server/app/models.py"
    cols, fks, indexes, unique, checks = [], [], [], [], []
    name = None
    for statement in node.body:
        if isinstance(statement, ast.Assign):
            targets = [_name(t) for t in statement.targets]
            if targets == ["__tablename__"]:
                name = _literal(statement.value)
            elif targets == ["__table_args__"]:
                _require(isinstance(statement.value, ast.Tuple), "Unreviewed table args")
                for arg in statement.value.elts:
                    _require(isinstance(arg, ast.Call), "Unreviewed table arg")
                    kind = _name(arg.func)
                    kw = _kwargs(arg, {"name", "unique", "postgresql_where"})
                    if kind == "Index":
                        _require(set(kw) <= {"unique", "postgresql_where"}, "Index kwargs")
                        indexes.append({"name": _literal(arg.args[0]),
                            "columns": [_literal(v) for v in arg.args[1:]],
                            "unique": _literal(kw["unique"]) if "unique" in kw else False,
                            "where": _default(kw["postgresql_where"])["sql"] if "postgresql_where" in kw else None})
                    elif kind == "UniqueConstraint":
                        _require(set(kw) == {"name"}, "Unique constraint options")
                        unique.append({"name": _literal(kw["name"]),
                                       "columns": [_literal(v) for v in arg.args]})
                    elif kind == "CheckConstraint":
                        _require(set(kw) == {"name"} and len(arg.args) == 1, "Check options")
                        checks.append({"name": _literal(kw["name"]), "sql": _literal(arg.args[0])})
                    else:
                        raise RuntimeError("Unknown selected table constraint: " + kind)
            continue
        if not isinstance(statement, ast.AnnAssign):
            continue
        call = statement.value
        _require(isinstance(call, ast.Call), "Unreviewed mapped attribute")
        if _name(call.func) == "relationship":
            continue
        _require(_name(call.func) == "mapped_column", "Unreviewed mapped attribute")
        args = list(call.args)
        column_name = _name(statement.target)
        if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
            column_name = _literal(args.pop(0))
        _require(bool(args), "Annotation-only type needs explicit review")
        type_spec = _type(args.pop(0))
        kw = _kwargs(call, {"nullable", "primary_key", "index", "unique", "default", "server_default", "onupdate"})
        primary = _literal(kw["primary_key"]) if "primary_key" in kw else False
        nullable = _literal(kw["nullable"]) if "nullable" in kw else (
            not primary and "None" in _name(statement.annotation))
        column = {"attribute": _name(statement.target), "name": column_name,
                  "type": type_spec, "type_source": _name(call.args[1] if isinstance(call.args[0], ast.Constant) else call.args[0]),
                  "nullable": nullable, "primary_key": primary,
                  "unique": _literal(kw["unique"]) if "unique" in kw else None,
                  "index": _literal(kw["index"]) if "index" in kw else None,
                  "default": _default(kw["default"]) if "default" in kw else None,
                  "server_default": _default(kw["server_default"]) if "server_default" in kw else None,
                  "onupdate": _default(kw["onupdate"]) if "onupdate" in kw else None,
                  "computed": None, "declaration": _name(call),
                  "anchor": _anchor(relative, statement, source)}
        for extra in args:
            _require(isinstance(extra, ast.Call), "Unreviewed extra column argument")
            if _name(extra.func) == "ForeignKey":
                fks.append(_fk(extra, column_name))
            elif _name(extra.func) == "Computed":
                options = _kwargs(extra, {"persisted"})
                _require(len(extra.args) == 1 and set(options) == {"persisted"}, "Computed shape")
                column["computed"] = {"sql": _literal(extra.args[0]), "persisted": _literal(options["persisted"])}
            else:
                raise RuntimeError("Unknown selected column object: " + _name(extra))
        cols.append(column)
    _require(name is not None, "Missing table name")
    for col in cols:
        if col["index"]:
            indexes.append({"name": "ix_" + name + "_" + col["name"], "columns": [col["name"]],
                            "unique": bool(col["unique"]), "where": None})
        elif col["unique"]:
            unique.append({"name": None, "columns": [col["name"]]})
    return {"name": name, "class": node.name, "schema": None, "anchor": _anchor(relative, node, source),
            "columns": cols, "primary_key": [c["name"] for c in cols if c["primary_key"]],
            "foreign_keys": sorted(fks, key=lambda x: x["columns"]),
            "indexes": sorted(indexes, key=lambda x: x["name"]),
            "unique_constraints": sorted(unique, key=lambda x: (x["name"] or "", x["columns"])),
            "check_constraints": sorted(checks, key=lambda x: x["name"])}


def _bootstrap(source, phone_source, tables):
    """Extract only exact selected statements, never execute a DO/bootstrap block."""
    db_path = "clearledger/server/app/database.py"
    tree = ast.parse(source)
    strings = [(n, n.value) for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    by_line = sorted(strings, key=lambda pair: pair[0].lineno)
    declared_indexes = {i["name"]: (t["name"], i) for t in tables.values() for i in t["indexes"]}
    operations, duplicates, inventory = [], [], []

    def operation(node, sql, kind, table=None):
        entry = {"kind": kind, "table": table, "sql": sql, "sha256": _sha(sql.encode("utf-8")),
                 "anchor": _anchor(db_path, node, source)}
        operations.append(entry)

    for node, sql in by_line:
        index = re.fullmatch(r"\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s*\(.*", sql, re.I | re.S)
        if index and index[2] in tables:
            if index[1] in declared_indexes:
                # No skip on name alone: prove the duplicate has the same complete
                # plain-column expression/order/unique flag/predicate as ORM.
                duplicate = re.fullmatch(r"\s*CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s*\(([^()]*)\)(?:\s+WHERE\s+(.+))?\s*", sql, re.I | re.S)
                _require(duplicate is not None, "Duplicate functional index needs separate proof")
                target, spec = declared_indexes[index[1]]
                equivalent = {"name": duplicate[2], "columns": [v.strip() for v in duplicate[4].split(",")],
                              "unique": bool(duplicate[1]), "where": duplicate[5]}
                _require(target == duplicate[3] and equivalent == spec, "Same-name bootstrap/ORM index differs")
                duplicates.append({"name": index[1], "table": index[2], "anchor": _anchor(db_path, node, source),
                                   "proof": equivalent, "disposition": "already emitted identically by actual ORM Table.create"})
            else:
                operation(node, sql, "index", index[2])
        if re.match(r"\s*CREATE OR REPLACE FUNCTION protect_canonical_data_entry\(\)", sql):
            operation(node, sql, "function", "data_entries")
        if re.match(r"\s*CREATE TRIGGER canonical_data_entry_guard_trg\b", sql):
            operation(node, sql, "trigger", "data_entries")
        if "CREATE UNIQUE INDEX uq_counterparties_inn_kpp" in sql:
            match = re.search(r"CREATE UNIQUE INDEX uq_counterparties_inn_kpp\s+ON counterparties.*?;", sql, re.S)
            _require(match is not None, "Counterparty unique bootstrap source unknown")
            operation(node, match[0].rstrip(";"), "index", "counterparties")
        if "ADD CONSTRAINT ck_counterparty_lifecycle_status" in sql:
            match = re.search(r"ALTER TABLE counterparties ADD CONSTRAINT ck_counterparty_lifecycle_status\s+CHECK \(lifecycle_status IN \('draft','verified','blocked','archived'\)\)", sql)
            _require(match is not None, "Counterparty lifecycle bootstrap source unknown")
            operation(node, match[0], "constraint", "counterparties")
        if "ALTER TABLE object_links ADD CONSTRAINT object_links_no_overlap" in sql:
            match = re.search(r"ALTER TABLE object_links ADD CONSTRAINT object_links_no_overlap\s+EXCLUDE USING gist \(.*?\)\s*;", sql)
            _require(match is not None, "ObjectLink EXCLUDE source unknown")
            operation(node, match[0].rstrip(";"), "constraint", "object_links")
        # All source snippets touching selected tables are review evidence, including
        # obsolete/backfill/mixed-table blocks that must never be run by this fixture.
        mentioned = sorted(t for t in tables if re.search(r"\b" + re.escape(t) + r"\b", sql))
        if mentioned and re.search(r"\b(?:ALTER|CREATE|DROP|UPDATE|DELETE|INSERT)\b", sql, re.I):
            inventory.append({"line": node.lineno, "end_line": node.end_lineno,
                "tables_mentioned": mentioned, "literal_sha256": _sha(sql.encode("utf-8")),
                "source": sql, "disposition": "review-only; never run enclosing bootstrap literal"})
    functions = [n for n in ast.parse(phone_source).body if isinstance(n, ast.Assign)
                 and [_name(t) for t in n.targets] == ["PHONE_FUNCTION_DDL"]]
    _require(len(functions) == 1, "Unknown phone function source")
    phone = _literal(functions[0].value)
    _require(_sha(phone.encode("utf-8")) == "4560f24aea6a08a62d24b9768b2e64aca64bacb5e420547179228659d6869d2b", "Phone function drift")
    phone_op = {"kind": "function", "table": None, "sql": phone, "sha256": _sha(phone.encode("utf-8")),
        "anchor": _anchor("clearledger/server/app/services/phone_e164.py", functions[0], phone_source)}
    _require(sum(o["kind"] == "function" for o in operations) == 1, "Canonical function unknown")
    _require(sum(o["kind"] == "trigger" for o in operations) == 1, "Canonical trigger unknown")
    _require(sum(o["kind"] == "constraint" for o in operations) == 2, "Supplemental constraint unknown")
    _require(sum(o["kind"] == "index" for o in operations) == 18 and len(duplicates) == 5,
             "Selected supplemental/duplicate index proof count changed")
    extension_sql = "CREATE EXTENSION IF NOT EXISTS btree_gist"
    supplemental_hashes = [phone_op["sha256"], _sha(extension_sql.encode("utf-8"))] + [o["sha256"] for o in operations]
    _require(supplemental_hashes == [sha for _, sha in SUPPLEMENTAL_DDL_FREEZE],
             "Exact supplemental DDL freeze/order changed")
    return {"before_tables": [phone_op], "after_tables": operations,
            "extra_ddl_sha256": supplemental_hashes,
            "required_extension": {"name": "btree_gist", "sql": extension_sql,
                "sha256": _sha(extension_sql.encode("utf-8")),
                "reason": "Exact object_links_no_overlap scalar equality + daterange GiST exclusion at database.py:4785-4821"},
            "orm_duplicates_not_reemitted": duplicates, "review_inventory": inventory,
            "bounded_dynamic_migrations": [
                {"anchor": "database.py:3251-3255", "disposition": "ADD IF NOT EXISTS primary_number/primary_date/bp_ref/bp_exported_at/posted_at to two selected document tables; all already declared in ORM"},
                {"anchor": "database.py:3806-3809", "disposition": "bounded ADD IF NOT EXISTS channel_id to data_entries; already declared with FK in ORM"},
                {"anchor": "database.py:2269-2274", "disposition": "bounded ADD IF NOT EXISTS users.away_from/away_to; already declared in ORM"},
            ]}


def static_schema_manifest(repo_root=None):
    """Full source-derived manifest; stdlib only, no ORM/helper execution.

    The returned JSON is the review artifact: every column includes its original
    declaration, type, defaults, nullability, computed expression and source hash.
    Every non-self FK must precede its dependent table; self-FKs stay in CREATE.
    """
    root = _root(repo_root)
    sources = {path: _source(root, path) for path in SOURCE_FREEZE}
    report = json.loads(sources["clearledger/docs/api/SERVICE_LOCATION_WRITER_CONVERGENCE_20261031.json"])
    _require(report["fixture_contract"]["direct_tables"] == list(DIRECT_TABLES), "PR83 direct roots drift")
    _require(report["source_expanded_case_count"] == 80, "PR83 source case budget changed")
    models = sources["clearledger/server/app/models.py"]
    classes = {}
    for node in ast.parse(models).body:
        if not isinstance(node, ast.ClassDef):
            continue
        names = [s for s in node.body if isinstance(s, ast.Assign)
                 and [_name(t) for t in s.targets] == ["__tablename__"]]
        if not names:
            continue
        _require(len(names) == 1, "Ambiguous table declaration")
        name = _literal(names[0].value)
        _require(name not in classes, "Duplicate frozen table")
        classes[name] = node
    tables, pending = {}, list(DIRECT_TABLES)
    while pending:
        name = pending.pop()
        if name in tables:
            continue
        _require(name in classes, "Unresolved selected FK table: " + name)
        table = _table(classes[name], models)
        tables[name] = table
        pending.extend(fk["target"].rsplit(".", 1)[0] for fk in table["foreign_keys"])
    _require(sorted(set(tables) - set(DIRECT_TABLES)) == list(EXPECTED_ADDITIONS), "FK closure changed")
    _require({n: len(t["columns"]) for n, t in tables.items()} == EXPECTED_COLUMN_COUNTS,
             "Frozen selected column count changed")
    edges = []
    for name, table in tables.items():
        for fk in table["foreign_keys"]:
            target, column = fk["target"].rsplit(".", 1)
            _require(column in {c["name"] for c in tables[target]["columns"]}, "Unresolved FK column")
            edges.append({"from_table": name, "from_column": fk["columns"][0],
                          "to_table": target, "to_column": column,
                          "self_reference": name == target})
    remaining, order = set(tables), []
    while remaining:
        ready = sorted(n for n in remaining if not any(
            e["from_table"] == n and not e["self_reference"] and e["to_table"] in remaining for e in edges))
        _require(bool(ready), "Non-self FK cycle requires unapproved ALTER; refuse")
        order.extend(ready)
        remaining.difference_update(ready)
    tables = {name: tables[name] for name in sorted(tables)}
    bootstrap = _bootstrap(sources["clearledger/server/app/database.py"],
                           sources["clearledger/server/app/services/phone_e164.py"], tables)
    return {"format": "service-location-selected-schema/v1", "base_commit": BASE_COMMIT,
        "status": "SOURCE_FROZEN_RUNTIME_NOTRUN", "source_freeze": dict(SOURCE_FREEZE),
        "direct_tables": list(DIRECT_TABLES), "additional_fk_tables": list(EXPECTED_ADDITIONS),
        "tables": tables, "foreign_key_edges": sorted(edges, key=lambda e: (e["from_table"], e["from_column"])),
        "topological_order": order, "table_count": len(tables), "column_count": sum(map(len, (t["columns"] for t in tables.values()))),
        "bootstrap": bootstrap, "limitations": list(LIMITATIONS),
        "source_budget": {"cases": 80, "company_rows_max": 160, "users_max": 80, "location_rows_max": 320,
                          "additional_usage_rows_per_case_max": 4, "test_pool_size": 3, "test_max_overflow": 0}}


def _runtime_default(default):
    if default is None:
        return None
    arg = default.arg
    if getattr(default, "is_callable", False):
        arg = inspect.unwrap(arg)
        if getattr(arg, "__name__", None) == "<lambda>":
            return {"kind": "lambda", "code": _code_signature(arg.__code__)}
        return {"kind": "callable", "module": getattr(arg, "__module__", None),
                "name": getattr(arg, "__name__", None)}
    if type(arg) in {str, int, bool, float} or arg is None:
        return {"kind": "scalar", "value": arg, "value_type": type(arg).__name__}
    return {"kind": "sql", "sql": str(arg)}


def _runtime_type(value, dialect):
    kind = type(value).__name__
    _require(not getattr(value, "_variant_mapping", {}), "Unapproved type variant")
    spec = {"kind": kind, "sql": str(value.compile(dialect=dialect))}
    if kind in {"String", "CHAR"}:
        _require(value.collation is None, "Unapproved column collation")
        spec["args"] = [] if value.length is None else [value.length]
    elif kind == "Numeric":
        _require(value.asdecimal is True, "Unapproved numeric representation")
        spec["args"] = [value.precision, value.scale]
    elif kind == "ARRAY":
        _require(value.dimensions is None and not value.zero_indexes and not value.as_tuple,
                 "Unapproved ARRAY representation")
        spec["item"] = _runtime_type(value.item_type, dialect)
    elif kind == "UUID":
        spec["as_uuid"] = value.as_uuid
    elif kind in {"DateTime", "Time"}:
        spec["timezone"] = value.timezone
    elif kind == "Float":
        _require(value.precision is None and value.asdecimal is False, "Unapproved float representation")
    return spec


def _metadata_shape(table, dialect):
    """Actual Table comparison, not construction of a parallel simplified Table."""
    _require(not table.info and not dict(table.dialect_kwargs) and not table._prefixes,
             "Unapproved table options")
    columns = []
    for column in table.columns:
        _require(column.identity is None and not dict(column.dialect_kwargs), "Unapproved identity/column options")
        computed = column.computed
        _require(column.server_onupdate is None or column.server_onupdate is computed,
                 "Unapproved server onupdate")
        columns.append({"name": column.name, "type": _runtime_type(column.type, dialect),
            "nullable": column.nullable, "primary_key": column.primary_key,
            "unique": column.unique, "index": column.index,
            "default": _runtime_default(column.default),
            "server_default": None if computed is not None else _runtime_default(column.server_default),
            "onupdate": _runtime_default(column.onupdate),
            "computed": None if computed is None else {"sql": str(computed.sqltext), "persisted": computed.persisted}})
    fks, unique, checks = [], [], []
    for constraint in table.constraints:
        kind = type(constraint).__name__
        _require(not dict(constraint.dialect_kwargs), "Unapproved constraint dialect options")
        if kind == "PrimaryKeyConstraint":
            _require(constraint.name is None and constraint.deferrable is None and constraint.initially is None,
                     "Unapproved PK options")
        elif kind == "ForeignKeyConstraint":
            _require(len(constraint.elements) == 1 and constraint.match is None,
                     "Unapproved composite/match FK")
            fk = constraint.elements[0]
            fks.append({"columns": [fk.parent.name], "target": fk.target_fullname,
                "name": constraint.name, "ondelete": constraint.ondelete, "onupdate": constraint.onupdate,
                "deferrable": constraint.deferrable, "initially": constraint.initially,
                "use_alter": constraint.use_alter})
        elif kind == "UniqueConstraint":
            _require(constraint.deferrable is None and constraint.initially is None, "Unapproved unique timing")
            unique.append({"name": constraint.name, "columns": [c.name for c in constraint.columns]})
        elif kind == "CheckConstraint":
            _require(constraint.deferrable is None and constraint.initially is None, "Unapproved check timing")
            checks.append({"name": constraint.name, "sql": str(constraint.sqltext)})
        else:
            raise RuntimeError("Unapproved runtime table constraint: " + kind)
    indexes = []
    for index in table.indexes:
        options = dict(index.dialect_kwargs)
        _require(set(options) <= {"postgresql_where"}, "Unapproved index options")
        _require(all(getattr(e, "table", None) is table and table.c[e.name] is e for e in index.expressions),
                 "Unapproved functional ORM index")
        indexes.append({"name": index.name, "columns": [e.name for e in index.expressions],
                        "unique": index.unique,
                        "where": str(options["postgresql_where"]) if "postgresql_where" in options else None})
    return {"name": table.name, "schema": table.schema, "columns": columns,
        "primary_key": [c.name for c in table.primary_key.columns],
        "foreign_keys": sorted(fks, key=lambda x: x["columns"]),
        "indexes": sorted(indexes, key=lambda x: x["name"]),
        "unique_constraints": sorted(unique, key=lambda x: (x["name"] or "", x["columns"])),
        "check_constraints": sorted(checks, key=lambda x: x["name"])}


def _expected_shape(table):
    keys = {"name", "schema", "primary_key", "foreign_keys", "indexes", "unique_constraints", "check_constraints"}
    out = {k: table[k] for k in keys}
    out["columns"] = [{k: v for k, v in c.items() if k not in
                      {"attribute", "anchor", "declaration", "type_source"}} for c in table["columns"]]
    for col in out["columns"]:
        for key in ("default", "server_default", "onupdate"):
            value = col[key]
            if value is not None and value["kind"] == "lambda":
                expression = ast.parse(value["source"], mode="eval")
                # Compile only, never eval/call a source default. Compare code
                # within the same reviewed interpreter as the actual ORM import.
                code = compile(expression, "<selected-default>", "eval", dont_inherit=True)
                lambdas = [c for c in code.co_consts if isinstance(c, CodeType)]
                _require(len(lambdas) == 1, "Unexpected lambda bytecode shape")
                col[key] = {"kind": "lambda", "code": _code_signature(lambdas[0])}
    return out


def _external_lease(approval):
    """Read exactly ROOT's private lease input; never discover a DSN/credential."""
    path = approval.get("external_lease_path")
    _require(isinstance(path, str) and Path(path).is_absolute(), "Explicit external lease path required")
    lease_path = Path(path)
    parent_stat = lease_path.parent.lstat()
    _require(stat.S_ISDIR(parent_stat.st_mode) and parent_stat.st_uid == 0
             and stat.S_IMODE(parent_stat.st_mode) == 0o700, "ROOT-owned 0700 lease control directory required")
    file_stat = lease_path.lstat()
    _require(stat.S_ISREG(file_stat.st_mode) and file_stat.st_uid == 0
             and stat.S_IMODE(file_stat.st_mode) == 0o600, "ROOT-owned 0600 regular lease file required")
    # O_NOFOLLOW plus fstat avoids accepting a swapped symlink between lstat/read.
    fd = os.open(lease_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        current = os.fstat(fd)
        _require((current.st_dev, current.st_ino, current.st_uid, stat.S_IMODE(current.st_mode)) ==
                 (file_stat.st_dev, file_stat.st_ino, 0, 0o600) and stat.S_ISREG(current.st_mode), "Lease changed during open")
        # Keep the read-only descriptor read-only under the harness FD fence;
        # do not convert it through fdopen/io.open (which needs write capability).
        raw = os.read(fd, 65537)
    finally:
        os.close(fd)
    _require(len(raw) <= 65536 and _sha(raw) == approval.get("external_lease_sha256"), "External lease bytes/hash mismatch")
    external = json.loads(raw)
    _require(external == approval.get("external_lease"), "Original external lease fields mismatch")
    _require(external.get("format") == 1 and external.get("kind") == "service_location_writer_root_lease"
             and external.get("run_id") == "run_19ce21b41b2c", "Exact ROOT lease protocol required")
    lease_uuid = external.get("lease_uuid")
    _require(isinstance(lease_uuid, str) and str(uuid.UUID(lease_uuid)) == lease_uuid, "Canonical lease UUID required")
    _require(external.get("database_name") == TARGET_DATABASE and external.get("owner_role") == "clearledger"
             and external.get("pg_port") == TARGET_PORT, "External lease target mismatch")
    _require(isinstance(external.get("pg_container_id"), str)
             and re.fullmatch(r"[0-9a-f]{64}", external["pg_container_id"]), "Frozen container identity required")
    _require(isinstance(external.get("created_utc"), str) and external["created_utc"].strip(), "Lease creation timestamp required")
    lease = approval["lease"]
    mapping = {"lease_id": "lease_uuid", "run_id": "run_id", "database": "database_name",
               "database_oid": "database_oid", "role": "owner_role", "role_oid": "owner_role_oid", "port": "pg_port"}
    _require(all(lease[k] == external[v] for k, v in mapping.items()), "Normalized/original lease disagreement")
    _require(type(external["database_oid"]) is int and external["database_oid"] > 0
             and type(external["owner_role_oid"]) is int and external["owner_role_oid"] > 0, "External lease OID mismatch")
    return external


def _validate_approval(connection, approval, stage):
    """No imports of app/framework and no SQL before this explicit boundary."""
    _require(isinstance(approval, dict), "Explicit ROOT approval required")
    _require(approval.get("approved_by") == "ROOT" and approval.get("stage") == stage,
             "ROOT stage approval required")
    _require(isinstance(approval.get("approval_id"), str) and approval["approval_id"].strip(), "Approval ID required")
    root = _root()
    manifest = static_schema_manifest(root)
    _require(approval.get("manifest_sha256") == manifest_sha256(manifest), "Approved source manifest mismatch")
    _require(approval.get("fixture_sha256") == _sha(Path(__file__).read_bytes()), "Approved fixture mismatch")
    _require(approval.get("root_extra_ddl_approval") == manifest["bootstrap"]["extra_ddl_sha256"],
             "ROOT exact ordered supplemental DDL hash approval required")
    harness_hash = approval.get("harness_sha256")
    _require(isinstance(harness_hash, str) and re.fullmatch(r"[0-9a-f]{64}", harness_hash), "Harness freeze required")
    boundary = approval.get("boundary", {})
    _require(boundary.get("harness_sha256") == harness_hash and all(boundary.get(k) is True for k in (
        "isolated_process", "import_fence_installed", "sanitized_environment", "no_live_dsn")),
        "Reviewed harness import/environment boundary required")
    lease = approval.get("lease", {})
    _require(lease.get("host") == TARGET_HOST and lease.get("port") == TARGET_PORT
             and lease.get("database") == TARGET_DATABASE and lease.get("synthetic") is True,
             "Dedicated ROOT-selected synthetic DB lease required")
    for key in ("database_oid", "role_oid"):
        _require(type(lease.get(key)) is int and lease[key] > 0, "Positive leased OID required: " + key)
    for key in ("lease_id", "run_id", "role"):
        _require(isinstance(lease.get(key), str) and lease[key].strip(), "Lease identity required: " + key)
    _external_lease(approval)
    _require(not connection.in_transaction() and not connection.in_nested_transaction(),
             "Fresh inactive connection required; fixture owns only its own transaction")
    _require(connection.dialect.name == "postgresql" and connection.dialect.driver == "asyncpg",
             "Reviewed PostgreSQL asyncpg connection required")
    _require(connection.sync_connection.get_execution_options().get("isolation_level") != "AUTOCOMMIT",
             "Transactional DDL required")
    url = connection.engine.url
    _require(url.host == TARGET_HOST and url.port == TARGET_PORT and url.database == TARGET_DATABASE
             and url.username == lease["role"] and not url.query, "Engine URL outside leased target")
    dsn = os.environ.get("TEST_DATABASE_URL", "")
    parsed = urlsplit(dsn)
    _require(parsed.scheme == "postgresql+asyncpg" and parsed.hostname == TARGET_HOST
             and parsed.port == TARGET_PORT and parsed.path == "/" + TARGET_DATABASE
             and not parsed.query and not parsed.fragment, "Validated synthetic TEST_DATABASE_URL required")
    _require(os.environ.get("DATABASE_URL") == dsn and str(url.render_as_string(hide_password=False)) == dsn,
             "Environment/connection DSN disagreement")
    _require(os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1", "Disable ambient pytest plugins")
    _require(not Path(".env").exists(), "Synthetic cwd without .env required")
    _require(not any(name in sys.modules for name in ("app.main", "app.config", "app.database", "app.models")),
             "Fresh process before app imports required")
    return manifest


class _StatementFence:
    """Connection-local exact SQL+parameter multiset; unarmed means deny all.

    Table.create emits its own indexes in unspecified iteration order, so a
    phase permits each exact compiled statement exactly once. No SQL prefix
    regex, arbitrary SELECT, table existence query, DO block, GUC or extra DDL.
    """
    def __init__(self):
        self.expected = Counter()
        self.executed = []

    @staticmethod
    def key(sql, parameters):
        # Empty tuple/dict both represent zero DBAPI parameters, not a wildcard.
        params = [] if parameters is None or parameters == () or parameters == {} else parameters
        return json.dumps([sql.strip(), params], sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def arm(self, statements):
        _require(not self.expected, "Previous SQL phase incomplete")
        self.expected = Counter(self.key(sql, params) for sql, params in statements)

    def before_cursor_execute(self, conn, cursor, statement, parameters, context, executemany):
        _require(not executemany, "No executemany in schema stage")
        key = self.key(statement, parameters)
        _require(self.expected[key] > 0, "Unapproved SQL/query/DDL in selected schema stage")
        self.expected[key] -= 1
        if not self.expected[key]:
            del self.expected[key]
        self.executed.append({"sql_sha256": _sha(statement.strip().encode("utf-8")),
                              "parameters_sha256": manifest_sha256(parameters or []),
                              "ddl": not statement.lstrip().upper().startswith("SELECT ")})

    def complete(self):
        _require(not self.expected, "Approved SQL statements were not all emitted")


# Catalog-only queries. No business table is read, including company/user data.
# public is deliberate: no SET/search_path, implicit namespace adoption or GUC.
_IDENTITY_SQL = """SELECT pg_catalog.current_database() AS database,
 d.oid::bigint AS database_oid, current_user AS role, session_user AS session_role,
 r.oid::bigint AS role_oid, owner.rolname AS database_owner,d.datdba::bigint AS database_owner_oid,
 pg_catalog.current_schema() AS schema, pg_catalog.current_schemas(false) AS schemas
 FROM pg_catalog.pg_database d
 JOIN pg_catalog.pg_roles r ON r.rolname = current_user
 JOIN pg_catalog.pg_roles owner ON owner.oid = d.datdba
 WHERE d.datname = pg_catalog.current_database()"""
_TRANSACTION_SQL = "SELECT pg_catalog.pg_current_xact_id()::text AS transaction_id"
_RELATIONS_SQL = """SELECT n.nspname AS schema, c.relname AS name, c.relkind AS kind,
 c.oid::bigint AS oid, c.relpersistence AS persistence
 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
 AND c.relkind IN ('r','p','f','v','m','S') ORDER BY n.nspname,c.relname"""
_NAMESPACES_SQL = """SELECT nspname AS name FROM pg_catalog.pg_namespace
 WHERE nspname !~ '^pg_' AND nspname <> 'information_schema' ORDER BY nspname"""
_EXTENSIONS_SQL = """SELECT e.extname AS name,e.extversion AS version,n.nspname AS schema
 FROM pg_catalog.pg_extension e JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace
 ORDER BY e.extname"""
_FUNCTIONS_SQL = """SELECT n.nspname AS schema,p.proname AS name,
 pg_catalog.pg_get_function_identity_arguments(p.oid) AS arguments,
 pg_catalog.format_type(p.prorettype,NULL) AS returns,l.lanname AS language,
 p.prosrc AS body,p.provolatile AS volatility,p.proparallel AS parallel,
 p.prosecdef AS security_definer,p.proconfig AS config,
 pg_catalog.pg_get_functiondef(p.oid) AS definition
 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang
 WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
 AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend d
 WHERE d.classid='pg_catalog.pg_proc'::pg_catalog.regclass AND d.objid=p.oid AND d.deptype='e')
 ORDER BY n.nspname,p.proname,arguments"""
_COLUMNS_SQL = """SELECT c.relname AS table,a.attname AS name,a.attnum AS position,
 pg_catalog.format_type(a.atttypid,a.atttypmod) AS type,a.atttypmod AS type_modifier,
 a.attnotnull AS not_null,a.attidentity AS identity,a.attgenerated AS generated,
 pg_catalog.pg_get_expr(d.adbin,d.adrelid) AS default_expression,
 col.collname AS collation
 FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
 LEFT JOIN pg_catalog.pg_collation col ON col.oid=a.attcollation
 WHERE n.nspname='public' AND a.attnum>0 AND NOT a.attisdropped
 AND c.relkind IN ('r','p') ORDER BY c.relname,a.attnum"""
_CONSTRAINTS_SQL = """SELECT t.relname AS table,c.conname AS name,c.contype AS kind,
 c.convalidated AS validated,c.condeferrable AS deferrable,c.condeferred AS deferred,
 pg_catalog.pg_get_constraintdef(c.oid,true) AS definition,
 ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(num,ord)
 LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.num ORDER BY k.ord) AS columns,
 ft.relname AS foreign_table,fn.nspname AS foreign_schema,
 ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(num,ord)
 JOIN pg_catalog.pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.num ORDER BY k.ord) AS foreign_columns,
 c.confdeltype AS ondelete,c.confupdtype AS onupdate
 FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_class t ON t.oid=c.conrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace
 LEFT JOIN pg_catalog.pg_class ft ON ft.oid=c.confrelid
 LEFT JOIN pg_catalog.pg_namespace fn ON fn.oid=ft.relnamespace
 WHERE n.nspname='public' ORDER BY t.relname,c.conname"""
_INDEXES_SQL = """SELECT t.relname AS table,c.relname AS name,i.indisunique AS unique,
 i.indisprimary AS primary,i.indisexclusion AS exclusion,i.indisvalid AS valid,i.indisready AS ready,
 pg_catalog.pg_get_indexdef(i.indexrelid) AS definition,
 pg_catalog.pg_get_expr(i.indpred,i.indrelid) AS predicate,
 pg_catalog.pg_get_expr(i.indexprs,i.indrelid) AS expressions
 FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class t ON t.oid=i.indrelid
 JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace
 WHERE n.nspname='public' ORDER BY t.relname,c.relname"""
_TRIGGERS_SQL = """SELECT t.relname AS table,g.tgname AS name,g.tgenabled AS enabled,
 g.tgisinternal AS internal,pg_catalog.pg_get_triggerdef(g.oid,true) AS definition
 FROM pg_catalog.pg_trigger g JOIN pg_catalog.pg_class t ON t.oid=g.tgrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace
 WHERE n.nspname='public' ORDER BY t.relname,g.tgname"""


async def _query(connection, fence, sql):
    fence.arm([(sql, ())])
    result = await connection.exec_driver_sql(sql)
    fence.complete()
    return [dict(row) for row in result.mappings().all()]


async def _execute(connection, fence, sql):
    fence.arm([(sql, ())])
    await connection.exec_driver_sql(sql)
    fence.complete()


async def _identity(connection, fence, lease):
    rows = await _query(connection, fence, _IDENTITY_SQL)
    _require(len(rows) == 1, "Ambiguous database identity")
    actual = rows[0]
    _require(all(actual[k] == lease[k] for k in ("database", "database_oid", "role", "role_oid")),
             "Actual database/role/OID disagrees with ROOT lease")
    _require(actual["session_role"] == lease["role"] and actual["database_owner"] == lease["role"]
             and actual["database_owner_oid"] == lease["role_oid"],
             "Leased role must own dedicated DB without role switching")
    _require(actual["schema"] == TARGET_SCHEMA and actual["schemas"] == [TARGET_SCHEMA],
             "Explicit sole effective public namespace required; no search_path mutation")
    _require(await _query(connection, fence, _NAMESPACES_SQL) == [{"name": TARGET_SCHEMA}],
             "Foreign user namespace in dedicated database")
    return actual


async def _catalog(connection, fence, manifest):
    relations = await _query(connection, fence, _RELATIONS_SQL)
    _require({r["name"] for r in relations} == set(manifest["tables"])
             and len(relations) == len(manifest["tables"])
             and all(r["schema"] == TARGET_SCHEMA and r["kind"] == "r" and r["persistence"] == "p" for r in relations),
             "Exact selected physical table set required; no extra tables/views/sequences")
    tables = {name: {"relation": next(r for r in relations if r["name"] == name)}
              for name in manifest["tables"]}
    for key, sql in (("columns", _COLUMNS_SQL), ("constraints", _CONSTRAINTS_SQL),
                     ("indexes", _INDEXES_SQL), ("triggers", _TRIGGERS_SQL)):
        rows = await _query(connection, fence, sql)
        _require(all(r["table"] in tables for r in rows), "Foreign table in catalog manifest")
        for name in tables:
            tables[name][key] = [r for r in rows if r["table"] == name]
    return {"tables": tables, "functions": await _query(connection, fence, _FUNCTIONS_SQL),
            "extensions": await _query(connection, fence, _EXTENSIONS_SQL)}


def _check_catalog(catalog, manifest):
    """Positive structural checks plus complete definitions frozen in receipt.

    SQL text/cast normalization belongs to PostgreSQL: we store full pg_get_*
    definitions and compare them exactly in the later process. The initial
    creation proof is exact verified ORM metadata + a closed SQL emission plan.
    """
    bootstrap = manifest["bootstrap"]
    index_ops = [o for o in bootstrap["after_tables"] if o["kind"] == "index"]
    action = {None: "a", "CASCADE": "c", "SET NULL": "n", "RESTRICT": "r", "NO ACTION": "a"}
    for name, expected in manifest["tables"].items():
        table = catalog["tables"][name]
        _require([c["name"] for c in table["columns"]] == [c["name"] for c in expected["columns"]],
                 "Catalog column set/order mismatch: " + name)
        for column, spec in zip(table["columns"], expected["columns"]):
            _require(column["not_null"] == (not spec["nullable"]) and column["identity"] == "",
                     "Catalog nullability/identity mismatch")
            _require(column["generated"] == ("s" if spec["computed"] else ""), "Computed column missing")
        constraints = table["constraints"]
        extra_constraints = 1 if name in {"object_links", "counterparties"} else 0
        _require(len(constraints) == 1 + len(expected["foreign_keys"]) + len(expected["unique_constraints"])
                 + len(expected["check_constraints"]) + extra_constraints,
                 "Unexpected catalog constraint count: " + name)
        _require(all(c["validated"] and not c["deferrable"] and not c["deferred"] for c in constraints),
                 "Constraint validation/timing mismatch")
        pks = [c for c in constraints if c["kind"] == "p"]
        _require(len(pks) == 1 and pks[0]["columns"] == expected["primary_key"], "PK mismatch")
        actual_fks = [c for c in constraints if c["kind"] == "f"]
        _require(len(actual_fks) == len(expected["foreign_keys"]), "FK count mismatch")
        for fk in expected["foreign_keys"]:
            target, target_column = fk["target"].rsplit(".", 1)
            matches = [c for c in actual_fks if c["columns"] == fk["columns"]
                and c["foreign_table"] == target and c["foreign_schema"] == TARGET_SCHEMA
                and c["foreign_columns"] == [target_column] and c["ondelete"] == action[fk["ondelete"]]
                and c["onupdate"] == action[fk["onupdate"]]
                and (fk["name"] is None or c["name"] == fk["name"])]
            _require(len(matches) == 1, "FK catalog mismatch: " + name)
        required_names = {c["name"] for c in expected["check_constraints"]}
        required_names |= {c["name"] for c in expected["unique_constraints"] if c["name"]}
        if name == "object_links":
            required_names.add("object_links_no_overlap")
            _require(any(c["name"] == "object_links_no_overlap" and c["kind"] == "x" for c in constraints),
                     "Exact ObjectLink exclusion missing")
        if name == "counterparties":
            required_names.add("ck_counterparty_lifecycle_status")
        _require(required_names <= {c["name"] for c in constraints}, "Required constraint missing")
        indexes = table["indexes"]
        expected_index_count = 1 + len(expected["unique_constraints"]) + len(expected["indexes"])
        expected_index_count += sum(o["table"] == name for o in index_ops) + (name == "object_links")
        _require(len(indexes) == expected_index_count and all(i["valid"] and i["ready"] for i in indexes),
                 "Unexpected/unready catalog index: " + name)
        required_indexes = {i["name"] for i in expected["indexes"]}
        for op in index_ops:
            if op["table"] == name:
                match = re.search(r"\bINDEX\s+(?:IF NOT EXISTS\s+)?(\w+)", op["sql"], re.I)
                _require(match is not None, "Bootstrap index identity unknown")
                required_indexes.add(match[1])
        _require(required_indexes <= {i["name"] for i in indexes}, "Required index missing")
        user_triggers = [t for t in table["triggers"] if not t["internal"]]
        _require([t["name"] for t in user_triggers] == (
            ["canonical_data_entry_guard_trg"] if name == "data_entries" else []), "Unexpected/missing user trigger")
        _require(all(t["enabled"] == "O" for t in table["triggers"]), "Disabled trigger")
    functions = catalog["functions"]
    _require({f["name"] for f in functions} == {"phone_to_e164", "protect_canonical_data_entry"}
             and len(functions) == 2, "Unexpected/missing schema function")
    function_ops = bootstrap["before_tables"] + [o for o in bootstrap["after_tables"] if o["kind"] == "function"]
    for op in function_ops:
        name = re.search(r"\bFUNCTION\s+(\w+)\(", op["sql"], re.I)[1]
        body = re.search(r"\bAS\s+(\$[A-Za-z0-9_]*\$)(.*?)\1", op["sql"], re.I | re.S)
        _require(body is not None, "Function body source unknown")
        row = next(f for f in functions if f["name"] == name)
        phone = name == "phone_to_e164"
        _require(row["schema"] == TARGET_SCHEMA and row["body"] == body[2]
                 and row["arguments"] == ("raw text" if phone else "")
                 and row["returns"] == ("character varying" if phone else "trigger")
                 and row["language"] == "plpgsql" and not row["security_definer"] and row["config"] is None
                 and row["volatility"] == ("i" if phone else "v") and row["parallel"] == ("s" if phone else "u"),
                 "Exact function signature/body/flags mismatch")
    _require({e["name"] for e in catalog["extensions"]} == {"plpgsql", "btree_gist"},
             "Required exact extension set mismatch")
    _require(all(e["schema"] == ("pg_catalog" if e["name"] == "plpgsql" else TARGET_SCHEMA)
                 for e in catalog["extensions"]), "Extension outside approved namespace")


def _actual_tables(models, manifest, connection):
    """Check already imported actual ORM Tables; this helper cannot import app."""
    root = _root()
    for module_name, relative in (("app.models", "clearledger/server/app/models.py"),
            ("app.database", "clearledger/server/app/database.py"), ("app.config", "clearledger/server/app/config.py")):
        module = sys.modules.get(module_name)
        _require(module is not None and Path(module.__file__).resolve() == (root / relative).resolve(),
                 "ORM import outside frozen tree")
        _source(root, relative)
    tables = {}
    for name in manifest["topological_order"]:
        expected = manifest["tables"][name]
        actual = getattr(models, expected["class"]).__table__
        _require(_metadata_shape(actual, connection.dialect) == _expected_shape(expected),
                 "Actual ORM metadata differs from approved full source manifest: " + name)
        tables[name] = actual
    _require(all(t.metadata is next(iter(tables.values())).metadata for t in tables.values()),
             "Mixed metadata source")
    return tables


async def provision_selected_schema(connection, root_approval):
    """Future ROOT-only DDL stage; no test execution, global engine use or cleanup.

    Requires engine.connect(), NOT engine.begin(). Commit/rollback is only for
    this function's one transaction. Errors propagate; no warning-and-skip.
    Connection-local exact statement guard is removed even on failure.
    """
    manifest = _validate_approval(connection, root_approval, "provision")
    # Framework imports are deliberately below every static boundary check.
    from sqlalchemy import event
    from sqlalchemy.schema import CreateIndex, CreateTable

    fence = _StatementFence()
    target = connection.sync_connection
    listener = fence.before_cursor_execute
    event.listen(target, "before_cursor_execute", listener)
    try:
        async with connection.begin():
            transaction = await _query(connection, fence, _TRANSACTION_SQL)
            identity = await _identity(connection, fence, root_approval["lease"])
            _require(not await _query(connection, fence, _RELATIONS_SQL), "Dedicated DB must be empty before provision")
            _require(not await _query(connection, fence, _FUNCTIONS_SQL),
                     "No overwrite: both function names/signatures must be absent")
            extensions = await _query(connection, fence, _EXTENSIONS_SQL)
            _require({e["name"] for e in extensions} <= {"plpgsql", "btree_gist"}, "Foreign extension in dedicated DB")
            # The sole app import is physically inside this guarded runtime
            # function, after harness approval and actual leased DB identity.
            models = importlib.import_module("app.models")
            tables = _actual_tables(models, manifest, connection)
            # A logical SQLAlchemy begin is insufficient if a caller configured
            # DBAPI autocommit. Two allocated PostgreSQL XID probes must agree
            # before the first DDL; no isolation GUC/connection setting is changed.
            _require(await _query(connection, fence, _TRANSACTION_SQL) == transaction,
                     "One physical PostgreSQL transaction required before DDL")
            # CREATE OR REPLACE literal remains exact, but preflight forbids an existing function.
            for op in manifest["bootstrap"]["before_tables"]:
                await _execute(connection, fence, op["sql"])
            if "btree_gist" not in {e["name"] for e in extensions}:
                await _execute(connection, fence, manifest["bootstrap"]["required_extension"]["sql"])
            for name in manifest["topological_order"]:
                table = tables[name]
                plan = [str(CreateTable(table).compile(dialect=connection.dialect))]
                plan.extend(str(CreateIndex(i).compile(dialect=connection.dialect)) for i in table.indexes)
                fence.arm([(sql, ()) for sql in plan])
                await connection.run_sync(lambda sync, selected=table: selected.create(sync, checkfirst=False))
                fence.complete()
            for op in manifest["bootstrap"]["after_tables"]:
                await _execute(connection, fence, op["sql"])
            catalog = await _catalog(connection, fence, manifest)
            _check_catalog(catalog, manifest)
            _require(await _query(connection, fence, _TRANSACTION_SQL) == transaction,
                     "Provision transaction changed before commit")
            fence.complete()
        # Receipt is built only after our transaction commits successfully.
        ddl = [entry for entry in fence.executed if entry["ddl"]]
        return {"format": "service-location-schema-ready/v1", "schema_ready": True,
            "stage": "schema-provisioned", "approval_id": root_approval["approval_id"],
            "lease": dict(root_approval["lease"]), "identity": identity,
            "provision_transaction": transaction,
            "external_lease": dict(root_approval["external_lease"]),
            "external_lease_sha256": root_approval["external_lease_sha256"],
            "root_extra_ddl_approval": list(root_approval["root_extra_ddl_approval"]),
            "fixture_sha256": root_approval["fixture_sha256"],
            "manifest_sha256": manifest_sha256(manifest), "harness_sha256": root_approval["harness_sha256"],
            "tables": list(manifest["tables"]), "table_manifest": catalog["tables"],
            "catalog": catalog, "catalog_sha256": manifest_sha256(catalog),
            "executed_ddl": ddl, "executed_ddl_sha256": manifest_sha256(ddl),
            "test_execution": "NOTRUN", "source_budget": manifest["source_budget"]}
    finally:
        event.remove(target, "before_cursor_execute", listener)


async def verify_schema(connection, receipt, root_approval):
    """Future separate process: catalog-only verification; zero ORM/fixture DDL.

    ROOT must preserve/approve the receipt digest out of band in its harness;
    a self-asserted JSON receipt is not an authorization credential.
    """
    manifest = _validate_approval(connection, root_approval, "verify")
    _require(isinstance(receipt, dict) and receipt.get("format") == "service-location-schema-ready/v1"
             and receipt.get("schema_ready") is True and receipt.get("stage") == "schema-provisioned",
             "Committed provision receipt required")
    _require(receipt.get("lease") == root_approval["lease"] and all(receipt.get(k) == root_approval[k]
             for k in ("fixture_sha256", "manifest_sha256", "harness_sha256")), "Receipt lease/source freeze mismatch")
    _require(all(receipt.get(k) == root_approval[k] for k in (
        "external_lease", "external_lease_sha256", "root_extra_ddl_approval")), "Receipt external lease/DDL approval mismatch")
    _require(root_approval.get("receipt_sha256") == manifest_sha256(receipt), "ROOT-approved receipt digest required")
    _require(receipt.get("tables") == list(manifest["tables"]), "Receipt table set mismatch")
    _require(receipt.get("catalog_sha256") == manifest_sha256(receipt.get("catalog")), "Receipt catalog digest mismatch")
    _require(receipt.get("table_manifest") == receipt["catalog"]["tables"], "Receipt table manifest mismatch")
    _require(receipt.get("executed_ddl_sha256") == manifest_sha256(receipt.get("executed_ddl")), "Receipt DDL digest mismatch")
    from sqlalchemy import event

    fence = _StatementFence()
    target = connection.sync_connection
    listener = fence.before_cursor_execute
    event.listen(target, "before_cursor_execute", listener)
    try:
        async with connection.begin():
            identity = await _identity(connection, fence, root_approval["lease"])
            _require(identity == receipt["identity"], "Provision/verification database identity mismatch")
            catalog = await _catalog(connection, fence, manifest)
            _check_catalog(catalog, manifest)
            _require(catalog == receipt["catalog"], "Schema changed since ROOT provision receipt")
            fence.complete()
        _require(not any(e["ddl"] for e in fence.executed), "Verification emitted unexpected DDL")
        return {"schema_ready": True, "stage": "schema-verified", "lease": dict(root_approval["lease"]),
            "manifest_sha256": manifest_sha256(manifest), "receipt_sha256": manifest_sha256(receipt),
            "catalog_sha256": manifest_sha256(catalog), "tables": list(manifest["tables"]),
            "table_manifest": catalog["tables"], "ddl_statements": 0, "test_execution": "NOTRUN"}
    finally:
        event.remove(target, "before_cursor_execute", listener)


async def verify_selected_schema(connection, root_approval):
    """Named preflight adapter: same strict receipt check, not a weaker check."""
    _require(isinstance(root_approval, dict) and "receipt" in root_approval,
             "Pass provision receipt in root_approval['receipt'] for this adapter")
    return await verify_schema(connection, root_approval["receipt"], root_approval)
