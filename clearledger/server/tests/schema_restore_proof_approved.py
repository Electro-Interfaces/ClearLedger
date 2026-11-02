"""Независимый source/env approval gate; opt-out не импортирует harness/app/driver."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys

SERVER = Path(__file__).resolve().parents[1]
BASE = Path('/srv/projects/api-modernization-test-env-20261029')
PYTHON = BASE / '.venv/bin/python'
EMPTY = BASE / 'schema-restore-proof-empty-test'
UPLOAD = BASE / 'schema-restore-proof-test-uploads'
EVIDENCE = BASE / 'private-schema-restore-proof-20261030'
BASE_COMMIT = '2578ec8fbef3c8a21fa274df72f96b86cd3e06af'
APP_TREE = '8e002e545929bc08c6034818c1921a828092dc48195074e8e5ea101796cb8236'
FROZEN_TREE = 'c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e'
FILES = {
    'tests/run_schema_restore_proof.py': '784b38d10f389d24389432a234dce6af77409884e5057eb5754e8207ae779831',
    'tests/partner_test_safety.py': '43de791a8f0b418f03d4cdc155c2d8cc2d923757134f88b91870a539609eafb1',
    'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0',
    'Dockerfile': 'aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d',
}


def tree(root, count, size=None):
    paths = [p for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
    total = sum(p.stat().st_size for p in paths)
    if len(paths)!=count or total>32*1024*1024 or any(p.is_symlink() for p in paths) or (size is not None and total!=size):
        raise RuntimeError('source tree bound mismatch')
    entries = [str(p.relative_to(root))+'\0'+hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    return hashlib.sha256(('\n'.join(entries)+'\n').encode()).hexdigest()


def verify_approval(*, require_empty_evidence=True):
    if sys.argv[1:]!=['--execute-approved-restore-tests'] or os.environ.get('RUN_SCHEMA_RESTORE_PROOF')!='1':
        raise RuntimeError('explicit root approval required')
    expected = {
        'HOME':pwd.getpwuid(os.getuid()).pw_dir,
        'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8', 'APP_ENV':'test',
        'SECRET_KEY':'schema-restore-synthetic-secret-key-only',
        'HOSTNAME':'schema-restore-proof-test',
        'ECOSYSTEM_COMPANIES':'restore-proof|Synthetic restore company|Synthetic|energy',
        'DATABASE_URL':'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_schema_restore_source_test',
        'TEST_DATABASE_URL':'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_schema_restore_source_test',
        'SCHEMA_RESTORE_TARGET_DATABASE_URL':'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_schema_restore_target_test',
        'UPLOAD_DIR':str(UPLOAD), 'PYTHONDONTWRITEBYTECODE':'1', 'RUN_SCHEMA_RESTORE_PROOF':'1',
    }
    if dict(os.environ)!=expected or sys.version_info[:3]!=(3,13,7) or Path(sys.executable)!=PYTHON:
        raise RuntimeError('exact clean environment/interpreter required')
    if Path.cwd()!=EMPTY:
        raise RuntimeError('empty cwd required')
    for directory in [EMPTY,UPLOAD,EVIDENCE]:
        if (not directory.is_dir() or directory.is_symlink() or directory.stat().st_uid!=os.getuid()
                or directory.stat().st_mode & 0o077):
            raise RuntimeError('private owned directory required')
    if any(EMPTY.iterdir()) or any(UPLOAD.iterdir()) or (require_empty_evidence and any(EVIDENCE.iterdir())):
        raise RuntimeError('fresh directories required')
    space = os.statvfs(EVIDENCE)
    if space.f_bavail*space.f_frsize < 128*1024*1024:
        raise RuntimeError('private host evidence space bound failed')
    if tree(SERVER/'app',489,17114637)!=APP_TREE or tree(SERVER/'schema_migrations',16)!=FROZEN_TREE:
        raise RuntimeError('approved application/package source mismatch')
    if any(hashlib.sha256((SERVER/name).read_bytes()).hexdigest()!=value for name,value in FILES.items()):
        raise RuntimeError('approved source file mismatch')
    for args in [
        ['git','-C',str(SERVER),'cat-file','-e',BASE_COMMIT+'^{commit}'],
        ['git','-C',str(SERVER),'merge-base','--is-ancestor',BASE_COMMIT,'HEAD'],
    ]:
        result = subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,check=False)
        if result.returncode:
            raise RuntimeError('immutable integration ancestry mismatch')
    # Общий pure pre-import guard: существующие conftest/pytest не исполняются.
    sys.path.insert(0,str(SERVER/'tests'))
    from partner_test_safety import partner_test_safety_error
    if partner_test_safety_error(os.environ, flag='RUN_SCHEMA_RESTORE_PROOF'):
        raise RuntimeError('common target pre-import guard refused')
    os.umask(0o077)


def main():
    try:
        verify_approval()
    except Exception:
        print(json.dumps({'ok':False,'phase':'source_environment_approval'},sort_keys=True))
        return 2
    # Ни app, ни asyncpg, ни harness не загружаются до всех проверок выше.
    import runpy
    runpy.run_path(str(SERVER/'tests/run_schema_restore_proof.py'),run_name='__main__')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
