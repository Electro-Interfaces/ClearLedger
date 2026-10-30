"""ROOT-only M00 source/environment/target gate, stdlib until full approval.

Worker must not import/execute this file. ROOT supervises/reaps this child and
owns CREATE/DROP of exactly api_meeting_hosts_test_20261030, never production.
"""
from contextlib import ExitStack
import contextvars
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import pwd
import re
import resource
import signal
import socket
import stat
import sys
from urllib.parse import urlsplit
import weakref

SERVER = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
REPO = SERVER.parents[1]
BASE_COMMIT = "bdbd8ccb3798316cd4b6794bdc99ecf10af4101a"
CANDIDATE = Path("/srv/projects/api-modernization-upgrade-test-env-20261030/.venv")
SITE = CANDIDATE / "lib/python3.13/site-packages"
DATABASE = "api_meeting_hosts_test_20261030"
PORT = 33546
FLAG = "RUN_LIVE_PRESERVATION_TESTS"
SECRET = "live-preservation-synthetic-secret-only"
ISSUER = "https://live-preservation.example.invalid"
COUNTS = {'app': 492, 'tests': 355, 'schema_migrations': 16}
DIGESTS = {'app': 'cdbd485f51127cc5f337b5ab21a9e7af3b62428f6833dda7350727e70d5de045', 'tests': '17d105dd527a1c9659f2341921dd64a120680c1e7d4011cf615c1eb4c14c0eba', 'schema_migrations': '51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d'}
SUPPORT = {'clearledger/server/requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'clearledger/server/pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601', 'clearledger/server/Dockerfile': 'aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d'}
RUNTIME = {'aiofiles': '24.1.0', 'aiohappyeyeballs': '2.7.1', 'aiohttp': '3.14.5', 'aiosignal': '1.4.0', 'aiosmtplib': '5.1.3', 'annotated-doc': '0.0.2', 'annotated-types': '0.8.0', 'anyio': '4.15.1', 'asyncpg': '0.30.0', 'attrs': '26.1.0', 'authlib': '1.9.1', 'bcrypt': '4.2.1', 'certifi': '2026.10.23', 'cffi': '2.1.1', 'charset-normalizer': '3.5.2', 'click': '8.5.0', 'cryptography': '50.0.2', 'dnspython': '2.9.1', 'email-validator': '2.3.0', 'et-xmlfile': '2.0.0', 'fastapi': '0.133.0', 'frozenlist': '1.8.0', 'greenlet': '3.5.6', 'gunicorn': '23.0.0', 'h11': '0.16.0', 'http-ece': '1.2.1', 'httpcore': '1.0.9', 'httptools': '0.9.0', 'httpx': '0.28.1', 'idna': '3.20', 'joserfc': '1.7.7', 'lxml': '6.1.3', 'multidict': '7.2.1', 'openpyxl': '3.1.5', 'packaging': '26.3', 'passlib': '1.7.4', 'pip': '26.2.2', 'propcache': '0.5.4', 'py-vapid': '1.9.6', 'pycparser': '3.12', 'pydantic': '2.14.2', 'pydantic-core': '2.50.2', 'pydantic-settings': '2.7.1', 'pyjwt': '2.15.0', 'pypdf': '6.21.2', 'python-docx': '1.1.2', 'python-dotenv': '1.2.2', 'python-multipart': '0.0.31', 'pywebpush': '2.5.0', 'pyyaml': '6.0.3', 'requests': '2.34.2', 'sqlalchemy': '2.0.36', 'starlette': '1.3.1', 'typing-extensions': '4.16.0', 'typing-inspection': '0.4.4', 'urllib3': '2.8.0', 'uvicorn': '0.34.0', 'uvloop': '0.23.0', 'watchfiles': '1.3.0', 'websockets': '17.3', 'yarl': '1.25.1'}
TOOLS = {'iniconfig': '2.3.1', 'jsonschema': '4.26.0', 'jsonschema-path': '0.5.0', 'jsonschema-specifications': '2025.9.1', 'lazy-object-proxy': '1.13.0', 'openapi-schema-validator': '0.9.0', 'openapi-spec-validator': '0.9.0', 'pathable': '0.6.0', 'pluggy': '1.7.0', 'pygments': '2.21.0', 'pytest': '9.2.0', 'pytest-asyncio': '1.4.1', 'referencing': '0.37.0', 'rfc3339-validator': '0.1.4', 'rpds-py': '2026.9.1', 'six': '1.17.0'}
SELECTION = ["tests/test_live_baseline_preservation.py::test_actor_email_chat_and_common_hosts"]
EXPECTED = {"test_live_baseline_preservation.py": 8}

BASELINE_HASHES = {'database.py': 'bc1c712246d1dd0497a99bb6a7ce33f593580a8c7d02b291ebf8d043ed5886e3', 'models.py': '6aef22c515d013e282e02f39bde3431d94d45fb25077d056144250b606b509a1', 'routers/sites_router.py': '2e907dee625169600f8e3fba7a8e593c6b950f54318f11c9bdca08bca8282b59', 'services/charge_sessions_normalize.py': '2369896a9dbe3363e7b789d6532ae4389bed9eb68e4f2b5ac1c673b49a09707a', 'services/ezs_changes.py': '1636290a9e3dc5b70483e5a940b720332cb3d0e2dc63a341ed851433925bcb44', 'services/ezs_site_work.py': '734fb3ac87df90f6f6fc8574d2a64b09647457ad633b30a3abea96744ffa9d79', 'services/meeting_notice.py': 'f5055aa8423bdf1b996bdc54c784bbb6edfc1abf5252d5598e5bddb07feb57d7'}
HELPER_SOURCE_SHA256 = {'tests/product_contract_objects_approved.py': '4f48de90e1a5b69bb03a98c4a6b7d5dfe7d35670d8740e22fb810a4e81bc1a82',
                        'tests/backend_upgrade_main_approved.py': '4ea9370970cbe79182efca907791c01ad2ea47f63b8137f3ce2003644baf24cd'}
LIMIT_LOG = 2 * 1024 * 1024
LIMIT_SCRATCH = 128 * 1024 * 1024
DEADLINE = 600


def refuse():
    raise RuntimeError("M00 live preservation immutable approval boundary refused")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(path, count):
    entries = [p for p in path.rglob("*") if "__pycache__" not in p.parts]
    if path.is_symlink() or any(p.is_symlink() for p in entries):
        refuse()
    files = sorted(p for p in entries if p.is_file() and p != SELF)
    if len(files) != count or len(files) > 1024 or sum(p.stat().st_size for p in files) > 64 * 1024 * 1024:
        refuse()
    rows = [[str(p.relative_to(SERVER)), sha(p)] for p in files]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def source_guard():
    expected = os.environ.get("LIVE_PRESERVATION_RUNNER_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or SELF.is_symlink() or sha(SELF) != expected:
        refuse()
    if set(COUNTS) != {"app", "tests", "schema_migrations"} or set(DIGESTS) != set(COUNTS):
        refuse()
    for name, count in COUNTS.items():
        if tree_digest(SERVER / name, count) != DIGESTS[name]:
            refuse()
    if any(sha(REPO / name) != expected for name, expected in SUPPORT.items()):
        refuse()


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


def private_empty(key):
    path = Path(os.environ.get(key, ""))
    if (not path.is_absolute() or ".." in path.parts or not path.is_dir()
            or any(p.is_symlink() for p in (path, *path.parents))
            or path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) != 0o700
            or "test" not in path.name.lower() or any(path.iterdir())):
        refuse()
    return path


def verify_approval():
    if (sys.argv[1:] != ["--execute-approved-live-preservation-tests"]
            or sys.version_info[:3] != (3, 13, 7) or sys.flags.optimize
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or os.confstr("CS_GNU_LIBC_VERSION") != "glibc 2.36"
            or Path(sys.executable).absolute().parent != CANDIDATE / "bin"
            or any("site-packages" in p or p in {"", str(SERVER)} for p in sys.path)
            or any(m in sys.modules for m in ("pytest", "app", "site"))):
        refuse()
    flags = (FLAG, "ROOT_APPROVED_LIVE_PRESERVATION_TESTS", "RUN_MEETING_HOSTS_QUERY_TESTS",
             "ROOT_APPROVED_MEETING_HOSTS_QUERY_TESTS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE")
    if any(os.environ.get(key) != "1" for key in flags):
        refuse()
    allowed = {*flags, "HOME", "PATH", "LANG", "LC_ALL", "APP_ENV", "SECRET_KEY", "DATABASE_URL", "TEST_DATABASE_URL",
               "UPLOAD_DIR", "TMPDIR", "LIVE_PRESERVATION_BASELINE_DIR",
               "SEED_SUPERADMIN_EMAIL", "SEED_SUPERADMIN_PASSWORD", "ECOSYSTEM_COMPANIES", "LIVE_PRESERVATION_EMPTY_CWD", "LIVE_PRESERVATION_EVIDENCE_DIR", "LIVE_PRESERVATION_SCRATCH_DIR", "LIVE_PRESERVATION_RUNNER_SHA256"}
    if (set(os.environ) - allowed or os.environ.get("HOME") != pwd.getpwuid(os.getuid()).pw_dir
            or os.environ.get("APP_ENV") != "test" or os.environ.get("SECRET_KEY") != SECRET
            or os.environ.get("SEED_SUPERADMIN_EMAIL") != "admin@clearledger.ru"
            or os.environ.get("SEED_SUPERADMIN_PASSWORD") != "admin123"
            or os.environ.get("ECOSYSTEM_COMPANIES") != "") :
        refuse()
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("DATABASE_URL") != raw:
        refuse()
    target = urlsplit(raw)
    if (target.scheme != "postgresql+asyncpg" or target.hostname != "127.0.0.1" or target.port != PORT
            or target.path != "/" + DATABASE or target.query or target.fragment
            or target.username != "clearledger" or target.password != "api_test_only"):
        refuse()
    empty, upload, evidence, scratch = [private_empty(key) for key in
        ("LIVE_PRESERVATION_EMPTY_CWD", "UPLOAD_DIR", "LIVE_PRESERVATION_EVIDENCE_DIR", "LIVE_PRESERVATION_SCRATCH_DIR")]
    paths = (empty, upload, evidence, scratch)
    if (Path.cwd() != empty or os.environ.get("TMPDIR") != str(scratch)
            or len(set(paths)) != 4 or any(a in b.parents for a in paths for b in paths if a != b)):
        refuse()
    for origin in (empty, SERVER):
        if any((p / ".env").exists() or (p / ".env").is_symlink() for p in (origin, *origin.parents)):
            refuse()
    baseline = Path(os.environ.get("LIVE_PRESERVATION_BASELINE_DIR", ""))
    if not baseline.is_absolute() or any(p.is_symlink() for p in (baseline, *baseline.parents)):
        refuse()
    for relative, expected in BASELINE_HASHES.items():
        path = baseline / relative
        if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)) or sha(path) != expected:
            refuse()
    if any(sha(SERVER / name) != value for name, value in HELPER_SOURCE_SHA256.items()):
        refuse()
    source_guard()
    installed = inventory()
    os.umask(0o077)
    return evidence, scratch, upload, target, installed


