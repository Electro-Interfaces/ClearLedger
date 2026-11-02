"""ROOT-only SQL/HTTP characterization of the three project commands."""
import os
import sys
if os.environ.get("RUN_PROJECT_WORKSPACE_COMMAND_OWNER_TESTS") != "1":
    raise RuntimeError("ROOT-approved project command runner required")

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.auth import create_access_token
from app.deps import _active_company
from app.main import app
from app.models import (AuditEvent, ChatMessage, ChatParticipant, ChatRoom, DocCard, DocKind,
    DocRelation, DocVersion, EzsSite, EzsSiteDoc, EzsSiteEvent, SourceFile, Task, TaskEvent, UserCompany)
from app.routers import chat_router, project_workspace_router as native, work_contexts_router
from app.schemas_project_workspace import DecisionBody, FileBody, LinkBody
from app.services import chat_access, file_store, project_work_context
from app.services import project_workspace_commands as owner
from tests.test_task_projection_access import actors  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")

def fixed(group, n):
    return uuid.UUID(f"{group}7100000-0000-4000-8000-{n:012x}")
SID, FOREIGN_SID = fixed('e', 1), fixed('e', 2)
TIDS = {n: fixed('a', i) for i,n in enumerate(('editable','readonly','hidden','personal','bound','conflict'),1)}
DIDS = {n: fixed('d', i) for i,n in enumerate(('editable','hidden','bound'),1)}
MIDS = {n: fixed('b', i) for i,n in enumerate(('plain','file','nofile','badfile','foreignfile','missingfile','deleted','foreignroom'),1)}
RIDS = [fixed('c', i) for i in (1,2)]
FIDS = [fixed('f', i) for i in (1,2,3)]
AT = datetime(2026,10,31,12,tzinfo=timezone.utc)

@pytest.fixture
async def world(actors, db, tmp_path):
    companies, users, _, _ = actors
    cid, other = [c.id for c in companies]
    for user in users.values(): user.last_seen_at = datetime.now(timezone.utc)
    sites = [EzsSite(id=SID, company_id=cid, title="P7 own", kind="new_build", stage="decision",
                    owner_user_id=users['author'].id, workspace_data={"budget":7,"target_date":"2026-12-01"}),
             EzsSite(id=FOREIGN_SID, company_id=other, title="P7 foreign", kind="new_build", stage="decision")]
    path=tmp_path/'p7.txt'; path.write_bytes(b'P7 synthetic file bytes\n')
    files=[SourceFile(id=FIDS[i],company_id=other if i==1 else cid,file_name='p7.txt',
        mime_type='text/plain',size=path.stat().st_size,purpose='attachment',
        storage_path=str(tmp_path/'absent.txt') if i==2 else str(path)) for i in range(3)]
    rooms=[ChatRoom(id=RIDS[i], company_id=c.id,type='group',name='P7 room',is_active=True) for i,c in enumerate(companies)]
    db.add_all([*sites,*files,*rooms]); await db.flush()
    for role in ('author','watcher','admin'):
        db.add(ChatParticipant(room_id=RIDS[0],user_id=users[role].id,role='member'))
    messages=[]
    for name in MIDS:
        file_url = f'/api/files/{FIDS[0]}' if name=='file' else f'/api/files/{FIDS[1]}' if name=='foreignfile' else f'/api/files/{FIDS[2]}' if name=='missingfile' else '/api/files/not-a-uuid' if name=='badfile' else None
        messages.append(ChatMessage(id=MIDS[name],room_id=RIDS[int(name=='foreignroom')],user_id=users['author'].id,
            user_name='P7 author',content='P7 message',type='file' if file_url else 'text',file_url=file_url,
            created_at=AT,deleted_at=AT if name=='deleted' else None))
    tasks=[]
    for name in TIDS:
        tasks.append(Task(id=TIDS[name],company_id=cid,title='P7 '+name,
            author_id=users['watcher' if name=='personal' else 'author'].id,
            visibility='private' if name=='hidden' else 'personal' if name=='personal' else 'company',
            subject_ref=f'site:{SID}' if name=='bound' else 'site:else' if name=='conflict' else None))
    kind=DocKind(company_id=cid,code='p7',name='P7 kind'); db.add(kind); await db.flush()
    docs=[DocCard(id=DIDS[n],company_id=cid,kind_id=kind.id,title='P7 '+n,
        author_id=users['author'].id,confidentiality='strict' if n=='hidden' else 'company') for n in DIDS]
    db.add_all([*messages,*tasks,*docs]); await db.flush()
    db.add(DocRelation(company_id=cid,doc_id=DIDS['bound'],kind='related',target_ref=f'site:{SID}'))
    await db.commit()
    _active_company.set(None)
    yield NS(cid=cid,other=other,users=users,sites=sites,path=path)
    _active_company.set(None)
    await db.execute(delete(EzsSite).where(EzsSite.id.in_([SID,FOREIGN_SID])))
    await db.execute(delete(Task).where(Task.id.in_(TIDS.values())))
    await db.execute(delete(DocCard).where(DocCard.id.in_(DIDS.values())))
    await db.execute(delete(ChatRoom).where(ChatRoom.id.in_(RIDS)))
    await db.execute(delete(SourceFile).where(SourceFile.id.in_(FIDS)))
    await db.commit()

