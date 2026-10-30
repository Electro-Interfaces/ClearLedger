#!/usr/bin/env python3
"""Source-only Contract evidence. Python 3.13; stdlib + read-only Git, never app imports.

Run from any cwd. Default verifies the bounded reviewed JSON and writes private
manifest/raw candidates/call sites/proof to ignored .artifacts/contract-writers.
--refresh updates ONLY derived hashes/counts in the paired JSON after review.
Candidates deliberately overapproximate writes: dynamic receiver != Contract.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import warnings

PIN = "eb5cdc513275e428e004f134e6b16d417d6f135e"
PREFIX = "clearledger/server/app/"
ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "clearledger/docs/api/CONTRACT_WRITER_INVENTORY_20261030.json"
PRIVATE = ROOT / ".artifacts/contract-writers"
ORM = "app.models.Contract"
RELATED = {"ContractLocation", "ContractLink", "ContractDimension", "OpsContractTerm"}
SQL_WRITE = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?)\s+(?:(?:core|public)\.)?(contracts|contract_locations|contract_links|contract_dimensions|ops_contract_terms)\b", re.I)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args, data=None):
    return subprocess.run(["git", "-C", str(ROOT), *args], input=data,
                          check=True, stdout=subprocess.PIPE).stdout


def dump(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def parse(data, filename):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(data.decode("utf-8-sig"), filename=filename)


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def symbols(tree):
    found = {}

    def walk(node, parents=()):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                key = ".".join((*parents, child.name))
                if key in found:
                    raise ValueError(f"duplicate source symbol {key}")
                found[key] = child
                walk(child, (*parents, child.name))
            else:
                walk(child, parents)
    walk(tree)
    return found


def imports(tree):
    # Conservative import spelling, not execution or data-flow inference.
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and not n.level:
            for alias in n.names:
                out[alias.asname or alias.name] = f"{n.module}.{alias.name}"
        elif isinstance(n, ast.Import):
            for alias in n.names:
                out[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
    return out


def classify(tree):
    """Only proven imported constructors; unresolved constructors stay unknown."""
    bindings = imports(tree)
    out = []
    for n in ast.walk(tree):
        kind = None
        value = dotted(n.func) if isinstance(n, ast.Call) else ""
        target = value.split(".")[0]
        resolved = bindings.get(target, target) + value[len(target):] if value else ""
        if isinstance(n, ast.Call):
            if resolved == ORM:
                kind = "orm_contract_constructor"
            elif resolved == "app.product_api.dto.Contract":
                kind = "dto_constructor_not_writer"
            elif resolved.startswith("app.models.") and resolved.rsplit(".", 1)[-1] in RELATED:
                kind = "related_constructor"
            elif value.endswith("Contract"):
                kind = "unknown_contract_constructor"
            elif value in {"setattr", "delattr", "eval", "exec", "__import__"} or value.endswith((".execute", ".executemany", ".delete", ".update", ".insert", ".add", ".add_all", ".merge", ".bulk_save_objects", ".bulk_insert_mappings", ".bulk_update_mappings", ".reflect", ".import_module")) or value in {"update", "insert", "delete", "apply_import_values", "mark_reference_changes"}:
                kind = "mutation_or_dynamic_candidate_unknown_receiver"
            elif value.endswith((".append", ".extend", ".remove", ".clear", ".pop", ".setdefault")):
                kind = "collection_mutation_unknown_receiver"
            if kind:
                out.append((n, kind, resolved))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            for match in SQL_WRITE.finditer(n.value):
                out.append((n, "literal_sql_write", match.group(1).lower()))
        elif isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.append((n, "attribute_store_unknown_receiver", dotted(n)))
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.append((n, "subscript_store_unknown_receiver", ""))
    return out


def self_check():
    # Counterexamples exercise classification boundaries, not app behavior.
    cases = [
        ("from app.models import Contract as C\nx=C(number='x')", "orm_contract_constructor"),
        ("from app.product_api import dto\nx=dto.Contract(id='x')", "dto_constructor_not_writer"),
        ("from somewhere import Contract\nx=Contract()", "unknown_contract_constructor"),
        ("from app.models import ContractLocation\nx=ContractLocation()", "related_constructor"),
        ("setattr(row, field, None)", "mutation_or_dynamic_candidate_unknown_receiver"),
        ("text('UPDATE core.contracts SET title=:v')", "literal_sql_write"),
        ("text('SELECT * FROM contracts')", None),
        ("row.title = None", "attribute_store_unknown_receiver"),
        ("db.execute(text(f'UPDATE {table} SET title=:v'))", "mutation_or_dynamic_candidate_unknown_receiver"),
        ("row.extra_metadata['warehouse'] = payload", "subscript_store_unknown_receiver"),
        ("row.links.append(link)", "collection_mutation_unknown_receiver"),
    ]
    for source, expected in cases:
        kinds = [k for _, k, _ in classify(ast.parse(source))]
        assert (expected in kinds) if expected else not kinds, (source, kinds)
    # Mutation must change expression hash; whitespace must not change AST hash.
    a = ast.dump(ast.parse("x=None"), include_attributes=False)
    assert a == ast.dump(ast.parse("x = None\n"), include_attributes=False)
    assert a != ast.dump(ast.parse("x=0"), include_attributes=False)
    return len(cases) + 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 13):
        raise SystemExit("Use Python >=3.13 for pinned app f-string syntax")
    if sys.flags.optimize:
        raise SystemExit("Refuse optimized Python: evidence assertions must be enabled")
    controls = self_check()
    public = json.loads(PUBLIC.read_bytes())
    assert public["pin"] == PIN
    assert len(PUBLIC.read_bytes()) < 150_000, "public inventory must stay bounded"
    assert len(public["families"]) <= 40 and len(public["references"]) <= 180
    # Read complete pinned subtree, including non-Python files and exact CRLF.
    entries = git("ls-tree", "-rz", PIN, "--", PREFIX).split(b"\0")
    manifest, sources, trees, index, candidates, calls, hits = [], {}, {}, {}, [], [], []
    for entry in entries:
        if not entry:
            continue
        meta, name = entry.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        path = name.decode()
        assert kind == "blob" and mode in {"100644", "100755"}, (path, mode)
        data = git("cat-file", "blob", oid)
        assert (ROOT / path).read_bytes() == data, f"working file drift: {path}"
        manifest.append({"path": path, "git_blob": oid, "sha256": digest(data), "bytes": len(data)})
        sources[path] = data
        if not path.endswith(".py"):
            continue
        tree = parse(data, path)
        trees[path] = tree
        index[path] = symbols(tree)
        text = data.decode("utf-8-sig")
        for line, value in enumerate(text.splitlines(), 1):
            if re.search(r"contract|setattr|bulk_|reflect|restore|__import__|exec\(|eval\(", value, re.I):
                hits.append({"path": path, "line": line, "text": value})
        for n, decision, resolved in classify(tree):
            owners = [(name, node) for name, node in index[path].items() if node.lineno <= n.lineno <= node.end_lineno]
            owner = min(owners, key=lambda v: v[1].end_lineno-v[1].lineno)[0] if owners else "<module>"
            candidates.append({"path": path, "line": n.lineno, "owner": owner,
                               "decision": decision, "resolved_spelling": resolved,
                               "expression": ast.unparse(n),
                               "ast_sha256": digest(ast.dump(n, include_attributes=False).encode())})
        for call in ast.walk(tree):
            if isinstance(call, ast.Call):
                owners = [(name, node) for name, node in index[path].items()
                          if node.lineno <= call.lineno <= node.end_lineno]
                owner = min(owners, key=lambda v: v[1].end_lineno-v[1].lineno)[0] if owners else "<module>"
                calls.append({"path": path, "owner": owner, "line": call.lineno,
                              "column": call.col_offset, "callee": dotted(call.func),
                              "resolution": "spelling_only"})
    # Reject new untracked app source; the inventory universe must be explicit.
    assert not git("ls-files", "--others", "--exclude-standard", "--", PREFIX).strip(), "untracked app files"
    refs = public["references"]
    assert len({r["id"] for r in refs}) == len(refs), "duplicate reference IDs"
    derived_refs = []
    for ref in refs:
        path = ref["path"]
        if path not in sources:
            data = git("show", f"{PIN}:{path}")
            assert (ROOT/path).read_bytes() == data, f"evidence drift: {path}"
            sources[path] = data
            tree = parse(data, path)
            trees[path], index[path] = tree, symbols(tree)
        node = index[path][ref["symbol"]]
        derived = {"file_sha256": digest(sources[path]), "start": node.lineno,
                   "end": node.end_lineno,
                   "ast_sha256": digest(ast.dump(node, include_attributes=False).encode())}
        if ref.get("anchors"):
            anchors = []
            for anchor in ref["anchors"]:
                matches = [n for n in ast.walk(node) if getattr(n, "lineno", None) == anchor["line"] and type(n).__name__ == anchor["kind"]]
                if "column" in anchor:
                    matches = [n for n in matches if n.col_offset == anchor["column"]]
                elif args.refresh and matches:
                    # Initial review anchors the outer expression on this line.
                    matches = [min(matches, key=lambda n: n.col_offset)]
                assert len(matches) == 1, (ref["id"], anchor, len(matches))
                anchors.append({"line": anchor["line"], "kind": anchor["kind"], "column": matches[0].col_offset,
                                "ast_sha256": digest(ast.dump(matches[0], include_attributes=False).encode())})
            derived["anchors"] = anchors
        if args.refresh:
            ref.update(derived)
        else:
            for key, value in derived.items():
                assert ref[key] == value, (ref["id"], key, "evidence changed")
        derived_refs.append(ref)
    ids = {r["id"] for r in refs}
    families = public["families"]
    assert len({f["id"] for f in families}) == len(families), "duplicate family IDs"
    model = index[PREFIX + "models.py"]["Contract"]
    columns = {n.target.id for n in model.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    assert sorted(columns) == public["contract_model_columns"]
    for family in families:
        assert family["owner"] and family["fields"] and family["decision"] and family["references"]
        assert set(family["references"]) <= ids, family["id"]
        for key, fields in family["fieldsets"].items():
            if key.startswith("contract_"):
                if fields is None:
                    assert family["id"] == "CW26", "unknown must remain explicit"
                else:
                    assert len(fields) == len(set(fields)) and set(fields) <= columns, (family["id"], key)
    for countercase in public["countercases"]:
        assert set(countercase["references"]) <= ids
    assert len({c["id"] for c in public["countercases"]}) == len(public["countercases"])
    for document in public["context_documents"]:
        if document["repository"] == "ledger":
            blob = git("show", f"{document['commit']}:{document['path']}")
            assert digest(blob) == document["sha256"]
            assert (ROOT/document["path"]).read_bytes() == blob
    edges = public["call_edges"]
    assert len({e["id"] for e in edges}) == len(edges), "duplicate edge IDs"
    all_ids = [r["id"] for r in refs] + [f["id"] for f in families] + [c["id"] for c in public["countercases"]] + [e["id"] for e in edges]
    assert len(all_ids) == len(set(all_ids)), "IDs must be unique across record kinds"
    by_id = {r["id"]: r for r in refs}
    for edge in edges:
        assert edge["from"] in ids and edge["to"] in ids
        source = by_id[edge["from"]]
        node = index[source["path"]][source["symbol"]]
        matches = [c for c in ast.walk(node) if isinstance(c, ast.Call) and dotted(c.func) == edge["spelling"]]
        assert matches, (edge["id"], "missing caller spelling")
        derived = [{"line": c.lineno, "column": c.col_offset,
                    "ast_sha256": digest(ast.dump(c, include_attributes=False).encode())}
                   for c in matches]
        if args.refresh:
            edge["calls"] = derived
        else:
            assert edge["calls"] == derived, edge["id"]
    # Every detected exact ORM constructor / SQL sink must be reviewed or refused.
    reviewed = {(r["path"], a["line"]) for r in refs for a in r.get("anchors", [])}
    exact = [c for c in candidates if c["decision"] in {"orm_contract_constructor", "literal_sql_write"}]
    assert all((c["path"], c["line"]) in reviewed for c in exact), "unreviewed exact constructor/SQL sink"
    proof = {"generator_sha256": digest(Path(__file__).read_bytes()),
             "app_files": len(manifest), "python_files": len(trees.keys() & {x["path"] for x in manifest}),
             "app_manifest_sha256": digest(dump(manifest)), "byte_equal_files": len(manifest),
             "candidate_count": len(candidates), "raw_hit_count": len(hits), "callsite_count": len(calls),
             "exact_constructor_count": sum(c["decision"] == "orm_contract_constructor" for c in exact),
             "literal_sql_sink_count": sum(c["decision"] == "literal_sql_write" for c in exact),
             "family_count": len(families), "reference_count": len(refs), "call_edge_count": len(edges),
             "countercase_count": len(public["countercases"]), "pure_controls": controls,
             "unknown_dynamic_receivers": "not resolved; candidate count is not writer count"}
    if args.refresh:
        public["proof"] = proof
        PUBLIC.write_bytes(dump(public))
    else:
        assert public["proof"] == proof, "proof counts/digest changed"
    assert git("check-ignore", str(PRIVATE / "proof.json")).strip(), "private output not ignored"
    PRIVATE.mkdir(parents=True, exist_ok=True)
    for name, value in [("manifest", manifest), ("raw-hits", hits), ("candidates", candidates), ("calls", calls), ("proof", proof)]:
        (PRIVATE / f"{name}.json").write_bytes(dump(value))
    print(json.dumps({"pin": PIN, "status": "source-proof-pass", **proof}, ensure_ascii=False))


if __name__ == "__main__":
    main()