def write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > LIMIT_LOG:
        refuse()
    with path.open("xb") as output:
        output.write(raw)


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
        counters["forbidden"].append(event)
        refuse()

    def audit(event, args):
        if event == "socket.connect":
            sock, address = args
            if (address != ("127.0.0.1", PORT) or sock.family != socket.AF_INET
                    or native_type(sock, socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
                    or sock.proto not in (0, socket.IPPROTO_TCP)):
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
        elif event in {"socket.bind", "socket.sendto", "socket.gethostbyname", "socket.gethostbyaddr",
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
    def no_listener(*args, **kwargs):
        deny("socket.listen")
    stack.enter_context(patch.object(socket.socket, "listen", no_listener))
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
    counters["ipv6_import_control"] = dict(scope=["aiohttp", "aiosmtplib", "httpx", "pywebpush", "requests"],
        suppressed=True, restored=socket.has_ipv6 is old_ipv6, bind_allowance=False)
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

    from app import config
    settings = config.Settings(_env_file=None)
    if any((settings.partner_oauth_enabled, settings.partner_api_enabled, settings.partner_docs_enabled,
            settings.partner_api_budget_enabled, settings.managed_core_budget_enabled)):
        refuse()
    stack.enter_context(patch.object(config, "get_settings", return_value=settings))
    stack.enter_context(patch.object(config, "settings", settings))
    def capture(name, *, asynchronous=False):
        def called(*args, **kwargs):
            counters["delivery"][name] = counters["delivery"].get(name, 0) + 1
            return None
        async def acalled(*args, **kwargs):
            return called(*args, **kwargs)
        return acalled if asynchronous else called
    stack.enter_context(patch.object(aiosmtplib, "send", capture("smtp", asynchronous=True)))
    stack.enter_context(patch.object(pywebpush, "webpush", capture("webpush")))
    # Before importing any HTTP router, capture existing delivery aliases.
    from app.services import email_service, notify
    original_meeting_email = email_service.send_meeting_invite
    for name in ("send_invite", "send_access_invite", "_deliver", "send_notice", "send_password_reset", "send_meeting_invite"):
        stack.enter_context(patch.object(email_service, name, capture("email." + name, asynchronous=True)))
    stack.enter_context(patch.object(notify, "dispatch_async", capture("notify.dispatch_async")))
    for name in ("notify_person", "tell", "dispatch", "post_alert"):
        stack.enter_context(patch.object(notify, name, capture("notify." + name, asynchronous=True)))
    from app.services import chat_mail, chat_ws, meeting_notice, web_push
    for owner, name, asynchronous in (
            (meeting_notice, "в_личку", True), (chat_mail, "push_room_mail_async", False),
            (web_push, "push_room_async", False), (web_push, "_send_one", False),
            (chat_ws.manager, "broadcast", True)):
        stack.enter_context(patch.object(owner, name, capture(name, asynchronous=asynchronous)))
    return settings, original_meeting_email



def main():
    try:
        evidence, scratch, upload, target, installed = verify_approval()
    except Exception:
        print(json.dumps({"ok": False, "phase": "live_preservation_pre_import_approval"}))
        return 2
    resource.setrlimit(resource.RLIMIT_CPU, (600, 600))
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT_LOG, LIMIT_LOG))
    signal.signal(signal.SIGALRM, lambda *_: sys.exit("M00 live preservation wall deadline"))
    signal.alarm(DEADLINE)
    anchors = {p: (p.stat().st_dev, p.stat().st_ino, p.stat().st_uid) for p in (scratch, upload, evidence)}
    controls = sendmsg_metadata_controls()
    counters = dict(forbidden=[], pg_connect=0, pg_sendmsg=0, delivery={})
    write_json(evidence / "pre-import-boundary.json", dict(runner_sha256=sha(SELF),
        source_base=BASE_COMMIT, counts=COUNTS, digests=DIGESTS, baseline_sha256=BASELINE_HASHES,
        helper_source_sha256=HELPER_SOURCE_SHA256, python="3.13.7", inventory_count=len(installed),
        environment_keys=sorted(os.environ), home_preserved=True, no_app_pytest_site_imported=True))
    sys.path[:0] = [str(SITE), str(SERVER)]
    with ExitStack() as stack:
        settings, original_meeting_email = install_boundaries(target, counters, stack, (scratch, upload, evidence))
        import pytest

        class Boundary:
            def __init__(self):
                self.results, self.collection, self.failures, self.capture_counts = [], {}, [], {}
                self.capture = {"meeting_email": [], "chat": []}

            @pytest.fixture(autouse=True)
            def meeting_delivery_capture(self, request):
                from unittest.mock import patch
                from app.services import email_service, meeting_notice
                for value in self.capture.values():
                    value.clear()
                with ExitStack() as local:
                    # Only the original MIME suite restores the high-level sender;
                    # its delivery fixture captures SMTP below it before scenario calls.
                    if Path(request.node.path).name == "test_calendar_actor_mail.py":
                        local.enter_context(patch.object(email_service, "send_meeting_invite", original_meeting_email))
                    if request.node.name == "test_asgi_invitation_uses_sorted_hosts_and_captured_delivery":
                        async def mail(to, **fields):
                            self.capture["meeting_email"].append({"to": to, **fields})
                            return True
                        async def chat(db, cid, actor, person, text, title):
                            self.capture["chat"].append(dict(person_id=person.id, text=text, title=title))
                            return True
                        local.enter_context(patch.object(email_service, "send_meeting_invite", mail))
                        local.enter_context(patch.object(meeting_notice, "в_личку", chat))
                    yield self.capture
                self.capture_counts[request.node.nodeid] = {key: len(value) for key, value in self.capture.items()}

            def pytest_collection_modifyitems(self, session, config, items):
                for item in items:
                    name = Path(item.path).name
                    self.collection[name] = self.collection.get(name, 0) + 1
                    if item.get_closest_marker("skip") or item.get_closest_marker("skipif") or item.get_closest_marker("xfail"):
                        refuse()
                if self.collection != EXPECTED:
                    raise pytest.UsageError("M00 exact affected 8-case selection differs")

            def pytest_runtest_logreport(self, report):
                if report.when == "call" or report.failed or report.skipped:
                    self.results.append(dict(nodeid=report.nodeid, when=report.when, outcome=report.outcome))
                if report.failed:
                    trace = report.longreprtext
                    trace = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s]+@", r"\1[redacted]@", trace)
                    self.failures.append(dict(nodeid=report.nodeid, when=report.when, trace=trace[:16384]))

            def pytest_runtest_teardown(self, item, nextitem):
                for path, anchor in anchors.items():
                    scratch_bound(path, anchor)

            @pytest.hookimpl(trylast=True)
            def pytest_sessionfinish(self, session, exitstatus):
                source_guard()
                if inventory() != installed:
                    refuse()
                if (counters["forbidden"] or not counters["ipv6_import_control"]["restored"]
                        or len(self.results) != sum(EXPECTED.values())
                        or any(r["when"] != "call" or r["outcome"] != "passed" for r in self.results)):
                    session.exitstatus = 1
                write_json(evidence / "live-preservation-boundary.json", dict(counters=counters, results=self.results,
                    collection=self.collection, source_after="PASS", inventory_after="PASS",
                    sendmsg_metadata_controls=controls, capture_counts=self.capture_counts,
                    source_base=BASE_COMMIT, production=False, full_main=False))
                write_json(evidence / "failures.json", self.failures)

        boundary = Boundary()
        result = pytest.main(["-c", str(SERVER / "pytest.ini"), "-p", "pytest_asyncio.plugin",
            "-p", "no:cacheprovider", "-q", "--tb=short", "--show-capture=no", "--capture=sys",
            "--basetemp=" + str(scratch / "pytest-test"), "--log-file=" + str(evidence / "pytest.log"),
            "--junitxml=" + str(evidence / "live-preservation.xml"),
            *(str(SERVER / item) for item in SELECTION)], plugins=[boundary])
        signal.alarm(0)
        for path, anchor in anchors.items():
            scratch_bound(path, anchor)
        return result


if __name__ == "__main__":
    raise SystemExit(main())