async def stored(db):
    return {m.__tablename__: sorted(repr(tuple(r)) for r in (await db.execute(select(m.__table__))).all())
        for m in (EzsSite,EzsSiteEvent,EzsSiteDoc,Task,TaskEvent,DocCard,DocRelation,DocVersion,SourceFile,AuditEvent)}

def headers(w, role='watcher'):
    u=w.users[role]
    return {'Authorization':'Bearer '+create_access_token(str(u.id),u.email),'X-Company-Id':str(w.cid)}

async def invoke(w, db, command, *, surface='direct', payload=None, role='watcher', sid=SID):
    payload=payload or {'discussion':{'kind':'message','id':str(MIDS['plain'])},
        'decision':{'text':' P7 decision ','source_message_id':str(MIDS['plain'])},
        'file':{'message_id':str(MIDS['file'])}}[command]
    user=w.users[role]
    if surface=='direct':
        fn, dto={'discussion':(owner.link_work,LinkBody),'decision':(owner.record_decision,DecisionBody),
                 'file':(owner.attach_message_file,FileBody)}[command]
        try: return (201 if command!='discussion' else 200), await fn(db,str(w.cid),user,sid,dto(**payload))
        except HTTPException as e: return e.status_code,{'detail':e.detail}
    if surface=='context-direct':
        b=work_contexts_router.ActionBody(ref=f'site:{sid}',action=command,
            message_id=MIDS['file' if command=='file' else 'plain'],text=payload.get('text'))
        try: return 200, await project_work_context.ProjectsContext().execute(db,w.cid,user,str(sid),b)
        except HTTPException as e:return e.status_code,{'detail':e.detail}
    route={'discussion':'link','decision':'decision','file':'file'}[command]
    url=f'/api/project-workspace/{sid}/{route}'
    if surface=='context':
        url='/api/work-contexts/action'
        payload={'ref':f'site:{sid}','action':command,'message_id':str(MIDS['file' if command=='file' else 'plain']), 'text':payload.get('text')}
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as c:
        r=await c.post(url,params={'company_id':str(w.cid)},headers=headers(w,role),json=payload)
    return r.status_code,r.json()

