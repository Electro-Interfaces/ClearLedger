#!/usr/bin/env python3
"""Offline actual Core route inventory; no lifespan, requests, SQL or credentials."""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import redirect_stderr, redirect_stdout
import functools
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import sysconfig
import tempfile
import traceback


SERVER = Path(__file__).resolve().parents[1] / "server"
FLAGS = {"partner_oauth_enabled": False, "partner_api_enabled": False, "partner_docs_enabled": False}
TIMEZONE = Path("/usr/share/zoneinfo/Europe/Moscow")
MIME_TYPES = Path("/etc/mime.types")


class OfflineViolation(RuntimeError):
    pass


class OfflineGuard:
    """Process-local guard; denied attempts invalidate even a recovered import."""
    def __init__(self, source=SERVER):
        self.source = Path(source).resolve()
        self.library_roots = [Path(sysconfig.get_path(key)).resolve() for key in ("stdlib", "platstdlib", "purelib", "platlib")]
        self.denied = []
        self.denial_traces = []
        self.resources = []
        for path, kind, name in ((TIMEZONE, "public_timezone_data", "Europe/Moscow"), (MIME_TYPES, "public_mime_types", "mime.types")):
            if path.resolve() != path:
                raise OfflineViolation("public_resource_realpath_mismatch")
            content = path.read_bytes()
            valid = content.startswith(b"TZif") if path == TIMEZONE else bool(re.search(rb"(?m)^[\w.+-]+/[\w.+-]+\s", content))
            if not valid:
                raise OfflineViolation("public_resource_format_mismatch")
            self.resources.append({"kind": kind, "resource": name, "readOnly": True,
                                   "sha256": hashlib.sha256(content).hexdigest()})

    def deny(self, category):
        self.denied.append(category)
        if len(self.denial_traces) < 12:
            self.denial_traces.append({"category": category, "frames": frame_metadata(traceback.walk_stack(sys._getframe(1)))[:18]})
        raise OfflineViolation(category)

    def audit(self, event, args):
        if event.startswith("sqlite3."):
            self.deny("sql_connect")
        if event.startswith("socket."):
            self.deny("network")
        if event.startswith("os.exec") or event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.fork", "pty.spawn"}:
            self.deny("process")
        if event in {"os.mkdir", "os.remove", "os.rename", "os.rmdir", "os.link", "os.symlink", "os.truncate"}:
            self.deny("filesystem_write")
        if event != "open":
            return
        filename, mode, flags = args
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            self.deny("filesystem_write")
        if isinstance(filename, int):
            self.deny("file_descriptor_read")
        path = Path(os.fsdecode(filename)).resolve()
        name = path.name.lower()
        if (name == ".env" or name.startswith(".env.") or name.startswith(("credentials", "id_rsa", "id_ed25519"))
                or path.suffix.lower() in {".key", ".pem", ".p12", ".pfx", ".sqlite", ".db"}
                or any(p.lower() in {".ssh", ".aws", ".vault", ".claude", ".codex", "secrets"} for p in path.parts)):
            self.deny("secret_file")
        if path == Path(__file__).resolve() or (path.is_relative_to(self.source) and path.suffix in {".py", ".pyc", ".so"}):
            return
        if path in {TIMEZONE, MIME_TYPES}:
            return
        if any(path.is_relative_to(root) for root in self.library_roots):
            return
        self.deny("unapproved_file")

    def install(self):
        sys.dont_write_bytecode = True
        sys.addaudithook(self.audit)

    def sql_connect(self, *args, **kwargs):
        self.deny("sql_connect")


def qualified(value):
    if isinstance(value, functools.partial):
        return qualified(value.func)
    if value is None:
        return None
    module = getattr(value, "__module__", None)
    name = getattr(value, "__qualname__", None)
    if not isinstance(module, str) or not isinstance(name, str):
        module, name = type(value).__module__, type(value).__qualname__ + ".__call__"
    # No repr/defaults/closure state or absolute filenames.
    return module + "." + name


