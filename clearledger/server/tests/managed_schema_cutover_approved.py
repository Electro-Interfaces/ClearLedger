"""Independent source approval gate. No harness/application import before hashes."""
import hashlib
import json
from pathlib import Path
import sys

SERVER=Path(__file__).resolve().parents[1]
APP_TREE = '8e002e545929bc08c6034818c1921a828092dc48195074e8e5ea101796cb8236'
FROZEN_TREE = 'c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e'
FILES = {
    'Dockerfile': 'aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d',
    '.dockerignore': '219f4861afde083e955dccd850e20ac3f86a4d3b51164c484e7fca1620490d6a',
    'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0',
    'tests/partner_test_safety.py': '43de791a8f0b418f03d4cdc155c2d8cc2d923757134f88b91870a539609eafb1',
    'tests/run_managed_schema_cutover.py': '188a4b52a3baa47db6a405a7bc854539b8a893ece334909fd5cb8532e04fd447',
}


def digest(root):
    paths=[p for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
    if len(paths)>1024 or sum(p.stat().st_size for p in paths)>32*1024*1024:
        raise RuntimeError('Approval source bounds exceeded')
    files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return hashlib.sha256(('\n'.join(name+'\0'+sha for name,sha in files.items())+'\n').encode()).hexdigest()


def verify_approval():
    if digest(SERVER/'app')!=APP_TREE or digest(SERVER/'schema_migrations')!=FROZEN_TREE:
        raise RuntimeError('Approved source tree mismatch')
    if any(hashlib.sha256((SERVER/name).read_bytes()).hexdigest()!=sha for name,sha in FILES.items()):
        raise RuntimeError('Approved source file mismatch')


def main():
    try:
        if sys.argv[1:]!=['--execute-approved-cutover-tests']:
            raise RuntimeError('Exact approved argument required')
        verify_approval()
    except Exception:
        print(json.dumps({'ok':False,'phase':'source_approval'},sort_keys=True))
        return 2
    import runpy
    target=SERVER/'tests/run_managed_schema_cutover.py'
    sys.argv=[str(target),'--execute-approved-cutover-tests']
    runpy.run_path(str(target),run_name='__main__')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