@pytest.mark.parametrize('surface',['native','direct','context','context-direct'])
@pytest.mark.parametrize('command',['discussion','decision','file'])
async def test_three_commands_repeat_fixed_outputs_events_audit_bytes(world,db,monkeypatch,pytestconfig,surface,command):
    w=world; before_hash=hashlib.sha256(w.path.read_bytes()).hexdigest()
    boundary=pytestconfig._project_workspace_command_owner_boundary; sent=len(boundary.capture)
    # Association validates a source path; it does not read/write/copy file bytes.
    monkeypatch.setattr(file_store,'read',Mock(side_effect=AssertionError('association read bytes')))
    trace=[]; original_commit=AsyncSession.commit
    command_codes={fn.__code__ for fn in (owner.link_work,owner.record_decision,owner.attach_message_file)}
    dependency_code=database.get_db.__code__
    async def commit(session,*args,**kwargs):
        caller=sys._getframe(1).f_code
        if caller in command_codes:trace.append('owner-commit')
        elif caller is dependency_code:trace.append('dependency-commit')
        else:raise AssertionError('unexpected commit caller inside command/request window')
        return await original_commit(session,*args,**kwargs)
    def sql(conn,cursor,statement,parameters,context,executemany):
        if 'ezs_sites' in statement and 'FOR UPDATE' in statement:trace.append('site-lock')
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession,'commit',commit)
        event.listen(Engine,'before_cursor_execute',sql)
        try:results=[await invoke(w,db,command,surface=surface) for _ in range(2)]
        finally:event.remove(Engine,'before_cursor_execute',sql)
    request_trace=['site-lock','owner-commit']+(['dependency-commit'] if surface in ('native','context') else [])
    assert trace==request_trace*2
    assert trace.count('owner-commit')==2
    assert trace.count('dependency-commit')==(2 if surface in ('native','context') else 0)
    status=200 if surface.startswith('context') or command=='discussion' else 201
    assert [r[0] for r in results]==[status,status],results
    events=(await db.scalars(select(EzsSiteEvent).where(EzsSiteEvent.site_id==SID).order_by(EzsSiteEvent.created_at,EzsSiteEvent.id))).all()
    assert len(events)==(2 if command=='decision' else 1)
    assert {e.kind for e in events}=={'discussion' if command=='discussion' else 'decision' if command=='decision' else 'note'}
    if command=='discussion': assert [r[1] for r in results]==[{'ok':True},{'ok':True}]
    elif command=='file':
        assert results[0][1]==results[1][1]
        link=await db.get(EzsSiteDoc,uuid.UUID(results[0][1]['id']))
        assert (link.site_id,link.file_id,link.kind,link.stage,link.note)==(SID,FIDS[0],'other','decision',f'chat:{MIDS["file"]}')
    else:
        assert {uuid.UUID(r[1]['id']) for r in results}=={e.id for e in events}
        assert [e.text for e in events]==['P7 decision','P7 decision']
    audits=(await db.scalars(select(AuditEvent).where(AuditEvent.company_id==w.cid))).all()
    assert [a.action for a in audits]==(['project.decision','project.decision'] if command=='decision' else [])
    assert boundary.capture[sent:]==(['app.services.notify.dispatch_async']*2 if command=='decision' else [])
    assert hashlib.sha256(w.path.read_bytes()).hexdigest()==before_hash
    assert await db.scalar(select(func.count()).select_from(DocVersion).where(DocVersion.company_id==w.cid))==0

@pytest.mark.parametrize('command',['discussion','decision','file'])
@pytest.mark.parametrize('policy',['member','admin','revoked','foreignsite'])
async def test_current_membership_role_and_site_tenant(world,db,command,policy):
    w=world; member=await db.get(UserCompany,(w.users['watcher'].id,w.cid))
    if policy=='revoked':await db.delete(member)
    else:
        member.role='admin' if policy=='admin' else 'user'
        member.object_scope=['outside-p7']  # Existing site lookup has no location scope clause.
    await db.commit(); before=await stored(db)
    expected=403 if policy=='revoked' else 404 if policy=='foreignsite' else 200 if command=='discussion' else 201
    for surface in ('native','direct'):
        status,body=await invoke(w,db,command,surface=surface,sid=FOREIGN_SID if policy=='foreignsite' else SID)
        assert status==expected,(surface,status,body)
        if expected>=400:
            assert body=={'detail':'Нет доступа к компании' if policy=='revoked' else 'Проект не найден'}
            assert await stored(db)==before

