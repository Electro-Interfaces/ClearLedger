"""SOURCE-only admission specification. Import performs no I/O and grants nothing.

ROOT alone supplies the private, root-owned, read-only contract for one process
inside its disposable namespace. This module neither creates nor renews it.
The public source pins are integrity expectations, never execution authority.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

PROFILE = 'partner-contract-schema4-native-v1'
CONTROL = Path('/test/control/partner-schema4-approval.json')
TARGET = 'api_partner_contract_schema_v4_test_20261101'
EXACT_DSN = 'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/' + TARGET
IMMUTABLE_SHA256 = '040e2004298eecbc415d7d24c5c8ed783f3fe4c9e42676706b1bbaf8fe6bdc56'
IMMUTABLE_BYTES = 14634482
IMMUTABLE_FILES = 535
HELPERS = ('tests/partner_contract_schema_v4_approval.py',
           'tests/partner_contract_schema_v4_fixture.py',
           'tests/partner_contract_schema_v4_cases.py')
_active = None


def _require(condition, reason):
    if not condition:
        raise RuntimeError('schema4 ROOT admission refused: ' + reason)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate contract key')
        result[key] = value
    return result


def _canonical(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=True).encode()


def _file(path):
    _require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink')
    info = path.stat()
    _require(stat.S_ISREG(info.st_mode), 'regular file required')
    return path.read_bytes()


def _private_contract():
    # Ownership/mode and the live PID/start-time lease establish authority;
    # a copied file with the expected name does not. ROOT must mount source RO.
    for path in (CONTROL, CONTROL.parent, CONTROL.parent.parent):
        info = path.lstat()
        _require(not stat.S_ISLNK(info.st_mode) and info.st_uid == 0
                 and not info.st_mode & 0o022, 'ROOT-controlled contract path')
    _require(CONTROL.stat().st_mode & 0o777 == 0o444, 'contract must be mode0444')
    raw = _file(CONTROL)
    _require(len(raw) <= 32768, 'contract size')
    return json.loads(raw, object_pairs_hook=_unique)


def _lease(contract):
    lease = contract['run_lease']
    # /proc/<pid>/stat starttime distinguishes PID reuse without running a tool.
    start = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]
    _require(set(lease) == {'run_id', 'nonce', 'pid', 'process_start_ticks',
                           'issued_at', 'expires_at'}, 'lease shape')
    _require(isinstance(lease['run_id'], str) and len(lease['run_id']) >= 16
             and isinstance(lease['nonce'], str) and len(lease['nonce']) >= 32,
             'ROOT lease identity')
    _require(type(lease['pid']) is int and lease['pid'] == os.getpid()
             and lease['process_start_ticks'] == start, 'lease process identity')
    now = time.time()
    _require(type(lease['issued_at']) in (int, float)
             and type(lease['expires_at']) in (int, float)
             and lease['issued_at'] <= now < lease['expires_at']
             and 0 < lease['expires_at'] - lease['issued_at'] <= 1800,
             'live bounded ROOT lease')


def require_running_approval():
    """Explicit call BEFORE any app/ORM/driver/fixture imports; no connections.

    Revalidates the private lease, exact source bytes and target on each call.
    ROOT freezes helper pins independently AFTER reviewing this source package.
    Nothing here generates an approval from the working target's own hashes.
    """
    global _active
    contract = _private_contract()
    _require(set(contract) == {'profile', 'source_root', 'working_directory',
                              'immutable_source', 'helpers', 'target', 'run_lease',
                              'disposable_namespace', 'runtime_seconds'}, 'contract shape')
    _require(contract['profile'] == PROFILE, 'fixed profile version')
    _lease(contract)
    root = Path(__file__).resolve().parents[1]
    _require(contract['source_root'] == str(root)
             and root == Path(__file__).absolute().parents[1], 'approved source origin')
    _require(contract['working_directory'] == str(Path.cwd())
             and not Path('.env').exists(), 'approved cwd without dotenv')
    _require(sys.dont_write_bytecode and not (root / 'tests/__pycache__').exists(),
             'ROOT must use source-only imports without project bytecode caches')
    _require(os.getuid() != 0 and os.environ.get('DATABASE_URL') == EXACT_DSN
             and os.environ.get('TEST_DATABASE_URL') == EXACT_DSN
             and os.environ.get('APP_ENV') == 'test'
             and os.environ.get('MANAGED_CORE_BUDGET_ENABLED') == 'true'
             and os.environ.get('MANAGED_CORE_BUDGET_EXPECTED_DATABASE') == TARGET
             and os.environ.get('MANAGED_CORE_BUDGET_EXPECTED_USER') == 'clearledger',
             'exact synthetic runtime target')
    _require(contract['target'].keys() == {'database', 'user', 'host', 'port',
             'database_oid', 'role_oid', 'core_oid', 'edge_oid'}, 'target shape')
    target = contract['target']
    _require((target['database'], target['user'], target['host'], target['port'])
             == (TARGET, 'clearledger', '127.0.0.1', 33546), 'fixed target')
    _require(all(type(target[key]) is int and target[key] > 0
                 for key in ('database_oid', 'role_oid', 'core_oid', 'edge_oid')),
             'actual ROOT-attested OIDs')
    ns = contract['disposable_namespace']
    _require(set(ns) == {'container_id', 'published_ports', 'source_read_only',
                        'independently_verified_by_root'}
             and isinstance(ns['container_id'], str) and len(ns['container_id']) == 64
             and all(c in '0123456789abcdef' for c in ns['container_id'])
             and ns['published_ports'] == [] and ns['source_read_only'] is True
             and ns['independently_verified_by_root'] is True, 'ROOT namespace attestation')
    _require(type(contract['runtime_seconds']) is int
             and 1 <= contract['runtime_seconds'] <= 1200, 'ROOT runtime budget')
    expected = {'sha256': IMMUTABLE_SHA256, 'bytes': IMMUTABLE_BYTES,
                'files': IMMUTABLE_FILES}
    _require(contract['immutable_source'] == expected, 'immutable source expectation')
    entries = []
    for directory in ('app', 'schema_migrations'):
        for path in sorted((root / directory).rglob('*')):
            _require(not path.is_symlink(), 'source symlink')
            _require(path.name != '__pycache__' and path.suffix not in {'.pyc', '.pyo'},
                     'project bytecode cache is outside source freeze')
            if path.is_file() and path.suffix in {'.py', '.sql', '.json', '.yml', '.yaml'}:
                raw = _file(path)
                entries.append([str(path.relative_to(root)), len(raw), hashlib.sha256(raw).hexdigest()])
    entries.sort()
    _require(len(entries) == IMMUTABLE_FILES
             and sum(row[1] for row in entries) == IMMUTABLE_BYTES
             and hashlib.sha256(_canonical(entries)).hexdigest() == IMMUTABLE_SHA256,
             'immutable source bytes differ')
    _require(set(contract['helpers']) == set(HELPERS), 'exact reviewed helper closure')
    for name in HELPERS:
        pin = contract['helpers'][name]
        raw = _file(root / name)
        _require(set(pin) == {'sha256', 'bytes'} and type(pin['bytes']) is int
                 and pin['bytes'] == len(raw)
                 and pin['sha256'] == hashlib.sha256(raw).hexdigest(),
                 'ROOT-frozen helper bytes differ')
    if _active is None:
        _require(not any(name == 'app' or name.startswith(('app.', 'sqlalchemy', 'asyncpg',
                         'schema_migrations')) or name == 'tests.partner_contract_schema_v4_fixture'
                         for name in sys.modules), 'admission must precede runtime imports')
    else:
        _require(contract == _active, 'contract changed during run')
    _active = contract
    return json.loads(json.dumps(contract))


def require_active_approval():
    """No-I/O import guard for fixture; first explicit admission must be complete."""
    _require(_active is not None, 'call require_running_approval before fixture import')
    _lease(_active)
