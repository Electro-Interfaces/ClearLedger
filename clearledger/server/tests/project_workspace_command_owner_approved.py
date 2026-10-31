"""ROOT-only frozen project workspace command owner execution gate; workers must never execute this file."""
from contextlib import ExitStack
import contextvars
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import stat
import sys
from urllib.parse import urlsplit
import weakref

SERVER = Path(__file__).resolve().parents[1]
BASE_COMMIT = "495b66a81f07a12ae9845dde9b7a7d20b3324ac7"
CANDIDATE = Path("/srv/projects/api-modernization-upgrade-test-env-20261030/.venv")
SITE = CANDIDATE / "lib/python3.13/site-packages"
PORT = 33546
DATABASE = "api_project_workspace_command_owner_test_20261031"
RUNTIME = {'aiofiles': '24.1.0', 'aiohappyeyeballs': '2.7.1', 'aiohttp': '3.14.5', 'aiosignal': '1.4.0', 'aiosmtplib': '5.1.3', 'annotated-doc': '0.0.2', 'annotated-types': '0.8.0', 'anyio': '4.15.1', 'asyncpg': '0.30.0', 'attrs': '26.1.0', 'authlib': '1.9.1', 'bcrypt': '4.2.1', 'certifi': '2026.10.23', 'cffi': '2.1.1', 'charset-normalizer': '3.5.2', 'click': '8.5.0', 'cryptography': '50.0.2', 'dnspython': '2.9.1', 'email-validator': '2.3.0', 'et-xmlfile': '2.0.0', 'fastapi': '0.133.0', 'frozenlist': '1.8.0', 'greenlet': '3.5.6', 'gunicorn': '23.0.0', 'h11': '0.16.0', 'http-ece': '1.2.1', 'httpcore': '1.0.9', 'httptools': '0.9.0', 'httpx': '0.28.1', 'idna': '3.20', 'joserfc': '1.7.7', 'lxml': '6.1.3', 'multidict': '7.2.1', 'openpyxl': '3.1.5', 'packaging': '26.3', 'passlib': '1.7.4', 'pip': '26.2.2', 'propcache': '0.5.4', 'py-vapid': '1.9.6', 'pycparser': '3.12', 'pydantic': '2.14.2', 'pydantic-core': '2.50.2', 'pydantic-settings': '2.7.1', 'pyjwt': '2.15.0', 'pypdf': '6.21.2', 'python-docx': '1.1.2', 'python-dotenv': '1.2.2', 'python-multipart': '0.0.31', 'pywebpush': '2.5.0', 'pyyaml': '6.0.3', 'requests': '2.34.2', 'sqlalchemy': '2.0.36', 'starlette': '1.3.1', 'typing-extensions': '4.16.0', 'typing-inspection': '0.4.4', 'urllib3': '2.8.0', 'uvicorn': '0.34.0', 'uvloop': '0.23.0', 'watchfiles': '1.3.0', 'websockets': '17.3', 'yarl': '1.25.1'}
TOOLS = {'iniconfig': '2.3.1', 'jsonschema': '4.26.0', 'jsonschema-path': '0.5.0', 'jsonschema-specifications': '2025.9.1', 'lazy-object-proxy': '1.13.0', 'openapi-schema-validator': '0.9.0', 'openapi-spec-validator': '0.9.0', 'pathable': '0.6.0', 'pluggy': '1.7.0', 'pygments': '2.21.0', 'pytest': '9.2.0', 'pytest-asyncio': '1.4.1', 'referencing': '0.37.0', 'rfc3339-validator': '0.1.4', 'rpds-py': '2026.9.1', 'six': '1.17.0'}

