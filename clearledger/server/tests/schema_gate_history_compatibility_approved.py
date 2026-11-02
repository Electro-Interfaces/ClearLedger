"""ROOT-only frozen schema gate history suite; workers must not execute this file."""
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
B_COMMIT = "1c73980f464a0b69e5203b8798d0b307cfb8630d"
CANDIDATE = Path("/srv/projects/api-modernization-upgrade-test-env-20261030/.venv")
SITE = CANDIDATE / "lib/python3.13/site-packages"
PORT = 33546
DATABASE = "api_schema_gate_history_test_20261031"
APP_DIGEST = '824e5ae16ff330d93e2d3f66ebe19e46c0b32aecd77edba5c742e8aaf3badca0'
TESTS_DIGEST = 'bf1fb7dd613c320866f2e6f009069ae54ae629635206397530415e1a396a5c34'
SCHEMA_DIGEST = '36144e75b41d79b27e5e8d455e963d46deb400968582d6f53983d440344b2165'
APP_COUNT = 503
TESTS_COUNT_WITHOUT_SELF = 387
SCHEMA_COUNT = 24
SUPPORT_FILES = {'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601', 'Dockerfile': 'aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d', '.dockerignore': '219f4861afde083e955dccd850e20ac3f86a4d3b51164c484e7fca1620490d6a'}
MAX_FILES = 4000
MAX_BLOB = 8 * 1024 * 1024
MAX_TREE = 64 * 1024 * 1024
MAX_SECONDS = 600
MAX_CAPTURE_EVENTS = 6000
LIMIT_SCRATCH = 128 * 1024 * 1024
_RUNNING = False
_ACTIVE_COUNTERS = None
DRIVER_SOURCE_FILES = {
    "asyncpg/connection.py": "105948ff55489121734accec5020a5d1e1492134fee4c712b80566589c82cbe6",
    "asyncpg/introspection.py": "6e28878f9c90301f1119c8764e21f64cfa1c37738eebf19ab328a3158c6050e3",
}

