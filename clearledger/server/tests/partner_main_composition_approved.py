"""ROOT-only M18 execution gate. Preparation workers must never run/import it.

Only stdlib executes before verify_approval. No conftest, dotenv, application,
pytest or database-driver import is permitted before the complete frozen gate.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import signal
import sys
from urllib.parse import urlsplit

SERVER = Path(__file__).resolve().parents[1]
BASE_COMMIT = "d2d014d873b6eb763f3cd03cc529dc3491d45cfb"
APP_DIGEST = 'fc73c090cd736b7e4a8f43df42025d78dee7114572989936a5ac27e99236e62a'
TESTS_DIGEST = 'bd352e7f2c77947355ea5377a9eb0c1ad251037885798ef55e6cf83c74dce320'
SCHEMA_DIGEST = '51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d'
APP_COUNT = 492
TESTS_COUNT_WITHOUT_SELF = 340
SCHEMA_COUNT = 16
SUPPORT_FILES = {'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601'}
SELECTION = (
    "test_main_problem_request_id_matches_outer_security_context",
    "test_main_swagger_canonical_projection_assets_session_csrf_and_live_revoke",
    "test_standalone_child_unavailable_problem_request_id_without_sql",
)
EXPECTED_CASES = 3
FLAG = "RUN_PARTNER_MAIN_COMPOSITION_TESTS"
ISSUER = "https://m18-space.example.invalid"
SECRET = "m18-synthetic-core-secret-never-production-20261030"
SCHEDULERS = ("channel_scheduler", "pulse_digest", "task_scheduler", "mail_poller",
              "store_price_scheduler", "onec_read_scheduler", "space_projection_scheduler", "intake_watch")


def refuse(message):
    raise RuntimeError(message)


def tree_digest(path, count, *, exclude_self=False):
    entries = [p for p in path.rglob("*") if "__pycache__" not in p.parts]
    if path.is_symlink() or any(p.is_symlink() for p in entries):
        refuse("source symlinks forbidden")
    files = sorted(p for p in entries if p.is_file()
                   and not (exclude_self and p == Path(__file__).resolve()))
    if len(files) != count or sum(p.stat().st_size for p in files) > 64 * 1024 * 1024:
        refuse("frozen source count/bytes differ")
    rows = [[str(p.relative_to(SERVER)), hashlib.sha256(p.read_bytes()).hexdigest()] for p in files]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def private_empty(value):
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts or not path.is_dir()
            or any(p.is_symlink() for p in (path, *path.parents))
            or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o777 != 0o700
            or "test" not in path.name or any(path.iterdir())):
        refuse("fresh owned 0700 empty test directory required")
    return path


def verify_approval():
    if sys.argv[1:] != ["--execute-approved-partner-main-composition"]:
        refuse("exact ROOT execution argument required")
    if sys.version_info[:2] != (3, 13) or sys.flags.optimize or not sys.flags.isolated:
        refuse("isolated unoptimized Python 3.13 required")
    flags = (FLAG, "ROOT_APPROVED_PARTNER_MAIN_COMPOSITION", "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
             "PYTHONDONTWRITEBYTECODE")
    if any(os.environ.get(key) != "1" for key in flags):
        refuse("ROOT and test opt-ins required")
    allowed = {*flags, "HOME", "PATH", "LANG", "LC_ALL", "DATABASE_URL", "TEST_DATABASE_URL",
               "UPLOAD_DIR", "APP_ENV", "SECRET_KEY", "M18_PG_PORT", "M18_EMPTY_CWD",
               "M18_EVIDENCE_DIR", "M18_RUNNER_SHA256"}
    if set(os.environ) - allowed or os.environ.get("HOME") != pwd.getpwuid(os.getuid()).pw_dir:
        refuse("clean allowlisted environment with actual HOME required")
    if os.environ.get("APP_ENV") != "test" or os.environ.get("SECRET_KEY") != SECRET:
        refuse("synthetic settings required")
    approved_sha = os.environ.get("M18_RUNNER_SHA256", "")
    if len(approved_sha) != 64 or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != approved_sha:
        refuse("ROOT reviewed runner SHA required")
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("DATABASE_URL") != raw:
        refuse("explicit byte-identical database URLs required")
    target = urlsplit(raw)
    if (target.scheme != "postgresql+asyncpg" or target.hostname != "127.0.0.1"
            or not target.port or str(target.port) != os.environ.get("M18_PG_PORT")
            or not target.username or not target.password or target.query or target.fragment
            or target.path != "/api_partner_main_test_20261030"):
        refuse("exact disposable database and ROOT-approved numeric loopback port required")
    empty, upload, evidence = [private_empty(os.environ.get(key, "")) for key in
                               ("M18_EMPTY_CWD", "UPLOAD_DIR", "M18_EVIDENCE_DIR")]
    if Path.cwd() != empty or len({p.resolve() for p in (empty, upload, evidence)}) != 3:
        refuse("three separate directories and empty cwd required")
    if (tree_digest(SERVER / "app", APP_COUNT) != APP_DIGEST
            or tree_digest(SERVER / "tests", TESTS_COUNT_WITHOUT_SELF, exclude_self=True) != TESTS_DIGEST
            or tree_digest(SERVER / "schema_migrations", SCHEMA_COUNT) != SCHEMA_DIGEST):
        refuse("full frozen app/tests/schema hashes differ")
    if any(hashlib.sha256((SERVER / name).read_bytes()).hexdigest() != expected
           for name, expected in SUPPORT_FILES.items()):
        refuse("support source differs")
    os.umask(0o077)
    return evidence, target.port


def install_network_boundary(port, attempts):
    def exact(address):
        return isinstance(address, tuple) and len(address) >= 2 and address[:2] == ("127.0.0.1", port)

    def audit(event, args):
        denied = ((event == "socket.connect" and not exact(args[1]))
                  or (event == "socket.getaddrinfo" and not exact(args))
                  or event in {"socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto",
                               "socket.bind", "subprocess.Popen", "os.system", "os.posix_spawn"})
        if event == "open" and isinstance(args[0], (str, bytes)):
            path = Path(os.fsdecode(args[0]))
            denied = denied or path.name == ".env" or path.name.startswith(".env.") or bool(
                {".ssh", ".vault", ".claude"}.intersection(path.parts))
        if denied:
            attempts.append(event)
            raise OSError("M18 permits only the exact approved PostgreSQL socket; no listeners/processes")
    sys.addaudithook(audit)


def main():
    try:
        evidence, port = verify_approval()
    except Exception:
        print(json.dumps({"ok": False, "phase": "m18_source_environment_approval"}))
        return 2
    attempts = []
    install_network_boundary(port, attempts)
    # The outer ROOT supervisor must also bound wall time/log bytes and reap the
    # child. SIGALRM is a second bound, never evidence that cleanup succeeded.
    signal.signal(signal.SIGALRM, lambda *_: sys.exit("M18 540s execution bound exceeded"))
    signal.alarm(540)
    sys.path.insert(0, str(SERVER))
    import pytest

    class Boundary:
        def __init__(self):
            self.patch = pytest.MonkeyPatch()
            self.counts = {}
            self.jobs = []
            self.results = []

        def counted(self, name):
            self.counts[name] = self.counts.get(name, 0) + 1

        def sync_capture(self, name):
            def capture(*args, **kwargs):
                self.counted(name)
                return None
            return capture

        def async_capture(self, name):
            async def capture(*args, **kwargs):
                self.counted(name)
                return True
            return capture

        def pytest_configure(self, config):
            import asyncio
            import base64
            import importlib
            import aiosmtplib
            import httpx
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from app.config import Settings
            # Explicitly disable dotenv at the settings source, preserving every
            # production default except these synthetic process-only switches.
            settings = Settings(_env_file=None)
            assert not any((settings.partner_oauth_enabled, settings.partner_api_enabled,
                            settings.partner_docs_enabled, settings.partner_api_budget_enabled))
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            settings.partner_oauth_signing_key = base64.b64encode(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption())).decode()
            settings.partner_oauth_issuer = ISSUER
            settings.partner_oauth_audience = "urn:elsyplus:m18:synthetic"
            settings.partner_oauth_enabled = settings.partner_api_enabled = settings.partner_docs_enabled = True
            settings.partner_docs_environment = "sandbox"
            settings.partner_docs_sandbox_api_url = ISSUER + "/api/v1"
            self.patch.setattr("app.config.get_settings", lambda: settings)
            self.patch.setattr(aiosmtplib, "send", self.async_capture("SMTP"))
            from app.services import chat_mail, chat_ws, email_service, jitsi, notify, web_push
            for name in ("send_invite", "send_access_invite", "_deliver", "send_notice",
                         "send_password_reset", "send_meeting_invite"):
                self.patch.setattr(email_service, name, self.async_capture("email." + name))
            for name in ("notify_person", "tell", "dispatch", "post_alert"):
                self.patch.setattr(notify, name, self.async_capture("notify." + name))
            self.patch.setattr(notify, "dispatch_async", self.sync_capture("notify.dispatch_async"))
            self.patch.setattr(chat_mail, "push_room_mail_async", self.sync_capture("chat_mail"))
            for name in ("push_room_async", "_send_one"):
                self.patch.setattr(web_push, name, self.sync_capture("web_push." + name))
            self.patch.setattr(jitsi, "sign_token", self.sync_capture("Jitsi"))
            for name in ("start", "stop", "broadcast"):
                self.patch.setattr(chat_ws.manager, name, self.async_capture("chat_ws." + name))

            def parked(name):
                async def run():
                    self.counted("scheduler." + name)
                    self.jobs.append(asyncio.current_task())
                    await asyncio.Event().wait()
                return run
            for name in SCHEDULERS:
                module = importlib.import_module("app.services." + name)
                self.patch.setattr(module, "run_forever", parked(name))

            original_send = httpx.AsyncClient.send
            async def asgi_only(client, request, **kwargs):
                if not isinstance(client._transport, httpx.ASGITransport):
                    self.counted("external_HTTP")
                    raise AssertionError("external HTTP forbidden in M18")
                return await original_send(client, request, **kwargs)
            self.patch.setattr(httpx.AsyncClient, "send", asgi_only)
            # Exact assembly import, after delivery boundaries, before fixtures.
            from app import main as application
            self.patch.setattr(application, "_prepare_database_once", self.async_capture("startup.prepare"))
            self.application = application
            self.settings = settings
            config._m18_boundary = self

        def pytest_collection_modifyitems(self, session, config, items):
            if (len(items) != EXPECTED_CASES or {i.name for i in items} != set(SELECTION)
                    or any(Path(i.path).name != "test_partner_main_composition.py" for i in items)):
                raise pytest.UsageError("exact three affected M18 cases required; previous five PASS must not repeat")

        def pytest_runtest_logreport(self, report):
            if report.when == "call" or report.failed or report.skipped:
                self.results.append({"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome})

        def pytest_sessionfinish(self, session, exitstatus):
            unexpected = {k: v for k, v in self.counts.items() if k not in
                          {"startup.prepare", "chat_ws.start", "chat_ws.stop", "notify.dispatch_async",
                           *["scheduler." + n for n in SCHEDULERS]}}
            expected_lifecycle = {"startup.prepare": 1, "chat_ws.start": 1, "chat_ws.stop": 1,
                                  "notify.dispatch_async": 1,
                                  **{"scheduler." + n: 1 for n in SCHEDULERS}}
            outcomes = [(r["when"], r["outcome"]) for r in self.results]
            exact_outcomes = sum(when == "call" and outcome in {"passed", "failed"}
                                 for when, outcome in outcomes) == EXPECTED_CASES and len(outcomes) == EXPECTED_CASES
            if attempts or unexpected or self.counts != expected_lifecycle or not exact_outcomes:
                session.exitstatus = 1
            (evidence / "boundary.json").write_text(json.dumps({
                "network_process_attempts": attempts, "capture_counts": self.counts,
                "unexpected_delivery_counts": unexpected, "expected_lifecycle_counts": expected_lifecycle,
                "results": self.results, "full_main_asgi": True, "nginx_browser_sso": False,
                "source_finding": "M18-RID-01: original equality retained; corrective affected-only retest, no xfail/skip",
            }, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

        def pytest_unconfigure(self, config):
            self.patch.undo()

    boundary = Boundary()
    result = pytest.main(["-c", str(SERVER / "pytest.ini"), "--noconftest", "-p", "pytest_asyncio.plugin",
                         "-p", "no:cacheprovider", "-vv", "--tb=short", "--show-capture=no",
                         "--junitxml=" + str(evidence / "main-composition.xml"),
                         *(str(SERVER / "tests/test_partner_main_composition.py") + "::" + name
                           for name in SELECTION)], plugins=[boundary])
    signal.alarm(0)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