@pytest.mark.parametrize('kind,name,role,status',[
    ('task','editable','author',200),('task','readonly','watcher',403),('task','hidden','watcher',404),
    ('task','personal','watcher',404),('task','conflict','author',409),('doc','editable','author',200),
    ('doc','editable','watcher',403),('doc','hidden','watcher',403),
])
async def test_link_write_authority_and_repeat_counts(world,db,kind,name,role,status):
    w=world; eid=(TIDS if kind=='task' else DIDS)[name]; before=await stored(db)
    for surface in ('native','direct'):
        if surface=='direct' and (kind,name,role,status)==('task','editable','author',200):
            # A separate HTTP session committed; initialize this fixture caller
            # from persisted state, without changing command freshness policy.
            assert await db.scalar(select(Task.subject_ref).where(Task.id==eid))==f'site:{SID}'
            assert await db.scalar(select(func.count()).select_from(TaskEvent).where(TaskEvent.task_id==eid))==1
            await db.refresh(await db.get(Task,eid))
            assert (await db.get(Task,eid)).subject_ref==f'site:{SID}'
        code,body=await invoke(w,db,'discussion',surface=surface,payload={'kind':kind,'id':str(eid)},role=role)
        assert code==status,(surface,body)
        if status!=200:assert await stored(db)==before
    if status==200:
        events=(await db.scalars(select(EzsSiteEvent).where(EzsSiteEvent.site_id==SID))).all()
        assert [(e.kind,e.text) for e in events]==[('note','Связана работа Трека')]*2
        if kind=='task':
            assert (await db.get(Task,eid)).subject_ref==f'site:{SID}'
            assert await db.scalar(select(func.count()).select_from(TaskEvent).where(TaskEvent.task_id==eid))==1
        else:
            assert await db.scalar(select(func.count()).select_from(DocRelation).where(DocRelation.doc_id==eid,DocRelation.kind=='basis',DocRelation.target_ref==f'site:{SID}'))==1

@pytest.mark.parametrize('kind,name,status', [('task','bound',201),('doc','bound',201),('task','readonly',400),('task','hidden',404)])
async def test_decision_uses_read_and_link_not_edit_authority(world,db,kind,name,status):
    w=world; eid=(TIDS if kind=='task' else DIDS)[name]
    before=await stored(db)
    for surface in ('native','direct'):
        code,body=await invoke(w,db,'decision',surface=surface,payload={'text':'P7 linked decision','work':{'kind':kind,'id':str(eid)}})
        assert code==status,(surface,body)
        if status!=201:assert await stored(db)==before
    if status==201:
        assert await db.scalar(select(func.count()).select_from(EzsSiteEvent).where(EzsSiteEvent.site_id==SID,EzsSiteEvent.kind=='decision'))==2

@pytest.mark.parametrize('name,status,detail',[
    ('nofile',400,'В сообщении нет файла'),('badfile',400,'Вложение недоступно для переноса'),
    ('foreignfile',404,'Вложение не найдено'),('missingfile',409,'Файл отсутствует в хранилище. Восстановите вложение и повторите'),
    ('deleted',404,'Сообщение не найдено'),('foreignroom',404,'Чат не найден')])
async def test_source_file_negative_goldens_no_mutation(world,db,name,status,detail):
    before=await stored(db)
    for surface in ('native','direct'):
        code,body=await invoke(world,db,'file',surface=surface,payload={'message_id':str(MIDS[name])})
        assert (code,body)==(status,{'detail':detail})
        assert await stored(db)==before

