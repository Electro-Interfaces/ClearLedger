"""ROOT-only composed main8 candidate regression runner; source review is not execution approval.

Launch only with reviewed SHA and -I -S -B in the NEW candidate environment.
Preparation uses AST/compile only: this module was never imported by its author.
"""
import argparse
import contextvars
import errno
import asyncio
from collections import Counter
from contextlib import ExitStack
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import pwd
import re
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time
import traceback
import weakref
from urllib.parse import urlsplit

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parents[1]
SELF = Path(__file__).resolve()
OTHER_RUNNER = SERVER / 'tests/backend_upgrade_approved.py'
APPROVED_OTHER_SHA = None
CURRENT_APPROVED_SHA = None
SOURCE_BASE = '330883aaf8e387e106e93d790806a182acbe526d'
FROZEN_COUNTS = {'app': 492, 'tests': 345, 'schema_migrations': 16}
CANDIDATE = Path('/srv/projects/api-modernization-upgrade-test-env-20261030/.venv')
SITE = CANDIDATE / 'lib/python3.13/site-packages'
RUN = REPO / '.artifacts/backend-upgrade-composed-main8-execution-20261030-attempt2'
EMPTY, UPLOAD, EVIDENCE = (RUN / n for n in ('main8-empty-test', 'main8-test-uploads', 'main8-test-evidence'))
DSN = 'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_partner_main_test_20261030'
RAW_DSN = DSN.replace('postgresql+asyncpg:', 'postgresql:', 1)
DATABASE = 'api_partner_main_test_20261030'
LIMIT_LOG = 2 * 1024 * 1024
LIMIT_SCRATCH = 64 * 1024 * 1024
DEADLINE = 540
# Filled from source bytes and accepted ROOT receipts, not imports/collection.
FROZEN_TREES = {'app': '748c5eda4d956dc73771aa84462c6bc789d80cbdcddc0b86825e141f04a8c3c0', 'tests': '08ae0ee2ed47661fe8d6d5dc89fab61641fbeccb49fa3cbf76e82a7b4dd5f0a9', 'schema_migrations': 'c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e'}
FROZEN_FILES = {'.dockerignore': '219f4861afde083e955dccd850e20ac3f86a4d3b51164c484e7fca1620490d6a', 'Dockerfile': 'aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d', 'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'requirements-upgrade-20261030.in': '90e92d607c5f3c966f5dca129461d92fdfc2a094e5b3a77e5e211ad5dc4d8caf', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601', 'locks/bootstrap-py313-linux-amd64.provisional.txt': '551e3fb88d8fda035c0d8a2f38c7b08e29b4798d9bad0bfc8d42f5a3c3a8200f', 'locks/bootstrap-upgrade-20261030-py313-linux-amd64.provisional.txt': 'b41fd964893071eb489e01e85256f471764997721fe151eaf08684bfb12a87b8', 'locks/dependency-artifacts-py313-linux-amd64.json': '3390cbfaa680b9bb970ce43e8d3e32014230908c46fd9e7b1d4464c7cf7365ee', 'locks/dependency-artifacts-upgrade-py313-linux-amd64-20261030.json': '8711de6afb6bc461718851a537c2456ea9b1f68b2f4236f3de599df561493b7f', 'locks/derived-http-ece-py313-linux-amd64.provisional.json': '84596a3ebfce149db956cc750006eeb55871c80b41d40207cfe29fb0d8961d83', 'locks/runtime-baseline.constraints.txt': '0ffe95bf719106fc03b76fc8ec2627173e574ee32b974660b7aadc7561e4f6f8', 'locks/runtime-py313-linux-amd64.provisional.txt': '3b17a7566f0519b7f056697975ed2216e01de5d99972cc882b678be2696cd3d1', 'locks/runtime-upgrade-20261030-py313-linux-amd64.provisional.txt': 'a9b060f941cda22fab721522eb68f717711c55f17dbbdc83fae169a8e0fbf2bc', 'locks/runtime-upgrade-20261030.constraints.txt': '0df586ccfd455936da34929fd32ded0c241b0bf3befad06e83b0be61c94ebfce', 'locks/tooling-py313-linux-amd64.provisional.txt': '9e9d2d3d92273c607c2acba679d1d08b3cefa3102583718eade5f665a1c99d80', 'locks/tooling-upgrade-20261030-py313-linux-amd64.provisional.txt': '554fc211ee0ed4e88a2136029781308ac4d820b33ec60fcc242b88a556c33162'}
RUNTIME_WITH_PIP = {'aiofiles': '24.1.0', 'aiohappyeyeballs': '2.7.1', 'aiohttp': '3.14.5', 'aiosignal': '1.4.0', 'aiosmtplib': '5.1.3', 'annotated-doc': '0.0.2', 'annotated-types': '0.8.0', 'anyio': '4.15.1', 'asyncpg': '0.30.0', 'attrs': '26.1.0', 'authlib': '1.9.1', 'bcrypt': '4.2.1', 'certifi': '2026.10.23', 'cffi': '2.1.1', 'charset-normalizer': '3.5.2', 'click': '8.5.0', 'cryptography': '50.0.2', 'dnspython': '2.9.1', 'email-validator': '2.3.0', 'et-xmlfile': '2.0.0', 'fastapi': '0.133.0', 'frozenlist': '1.8.0', 'greenlet': '3.5.6', 'gunicorn': '23.0.0', 'h11': '0.16.0', 'http-ece': '1.2.1', 'httpcore': '1.0.9', 'httptools': '0.9.0', 'httpx': '0.28.1', 'idna': '3.20', 'joserfc': '1.7.7', 'lxml': '6.1.3', 'multidict': '7.2.1', 'openpyxl': '3.1.5', 'packaging': '26.3', 'passlib': '1.7.4', 'pip': '26.2.2', 'propcache': '0.5.4', 'py-vapid': '1.9.6', 'pycparser': '3.12', 'pydantic': '2.14.2', 'pydantic-core': '2.50.2', 'pydantic-settings': '2.7.1', 'pyjwt': '2.15.0', 'pypdf': '6.21.2', 'python-docx': '1.1.2', 'python-dotenv': '1.2.2', 'python-multipart': '0.0.31', 'pywebpush': '2.5.0', 'pyyaml': '6.0.3', 'requests': '2.34.2', 'sqlalchemy': '2.0.36', 'starlette': '1.3.1', 'typing-extensions': '4.16.0', 'typing-inspection': '0.4.4', 'urllib3': '2.8.0', 'uvicorn': '0.34.0', 'uvloop': '0.23.0', 'watchfiles': '1.3.0', 'websockets': '17.3', 'yarl': '1.25.1'}
TEST_TOOLS = {'iniconfig': '2.3.1', 'jsonschema': '4.26.0', 'jsonschema-path': '0.5.0', 'jsonschema-specifications': '2025.9.1', 'lazy-object-proxy': '1.13.0', 'openapi-schema-validator': '0.9.0', 'openapi-spec-validator': '0.9.0', 'pathable': '0.6.0', 'pluggy': '1.7.0', 'pygments': '2.21.0', 'pytest': '9.2.0', 'pytest-asyncio': '1.4.1', 'referencing': '0.37.0', 'rfc3339-validator': '0.1.4', 'rpds-py': '2026.9.1', 'six': '1.17.0'}