def dependencies(route):
    names, seen = set(), set()
    def walk(node):
        if id(node) in seen:
            return
        seen.add(id(node))
        for child in getattr(node, "dependencies", ()):
            if name := qualified(getattr(child, "call", None)):
                names.add(name)
            walk(child)
    if node := getattr(route, "dependant", None):
        walk(node)
    return sorted(names)


def join_path(prefix, path):
    return prefix.rstrip("/") + path if path else prefix or "/"


def inventory(app, *, revision, policy_type=None, product_app=None, resources=()):
    from fastapi.routing import APIRoute
    from starlette.routing import Mount, Route, WebSocketRoute
    rows, mounts, unresolved = [], [], []
    def walk(routes, prefix, chain, ancestors, mount_chain):
        for index, route in enumerate(routes):
            order = [*chain, index]
            route_class = qualified(type(route))
            path = getattr(route, "path", None)
            if not isinstance(path, str):
                unresolved.append({"order": order, "kind": "unknown_route", "routeClass": route_class})
                continue
            full = join_path(prefix, path)
            if isinstance(route, Mount):
                children = route.routes
                record = {"path": full, "order": order, "routeClass": route_class,
                          "applicationClass": qualified(type(route.app))}
                mounts.append(record)
                if id(route.app) in ancestors:
                    unresolved.append({**record, "kind": "mount_cycle"})
                elif not children:
                    unresolved.append({**record, "kind": "opaque_or_empty_mount"})
                else:
                    walk(children, full, order, ancestors | {id(route.app)}, [*mount_chain, full])
                continue
            if not isinstance(route, (APIRoute, Route, WebSocketRoute)):
                unresolved.append({"path": full, "order": order, "kind": "unknown_route", "routeClass": route_class})
                continue
            policy = None
            if policy_type is not None and isinstance(route, policy_type):
                policy = route.binding.policy.metadata()
            curated = product_app is not None and any(route is candidate for candidate in product_app.routes) and policy is not None
            methods = ["WEBSOCKET"] if isinstance(route, WebSocketRoute) else sorted(route.methods or ["*"])
            pattern = getattr(getattr(route, "path_regex", None), "pattern", path)
            full_pattern = "^" + re.escape(prefix) + pattern.removeprefix("^")
            shape = re.sub(r"\(\?P<[^>]+>", "(?:", full_pattern)
            for method in methods:
                rows.append({"method": method, "protocol": "websocket" if method == "WEBSOCKET" else "http",
                    "path": full, "declaredPath": path, "mountPath": prefix or "/", "mountChain": mount_chain, "order": order,
                    "endpoint": qualified(route.endpoint), "routeClass": route_class,
                    "name": route.name, "responseClass": qualified(route.response_class) if isinstance(getattr(route, "response_class", None), type) else None,
                    "dependencies": dependencies(route), "policy": policy,
                    "category": "curated_policy" if curated else "declared_policy" if policy else "legacy_public_internal_unclassified",
                    "ownership": {"sourceModule": getattr(route.endpoint, "__module__", type(route.endpoint).__module__), "businessOwner": policy["owner"] if policy else None},
                    "authAssessment": "declared_policy_not_request_validated" if policy else "not_proven_by_dependency_names",
                    "manualReview": not curated, "pathShape": shape, "matchPattern": full_pattern})
    walk(app.routes, "", [], {id(app)}, [])
    groups, shapes, paths = defaultdict(list), defaultdict(list), defaultdict(list)
    for index, row in enumerate(rows):
        groups[(row["protocol"], row["method"], row["path"])].append(index)
        shapes[(row["protocol"], row["method"], row["pathShape"])].append(index)
        paths[row["path"]].append(index)
    duplicates = [{"protocol": key[0], "method": key[1], "path": key[2], "operations": ids}
                  for key, ids in sorted(groups.items()) if len(ids) > 1]
    collisions = [{"kind": "parameter_shape", "operations": ids}
                  for ids in shapes.values() if len({rows[i]["path"] for i in ids}) > 1]
    mixed = [{"path": path, "operations": ids, "kind": "shared_path_different_methods_or_protocols"}
             for path, ids in sorted(paths.items()) if len({(rows[i]["protocol"], rows[i]["method"]) for i in ids}) > 1]
    overlaps = []
    for i, parameter in enumerate(rows):
        if "{" not in parameter["path"]:
            continue
        pattern = re.compile(parameter["matchPattern"])
        for j, literal in enumerate(rows):
            if ("{" not in literal["path"] and parameter["method"] == literal["method"]
                    and parameter["protocol"] == literal["protocol"] and pattern.fullmatch(literal["path"])):
                overlaps.append({"kind": "literal_parameter_overlap_candidate", "operations": sorted([i, j])})
    return {"schemaVersion": 1, "kind": "provided-asgi-route-tree", "sourceRevision": revision,
        "provenance": {"entrypoint": "provided-app", "lifespanExecuted": False, "requestsExecuted": False,
                       "openapiGenerated": False, "readOnlyResources": list(resources)},
        "operations": rows, "mounts": mounts, "unresolved": unresolved, "duplicates": duplicates,
        "parameterCollisions": collisions, "sharedPaths": mixed, "literalParameterOverlaps": overlaps,
        "statistics": {"operations": len(rows), "curatedOperations": sum(r["category"] == "curated_policy" for r in rows),
                       "websocketOperations": sum(r["protocol"] == "websocket" for r in rows),
                       "mounts": len(mounts), "unresolved": len(unresolved), "duplicateGroups": len(duplicates)},
        "limits": ["Service-local paths; gateway/root_path and other compositions unverified",
                   "Dependency names do not prove ACL or public access", "Business ownership requires review",
                   "No endpoint, policy guard, startup or lifespan executed",
                   "Middleware OPTIONS, redirects, static/proxy dispatch and dynamically returned SSE are not enumerated",
                   "Regex/parameter collisions are candidates, not exhaustive dispatch or shadowing proof"]}


