"""ROOT-only frozen meeting-hosts gate; worker must never execute this runner."""
import hashlib
from ipaddress import ip_address
import json
import os
from pathlib import Path
import pwd
import sys
from urllib.parse import urlsplit

SERVER = Path(__file__).resolve().parents[1]
BASE_COMMIT = "05e462d99009580bd529e3096740fdc077e83dd2"
APP_DIGEST = '716fa867894646a1977ea89c970503d319c9205c0b0459e73682a7722534a5fe'
TESTS_DIGEST = '40c99db8e6f3b22b489d277c4514e9af8baf8988322932160375d63ec522b64b'
SCHEMA_DIGEST = '51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d'
APP_COUNT = 492
TESTS_COUNT_WITHOUT_SELF = 338
SCHEMA_COUNT = 16
SUPPORT_FILES = {'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601'}
SELECTION = [
    "tests/test_meeting_hosts_query.py",
    "tests/test_conf_app.py::test_ведущие_встречи_и_пять_минут",
]
EXPECTED_CASES = 8


def refuse(message):
    raise RuntimeError(message)


def tree_digest(path, *, count, exclude_self=False):
    entries = [p for p in path.rglob("*") if "__pycache__" not in p.parts]
    if path.is_symlink() or any(p.is_symlink() for p in entries):
        refuse("source symlinks are not approved")
    files = sorted(p for p in entries if p.is_file() and not (exclude_self and p == Path(__file__).resolve()))
    if len(files) != count or sum(p.stat().st_size for p in files) > 64 * 1024 * 1024:
        refuse("frozen source count/bytes differ")
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
    if sys.argv[1:] != ["--execute-approved-meeting-hosts-tests"]:
        refuse("exact ROOT execution argument required")
    if sys.version_info[:2] != (3, 13) or sys.flags.optimize:
        refuse("unoptimized Python 3.13 required")
    flags = ("ROOT_APPROVED_MEETING_HOSTS_QUERY_TESTS", "RUN_MEETING_HOSTS_QUERY_TESTS",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE")
    if any(os.environ.get(flag) != "1" for flag in flags):
        refuse("explicit ROOT/test opt-ins required")
    allowed = {*flags, "HOME", "PATH", "LANG", "LC_ALL", "APP_ENV", "SECRET_KEY",
               "DATABASE_URL", "TEST_DATABASE_URL", "UPLOAD_DIR", "MEETING_HOSTS_PG_PORT",
               "MEETING_HOSTS_EMPTY_CWD", "MEETING_HOSTS_EVIDENCE_DIR", "MEETING_HOSTS_RUNNER_SHA256"}
    if set(os.environ) - allowed or os.environ.get("HOME") != pwd.getpwuid(os.getuid()).pw_dir:
        refuse("clean allowlisted environment and preserved HOME required")
    if os.environ.get("APP_ENV") != "test" or os.environ.get("SECRET_KEY") != "meeting-hosts-synthetic-secret-only":
        refuse("synthetic test settings required")
    expected_self = os.environ.get("MEETING_HOSTS_RUNNER_SHA256", "")
    if len(expected_self) != 64 or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != expected_self:
        refuse("ROOT-reviewed immutable runner SHA required")
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("DATABASE_URL") != raw:
        refuse("explicit matching database URLs required")
    target = urlsplit(raw)
    if (target.scheme != "postgresql+asyncpg" or target.query or target.fragment
            or target.hostname != "127.0.0.1" or not ip_address(target.hostname).is_loopback
            or not target.username or not target.password
            or target.path != "/api_meeting_hosts_test_20261030"
            or not target.port or str(target.port) != os.environ.get("MEETING_HOSTS_PG_PORT")):
        refuse("exact ROOT-approved disposable meeting-hosts database required")
    empty = private_empty(os.environ.get("MEETING_HOSTS_EMPTY_CWD", ""))
    upload = private_empty(os.environ.get("UPLOAD_DIR", ""))
    evidence = private_empty(os.environ.get("MEETING_HOSTS_EVIDENCE_DIR", ""))
    if Path.cwd() != empty or len({p.resolve() for p in (empty, upload, evidence)}) != 3:
        refuse("separate cwd/upload/evidence required")
    if (tree_digest(SERVER / "app", count=APP_COUNT) != APP_DIGEST
            or tree_digest(SERVER / "tests", count=TESTS_COUNT_WITHOUT_SELF, exclude_self=True) != TESTS_DIGEST
            or tree_digest(SERVER / "schema_migrations", count=SCHEMA_COUNT) != SCHEMA_DIGEST):
        refuse("full app/tests/schema differs from approval")
    if any(hashlib.sha256((SERVER / path).read_bytes()).hexdigest() != expected
           for path, expected in SUPPORT_FILES.items()):
        refuse("test configuration/dependency source differs")
    os.umask(0o077)
    return evidence, target.port


def install_network_boundary(port, blocked):
    """Allow only the approved PostgreSQL socket; ASGI has no network socket."""
    def approved(address):
        return (isinstance(address, tuple) and len(address) >= 2
                and address[0] == "127.0.0.1" and address[1] == port)

    def audit(event, args):
        denied = ((event == "socket.connect" and not approved(args[1]))
                  or (event == "socket.getaddrinfo" and not approved(args))
                  or event in {"socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto"})
        if denied:
            blocked.append(event)
            raise OSError("external network disabled by meeting-hosts ROOT gate")
    sys.addaudithook(audit)


def main():
    try:
        evidence, port = verify_approval()
    except Exception:
        print(json.dumps({"ok": False, "phase": "meeting_hosts_source_environment_approval"}))
        return 2
    blocked = []
    install_network_boundary(port, blocked)
    sys.path.insert(0, str(SERVER))
    # First pytest/app/driver imports are strictly beyond every frozen approval.
    import pytest

    class DeliveryBoundary:
        def __init__(self):
            self.patch = pytest.MonkeyPatch()
            self.capture = {"meeting_email": [], "chat": [], "other": []}
            self.totals = {}

        def pytest_configure(self, config):
            import aiosmtplib
            from app.services import chat_mail, chat_ws, email_service, meeting_notice, notify, web_push

            async def meeting_email(to, **fields):
                self.capture["meeting_email"].append({"to": to, **fields})
                return True

            async def chat(db, cid, actor, person, text, title):
                self.capture["chat"].append({"person_id": person.id, "text": text, "title": title})
                return True

            def sync_capture(name):
                def captured(*args, **kwargs):
                    self.capture["other"].append(name)
                return captured

            def async_capture(name):
                async def captured(*args, **kwargs):
                    self.capture["other"].append(name)
                    return True
                return captured

            self.patch.setattr(email_service, "send_meeting_invite", meeting_email)
            self.patch.setattr(meeting_notice, "в_личку", chat)
            for name in ("send_invite", "send_access_invite", "_deliver", "send_notice", "send_password_reset"):
                self.patch.setattr(email_service, name, async_capture("email_service." + name))
            self.patch.setattr(aiosmtplib, "send", async_capture("SMTP"))
            for name in ("notify_person", "tell", "dispatch", "post_alert"):
                self.patch.setattr(notify, name, async_capture("notify." + name))
            self.patch.setattr(notify, "dispatch_async", sync_capture("notify.dispatch_async"))
            self.patch.setattr(chat_mail, "push_room_mail_async", sync_capture("chat_mail"))
            self.patch.setattr(web_push, "push_room_async", sync_capture("web_push"))
            self.patch.setattr(web_push, "_send_one", sync_capture("web_push.low_level"))
            self.patch.setattr(chat_ws.manager, "broadcast", async_capture("chat_ws.broadcast"))

        @pytest.fixture(autouse=True)
        def meeting_delivery_capture(self, request):
            for rows in self.capture.values():
                rows.clear()
            yield self.capture
            self.totals[request.node.nodeid] = {key: len(value) for key, value in self.capture.items()}

        def pytest_collection_modifyitems(self, session, config, items):
            if len(items) != EXPECTED_CASES:
                raise pytest.UsageError("exact eight focused meeting-hosts cases required")

        def pytest_sessionfinish(self, session, exitstatus):
            if blocked:
                session.exitstatus = 1
            (evidence / "meeting-hosts-boundary.json").write_text(json.dumps({
                "network_attempts_blocked": len(blocked), "capture_counts": self.totals,
                "external_delivery_stubbed": True,
            }, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

        def pytest_unconfigure(self, config):
            self.patch.undo()

    return pytest.main(["-c", str(SERVER / "pytest.ini"), "-p", "pytest_asyncio.plugin",
                        "-p", "no:cacheprovider", "-vv", "--tb=short",
                        "--junitxml=" + str(evidence / "meeting-hosts.xml"),
                        *(str(SERVER / item) for item in SELECTION)], plugins=[DeliveryBoundary()])


if __name__ == "__main__":
    raise SystemExit(main())
