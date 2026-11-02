#!/usr/bin/env python3
"""Source-only service -> router inventory; Python 3.13+, stdlib only.

Reads committed blobs, never imports app or follows working-tree source files.
Outputs private evidence to an explicit NEW directory inside the repository.
No output is suitable for publication without review; public.json is bounded to
code references, names and hashes. This is NOT a runtime call graph.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import time
import warnings

PREFIX = "clearledger/server/"
APP = PREFIX + "app/"
MAX_FILES = 4000
MAX_BLOB = 8 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
MAX_PUBLIC = 1024 * 1024
MAX_SECONDS = 90


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ast_hash(node):
    return sha(ast.dump(node, include_attributes=False).encode())


def dump(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def spelling(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = spelling(node.value)
        return head + "." + node.attr if head else None
    return None


def module_name(path):
    name = path.removeprefix(PREFIX).removesuffix(".py").replace("/", ".")
    return name.removesuffix(".__init__")


def absolute_from(module, is_package, level, tail):
    if not level:
        return tail or ""
    package = module.split(".") if is_package else module.split(".")[:-1]
    if level > len(package):
        return None
    return ".".join(package[:len(package) - level + 1] + ([tail] if tail else []))


class Source(ast.NodeVisitor):
    """Retains every AST import, including nested/guarded sites, and call spellings."""

    def __init__(self, path, data):
        self.path, self.module = path, module_name(path)
        self.source_sha256 = sha(data)
        self.package = path.endswith("/__init__.py")
        self.tree = ast.parse(data, filename=path)
        self.scope, self.guards = [], []
        self.imports, self.calls, self.dynamic, self.defs = [], [], [], {}
        self.stores = []
        self.visit(self.tree)

    def ref(self, node):
        return {"path": self.path, "line": node.lineno, "end_line": node.end_lineno,
                "column": node.col_offset, "scope": list(self.scope),
                "source_sha256": self.source_sha256,
                "guards": list(self.guards), "ast_sha256": ast_hash(node)}

    def definition(self, node):
        ref = self.ref(node)
        ref.update(kind=type(node).__name__, name=node.name,
                   decorators=[spelling(d.func if isinstance(d, ast.Call) else d)
                               for d in node.decorator_list])
        # Definition-local observations, not transitive effects or ownership proof.
        ref["call_spellings"] = sorted({s for n in ast.walk(node) if isinstance(n, ast.Call)
                                        if (s := spelling(n.func))})
        self.defs[".".join(self.scope + [node.name])] = ref
        for d in node.decorator_list:
            self.visit(d)
        # Defaults/annotations are outside the function body scope.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.visit(node.args)
            if node.returns:
                self.visit(node.returns)
        else:
            for base in node.bases:
                self.visit(base)
            for kw in node.keywords:
                self.visit(kw)
        self.scope.append(node.name)
        if hasattr(node, "args"):
            for arg in ast.walk(node.args):
                if isinstance(arg, ast.arg):
                    self.stores.append((list(self.scope), arg.arg, arg.lineno))
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    visit_FunctionDef = definition
    visit_AsyncFunctionDef = definition
    visit_ClassDef = definition

    def guarded(self, node):
        # Branch is explicit; no evaluation, including TYPE_CHECKING or try imports.
        for field, value in ast.iter_fields(node):
            if isinstance(value, list) and field in {"body", "orelse", "finalbody", "handlers", "cases"}:
                guard = {"kind": type(node).__name__, "line": node.lineno,
                         "branch": field, "ast_sha256": ast_hash(node)}
                if isinstance(node, ast.If):
                    guard["test_spelling"] = spelling(node.test)
                    guard["test_ast_sha256"] = ast_hash(node.test)
                self.guards.append(guard)
                for child in value:
                    self.visit(child)
                self.guards.pop()
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, ast.AST):
                        self.visit(child)
            elif isinstance(value, ast.AST):
                self.visit(value)

    visit_If = guarded
    visit_Try = guarded
    visit_TryStar = guarded
    visit_ExceptHandler = guarded
    visit_For = guarded
    visit_AsyncFor = guarded
    visit_While = guarded
    visit_With = guarded
    visit_AsyncWith = guarded
    visit_Match = guarded

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(dict(self.ref(node), form="import", requested=alias.name,
                                     bound=alias.asname or alias.name.split(".")[0],
                                     bound_target=alias.name if alias.asname else alias.name.split(".")[0]))

    def visit_ImportFrom(self, node):
        base = absolute_from(self.module, self.package, node.level, node.module)
        for alias in node.names:
            requested = base + "." + alias.name if base else None
            self.imports.append(dict(self.ref(node), form="from", requested=requested,
                                     base=base, relative_level=node.level,
                                     bound=alias.asname or alias.name, bound_target=requested))

    def visit_Call(self, node):
        self.calls.append(dict(self.ref(node), spelling=spelling(node.func), node=node))
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.stores.append((list(self.scope), node.id, node.lineno))


def applicable(binding, call):
    # Syntactic ancestry only: no reaching-definition, dominance or execution claim.
    scope = binding["scope"]
    return call["scope"][:len(scope)] == scope


def loader(call, source):
    name = call["spelling"]
    if name == "__import__":
        return "__import__"
    if name in {"importlib.import_module", "builtins.__import__"}:
        return name.split(".")[-1]
    for binding in source.imports:
        if not applicable(binding, call) or not name:
            continue
        bound, target = binding["bound"], binding["bound_target"]
        if name == bound or name.startswith(bound + "."):
            expanded = (target or "") + name[len(bound):]
            if expanded in {"importlib.import_module", "builtins.__import__"}:
                return expanded.split(".")[-1]
    return None


def dynamic_imports(source):
    found = []
    for call in source.calls:
        kind = loader(call, source)
        if kind is None:
            continue
        node = call["node"]
        item = {k: v for k, v in call.items() if k != "node"}
        item.update(form=kind, status="unknown", requested=None,
                    reason="nonliteral/unsupported loader signature or possibly rebound loader")
        keywords = {k.arg: k.value for k in node.keywords}
        arg = node.args[0] if node.args else keywords.get("name")
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            name = arg.value
            if kind == "import_module" and name.startswith("."):
                package = node.args[1] if len(node.args) > 1 else keywords.get("package")
                if isinstance(package, ast.Constant) and isinstance(package.value, str):
                    level = len(name) - len(name.lstrip("."))
                    name = absolute_from(package.value, True, level, name.lstrip("."))
                else:
                    name = None
            if kind == "__import__":
                level = node.args[4] if len(node.args) > 4 else keywords.get("level")
                if level is not None and not (isinstance(level, ast.Constant) and level.value == 0):
                    name = None
            if name and re.fullmatch(r"[A-Za-z_\w]+(?:\.[A-Za-z_\w]+)*", name):
                item.update(status="literal-supported", requested=name, reason=None)
        item["loader_binding"] = "spelling candidate; rebinding/monkeypatching not evaluated"
        found.append(item)
    return found


def analyze(blobs, pin):
    sources, manifest, errors = {}, [], []
    for path, oid, mode, data in blobs:
        row = {"path": path, "git_blob": oid, "mode": mode,
               "bytes": len(data), "sha256": sha(data), "ast": "not-python"}
        if path.endswith(".py"):
            try:
                with warnings.catch_warnings(record=True) as seen:
                    warnings.simplefilter("always")
                    source = Source(path, data)
                sources[source.module] = source
                row.update(ast="parsed", ast_sha256=ast_hash(source.tree),
                           parse_warnings=[{"kind": w.category.__name__, "line": w.lineno} for w in seen])
            except (SyntaxError, UnicodeError, ValueError, RecursionError) as exc:
                row.update(ast="unknown", error=type(exc).__name__, line=getattr(exc, "lineno", None))
                errors.append(dict(row))
        manifest.append(row)

    def owner(target, seen=()):
        if not target or target in seen:
            return {"requested": target, "kind": "unknown", "reason": "unresolved or re-export cycle"}
        if target in sources:
            return {"requested": target, "kind": "module", "path": sources[target].path}
        mod, _, symbol = target.rpartition(".")
        source = sources.get(mod)
        if source:
            if symbol in source.defs:
                return dict(source.defs[symbol], requested=target, module=mod)
            exports = [i for i in source.imports if not i["scope"] and i["bound"] == symbol]
            if len(exports) == 1:
                return dict(owner(exports[0]["bound_target"], seen + (target,)), reexport_ref=exports[0])
        return {"requested": target, "kind": "unknown", "reason": "not a parsed module/top-level definition/simple re-export"}

    sites, all_imports, dynamic = [], [], []
    for mod, source in sorted(sources.items()):
        if not mod.startswith("app.services.") and mod != "app.services":
            continue
        all_imports.extend(source.imports)
        dyn = dynamic_imports(source)
        dynamic.extend(dyn)
        for item in source.imports + dyn:
            target = item["requested"] or ""
            is_router = target == "app.routers" or target.startswith("app.routers.")
            if not is_router:
                continue
            scopes = [source.defs[".".join(item["scope"][:i])]
                      for i in range(1, len(item["scope"]) + 1)
                      if ".".join(item["scope"][:i]) in source.defs]
            site = dict(item, owner=owner(target), calls=[],
                        enclosing_definitions=[{k: s[k] for k in
                            ("path", "line", "end_line", "kind", "name", "ast_sha256")} for s in scopes])
            if "bound" in item and item["bound"] != "*":
                for call in source.calls:
                    name = call["spelling"]
                    bound = item["bound"]
                    if name and (name == bound or name.startswith(bound + ".")) and applicable(item, call):
                        expanded = (item["bound_target"] or "") + name[len(bound):]
                        # `import app.routers.x` binds `app`; exclude unrelated app.* calls.
                        if item["form"] == "import" and not (expanded == target or expanded.startswith(target + ".")):
                            continue
                        edge = {k: v for k, v in call.items() if k != "node"}
                        edge.update(target=expanded, owner=owner(expanded), resolution="source-spelling-only",
                                    possible_shadowing=any(n == bound and call["scope"][:len(s)] == s
                                                          for s, n, _ in source.stores))
                        site["calls"].append(edge)
            sites.append(site)
    sites.sort(key=lambda s: (s["path"], s["line"], s.get("bound", ""), s["requested"] or ""))
    for i, site in enumerate(sites, 1):
        site["id"] = "E%02d" % i
    public = {"schema": "service-router-boundaries-v1", "git_pin": pin,
              "app_path": APP.rstrip("/"), "manifest_sha256": sha(dump(manifest)),
              "coverage": {"files": len(manifest), "bytes": sum(r["bytes"] for r in manifest),
                           "python_parsed": len(sources), "parse_unknown": len(errors),
                           "service_import_bindings": len(all_imports), "router_bindings": len(sites),
                           "router_import_sites": len({(s["path"], s["line"]) for s in sites})},
              "limitations": ["No application execution, imports, ORM, DB or network.",
                              "Calls are syntactic spelling candidates, not runtime/reaching-definition edges.",
                              "Guards retained, never evaluated; no automatic TYPE_CHECKING exemption.",
                              "Arbitrary computed loaders, assignment aliases, getattr, exec and monkeypatching are not resolved.",
                              "Owner call spellings include nested bodies, are not transitive effects."],
              "parse_unknowns": errors, "edges": sites, "dynamic_loaders": dynamic}
    public["parse_warnings"] = [{"path": r["path"], "warnings": r["parse_warnings"]}
                                for r in manifest if r.get("parse_warnings")]
    return public, manifest, all_imports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-pin", required=True, help="Full 40-hex immutable local commit")
    parser.add_argument("--output", type=Path, required=True, help="New directory inside this repository; never overwrite")
    args = parser.parse_args()
    if sys.version_info < (3, 13):
        parser.error("Python 3.13+ is required for this source grammar")
    if not re.fullmatch(r"[0-9a-f]{40}", args.git_pin):
        parser.error("--git-pin must be a full lowercase commit SHA")
    if not hasattr(signal, "SIGALRM"):
        parser.error("POSIX SIGALRM is required for the hard time budget")
    def timed_out(_signum, _frame):
        raise TimeoutError("inventory hard time budget exceeded")
    signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(MAX_SECONDS)
    started = time.monotonic()
    def git(*argv, data=None):
        remaining = MAX_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            raise ValueError("time budget exceeded")
        return subprocess.run(["git", "--no-replace-objects", *argv], input=data,
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=remaining).stdout
    root = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    # Reject symlink components, traversal and pre-existing output; no external file writes.
    raw_output = args.output if args.output.is_absolute() else Path.cwd() / args.output
    if ".." in raw_output.parts or any(p.is_symlink() for p in [raw_output, *raw_output.parents]):
        parser.error("output traversal/symlinks forbidden")
    output = raw_output.resolve()
    if output == root or not output.is_relative_to(root) or output.exists():
        parser.error("output must be a NEW directory strictly inside the repository")
    if git("rev-parse", args.git_pin + "^{commit}").decode().strip() != args.git_pin:
        parser.error("pin is not an exact local commit")
    rows = git("ls-tree", "-r", "-l", "-z", args.git_pin, "--", APP).split(b"\0")
    entries, total = [], 0
    for raw in rows:
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, kind, oid, size = metadata.decode().split()
        path = raw_path.decode("utf-8")
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("non-regular app blob: " + path)
        if not path.startswith(APP) or ".." in PurePosixPath(path).parts:
            raise ValueError("unexpected app path")
        size = int(size)
        total += size
        if size > MAX_BLOB or total > MAX_TOTAL or len(entries) >= MAX_FILES:
            raise ValueError("source byte/count budget exceeded")
        entries.append((path, oid, mode, size))
    if not entries:
        raise ValueError("empty app snapshot")
    packed = git("cat-file", "--batch", data="".join(e[1] + "\n" for e in entries).encode())
    offset, blobs = 0, []
    for path, oid, mode, size in entries:
        end = packed.index(b"\n", offset)
        if packed[offset:end].decode() != f"{oid} blob {size}":
            raise ValueError("batch header mismatch")
        data = packed[end + 1:end + 1 + size]
        offset = end + 2 + size
        blobs.append((path, oid, mode, data))
    if offset != len(packed):
        raise ValueError("batch framing mismatch")
    public, manifest, imports = analyze(blobs, args.git_pin)
    payloads = {"public.json": dump(public), "manifest.json": dump(manifest),
                "service-imports.json": dump(imports)}
    if len(payloads["public.json"]) > MAX_PUBLIC or time.monotonic() - started > MAX_SECONDS:
        raise ValueError("output/time budget exceeded")
    payloads["receipt.json"] = dump({"git_pin": args.git_pin,
        "python": sys.version.split()[0], "tool_sha256": sha(Path(__file__).read_bytes()),
        "outputs": {k: {"sha256": sha(v), "bytes": len(v)} for k, v in payloads.items()},
        "limits": {"files": MAX_FILES, "blob_bytes": MAX_BLOB, "total_bytes": MAX_TOTAL,
                   "public_bytes": MAX_PUBLIC, "seconds": MAX_SECONDS}})
    output.mkdir(parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    for name, data in payloads.items():
        with (output / name).open("xb") as handle:
            handle.write(data)
        os.chmod(output / name, 0o600)
    print(json.dumps({"output": str(output), "coverage": public["coverage"],
                      "public_sha256": sha(payloads["public.json"])}))


if __name__ == "__main__":
    main()
