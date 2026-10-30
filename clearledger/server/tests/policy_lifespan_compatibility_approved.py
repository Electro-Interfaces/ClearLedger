"""ROOT-only, frozen, no-SQL lifespan matrix entry point. Never run during preparation."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import signal
import subprocess
import sys

SERVER = Path(__file__).resolve().parents[1]
WORKTREE = Path("/home/mag/orca/workspaces/ledger-app/api-conf-context-20261030")
BASE = "850004b35e261b8d9115cc44c414a88d79c3e98e"
BRANCH = "agent/api-lifespan-compatibility-20261030"
FROZEN = {'app': {'count': 492, 'sha256': '120b78d9052a7a4dc182095638802cd0627443233e50e67f3fd3011a37a98862'}, 'tests': {'count': 344, 'sha256': '1d0852d8ad15522a59b54e16f5c7fafcdd4e5e0f52592cae7c55e5664d027f7d'}, 'schema_migrations': {'count': 16, 'sha256': '51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d'}}
INVENTORIES = {'old': {'prefix': '/srv/projects/api-modernization-test-env-20261029/.venv', 'sha256': 'e77307d05df3dd628e45dc8062b16a7f309f241eacb9e9a810e2d6a6c9f3e65f'}, 'new': {'prefix': '/srv/projects/api-modernization-upgrade-test-env-20261030/.venv', 'sha256': '9349a25d76e9b5df09325d74901254f10ed543d6fe8607039759b401281c3a83'}}
SUPPORT = {'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601'}
FLAG = "RUN_POLICY_LIFESPAN_COMPATIBILITY"
APPROVAL = "ROOT_APPROVED_POLICY_LIFESPAN_COMPATIBILITY"
TEST_NAMES = {
    "test_registry_precedes_root_sync_async_hooks_once_each_lifespan",
    "test_include_default_hooks_run_once_and_mount_does_not_start_child[False]",
    "test_include_default_hooks_run_once_and_mount_does_not_start_child[True]",
    "test_nested_custom_lifespans_keep_state_precedence_and_reverse_cleanup",
    "test_late_invalid_policy_blocks_every_startup_effect[root]",
    "test_late_invalid_policy_blocks_every_startup_effect[mounted]",
    "test_late_invalid_policy_blocks_every_startup_effect[metadata]",
    "test_startup_failure_keeps_framework_no_shutdown_semantics",
    "test_custom_lifespan_failure_unwinds_root_and_preserves_exception[enter]",
    "test_custom_lifespan_failure_unwinds_root_and_preserves_exception[exit]",
    "test_shutdown_failure_propagates_and_does_not_repeat_handlers",
    "test_resource_guard_dependency_and_schema_survive_real_lifespan",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_tree(name):
    root = SERVER / name
    entries = list(root.rglob("*"))
    require(not root.is_symlink() and not any(p.is_symlink() for p in entries), "source symlink")
    files = sorted(p for p in entries if p.is_file() and "__pycache__" not in p.parts
                   and p != Path(__file__).resolve())
    require(sum(p.stat().st_size for p in files) < 64 * 1024 * 1024, "source size bound")
    rows = [[str(p.relative_to(SERVER)), digest(p)] for p in files]
    return {"count": len(rows), "sha256": hashlib.sha256(
        json.dumps(rows, separators=(",", ":")).encode()).hexdigest()}


def installed_inventory(prefix):
    site = prefix / "lib/python3.13/site-packages"
    files = sorted(site.glob("*.dist-info/METADATA"))
    require(files and not any(p.is_symlink() for p in files), "installed metadata missing/symlink")
    rows = [[str(p.relative_to(site)), digest(p)] for p in files]
    return {"distributions": rows, "routing": {
        name: digest(site / name / "routing.py") for name in ("fastapi", "starlette")}}


def private_empty(key):
    path = Path(os.environ.get(key, ""))
    require(path.is_absolute() and ".." not in path.parts and path.is_dir(), "absolute private dir")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "directory symlink")
    require(path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o777 == 0o700
            and "lifespan-test" in path.name and not any(path.iterdir()), "fresh owned 0700 empty dir")
    return path


def verify():
    require(not any(k == "pytest" or k == "app" or k.startswith("app.") for k in sys.modules),
            "no application/pytest import before gate")
    require(sys.argv[1:] == ["--execute-approved-policy-lifespan-compatibility"], "exact execution opt-in")
    require(sys.flags.isolated and sys.flags.dont_write_bytecode and not sys.flags.optimize
            and sys.version_info[:2] == (3, 13), "isolated -I -B unoptimized Python3.13 required")
    flags = {FLAG, APPROVAL, "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE"}
    require(all(os.environ.get(k) == "1" for k in flags), "ROOT and test flags required")
    allowed = flags | {"HOME", "PATH", "LANG", "LC_ALL", "LIFESPAN_RUNNER_SHA256",
                       "LIFESPAN_SOURCE_HEAD", "LIFESPAN_EMPTY_CWD", "LIFESPAN_EVIDENCE_DIR",
                       "LIFESPAN_RUNTIME"}
    require(not set(os.environ) - allowed, "clean allowlisted environment; no database/settings/secrets")
    require(os.environ.get("HOME") == pwd.getpwuid(os.getuid()).pw_dir, "preserve actual HOME")
    require(digest(Path(__file__)) == os.environ.get("LIFESPAN_RUNNER_SHA256"), "ROOT-reviewed own SHA")
    require(SERVER == WORKTREE / "clearledger/server", "exact dedicated source tree")
    empty, evidence = private_empty("LIFESPAN_EMPTY_CWD"), private_empty("LIFESPAN_EVIDENCE_DIR")
    require(Path.cwd() == empty and empty != evidence, "separate empty cwd/evidence")
    require(FROZEN and {k: source_tree(k) for k in FROZEN} == FROZEN, "complete frozen app/tests/schema")
    require(SUPPORT and all(digest(SERVER / k) == v for k, v in SUPPORT.items()), "frozen support files")
    git_env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}

    def git(*args):
        return subprocess.check_output(["/usr/bin/git", "-C", str(WORKTREE), *args],
                                       env=git_env, text=True, timeout=5).strip()

    head = git("rev-parse", "HEAD")
    require(head == os.environ.get("LIFESPAN_SOURCE_HEAD") and len(head) == 40, "exact ROOT-approved commit")
    require(git("branch", "--show-current") == BRANCH, "dedicated branch")
    require(git("merge-base", BASE, head) == BASE, "exact integration base ancestry")
    require(not git("status", "--porcelain", "--untracked-files=normal"), "clean frozen worktree")
    runtime = os.environ.get("LIFESPAN_RUNTIME")
    require(runtime in INVENTORIES, "distinct old/new runtime selection")
    approved = INVENTORIES[runtime]
    require(sys.prefix == approved["prefix"] and sys.executable == approved["prefix"] + "/bin/python",
            "exact installed interpreter and venv; no other environment")
    inventory = installed_inventory(Path(sys.prefix))
    inventory_sha = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    require(inventory_sha == approved["sha256"], "exact installed distribution/source inventory")
    os.umask(0o077)
    return evidence, {"head": head, "base": BASE, "runtime": runtime, "prefix": sys.prefix,
                      "inventory": inventory, "inventory_sha256": inventory_sha,
                      "frozen": FROZEN, "runner_sha256": digest(Path(__file__))}


def install_boundary(attempts):
    import importlib.abc

    class NoDatabaseOrAssembly(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            denied = (fullname.split(".")[0] in {"sqlalchemy", "asyncpg", "psycopg", "psycopg2",
                                                  "sqlite3", "aiosqlite", "aiosmtplib", "smtplib"}
                      or fullname in {"app.main", "app.database", "app.config", "dotenv"}
                      or fullname.startswith("app.services"))
            if denied:
                attempts.append("import:" + fullname)
                raise ImportError("pure ASGI matrix forbids database/engine/config/sender/assembly imports")

    sys.meta_path.insert(0, NoDatabaseOrAssembly())

    def audit(event, args):
        denied = event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo",
                           "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg",
                           "socket.bind", "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec",
                           "os.fork", "os.forkpty", "sqlite3.connect"}
        if event == "open" and isinstance(args[0], (str, bytes)):
            path = Path(os.fsdecode(args[0]))
            denied = denied or path.name == ".env" or path.name.startswith(".env.") or bool(
                {".ssh", ".vault", ".claude"}.intersection(path.parts))
        if denied:
            attempts.append(event)
            raise OSError("lifespan matrix forbids SQL, external network, senders, subprocesses and dotenv")

    sys.addaudithook(audit)


def main():
    try:
        evidence, proof = verify()
    except Exception as exc:
        print(json.dumps({"ok": False, "phase": "approval", "error": str(exc)}))
        return 2
    attempts = []
    install_boundary(attempts)
    signal.signal(signal.SIGALRM, lambda *_: sys.exit("lifespan matrix exceeded 180 seconds"))
    signal.alarm(180)
    sys.path.insert(0, str(SERVER))
    import pytest

    class Boundary:
        def __init__(self):
            self.results = []
            self.collected = []
            self.patch = pytest.MonkeyPatch()

        def pytest_configure(self, config):
            import httpx

            def denied(*args, **kwargs):
                attempts.append("httpx.external_transport")
                raise AssertionError("only in-process TestClient transport allowed")

            async def async_denied(*args, **kwargs):
                return denied(*args, **kwargs)

            self.patch.setattr(httpx.HTTPTransport, "handle_request", denied)
            self.patch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_denied)

        def pytest_collection_modifyitems(self, session, config, items):
            self.collected = [item.name for item in items]
            if (set(self.collected) != TEST_NAMES or len(items) != len(TEST_NAMES)
                    or any(Path(i.path) != SERVER / "tests/test_policy_lifespan_compatibility.py" for i in items)):
                raise pytest.UsageError("exact focused lifecycle selection required")

        def pytest_runtest_logreport(self, report):
            self.results.append({"nodeid": report.nodeid, "phase": report.when, "outcome": report.outcome})

        def pytest_sessionfinish(self, session, exitstatus):
            calls = [r for r in self.results if r["phase"] == "call"]
            clean = (not attempts and "app.main" not in sys.modules and "app.database" not in sys.modules
                     and len(calls) == len(TEST_NAMES)
                     and all(r["outcome"] == "passed" for r in self.results)
                     and len(self.results) == 3 * len(TEST_NAMES))
            if not clean:
                session.exitstatus = 1
            (evidence / "boundary.json").write_text(json.dumps({
                **proof, "ok": clean and int(exitstatus) == 0, "database_allowed": False,
                "app_main_imported": "app.main" in sys.modules, "network_sql_sender_attempts": attempts,
                "collected": self.collected, "results": self.results,
            }, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

        def pytest_unconfigure(self, config):
            self.patch.undo()

    boundary = Boundary()
    code = pytest.main(["-c", str(SERVER / "pytest.ini"), "--noconftest", "-p", "pytest_asyncio.plugin",
                        "-p", "no:cacheprovider",
                        "-vv", "--tb=long", "--show-capture=no",
                        "--junitxml=" + str(evidence / "lifespan.xml"),
                        str(SERVER / "tests/test_policy_lifespan_compatibility.py")], plugins=[boundary])
    signal.alarm(0)
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
