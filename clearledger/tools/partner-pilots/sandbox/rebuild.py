#!/usr/bin/env python3
"""Пересобрать актуальные React entrypoints без перезапуска HTTPS и БД."""
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
from urllib.parse import urlsplit
import httpx
from runtime import HERE, PRIVATE, write_json


def main():
    path=PRIVATE/'owner-state.json'
    state=json.loads(path.read_text())
    target=urlsplit(state['origin'])
    if (state.get('status')!='ready' or target.scheme!='https' or target.hostname!='127.0.0.1'
            or not target.port or target.username or target.query or target.fragment):
        raise RuntimeError('A ready owned loopback sandbox is required')
    process_cmdline=Path('/proc/'+str(state['pid'])+'/cmdline').read_bytes()
    if str(HERE/'server.py').encode() not in process_cmdline:
        raise RuntimeError('Recorded process is not the owned sandbox')
    project=HERE.parents[2]
    revision=subprocess.check_output(['git','-C',str(project),'rev-parse','HEAD'],text=True).strip()
    pending=PRIVATE/'front-next'; previous=PRIVATE/'front-previous'
    for directory in (pending,previous):
        if directory.exists(): shutil.rmtree(directory)
    env={name:os.environ[name] for name in ('PATH','HOME','LANG') if name in os.environ}
    try:
        process=subprocess.run(['node',str(HERE/'build.mjs'),state['origin'],str(pending)],
            cwd=project,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=300)
        if process.returncode:
            error=PRIVATE/'rebuild-error.log';error.write_bytes(process.stderr);error.chmod(0o600)
            raise RuntimeError('Actual frontend rebuild failed; see private rebuild-error.log')
        (PRIVATE/'front').rename(previous)
        try: pending.rename(PRIVATE/'front')
        except BaseException:
            previous.rename(PRIVATE/'front')
            raise
        shutil.rmtree(previous)
        # Только HTML-выдача: никаких сессий, token exchange, SQL или auth overrides.
        with httpx.Client(verify=ssl.create_default_context(cafile=state['caPath']),trust_env=False) as client:
            response=client.get(state['origin']+'/developer/api/callback',headers={'Accept':'text/html'})
            if response.status_code!=200 or b'/p/' not in response.content:
                raise RuntimeError('Rebuilt public callback was not served')
        latest=json.loads(path.read_text())
        latest['frontendSourceRevision']=revision
        write_json(path,latest)
        manifest_path=PRIVATE/'client-manifest.json'
        manifest=json.loads(manifest_path.read_text());manifest['frontendSourceRevision']=revision
        write_json(manifest_path,manifest)
        print('FRONTEND_REBUILT '+revision+' BACKEND_UNCHANGED')
    finally:
        if pending.exists(): shutil.rmtree(pending)

if __name__=='__main__':main()
