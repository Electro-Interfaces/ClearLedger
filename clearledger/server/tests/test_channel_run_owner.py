"""Fixed-output lifecycle and native HTTP characterization; ROOT-only disposable SQL."""
import os
if os.environ.get('RUN_CHANNEL_RUN_OWNER_TESTS') != '1':
    raise RuntimeError('ROOT channel run owner gate required')

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, text

from app.auth import create_access_token
from app.database import get_db
from app.models import (AuditEvent, Channel, ChannelStream, ChannelSyncLog, Counterparty,
    DataEntry, EventSubscription, OutboxEvent, ServiceLocation, Source, SourceFile,
    StationContractSettlement, User, UserCompany)
from app.routers import channels_router as native
from app.services import channel_runs as owner, channel_scheduler, channel_orchestrator
from tests import channel_run_owner_support as support

pytestmark = pytest.mark.asyncio(loop_scope='session')
CHID = uuid.UUID('b1100000-0000-4000-8000-000000000011')
FOREIGN = uuid.UUID('b1100000-0000-4000-8000-000000000012')
LID = uuid.UUID('b1100000-0000-4000-8000-000000000021')
UID = uuid.UUID('b1100000-0000-4000-8000-000000000031')
SID = uuid.UUID('b1100000-0000-4000-8000-000000000041')
FID = uuid.UUID('b1100000-0000-4000-8000-000000000051')
MISSING = uuid.UUID('b1100000-0000-4000-8000-000000000099')
AT = datetime(2026, 10, 31, 12, 30, tzinfo=timezone.utc)


class FalseyCallable:
    def __init__(self, fn): self.fn = fn
    def __bool__(self): return False
    def __call__(self, *a, **kw): return self.fn(*a, **kw)


@pytest_asyncio.fixture(loop_scope='session')
async def world(setup_database, monkeypatch):
    factory = setup_database
    await support.reset_world(factory)
    async with factory() as db:
        db.add_all([Channel(id=CHID, company_id=support.CID, name='P11 канал', docs_loaded=7),
                    Channel(id=FOREIGN, company_id=support.OTHER, name='P11 чужой канал', docs_loaded=19),
                    User(id=UID, company_id=support.CID, name='P11 участник',
                         email='p11@example.test', password_hash='!synthetic', last_seen_at=datetime.now(timezone.utc))])
        await db.flush()
        db.add(UserCompany(user_id=UID, company_id=support.CID, role='user', party_type='internal'))
        await db.commit()
    monkeypatch.setattr(owner, 'async_session_factory', factory)
    monkeypatch.setattr(native, 'async_session_factory', factory)
    monkeypatch.setattr(channel_scheduler, 'async_session_factory', factory)
    trace = support.TRACE
    start = len(trace.timeline)
    yield NS(factory=factory, trace=trace, start=start)


async def running(world, log_id=LID):
    async with world.factory() as db:
        db.add(ChannelSyncLog(id=log_id, channel_id=CHID, status='running',
                              finished_at=None, date_from='2026-10-01', date_to='2026-10-31'))
        await db.commit()


async def snapshot(world, log_id=LID):
    async with world.factory() as db:
        log = await db.get(ChannelSyncLog, log_id)
        ch = await db.get(Channel, CHID)
        other = await db.get(Channel, FOREIGN)
        audits = (await db.execute(select(AuditEvent).where(AuditEvent.company_id == support.CID))).scalars().all()
        return NS(log=log, ch=ch, other=other, audits=audits)


async def call(world, monkeypatch, path, result, *, log_id=LID, channel_id=CHID):
    seen = []
    async def orchestrate(db, ch, **kw):
        seen.append((ch.id, kw))
        world.trace.record('orchestrate')
        if result in ('exception', 'cancel'):
            db.add(Counterparty(company_id=support.CID, name='P11 partial', inn=''))
            await db.flush()
            if result == 'cancel':
                world.cancel_started.set()
                await world.cancel_release.wait()
                raise AssertionError('cancel barrier unexpectedly released')
            raise ValueError('P11 controlled failure')
        return result
    if path == 'native':
        monkeypatch.setattr(native, 'orchestrate_channel', orchestrate)
        await native._run_channel_background(channel_id, '2026-10-01', '2026-10-31', log_id, [501], True, 'replace')
    else:
        await owner.run_channel_background(channel_id, '2026-10-01', '2026-10-31', log_id, [501], True, 'replace',
            session_factory=world.factory, orchestrate_channel=orchestrate)
    return seen


