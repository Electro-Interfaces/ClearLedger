"""ROOT-only frozen old/new pure OpenAPI matrix; never execute as a worker."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import signal
import subprocess
import sys

SERVER = Path(__file__).resolve().parents[1]
WORKTREE = Path("/home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030")
BASE = "0eb3319dffc30da8df40cdb83d0c280bb41be211"
BRANCH = "agent/api-objectid-schema-compatibility-20261030"
FROZEN = {'app': {'count': 492, 'sha256': '2c65aa4a192cd8f7b8f22985de86eefcc86977ab2550bded5af7ede97dbf2329'}, 'tests': {'count': 347, 'sha256': '3509851123facc067ce4d6bedb33886843a866cb5ed89737ce3621cf1612b41e'}, 'schema_migrations': {'count': 16, 'sha256': '51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d'}}
SUPPORT = {'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601'}
INVENTORIES = {'old': {'prefix': '/srv/projects/api-modernization-test-env-20261029/.venv', 'count': 79, 'sha256': '2850615e939b64d93a5c3bf1d2b2f148795f9e11eb528d7d2de3227c42fb7262'}, 'new': {'prefix': '/srv/projects/api-modernization-upgrade-test-env-20261030/.venv', 'count': 77, 'sha256': '1716af920666a4b5e19d2fb74ec0061b2e354220825b623bd54a71b33bb5a58b'}}
FLAG = "RUN_PRODUCT_OBJECTID_SCHEMA_COMPATIBILITY"
APPROVAL = "ROOT_APPROVED_PRODUCT_OBJECTID_SCHEMA_COMPATIBILITY"
UNUSED_URL = "postgresql+asyncpg://synthetic:unused@127.0.0.1:1/objectid_schema_test_unused"
SECRET = "objectid-schema-synthetic-secret-unused-20261030"
SELECTION = ["tests/test_product_object_ids.py::test_pure_schema_distinguishes_object_identity_from_other_ids",
             "tests/test_product_objectid_schema_compatibility.py"]
TEST_NAMES = {
    "test_pure_schema_distinguishes_object_identity_from_other_ids",
    "test_equivalent_inline_changes_only_two_schema_nodes",
    "test_existing_references_are_unchanged_and_idempotent",
    "test_inline_without_display_title_and_component_annotations",
    "test_constraint_drift_is_rejected_atomically",
    "test_wrong_reference_and_reference_siblings_are_rejected",
    "test_wrong_parameter_identity_or_required_flag_is_rejected",
    "test_missing_component_or_route_is_rejected",
    "test_unreviewed_path_method_or_operation_is_rejected",
    "test_unrelated_schema_branches_and_query_parameters_are_preserved",
    "test_authoritative_component_future_keyword_must_match",
    "test_real_canonical_contract_and_codegen_identity_controls",
    "test_real_public_projection_preserves_refs_and_canonical_security",
    "test_curated_export_rejects_generator_constraint_drift",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_tree(name):
    root = SERVER / name
    entries = list(root.rglob("*"))
    require(not root.is_symlink() and len(entries) < 8000
            and not any(p.is_symlink() for p in entries), "source symlink/count")
    files = sorted(p for p in entries if p.is_file() and "__pycache__" not in p.parts
                   and p != Path(__file__).resolve())
    require(all(p.stat().st_size < 8 * 1024 * 1024 for p in files)
            and sum(p.stat().st_size for p in files) < 64 * 1024 * 1024, "source byte bounds")
    rows = [[str(p.relative_to(SERVER)), digest(p)] for p in files]
    return {"count": len(rows), "sha256": hashlib.sha256(
        json.dumps(rows, separators=(",", ":")).encode()).hexdigest()}


def installed_inventory(prefix):
    site = prefix / "lib/python3.13/site-packages"
    files = sorted(site.glob("*.dist-info/METADATA"))
    require(files and not site.is_symlink() and not any(p.is_symlink() for p in files), "metadata/site symlink")
    rows = [[str(p.relative_to(site)), digest(p)] for p in files]
    return {"distributions": rows, "routing": {
        name: digest(site / name / "routing.py") for name in ("fastapi", "starlette")},
        "pyvenv_cfg": digest(prefix / "pyvenv.cfg")}


def private_empty(key):
    path = Path(os.environ.get(key, ""))
    require(path.is_absolute() and ".." not in path.parts and path.is_dir(), "absolute private directory")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "directory symlink")
    require(path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o777 == 0o700
            and "objectid-test" in path.name and not any(path.iterdir()), "fresh owned empty 0700 directory")
    return path


def verify():
    require(not any(k == "pytest" or k == "app" or k.startswith("app.") for k in sys.modules),
            "no app/pytest imports before approval")
    require(sys.argv[1:] == ["--execute-approved-objectid-schema-compatibility"], "exact execution opt-in")
    require(sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
            and not sys.flags.optimize and sys.version_info[:3] == (3, 13, 7), "Python3.13.7 -I -S -B required")
    require(not any("site-packages" in p for p in sys.path), "no site before boundary")
    flags = {FLAG, APPROVAL, "RUN_PRODUCT_OBJECT_ID_TESTS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE"}
    require(all(os.environ.get(k) == "1" for k in flags), "ROOT and test flags required")
    allowed = flags | {"HOME", "PATH", "LANG", "LC_ALL", "OBJECTID_RUNNER_SHA256", "OBJECTID_SOURCE_HEAD",
                       "OBJECTID_EMPTY_CWD", "OBJECTID_EVIDENCE_DIR", "OBJECTID_RUNTIME", "UPLOAD_DIR", "TEST_DATABASE_URL"}
    require(not set(os.environ) - allowed and os.environ.get("TEST_DATABASE_URL") == UNUSED_URL,
            "clean synthetic environment; only exact explicitly unused test URL")
    require(os.environ.get("HOME") == pwd.getpwuid(os.getuid()).pw_dir, "preserve actual HOME")
    require(digest(Path(__file__)) == os.environ.get("OBJECTID_RUNNER_SHA256"), "ROOT-reviewed self SHA")
    require(SERVER == WORKTREE / "clearledger/server", "exact source tree")
    directories = [private_empty(k) for k in ("OBJECTID_EMPTY_CWD", "UPLOAD_DIR", "OBJECTID_EVIDENCE_DIR")]
    require(Path.cwd() == directories[0] and len(set(directories)) == 3
            and not any(a != b and a.is_relative_to(b) for a in directories for b in directories)
            and not any(p.is_relative_to(SERVER) for p in directories), "separate nonnested empty directories outside source")
    require(FROZEN and {k: source_tree(k) for k in FROZEN} == FROZEN, "complete frozen app/tests/schema counts and hashes")
    require(SUPPORT and all(not (SERVER / k).is_symlink() and digest(SERVER / k) == v for k, v in SUPPORT.items()),
            "support source hashes")
    git_env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}

    def git(*args):
        return subprocess.check_output(["/usr/bin/git", "-C", str(WORKTREE), *args],
                                       env=git_env, text=True, timeout=5).strip()

    head = git("rev-parse", "HEAD")
    require(head == os.environ.get("OBJECTID_SOURCE_HEAD") and len(head) == 40, "ROOT-approved exact source head")
    require(git("branch", "--show-current") == BRANCH and git("merge-base", BASE, head) == BASE, "dedicated branch/base")
    require(not git("status", "--porcelain", "--untracked-files=normal"), "clean frozen tree")
    runtime = os.environ.get("OBJECTID_RUNTIME")
    require(runtime in INVENTORIES, "old/new selection")
    approved = INVENTORIES[runtime]
    prefix = Path(approved["prefix"])
    require(sys.executable == str(prefix / "bin/python") and Path(sys.executable).resolve() == Path(
        "/home/mag/.local/share/uv/python/cpython-3.13.7-linux-x86_64-gnu/bin/python3.13"), "exact existing interpreter")
    # On Python3.13 -S deliberately leaves sys.prefix at the base interpreter.
    require(sys.prefix == sys.base_prefix, "site initialization must remain disabled")
    inventory = installed_inventory(prefix)
    inventory_sha = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    require(inventory_sha == approved["sha256"] and len(inventory["distributions"]) == approved["count"], "installed inventory")
    os.umask(0o077)
    return directories[2], prefix / "lib/python3.13/site-packages", {
        "head": head, "base": BASE, "runtime": runtime, "prefix": str(prefix), "inventory": inventory,
        "inventory_sha256": inventory_sha, "frozen": FROZEN, "runner_sha256": digest(Path(__file__)),
        "home_preserved": True, "no_site_before_gate": True, "empty_0700_directories": True}


def install_boundary(attempts, evidence):
    import importlib.abc

    class NoAssemblyOrDrivers(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if (fullname == "app.main" or fullname == "app.services" or fullname.startswith("app.services.")
                    or fullname.split(".")[0] in {"asyncpg", "psycopg", "psycopg2", "aiosqlite"}):
                attempts.append("import:" + fullname)
                raise ImportError("pure OpenAPI boundary forbids assembly/senders/database drivers")

    sys.meta_path.insert(0, NoAssemblyOrDrivers())

    def audit(event, args):
        denied = event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.getnameinfo",
            "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg", "socket.bind",
            "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.forkpty", "sqlite3.connect"}
        if event == "open" and isinstance(args[0], (str, bytes)):
            path = Path(os.fsdecode(args[0]))
            denied = denied or path.name == ".env" or path.name.startswith(".env.") or bool(
                {".ssh", ".vault", ".claude"}.intersection(path.parts))
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            denied = denied or bool(writing and not path.absolute().is_relative_to(evidence))
        if denied:
            attempts.append(event)
            raise OSError("pure OpenAPI boundary forbids all network/SQL/process/config input and outside writes")

    sys.addaudithook(audit)


def run(evidence, site, proof, attempts):
    sys.path.insert(0, str(site))  # Verified exact site only; never site.main()/addsitedir()/.pth execution.
    import socket
    import smtplib

    def denied(*args, **kwargs):
        attempts.append("engine_session_sender_or_network_operation")
        raise RuntimeError("pure schema matrix forbids engine/session/sender/network operations")

    async def async_denied(*args, **kwargs):
        denied(*args, **kwargs)

    for name in ("connect", "connect_ex", "bind", "sendto", "sendmsg", "sendall", "send"):
        setattr(socket.socket, name, denied)
    for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
        setattr(socket, name, denied)
    smtplib.SMTP.connect = smtplib.SMTP.sendmail = smtplib.SMTP.send_message = denied
    before = socket.has_ipv6
    try:
        socket.has_ipv6 = False
        import aiohttp
        import aiosmtplib
        import httpx
        import pywebpush
        import requests
    finally:
        socket.has_ipv6 = before
        proof["import_capability"] = {"scope": ["aiohttp", "aiosmtplib", "httpx", "pywebpush", "requests"],
                                     "restored": socket.has_ipv6 is before, "old_value": before, "bind_allowance": False}
    httpx.HTTPTransport.handle_request = denied
    httpx.AsyncHTTPTransport.handle_async_request = async_denied
    requests.sessions.Session.request = denied
    aiohttp.ClientSession._request = async_denied
    aiosmtplib.send = async_denied
    aiosmtplib.SMTP.connect = aiosmtplib.SMTP.sendmail = async_denied
    pywebpush.webpush = denied

    import sqlalchemy
    import sqlalchemy.ext.asyncio as sa_async
    import sqlalchemy.orm as orm
    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.pool import Pool

    class InertImportBinding:
        def __getattr__(self, name):
            return denied()

    bindings = []

    def import_binding(url, **kwargs):
        require(sys._getframe(1).f_globals.get("__name__") == "app.database" and not bindings
                and url == UNUSED_URL and kwargs == {"echo": False, "pool_size": 10, "max_overflow": 20,
                    "pool_pre_ping": True, "pool_recycle": 1800}, "only one inert app.database import binding")
        bindings.append("app.database module import: no engine constructed")
        return InertImportBinding()

    sqlalchemy.create_engine = sqlalchemy.engine.create_engine = denied
    sa_async.create_async_engine = sa_async.engine.create_async_engine = import_binding
    for cls, names in ((Engine, ("connect", "begin", "raw_connection")),
                       (Connection, ("execute", "exec_driver_sql", "scalar", "scalars", "begin")),
                       (Pool, ("connect",)), (orm.Session, ("__init__",)),
                       (orm.sessionmaker, ("__call__",)), (sa_async.AsyncSession, ("__init__",)),
                       (sa_async.async_sessionmaker, ("__call__",)),
                       (sa_async.AsyncEngine, ("connect", "begin", "raw_connection"))):
        for name in names:
            setattr(cls, name, denied)

    # app.config creates a module-level Settings instance on import. Force that
    # first real instance to use only known synthetic inputs and _env_file=None.
    from pydantic_settings import BaseSettings
    init = BaseSettings.__init__
    settings_calls = []

    def synthetic_init(self, *args, **kwargs):
        require(type(self).__module__ == "app.config" and type(self).__name__ == "Settings"
                and not settings_calls and not args and not kwargs, "only initial app.config Settings")
        settings_calls.append("Settings(_env_file=None), known synthetic values")
        return init(self, _env_file=None, app_env="test", database_url=UNUSED_URL, SECRET_KEY=SECRET)

    sys.path.insert(0, str(SERVER))
    BaseSettings.__init__ = synthetic_init
    try:
        import app.config as config
    finally:
        BaseSettings.__init__ = init
    settings = config.get_settings()
    require(settings.database_url == UNUSED_URL and settings.app_env == "test" and settings.secret_key == SECRET
            and not any((settings.partner_oauth_enabled, settings.partner_api_enabled, settings.partner_docs_enabled,
                         settings.partner_api_budget_enabled)), "exact synthetic disabled settings")
    import pytest

    class Boundary:
        def __init__(self):
            self.collected, self.results = [], []

        def pytest_collection_modifyitems(self, session, config, items):
            self.collected = [item.name for item in items]
            if (set(self.collected) != TEST_NAMES or len(items) != len(TEST_NAMES)
                    or any(str(item.path.relative_to(SERVER)) not in {s.split("::")[0] for s in SELECTION} for item in items)):
                raise pytest.UsageError("exact 14 pure OpenAPI tests required")

        def pytest_runtest_logreport(self, report):
            self.results.append({"nodeid": report.nodeid, "phase": report.when, "outcome": report.outcome})

        def pytest_sessionfinish(self, session, exitstatus):
            forbidden = [k for k in sys.modules if k == "app.main" or k == "app.services" or k.startswith("app.services.")]
            clean = (not attempts and not forbidden and len(bindings) == len(settings_calls) == 1
                     and len(self.results) == 3 * len(TEST_NAMES)
                     and all(r["outcome"] == "passed" for r in self.results)
                     and proof["import_capability"]["restored"])
            if not clean:
                session.exitstatus = 1
            (evidence / "boundary-proof.json").write_text(json.dumps({**proof,
                "ok": clean and int(exitstatus) == 0, "network_sql_engine_sender_attempts": attempts,
                "inert_import_bindings": bindings, "settings_initialization": settings_calls,
                "app_database_imported": "app.database" in sys.modules, "sqlalchemy_imported": "sqlalchemy" in sys.modules,
                "real_engines_created": 0, "connections_allowed": False, "forbidden_modules": forbidden,
                "collected": self.collected, "results": self.results}, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    code = pytest.main(["-c", str(SERVER / "pytest.ini"), "--noconftest", "-p", "pytest_asyncio.plugin",
        "-p", "no:cacheprovider", "-vv", "--tb=long", "--show-capture=no",
        "--junitxml=" + str(evidence / "junit.xml"), *[str(SERVER / s) for s in SELECTION]], plugins=[Boundary()])
    return int(code)


def main():
    try:
        evidence, site, proof = verify()
    except Exception as exc:
        print(json.dumps({"ok": False, "phase": "approval", "error": str(exc)}))
        return 2
    attempts = []
    install_boundary(attempts, evidence)
    signal.signal(signal.SIGALRM, lambda *_: require(False, "pure schema matrix exceeded 180 seconds"))
    signal.alarm(180)
    try:
        return run(evidence, site, proof, attempts)
    except Exception as exc:
        (evidence / "boundary-error.json").write_text(json.dumps({**proof, "ok": False,
            "phase": "pure_schema_boundary", "error_type": type(exc).__name__, "error": str(exc),
            "network_sql_engine_sender_attempts": attempts}, sort_keys=True, indent=2) + "\n")
        raise
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