@pytest.mark.parametrize('cutoff',[None,'before','equal','after'])
async def test_source_selected_company_history_and_current_participation(world,db,cutoff):
    w=world; p=await db.get(ChatParticipant,await db.scalar(select(ChatParticipant.id).where(ChatParticipant.room_id==RIDS[0],ChatParticipant.user_id==w.users['watcher'].id)))
    p.history_from=None if cutoff is None else AT+timedelta(seconds={'before':1,'equal':0,'after':-1}[cutoff]);await db.commit()
    before=await stored(db)
    for source in (native.source_message,owner.source_message):
        if cutoff=='before':
            with pytest.raises(HTTPException) as e:await source(db,w.cid,w.users['watcher'],MIDS['plain'])
            assert (e.value.status_code,e.value.detail)==(404,'Сообщение не найдено')
        else:assert (await source(db,w.cid,w.users['watcher'],MIDS['plain'])).id==MIDS['plain']
        token=_active_company.set(str(w.other))
        try:
            with pytest.raises(HTTPException) as e:await source(db,w.cid,w.users['watcher'],MIDS['plain'])
            assert (e.value.status_code,e.value.detail)==(403,'Нет доступа к компании')
        finally:_active_company.reset(token)
    assert await stored(db)==before
    await db.delete(p);await db.commit();before=await stored(db)
    for source in (native.source_message,owner.source_message):
        with pytest.raises(HTTPException) as e:await source(db,w.cid,w.users['watcher'],MIDS['plain'])
        assert (e.value.status_code,e.value.detail)==(404,'Чат не найден')
    assert await stored(db)==before

@pytest.mark.parametrize('surface',['native','direct'])
async def test_foreign_audit_then_decision_audit_notify_before_single_commit(world,db,monkeypatch,pytestconfig,surface):
    w=world; user=w.users['superadmin']; before=len(pytestconfig._project_workspace_command_owner_boundary.capture)
    chat_access.FOREIGN_SEEN.clear(); trace=[]
    original=owner.ezs_site_work.log_event
    async def event(*a,**kw):
        assert await a[0].scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.company_id==w.cid,AuditEvent.action=='chat.foreign_access'))==1
        trace.append('decision');return await original(*a,**kw)
    monkeypatch.setattr(owner.ezs_site_work,'log_event',event)
    commit=AsyncMock(wraps=db.commit);monkeypatch.setattr(db,'commit',commit)
    code,_=await invoke(w,db,'decision',surface=surface,role='superadmin')
    assert code==201 and trace==['decision']
    audits=(await db.scalars(select(AuditEvent).where(AuditEvent.company_id==w.cid).order_by(AuditEvent.timestamp,AuditEvent.id))).all()
    assert sorted(a.action for a in audits)==['chat.foreign_access','project.decision']
    assert pytestconfig._project_workspace_command_owner_boundary.capture[before:]==['app.services.notify.dispatch_async']*2
    if surface=='direct':commit.assert_awaited_once()

async def test_context_direct_binding_scenario_text_and_file_repeat_kind(world,db,monkeypatch):
    w=world
    for name in ('link','decision','attach_file','LinkBody','DecisionBody','FileBody'):
        monkeypatch.setattr(native,name,Mock(side_effect=AssertionError('obsolete router binding')))
    assert (await invoke(w,db,'discussion',surface='context-direct'))[0]==200
    assert (await invoke(w,db,'decision',surface='context-direct'))[0]==200
    one=await invoke(w,db,'file',surface='context-direct')
    two=await invoke(w,db,'file',payload={'message_id':str(MIDS['file']),'kind':'reclassified'})
    assert one[1]==two[1] and (await db.get(EzsSiteDoc,uuid.UUID(one[1]['id']))).kind=='other'
    provider=project_work_context.ProjectsContext()
    body=work_contexts_router.ActionBody(ref=f'site:{SID}',action='decision',message_id=MIDS['plain'],text='   ')
    with pytest.raises(HTTPException) as e:await provider.execute(db,w.cid,w.users['watcher'],str(SID),body)
    assert (e.value.status_code,e.value.detail)==(400,'Сформулируйте решение')
    # Native/owner DTO accepts length-three whitespace, then strips it. Preserve this discrepancy.
    code,result=await invoke(w,db,'decision',payload={'text':'   ','budget':0,'deadline':'2027-01-01'})
    assert code==201 and (await db.get(EzsSiteEvent,uuid.UUID(result['id']))).text==''
    await db.refresh(w.sites[0]);assert w.sites[0].workspace_data=={'budget':0,'target_date':'2027-01-01'}
    monkeypatch.setattr(provider,'resolve',AsyncMock(return_value={'actions':[]}))
    with pytest.raises(HTTPException) as e:await provider.execute(db,w.cid,w.users['watcher'],str(SID),body)
    assert (e.value.status_code,e.value.detail)==(403,'Действие отключено в сценарии приложения')

