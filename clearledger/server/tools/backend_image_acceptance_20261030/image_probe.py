"""ROOT-only bounded runtime61/acceptance77 image probe; author never executes it."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import pwd
import re
import resource
import socket
import sys

SELF = Path(__file__).resolve()
SERVER = SELF.parents[2]
SITE = Path('/opt/candidate/lib/python3.13/site-packages')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approved-sha256', required=True)
    parser.add_argument('--approved-manifest-sha256', required=True)
    parser.add_argument('--profile', choices=['runtime61', 'acceptance77'], required=True)
    args = parser.parse_args()
    manifest_path = SELF.parent / 'source-manifest.json'
    for path, expected in ((SELF, args.approved_sha256), (manifest_path, args.approved_manifest_sha256)):
        if not re.fullmatch('[0-9a-f]{64}', expected) or path.is_symlink() or sha(path) != expected:
            raise RuntimeError('Independent ROOT SHA approval mismatch')
    if (sys.version_info[:3] != (3, 13, 18) or os.confstr('CS_GNU_LIBC_VERSION') != 'glibc 2.41'
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or sys.flags.optimize
            or Path(sys.executable).absolute().parent != Path('/opt/candidate/bin')
            or os.environ.get('HOME') != pwd.getpwuid(os.getuid()).pw_dir
            or any('/site-packages' in p or p in {'',str(SERVER)} for p in sys.path)
            or any(n in sys.modules for n in ('app','pytest','site'))):
        raise RuntimeError('Exact isolated target interpreter/HOME required')
    expected_env = {'HOME':pwd.getpwuid(os.getuid()).pw_dir,
        'PATH':'/opt/candidate/bin:/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8',
        'APP_ENV':'test','DATABASE_URL':'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_backend_upgrade_test_20261030',
        'SECRET_KEY':'backend-image-synthetic-key-at-least-32-bytes',
        'UPLOAD_DIR':'/tmp/backend-image-test-uploads'}
    if dict(os.environ) != expected_env:
        raise RuntimeError('Exact clean synthetic probe environment required')
    manifest = json.loads(manifest_path.read_text())
    def source_guard():
        directories = ['app','schema_migrations'] + (['tests'] if args.profile == 'acceptance77' else [])
        for directory in directories:
            root = SERVER / directory
            paths = list(root.rglob('*'))
            if root.is_symlink() or any(p.is_symlink() for p in paths):
                raise RuntimeError('Source symlinks forbidden')
            found = {str(p.relative_to(SERVER)):sha(p) for p in paths if p.is_file()}
            expected = {n:v for n,v in manifest['files'].items() if n.startswith(directory+'/')}
            if found != expected:
                raise RuntimeError('Complete baked source mismatch: '+directory)
        if args.profile == 'acceptance77':
            for name, expected in manifest['files'].items():
                path = SERVER/name
                if path.is_symlink() or sha(path) != expected:
                    raise RuntimeError('Complete source/support mismatch: '+name)
        if any(p.name == '.env'  or p.name.startswith('.env.') for p in SERVER.rglob('*')):
            raise RuntimeError('Baked dotenv files forbidden')
    source_guard()
    if SITE.is_symlink() or not SITE.is_dir():
        raise RuntimeError('Missing image-local candidate site')
    cfg = Path('/opt/candidate/pyvenv.cfg').read_text()
    if not re.search(r'^include-system-site-packages\s*=\s*false\s*$',cfg,re.M):
        raise RuntimeError('System site forbidden')
    if any(p.is_symlink() or p.suffix == '.pth' or p.name in {'sitecustomize.py','usercustomize.py'} for p in SITE.rglob('*')):
        raise RuntimeError('Import hooks/symlinks forbidden')
    inventory = {}
    for dist in importlib.metadata.distributions(path=[str(SITE)]):
        name = re.sub('[-_.]+','-',dist.metadata['Name']).lower()
        if name in inventory:
            raise RuntimeError('Duplicate distributions')
        inventory[name] = dist.version
    expected = dict(manifest['runtime61'])
    if args.profile == 'acceptance77':
        expected.update(manifest['testtools16'])
    if inventory != expected or len(inventory) != (61 if args.profile == 'runtime61' else 77):
        raise RuntimeError('Exact runtime/testtools inventory mismatch')
    if list(importlib.metadata.distributions(path=['/usr/local/lib/python3.13/site-packages'])):
        raise RuntimeError('Retained old system distributions forbidden')
    resource.setrlimit(resource.RLIMIT_CPU,(45,50))
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE,(1024**2,1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE,(256,256))
    denied = []
    def audit(event, values):
        if event.startswith('socket.') and event not in {'socket.__new__'} or event in {
                'subprocess.Popen','os.system','os.posix_spawn','os.exec','os.fork','os.forkpty'}:
            denied.append(event)
            raise RuntimeError('No probe network/process calls')
        if event == 'open' and isinstance(values[0],(str,bytes,os.PathLike)):
            name=Path(os.fsdecode(values[0])).name
            if name == '.env' or name.startswith('.env.'):
                denied.append('dotenv')
                raise RuntimeError('Dotenv read forbidden')
    sys.addaudithook(audit)
    sys.path[:0]=[str(SERVER),str(SITE)]
    ipv6_before=socket.has_ipv6
    try:
        socket.has_ipv6=False
        import aiohttp, aiosmtplib, httpx, pywebpush, requests
    finally:
        socket.has_ipv6=ipv6_before
    from app.config import Settings
    settings=Settings(_env_file=None)
    flags={name:getattr(settings,name) for name in ('managed_core_budget_enabled','partner_oauth_enabled',
           'partner_api_enabled','partner_api_budget_enabled','partner_docs_enabled')}
    if any(flags.values()):
        raise RuntimeError('Production defaults must remain OFF')
    import app.main, app.database, app.config, app.services.schema_version_gate
    for module in (app.main,app.database,app.config,app.services.schema_version_gate):
        if not Path(module.__file__).is_relative_to(SERVER/'app'):
            raise RuntimeError('Application must come from baked image')
    source_guard()
    if denied or socket.has_ipv6 is not ipv6_before:
        raise RuntimeError('Forbidden probe activity/capability drift')
    print(json.dumps({'status':'PASS','profile':args.profile,'python':'3.13.18','glibc':'2.41',
          'source_base':manifest['source_base'],'trees':manifest['trees'],'counts':manifest['counts'],
          'inventory':inventory,'default_flags':flags,'blocked_attempts':denied,
          'home_preserved':True,'app_from_image':True,'source_guard_before_after':True},sort_keys=True))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