def compare_static(report, static):
    sources = static.get("sources", [static])
    core = [s for s in sources if s.get("name") == "Core"]
    if len(core) != 1:
        raise ValueError("exactly_one_Core_source_required")
    declarations = core[0].get("endpoints", [])
    known = {(r.get("method"), r.get("path")) for r in declarations if isinstance(r.get("path"), str) and isinstance(r.get("method"), str)}
    actual = {(r["method"], r["path"]) for r in report["operations"]}
    return {"scope": "method_path_sets_only_not_registration_or_authorization_parity",
            "staticSourceRevision": core[0].get("git", {}).get("head"),
            "sourceRevisionMatches": core[0].get("git", {}).get("head") == report["sourceRevision"],
            "staticOnly": [{"method": m, "path": p} for m, p in sorted(known - actual)],
            "runtimeOnly": [{"method": m, "path": p} for m, p in sorted(actual - known)],
            "commonPairs": len(known & actual), "staticUnresolvedCount": len(core[0].get("unresolved", []))}


def markdown(report):
    if report.get("status") == "blocked":
        return "# Runtime API inventory: BLOCKED\n\n" + json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    lines = ["# Offline runtime API inventory", "", "Source revision: " + report["sourceRevision"], "",
             "No lifespan, requests, SQL or network; dependencies are not ACL evidence.", "",
             "Statistics: " + json.dumps(report["statistics"], sort_keys=True), "",
             "| Method | Service-local path | Endpoint | Category |", "|---|---|---|---|"]
    for row in report["operations"]:
        lines.append("| " + " | ".join(str(row[k]).replace("|", "\\|").replace("\n", " ") for k in ("method", "path", "endpoint", "category")) + " |")
    for name in ("duplicates", "parameterCollisions", "literalParameterOverlaps", "unresolved", "staticComparison"):
        if report.get(name):
            lines += ["", "## " + name, "", "```json", json.dumps(report[name], ensure_ascii=False, sort_keys=True, indent=2), "```"]
    return "\n".join(lines) + "\n"


