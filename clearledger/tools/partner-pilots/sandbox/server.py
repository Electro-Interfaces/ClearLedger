#!/usr/bin/env python3
"""Явно включаемая HTTPS fixture без импорта production app.main и conftest."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import socket
import ssl
import subprocess
import sys
from urllib.parse import urlsplit

from guard import validate
from runtime import HERE, PRIVATE, prepare, private_dir, write_json

PROJECT = HERE.parents[2]
STATE = PRIVATE/'owner-state.json'


def configure():
    database, upload = validate()
    # Настройки не получают унаследованные credentials или настоящий .env.
    # До импорта Ядра переходим в свой закрытый каталог; env_file тоже отключён.
    preserved = {name:os.environ[name] for name in ('PATH','HOME','LANG') if name in os.environ}
    os.environ.clear()
    os.environ.update(preserved)
    os.environ.update(DATABASE_URL=database, UPLOAD_DIR=str(upload), APP_ENV='test',
        SECRET_KEY=secrets.token_urlsafe(48), PARTNER_OAUTH_ENABLED='true',
        PARTNER_API_ENABLED='true', PARTNER_DOCS_ENABLED='true',
        PARTNER_OAUTH_AUDIENCE='urn:synthetic:partner-pilots', PARTNER_DOCS_ENVIRONMENT='sandbox')
    os.chdir(private_dir())
    if Path('.env').exists():
        raise RuntimeError('Unexpected .env in private fixture directory')
    sys.path.insert(0,str(PROJECT/'server'))
    from app.config import Settings, get_settings
    Settings.model_config['env_file']=None
    get_settings.cache_clear()
    # При первом импорте config здесь нет .env и секретов в окружении.
    import app.config as config
    config.settings=get_settings()
    for name in ('hubex_base_url','asr_url','calendar_reply_imap_host','smtp_host',
        'tradecorp_api_url','msto_api_url','app_public_url'):
        setattr(config.settings,name,'')
    # Запрещаем исходящие соединения даже при случайном вызове коннектора.
    def network_guard(event,args):
        if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1',None):
            raise RuntimeError('Sandbox DNS egress is disabled')
        if event == 'socket.connect':
            address=args[1]
            if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1'):
                raise RuntimeError('Sandbox network egress is disabled')
    sys.addaudithook(network_guard)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    return database,upload,config.settings


def application(factory, settings, state):
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse, Response
    from app.database import get_db
    from app.auth import gate_ok
    from app.routers import auth_router, partner_admin_router, partner_oauth_router, docs_portal_router, users_router
    from app.services import partner_identity as identity, notify
    from app.product_api import create_product_api
    from app.api_contracts import policy_registry
    # Заглушена только доставка; пароли, gate Ядра, grants и verifier настоящие.
    async def no_notice(*args,**kwargs): pass
    auth_router.email_service.send_notice=no_notice
    notify.dispatch_async=lambda *args,**kwargs:None
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    app.add_exception_handler(identity.PartnerProblem,identity.problem_handler)
    for router in (auth_router.router,partner_admin_router.router,partner_oauth_router.router,
                   partner_oauth_router.consent_router,docs_portal_router.router,users_router.router):
        app.include_router(router,prefix='/api')
    app.include_router(partner_oauth_router.well_known_router)
    async def database():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    app.dependency_overrides[get_db]=database
    child=create_product_api(session_factory=factory,enabled=True,upload_dir=os.environ['UPLOAD_DIR'],
        issuer=state['origin'],source_revision=state['sourceRevision'])
    policy_registry(child)
    app.state.product_api=child
    app.mount('/api/v1',child)

    @app.get('/{path:path}')
    async def frontend(path:str,request:Request):
        headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
        if path.startswith(('api/','.well-known/')):
            return Response(status_code=404,headers=headers)
        public=PRIVATE/'front'/'public'
        main=PRIVATE/'front'/'main'
        if not (public/'public.html').is_file() or not (main/'index.html').is_file():
            return Response(status_code=503,headers=headers)
        if path.startswith('p/'):
            root=public.resolve(); target=(root/path[2:]).resolve()
        else:
            async with factory() as db:
                gate=await gate_ok(request.cookies.get('cl_gate'),db)
            html='text/html' in request.headers.get('accept','')
            if html and not gate:
                return FileResponse(public/'public.html',media_type='text/html',headers=headers)
            if not gate:
                return Response(status_code=403,headers=headers)
            root=main.resolve(); target=(root/('index.html' if html else path)).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return Response(status_code=404,headers=headers)
        return FileResponse(target,headers=headers)
    return app


async def initialize(database,upload,state,*,resume=False):
    import asyncpg
    from sqlalchemy import text
    import app.database as core_db
    import app.models, app.models_partner, app.models_docs_portal  # зарегистрировать реальные модели
    from fixture import seed
    if resume:
        if state.get('status')!='initializing' or state.get('databaseOwned') is not True:
            raise RuntimeError('Seed resume requires the owned interrupted bootstrap')
        async with core_db.engine.connect() as conn:
            for table in ('companies','users','partner_clients'):
                if await conn.scalar(text('SELECT count(*) FROM '+table)):
                    raise RuntimeError('Seed resume refused: existing identity/domain records')
        state['fixture']=await seed(core_db.async_session_factory,upload)
        state['status']='seeded-awaiting-serve'; write_json(STATE,state)
        await core_db.engine.dispose()
        return
    if upload.exists() and any(upload.iterdir()):
        raise RuntimeError('Test upload directory is nonempty; refusing to mix fixture ownership')
    admin=await asyncpg.connect(database.replace('postgresql+asyncpg:','postgresql:').rsplit('/',1)[0]+'/postgres')
    try:
        exists=await admin.fetchval('SELECT 1 FROM pg_database WHERE datname=$1','api_partner_pilots_test')
        if not exists:
            await admin.execute('CREATE DATABASE api_partner_pilots_test')
    finally:
        await admin.close()
    async with core_db.engine.begin() as conn:
        count=await conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('public','edge')"))
        if count:
            raise RuntimeError('Dedicated database is nonempty; refusing implicit reset/reseed')
        await conn.execute(text('CREATE SCHEMA IF NOT EXISTS edge'))
    state.update(status='initializing',databaseOwned=True,uploadDir=str(upload))
    write_json(STATE,state)
    await core_db.create_all()  # штатный bootstrap сначала создаёт безопасную телефонную функцию
    state['fixture']=await seed(core_db.async_session_factory,upload)
    state['uploadDir']=str(upload)
    state['status']='seeded-awaiting-serve'
    write_json(STATE,state)
    await core_db.engine.dispose()


async def serve(database,upload,settings,state,callback):
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import app.database as core_db
    import uvicorn
    import httpx
    preprovision_retry=(state.get('status')=='stopped' and not state.get('clients')
        and not (PRIVATE/'client-manifest.json').exists())
    if 'fixture' not in state or (state.get('status')!='seeded-awaiting-serve' and not preprovision_retry):
        raise RuntimeError('Run separately authorized init first; implicit session restart is disabled')
    target=urlsplit(callback)
    if target.scheme!='https' or target.hostname!='127.0.0.2' or not target.port or target.username or target.password or target.query or target.fragment:
        raise ValueError('Explicit real HTTPS loopback callback required')
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); sock.listen(128); sock.setblocking(False)
    origin='https://127.0.0.1:'+str(sock.getsockname()[1])
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    settings.partner_oauth_signing_key=base64.b64encode(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,serialization.NoEncryption())).decode()
    settings.partner_oauth_kid='synthetic-pilot/1'
    settings.partner_oauth_issuer=origin
    settings.partner_docs_sandbox_api_url=origin+'/api/v1'
    settings.app_public_url=origin
    state.update(origin=origin,pid=os.getpid(),status='starting',callback=callback,
        sourceRevision=subprocess.check_output(['git','-C',str(PROJECT),'rev-parse','HEAD'],text=True).strip())
    write_json(STATE,state)
    app=application(core_db.async_session_factory,settings,state)
    @asynccontextmanager
    async def lifespan(_app):
        yield
        await core_db.engine.dispose()
    app.router.lifespan_context=lifespan
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,access_log=False,log_level='critical',
        ssl_certfile=str(PRIVATE/'issuer.pem'),ssl_keyfile=str(PRIVATE/'issuer.key'),proxy_headers=False))
    task=asyncio.create_task(server.serve(sockets=[sock]))
    state['clients']={}
    try:
        for _ in range(200):
            if server.started: break
            if task.done(): await task
            await asyncio.sleep(.05)
        if not server.started: raise RuntimeError('HTTPS server did not start')
        tls=ssl.create_default_context(cafile=state['caPath'])
        async with httpx.AsyncClient(base_url=origin,verify=tls,trust_env=False) as client:
            async def call(method,path,expected=200,**kwargs):
                response=await client.request(method,path,**kwargs)
                if response.status_code!=expected:
                    raise RuntimeError(f'Fixture HTTP {method} {path.split("?")[0]} returned {response.status_code}')
                return response.json()
            fixture=state['fixture']
            logged=await call('POST','/api/auth/login',json={k:fixture['owner'][k] for k in ('email','password')})
            headers={'Authorization':'Bearer '+logged['access_token']}
            manifest={'origin':origin,'caPath':state['caPath'],'companyId':fixture['companyId'],
                'callback':callback,'caFile':state['caPath'],'runId':secrets.token_hex(12),
                'sourceRevision':state['sourceRevision'],'subjectKind':'company-owner','delegatedSubject':'synthetic-owner-admin', 'resources':{k:v for k,v in fixture.items() if k not in ('owner','employee')},'clients':{}}
            empty={'mode':'EMPTY','ids':[]}
            def selected(ids): return {'mode':'SET','ids':ids}
            async def register(name,scopes,method,resources,redirects):
                registered=await call('POST','/api/developer/clients',201,headers=headers,json={
                    'companyId':fixture['companyId'],'name':'Synthetic '+name,'scopes':scopes,
                    'authMethod':method,'redirectUris':redirects})
                cid=registered['clientId']
                await call('POST',f'/api/developer/clients/{cid}/status',headers=headers,json={'enabled':True})
                installed=await call('POST',f'/api/developer/clients/{cid}/installations',201,headers=headers,json={
                    'companyId':fixture['companyId'],'scopes':scopes,'locationIds':fixture['objects'][:2],
                    'resourceScopes':resources})
                owner={**registered,**installed}
                result={**registered,**installed,'resourceScopes':resources}
                if method=='client_secret_basic':
                    credential=await call('POST',f'/api/developer/clients/{cid}/credentials',201,headers=headers)
                    grant=await call('POST',f'/api/developer/installations/{installed["installationId"]}/machine-grants',201,
                        headers=headers,json={'scopes':scopes})
                    owner.update(credentialId=credential['credentialId'],**grant)
                    result.update(credential,**grant)
                state['clients'][name]=owner
                if name!='portal':
                    manifest['clients'][name]=result
                    write_json(PRIVATE/'client-manifest.json',manifest)
                write_json(STATE,state)
                return cid
            obj=selected(fixture['objects'][:2])
            await register('references',['objects:read','equipment:read','counterparties:read','contracts:read'],
                'client_secret_basic',{'objects':obj,'equipment':{'mode':'ALL','ids':[]},
                    'counterparties':selected(fixture['counterparties'][:2]), 'contracts':selected(fixture['contracts'][:2]),
                    'documents':empty},[callback])
            await register('monitoring',['objects:read','equipment:read','monitoring:read'],'client_secret_basic',
                {'objects':obj,'equipment':selected(fixture['equipment'][:2]),'counterparties':empty,'contracts':empty,'documents':empty},[callback])
            await register('documents',['openid','documents:read','documents.files:download'],'none',
                {'objects':obj,'equipment':empty,'counterparties':empty,'contracts':empty,
                    'documents':selected(fixture['documents'])},[callback])
            settings.partner_docs_client_id=await register('portal',['openid','docs:read','objects:read'],'none',
                {'objects':obj,'equipment':empty,'counterparties':empty,'contracts':empty,'documents':empty},
                [origin+'/developer/api/callback',origin+'/api/developer/docs/oauth2-redirect'])
            # Клиент портала issuer никогда не передаётся внешнему клиенту.
            manifest['rental']={**manifest['clients']['references'],'vectors':{k:fixture['vectors'][k] for k in ('objects','counterparties','contracts')}}
            manifest['operations']={**manifest['clients']['monitoring'],'vectors':{k:fixture['vectors'][k] for k in ('objects','equipment')},
                'afterNarrowObjects':fixture['objects'][:1]}
            manifest['documents']={**manifest['clients']['documents'],'redirectUri':callback,
                'vectors':{'documents':fixture['vectors']['documents']},'allowedContent':fixture['allowedContent'],'deniedContent':fixture['deniedContent']}
            write_json(PRIVATE/'client-manifest.json',manifest)
            discovery=await call('GET','/.well-known/openid-configuration')
            if discovery['issuer']!=origin: raise RuntimeError('Discovery issuer mismatch')
            unauth=await client.get('/api/v1/objects')
            docs_closed=await client.get('/api/developer/docs/assets/swagger-ui-bundle.js')
            if unauth.status_code!=401 or docs_closed.status_code!=401:
                raise RuntimeError('Anonymous protected surfaces did not reject access')
            state['verification']={'discoveryIssuer':True,'unauthProductStatus':401,'unauthDocsAssetStatus':401}
            state['status']='api-ready-building-ui'; write_json(STATE,state)
            print('API_READY '+origin+' CA='+state['caPath']+' CLIENT_MANIFEST='+str(PRIVATE/'client-manifest.json'),flush=True)
        # Используем дерево зависимостей root без установки и изменения пакетов.
        process=await asyncio.create_subprocess_exec('node',str(HERE/'build.mjs'),origin,str(PRIVATE/'front'),
            cwd=PROJECT,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
        communication=asyncio.create_task(process.communicate())
        done,_=await asyncio.wait([task,communication],return_when=asyncio.FIRST_COMPLETED)
        if task in done and not communication.done():
            process.terminate(); await communication
            return
        _,error=await communication
        if process.returncode:
            (PRIVATE/'build-error.log').write_bytes(error); (PRIVATE/'build-error.log').chmod(0o600)
            raise RuntimeError('React fixture build failed; see private build-error.log')
        async with httpx.AsyncClient(base_url=origin,verify=ssl.create_default_context(cafile=state['caPath']),trust_env=False) as client:
            callback_page=await client.get('/developer/api/callback',headers={'Accept':'text/html'})
            private_asset=await client.get('/assets/synthetic-denied.js')
            if callback_page.status_code!=200 or '/p/' not in callback_page.text or private_asset.status_code!=403:
                raise RuntimeError('Public callback/private gate fixture delivery failed')
        state['verification'].update(publicCallbackStatus=200,privateAssetWithoutGateStatus=403)
        state['status']='ready'; write_json(STATE,state)
        print('UI_READY OWNER_STATE='+str(STATE),flush=True)
        await task
    finally:
        server.should_exit=True
        await task
        sock.close()
        await core_db.engine.dispose()
        latest=json.loads(STATE.read_text())
        latest['status']='stopped'; write_json(STATE,latest)



async def cleanup(database,upload,state):
    import asyncpg
    import shutil
    if (state.get('status') not in ('stopped','initializing') or state.get('databaseOwned') is not True
            or state.get('uploadDir')!=str(upload)):
        raise RuntimeError('Cleanup requires the stopped owned fixture and matching test upload directory')
    admin=await asyncpg.connect(database.replace('postgresql+asyncpg:','postgresql:').rsplit('/',1)[0]+'/postgres')
    try:
        # Без FORCE: активное соединение владельца или клиента запрещает очистку.
        await admin.execute('DROP DATABASE api_partner_pilots_test')
    finally:
        await admin.close()
    if upload.exists(): shutil.rmtree(upload)
    for child in PRIVATE.iterdir():
        if child.is_dir(): shutil.rmtree(child)
        else: child.unlink()
    write_json(PRIVATE/'cleanup-summary.json',{'status':'cleaned','database':'api_partner_pilots_test',
        'uploadsRemoved':True,'privateKeysRemoved':True})
    print('OWNED_SANDBOX_CLEANED')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','init','serve','stop','cleanup'])
    parser.add_argument('--callback')
    parser.add_argument('--resume-seed',action='store_true')
    args=parser.parse_args()
    if args.action=='prepare':
        state=prepare()
        print('TLS_READY OWNER_STATE='+str(STATE)+' CA='+state['caPath'])
        return
    if args.action=='stop':
        state=json.loads(STATE.read_text())
        pid=state.get('pid')
        if state.get('status')=='stopped' or not pid: return
        # Нельзя отправлять сигнал повторно использованному PID чужой программы.
        if str(HERE/'server.py') not in Path('/proc/'+str(pid)+'/cmdline').read_bytes().decode().replace('\0',' '):
            raise RuntimeError('Recorded PID is not the owned sandbox')
        os.kill(pid,signal.SIGTERM)
        return
    authorization=None
    if args.action in ('init','cleanup'):
        validate(ddl=True)
        authorization=os.environ['PARTNER_SANDBOX_SQL_WINDOW']
    database,upload,settings=configure()
    state=prepare()
    if authorization: state['sqlWindowReference']=authorization
    if args.action=='cleanup': asyncio.run(cleanup(database,upload,state))
    elif args.action=='init': asyncio.run(initialize(database,upload,state,resume=args.resume_seed))
    else:
        if not args.callback: parser.error('--callback required')
        asyncio.run(serve(database,upload,settings,state,args.callback))

if __name__=='__main__':
    try: main()
    except (ValueError,RuntimeError) as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr); sys.exit(1)
    except Exception:
        import traceback
        private_dir()
        target=PRIVATE/'owner-error.log'
        target.write_text(traceback.format_exc()); target.chmod(0o600)
        print('Sandbox failed; details saved to private owner-error.log',file=sys.stderr); sys.exit(1)