SELECTION = ('test_main_problem_request_id_matches_outer_security_context', 'test_standalone_child_unavailable_problem_request_id_without_sql', 'test_main_mount_order_anonymous_docs_and_version_guards', 'test_ordinary_employee_scoped_entities_refresh_and_revoke', 'test_ordinary_employee_document_eligibility_denial_is_not_owner_consent', 'test_explicit_docs_role_employee_allowed_bytes_hidden_and_foreign_404', 'test_main_swagger_canonical_projection_assets_session_csrf_and_live_revoke', 'test_main_confidential_registration_admin_machine_grant_and_live_revoke')
EXPECTED_CASES = {'test_partner_main_composition.py': 8}
AFFECTED_SELECTION = ('test_ordinary_employee_scoped_entities_refresh_and_revoke', 'test_ordinary_employee_document_eligibility_denial_is_not_owner_consent', 'test_explicit_docs_role_employee_allowed_bytes_hidden_and_foreign_404', 'test_main_swagger_canonical_projection_assets_session_csrf_and_live_revoke', 'test_main_confidential_registration_admin_machine_grant_and_live_revoke')
FLAG = 'RUN_PARTNER_MAIN_COMPOSITION_TESTS'
ISSUER = 'https://m18-space.example.invalid'
SECRET = 'm18-synthetic-core-secret-never-production-20261030'
SCHEDULERS = ('channel_scheduler', 'pulse_digest', 'task_scheduler', 'mail_poller', 'store_price_scheduler', 'onec_read_scheduler', 'space_projection_scheduler', 'intake_watch')
PREPARATION_RECEIPTS = {'runtime-prepare-proof.json': 'abbd7b18db3ba39bc18ad6ded7158347e8964af1126128472f9b9868a8863a42', 'test-tools-prepare-proof.json': 'f183375c1a42089673fe47824868e0670874aa3a884a32c0a3296cd5990bfe39'}
FORBIDDEN_COUNTERS = ('blocked_network', 'blocked_subprocess', 'denied_env_reads')
SENDER_COUNTS = {}
AUDIT_DIAGNOSTICS = []
IMPORT_CAPABILITY_PROOF = {}
BOUNDARY = {'blocked_network': 0, 'allowed_pg_connects': 0, 'blocked_subprocess': 0,
            'denied_env_reads': 0, 'db_connections': 0, 'allowed_pg_sendmsg': 0}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root):
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob('*')):
        raise RuntimeError('M18 source files/directories must not be symlinks')
    paths = [p for p in sorted(root.rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts and p not in {SELF, OTHER_RUNNER}]
    if root.name in FROZEN_COUNTS and len(paths) != FROZEN_COUNTS[root.name]:
        raise RuntimeError('Frozen exact source file count mismatch')
    if len(paths) > 1024 or sum(p.stat().st_size for p in paths) > 32 * 1024 * 1024:
        raise RuntimeError('Source tree exceeds approved bounds')
    if any(p.is_symlink() for p in paths):
        raise RuntimeError('Source symlinks prohibited')
    value = '\n'.join(str(p.relative_to(root)) + '\0' + sha(p) for p in paths) + '\n'
    return hashlib.sha256(value.encode()).hexdigest()


def source_guard(approved_sha):
    if not re.fullmatch('[0-9a-f]{64}', approved_sha) or sha(SELF) != approved_sha:
        raise RuntimeError('Runner SHA does not match independent ROOT approval')
    if (not isinstance(APPROVED_OTHER_SHA, str) or
            not re.fullmatch('[0-9a-f]{64}', APPROVED_OTHER_SHA) or
            OTHER_RUNNER.is_symlink() or sha(OTHER_RUNNER) != APPROVED_OTHER_SHA):
        raise RuntimeError('Other owned entrypoint SHA lacks independent ROOT approval')
    for name, expected in FROZEN_TREES.items():
        if tree_digest(SERVER / name) != expected:
            raise RuntimeError('Frozen complete source tree mismatch: ' + name)
    for name, expected in FROZEN_FILES.items():
        if sha(SERVER / name) != expected:
            raise RuntimeError('Frozen source/input mismatch: ' + name)


def no_env_files():
    # Inspect existence only. Never read .env content, even on a failed guard.
    candidates = {p / '.env' for root in (Path.cwd(), SERVER, RUN)
                  for p in (root, *root.parents)}
    if any(p.exists() or p.is_symlink() for p in candidates):
        raise RuntimeError('An ancestor .env exists; refuse before imports')


def inventory():
    if not SITE.is_dir() or SITE.is_symlink():
        raise RuntimeError('Candidate site missing or symlinked')
    cfg = (CANDIDATE / 'pyvenv.cfg').read_text()
    if not re.search(r'^include-system-site-packages\s*=\s*false\s*$', cfg, re.M):
        raise RuntimeError('Candidate must exclude system site')
    for p in SITE.rglob('*'):
        if p.suffix == '.pth' or p.name in {'sitecustomize.py', 'usercustomize.py'} or p.is_symlink():
            raise RuntimeError('Candidate import hook/symlink prohibited')
    for name, expected in PREPARATION_RECEIPTS.items():
        if sha(CANDIDATE.parent / name) != expected:
            raise RuntimeError('ROOT preparation receipt mismatch')
    packages = {}
    for dist in importlib.metadata.distributions(path=[str(SITE)]):
        name = re.sub('[-_.]+', '-', dist.metadata['Name']).lower()
        if name in packages:
            raise RuntimeError('Duplicate candidate distribution')
        packages[name] = dist.version
    if len(RUNTIME_WITH_PIP) != 61 or len(TEST_TOOLS) != 16 or set(RUNTIME_WITH_PIP) & set(TEST_TOOLS):
        raise RuntimeError('Invalid frozen inventory contract')
    if packages != {**RUNTIME_WITH_PIP, **TEST_TOOLS}:
        raise RuntimeError('Exact runtime61 + separate testtools16 inventory required')
    return packages


def interpreter_guard():
    if (sys.version_info[:3] != (3, 13, 7) or not sys.flags.isolated or not sys.flags.no_site
            or sys.flags.optimize or not sys.dont_write_bytecode or os.confstr('CS_GNU_LIBC_VERSION') != 'glibc 2.36'
            or Path(sys.executable).absolute().parent != CANDIDATE / 'bin'):
        raise RuntimeError('Exact NEW host candidate Python3.13.7/glibc2.36 -I -S -B required')
    if any(str(SITE) == p or '/site-packages' in p or p in {'', str(SERVER)} for p in sys.path):
        raise RuntimeError('Third-party/current-directory path present before boundary checks')
    if 'pytest' in sys.modules or 'app' in sys.modules or 'site' in sys.modules:
        raise RuntimeError('Site/pytest/app already imported')
    if os.environ.get('HOME') != pwd.getpwuid(os.getuid()).pw_dir:
        raise RuntimeError('Preserve actual account HOME')


def write_json(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    if len(data) > LIMIT_LOG:
        raise RuntimeError('Evidence exceeds bound')
    temp = path.with_name('.' + path.name + '.atomic-tmp')
    # Exact private sibling, exclusive/no-follow; replace commits a complete JSON.
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def owned_scratch_bytes(root, expected_anchor):
    """Reviewed target-driver ENOENT-only live-child policy, with exact root identity."""
    root = Path(root)
    anchor = root.lstat()  # A missing root, symlink, permission error or drift always fails.
    identity = lambda info: (info.st_dev, info.st_ino, info.st_uid)
    if (not stat.S_ISDIR(anchor.st_mode) or anchor.st_uid != os.geteuid()
            or anchor.st_mode & 0o077 or identity(anchor) != expected_anchor):
        raise RuntimeError('Owned scratch anchor identity mismatch')
    def vanished(exc, path):
        return (isinstance(exc, FileNotFoundError) and exc.errno == errno.ENOENT
                and path != root and path.is_relative_to(root) and exc.filename is not None
                and Path(exc.filename) == path)
    def walk_error(exc):
        if exc.filename is not None and vanished(exc, Path(exc.filename)):
            return
        raise exc
    size, count = 0, 0
    for parent, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in directories + files:
            path = Path(parent) / name
            if path == root or not path.is_relative_to(root):
                raise RuntimeError('Scratch entry outside exact owned anchor')
            count += 1  # Even vanished entries/symlinks count toward the upper bound.
            if count > 4096:
                raise RuntimeError('Scratch 4096-entry bound')
            try:
                info = path.lstat()
            except OSError as exc:
                if vanished(exc, path):
                    continue
                raise
            # Do not follow symlinks; negative file-policy fixtures intentionally create them/FIFOs.
            if stat.S_ISREG(info.st_mode):
                size += info.st_size
                if size > LIMIT_SCRATCH:
                    raise RuntimeError('Scratch 64MiB bound')
    after = root.lstat()
    if not stat.S_ISDIR(after.st_mode) or identity(after) != expected_anchor:
        raise RuntimeError('Owned scratch anchor changed during observation')
    return size


def safe_failure_text(report, available):
    # Pytest --tb=short, without showlocals; retain bounded synthetic-source trace only.
    text = report.longreprtext
    text = re.sub(r'([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+(?::[^/@\s]*)?@', r'\1[redacted]@', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[redacted-jwt]', text)
    text = re.sub(r'(?i)(authorization|password|secret|access_token|refresh_token)([\"\' ]*[:=][\"\' ]*)[^\s,}]+', r'\1\2[redacted]', text)
    raw = text.encode('utf-8')
    limit = min(16384, max(0, available))
    result = raw[:limit].decode('utf-8', errors='ignore')
    return result, len(raw) > limit


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


def install_boundaries():
    # Weak object ownership plus original fd prevents closed/detached/fd-reused sockets.
    owned_pg_sockets = weakref.WeakKeyDictionary()
    active_sendmsg = contextvars.ContextVar('approved_pg_sendmsg', default=None)
    native_sendmsg = socket.socket.sendmsg
    native_fileno = socket.socket.fileno
    native_peer = socket.socket.getpeername
    native_type = socket.socket.getsockopt
    def diagnostic(event):
        if len(AUDIT_DIAGNOSTICS) >= 32:
            return
        stack = traceback.StackSummary.extract(traceback.walk_stack(None), limit=12, lookup_lines=False)
        def safe_file(filename):
            path = Path(filename)
            if path.is_relative_to(SERVER):
                return 'server/' + str(path.relative_to(SERVER))
            if path.is_relative_to(SITE):
                return 'site/' + str(path.relative_to(SITE))
            return path.name
        AUDIT_DIAGNOSTICS.append({'event': event, 'stack': [
            {'file': safe_file(frame.filename), 'function': frame.name, 'line': frame.lineno}
            for frame in stack]})
    def owned_stream_allowed(sock, extra_args=(), extra_kwargs=None):
        try:
            return pg_sendmsg_metadata_allowed(
                sock.family, native_type(sock, socket.SOL_SOCKET, socket.SO_TYPE), sock.proto,
                owned_pg_sockets.get(sock), native_fileno(sock),
                native_peer(sock) == ('127.0.0.1', 33546), extra_args,
                {} if extra_kwargs is None else extra_kwargs)
        except (OSError, TypeError, AttributeError):
            return False
    def audit(event, args):
        if event == 'socket.connect':
            sock, address = args
            if sock.family not in (socket.AF_INET, socket.AF_INET6) or address != ('127.0.0.1', 33546):
                diagnostic(event)
                BOUNDARY['blocked_network'] += 1
                raise RuntimeError('Only approved PostgreSQL loopback socket allowed')
            BOUNDARY['allowed_pg_connects'] += 1
            if (sock.family == socket.AF_INET and native_type(sock, socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM
                    and sock.proto in (0, socket.IPPROTO_TCP)):
                owned_pg_sockets[sock] = native_fileno(sock)
        elif event == 'socket.sendmsg':
            active = active_sendmsg.get()
            if (active is None or len(args) != 2 or args[0] is not active[0] or args[1] is not None
                    or sys._getframe(1).f_code is not exact_pg_sendmsg.__code__
                    or not owned_stream_allowed(args[0])
                    or native_fileno(args[0]) != active[1]
                    or owned_pg_sockets.get(args[0]) != active[1]):
                diagnostic(event)
                BOUNDARY['blocked_network'] += 1
                raise RuntimeError('Unapproved sendmsg context')
            BOUNDARY['allowed_pg_sendmsg'] += 1
        elif event in {'socket.bind', 'socket.sendto', 'socket.gethostbyname', 'socket.gethostbyaddr'}:
            diagnostic(event)
            BOUNDARY['blocked_network'] += 1
            raise RuntimeError('No listeners/datagrams in candidate tests')
        elif event == 'socket.getaddrinfo':
            if args[0] != '127.0.0.1' or int(args[1]) != 33546:
                diagnostic(event)
                BOUNDARY['blocked_network'] += 1
                raise RuntimeError('External DNS prohibited')
        elif event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork', 'os.forkpty'}:
            diagnostic(event)
            BOUNDARY['blocked_subprocess'] += 1
            raise RuntimeError('Subprocesses prohibited inside test child')
        elif event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0]))
            if (path.name == '.env' or path.name.startswith('.env.')
                    or {'.ssh', '.vault', '.claude'}.intersection(path.parts)):
                diagnostic(event)
                BOUNDARY['denied_env_reads'] += 1
                raise RuntimeError('Reading .env prohibited')
    def exact_pg_sendmsg(sock, buffers, *extra_args, **extra_kwargs):
        allowed = owned_stream_allowed(sock, extra_args, extra_kwargs)
        if not allowed:
            diagnostic('socket.sendmsg-policy-denied')
            BOUNDARY['blocked_network'] += 1
            raise RuntimeError('Only an owned connected PG stream with buffer-only sendmsg is allowed')
        token = active_sendmsg.set((sock, native_fileno(sock)))
        try:
            # No ancillary data, flags or address are ever forwarded, even explicit empty/default options.
            return native_sendmsg(sock, buffers)
        finally:
            active_sendmsg.reset(token)
    sys.addaudithook(audit)
    # Low-level socket restriction remains even if a test replaces an HTTP seam.
    # ROOT-approved isolation of urllib3's import-only IPv6 bind capability probe.
    # No bind is allowed: report IPv6 unavailable during exactly these imports.
    # Restore the exact old flag before all later application imports/fixtures.
    ipv6_before = socket.has_ipv6
    try:
        socket.has_ipv6 = False
        import aiohttp
        import aiosmtplib
        import httpx
        import pywebpush
        import requests
    finally:
        socket.has_ipv6 = ipv6_before
        IMPORT_CAPABILITY_PROOF.update(
            scope=['aiohttp', 'aiosmtplib', 'httpx', 'pywebpush', 'requests'],
            suppressed=True, restored=socket.has_ipv6 is ipv6_before,
            old_value=ipv6_before, bind_allowance=False)
    import smtplib
    stack = ExitStack()
    def captured(label, result=None, *, asynchronous=False):
        SENDER_COUNTS[label] = 0
        def call(*args, **kwargs):
            SENDER_COUNTS[label] += 1
            return result
        async def acall(*args, **kwargs):
            return call(*args, **kwargs)
        return acall if asynchronous else call
    def deny(*args, **kwargs):
        diagnostic('blocked-external-transport')
        BOUNDARY['blocked_network'] += 1
        raise RuntimeError('External sender blocked')
    async def adeny(*args, **kwargs):
        return deny(*args, **kwargs)
    from unittest.mock import patch
    stack.enter_context(patch.object(socket.socket, 'listen', deny))
    stack.enter_context(patch.object(socket.socket, 'sendmsg', exact_pg_sendmsg))
    for owner, name, replacement in (
        (aiosmtplib, 'send', captured('smtp.aiosmtplib.send', asynchronous=True)),
        (aiosmtplib.SMTP, 'connect', captured('smtp.aiosmtplib.connect', asynchronous=True)),
        (smtplib.SMTP, 'connect', captured('smtp.smtplib.connect', (421, 'synthetic delivery disabled'))),
        (smtplib.SMTP_SSL, 'connect', captured('smtp.smtplib.ssl_connect', (421, 'synthetic delivery disabled'))),
        (smtplib.SMTP, 'sendmail', captured('smtp.smtplib.sendmail', {})),
        (smtplib.SMTP, 'send_message', captured('smtp.smtplib.send_message', {})),
        (pywebpush, 'webpush', captured('push.pywebpush.webpush')),
        (requests.sessions.Session, 'request', deny),
        (httpx.HTTPTransport, 'handle_request', deny),
        (httpx.AsyncHTTPTransport, 'handle_async_request', adeny),
        (aiohttp.ClientSession, '_request', adeny),
    ):
        stack.enter_context(patch.object(owner, name, replacement))
    import asyncpg
    actual_connect = asyncpg.connect
    async def connect(dsn=None, **kwargs):
        if dsn is not None:
            target = urlsplit(dsn)
            if (target.scheme not in {'postgres', 'postgresql'} or target.hostname != '127.0.0.1'
                    or target.port != 33546 or target.path != '/' + DATABASE
                    or target.username != 'clearledger' or target.password != 'api_test_only'
                    or target.query or target.fragment):
                raise RuntimeError('Unapproved SQL target')
        allowed_target = {'host': '127.0.0.1', 'port': 33546, 'database': DATABASE,
                          'user': 'clearledger', 'password': 'api_test_only'}
        if dsn is None and any(kwargs.get(k) != v for k, v in allowed_target.items()):
            raise RuntimeError('SQL keyword target mismatch')
        if dsn is not None and any(k in kwargs and kwargs[k] != v for k, v in allowed_target.items()):
            raise RuntimeError('SQL target override prohibited')
        settings = dict(kwargs.get('server_settings') or {})
        settings.update(statement_timeout='30000', lock_timeout='1000',
                        idle_in_transaction_session_timeout='30000')
        kwargs['server_settings'] = settings
        kwargs['timeout'] = min(kwargs.get('timeout', 10), 10)
        kwargs['command_timeout'] = min(kwargs.get('command_timeout', 30), 30)
        con = await actual_connect(dsn, **kwargs)
        try:
            if (await con.fetchval('SELECT current_database()') != DATABASE
                    or await con.fetchval('SELECT current_user') != 'clearledger'):
                raise RuntimeError('Connected SQL identity mismatch')
        except BaseException:
            await con.close()
            raise
        BOUNDARY['db_connections'] += 1
        return con
    stack.enter_context(patch.object(asyncpg, 'connect', connect))
    return stack


async def database_preflight():
    import asyncpg
    con = await asyncpg.connect(RAW_DSN, timeout=5, command_timeout=10)
    try:
        count = await con.fetchval("""SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
            AND c.relkind IN ('r','p','v','m','S','f')""")
        if count or await con.fetchval("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"):
            raise RuntimeError('Dedicated approved database must be empty and exclusive')
        if await con.fetchval('SELECT pg_database_size(current_database())') > 256 * 1024 * 1024:
            raise RuntimeError('Database size bound exceeded')
    finally:
        await con.close()


def child(approved_sha, profile):
    interpreter_guard()
    source_guard(approved_sha)
    no_env_files()
    if Path.cwd() != EMPTY or any(EMPTY.iterdir()) or any(UPLOAD.iterdir()):
        raise RuntimeError('Fresh empty cwd/upload required before imports')
    if any(p.stat().st_mode & 0o077 for p in (RUN, EMPTY, UPLOAD, EVIDENCE)):
        raise RuntimeError('Private directories required')
    expected_env = clean_environment()
    if dict(os.environ) != expected_env:
        raise RuntimeError('Exact scrubbed environment required')
    for directory in (EMPTY, UPLOAD, EVIDENCE):
        if (not directory.is_absolute() or '..' in directory.parts
                or any(parent.is_symlink() for parent in (directory, *directory.parents))
                or directory.stat().st_uid != os.getuid()
                or directory.stat().st_mode & 0o777 != 0o700 or 'test' not in directory.name):
            raise RuntimeError('M18 requires exact fresh owned private test directories')
    if len({directory.resolve() for directory in (EMPTY, UPLOAD, EVIDENCE)}) != 3:
        raise RuntimeError('M18 test directories must be distinct')
    entries = list(EVIDENCE.iterdir())
    log = EVIDENCE / 'run.log'  # Opened empty by the independent parent supervisor only.
    if entries != [log] or log.is_symlink() or log.stat().st_size != 0:
        raise RuntimeError('M18 evidence was not fresh before child startup')
    packages = inventory()
    write_json(EVIDENCE / 'pre-import-boundary.json', {
        'runner_sha256': approved_sha, 'source_trees': FROZEN_TREES, 'source_counts': FROZEN_COUNTS,
        'source_base': SOURCE_BASE, 'other_runner_sha256': APPROVED_OTHER_SHA,
        'runtime61': RUNTIME_WITH_PIP, 'test_tools16': TEST_TOOLS,
        'python': '3.13.7', 'glibc': '2.36', 'flags': ['-I', '-S', '-B'],
        'environment_keys': sorted(os.environ), 'home_preserved': True,
        'cwd_and_upload_empty': True, 'no_env_files': True,
        'no_app_pytest_site_imported': True})
    # Only now add verified distributions and frozen application sources.
    sys.path[:0] = [str(SERVER), str(SITE)]
    resource.setrlimit(resource.RLIMIT_CPU, (600, 610))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT_LOG, LIMIT_LOG))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    signal.signal(signal.SIGALRM, lambda *_: sys.exit('M18 540s execution bound exceeded'))
    signal.alarm(540)
    selection = SELECTION if profile == 'main8' else AFFECTED_SELECTION
    cases = {'test_partner_main_composition.py': len(selection)}
    controls = sendmsg_metadata_controls()
    record = {'profile': profile, 'main8_accepted': False, 'affected5_accepted': False,
              'sendmsg_metadata_controls': controls, 'status': 'starting', 'python': '3.13.7', 'glibc': '2.36', 'runner_sha256': approved_sha,
              'inventory': packages, 'runtime_count': 61, 'test_tool_count': 16,
              'home_preserved': True, 'no_site_before_guards': True, 'no_env_files': True,
              'source_trees': FROZEN_TREES, 'source_counts': FROZEN_COUNTS,
              'source_base': SOURCE_BASE, 'other_runner_sha256': APPROVED_OTHER_SHA, 'sql_target': DATABASE}
    code = 2
    try:
        with install_boundaries():
            if not (IMPORT_CAPABILITY_PROOF.get('suppressed') is True and
                    IMPORT_CAPABILITY_PROOF.get('restored') is True):
                raise RuntimeError('Import capability isolation/restore proof required')
            asyncio.run(database_preflight())
            import pytest
            evidence = EVIDENCE
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
                    record['collected'] = dict(Counter(Path(item.path).name for item in items))
                    record['nodeids'] = [item.nodeid for item in items]
                    if (len(items) != len(selection) or {item.name for item in items} != set(selection)
                            or any(Path(item.path).name != 'test_partner_main_composition.py' for item in items)):
                        raise pytest.UsageError('Exact unchanged M18 profile selection required')

                def pytest_runtest_logreport(self, report):
                    if report.when == 'call' or report.failed or report.skipped:
                        outcome = ('xpassed' if report.passed else 'xfailed') if hasattr(report, 'wasxfail') else report.outcome
                        self.results.append({'nodeid': report.nodeid, 'when': report.when, 'outcome': outcome})
                        record.setdefault('outcomes', {})[report.nodeid] = outcome
                    if report.failed:
                        used = record.get('failure_text_bytes', 0)
                        trace, truncated = safe_failure_text(report, 1024 * 1024 - used)
                        record['failure_text_bytes'] = used + len(trace.encode('utf-8'))
                        record.setdefault('failures', {})[report.nodeid + '::' + report.when] = {
                            'when': report.when, 'trace': trace, 'truncated': truncated}
                    record.update(checkpoint_complete=False, last_report_phase=report.when,
                                  boundary=dict(BOUNDARY), sender_counts=dict(self.counts),
                                  audit_diagnostics=list(AUDIT_DIAGNOSTICS),
                                  import_capability_proof=dict(IMPORT_CAPABILITY_PROOF))
                    write_json(evidence / 'outcome-checkpoint.json', record)

                def pytest_sessionfinish(self, session, exitstatus):
                    unexpected = {k: v for k, v in self.counts.items() if k not in
                                  {"startup.prepare", "chat_ws.start", "chat_ws.stop", "notify.dispatch_async",
                                   *["scheduler." + n for n in SCHEDULERS]}}
                    expected_lifecycle = {"startup.prepare": 1, "chat_ws.start": 1, "chat_ws.stop": 1,
                                          "notify.dispatch_async": 8,
                                          **{"scheduler." + n: 1 for n in SCHEDULERS}}
                    outcomes = [(r["when"], r["outcome"]) for r in self.results]
                    exact_outcomes = sum(when == "call" and outcome in {"passed", "failed"}
                                         for when, outcome in outcomes) == len(selection) and len(outcomes) == len(selection)
                    if (any(BOUNDARY[name] for name in FORBIDDEN_COUNTERS) or unexpected
                            or self.counts != expected_lifecycle or not exact_outcomes
                            or len(self.jobs) != 8 or not all(job.cancelled() for job in self.jobs)):
                        session.exitstatus = 1
                    record['m18_lifecycle_accepted'] = not (
                        unexpected or self.counts != expected_lifecycle or not exact_outcomes
                        or len(self.jobs) != 8 or not all(job.cancelled() for job in self.jobs))
                    record['m18_counts'] = dict(self.counts)
                    record['m18_jobs_cancelled'] = len(self.jobs) == 8 and all(job.cancelled() for job in self.jobs)
                    write_json(evidence / 'm18-boundary.json', {
                        'network_process_attempts': dict(BOUNDARY), 'capture_counts': self.counts,
                        'unexpected_delivery_counts': unexpected, 'expected_lifecycle_counts': expected_lifecycle,
                        'results': self.results, 'full_main_asgi': True, 'nginx_browser_sso': False,
                        'parked_jobs': len(self.jobs), 'all_jobs_cancelled': record['m18_jobs_cancelled'],
                        'source_scope': f'accepted composed source on new runtime; {profile}; {len(selection)} distinct cases'})


                def pytest_unconfigure(self, config):
                    self.patch.undo()

            boundary = Boundary()
            argv = ['-c', str(SERVER / 'pytest.ini'), '--rootdir=' + str(SERVER),
                    '--confcutdir=' + str(SERVER), '--import-mode=importlib', '-p', 'pytest_asyncio.plugin',
                    '-p', 'no:cacheprovider', '--noconftest', '--show-capture=no', '--basetemp=' + str(EMPTY / 'pytest-test-temp'),
                    '--junitxml=' + str(EVIDENCE / 'junit.xml'), '--tb=short', '-q',
                    *[str(SERVER / 'tests/test_partner_main_composition.py') + '::' + name for name in selection]]
            code = int(pytest.main(argv, plugins=[boundary]))
            record['pytest_exit'] = code
            if not record.get('m18_lifecycle_accepted'):
                code = code or 6
            outcomes = record.get('outcomes', {})
            # A zero exit with missing/skip/xfail cases is not accepted.
            if len(outcomes) != sum(cases.values()) or set(outcomes.values()) != {'passed'}:
                code = code or 3
            source_guard(approved_sha)
            import asyncpg
            async def final_database_bounds():
                con = await asyncpg.connect(RAW_DSN, timeout=5)
                try:
                    size = await con.fetchval('SELECT pg_database_size(current_database())')
                    if size > 256 * 1024 * 1024:
                        raise RuntimeError('Final database size bound exceeded')
                    return size
                finally:
                    await con.close()
            record['final_database_bytes'] = asyncio.run(final_database_bounds())
    except BaseException as exc:
        code = 2
        record['failure_type'] = type(exc).__name__
    finally:
        signal.alarm(0)
        if any(value != 0 for value in SENDER_COUNTS.values()):
            code = code or 7
        if any(BOUNDARY[name] != 0 for name in FORBIDDEN_COUNTERS):
            code = code or 4
        if os.environ.get('HOME') != pwd.getpwuid(os.getuid()).pw_dir:
            code = code or 5
        record.update(status='PASS' if code == 0 else 'FAIL',
                      main8_accepted=profile == 'main8' and code == 0,
                      affected5_accepted=profile == 'affected5' and code == 0, boundary=dict(BOUNDARY),
                      sender_counts=dict(record.get('m18_counts', {})),
                      transport_stub_counts=dict(SENDER_COUNTS), audit_diagnostics=list(AUDIT_DIAGNOSTICS),
                      import_capability_proof=dict(IMPORT_CAPABILITY_PROOF),
                      ipv6_import_probe_suppressed=IMPORT_CAPABILITY_PROOF.get('suppressed') is True,
                      home_preserved=os.environ.get('HOME') == pwd.getpwuid(os.getuid()).pw_dir)
        write_json(EVIDENCE / 'boundary-proof.json', record)
    return code