RUNTIME = {'aiofiles': '24.1.0', 'aiohappyeyeballs': '2.7.1', 'aiohttp': '3.14.5', 'aiosignal': '1.4.0', 'aiosmtplib': '5.1.3', 'annotated-doc': '0.0.2', 'annotated-types': '0.8.0', 'anyio': '4.15.1', 'asyncpg': '0.30.0', 'attrs': '26.1.0', 'authlib': '1.9.1', 'bcrypt': '4.2.1', 'certifi': '2026.10.23', 'cffi': '2.1.1', 'charset-normalizer': '3.5.2', 'click': '8.5.0', 'cryptography': '50.0.2', 'dnspython': '2.9.1', 'email-validator': '2.3.0', 'et-xmlfile': '2.0.0', 'fastapi': '0.133.0', 'frozenlist': '1.8.0', 'greenlet': '3.5.6', 'gunicorn': '23.0.0', 'h11': '0.16.0', 'http-ece': '1.2.1', 'httpcore': '1.0.9', 'httptools': '0.9.0', 'httpx': '0.28.1', 'idna': '3.20', 'joserfc': '1.7.7', 'lxml': '6.1.3', 'multidict': '7.2.1', 'openpyxl': '3.1.5', 'packaging': '26.3', 'passlib': '1.7.4', 'pip': '26.2.2', 'propcache': '0.5.4', 'py-vapid': '1.9.6', 'pycparser': '3.12', 'pydantic': '2.14.2', 'pydantic-core': '2.50.2', 'pydantic-settings': '2.7.1', 'pyjwt': '2.15.0', 'pypdf': '6.21.2', 'python-docx': '1.1.2', 'python-dotenv': '1.2.2', 'python-multipart': '0.0.31', 'pywebpush': '2.5.0', 'pyyaml': '6.0.3', 'requests': '2.34.2', 'sqlalchemy': '2.0.36', 'starlette': '1.3.1', 'typing-extensions': '4.16.0', 'typing-inspection': '0.4.4', 'urllib3': '2.8.0', 'uvicorn': '0.34.0', 'uvloop': '0.23.0', 'watchfiles': '1.3.0', 'websockets': '17.3', 'yarl': '1.25.1'}
TOOLS = {'iniconfig': '2.3.1', 'jsonschema': '4.26.0', 'jsonschema-path': '0.5.0', 'jsonschema-specifications': '2025.9.1', 'lazy-object-proxy': '1.13.0', 'openapi-schema-validator': '0.9.0', 'openapi-spec-validator': '0.9.0', 'pathable': '0.6.0', 'pluggy': '1.7.0', 'pygments': '2.21.0', 'pytest': '9.2.0', 'pytest-asyncio': '1.4.1', 'referencing': '0.37.0', 'rfc3339-validator': '0.1.4', 'rpds-py': '2026.9.1', 'six': '1.17.0'}
CASE_GROUPS = {'off': ['OFF-connection-no-io', 'OFF-engine-no-checkout'], 'known_prefixes': ['P1-created-no-successor-prerequisites', 'P1-adopted', 'P2-created-no-pulse-prerequisites', 'P2-adopted', 'P3-created', 'P3-adopted'], 'history_shape': ['H-empty', 'H-missing-journal', 'H-gap-1', 'H-gap-2', 'H-unknown-row', 'H-future-row', 'H-extra-over-bound', 'H-duplicate-or-reordered', 'H-required-absent'], 'history_fields': ['H1-revision', 'H1-ordinal', 'H1-parent_revision', 'H1-artifact_sha256', 'H1-contract_sha256', 'H1-predecessor_sha256', 'H1-runner_format', 'H1-app_commit', 'H1-applied_by', 'H1-action', 'H2-revision', 'H2-ordinal', 'H2-parent_revision', 'H2-artifact_sha256', 'H2-contract_sha256', 'H2-predecessor_sha256', 'H2-runner_format', 'H2-app_commit', 'H2-applied_by', 'H2-action', 'H3-revision', 'H3-ordinal', 'H3-parent_revision', 'H3-artifact_sha256', 'H3-contract_sha256', 'H3-predecessor_sha256', 'H3-runner_format', 'H3-app_commit', 'H3-applied_by', 'H3-action'], 'catalog': ['C-budget-column', 'C-budget-fk-trigger', 'C-journal-shape', 'C-parent-ownership', 'C-calendar-managed-column', 'C-calendar-managed-check', 'C-calendar-owner', 'C-pulse-shape', 'C-pulse-fk', 'C-pulse-trigger-acl', 'C-public-sentinel'], 'configuration_source': ['S-driver', 'S-query-TLS', 'S-expectedDB', 'S-expectedUser', 'S-empty-identity', 'S-source-artifact', 'S-registry-unknown', 'S-source-verifier-marker', 'S-default-port'], 'actual_connection': ['T-borrowed-lazy-TX', 'T-borrowed-readwrite-continuation', 'T-borrowed-readonly-enforcement', 'T-borrowed-isolation-path-options', 'T-owned-RR-readonly', 'T-actual-public-refusal', 'T-actual-identity-refusal', 'T-no-writes-locks-options-extra-connect', 'T-safe-error-redaction', 'T-gate-repeat-invariance', 'T-cold-jit-on', 'T-cold-jit-off'], 'old_independent': ['OLD-immutable-harness-closure-preserved', 'OLD-gate-P2-refusal', 'OLD-explicit-default-runner-P2-refusal']}
EXPECTED_FULL_IDS = ['OFF-connection-no-io', 'OFF-engine-no-checkout', 'P1-created-no-successor-prerequisites', 'P1-adopted', 'P2-created-no-pulse-prerequisites', 'P2-adopted', 'P3-created', 'P3-adopted', 'H-empty', 'H-missing-journal', 'H-gap-1', 'H-gap-2', 'H-unknown-row', 'H-future-row', 'H-extra-over-bound', 'H-duplicate-or-reordered', 'H-required-absent', 'H1-revision', 'H1-ordinal', 'H1-parent_revision', 'H1-artifact_sha256', 'H1-contract_sha256', 'H1-predecessor_sha256', 'H1-runner_format', 'H1-app_commit', 'H1-applied_by', 'H1-action', 'H2-revision', 'H2-ordinal', 'H2-parent_revision', 'H2-artifact_sha256', 'H2-contract_sha256', 'H2-predecessor_sha256', 'H2-runner_format', 'H2-app_commit', 'H2-applied_by', 'H2-action', 'H3-revision', 'H3-ordinal', 'H3-parent_revision', 'H3-artifact_sha256', 'H3-contract_sha256', 'H3-predecessor_sha256', 'H3-runner_format', 'H3-app_commit', 'H3-applied_by', 'H3-action', 'C-budget-column', 'C-budget-fk-trigger', 'C-journal-shape', 'C-parent-ownership', 'C-calendar-managed-column', 'C-calendar-managed-check', 'C-calendar-owner', 'C-pulse-shape', 'C-pulse-fk', 'C-pulse-trigger-acl', 'C-public-sentinel', 'S-driver', 'S-query-TLS', 'S-expectedDB', 'S-expectedUser', 'S-empty-identity', 'S-source-artifact', 'S-registry-unknown', 'S-source-verifier-marker', 'S-default-port', 'T-borrowed-lazy-TX', 'T-borrowed-readwrite-continuation', 'T-borrowed-readonly-enforcement', 'T-borrowed-isolation-path-options', 'T-owned-RR-readonly', 'T-actual-public-refusal', 'T-actual-identity-refusal', 'T-no-writes-locks-options-extra-connect', 'T-safe-error-redaction', 'T-gate-repeat-invariance', 'T-cold-jit-on', 'T-cold-jit-off', 'OLD-immutable-harness-closure-preserved', 'OLD-gate-P2-refusal', 'OLD-explicit-default-runner-P2-refusal']
EXPECTED_CASES = 82