@pytest.mark.parametrize('command',['discussion','decision','file'])
@pytest.mark.parametrize('profile',['native','service'])
async def test_concrete_falsey_hooks_lock_event_commit_order(monkeypatch,command,profile):
    trace=[]; uid=fixed('9',1); mid=MIDS['plain']; cid=fixed('9',2)
    user=NS(id=uid);site=NS(id=SID,stage='decision');msg=NS(id=mid,room_id=RIDS[0]);source=NS(id=FIDS[0],file_name='P7.txt')
    class Falsey:
        def __init__(self,fn):self.fn=fn
        def __bool__(self):return False
        async def __call__(self,*a,**kw):return await self.fn(*a,**kw)
    async def member(ref,u,d):assert (ref,u)==(str(cid),user);trace.append('member');return cid
    async def lookup(d,c,s,*,lock=False):assert (c,s,lock)==(cid,SID,True);trace.append('owned-lock');return site
    async def message(d,c,u,m):assert (c,u,m)==(cid,user,mid);trace.append('source');return msg
    async def event(*a,**kw):trace.append('event:'+a[2]);return NS(id=fixed('9',3))
    async def file(*a):trace.append('file');return source
    class DB:
        def __init__(self):self.added=[]
        async def scalar(self,q):trace.append('select');return None
        def add(self,row):trace.append('add');self.added.append(row)
        async def commit(self):
            trace.append('commit')
            for row in self.added:row.id=fixed('9',4)
    db=DB()
    monkeypatch.setattr(owner.ezs_site_work,'log_event',event)
    monkeypatch.setattr(owner.track_files,'message_file',file)
    module=native if profile=='native' else owner
    for name,fn in [('assert_company_member',member),('owned',lookup),('source_message',message)]:monkeypatch.setattr(module,name,Falsey(fn))
    body={'discussion':LinkBody(kind='message',id=mid),'decision':DecisionBody(text='P7 decision',source_message_id=mid),'file':FileBody(message_id=mid)}[command]
    fn=({'discussion':native.link,'decision':native.decision,'file':native.attach_file} if profile=='native' else
        {'discussion':owner.link_work,'decision':owner.record_decision,'file':owner.attach_message_file})[command]
    result=await fn(SID,body,str(cid),user,db) if profile=='native' else await fn(db,str(cid),user,SID,body)
    expected={'discussion':['member','owned-lock','source','select','event:discussion','commit'],
        'decision':['member','owned-lock','source','event:decision','commit'],
        'file':['member','owned-lock','source','file','select','add','event:note','commit']}[command]
    assert trace==expected
    assert result==({'ok':True} if command=='discussion' else {'id':str(fixed('9',3 if command=='decision' else 4))})
    trace.clear()
    async def denied(*a,**kw):trace.append('member-deny');raise HTTPException(403,'old membership')
    monkeypatch.setattr(module,'assert_company_member',Falsey(denied))
    with pytest.raises(HTTPException) as caught:
        await fn(SID,body,str(cid),user,db) if profile=='native' else await fn(db,str(cid),user,SID,body)
    assert caught.value.detail=='old membership' and trace==['member-deny']

