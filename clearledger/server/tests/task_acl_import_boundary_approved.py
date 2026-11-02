"""ROOT-only frozen task ACL execution gate; workers must never execute this file."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import signal
import stat
import sys
from urllib.parse import urlsplit

SERVER = Path(__file__).resolve().parents[1]
BASE_COMMIT = "cf209237bf495e7b5fa981976fac20959c88d5db"
APP_DIGEST = '1360e0813ed1206204183ceb4f66a9cff00090cfc83204e6aca1f5f1f532792b'
TESTS_DIGEST = 'be918799bba483d2ba71b4950f617a518d1bd6c2bf039f3a7da1ba8394faab8b'
SCHEMA_DIGEST = '51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d'
APP_COUNT = 492
TESTS_COUNT_WITHOUT_SELF = 340
SCHEMA_COUNT = 16
SUPPORT_FILES = {'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601'}
SELECTION = [
    "tests/test_task_acl_import_boundary.py::test_work_union_and_single_read_preserve_task_doc_acl",
]
EXPECTED_COUNTS = [11]
EXPECTED_CASES = 11
MAX_FILES = 4000
MAX_BLOB = 8 * 1024 * 1024
MAX_TREE = 64 * 1024 * 1024
MAX_SECONDS = 600
MAX_CAPTURE_EVENTS = 4000


def refuse(message):
    raise RuntimeError(message)


def tree_digest(path, *, count, exclude_self=False):
    entries = list(path.rglob("*"))
    if path.is_symlink() or len(entries) > 2 * MAX_FILES or any(p.is_symlink() for p in entries):
        refuse("source symlinks/count differ from approval")
    files = sorted(p for p in entries if "__pycache__" not in p.parts and p.is_file()
                   and not (exclude_self and p == Path(__file__).resolve()))
    if (len(files) != count or len(files) > MAX_FILES
            or any(p.stat().st_size > MAX_BLOB for p in files)
            or sum(p.stat().st_size for p in files) > MAX_TREE
            or any(not stat.S_ISREG(p.stat().st_mode) for p in files)):
        refuse("frozen source count/bytes/type differ")
    manifest = [[str(p.relative_to(SERVER)), hashlib.sha256(p.read_bytes()).hexdigest()] for p in files]
    return hashlib.sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest()


def private_empty(value):
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts or not path.is_dir()
            or any(p.is_symlink() for p in [path, *path.parents])
            or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077
            or "test" not in path.name.lower() or any(path.iterdir())):
        refuse("three separate private owned empty test directories required")
    return path


def verify_approval():
    if sys.argv[1:] != ["--execute-approved-task-acl-import-boundary-tests"]:
        refuse("exact ROOT execution argument required")
    if sys.version_info[:2] != (3, 13) or sys.flags.optimize or not sys.dont_write_bytecode:
        refuse("unoptimized Python 3.13 with bytecode writes disabled required")
    flags = ("ROOT_APPROVED_TASK_ACL_IMPORT_BOUNDARY_TESTS", "RUN_TASK_ACL_IMPORT_BOUNDARY_TESTS",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE")
    if any(os.environ.get(flag) != "1" for flag in flags):
        refuse("explicit ROOT/test opt-ins required")
    allowed = {*flags, "HOME", "PATH", "LANG", "LC_ALL", "APP_ENV", "SECRET_KEY",
               "DATABASE_URL", "TEST_DATABASE_URL", "UPLOAD_DIR", "TASK_ACL_PG_PORT",
               "TASK_ACL_EMPTY_CWD", "TASK_ACL_EVIDENCE_DIR", "TASK_ACL_RUNNER_SHA256"}
    if set(os.environ) - allowed or os.environ.get("HOME") != pwd.getpwuid(os.getuid()).pw_dir:
        refuse("clean allowlisted environment and preserved actual HOME required")
    if os.environ.get("APP_ENV") != "test" or os.environ.get("SECRET_KEY") != "task-acl-boundary-synthetic-secret-only":
        refuse("synthetic test settings required")
    expected_self = os.environ.get("TASK_ACL_RUNNER_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_self) or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != expected_self:
        refuse("ROOT-reviewed immutable runner SHA required")
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("DATABASE_URL") != raw:
        refuse("explicit matching database URLs required")
    target = urlsplit(raw)
    port = os.environ.get("TASK_ACL_PG_PORT", "")
    if (not re.fullmatch(r"[1-9][0-9]{0,4}", port) or not 1024 <= int(port) <= 65535
            or target.scheme != "postgresql+asyncpg" or target.query or target.fragment
            or target.hostname != "127.0.0.1" or not target.username or not target.password
            or target.path != "/api_task_acl_boundary_test_20261030" or target.port != int(port)
            or "@" in target.username or ":" in target.username):
        refuse("exact ROOT-approved numeric loopback PostgreSQL disposable database required")
    empty = private_empty(os.environ.get("TASK_ACL_EMPTY_CWD", ""))
    upload = private_empty(os.environ.get("UPLOAD_DIR", ""))
    evidence = private_empty(os.environ.get("TASK_ACL_EVIDENCE_DIR", ""))
    directories = [p.resolve() for p in (empty, upload, evidence)]
    if (Path.cwd() != empty or len(set(directories)) != 3
            or any(a != b and (a.is_relative_to(b) or b.is_relative_to(a))
                   for a in directories for b in directories)
            or any(p.is_relative_to(SERVER / "app") or p.is_relative_to(SERVER / "tests")
                   or p.is_relative_to(SERVER / "schema_migrations") for p in directories)):
        refuse("separate non-nested cwd/upload/evidence directories required")
    if (tree_digest(SERVER / "app", count=APP_COUNT) != APP_DIGEST
            or tree_digest(SERVER / "tests", count=TESTS_COUNT_WITHOUT_SELF, exclude_self=True) != TESTS_DIGEST
            or tree_digest(SERVER / "schema_migrations", count=SCHEMA_COUNT) != SCHEMA_DIGEST):
        refuse("full app/tests/schema differs from approval")
    if any((SERVER / path).is_symlink() or hashlib.sha256((SERVER / path).read_bytes()).hexdigest() != expected
           for path, expected in SUPPORT_FILES.items()):
        refuse("test configuration/dependency source differs")
    os.umask(0o077)
    return evidence, target.port


def install_network_boundary(port, blocked):
    """Only numeric approved PG outbound; socketpair for asyncio remains local."""
    def approved(address):
        return (isinstance(address, tuple) and len(address) == 2
                and address[0] == "127.0.0.1" and address[1] == port)

    def audit(event, args):
        denied = ((event == "socket.connect" and not approved(args[1]))
                  or (event == "socket.getaddrinfo" and not approved(args[:2]))
                  or event in {"socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
                               "socket.sendto", "socket.sendmsg", "socket.bind", "subprocess.Popen",
                               "os.system", "os.exec", "os.posix_spawn"})
        if denied:
            if len(blocked) < MAX_CAPTURE_EVENTS:
                blocked.append(event)
            raise OSError("external network/process disabled by task ACL ROOT gate")
    sys.addaudithook(audit)


def main():
    try:
        evidence, port = verify_approval()
    except Exception:
        print(json.dumps({"ok": False, "phase": "task_acl_source_environment_approval"}))
        return 2
    blocked = []
    install_network_boundary(port, blocked)
    signal.signal(signal.SIGALRM, lambda *_: refuse("task ACL execution time bound exceeded"))
    signal.alarm(MAX_SECONDS)
    sys.path.insert(0, str(SERVER))
    # First pytest/app/ORM imports occur only beyond every approval check.
    import pytest

    class DeliveryBoundary:
        def __init__(self):
            self.patch = pytest.MonkeyPatch()
            self.capture = []
            self.collected = []
            self.started = []
            self.outcomes = []
            self.installed = False

        def record(self, name):
            if len(self.capture) >= MAX_CAPTURE_EVENTS:
                refuse("delivery capture count bound exceeded")
            # Deliberately no recipients, credentials, content or argument repr.
            self.capture.append(name)

        def pytest_load_initial_conftests(self, early_config, parser, args):
            import aiosmtplib
            import smtplib
            from app.services import chat_mail, chat_ws, email_service, meeting_notice, notify, task_mail, web_push

            def sync_capture(name):
                def captured(*args, **kwargs):
                    self.record(name)
                    return True
                return captured

            def async_capture(name):
                async def captured(*args, **kwargs):
                    self.record(name)
                    return True
                return captured

            for module, names in (
                (email_service, ("send_invite", "send_access_invite", "_deliver", "send_notice",
                                 "send_meeting_invite", "send_password_reset")),
                (notify, ("notify_person", "tell", "dispatch", "post_alert")),
                (chat_mail, ("send_notice",)),
                (task_mail, ("send_notice", "send_notice_checked")),
                (meeting_notice, ("в_личку",)),
            ):
                for name in names:
                    self.patch.setattr(module, name, async_capture(module.__name__ + "." + name))
            self.patch.setattr(aiosmtplib, "send", async_capture("aiosmtplib.send"))
            for name in ("connect", "sendmail", "send_message"):
                self.patch.setattr(aiosmtplib.SMTP, name, async_capture("aiosmtplib.SMTP." + name))
                self.patch.setattr(smtplib.SMTP, name, sync_capture("smtplib.SMTP." + name))
            for module, names in (
                (notify, ("dispatch_async",)), (chat_mail, ("push_room_mail_async",)),
                (task_mail, ("send_delegation_async", "send_notice_async")),
                (web_push, ("push_room_async", "_send_one")),
            ):
                for name in names:
                    self.patch.setattr(module, name, sync_capture(module.__name__ + "." + name))
            for name in ("broadcast", "_publish", "_broadcast_local"):
                self.patch.setattr(chat_ws.manager, name, async_capture("chat_ws." + name))
            self.installed = True

        def pytest_collection_modifyitems(self, session, config, items):
            actual = {}
            for item in items:
                key = "tests/" + Path(str(item.path)).name + "::" + item.originalname
                actual[key] = actual.get(key, 0) + 1
            if (not self.installed or actual != dict(zip(SELECTION, EXPECTED_COUNTS))
                    or len(items) != EXPECTED_CASES or len({item.nodeid for item in items}) != len(items)):
                raise pytest.UsageError("exact 11 corrected union cases and delivery stubs required")
            self.collected = [item.nodeid for item in items]

        def pytest_runtest_setup(self, item):
            if not self.installed:
                refuse("delivery stubs must precede every fixture setup")
            self.started.append(item.nodeid)

        def pytest_runtest_logreport(self, report):
            self.outcomes.append({"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome})

        def pytest_sessionfinish(self, session, exitstatus):
            calls = [r for r in self.outcomes if r["when"] == "call"]
            if (blocked or len(calls) != EXPECTED_CASES or any(r["outcome"] != "passed" for r in calls)
                    or len(self.started) != EXPECTED_CASES):
                session.exitstatus = 1
            payload = {"network_attempts_blocked": blocked, "delivery_capture": self.capture,
                       "external_delivery_stubbed_before_conftest": self.installed,
                       "collected": self.collected, "results": self.outcomes,
                       "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "app_sha256": APP_DIGEST, "tests_without_runner_sha256": TESTS_DIGEST,
                       "schema_sha256": SCHEMA_DIGEST, "expected_cases": EXPECTED_CASES,
                       "exitstatus": int(session.exitstatus)}
            raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            if len(raw) > 1024 * 1024:
                refuse("evidence size bound exceeded")
            with (evidence / "task-acl-boundary.json").open("xb") as output:
                output.write(raw)

        def pytest_unconfigure(self, config):
            self.patch.undo()

    try:
        return pytest.main(["-c", str(SERVER / "pytest.ini"), "-p", "pytest_asyncio.plugin",
                            "-p", "no:cacheprovider", "-vv", "--tb=short", "--basetemp=" + str(evidence / "tmp"),
                            "--junitxml=" + str(evidence / "task-acl.xml"),
                            *(str(SERVER / item) for item in SELECTION)], plugins=[DeliveryBoundary()])
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