def refuse(message="pulse view role schema immutable approval boundary refused"):
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

def verify_approval():
    if sys.argv[1:] != ["--execute-approved-schema-gate-history-tests"]:
        refuse("exact ROOT execution argument required")
    if (sys.version_info[:3] != (3, 13, 7) or sys.flags.optimize or not sys.dont_write_bytecode
            or not sys.flags.isolated or not sys.flags.no_site
            or os.confstr("CS_GNU_LIBC_VERSION") != "glibc 2.36"
            or Path(sys.executable).absolute().parent != CANDIDATE / "bin"
            or any("site-packages" in p or p in {"", str(SERVER)} for p in sys.path)
            or any(m in sys.modules for m in ("pytest", "app", "site"))):
        refuse("exact isolated unoptimized Python/tool entrypoint required")
    flags = ("ROOT_APPROVED_SCHEMA_GATE_HISTORY_TESTS", "RUN_SCHEMA_GATE_HISTORY_TESTS", "PYTHONDONTWRITEBYTECODE")
    allowed = {*flags, "HOME", "PATH", "LANG", "LC_ALL", "APP_ENV", "SECRET_KEY", "ECOSYSTEM_COMPANIES",
               "DATABASE_URL", "TEST_DATABASE_URL", "UPLOAD_DIR", "SCHEMA_GATE_HISTORY_PG_PORT",
               "SCHEMA_GATE_HISTORY_EMPTY_CWD", "SCHEMA_GATE_HISTORY_EVIDENCE_DIR", "SCHEMA_GATE_HISTORY_RUNNER_SHA256",
               "TMPDIR", "SCHEMA_GATE_HISTORY_SCRATCH_DIR"}
    if (any(os.environ.get(flag) != "1" for flag in flags) or set(os.environ) - allowed
            or os.environ.get("HOME") != pwd.getpwuid(os.getuid()).pw_dir):
        refuse("explicit ROOT opt-ins and exact scrubbed environment required")
    if (os.environ.get("APP_ENV") != "test"
            or os.environ.get("SECRET_KEY") != "schema-gate-history-synthetic-secret-only"
            or os.environ.get("ECOSYSTEM_COMPANIES") != ""):
        refuse("explicit synthetic settings required")
    own = os.environ.get("SCHEMA_GATE_HISTORY_RUNNER_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", own) or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != own:
        refuse("ROOT-reviewed immutable runner SHA required")
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("DATABASE_URL") != raw:
        refuse("explicit matching database URLs required")
    from urllib.parse import urlsplit
    target = urlsplit(raw)
    if (target.scheme != "postgresql+asyncpg" or target.hostname != "127.0.0.1" or target.port != PORT
            or target.path != "/" + DATABASE or target.username != "clearledger" or target.password != "api_test_only"
            or target.query or target.fragment or os.environ.get("SCHEMA_GATE_HISTORY_PG_PORT") != str(PORT)):
        refuse("exact dedicated numeric-loopback PostgreSQL target required")
    empty = private_empty(os.environ.get("SCHEMA_GATE_HISTORY_EMPTY_CWD", ""))
    upload = private_empty(os.environ.get("UPLOAD_DIR", ""))
    evidence = private_empty(os.environ.get("SCHEMA_GATE_HISTORY_EVIDENCE_DIR", ""))
    scratch = private_empty(os.environ.get("SCHEMA_GATE_HISTORY_SCRATCH_DIR", ""))
    roots = [p.resolve() for p in (empty, upload, evidence, scratch)]
    if (Path.cwd() != empty or os.environ.get("TMPDIR") != str(scratch) or len(set(roots)) != 4
            or any(a != b and (a.is_relative_to(b) or b.is_relative_to(a)) for a in roots for b in roots)
            or any(p.is_relative_to(SERVER / name) for p in roots for name in ("app", "tests", "schema_migrations"))):
        refuse("separate private owned non-nested empty directories required")
    if (len(EXPECTED_FULL_IDS) != EXPECTED_CASES or len(set(EXPECTED_FULL_IDS)) != EXPECTED_CASES
            or sum(map(len, CASE_GROUPS.values())) != EXPECTED_CASES
            or set(EXPECTED_FULL_IDS) != {item for group in CASE_GROUPS.values() for item in group}):
        refuse("exact case IDs/group counts required")
    if (tree_digest(SERVER / "app", count=APP_COUNT) != APP_DIGEST
            or tree_digest(SERVER / "tests", count=TESTS_COUNT_WITHOUT_SELF, exclude_self=True) != TESTS_DIGEST
            or tree_digest(SERVER / "schema_migrations", count=SCHEMA_COUNT) != SCHEMA_DIGEST):
        refuse("full app/tests/schema source differs from approval")
    if any((SERVER / path).is_symlink() or hashlib.sha256((SERVER / path).read_bytes()).hexdigest() != wanted
           for path, wanted in SUPPORT_FILES.items()):
        refuse("support/dependency source differs from approval")
    if any((SITE / path).is_symlink() or hashlib.sha256((SITE / path).read_bytes()).hexdigest() != wanted
           for path, wanted in DRIVER_SOURCE_FILES.items()):
        refuse("source-matched driver protocol files differ from approval")
    os.umask(0o077)
    return evidence, scratch, upload, target, inventory()