APP_DIGEST = 'cb0243fba571708c2b314b813b47f3959651652a93e5e926b03bb78287118381'
TESTS_DIGEST = '060a1f0381a3fe2cd34a79aa50df511ff058e6c7a5ebbbe1413b235e15de0425'
SCHEMA_DIGEST = '51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d'
APP_COUNT = 500
TESTS_COUNT_WITHOUT_SELF = 371
SCHEMA_COUNT = 16
SUPPORT_FILES = {'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601'}
SELECTION = [
    "tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[discussion-native]",
    "tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[discussion-context]",
    "tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[decision-native]",
    "tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[decision-context]",
    "tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[file-native]",
    "tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[file-context]",
    "tests/test_project_workspace_command_owner.py::test_link_write_authority_and_repeat_counts[task-editable-author-200]"
]
EXPECTED_COUNTS = [
    1,
    1,
    1,
    1,
    1,
    1,
    1
]
EXPECTED_GROUP_COUNTS = {'tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes': 6, 'tests/test_project_workspace_command_owner.py::test_link_write_authority_and_repeat_counts': 1}
EXPECTED_CASES = 7
MAX_FILES = 4000
MAX_BLOB = 8 * 1024 * 1024
MAX_TREE = 64 * 1024 * 1024
MAX_SECONDS = 600
MAX_CAPTURE_EVENTS = 4000
LIMIT_SCRATCH = 128 * 1024 * 1024


def refuse(message="project workspace command owner immutable approval boundary refused"):
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
        refuse("four separate private owned empty test directories required")
    return path


