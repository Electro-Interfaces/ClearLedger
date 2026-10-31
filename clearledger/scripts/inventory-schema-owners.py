#!/usr/bin/env python3
"""Bounded, stdlib-only AST inventory of immutable schema source; never runs SQL.

Reads local git objects, not a worktree environment. Output is JSON, containing
paths/lines/hashes/counts only, never SQL text, credentials or private deploy files.
Counts describe literal AST nodes; they are not expanded/executed DDL statements.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

SOURCE = "ccfcd653f5cc01490bbf8571f9e89eae4a230ead"
PREFIX = "clearledger/server/"
COMMAND = re.compile(r"^\s*(?:(?:CREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:UNIQUE|UNLOGGED|TEMPORARY|TEMP)\s+)?|ALTER\s+|DROP\s+)"
    r"(?:TABLE|INDEX|FUNCTION|TRIGGER|VIEW|MATERIALIZED|SEQUENCE|SCHEMA|EXTENSION|TYPE|ROLE|DATABASE)\b"
    r"|DO\s+\$|TRUNCATE\s+|COMMENT\s+ON\s+|(?:GRANT|REVOKE)\s+(?:ALL|SELECT|USAGE|CREATE)\b)", re.I)
DML = re.compile(r"^\s*(?:UPDATE\s+\S+\s+SET\b|INSERT\s+INTO\s+|DELETE\s+FROM\s+|WITH\s+\w+\s+AS\s*\()", re.I)
PIN_PATHS = ["app/database.py", "app/main.py", "app/models.py", "app/models_partner.py",
    "app/models_product_budget.py", "app/models_docs_portal.py", "app/services/phone_e164.py",
    "app/routers/perimeter_router.py", "app/services/app_registry.py", "alembic/env.py",
    "alembic/versions/20261025_01_baseline.py", "alembic.ini",
    "tests/test_schema_namespace_ownership.py", "tests/test_partner_schema_compatibility.py"]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def analyze(raw, path):
    tree = ast.parse(raw.decode("utf-8-sig"), filename=path)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)}
    sql, dml, calls, declarations = [], [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if COMMAND.match(node.value):
                sql.append(node)
            elif DML.match(node.value):
                dml.append(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "create_all":
            calls.append({"line": node.lineno, "method": "create_all"})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {
                "create_all", "execute", "exec_driver_sql", "begin", "begin_nested"}:
            calls.append({"line": node.lineno, "method": node.func.attr})
        if isinstance(node, ast.Assign) and any(isinstance(n, ast.Name) and n.id == "__tablename__" for n in node.targets):
            if isinstance(node.value, ast.Constant):
                declarations.append({"line": node.lineno, "name": node.value.value})
    groups = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id.endswith("_DDL") for t in node.targets):
            contained = [n for n in sql if node.lineno <= n.lineno <= node.end_lineno]
            groups.append({"symbol": next(t.id for t in node.targets if isinstance(t, ast.Name)),
                "line": node.lineno, "end_line": node.end_lineno, "expression": type(node.value).__name__, "ddl_literal_nodes": len(contained)})
    owners = Counter()
    for node in sql:
        ancestor = parents.get(node)
        while ancestor is not None and not isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ancestor = parents.get(ancestor)
        owners[ancestor.name if ancestor else "<module constants>"] += 1
    return {"ddl_literal_nodes": len(sql), "dml_literal_nodes": len(dml),
        "ddl_first_line": min((n.lineno for n in sql), default=None),
        "ddl_owners": dict(sorted(owners.items())), "calls": sorted(calls, key=lambda x: (x["line"], x["method"])),
        "named_ddl_blocks": groups, "declarations": declarations}


def inventory(repo):
    actual = git(repo, "rev-parse", SOURCE + "^{commit}").decode().strip()
    if actual != SOURCE:
        raise ValueError("Immutable source mismatch")
    names = git(repo, "ls-tree", "-r", "--name-only", SOURCE, PREFIX).decode().splitlines()
    if len(names) > 4096:
        raise ValueError("Source inventory bound exceeded")
    owners, pins, db = [], [], None
    source_files = 0
    for path in names:
        relative = path.removeprefix(PREFIX)
        is_app = relative.startswith("app/") and relative.endswith(".py")
        if not is_app and relative not in PIN_PATHS:
            continue
        raw = git(repo, "show", SOURCE + ":" + path)
        if len(raw) > 2_000_000:
            raise ValueError("Source file bound exceeded")
        if relative in PIN_PATHS:
            pins.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(),
                "blob": git(repo, "rev-parse", SOURCE + ":" + path).decode().strip(), "lines": len(raw.splitlines())})
        if not is_app:
            continue
        source_files += 1
        item = analyze(raw, path)
        if relative == "app/database.py":
            db = {key: item[key] for key in ("ddl_literal_nodes", "dml_literal_nodes", "named_ddl_blocks", "calls")}
        if item["ddl_literal_nodes"] or any(c["method"] == "create_all" for c in item["calls"]):
            owners.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(),
                **{key: item[key] for key in ("ddl_literal_nodes", "dml_literal_nodes", "ddl_first_line", "ddl_owners")},
                "create_all_lines": [c["line"] for c in item["calls"] if c["method"] == "create_all"]})
    if len(owners) > 128 or db is None:
        raise ValueError("Owner inventory bound exceeded")
    return {"source_commit": actual, "scope": "tracked server/app Python AST; fixed source pins; no imports/DB",
        "count_unit": "SQL-looking string literal AST nodes excluding docstrings; not SQL statements or execution counts",
        "app_python_files_scanned": source_files, "schema_source_files": len(owners),
        "ddl_literal_nodes": sum(item["ddl_literal_nodes"] for item in owners),
        "pins": pins, "database": db, "schema_sources": owners}


def main():
    if sys.version_info < (3, 12):
        raise SystemExit("Python >=3.12 is required to parse the pinned application source")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(inventory(args.repo), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
