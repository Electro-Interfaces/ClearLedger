#!/usr/bin/env python3
"""Bounded offline match-only triage; never call ASGI, endpoints or lifespan."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from functools import lru_cache
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
SPEC = importlib.util.spec_from_file_location("guarded_inventory", HERE.with_name("export-runtime-inventory.py"))
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def synthetic_scope(path, method="GET", protocol="http", root_path=""):
    return {"type": protocol, "path": path, "raw_path": path.encode("ascii"),
            "root_path": root_path, "method": method, "path_params": {}}


def first_full(routes, scope, chain=()):
    """Router's ordered first FULL, including Mount commitment (no sibling fallthrough).

    PARTIAL is remembered but never beats a later FULL. No handle/default/redirect
    or other callable is invoked. An exhausted child mount stays unresolved here.
    """
    from starlette.routing import Match, Mount
    examined, partials = 0, []
    for index, route in enumerate(routes):
        examined += 1
        match, child = route.matches(scope)
        order = [*chain, index]
        if match == Match.PARTIAL:
            partials.append(order)
        if match != Match.FULL:
            continue
        if isinstance(route, Mount):
            nested = first_full(route.routes, {**scope, **child}, order)
            nested["examined"] += examined
            nested["partials"] = partials + nested["partials"]
            nested["mounts"].insert(0, {"order": order, "path": route.path,
                                         "regex": route.path_regex.pattern,
                                         "childRootPath": child["root_path"]})
            return nested
        return {"route": route, "order": order, "examined": examined,
                "partials": partials, "mounts": [], "pathParams": child.get("path_params", {})}
    return {"route": None, "order": None, "examined": examined,
            "partials": partials, "mounts": [], "pathParams": {}}


def route_at(app, order):
    routes = app.routes
    for depth, index in enumerate(order):
        route = routes[index]
        if depth < len(order) - 1:
            routes = route.routes
    return route


def scope_at(app, order, scope):
    from starlette.routing import Match, Mount
    routes = app.routes
    for index in order[:-1]:
        mount = routes[index]
        assert isinstance(mount, Mount)
        match, child = mount.matches(scope)
        assert match == Match.FULL
        scope = {**scope, **child}
        routes = mount.routes
    return scope


@lru_cache(maxsize=32)
def parsed_source(file):
    content = file.read_bytes()
    text = content.decode("utf-8")
    return content, text.splitlines(), ast.parse(text)


def source_evidence(endpoint, path_names):
    file = Path(inspect.getsourcefile(endpoint)).resolve()
    relative = file.relative_to(exporter.SERVER).as_posix()
    content, lines, tree = parsed_source(file)
    nodes = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == endpoint.__name__
             and min([n.lineno, *[d.lineno for d in n.decorator_list]]) <= endpoint.__code__.co_firstlineno <= n.lineno]
    if len(nodes) != 1:
        raise ValueError("source_definition_not_unique")
    node = nodes[0]
    arguments = {a.arg: ast.unparse(a.annotation) if a.annotation else None
                 for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs] if a.arg in path_names}
    returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
    use_lines = sorted({n.lineno for n in ast.walk(node)
                        if isinstance(n, ast.Name) and n.id in path_names and n.lineno > node.lineno})
    snippets = [{"line": n.lineno, "text": lines[n.lineno - 1].strip()[:240]} for n in returns[:2]]
    uses = [{"line": n, "text": lines[n - 1].strip()[:240]} for n in use_lines[:3]]
    start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
    segment = "\n".join(lines[start - 1:node.end_lineno])
    return {"file": "clearledger/server/" + relative, "line": node.lineno, "endLine": node.end_lineno,
            "fileSha256": hashlib.sha256(content).hexdigest(),
            "definitionSha256": hashlib.sha256(segment.encode()).hexdigest(),
            "decorators": [ast.unparse(d) for d in node.decorator_list],
            "docFirstParagraph": (ast.get_docstring(node) or "").split("\n\n")[0][:420],
            "pathAnnotations": arguments, "pathUses": uses, "returns": snippets}


def route_record(row, route):
    return {key: row[key] for key in ("method", "protocol", "path", "declaredPath", "mountPath", "mountChain",
                                     "order", "endpoint", "routeClass")} | {
        "compiledRegex": route.path_regex.pattern,
        "convertors": {name: {"class": exporter.qualified(type(c)), "regex": c.regex}
                       for name, c in route.param_convertors.items()},
        "registeredMethods": sorted(route.methods) if getattr(route, "methods", None) else [],
    }


def triage(app, registry):
    from starlette.routing import Match
    endpoints, pairs = {}, []
    rows = registry["operations"]
    seen = set()
    for number, candidate in enumerate(registry["literalParameterOverlaps"], 1):
        ids = tuple(candidate["operations"])
        assert len(ids) == 2 and ids not in seen
        seen.add(ids)
        a, b = (rows[i] for i in ids)
        parameter, literal = (a, b) if "{" in a["path"] else (b, a)
        assert "{" in parameter["path"] and "{" not in literal["path"]
        pr, lr = route_at(app, parameter["order"]), route_at(app, literal["order"])
        for row, route in ((parameter, pr), (literal, lr)):
            assert exporter.qualified(route.endpoint) == row["endpoint"]
            if row["endpoint"] not in endpoints:
                endpoints[row["endpoint"]] = source_evidence(route.endpoint, set(route.param_convertors))
        scope = synthetic_scope(literal["path"], literal["method"], literal["protocol"])
        lm, _ = lr.matches(scope_at(app, literal["order"], scope))
        pm, pc = pr.matches(scope_at(app, parameter["order"], scope))
        first = first_full(app.routes, scope)
        compatible = literal["protocol"] == parameter["protocol"] and literal["method"] == parameter["method"]
        if not compatible:
            verdict = "incompatible_method_or_protocol"
        elif lm != Match.FULL or pm != Match.FULL or first["route"] is None:
            verdict = "unknown_match_proof_insufficient"
        elif first["order"] == literal["order"]:
            verdict = "literal_precedes_parameter"
        elif first["order"] == parameter["order"]:
            verdict = "parameter_before_literal_shadow"
        else:
            verdict = "other_earlier_route_shadows_literal"
        pairs.append({"id": f"O{number:03}", "artifactOperationIndices": list(ids), "verdict": verdict,
                      "literal": route_record(literal, lr), "parameter": route_record(parameter, pr),
                      "witness": {"path": scope["path"], "method": scope["method"], "protocol": scope["type"],
                                  "rootPath": "", "literalMatch": lm.name, "parameterMatch": pm.name,
                                  "parameterPathParams": pc.get("path_params", {})},
                      "firstFull": {"order": first["order"],
                                    "endpoint": exporter.qualified(first["route"].endpoint) if first["route"] else None,
                                    "examinedRouteNodes": first["examined"], "earlierPartialOrders": first["partials"],
                                    "mounts": first["mounts"]}})
    return {"pairs": pairs, "sourceEndpoints": endpoints, "counts": dict(sorted(Counter(p["verdict"] for p in pairs).items()))}


def child_export(revision):
    # Same pre-import controls as exporter.child_export; reuse its guard and
    # failure serializer, without adding permissions or clearing denial history.
    os.environ.clear()
    os.environ.update(exporter.synthetic_environment(revision))
    guard = exporter.OfflineGuard()
    sys.path[:] = [str(exporter.SERVER), *[str(Path(p).resolve()) for p in sys.path if p and Path(p).is_dir()
                  and any(Path(p).resolve().is_relative_to(root) for root in guard.library_roots)]]
    guard.install()
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            if not sys.flags.isolated:
                raise exporter.OfflineViolation("isolated_python_required")
            from app import database
            from sqlalchemy import event
            event.listen(database.engine.sync_engine, "do_connect", guard.sql_connect)
            if (database.settings.database_url != exporter.synthetic_environment(revision)["DATABASE_URL"]
                    or database.engine.url.host != "127.0.0.1" or database.engine.url.port != 1
                    or database.settings.app_env != "dev"
                    or any(getattr(database.settings, name) is not expected for name, expected in exporter.FLAGS.items())):
                raise RuntimeError("synthetic_configuration_required")
            from app.main import app, product_api
            from app.api_contracts.routing import PolicyRoute
            if Path(database.__file__).resolve() != exporter.SERVER / "app/database.py" or database.Base.__module__ != "app.database":
                raise RuntimeError("actual_database_module_required")
            report = exporter.inventory(app, revision=revision, policy_type=PolicyRoute,
                                        product_app=product_api, resources=guard.resources)
            assert report["statistics"]["curatedOperations"] == 12
            report["triage"] = triage(app, report)
            import fastapi
            import starlette
            report["triage"]["versions"] = {"python": sys.version.split()[0], "fastapi": fastapi.__version__, "starlette": starlette.__version__}
            report["kind"] = "actual-core-runtime-route-inventory"
            report["provenance"].update({"entrypoint": "app.main.app", "ambientEnvironment": "replaced", "appEnv": "dev", "pythonIsolated": True,
                "realDatabaseBase": True, "compositionFlags": exporter.FLAGS,
                "guard": {"deniedAttempts": len(guard.denied), "sql": "real_engine_do_connect_denied",
                          "network": "socket_audit_denied", "writes": "audit_denied", "processes": "audit_denied"}})
            if guard.denied:
                raise exporter.OfflineViolation("recovered_denial")
    except Exception as error:
        report = exporter.safe_failure(error, guard)
        report["sourceRevision"] = revision
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 2 if report.get("status") == "blocked" else 0


def triage_runner(argv, **kwargs):
    # Reuse launch_export's temporary cwd, -I/-B, exact synthetic environment,
    # timeout, captured pipes and sanitized nonzero envelope. Only entrypoint changes.
    assert Path(argv[3]) == Path(exporter.__file__).resolve()
    return subprocess.run([*argv[:3], str(HERE), *argv[4:]], **kwargs)


def bounded_report(args):
    original_bytes = args.artifact.read_bytes()
    assert hashlib.sha256(original_bytes).hexdigest() == args.artifact_sha256, "artifact_hash_mismatch"
    original = json.loads(original_bytes)
    assert original["sourceRevision"] == args.artifact_revision, "artifact_revision_mismatch"
    assert original["kind"] == "actual-core-runtime-route-inventory"
    assert len(original["operations"]) == 1703 and len(original["literalParameterOverlaps"]) == 109
    assert original["provenance"]["guard"]["deniedAttempts"] == 0
    assert original["provenance"]["realDatabaseBase"] and not original["provenance"]["lifespanExecuted"]
    assert not original["provenance"]["requestsExecuted"]
    subprocess.run(["git", "diff", "--exit-code", args.source_revision, "--", "clearledger/server/app",
                    "clearledger/scripts/export-runtime-inventory.py"], cwd=ROOT, check=True, capture_output=True)
    current = exporter.launch_export(args.source_revision, runner=triage_runner)
    if current.get("status") == "blocked":
        return current
    sections = ("operations", "mounts", "unresolved", "literalParameterOverlaps", "duplicates", "parameterCollisions", "sharedPaths")
    parity = {key: {"identical": current[key] == original[key], "sha256": digest(current[key])} for key in sections}
    assert all(p["identical"] for p in parity.values()), "registry_or_registration_order_changed"
    assert not current["unresolved"]
    result = {"schemaVersion": 1, "kind": "bounded-route-overlap-triage", "sourceRevision": args.source_revision,
              "artifact": {"sourceRevision": original["sourceRevision"], "sha256": args.artifact_sha256,
                           "operationCount": 1703, "candidateCount": 109},
              "registrationParity": parity, "provenance": current["provenance"],
              "rawInventoryPublished": False, **current["triage"]}
    assert len(result["pairs"]) == 109 == sum(result["counts"].values())
    assert len({tuple(p["artifactOperationIndices"]) for p in result["pairs"]}) == 109
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--artifact-sha256")
    parser.add_argument("--artifact-revision")
    args = parser.parse_args()
    if not exporter.re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("explicit full source revision required")
    if args.child:
        return child_export(args.source_revision)
    if not args.artifact or not args.artifact_sha256 or not args.artifact_revision:
        parser.error("artifact path, sha256 and full artifact revision required")
    try:
        report = bounded_report(args)
    except Exception as error:
        report = {"status": "blocked", "kind": "bounded-triage-input-or-parity-failed",
                  "errorType": exporter.qualified(type(error)), "exceptionText": "omitted"}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