def sources_unchanged():
    return (tree_digest(SERVER / "app", count=APP_COUNT) == APP_DIGEST
            and tree_digest(SERVER / "tests", count=TESTS_COUNT_WITHOUT_SELF, exclude_self=True) == TESTS_DIGEST
            and tree_digest(SERVER / "schema_migrations", count=SCHEMA_COUNT) == SCHEMA_DIGEST
            and hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == os.environ["SCHEMA_GATE_HISTORY_RUNNER_SHA256"]
            and all(hashlib.sha256((SERVER / path).read_bytes()).hexdigest() == wanted
                    for path, wanted in SUPPORT_FILES.items())
            and all(hashlib.sha256((SITE / path).read_bytes()).hexdigest() == wanted
                    for path, wanted in DRIVER_SOURCE_FILES.items()))


def require_running_approval():
    if not _RUNNING or _ACTIVE_COUNTERS is None:
        refuse("ROOT main execution envelope required before test/app imports")


def running_counters():
    require_running_approval()
    return {"pg_connect": _ACTIVE_COUNTERS["pg_connect"], "pg_sendmsg": _ACTIVE_COUNTERS["pg_sendmsg"]}


def main():
    global _RUNNING, _ACTIVE_COUNTERS
    try:
        evidence, scratch, upload, target, installed = verify_approval()
    except Exception:
        print(json.dumps({"ok": False, "phase": "schema_gate_history_source_environment_approval"}))
        return 2
    anchors = {p: (p.stat().st_dev, p.stat().st_ino, p.stat().st_uid) for p in (scratch, upload, evidence)}
    counters = dict(forbidden=[], pg_connect=0, pg_sendmsg=0, delivery={})
    controls = sendmsg_metadata_controls()
    stack = ExitStack()
    sys.path[:0] = [str(SITE), str(SERVER)]
    install_boundaries(target, counters, stack, (scratch, upload, evidence))
    signal.signal(signal.SIGALRM, lambda *_: refuse("schema gate history execution deadline exceeded"))
    signal.alarm(MAX_SECONDS)
    records = []
    failure = None
    result = None
    source_after = False
    post = None
    _RUNNING, _ACTIVE_COUNTERS = True, counters
    # Importing this helper by package name must resolve to this approved main.
    sys.modules["tests.schema_gate_history_compatibility_approved"] = sys.modules[__name__]

    def progress(case_id, detail):
        if case_id not in EXPECTED_FULL_IDS or any(row["case_id"] == case_id for row in records) or len(records) >= EXPECTED_CASES:
            refuse("unexpected or duplicate executed case ID")
        records.append({"case_id": case_id, "outcome": "passed", "detail": detail})

    async def execute():
        from types import SimpleNamespace
        from tests import schema_gate_history_preflight_cases as preflight, schema_gate_history_pg_cases as pg
        ids = (*preflight.CASE_IDS, *pg.CASE_IDS)
        if len(ids) != EXPECTED_CASES or len(set(ids)) != EXPECTED_CASES or set(ids) != set(EXPECTED_FULL_IDS):
            refuse("runtime source case registry differs from immutable approval")
        settings = SimpleNamespace(database_url=os.environ["DATABASE_URL"], managed_core_budget_enabled=True,
            managed_core_budget_expected_database=DATABASE, managed_core_budget_expected_user="clearledger")
        preflight_ids = await preflight.run(settings, scratch, progress)
        pg_result = await pg.run(settings, progress)
        import asyncpg
        from app.services.schema_version_gate import _config
        connection = await asyncpg.connect(_config(settings).dsn)
        try:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                row = await connection.fetchrow("""SELECT current_database() AS db,current_user AS usr,
                    current_setting('max_locks_per_transaction')::int AS maxlocks,
                    pg_database_size(current_database()) AS bytes,
                    (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()) AS other_clients,
                    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                     WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
                     AND c.relkind IN ('r','p','v','m','f','S')) AS relations""")
                receipt = dict(row)
                assert (receipt["db"], receipt["usr"], receipt["maxlocks"], receipt["other_clients"], receipt["relations"]) == (DATABASE, "clearledger", 64, 0, 0)
                assert receipt["bytes"] < 256 * 1024 * 1024
        finally:
            await connection.close()
        return {"preflight_completed": preflight_ids, "pg": pg_result}, receipt

    try:
        import asyncio
        result, post = asyncio.run(execute())
    except BaseException as error:
        import traceback
        raw = traceback.format_exc().replace(os.environ["DATABASE_URL"], "<synthetic-target>").replace(target.password, "<synthetic-password>")
        failure = {"type": type(error).__name__, "traceback": raw[:32000]}
    finally:
        _RUNNING = False
        try:
            source_after = sources_unchanged()
            installed_after = inventory()
            for path, anchor in anchors.items():
                scratch_bound(path, anchor)
        except Exception:
            source_after = False
            installed_after = None
        signal.alarm(0)
        stack.close()
    group_counts = {name: sum(row["case_id"] in ids for row in records) for name, ids in CASE_GROUPS.items()}
    passed = [row["case_id"] for row in records]
    ok = (failure is None and not counters["forbidden"] and counters["ipv6_probe_flag_restored"]
          and all(controls.values()) and source_after and installed_after == installed
          and len(passed) == EXPECTED_CASES and set(passed) == set(EXPECTED_FULL_IDS)
          and group_counts == {name: len(ids) for name, ids in CASE_GROUPS.items()} and post is not None
          and "app.main" not in sys.modules)
    payload = {"ok": ok, "expected_full_ids": EXPECTED_FULL_IDS, "expected_cases": EXPECTED_CASES,
        "case_results": records, "actual_group_counts": group_counts, "failure": failure,
        "result": result, "post_teardown": post, "source_after": source_after,
        "network_boundary": counters, "sendmsg_metadata_controls": controls,
        "verified_inventory_count": len(installed), "inventory_after_same": installed_after == installed,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "app_sha256": APP_DIGEST, "tests_without_self_sha256": TESTS_DIGEST, "schema_sha256": SCHEMA_DIGEST,
        "driver_source_sha256": DRIVER_SOURCE_FILES,
        "driver_protocol_scope": "exact raw JIT/typeintro protocol, normal paths only; not zero GUC statements",
        "app_main_imported": "app.main" in sys.modules,
        "startup_jobs_invoked_by_harness": False,
        "historical_scope": "immutable old gate on current strict default framework; full historical harness closure source-preserved, not rerun"}
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > 1024 * 1024:
        refuse("evidence size bound exceeded")
    with (evidence / "schema-gate-history-boundary.json").open("xb") as output:
        output.write(raw)
    print(json.dumps({"ok": ok, "passed": len(passed), "expected": EXPECTED_CASES, "source_after": source_after}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

