"""ROOT-only candidate regression runner; source review is not execution approval.

Launch only with reviewed SHA and -I -S -B in the NEW candidate environment.
Preparation uses AST/compile only: this module was never imported by its author.
"""
import argparse
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
import subprocess
import sys
import time
from urllib.parse import urlsplit

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parents[1]
SELF = Path(__file__).resolve()
CANDIDATE = Path('/srv/projects/api-modernization-upgrade-test-env-20261030/.venv')
SITE = CANDIDATE / 'lib/python3.13/site-packages'
RUN = REPO / '.artifacts/backend-upgrade-functional-execution-20261030'
EMPTY, UPLOAD, EVIDENCE = (RUN / n for n in ('empty-test', 'upgrade-test-uploads', 'evidence'))
DSN = 'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_backend_upgrade_test_20261030'
RAW_DSN = DSN.replace('postgresql+asyncpg:', 'postgresql:', 1)
DATABASE = 'api_backend_upgrade_test_20261030'
LIMIT_LOG = 2 * 1024 * 1024
LIMIT_SCRATCH = 64 * 1024 * 1024
DEADLINE = 900
# Filled from source bytes and accepted ROOT receipts, not imports/collection.
FROZEN_TREES = {'app': '6eff5b153368ec492b91664a76825bd4ae360bfe4af55e902651f95d0d679981', 'schema_migrations': 'c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e', 'tests': 'faa034c1241dabd15aceb82f1ed6e90e47a0131b9af6ab0342cf00f7a898e722'}
FROZEN_FILES = {'.dockerignore': '219f4861afde083e955dccd850e20ac3f86a4d3b51164c484e7fca1620490d6a', 'Dockerfile': 'aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d', 'locks/dependency-artifacts-upgrade-py313-linux-amd64-20261030.json': '8711de6afb6bc461718851a537c2456ea9b1f68b2f4236f3de599df561493b7f', 'locks/runtime-upgrade-20261030-py313-linux-amd64.provisional.txt': 'a9b060f941cda22fab721522eb68f717711c55f17dbbdc83fae169a8e0fbf2bc', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601', 'requirements-upgrade-20261030.in': '90e92d607c5f3c966f5dca129461d92fdfc2a094e5b3a77e5e211ad5dc4d8caf', 'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0'}
RUNTIME_WITH_PIP = {'aiofiles': '24.1.0', 'aiohappyeyeballs': '2.7.1', 'aiohttp': '3.14.5', 'aiosignal': '1.4.0', 'aiosmtplib': '5.1.3', 'annotated-doc': '0.0.2', 'annotated-types': '0.8.0', 'anyio': '4.15.1', 'asyncpg': '0.30.0', 'attrs': '26.1.0', 'authlib': '1.9.1', 'bcrypt': '4.2.1', 'certifi': '2026.10.23', 'cffi': '2.1.1', 'charset-normalizer': '3.5.2', 'click': '8.5.0', 'cryptography': '50.0.2', 'dnspython': '2.9.1', 'email-validator': '2.3.0', 'et-xmlfile': '2.0.0', 'fastapi': '0.133.0', 'frozenlist': '1.8.0', 'greenlet': '3.5.6', 'gunicorn': '23.0.0', 'h11': '0.16.0', 'http-ece': '1.2.1', 'httpcore': '1.0.9', 'httptools': '0.9.0', 'httpx': '0.28.1', 'idna': '3.20', 'joserfc': '1.7.7', 'lxml': '6.1.3', 'multidict': '7.2.1', 'openpyxl': '3.1.5', 'packaging': '26.3', 'passlib': '1.7.4', 'pip': '26.2.2', 'propcache': '0.5.4', 'py-vapid': '1.9.6', 'pycparser': '3.12', 'pydantic': '2.14.2', 'pydantic-core': '2.50.2', 'pydantic-settings': '2.7.1', 'pyjwt': '2.15.0', 'pypdf': '6.21.2', 'python-docx': '1.1.2', 'python-dotenv': '1.2.2', 'python-multipart': '0.0.31', 'pywebpush': '2.5.0', 'pyyaml': '6.0.3', 'requests': '2.34.2', 'sqlalchemy': '2.0.36', 'starlette': '1.3.1', 'typing-extensions': '4.16.0', 'typing-inspection': '0.4.4', 'urllib3': '2.8.0', 'uvicorn': '0.34.0', 'uvloop': '0.23.0', 'watchfiles': '1.3.0', 'websockets': '17.3', 'yarl': '1.25.1'}
TEST_TOOLS = {'iniconfig': '2.3.1', 'jsonschema': '4.26.0', 'jsonschema-path': '0.5.0', 'jsonschema-specifications': '2025.9.1', 'lazy-object-proxy': '1.13.0', 'openapi-schema-validator': '0.9.0', 'openapi-spec-validator': '0.9.0', 'pathable': '0.6.0', 'pluggy': '1.7.0', 'pygments': '2.21.0', 'pytest': '9.2.0', 'pytest-asyncio': '1.4.1', 'referencing': '0.37.0', 'rfc3339-validator': '0.1.4', 'rpds-py': '2026.9.1', 'six': '1.17.0'}
EXPECTED_CASES = {'backend_upgrade_approved.py': 6, 'test_api_contracts_context.py': 34, 'test_api_contracts_http.py': 56, 'test_auth.py': 13, 'test_contract_liability.py': 1, 'test_doc_text.py': 9, 'test_docs_portal.py': 22, 'test_docs_register.py': 23, 'test_partner_identity.py': 67, 'test_partner_product_integration.py': 20, 'test_partner_userinfo_wire.py': 14, 'test_product_api.py': 57, 'test_product_http_profile.py': 12, 'test_product_object_ids.py': 27, 'test_product_openapi_http_contract.py': 8, 'test_product_service_openapi.py': 7}
PREPARATION_RECEIPTS = {'runtime-prepare-proof.json': 'abbd7b18db3ba39bc18ad6ded7158347e8964af1126128472f9b9868a8863a42', 'test-tools-prepare-proof.json': 'f183375c1a42089673fe47824868e0670874aa3a884a32c0a3296cd5990bfe39'}
BOUNDARY = {'blocked_network': 0, 'allowed_pg_connects': 0, 'blocked_subprocess': 0,
            'denied_env_reads': 0, 'db_connections': 0}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root):
    paths = [p for p in sorted(root.rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts and p != SELF]
    if len(paths) > 1024 or sum(p.stat().st_size for p in paths) > 32 * 1024 * 1024:
        raise RuntimeError('Source tree exceeds approved bounds')
    if any(p.is_symlink() for p in paths):
        raise RuntimeError('Source symlinks prohibited')
    value = '\n'.join(str(p.relative_to(root)) + '\0' + sha(p) for p in paths) + '\n'
    return hashlib.sha256(value.encode()).hexdigest()


def source_guard(approved_sha):
    if not re.fullmatch('[0-9a-f]{64}', approved_sha) or sha(SELF) != approved_sha:
        raise RuntimeError('Runner SHA does not match independent ROOT approval')
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
            or not sys.dont_write_bytecode or os.confstr('CS_GNU_LIBC_VERSION') != 'glibc 2.36'
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
    path.write_bytes(data)
    path.chmod(0o600)


def install_boundaries():
    def audit(event, args):
        if event == 'socket.connect':
            sock, address = args
            if sock.family not in (socket.AF_INET, socket.AF_INET6) or address != ('127.0.0.1', 33546):
                BOUNDARY['blocked_network'] += 1
                raise RuntimeError('Only approved PostgreSQL loopback socket allowed')
            BOUNDARY['allowed_pg_connects'] += 1
        elif event in {'socket.bind', 'socket.sendto', 'socket.sendmsg'}:
            BOUNDARY['blocked_network'] += 1
            raise RuntimeError('No listeners/datagrams in candidate tests')
        elif event == 'socket.getaddrinfo':
            if args[0] != '127.0.0.1' or int(args[1]) != 33546:
                BOUNDARY['blocked_network'] += 1
                raise RuntimeError('External DNS prohibited')
        elif event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork', 'os.forkpty'}:
            BOUNDARY['blocked_subprocess'] += 1
            raise RuntimeError('Subprocesses prohibited inside test child')
        elif event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            if Path(os.fsdecode(args[0])).name == '.env':
                BOUNDARY['denied_env_reads'] += 1
                raise RuntimeError('Reading .env prohibited')
    sys.addaudithook(audit)
    # Low-level socket restriction remains even if a test replaces an HTTP seam.
    from unittest.mock import AsyncMock, Mock
    import aiohttp
    import aiosmtplib
    import httpx
    import pywebpush
    import requests
    stack = ExitStack()
    def deny(*args, **kwargs):
        BOUNDARY['blocked_network'] += 1
        raise RuntimeError('External sender blocked')
    async def adeny(*args, **kwargs):
        return deny(*args, **kwargs)
    from unittest.mock import patch
    for owner, name, replacement in (
        (aiosmtplib, 'send', AsyncMock(return_value=None)),
        (pywebpush, 'webpush', Mock(side_effect=deny)),
        (requests.sessions.Session, 'request', deny),
        (httpx.HTTPTransport, 'handle_request', deny),
        (httpx.AsyncHTTPTransport, 'handle_async_request', adeny),
        (aiohttp.ClientSession, '_request', adeny),
    ):
        stack.enter_context(patch.object(owner, name, replacement))
    # No fixture has run. Import these modules only after env/site/socket guards.
    from app.services import email_service, notify, doc_text
    stack.enter_context(patch.object(notify, 'dispatch_async', Mock(return_value=None)))
    for name in ('send_invite', 'send_access_invite', 'send_notice', 'send_meeting_invite', 'send_password_reset'):
        stack.enter_context(patch.object(email_service, name, AsyncMock(return_value=False)))
    stack.enter_context(patch.object(doc_text, '_command', AsyncMock(return_value=b'')))
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


def child(approved_sha):
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
    packages = inventory()
    write_json(EVIDENCE / 'pre-import-boundary.json', {
        'runner_sha256': approved_sha, 'source_trees': FROZEN_TREES,
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
    record = {'status': 'starting', 'python': '3.13.7', 'glibc': '2.36', 'runner_sha256': approved_sha,
              'inventory': packages, 'runtime_count': 61, 'test_tool_count': 16,
              'home_preserved': True, 'no_site_before_guards': True, 'no_env_files': True,
              'source_trees': FROZEN_TREES, 'sql_target': DATABASE}
    code = 2
    try:
        with install_boundaries():
            asyncio.run(database_preflight())
            import pytest
            class Record:
                def pytest_collection_modifyitems(self, session, config, items):
                    counts = dict(Counter(Path(item.path).name for item in items))
                    record['collected'] = counts
                    record['nodeids'] = [item.nodeid for item in items]
                    if counts != EXPECTED_CASES:
                        raise pytest.UsageError('Collection differs from frozen AST case counts')
                def pytest_runtest_logreport(self, report):
                    if report.when == 'call' or report.failed or report.skipped:
                        outcomes = record.setdefault('outcomes', {})
                        outcomes[report.nodeid] = ('xpassed' if report.passed else 'xfailed') if hasattr(report, 'wasxfail') else report.outcome
            argv = ['-c', str(SERVER / 'pytest.ini'), '--rootdir=' + str(SERVER),
                    '--confcutdir=' + str(SERVER), '--import-mode=importlib', '-p', 'pytest_asyncio.plugin',
                    '-p', 'no:cacheprovider', '--basetemp=' + str(EMPTY / 'pytest-test-temp'),
                    '--junitxml=' + str(EVIDENCE / 'junit.xml'), '--tb=short', '-q',
                    *[str(SERVER / 'tests' / n) for n in EXPECTED_CASES]]
            code = int(pytest.main(argv, plugins=[Record()]))
            record['pytest_exit'] = code
            outcomes = record.get('outcomes', {})
            # A zero exit with missing/skip/xfail cases is not accepted.
            if len(outcomes) != sum(EXPECTED_CASES.values()) or set(outcomes.values()) != {'passed'}:
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
        record.update(status='PASS' if code == 0 else 'FAIL', boundary=dict(BOUNDARY),
                      home_preserved=os.environ.get('HOME') == pwd.getpwuid(os.getuid()).pw_dir)
        write_json(EVIDENCE / 'boundary-proof.json', record)
    return code


def clean_environment():
    # HOME is the real account home, never a fabricated scratch home.
    return {'HOME': pwd.getpwuid(os.getuid()).pw_dir, 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
            'APP_ENV': 'test', 'HOSTNAME': 'backend-upgrade-test',
            'SECRET_KEY': 'backend-upgrade-synthetic-secret-key-at-least-32-bytes',
            'ECOSYSTEM_COMPANIES': '', 'DATABASE_URL': DSN, 'TEST_DATABASE_URL': DSN,
            'UPLOAD_DIR': str(UPLOAD), 'TMPDIR': str(EMPTY), 'PYTHONDONTWRITEBYTECODE': '1',
            'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'RUN_PARTNER_IDENTITY_TESTS': '1',
            'RUN_PRODUCT_API_TESTS': '1', 'SEED_SUPERADMIN_EMAIL': 'admin@clearledger.ru',
            'SEED_SUPERADMIN_PASSWORD': 'admin123'}


def supervise(approved_sha):
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
    argv = [str(CANDIDATE / 'bin/python'), '-I', '-S', '-B', str(SELF),
            '--approved-sha256', approved_sha, '--root-reviewed-child']
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
                    raise RuntimeError('Global 900s deadline')
                files = [p for p in RUN.rglob('*') if p.is_file() and not p.is_symlink()]
                if len(files) > 4096 or sum(p.stat().st_size for p in files) > LIMIT_SCRATCH:
                    raise RuntimeError('Scratch 64MiB/4096 files bound')
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
            accepted = (len(cases) == sum(EXPECTED_CASES.values()) and
                    not any(suites.findall('.//' + k) for k in ('failure', 'error', 'skipped')) and
                    json.loads(proof.read_text()).get('status') == 'PASS')
    except Exception as exc:
        accepted = False
        reason = 'JUnit/proof validation failed: ' + type(exc).__name__
    receipt = {'status': 'PASS' if accepted else 'FAIL', 'child_exit': child_exit,
               'reason': reason, 'child_reaped': True, 'elapsed_seconds': time.monotonic() - started,
               'runner_sha256': approved_sha, 'log_bytes': size, 'log_sha256': sha(EVIDENCE / 'run.log'),
               'junit_sha256': sha(junit) if junit.is_file() else None,
               'boundary_sha256': sha(proof) if proof.is_file() else None,
               'sql_target': DATABASE, 'app_runtime': 'NEW candidate host Python3.13.7',
               'cleanup': 'ROOT-owned dedicated DB/directories retained for review'}
    write_json(EVIDENCE / 'supervisor-proof.json', receipt)
    return 0 if accepted else 1


# Additional upgrade probes: synthetic bytes only. Existing expectations stay frozen.
def test_upgrade_dotenv_synthetic_stream():
    from io import StringIO
    from dotenv import dotenv_values
    values = dotenv_values(stream=StringIO("A=one\nB=\"${A} two\"\nEMPTY=\nexport Q='x y'\nNO_VALUE\n"))
    assert dict(values) == {'A': 'one', 'B': 'one two', 'EMPTY': '', 'Q': 'x y', 'NO_VALUE': None}


def test_upgrade_raw_jwt_verification():
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = {'sub': 'synthetic-user', 'iss': 'https://synthetic.example.invalid',
              'aud': 'upgrade-test', 'iat': int(time.time()), 'exp': int(time.time()) + 120}
    raw = jwt.encode(claims, key, algorithm='RS256')
    assert jwt.decode(raw, key.public_key(), algorithms=['RS256'], audience='upgrade-test',
                      issuer=claims['iss'], options={'require': ['exp', 'sub', 'iat']}) == claims
    import pytest
    for options, error in (({'audience': 'wrong'}, jwt.InvalidAudienceError),
                           ({'issuer': 'https://wrong.invalid'}, jwt.InvalidIssuerError),
                           ({'algorithms': ['HS256']}, jwt.InvalidAlgorithmError)):
        kwargs = {'algorithms': ['RS256'], 'audience': 'upgrade-test', 'issuer': claims['iss'], **options}
        with pytest.raises(error):
            jwt.decode(raw, key.public_key(), **kwargs)
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(jwt.encode({**claims, 'exp': 1}, key, algorithm='RS256'), key.public_key(),
                   algorithms=['RS256'], audience='upgrade-test', issuer=claims['iss'])
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(raw, wrong.public_key(), algorithms=['RS256'], audience='upgrade-test', issuer=claims['iss'])


def _pdf_bytes(text=None):
    from io import BytesIO
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if text is not None:
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 10 Tf 50 700 Td (' + text + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_upgrade_pdf_actual_library_and_application_extract():
    from app.services.contract_liability import извлечь_текст
    text = 'Synthetic contract text with enough readable content. ' * 6
    actual, warning = извлечь_текст('synthetic.pdf', _pdf_bytes(text))
    assert actual.strip() == text.strip() and warning is None
    blank, warning = извлечь_текст('blank.pdf', _pdf_bytes())
    assert blank.strip() == '' and warning and 'нет текстового слоя' in warning


def test_upgrade_pdf_malformed_is_library_error():
    from app.services.contract_liability import извлечь_текст
    from pypdf.errors import PdfReadError
    import pytest
    with pytest.raises(PdfReadError):
        извлечь_текст('malformed.pdf', b'%PDF-1.4\nnot a PDF document\n')


def _multipart_app():
    from fastapi import FastAPI, File, Request, UploadFile
    app = FastAPI()
    @app.post('/echo')
    async def echo(file: UploadFile = File(...)):
        content = await file.read()
        result = {'filename': file.filename, 'type': file.content_type,
                  'size': file.size, 'hex': content.hex()}
        await file.close()
        return result
    @app.post('/limited')
    async def limited(request: Request):
        async with request.form(max_files=1, max_fields=1, max_part_size=8) as form:
            return {'parts': len(form)}
    return app


async def test_upgrade_multipart_filename_and_exact_bytes():
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=_multipart_app()), base_url='http://synthetic') as client:
        for name, content in (('../Тест.pdf', b'%PDF-\x00\xff\n'), ('empty.bin', b'')):
            response = await client.post('/echo', files={'file': (name, content, 'application/octet-stream')})
            assert response.status_code == 200
            assert response.json() == {'filename': name, 'type': 'application/octet-stream',
                                       'size': len(content), 'hex': content.hex()}


async def test_upgrade_multipart_validation_and_limits():
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=_multipart_app()), base_url='http://synthetic') as client:
        response = await client.post('/echo', data={'other': 'x'})
        assert response.status_code == 422 and response.json()['detail'][0]['loc'] == ['body', 'file']
        response = await client.post('/echo', content=b'invalid', headers={'Content-Type': 'multipart/form-data'})
        assert response.status_code == 400
        response = await client.post('/limited', files=[('a', ('a.bin', b'a')), ('b', ('b.bin', b'b'))])
        assert response.status_code == 400 and 'Too many files' in response.json()['detail']
        response = await client.post('/limited', files=[('a', (None, 'a')), ('b', (None, 'b'))])
        assert response.status_code == 400 and 'Too many fields' in response.json()['detail']
        response = await client.post('/limited', files={'a': (None, '123456789')})
        assert response.status_code == 400 and 'maximum size' in response.json()['detail']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approved-sha256', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--execute-root-reviewed', action='store_true')
    group.add_argument('--root-reviewed-child', action='store_true')
    args = parser.parse_args()
    return child(args.approved_sha256) if args.root_reviewed_child else supervise(args.approved_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