def verify_approval():
    if sys.argv[1:] != ["--execute-approved-project-workspace-command-owner-tests"]:
        refuse("exact ROOT execution argument required")
    if (sys.version_info[:3] != (3, 13, 7) or sys.flags.optimize or not sys.dont_write_bytecode
            or not sys.flags.isolated or not sys.flags.no_site
            or os.confstr("CS_GNU_LIBC_VERSION") != "glibc 2.36"
            or Path(sys.executable).absolute().parent != CANDIDATE / "bin"
            or any("site-packages" in p or p in {"", str(SERVER)} for p in sys.path)
            or any(m in sys.modules for m in ("pytest", "app", "site"))):
        refuse("unoptimized Python 3.13 with bytecode writes disabled required")
    flags = ("ROOT_APPROVED_PROJECT_WORKSPACE_COMMAND_OWNER_TESTS", "RUN_PROJECT_WORKSPACE_COMMAND_OWNER_TESTS",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE")
    if any(os.environ.get(flag) != "1" for flag in flags):
        refuse("explicit ROOT/test opt-ins required")
    allowed = {*flags, "HOME", "PATH", "LANG", "LC_ALL", "APP_ENV", "SECRET_KEY",
               "DATABASE_URL", "TEST_DATABASE_URL", "UPLOAD_DIR", "PROJECT_WORKSPACE_COMMAND_OWNER_PG_PORT",
               "SEED_SUPERADMIN_EMAIL", "SEED_SUPERADMIN_PASSWORD", "ECOSYSTEM_COMPANIES",
               "PROJECT_WORKSPACE_COMMAND_OWNER_EMPTY_CWD", "PROJECT_WORKSPACE_COMMAND_OWNER_EVIDENCE_DIR", "PROJECT_WORKSPACE_COMMAND_OWNER_RUNNER_SHA256",
               "TMPDIR", "PROJECT_WORKSPACE_COMMAND_OWNER_SCRATCH_DIR"}
    if set(os.environ) - allowed or os.environ.get("HOME") != pwd.getpwuid(os.getuid()).pw_dir:
        refuse("clean allowlisted environment and preserved actual HOME required")
    if os.environ.get("APP_ENV") != "test" or os.environ.get("SECRET_KEY") != "project-workspace-command-owner-boundary-synthetic-secret-only":
        refuse("synthetic test settings required")
    if (os.environ.get("SEED_SUPERADMIN_EMAIL") != "admin@clearledger.ru"
            or os.environ.get("SEED_SUPERADMIN_PASSWORD") != "admin123"
            or os.environ.get("ECOSYSTEM_COMPANIES") != ""):
        refuse("explicit synthetic conftest seed required before cached Settings import")
    expected_self = os.environ.get("PROJECT_WORKSPACE_COMMAND_OWNER_RUNNER_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_self) or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != expected_self:
        refuse("ROOT-reviewed immutable runner SHA required")
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("DATABASE_URL") != raw:
        refuse("explicit matching database URLs required")
    target = urlsplit(raw)
    port = os.environ.get("PROJECT_WORKSPACE_COMMAND_OWNER_PG_PORT", "")
    if (not re.fullmatch(r"[1-9][0-9]{0,4}", port) or not 1024 <= int(port) <= 65535
            or target.scheme != "postgresql+asyncpg" or target.query or target.fragment
            or target.hostname != "127.0.0.1" or not target.username or not target.password
            or target.path != "/" + DATABASE or target.port != PORT or int(port) != PORT
            or target.username != "clearledger" or target.password != "api_test_only"
            or "@" in target.username or ":" in target.username):
        refuse("exact ROOT-approved numeric loopback PostgreSQL disposable database required")
    empty = private_empty(os.environ.get("PROJECT_WORKSPACE_COMMAND_OWNER_EMPTY_CWD", ""))
    upload = private_empty(os.environ.get("UPLOAD_DIR", ""))
    evidence = private_empty(os.environ.get("PROJECT_WORKSPACE_COMMAND_OWNER_EVIDENCE_DIR", ""))
    scratch = private_empty(os.environ.get("PROJECT_WORKSPACE_COMMAND_OWNER_SCRATCH_DIR", ""))
    directories = [p.resolve() for p in (empty, upload, evidence, scratch)]
    if (Path.cwd() != empty or os.environ.get("TMPDIR") != str(scratch) or len(set(directories)) != 4
            or any(a != b and (a.is_relative_to(b) or b.is_relative_to(a))
                   for a in directories for b in directories)
            or any(p.is_relative_to(SERVER / "app") or p.is_relative_to(SERVER / "tests")
                   or p.is_relative_to(SERVER / "schema_migrations") for p in directories)):
        refuse("separate non-nested cwd/upload/evidence/scratch directories required")
    if (tree_digest(SERVER / "app", count=APP_COUNT) != APP_DIGEST
            or tree_digest(SERVER / "tests", count=TESTS_COUNT_WITHOUT_SELF, exclude_self=True) != TESTS_DIGEST
            or tree_digest(SERVER / "schema_migrations", count=SCHEMA_COUNT) != SCHEMA_DIGEST):
        refuse("full app/tests/schema differs from approval")
    if any((SERVER / path).is_symlink() or hashlib.sha256((SERVER / path).read_bytes()).hexdigest() != expected
           for path, expected in SUPPORT_FILES.items()):
        refuse("test configuration/dependency source differs")
    os.umask(0o077)
    installed = inventory()
    return evidence, scratch, upload, target, installed


def inventory():
    if not SITE.is_dir() or SITE.is_symlink() or not CANDIDATE.is_dir():
        refuse()
    cfg = (CANDIDATE / "pyvenv.cfg").read_text()
    if not re.search(r"^include-system-site-packages\s*=\s*false\s*$", cfg, re.M):
        refuse()
    if any(p.is_symlink() or p.suffix == ".pth" or p.name in {"sitecustomize.py", "usercustomize.py"}
           for p in SITE.rglob("*")):
        refuse()
    installed = {}
    for dist in importlib.metadata.distributions(path=[str(SITE)]):
        name = re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower()
        if name in installed:
            refuse()
        installed[name] = dist.version
    if len(RUNTIME) != 61 or len(TOOLS) != 16 or set(RUNTIME) & set(TOOLS) or installed != {**RUNTIME, **TOOLS}:
        refuse()
    return installed

def pg_sendmsg_metadata_allowed(family, socktype, protocol, owned_fd, current_fd,
                               peer_exact, extra_args, extra_kwargs):
    """Pure metadata policy; no data buffers, addresses, sockets or I/O inspected."""
    return (family == socket.AF_INET and socktype == socket.SOCK_STREAM
            and protocol in (0, socket.IPPROTO_TCP)
            and type(owned_fd) is int and owned_fd >= 0
            and type(current_fd) is int and current_fd >= 0 and current_fd == owned_fd
            and peer_exact is True and not extra_args and not extra_kwargs)

def sendmsg_metadata_controls():
    """One positive and exact negative source matrix; no live socket/probe is created."""
    good = dict(family=socket.AF_INET, socktype=socket.SOCK_STREAM,
                protocol=socket.IPPROTO_TCP, owned_fd=17, current_fd=17,
                peer_exact=True, extra_args=(), extra_kwargs={})
    bad = {
        'unowned': {'owned_fd': None}, 'closed': {'current_fd': -1},
        'fd_reused_or_detached': {'current_fd': 18}, 'wrong_peer_or_unconnected': {'peer_exact': False},
        'datagram': {'socktype': socket.SOCK_DGRAM}, 'unix': {'family': socket.AF_UNIX},
        'ipv6': {'family': socket.AF_INET6}, 'raw': {'socktype': socket.SOCK_RAW},
        'other_protocol': {'protocol': 132}, 'ancillary': {'extra_args': ((('forbidden',),),)},
        'explicit_flags_even_zero': {'extra_args': ((), 0)},
        'explicit_address': {'extra_args': ((), 0, ('forbidden', 1))},
        'keyword_flags': {'extra_kwargs': {'flags': 0}},
        'keyword_ancillary': {'extra_kwargs': {'ancdata': ()}},
        'keyword_address': {'extra_kwargs': {'address': None}},
    }
    checks = {'owned_connected_pg_stream_only': pg_sendmsg_metadata_allowed(**good)}
    checks.update({name: not pg_sendmsg_metadata_allowed(**{**good, **changed}) for name, changed in bad.items()})
    if not all(checks.values()):
        raise RuntimeError('PG sendmsg metadata source controls failed')
    return checks

def install_boundaries(target, counters, stack, writable):
    owned = weakref.WeakKeyDictionary()
    active_sendmsg = contextvars.ContextVar("r1_pg_sendmsg", default=None)
    native_sendmsg = socket.socket.sendmsg
    native_fileno, native_peer, native_type = socket.socket.fileno, socket.socket.getpeername, socket.socket.getsockopt

    def allowed(sock, args=(), kwargs=None):
        try:
            return pg_sendmsg_metadata_allowed(
                sock.family, native_type(sock, socket.SOL_SOCKET, socket.SO_TYPE), sock.proto,
                owned.get(sock), native_fileno(sock), native_peer(sock) == ("127.0.0.1", PORT),
                args, {} if kwargs is None else kwargs)
        except (OSError, TypeError, AttributeError):
            return False

    def deny(event):
        if len(counters["forbidden"]) < MAX_CAPTURE_EVENTS:
            counters["forbidden"].append(event)
        refuse()

    def audit(event, args):
        if event == "socket.connect":
            sock, address = args
            if (address != ("127.0.0.1", PORT) or sock.family != socket.AF_INET
                    or native_type(sock, socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
                    or sock.proto not in (0, socket.IPPROTO_TCP) or native_fileno(sock) < 0):
                deny(event)
            owned[sock] = native_fileno(sock)
            counters["pg_connect"] += 1
        elif event == "socket.sendmsg":
            active = active_sendmsg.get()
            if (active is None or len(args) != 2 or args[0] is not active[0] or args[1] is not None
                    or sys._getframe(1).f_code is not exact_sendmsg.__code__ or not allowed(args[0])
                    or native_fileno(args[0]) != active[1]):
                deny(event)
            counters["pg_sendmsg"] += 1
        elif event == "socket.getaddrinfo":
            if args[0] != "127.0.0.1" or int(args[1]) != PORT:
                deny(event)
        elif event in {"socket.bind", "socket.sendto", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
                       "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.forkpty"}:
            deny(event)
        elif event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0]))
            if path.name == ".env" or path.name.startswith(".env.") or {".ssh", ".vault", ".claude"} & set(path.parts):
                deny(event)
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                absolute = path.resolve()
                if not any(absolute.is_relative_to(root) for root in writable):
                    deny("write-outside-owned-test-roots")

    def exact_sendmsg(sock, buffers, *args, **kwargs):
        if not allowed(sock, args, kwargs):
            deny("sendmsg-metadata")
        capability = active_sendmsg.set((sock, native_fileno(sock)))
        try:
            return native_sendmsg(sock, buffers)
        finally:
            active_sendmsg.reset(capability)

    sys.addaudithook(audit)
    from unittest.mock import patch
    stack.enter_context(patch.object(socket.socket, "sendmsg", exact_sendmsg))
    stack.enter_context(patch.object(socket.socket, "listen", lambda *a, **k: deny("socket.listen")))
    # Reviewed import-only urllib3 IPv6 probe suppression; no bind is permitted.
    old_ipv6 = socket.has_ipv6
    try:
        socket.has_ipv6 = False
        import aiohttp
        import aiosmtplib
        import httpx
        import pywebpush
        import requests
    finally:
        socket.has_ipv6 = old_ipv6
    counters["ipv6_probe_flag_restored"] = socket.has_ipv6 is old_ipv6
    import asyncpg
    original_connect = asyncpg.connect
    expected = dict(host="127.0.0.1", port=PORT, database=DATABASE, user=target.username, password=target.password)
    async def connect(dsn=None, **kwargs):
        if dsn is not None:
            parsed = urlsplit(dsn)
            if (parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname != expected["host"]
                    or parsed.port != PORT or parsed.path != "/" + DATABASE or parsed.query or parsed.fragment
                    or parsed.username != target.username or parsed.password != target.password):
                deny("sql-target")
        if any((key not in kwargs and dsn is None) or (key in kwargs and kwargs[key] != value) for key, value in expected.items()):
            deny("sql-override")
        kwargs["server_settings"] = {**(kwargs.get("server_settings") or {}), "statement_timeout": "20000",
            "lock_timeout": "2000", "idle_in_transaction_session_timeout": "30000"}
        kwargs["timeout"], kwargs["command_timeout"] = 10, 30
        return await original_connect(dsn, **kwargs)
    stack.enter_context(patch.object(asyncpg, "connect", connect))
    async def no_external(*args, **kwargs):
        deny("external-http")
    def no_external_sync(*args, **kwargs):
        deny("external-http")
    stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", no_external))
    stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", no_external_sync))
    stack.enter_context(patch.object(requests.sessions.Session, "request", no_external_sync))
    stack.enter_context(patch.object(aiohttp.ClientSession, "_request", no_external))

    return counters