def clean_environment():
    return {'HOME': pwd.getpwuid(os.getuid()).pw_dir, 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
            'APP_ENV': 'test', 'HOSTNAME': 'backend-upgrade-main8-test', 'SECRET_KEY': SECRET,
            'DATABASE_URL': DSN, 'TEST_DATABASE_URL': DSN, 'UPLOAD_DIR': str(UPLOAD),
            'TMPDIR': str(EMPTY), 'PYTHONDONTWRITEBYTECODE': '1',
            'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'RUN_PARTNER_MAIN_COMPOSITION_TESTS': '1',
            'ROOT_APPROVED_PARTNER_MAIN_COMPOSITION': '1', 'M18_PG_PORT': '33546',
            'M18_EMPTY_CWD': str(EMPTY), 'M18_EVIDENCE_DIR': str(EVIDENCE),
            'M18_RUNNER_SHA256': CURRENT_APPROVED_SHA}


def supervise(approved_sha, profile):
    interpreter_guard()
    source_guard(approved_sha)
    no_env_files()
    inventory()
    if os.environ.get('ROOT_BACKEND_UPGRADE_REVIEWED') != '1':
        raise RuntimeError('Separate ROOT execution decision required')
    if RUN.exists() or RUN.is_symlink():
        raise RuntimeError('Execution directory must be fresh; preserve old evidence')
    RUN.mkdir(mode=0o700)
    for directory in (EMPTY, UPLOAD, EVIDENCE):
        directory.mkdir(mode=0o700)
    anchor = RUN.lstat()
    anchor_identity = (anchor.st_dev, anchor.st_ino, anchor.st_uid)
    selection = SELECTION if profile == 'main8' else AFFECTED_SELECTION
    cases = {'test_partner_main_composition.py': len(selection)}
    argv = [str(CANDIDATE / 'bin/python'), '-I', '-S', '-B', str(SELF),
            '--approved-sha256', approved_sha, '--approved-other-sha256', APPROVED_OTHER_SHA, '--profile', profile, '--root-reviewed-child']
    started = time.monotonic()
    proc = subprocess.Popen(argv, cwd=EMPTY, env=clean_environment(), start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    reason = None
    size = 0
    child_exit = None
    with (EVIDENCE / 'run.log').open('xb') as log, selectors.DefaultSelector() as poll:
        poll.register(proc.stdout, selectors.EVENT_READ)
        try:
            while poll.get_map():
                if time.monotonic() - started > DEADLINE:
                    raise RuntimeError('Global M18 540s deadline')
                owned_scratch_bytes(RUN, anchor_identity)
                for key, _ in poll.select(timeout=0.25):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        poll.unregister(key.fileobj)
                        continue
                    if size + len(data) > LIMIT_LOG:
                        raise RuntimeError('Aggregate log 2MiB bound')
                    size += len(data)
                    log.write(data)
            child_exit = proc.wait(timeout=max(1, DEADLINE - (time.monotonic() - started)))
        except BaseException as exc:
            reason = type(exc).__name__ + ': ' + str(exc)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)
            proc.stdout.close()
    # Do not delete fresh dirs/DB after failure: ROOT owns review and cleanup.
    junit = EVIDENCE / 'junit.xml'
    proof = EVIDENCE / 'boundary-proof.json'
    accepted = child_exit == 0 and reason is None and junit.is_file() and proof.is_file()
    try:
        if accepted:
            from xml.etree import ElementTree
            suites = ElementTree.parse(junit).getroot()
            cases = suites.findall('.//testcase')
            accepted = (len(cases) == len(selection) and
                    not any(suites.findall('.//' + k) for k in ('failure', 'error', 'skipped')) and
                    json.loads(proof.read_text()).get('status') == 'PASS')
            boundary = json.loads(proof.read_text())
            accepted = (accepted and boundary.get('home_preserved') is True and
                        all(boundary.get('boundary', {}).get(name) == 0 for name in FORBIDDEN_COUNTERS) and
                        isinstance(boundary.get('sender_counts'), dict) and bool(boundary['sender_counts']) and
                        boundary.get('import_capability_proof', {}).get('suppressed') is True and
                        boundary.get('import_capability_proof', {}).get('restored') is True and
                        boundary.get('import_capability_proof', {}).get('bind_allowance') is False and
                        isinstance(boundary.get('transport_stub_counts'), dict) and
                        bool(boundary['transport_stub_counts']) and
                        all(value == 0 for value in boundary['transport_stub_counts'].values()) and
                        boundary.get('m18_lifecycle_accepted') is True and
                        boundary.get('m18_jobs_cancelled') is True and
                        boundary.get('main8_accepted' if profile == 'main8' else 'affected5_accepted') is True and
                        all(boundary.get('sendmsg_metadata_controls', {}).values()) and
                        len(boundary.get('sendmsg_metadata_controls', {})) == 16 and
                        boundary.get('boundary', {}).get('allowed_pg_sendmsg', 0) > 0 and
                        boundary.get('collected') == {'test_partner_main_composition.py': len(selection)} and
                        boundary.get('m18_counts') == {
                            'startup.prepare': 1, 'chat_ws.start': 1, 'chat_ws.stop': 1,
                            'notify.dispatch_async': 8, **{'scheduler.' + name: 1 for name in SCHEDULERS}})
    except Exception as exc:
        accepted = False
        reason = 'JUnit/proof validation failed: ' + type(exc).__name__
    receipt = {'status': 'PASS' if accepted else 'FAIL',
               'profile': profile, 'main8_accepted': profile == 'main8' and accepted,
               'affected5_accepted': profile == 'affected5' and accepted, 'child_exit': child_exit,
               'scratch_anchor_identity': anchor_identity,
               'scratch_policy': 'lstat/no-follow; exact owned root; only exact child ENOENT ignored',
               'reason': reason, 'child_reaped': True, 'elapsed_seconds': time.monotonic() - started,
               'runner_sha256': approved_sha, 'log_bytes': size, 'log_sha256': sha(EVIDENCE / 'run.log'),
               'junit_sha256': sha(junit) if junit.is_file() else None,
               'boundary_sha256': sha(proof) if proof.is_file() else None,
               'sql_target': DATABASE, 'app_runtime': 'NEW candidate host Python3.13.7',
               'cleanup': 'ROOT-owned dedicated DB/directories retained for review'}
    owned_scratch_bytes(RUN, anchor_identity)
    artifacts = {}
    for path in sorted(EVIDENCE.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('M18 evidence symlink forbidden')
        if path.is_file():
            artifacts[str(path.relative_to(EVIDENCE))] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    write_json(EVIDENCE / 'retained-evidence-manifest.json', {
        'source_base': SOURCE_BASE, 'runner_sha256': approved_sha,
        'other_runner_sha256': APPROVED_OTHER_SHA, 'artifacts': artifacts,
        'test_runtime': 'new candidate77 Python3.13.7/glibc2.36'})
    receipt['evidence_manifest_sha256'] = sha(EVIDENCE / 'retained-evidence-manifest.json')
    write_json(EVIDENCE / 'supervisor-proof.json', receipt)
    return 0 if accepted else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approved-sha256', required=True)
    parser.add_argument('--approved-other-sha256', required=True)
    parser.add_argument('--profile', required=True, choices=['main8', 'affected5'])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--execute-root-reviewed', action='store_true')
    group.add_argument('--root-reviewed-child', action='store_true')
    args = parser.parse_args()
    global APPROVED_OTHER_SHA, CURRENT_APPROVED_SHA
    APPROVED_OTHER_SHA, CURRENT_APPROVED_SHA = args.approved_other_sha256, args.approved_sha256
    return child(args.approved_sha256, args.profile) if args.root_reviewed_child else supervise(args.approved_sha256, args.profile)


if __name__ == '__main__':
    raise SystemExit(main())