@pytest.mark.parametrize('result,total,summary', [
    ({}, 0, 'загружено 0'),
    ({'created':'7','errors':2}, 7, 'загружено 7, ошибок 2'),
    ({'created':99,'by_station':[]}, 0, 'загружено 0'),
    ({'created':99,'by_station':[{'created':'2'},{'created':None}], 'stations_total':4, 'stations_ok':1},
     2, 'загружено 2, станций 1/4'),
    ({'created':3,'message':'ошибка уже описана','errors':2}, 3, 'ошибка уже описана'),
    ({'created':None,'stations_total':0}, 0, 'загружено 0, станций ?/0'),
], ids=['empty','top-errors','empty-list-priority','stations','existing-error','zero-total'])
async def test_fixed_totals_and_summaries(result, total, summary):
    assert owner.loaded_total(result) == native._loaded_total(result) == total
    assert owner.run_summary(result) == native._run_summary(result) == summary


@pytest.mark.parametrize('result,error', [({'created':'bad'}, ValueError),
    ({'created':{'bad':1}}, TypeError), ({'by_station':[{'created':'bad'}]}, ValueError),
    ({'errors':'bad'}, ValueError)], ids=['top-int','top-type','station-int','error-int'])
async def test_malformed_counters_keep_errors(result, error):
    for summary in (owner.run_summary, native._run_summary):
        with pytest.raises(error): summary(result)


RESULTS = {
    'stations': {'created':99,'by_station':[{'created':'2','skipped':'3'},
        {'created':None,'skipped':1,'duplicates':'2','error':'station failed'}],
        'stations_total':4,'stations_ok':1,'errors':2},
    'empty-list': {'created':88,'by_station':[],'skipped':3,'duplicates':4,'errors':2},
    'skipped': {'status':'skipped','message':'нет источника'},
    'unmatched': {'status':'success','created':5,'unmatched_sessions':1},
    'exception': 'exception',
    'missing-log': {'status':'skipped','created':3,'message':'без log'},
}
GOLDENS = {
    'stations': ('success', 2, 4, 2, 1, 'info', 'загружено 2, станций 1/4, ошибок 2', 'channel.run.finished'),
    'empty-list': ('success', 0, 3, 4, 2, 'info', 'загружено 0, ошибок 2', 'channel.run.finished'),
    'skipped': ('partial', 0, 0, 0, 0, 'info', 'нет источника', 'channel.run.partial'),
    'unmatched': ('partial', 5, 0, 0, 0, 'error', 'загружено 5', 'channel.run.partial'),
    'exception': ('error', 0, 0, 0, 0, 'error', 'ValueError: P11 controlled failure', 'channel.run.failed'),
}


@pytest.mark.parametrize('path', ['native','direct'])
@pytest.mark.parametrize('case', list(RESULTS), ids=list(RESULTS))
async def test_sql_lifecycle_fixed_goldens(world, monkeypatch, path, case):
    if case != 'missing-log': await running(world)
    begin = len(world.trace.timeline)
    seen = await call(world, monkeypatch, path, RESULTS[case])
    assert seen == [(CHID, dict(date_from='2026-10-01', date_to='2026-10-31', log_id=LID,
                               station_codes=[501], all_period=True, mode='replace'))]
    tail = world.trace.timeline[begin:]
    assert tail.count('dispatch') == 1 and tail.index('dispatch') < tail.index('commit')
    state = await snapshot(world)
    assert state.other.docs_loaded == 19 and state.other.last_sync_at is None
    assert state.ch.last_sync_at is not None and len(state.audits) == 1
    audit = state.audits[0]
    assert (audit.user_id, audit.user_name) == ('system', 'Платформа')
    if case == 'missing-log':
        assert state.log is None and state.ch.docs_loaded == 10
        assert audit.action == 'channel.run.finished' and 'без log' in audit.details
    else:
        status, loaded, skipped, dup, errors, level, summary, action = GOLDENS[case]
        log = state.log
        assert (log.status, log.loaded, log.skipped, log.duplicates, log.errors) == (status, loaded, skipped, dup, errors)
        assert log.finished_at is not None
        assert log.events == [{'level':level, 'event':'run', 'message':summary,
            'stations_done':2 if case=='stations' else 0,
            'stations_total':4 if case=='stations' else 0, 'loaded':loaded,
            'by_station':RESULTS[case]['by_station'] if case in ('stations','empty-list') else []}]
        assert state.ch.docs_loaded == 7 + loaded and audit.action == action
        assert summary in audit.details
    async with world.factory() as db:
        assert await db.scalar(select(func.count()).select_from(Counterparty)) == 0
        assert await db.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    if case == 'exception': assert 'rollback' in tail and tail.index('rollback') < tail.index('dispatch')