def scratch_bound(root, anchor):
    now = root.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_uid)
    if identity(now) != anchor or not stat.S_ISDIR(now.st_mode) or now.st_mode & 0o077:
        refuse()
    size = count = 0
    for path in root.rglob("*"):
        count += 1
        try:
            info = path.lstat()
        except FileNotFoundError:
            # Only transient descendants under the unchanged owned root may vanish.
            if not path.is_relative_to(root) or path == root:
                refuse()
            continue
        if stat.S_ISREG(info.st_mode):
            size += info.st_size
        if count > 4096 or size > LIMIT_SCRATCH:
            refuse()
    if identity(root.lstat()) != anchor:
        refuse()
    return size

def sources_unchanged():
    return (tree_digest(SERVER / "app", count=APP_COUNT) == APP_DIGEST
            and tree_digest(SERVER / "tests", count=TESTS_COUNT_WITHOUT_SELF, exclude_self=True) == TESTS_DIGEST
            and tree_digest(SERVER / "schema_migrations", count=SCHEMA_COUNT) == SCHEMA_DIGEST
            and hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == os.environ["PROJECT_WORKSPACE_COMMAND_OWNER_RUNNER_SHA256"]
            and all(hashlib.sha256((SERVER / path).read_bytes()).hexdigest() == expected
                    for path, expected in SUPPORT_FILES.items()))