def frame_metadata(items):
    frames = []
    for frame, line in items:
        path = Path(frame.f_code.co_filename)
        relative = path.relative_to(SERVER).as_posix() if path.is_relative_to(SERVER) else "<exporter>" if path == Path(__file__) else "<dependency>"
        module = frame.f_globals.get("__name__", "")
        frames.append({"file": relative, "line": line, "function": frame.f_code.co_name,
                       "module": module if isinstance(module, str) and re.fullmatch(r"[\w.]+", module) else "unknown"})
    return frames


def safe_failure(error, guard):
    return {"status": "blocked", "kind": "actual-core-import-failed", "errorType": qualified(type(error)),
            "frames": frame_metadata(traceback.walk_tb(error.__traceback__)), "deniedCategories": sorted(set(guard.denied)),
            "guardDenials": guard.denial_traces,
            "lifespanExecuted": False, "exceptionText": "omitted"}


def child_export(revision):
    os.environ.clear()
    os.environ.update(synthetic_environment(revision))
    guard = OfflineGuard()
    # importlib.metadata probes nonexistent interpreter ZIP entries as files.
    # Keep existing trusted interpreter directories; add the real server explicitly.
    sys.path[:] = [str(SERVER), *[str(Path(p).resolve()) for p in sys.path if p and Path(p).is_dir()
                  and any(Path(p).resolve().is_relative_to(root) for root in guard.library_roots)]]
    guard.install()
    capture = io.StringIO()
    try:
        with redirect_stdout(capture), redirect_stderr(capture):
            if not sys.flags.isolated:
                raise OfflineViolation("isolated_python_required")
            from app import database
            from sqlalchemy import event
            event.listen(database.engine.sync_engine, "do_connect", guard.sql_connect)
            if (database.settings.database_url != synthetic_environment(revision)["DATABASE_URL"]
                    or database.engine.url.host != "127.0.0.1" or database.engine.url.port != 1
                    or database.settings.app_env != "dev"
                    or any(getattr(database.settings, name) is not expected for name, expected in FLAGS.items())):
                raise RuntimeError("synthetic_configuration_required")
            from app.main import app, product_api
            from app.api_contracts.routing import PolicyRoute
            if Path(database.__file__).resolve() != SERVER / "app/database.py" or database.Base.__module__ != "app.database":
                raise RuntimeError("actual_database_module_required")
            result = inventory(app, revision=revision, policy_type=PolicyRoute, product_app=product_api, resources=guard.resources)
            result["kind"] = "actual-core-runtime-route-inventory"
            result["provenance"].update({"entrypoint": "app.main.app", "compositionFlags": FLAGS,
                "ambientEnvironment": "replaced", "pythonIsolated": True, "appEnv": "dev",
                "importPath": "server_and_existing_interpreter_directories", "realDatabaseBase": True,
                "guard": {"deniedAttempts": len(guard.denied), "sql": "real_engine_do_connect_denied",
                          "network": "socket_audit_denied", "writes": "audit_denied", "processes": "audit_denied"}})
            if guard.denied:
                raise OfflineViolation("recovered_denial")
            if result["statistics"]["curatedOperations"] != 12:
                raise RuntimeError("unexpected_curated_operation_count")
    except Exception as error:
        result = safe_failure(error, guard)
        result["sourceRevision"] = revision
        result["compositionFlags"] = FLAGS
        result["ambientEnvironment"] = "replaced"
        result["appEnv"] = "dev"
        result["readOnlyResources"] = guard.resources
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 2 if result.get("status") == "blocked" else 0


def synthetic_environment(revision):
    return {"LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "APP_ENV": "dev",
            "DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/runtime_inventory_test",
            "SECRET_KEY": "synthetic-offline-route-inventory-only", "SOURCE_REVISION": revision,
            "PARTNER_API_ENABLED": "false", "PARTNER_OAUTH_ENABLED": "false", "PARTNER_DOCS_ENABLED": "false",
            "UPLOAD_DIR": "/offline-runtime-inventory-unused"}