@pytest.mark.parametrize('path', ['native','direct'])
@pytest.mark.parametrize('case', ['missing-channel','malformed','cancel'])
async def test_early_failure_and_cancellation_keep_initial_log(world, monkeypatch, path, case):
    await running(world)
    begin = len(world.trace.timeline)
    if case == 'missing-channel':
        seen = await call(world, monkeypatch, path, {}, channel_id=MISSING)
        assert seen == []
    elif case == 'cancel':
        world.cancel_started, world.cancel_release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(call(world, monkeypatch, path, 'cancel'))
        try:
            await asyncio.wait_for(world.cancel_started.wait(), timeout=10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        finally:
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    else:
        with pytest.raises(ValueError):
            await call(world, monkeypatch, path, {'created':'bad'})
    tail = world.trace.timeline[begin:]
    assert 'dispatch' not in tail and 'commit' not in tail
    state = await snapshot(world)
    assert (state.log.status, state.log.loaded, state.log.finished_at) == ('running',0,None)
    assert state.ch.docs_loaded == 7 and state.ch.last_sync_at is None and state.audits == []
    async with world.factory() as db:
        assert await db.scalar(select(func.count()).select_from(Counterparty)) == 0


async def test_native_hooks_and_falsey_service_seams(world, monkeypatch):
    await running(world)
    async def result(*a, **kw): return {'created':3}
    monkeypatch.setattr(native, 'async_session_factory', FalseyCallable(world.factory))
    monkeypatch.setattr(native, 'orchestrate_channel', FalseyCallable(result))
    monkeypatch.setattr(native, '_loaded_total', FalseyCallable(lambda result: 41))
    monkeypatch.setattr(native, '_run_summary', FalseyCallable(lambda result: 'текущий native hook'))
    await native._run_channel_background(CHID, None, None, LID)
    state = await snapshot(world)
    assert state.log.loaded == 41 and state.ch.docs_loaded == 48
    assert state.log.events[0]['message'] == 'текущий native hook'
    async with world.factory.begin() as db:
        await db.execute(delete(AuditEvent))
        await db.execute(delete(ChannelSyncLog))
    await running(world)
    await owner.run_channel_background(CHID, None, None, LID,
        session_factory=FalseyCallable(world.factory), orchestrate_channel=FalseyCallable(result),
        loaded_total_fn=FalseyCallable(lambda result: 17),
        run_summary_fn=FalseyCallable(lambda result: 'direct hook'))
    state = await snapshot(world)
    assert (state.log.loaded, state.ch.docs_loaded, state.log.events[0]['message']) == (17,65,'direct hook')
    assert owner.run_summary({'created':2}, loaded_total_fn=FalseyCallable(lambda _: 11)) == 'загружено 11'


async def test_native_summary_resolves_current_loaded_hook(monkeypatch):
    monkeypatch.setattr(native, '_loaded_total', FalseyCallable(lambda _: 29))
    assert native._run_summary({}) == 'загружено 29'
    assert owner.run_summary({}) == 'загружено 0'


@pytest.mark.parametrize('status,kind,df,dt,expected', [
    ('success','fuel_shift','2026-10-01','2026-10-31',True),
    ('failed','fuel_shift','2026-10-01','2026-10-31',True),
    ('error','fuel_shift','2026-10-01','2026-10-31',False),
    ('success','reestr','2026-10-01','2026-10-31',False),
    ('success','fuel_shift',None,'2026-10-31',False),
], ids=['success','raw-failed','error','other-kind','missing-date'])
async def test_post_session_followup_is_terminal_only(world, monkeypatch, status, kind, df, dt, expected):
    from app.services import fuel_shift_refresh
    await running(world)
    seen=[]
    async def terminal(cid, start, end):
        assert world.factory.kw['bind'].pool.checkedout() == 0
        seen.append((cid,start,end))
        raise RuntimeError('captured followup failure')
    monkeypatch.setattr(fuel_shift_refresh, 'followup_fuel_sales', terminal)
    async def result(*a,**kw): return {'status':status,'kind':kind,'created':1}
    await owner.run_channel_background(CHID, df, dt, LID, orchestrate_channel=result)
    assert seen == ([(support.CID,df,dt)] if expected else [])
    state=await snapshot(world)
    assert state.log.status == ('success' if status=='success' else 'error')
    assert state.ch.docs_loaded == 8 and len(state.audits)==1


async def local_http(world):
    app=FastAPI()
    app.include_router(native.router,prefix='/api')
    async def db():
        async with world.factory() as session: yield session
    app.dependency_overrides[get_db]=db
    token=create_access_token(str(UID),'p11@example.test')
    return app, AsyncClient(transport=ASGITransport(app=app),base_url='http://test',
                            headers={'Authorization':'Bearer '+token})


@pytest.mark.parametrize('case', ['foreign','missing','invalid-id','invalid-body','revoked','object-scope'])
async def test_native_http_refusals_do_not_launch_or_write(world, monkeypatch, case):
    if case in ('revoked','object-scope'):
        async with world.factory.begin() as db:
            m=(await db.execute(select(UserCompany).where(UserCompany.user_id==UID))).scalar_one()
            if case=='revoked': await db.delete(m)
            else: m.object_scope=['p11-location-only']
    tasks=[]
    monkeypatch.setattr(native,'asyncio',NS(create_task=lambda coro:tasks.append(coro)))
    app,client=await local_http(world)
    target={'foreign':FOREIGN,'missing':MISSING,'invalid-id':'invalid'}.get(case,CHID)
    async with client:
        r=await client.post(f'/api/channels/{target}/run', json={'station_codes':['bad']} if case=='invalid-body' else {})
    assert r.status_code == (422 if case in ('invalid-id','invalid-body') else 404),r.text
    if r.status_code==404: assert r.json()=={'detail':'Не найдено'}
    assert tasks==[]
    async with world.factory() as db:
        assert await db.scalar(select(func.count()).select_from(ChannelSyncLog))==0
        assert await db.scalar(select(func.count()).select_from(AuditEvent))==0
        assert (await db.get(Channel,CHID)).docs_loaded==7


async def test_native_request_openapi_and_committed_task_arguments(world, monkeypatch):
    tasks=[]
    monkeypatch.setattr(native,'asyncio',NS(create_task=lambda coro:tasks.append(coro)))
    app,client=await local_http(world)
    schema=app.openapi()
    run=schema['paths']['/api/channels/{channel_id}/run']['post']
    assert sorted(run['responses'])==['200','422']
    assert run['requestBody']['content']['application/json']['schema']=={
        'anyOf':[{'$ref':'#/components/schemas/RunRequest'},{'type':'null'}],'title':'Payload'}
    assert native.RunRequest().model_dump()==dict(date_from=None,date_to=None,station_codes=None,all_period=False,mode='append')
    props=schema['components']['schemas']['RunRequest']['properties']
    assert props['all_period']['default'] is False and props['mode']['default']=='append'
    async def result(*a,**kw): return {'created':2}
    monkeypatch.setattr(native,'orchestrate_channel',result)
    try:
        async with client:
            r=await client.post(f'/api/channels/{CHID}/run',json={'date_from':'2026-10-01','date_to':'2026-10-31',
                'station_codes':[],'all_period':True,'mode':''})
        assert r.status_code==200,r.text
        body=r.json();log_id=uuid.UUID(body['sync_log_id'])
        assert body=={'status':'running','sync_log_id':str(log_id),'message':'Загрузка запущена в фоне'}
        assert len(tasks)==1
        async with world.factory() as db:
            log=await db.get(ChannelSyncLog,log_id)
            assert (log.status,log.date_from,log.date_to)==('running',None,None)
        frame=tasks[0].cr_frame.f_locals
        assert [frame[k] for k in ('channel_id','date_from','date_to','log_id','station_codes','all_period','mode')]==[
            CHID,'2026-10-01','2026-10-31',log_id,[],True,'append']
        await tasks.pop()
        assert (await snapshot(world,log_id)).log.loaded==2
    finally:
        for coro in tasks:coro.close()


@pytest.mark.parametrize('lookback,expected_from', [(3,'2026-10-28'),(-7,'2026-10-31')],ids=['three-days','negative-clamped'])
async def test_scheduler_launch_direct_factory_and_durable_log(world, monkeypatch, lookback, expected_from):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return AT.astimezone(tz) if tz else AT.replace(tzinfo=None)
    monkeypatch.setattr(channel_scheduler,'datetime',Clock)
    def forbidden(*a,**kw): raise AssertionError('scheduler entered native router helper')
    monkeypatch.setattr(native,'_run_channel_background',forbidden)
    tasks=[]
    monkeypatch.setattr(channel_scheduler,'asyncio',NS(create_task=lambda coro:tasks.append(coro)))
    seam=FalseyCallable(world.factory)
    monkeypatch.setattr(channel_scheduler,'async_session_factory',seam)
    try:
        async with world.factory() as db:
            ch=await db.get(Channel,CHID)
            await channel_scheduler._launch(db,ch,lookback)
        assert len(tasks)==1
        frame=tasks[0].cr_frame.f_locals
        assert frame['session_factory'] is seam
        assert (frame['date_from'],frame['date_to'])==(expected_from,'2026-10-31')
        log_id=frame['log_id']
        async with world.factory() as db:
            log=await db.get(ChannelSyncLog,log_id)
            assert (log.channel_id,log.status,log.date_from,log.date_to,log.finished_at)==(CHID,'running',expected_from,'2026-10-31',None)
            assert log.events==[{'level':'info','event':'run','message':f'автозапуск по расписанию ({expected_from}…2026-10-31)'}]
        # No stream: real orchestrator's skipped path, no network or scheduler loop.
        await tasks.pop()
        state=await snapshot(world,log_id)
        assert state.log.status=='partial' and state.log.loaded==0
    finally:
        for coro in tasks:coro.close()


@pytest.mark.parametrize('path',['native','direct'])
async def test_real_registry_file_rows_repeat_and_company_scope(world, monkeypatch, path):
    import openpyxl
    file=Path(os.environ['UPLOAD_DIR'])/('p11-'+path+'.xlsx')
    book=openpyxl.Workbook();ws=book.active;ws.title='Общий свод'
    ws.append(['P11 synthetic registry']);ws.append(['БУ','Объект','Поставщик'])
    ws.append(['501','P11 ЭЗС','ООО P11 Поставщик',None,None,None,None,None,'fixed fixture'])
    ws.append(['999','P11 чужая ЭЗС','ООО P11 Чужой поставщик'])
    book.save(file);book.close();assert file.stat().st_size<32768
    async with world.factory() as db:
        db.add_all([ServiceLocation(id='p11-local',company_id=support.CID,code='501',name='P11 ЭЗС',type='ev_charging'),
            ServiceLocation(id='p11-foreign',company_id=support.OTHER,code='999',name='P11 чужая ЭЗС',type='ev_charging'),
            Source(id=SID,company_id=support.CID,source_type='manual_table',name='P11 собственный XLSX'),
            SourceFile(id=FID,company_id=support.CID,file_name=file.name,storage_path=str(file),size=file.stat().st_size),
            EventSubscription(company_id=support.CID,label='P11 local',target_kind='url',url='http://never.example.test',
                              event_types=['connector.sync.completed','connector.sync.failed'])])
        ch=await db.get(Channel,CHID);ch.config={'uploadFileId':str(FID)}
        await db.flush()
        db.add(ChannelStream(channel_id=CHID,source_id=SID,doc_type_id='reestr',name='P11',role='anchor'))
        await db.commit()
    tasks=[]
    if path=='native': monkeypatch.setattr(native,'asyncio',NS(create_task=lambda coro:tasks.append(coro)))
    observed=[]
    for index,loaded in enumerate((2,0)):
        if path=='native':
            app,client=await local_http(world)
            async with client:
                response=await client.post(f'/api/channels/{CHID}/run',json={})
            assert response.status_code==200,response.text
            log_id=uuid.UUID(response.json()['sync_log_id'])
            assert len(tasks)==1
            try:await tasks.pop()
            finally:
                for coro in tasks:coro.close()
        else:
            log_id=uuid.UUID(f'b1100000-0000-4000-8000-{101+index:012x}')
            await running(world,log_id)
            await owner.run_channel_background(CHID,None,None,log_id)
        state=await snapshot(world,log_id)
        assert (state.log.status,state.log.loaded,state.log.errors)==('success',loaded,0)
        assert state.log.events[0]['message']==f'загружено {loaded}'
        assert state.ch.docs_loaded==9 and state.other.docs_loaded==19
        assert set(state.ch.config['uploadFiles'])=={'svod'}
        async with world.factory() as db:
            entries=(await db.execute(select(DataEntry).order_by(DataEntry.source_label))).scalars().all()
            assert sorted((e.source_label,e.layer) for e in entries)==[
                ('reestr-ezs-oplaty-dogovory-501','raw'),('reestr-ezs-oplaty-dogovory-999','raw'),
                ('reestr-ezs-oplaty-dogovory-clean-501','clean')]
            assert all(e.company_id==support.CID for e in entries)
            assert (await db.execute(select(Counterparty.name))).scalars().all()==['ООО P11 Поставщик']
            settlements=(await db.execute(select(StationContractSettlement))).scalars().all()
            assert [(s.company_id,s.location_id,s.role,s.payment_status) for s in settlements]==[
                (support.CID,'p11-local','energy','unknown')]
            outbox=(await db.execute(select(OutboxEvent))).scalars().all()
            assert len(outbox)==index+1 and {o.type for o in outbox}=={'connector.sync.completed'}
            assert {o.company_id for o in outbox}=={support.CID}
            observed.append((len(entries),len(settlements)))
    assert observed==[(3,1),(3,1)] and len((await snapshot(world,log_id)).audits)==2


@pytest.mark.parametrize('case',['dispatch-error','publication-error'])
async def test_actual_orchestrator_failure_publication_and_rethrow(world,monkeypatch,case):
    from app.services import space_events
    async with world.factory() as db:
        db.add_all([Source(id=SID,company_id=support.CID,source_type='p11-unknown',name='P11'),
            EventSubscription(company_id=support.CID,label='P11 failure',target_kind='url',url='http://never.example.test',
                              event_types=['connector.sync.completed','connector.sync.failed'])])
        await db.flush();db.add(ChannelStream(channel_id=CHID,source_id=SID,doc_type_id='p11',name='P11'))
        await db.commit()
    await running(world)
    if case=='dispatch-error':
        async def fail(db,*a,**kw):
            db.add(Counterparty(company_id=support.CID,name='P11 partial',inn=''))
            await db.flush();raise ValueError('actual dispatch failed')
        monkeypatch.setattr(channel_orchestrator,'_dispatch',fail)
    else:
        async def publication(db,*a,**kw): await db.execute(text('select 1/0'))
        monkeypatch.setattr(space_events,'publish',publication)
    begin=len(world.trace.timeline)
    await owner.run_channel_background(CHID,None,None,LID)
    tail=world.trace.timeline[begin:]
    state=await snapshot(world)
    assert state.log.status==('error' if case=='dispatch-error' else 'partial')
    assert state.audits[0].action==('channel.run.failed' if case=='dispatch-error' else 'channel.run.partial')
    assert 'rollback' in tail
    async with world.factory() as db:
        assert await db.scalar(select(func.count()).select_from(Counterparty))==0
        events=(await db.execute(select(OutboxEvent))).scalars().all()
        assert [e.type for e in events]==(['connector.sync.failed'] if case=='dispatch-error' else [])


async def test_two_separate_utc_instants_are_preserved(world, monkeypatch):
    from datetime import timedelta
    times=[]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            assert tz is timezone.utc
            value=AT+timedelta(seconds=len(times))
            times.append(value)
            return value
    monkeypatch.setattr(owner,'datetime',Clock)
    await running(world)
    async def result(*a,**kw):return {'created':0}
    await owner.run_channel_background(CHID,None,None,LID,orchestrate_channel=result)
    state=await snapshot(world)
    assert times==[AT,AT+timedelta(seconds=1)]
    assert (state.log.finished_at,state.ch.last_sync_at)==tuple(times)