@pytest.mark.parametrize('profile',['native','service'])
async def test_source_concrete_chat_hooks_falsey_and_history_first(monkeypatch,profile):
    trace=[];user=NS(id=fixed('9',5));cid=fixed('9',6);msg=NS(room_id=RIDS[0],deleted_at=None,created_at=AT)
    class DB:
        async def get(self,model,mid):trace.append('get');return msg
    class Falsey:
        def __init__(self,fn):self.fn=fn
        def __bool__(self):return False
        async def __call__(self,*a):return await self.fn(*a)
    async def participant(*a):trace.append('participant');return NS(company_id=fixed('9',7))
    async def history(*a):trace.append('history');return AT+timedelta(seconds=1)
    module=chat_router if profile=='native' else chat_access
    monkeypatch.setattr(module,'_assert_participant' if profile=='native' else 'assert_participant',Falsey(participant))
    monkeypatch.setattr(module,'_history_from' if profile=='native' else 'history_from',Falsey(history))
    with pytest.raises(HTTPException) as caught:
        await (native.source_message if profile=='native' else owner.source_message)(DB(),cid,user,MIDS['plain'])
    assert (caught.value.status_code,caught.value.detail)==(404,'Сообщение не найдено')
    assert trace==['get','participant','history']  # cutoff happens before foreign-room company check.

async def test_runtime_dto_identity_fields_validation_and_native_openapi():
    assert native.LinkBody is LinkBody and native.DecisionBody is DecisionBody and native.FileBody is FileBody
    assert LinkBody.model_json_schema()=={
        'properties':{'kind':{'enum':['doc','task','message'],'title':'Kind','type':'string'},
                      'id':{'format':'uuid','title':'Id','type':'string'}},
        'required':['kind','id'],'title':'LinkBody','type':'object'}
    assert FileBody.model_json_schema()=={
        'properties':{'message_id':{'format':'uuid','title':'Message Id','type':'string'},
                      'kind':{'default':'other','maxLength':24,'title':'Kind','type':'string'}},
        'required':['message_id'],'title':'FileBody','type':'object'}
    schema=DecisionBody.model_json_schema()
    assert schema['required']==['text']
    assert schema['properties']['text']=={'minLength':3,'maxLength':4000,'title':'Text','type':'string'}
    assert schema['properties']['budget']=={'anyOf':[{'minimum':0,'type':'number'},{'type':'null'}],'default':None,'title':'Budget'}
    assert schema['properties']['deadline']=={'anyOf':[{'format':'date','type':'string'},{'type':'null'}],'default':None,'title':'Deadline'}
    assert DecisionBody(text='abc').model_dump()=={'text':'abc','source_message_id':None,'work':None,'deadline':None,'budget':None}
    for dto,payload,field,kind in [(LinkBody,{'kind':'other','id':str(SID)},'kind','literal_error'),
            (FileBody,{'message_id':str(SID),'kind':None},'kind','string_type'),
            (FileBody,{'message_id':str(SID),'kind':'x'*25},'kind','string_too_long'),
            (DecisionBody,{'text':'ab'},'text','string_too_short'),
            (DecisionBody,{'text':'abc','budget':-1},'budget','greater_than_equal'),
            (DecisionBody,{'text':'abc','budget':float('inf')},'budget','finite_number')]:
        with pytest.raises(ValidationError) as e:dto(**payload)
        assert [(x['loc'],x['type']) for x in e.value.errors()]==[((field,),kind)]
    native_app=FastAPI()
    native_app.include_router(native.router,prefix="/api")
    spec=native_app.openapi()
    for path,body,status,operation in [('link','LinkBody','200','link'),('decision','DecisionBody','201','decision'),('file','FileBody','201','attach_file')]:
        route=spec['paths']['/api/project-workspace/{sid}/'+path]['post']
        assert route['operationId']==operation+'_api_project_workspace__sid__'+path+'_post'
        assert route['requestBody']['content']['application/json']['schema']=={'$ref':'#/components/schemas/'+body}
        assert route['requestBody']['required'] is True and set(route['responses'])=={status,'422'}
        assert [(p['name'],p['in'],p['required']) for p in route['parameters']]==[('sid','path',True),('company_id','query',True)]
        assert route['responses'][status]['content']['application/json']['schema']=={}
    # The exact original DTO annotations are shared by adjacent unchanged handlers.
    assert native.NextBody.model_fields['work'].annotation==LinkBody|None
    assert native.ScenarioBody.model_fields['evidence'].annotation==LinkBody|None