def sanitized_child_failure(payload, revision):
    def frames(values):
        clean = []
        for value in values[:40] if isinstance(values, list) else []:
            if not isinstance(value, dict):
                continue
            file = value.get("file", "")
            if not (file in {"<exporter>", "<dependency>"} or
                    isinstance(file, str) and re.fullmatch(r"app/[\w/.-]+\.py", file) and ".." not in file):
                file = "<dependency>"
            record = {"file": file}
            for key in ("module", "function"):
                token = value.get(key, "")
                record[key] = token if isinstance(token, str) and re.fullmatch(r"[\w.<>]+", token) else "unknown"
            line = value.get("line")
            record["line"] = line if type(line) is int and line >= 0 else 0
            clean.append(record)
        return clean
    categories = {"network", "process", "filesystem_write", "file_descriptor_read", "secret_file", "unapproved_file", "sql_connect"}
    error_type = payload.get("errorType", "")
    return {"status": "blocked", "kind": "actual-core-import-failed", "sourceRevision": revision,
            "appEnv": "dev", "compositionFlags": FLAGS, "ambientEnvironment": "replaced",
            "lifespanExecuted": False, "exceptionText": "omitted",
            "errorType": error_type if isinstance(error_type, str) and re.fullmatch(r"[\w.]+", error_type) else "unknown",
            "frames": frames(payload.get("frames")),
            "deniedCategories": sorted(categories.intersection(payload.get("deniedCategories", []))),
            "guardDenials": [{"category": item["category"], "frames": frames(item.get("frames"))}
                for item in payload.get("guardDenials", [])[:12] if isinstance(item, dict) and item.get("category") in categories]}


def launch_export(revision, *, runner=None):
    runner = subprocess.run if runner is None else runner
    def blocked(reason, exit_code=None):
        report = {"status": "blocked", "kind": reason, "sourceRevision": revision,
                  "appEnv": "dev", "compositionFlags": FLAGS}
        if exit_code is not None:
            report["exitCode"] = exit_code
        return report
    try:
        with tempfile.TemporaryDirectory(prefix="runtime-inventory-") as cwd:
            result = runner([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--child", "--source-revision", revision],
                            cwd=cwd, env=synthetic_environment(revision), capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return blocked("hermetic_child_timeout")
    except OSError:
        return blocked("hermetic_child_start_failed")
    try:
        report = json.loads(result.stdout)
    except (ValueError, TypeError):
        return blocked("hermetic_child_invalid_json", result.returncode)
    if not isinstance(report, dict):
        return blocked("hermetic_child_invalid_report", result.returncode)
    if result.returncode != 0:
        # Only our child's explicitly sanitized import failure is retained.
        if report.get("status") == "blocked" and report.get("kind") == "actual-core-import-failed":
            try:
                return sanitized_child_failure(report, revision)
            except (TypeError, ValueError, KeyError):
                return blocked("hermetic_child_invalid_report", result.returncode)
        return blocked("hermetic_child_nonzero", result.returncode)
    if (report.get("kind") != "actual-core-runtime-route-inventory"
            or report.get("sourceRevision") != revision or not isinstance(report.get("operations"), list)):
        return blocked("hermetic_child_invalid_report", result.returncode)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--static-json", type=Path)
    parser.add_argument("--markdown", type=Path, help="Local report only; no HTTP publication")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("source-revision must be an explicit immutable SHA")
    if args.child:
        return child_export(args.source_revision)
    report = launch_export(args.source_revision)
    try:
        if args.static_json and report.get("status") != "blocked":
            report["staticComparison"] = compare_static(report, json.loads(args.static_json.read_text()))
        if args.markdown:
            args.markdown.write_text(markdown(report), encoding="utf-8")
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        report = {"status": "blocked", "kind": "inventory_input_or_output_failed", "sourceRevision": args.source_revision}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