def main():
    try:
        evidence, scratch, upload, target, installed = verify_approval()
    except Exception:
        print(json.dumps({"ok": False, "phase": "project_workspace_command_owner_source_environment_approval"}))
        return 2
    anchors = {p: (p.stat().st_dev, p.stat().st_ino, p.stat().st_uid) for p in (scratch, upload, evidence)}
    counters = dict(forbidden=[], pg_connect=0, pg_sendmsg=0, delivery={})
    blocked = counters["forbidden"]
    controls = sendmsg_metadata_controls()
    stack = ExitStack()
    sys.path[:0] = [str(SITE), str(SERVER)]
    install_boundaries(target, counters, stack, (scratch, upload, evidence))
    signal.signal(signal.SIGALRM, lambda *_: refuse("project workspace command owner execution time bound exceeded"))
    signal.alarm(MAX_SECONDS)
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

        def pytest_configure(self, config):
            config._project_workspace_command_owner_boundary = self

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
            if (not self.installed or actual != EXPECTED_GROUP_COUNTS
                    or set(item.nodeid for item in items) != set(SELECTION)
                    or dict(zip(SELECTION, EXPECTED_COUNTS)) != {key: 1 for key in SELECTION}
                    or len(items) != EXPECTED_CASES or len({item.nodeid for item in items}) != len(items)):
                raise pytest.UsageError("exact frozen project workspace command owner cases and delivery stubs required")
            self.collected = [item.nodeid for item in items]

        def pytest_runtest_setup(self, item):
            if not self.installed:
                refuse("delivery stubs must precede every fixture setup")
            self.started.append(item.nodeid)

        def pytest_runtest_logreport(self, report):
            self.outcomes.append({"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome})

        def pytest_runtest_teardown(self, item, nextitem):
            for path, anchor in anchors.items():
                scratch_bound(path, anchor)

        def pytest_sessionfinish(self, session, exitstatus):
            source_after = sources_unchanged()
            calls = [r for r in self.outcomes if r["when"] == "call"]
            if (blocked or not counters["ipv6_probe_flag_restored"] or not all(controls.values())
                    or inventory() != installed or not source_after or len(calls) != EXPECTED_CASES or any(r["outcome"] != "passed" for r in calls)
                    or len(self.started) != EXPECTED_CASES):
                session.exitstatus = 1
            payload = {"network_attempts_blocked": blocked, "network_boundary": counters,
                       "source_after": source_after, "sendmsg_metadata_controls": controls, "verified_inventory_count": len(installed), "delivery_capture": self.capture,
                       "external_delivery_stubbed_before_conftest": self.installed,
                       "collected": self.collected, "results": self.outcomes,
                       "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "app_sha256": APP_DIGEST, "tests_without_runner_sha256": TESTS_DIGEST,
                       "schema_sha256": SCHEMA_DIGEST, "expected_cases": EXPECTED_CASES,
                       "exitstatus": int(session.exitstatus)}
            raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            if len(raw) > 1024 * 1024:
                refuse("evidence size bound exceeded")
            with (evidence / "project-workspace-command-owner-boundary.json").open("xb") as output:
                output.write(raw)

        def pytest_unconfigure(self, config):
            self.patch.undo()

    try:
        return pytest.main(["-c", str(SERVER / "pytest.ini"), "-p", "pytest_asyncio.plugin",
                            "-p", "no:cacheprovider", "-vv", "--tb=short", "--capture=sys", "--basetemp=" + str(scratch / "pytest-test"),
                            "--log-file=" + str(evidence / "pytest.log"),
                            "--junitxml=" + str(evidence / "project-workspace-command-owner.xml"),
                            *(str(SERVER / item) for item in SELECTION)], plugins=[DeliveryBoundary()])
    finally:
        signal.alarm(0)
        stack.close()
        for path, anchor in anchors.items():
            scratch_bound(path, anchor)


if __name__ == "__main__":
    raise SystemExit(main())
