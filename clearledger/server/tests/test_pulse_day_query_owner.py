"""ROOT-only fixed SQL/HTTP characterization; synthetic Support read contract."""
import os
if os.environ.get('RUN_PULSE_DAY_QUERY_OWNER_TESTS')!='1':
    raise RuntimeError('ROOT-approved pulse day query gate required')

import uuid
from contextlib import asynccontextmanager
from datetime import date,datetime,timedelta,timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport,AsyncClient
from sqlalchemy import delete,event,select,text
from sqlalchemy.engine import Engine,make_url
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import DBAPIError,ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession,async_sessionmaker,create_async_engine

from app import database
from app.auth import create_access_token
from app.main import app
from app.models import (App,AppCompanyLink,AuditEvent,ChargeSession,Company,CompanyRole,FuelTransaction,
    GlBalance,GlEntry,PulseAck,PulseTarget,PulseView,PulseViewBlock,Task,User,UserCompany)
from app.routers import pulse_router as native
from app.services import pulse_day as owner,pulse_digest,space_desk

pytestmark=pytest.mark.asyncio(loop_scope='session')
# Selected read projection, not a replacement for Support schema/FKs/role grants.
# Canonical source pins:002_schema.sql4350d533...,016_extended_statuses22b2b194...,
#018_archive_delete da2d7226...,028_hubex a0cf50d8... (full pins in report).
TICKETS_DDL='''CREATE TABLE public.tickets (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), company_id UUID NOT NULL,
 status TEXT NOT NULL DEFAULT 'new' CHECK(status IN
 ('new','in_progress','waiting_customer','escalated','resolved','closed','cancelled','reopened')),
 external_system TEXT, sla_breached BOOLEAN DEFAULT false, reopen_count INT DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 is_deleted BOOLEAN NOT NULL DEFAULT false,is_archived BOOLEAN NOT NULL DEFAULT false)'''

TAX_READ_DDL = ["CREATE TABLE IF NOT EXISTS public.tax_regimes (\n    code            text PRIMARY KEY,\n    name            text NOT NULL,\n    short_name      text,\n    -- Кому доступен: у форм собственности разные наборы (патент — только ИП,\n    -- НПД — физлицу и ИП, ОСНО — всем).\n    for_legal       boolean NOT NULL DEFAULT true,\n    for_ip          boolean NOT NULL DEFAULT true,\n    for_person      boolean NOT NULL DEFAULT false,\n    -- Что облагается: income · income_minus_expense · patent · none.\n    object          text,\n    -- НДС и налог на прибыль по умолчанию. «По умолчанию» — потому что у УСН с\n    -- 2025 года появилась обязанность по НДС при доходе выше порога, и признак\n    -- решается не только режимом (см. tax_regime_rates.kind = 'vat_threshold').\n    pays_vat        boolean NOT NULL DEFAULT false,\n    pays_profit_tax boolean NOT NULL DEFAULT false,\n    -- Счёт учёта основного налога режима: по нему считается «сколько начислено».\n    tax_account     text,\n    -- Совмещается ли с другими режимами (патент — да, ОСНО с УСН — нет).\n    combinable      boolean NOT NULL DEFAULT false,\n    note            text,\n    sort            integer NOT NULL DEFAULT 100\n);", 'CREATE TABLE IF NOT EXISTS public.organization_tax_regimes (\n    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),\n    company_id      uuid NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,\n    organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,\n    regime_code     text NOT NULL REFERENCES public.tax_regimes(code),\n    valid_from      date NOT NULL,\n    valid_to        date,\n    -- Региональная ставка, если отличается от базовой (у УСН «Доходы минус\n    -- расходы» регионы дают от 5 %, у «Доходов» — от 1 %).\n    rate            numeric(18,4),\n    -- Основной режим против совмещаемого: патент дополняет УСН, а не заменяет.\n    is_primary      boolean NOT NULL DEFAULT true,\n    -- Плательщик НДС по факту: на УСН это следствие оборота, и решать за клиента\n    -- систему нельзя — признак ставит бухгалтер, а система показывает основание.\n    vat_payer       boolean,\n    source          text,          -- откуда узнали: manual · 1c · detected\n    note            text,\n    created_at      timestamptz NOT NULL DEFAULT now(),\n    updated_at      timestamptz NOT NULL DEFAULT now()\n);']


def fixed(prefix,n):return uuid.UUID(f'{prefix}8100000-0000-4000-8000-{n:012x}')
UIDS={name:fixed('a',i) for i,name in enumerate(('reader','sales','admin','outsider'),1)}
ROLE_ID=fixed('b',1);SUPPORT_ID=fixed('b',2);FOREIGN_SUPPORT=fixed('b',3)

@pytest.fixture
async def tickets_contract(db):
    assert await db.scalar(text("select to_regclass('public.tickets')")) is None
    await db.execute(text(TICKETS_DDL));await db.commit()
    yield
    await db.rollback()
    await db.execute(text('DROP TABLE IF EXISTS public.tickets'));await db.commit()

@pytest.fixture
async def world(db,tickets_contract,monkeypatch,request):
    today=await db.scalar(text('select current_date'))
    at=datetime.combine(today,datetime.min.time(),timezone.utc)+timedelta(hours=12)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return at.astimezone(tz) if tz else at.replace(tzinfo=None)
    class Day(date):
        @classmethod
        def today(cls):return today
    monkeypatch.setattr(owner,'datetime',Clock);monkeypatch.setattr(owner,'date',Day)
    monkeypatch.setattr(pulse_digest,'datetime',Clock)
    companies=[Company(name='P8 synthetic '+str(i),slug='p8-'+uuid.uuid4().hex,profile_id='energy') for i in (0,1)]
    db.add_all(companies);await db.flush();cid,other=[c.id for c in companies]
    reader_role=CompanyRole(id=ROLE_ID,company_id=cid,name='P8 reader',modules=['pulse:today','pulse:team.people'])
    db.add(reader_role)
    users={name:User(id=uid,company_id=other if name=='outsider' else cid,name='P8 '+name,
        email='p8-'+name+'-'+uuid.uuid4().hex+'@example.test',password_hash='!synthetic',
        role='user',last_seen_at=datetime.now(timezone.utc)) for name,uid in UIDS.items()}
    db.add_all(users.values());await db.flush()
    for name in ('reader','sales','admin'):
        db.add(UserCompany(user_id=UIDS[name],company_id=cid,role='admin' if name=='admin' else 'user',
            role_id=ROLE_ID if name=='reader' else None,modules=None if name!='sales' else
                ['pulse:today','pulse:business.sales','pulse:business.summary'],party_type='internal'))
    db.add(UserCompany(user_id=UIDS['outsider'],company_id=other,role='user',modules=['pulse']))
    await db.commit()
    tax_owned=False; legal_form_owned=False
    if request.node.originalname=='test_fixed_profile_day_native_direct_and_desk' and request.node.callspec.params['mode']=='office-books':
        for name in ('tax_regimes','organization_tax_regimes'):
            assert await db.scalar(text('select to_regclass(:name)'),{'name':'public.'+name}) is None
        for ddl in TAX_READ_DDL:await db.execute(text(ddl))
        tax_owned=True
        legal_form_owned=not await db.scalar(text("select exists(select 1 from information_schema.columns where table_schema='public' and table_name='organizations' and column_name='legal_form')"))
        if legal_form_owned:await db.execute(text('ALTER TABLE public.organizations ADD COLUMN legal_form text'))
        await db.commit()
    tokens={name:create_access_token(str(user.id),user.email) for name,user in users.items()}
    emails={name:user.email for name,user in users.items()}
    yield NS(cid=cid,other=other,company=companies[0],users=users,role=reader_role,today=today,at=at,tokens=tokens,emails=emails)
    await db.rollback()
    for model in (AppCompanyLink,PulseViewBlock,PulseView,PulseAck,PulseTarget,ChargeSession,FuelTransaction,GlEntry,GlBalance,Task):
        if hasattr(model,'company_id'):await db.execute(delete(model).where(model.company_id.in_([cid,other])))
    await db.execute(delete(UserCompany).where(UserCompany.company_id.in_([cid,other])))
    await db.execute(delete(User).where(User.id.in_(UIDS.values())))
    await db.execute(delete(CompanyRole).where(CompanyRole.id==ROLE_ID))
    if tax_owned:
        await db.execute(text('DROP TABLE public.organization_tax_regimes'))
        await db.execute(text('DROP TABLE public.tax_regimes'))
    if legal_form_owned:await db.execute(text('ALTER TABLE public.organizations DROP COLUMN legal_form'))
    await db.commit()

async def populate(w,db,mode):
    w.company.profile_id='office' if mode.startswith('office') else 'fuel' if mode=='fuel' else 'p8-unknown' if mode=='unknown' else 'energy'
    anchor=w.at-timedelta(days=8 if mode=='stale' else 0)
    if mode in ('energy','fuel','unknown','stale'):
        for i,days,amount in [(1,0,2000),(2,1,3000),(3,8,10000)]:
            if mode=='fuel':row=FuelTransaction(id=fixed('d',i),company_id=w.cid,station_code=810,ext_id=i,
                dt=anchor-timedelta(days=days),amount=amount,liters=amount/100)
            else:row=ChargeSession(id=fixed('d',i),company_id=w.cid,session_ext_id='p8-'+str(i),
                started_at=(anchor-timedelta(days=days)).replace(tzinfo=None),amount=amount,energy_kwh=amount/100)
            db.add(row)
        # A foreign company with a later timestamp cannot change this company's as_of/window.
        db.add(ChargeSession(id=fixed('d',99),company_id=w.other,session_ext_id='foreign',
            started_at=(w.at+timedelta(days=10)).replace(tzinfo=None),amount=999999,energy_kwh=9999))
    if mode=='office-work':
        for i,status,visibility,due,assignee in [(1,'open','company',w.at-timedelta(days=1),None),
            (2,'open','private',w.at+timedelta(days=1),UIDS['reader']),
            (3,'open','personal',None,None),(4,'done','company',None,None)]:
            db.add(Task(id=fixed('9',i),company_id=w.cid,title='P8 task '+str(i),status=status,
                visibility=visibility,due_at=due,assignee_id=assignee,author_id=UIDS['admin']))
    if mode=='office-books':
        for i,dt,kt,amount in [(1,'62.01','90.01',1000),(2,'62.01','90.01',2000),
                              (3,'62.01','90.01',3000),(4,'90.02','20',1000)]:
            db.add(GlEntry(id=fixed('e',i),company_id=w.cid,entry_date=w.today,period_year=w.today.year,
                period_month=w.today.month,account_dt=dt,account_kt=kt,amount=amount))
        db.add(GlBalance(id=fixed('f',1),company_id=w.cid,as_of=w.today,account='62.01',debit=1250))
    await db.commit()

async def snapshot(db):
    return {m.__tablename__:sorted(repr(tuple(r)) for r in (await db.execute(select(m.__table__))).all())
        for m in (AuditEvent,Task,ChargeSession,FuelTransaction,GlEntry,GlBalance,PulseAck,PulseTarget,UserCompany,User,CompanyRole)}

def headers(w,role='admin'):
    # Query rollbacks expire ORM fixture rows; transport credentials are plain fixture values.
    return {'Authorization':'Bearer '+w.tokens[role],'X-Company-Id':str(w.cid)}

async def get(w,path='/api/pulse/day',role='admin',raise_exceptions=False,**params):
    async with AsyncClient(transport=ASGITransport(app=app,raise_app_exceptions=raise_exceptions),base_url='http://test') as client:
        return await client.get(path,headers=headers(w,role),params={'company_id':str(w.cid),**params})

@pytest.mark.parametrize('mode',['energy','fuel','unknown','empty','stale','office-work','office-books'],ids=['energy','fuel','unknown','empty','stale','office-work','office-books'])
async def test_fixed_profile_day_native_direct_and_desk(world,db,mode,pytestconfig):
    w=world;await populate(w,db,mode);before=await snapshot(db)
    boundary=pytestconfig._pulse_day_query_owner_boundary;sent=len(boundary.capture)
    direct=await owner.pulse_day_data(db,str(w.cid))
    r=await get(w);assert r.status_code==200,r.text
    assert r.json()==direct  # Fixed owner clock preserves every field, including generated_at.
    assert direct['generated_at']==w.at.isoformat()
    values={k['key']:k['value'] for k in direct['kpi']}
    if mode in ('energy','fuel','unknown','stale'):
        assert values==({'revenue':5000.0,'sessions':2,'silent':0,'people':3} if mode=='fuel' else {'revenue':5000.0,'sessions':2,'people':3})
        assert [(k['key'],k['delta_pct']) for k in direct['kpi']]==[('revenue',-50.0),('sessions',100.0)]+([('silent',None)] if mode=='fuel' else [])+[('people',None)]
        assert [c['key'] for c in direct['cards']]==(['data_stale','sales_drop'] if mode=='stale' else ['sales_drop'])
        expected_at=(w.at-timedelta(days=8 if mode=='stale' else 0)).replace(tzinfo=None).isoformat()
        assert direct['as_of']==expected_at and direct['stale_days']==(8 if mode=='stale' else 0)
    elif mode=='empty':
        assert values=={'people':3};assert [c['key'] for c in direct['cards']]==['data_stale']
        assert direct['as_of'] is None and direct['stale_days'] is None
    elif mode=='office-work':
        assert values=={'work_open':3,'work_overdue':1,'approvals':0,'acquaints':0,'meetings':0,'own_open':0,'people':3}
        assert [(c['key'],c['count']) for c in direct['cards']]==[('work_overdue',1),('work_no_owner',2)]
        assert direct['as_of'] is None and direct['stale_days'] is None
    else:
        assert values=={'money_revenue':6000,'profit':5000,'vat':0,'receivable':1250,'people':3}
        assert direct['cards']==[] and direct['stale_days']==0
        assert direct['as_of']==w.today.isoformat()+'T00:00:00'
    desk=await space_desk._pulse(db,w.cid)
    n=len(direct['cards']);stale=direct['stale_days']
    assert desk=={'metrics':[
        {'label':'требуют внимания','value':str(n),'tone':'warn' if n else 'ok'},
        {'label':'данные сети','value':'нет' if stale is None else 'сегодня' if stale==0 else '8 дн назад',
         'tone':'warn' if stale is None or stale>7 else 'ok'}]}
    assert await snapshot(db)==before and len(boundary.capture)==sent

@pytest.mark.parametrize('role,keys,cards',[('reader',['people'],[]),('sales',['revenue','sessions'],['sales_drop']),
    ('admin',['revenue','sessions','people'],['sales_drop'])],ids=['reader','sales','admin'])
async def test_native_visibility_money_vs_system_and_selected_company(world,db,role,keys,cards):
    w=world;await populate(w,db,'energy');before=await snapshot(db)
    r=await get(w,role=role);assert r.status_code==200,r.text
    assert [k['key'] for k in r.json()['kpi']]==keys
    assert [c['key'] for c in r.json()['cards']]==cards
    # Query owns data, not authorization: visible=None is the historical system slice.
    full=await owner.pulse_day_data(db,str(w.cid))
    assert [c['key'] for c in full['cards']]==['sales_drop']
    assert (await space_desk._pulse(db,w.cid))['metrics'][0]=={'label':'требуют внимания','value':'1','tone':'warn'}
    bad=await get(w,role='outsider');assert bad.status_code==403 and bad.json()=={'detail':'Нет доступа к компании'}
    # company query chooses the tenant; conflicting UI company header does not broaden it.
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as c:
        r=await c.get('/api/pulse/day',headers=headers(w,role),params={'company_id':str(w.other)})
    assert r.status_code==403
    assert await snapshot(db)==before

@pytest.mark.parametrize('change',['membership','product','grant'],ids=['membership','product','grant'])
async def test_current_role_and_membership_revoke(world,db,change):
    w=world;await populate(w,db,'energy')
    assert [k['key'] for k in (await get(w,role='reader')).json()['kpi']]==['people']
    if change=='membership':await db.delete(await db.get(UserCompany,(UIDS['reader'],w.cid)))
    else:w.role.modules=['docs'] if change=='product' else ['pulse:today','pulse:business.sales']
    await db.commit();before=await snapshot(db)
    r=await get(w,role='reader')
    if change=='grant':
        assert r.status_code==200 and [k['key'] for k in r.json()['kpi']]==['revenue','sessions']
    else:
        assert r.status_code==403 and r.json()=={'detail':'Нет доступа к компании' if change=='membership' else 'Нет доступа к продукту'}
    assert {k['key']:k['value'] for k in (await owner.pulse_day_data(db,str(w.cid)))['kpi']}=={'revenue':5000,'sessions':2,'people':2 if change=='membership' else 3}
    assert await snapshot(db)==before

async def test_as_role_and_native_late_binding(world,db,monkeypatch):
    w=world;await populate(w,db,'energy')
    r=await get(w,as_role=str(ROLE_ID));assert r.status_code==200 and [k['key'] for k in r.json()['kpi']]==['people']
    r=await get(w,role='reader',as_role=str(uuid.uuid4()))
    assert r.status_code==200 and [k['key'] for k in r.json()['kpi']]==['people']
    r=await get(w,as_role=str(uuid.uuid4()))
    assert r.status_code==200 and [k['key'] for k in r.json()['kpi']]==['revenue','sessions','people']
    calls=[];original=owner.pulse_day_data
    async def hook(db,cid,visible=None):
        calls.append((cid,visible));return await original(db,cid,visible)
    monkeypatch.setattr(native,'pulse_day_data',hook)
    assert (await get(w,role='reader')).status_code==200
    assert calls==[(str(w.cid),{'today','team.people'})]
    # Desk has a direct owner import, and must not use the old native binding.
    monkeypatch.setattr(native,'pulse_day_data',AsyncMock(side_effect=AssertionError('old router binding')))
    assert (await space_desk._pulse(db,w.cid))['metrics'][0]['value']=='1'

async def test_threshold_ack_and_none_empty_visibility(world,db):
    w=world;await populate(w,db,'energy')
    threshold=PulseTarget(company_id=w.cid,key='sales_drop_pct',value=60)
    db.add(threshold);db.add(PulseTarget(company_id=w.other,key='sales_drop_pct',value=1));await db.commit()
    assert (await owner.pulse_day_data(db,str(w.cid)))['cards']==[]
    threshold.value=50;await db.commit()
    cards=(await owner.pulse_day_data(db,str(w.cid)))['cards']
    assert [(c['key'],c['count'],c['level']) for c in cards]==[('sales_drop',5000,'warn')]
    ack=PulseAck(company_id=w.cid,card_key='sales_drop',acked_on=w.today,user_id=UIDS['admin'])
    db.add(ack);await db.commit()
    assert (await owner.pulse_day_data(db,str(w.cid)))['cards']==[]
    await db.delete(ack);await db.flush()
    ack=PulseAck(company_id=w.cid,card_key='sales_drop',acked_on=w.today-timedelta(days=1),snooze_until=w.today)
    db.add(ack);await db.commit();assert (await owner.pulse_day_data(db,str(w.cid)))['cards']==[]
    ack.snooze_until=w.today-timedelta(days=1);await db.commit()
    assert [c['key'] for c in (await owner.pulse_day_data(db,str(w.cid)))['cards']]==['sales_drop']
    empty=await owner.pulse_day_data(db,str(w.cid),set())
    assert empty=={'as_of':w.at.replace(tzinfo=None).isoformat(),'stale_days':0,'kpi':[],'cards':[],'generated_at':w.at.isoformat()}
    assert owner.DEFAULT_THRESHOLDS['sales_drop_pct']==20

async def ticket(db,w,n,company=SUPPORT_ID,*,status='in_progress',sla=True,days=4):
    await db.execute(text('''INSERT INTO public.tickets(id,company_id,status,sla_breached,created_at)
        VALUES(:id,:cid,:status,:sla,:at)'''),{'id':fixed('f',100+n),'cid':company,'status':status,
        'sla':sla,'at':w.at-timedelta(days=days)})

async def test_core_support_mapping_and_legacy_global_sources(world,db):
    w=world;await populate(w,db,'energy')
    await ticket(db,w,1);await ticket(db,w,2,FOREIGN_SUPPORT);await ticket(db,w,3,status='closed');await db.commit()
    before=await snapshot(db)
    no_map=await owner.pulse_day_data(db,str(w.cid));assert 'own_open' not in {k['key'] for k in no_map['kpi']}
    support=await db.scalar(select(App).where(App.code=='support'))
    if support is None:
        support=App(code='support',name='P8 support');db.add(support);await db.flush()
    db.add(AppCompanyLink(company_id=w.cid,app_id=support.id,external_company_id=str(SUPPORT_ID)));await db.commit()
    before=await snapshot(db)
    day=await owner.pulse_day_data(db,str(w.cid))
    assert {k['key']:k['value'] for k in day['kpi']}=={'revenue':5000,'sessions':2,'own_open':1,'people':3}
    assert next(c['count'] for c in day['cards'] if c['key']=='own_sla')==1
    sources=await owner._sources_snapshot(db,str(w.cid))
    # Existing source/CC definitions are global; do not label them tenant-safe.
    assert next(s['count'] for s in sources if s['key']=='tickets')==3
    assert await snapshot(db)==before

async def test_sources_minimum_rows_and_unknown_definition(world,db):
    w=world
    for n in range(9):await ticket(db,w,n,FOREIGN_SUPPORT)
    await db.commit()
    source=next(s for s in await owner._sources_snapshot(db,str(w.cid)) if s['key']=='tickets')
    assert (source['count'],source['days'],source['used'],source['stale'])==(9,4,True,False)
    await ticket(db,w,9,FOREIGN_SUPPORT);await db.commit()
    source=next(s for s in await owner._sources_snapshot(db,str(w.cid)) if s['key']=='tickets')
    assert (source['count'],source['days'],source['used'],source['stale'])==(10,4,True,True)
    with pytest.raises(KeyError):owner._data_sources('unregistered-source-profile')
    assert await owner._cc_snapshot(db)=={}  # public.call_records/inbox_threads absent, not a permission-denial proof.

async def test_missing_support_table_aborts_legacy_query_and_desk_falls_back(world,db,pytestconfig):
    w=world;sent=len(pytestconfig._pulse_day_query_owner_boundary.capture)
    await db.execute(text('DROP TABLE public.tickets'));await db.commit()
    assert await owner._tickets_available(db) is False
    with pytest.raises(DBAPIError):await db.execute(text('select 1'))
    await db.rollback()
    with pytest.raises(DBAPIError):await owner.pulse_day_data(db,str(w.cid))
    await db.rollback()
    assert await space_desk._pulse(db,w.cid)=={'metrics':[]}
    await db.rollback()
    r=await get(w);assert r.status_code==500
    assert len(pytestconfig._pulse_day_query_owner_boundary.capture)==sent
    await db.rollback()

async def test_native_business_export_and_existing_view_null_anchor(world,db,pytestconfig):
    w=world;await populate(w,db,'energy')
    r=await get(w,'/api/pulse/business');assert r.status_code==200,r.text
    assert next(k['value'] for k in r.json()['net'] if k['key']=='revenue')==15000
    view=PulseView(id=fixed('8',1),company_id=w.cid,name='P8 view',status='published',feedback_mode='none')
    db.add(view);await db.flush();db.add(PulseViewBlock(view_id=view.id,block_key='net.sales'));await db.commit()
    r=await get(w,f'/api/pulse/views/{view.id}/data',raise_exceptions=True);assert r.status_code==200,r.text
    block=r.json()['blocks'][0]
    # Existing _net_block_data passes None as_of to _sales_snapshot. Preserve the
    # resulting empty view, even though /day and /business have actual sales.
    assert (block['key'],block['metrics'],block['items'],block['note'])==('net.sales',[],[],'Данных о продажах за период нет.')
    sent=len(pytestconfig._pulse_day_query_owner_boundary.capture)
    r=await get(w,'/api/pulse/export',view='objects');assert r.status_code==200,r.text
    assert r.content.decode('utf-8')=='\ufeffТочка;Код;Признаки;Под вопросом, ₽;Выручка недели, ₽;Было неделей раньше, ₽;Ожидаем по договорам за 2 мес, ₽;Без документа;Последняя сессия\r\n'
    assert await db.scalar(select(AuditEvent.action).where(AuditEvent.company_id==w.cid))=='exported'
    assert len(pytestconfig._pulse_day_query_owner_boundary.capture)==sent

@pytest.mark.parametrize('mode',['partner','dormant','optout','away','role-revoke'],ids=['partner','dormant','optout','away','role-revoke'])
async def test_digest_current_recipient_filters(world,db,mode):
    w=world;member=await db.get(UserCompany,(UIDS['reader'],w.cid));u=w.users['reader']
    assert set(await pulse_digest._recipients(db,str(w.cid)))=={w.emails[n] for n in ('reader','sales','admin')}
    if mode=='partner':member.party_type='partner'
    elif mode=='dormant':u.last_seen_at=w.at-timedelta(days=31)
    elif mode=='optout':u.email_notify=[]
    elif mode=='away':u.away_from=w.today-timedelta(days=1);u.away_to=w.today+timedelta(days=1)
    else:w.role.modules=['docs']
    await db.commit();before=await snapshot(db)
    assert set(await pulse_digest._recipients(db,str(w.cid)))=={w.emails[n] for n in ('sales','admin')}
    assert await snapshot(db)==before

async def test_digest_bounded_real_query_lock_send_audit_commit_order(world,db,monkeypatch,pytestconfig):
    w=world;await populate(w,db,'energy')
    db.add(PulseTarget(company_id=w.cid,key='digest_hour',value=15));await db.commit()
    assert str(w.cid) in {cid for cid,_ in await pulse_digest._companies_due(db)}
    original_due=pulse_digest._companies_due
    due=AsyncMock(return_value=[(str(w.cid),'P8 synthetic')])
    # Bind the synthetic conftest factory, not the import-time factory captured
    # by app.main before conftest replaces database.async_session_factory.
    monkeypatch.setattr(pulse_digest,'async_session_factory',database.async_session_factory)
    monkeypatch.setattr(pulse_digest,'_companies_due',due)
    monkeypatch.setattr(native,'pulse_day_data',AsyncMock(side_effect=AssertionError('old router binding')))
    original_day=owner.pulse_day_data;original_recipients=pulse_digest._recipients
    trace=[];messages=[];boundary=pytestconfig._pulse_day_query_owner_boundary
    async def day(*a,**kw):
        assert len(a)==2 and kw=={};trace.append('day');return await original_day(*a,**kw)
    async def recipients(*a):trace.append('recipients');return await original_recipients(*a)
    async def send(emails,subject,body):
        trace.append('send');messages.append((set(emails),subject,body));boundary.record('synthetic.pulse_digest.send_notice')
    monkeypatch.setattr(owner,'pulse_day_data',day);monkeypatch.setattr(pulse_digest,'_recipients',recipients)
    monkeypatch.setattr(pulse_digest,'send_notice',send)
    def sql(conn,cursor,statement,parameters,context,executemany):
        if 'pg_try_advisory_lock' in statement:trace.append('lock')
        elif 'pg_advisory_unlock' in statement:trace.append('unlock')
        elif 'insert into audit_events' in statement and 'pulse.digest' in statement:trace.append('audit')
    original_commit=AsyncSession.commit
    async def commit(session,*a,**kw):trace.append('commit');return await original_commit(session,*a,**kw)
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession,'commit',commit);event.listen(Engine,'before_cursor_execute',sql)
        try:assert await pulse_digest.run_once()==1
        finally:event.remove(Engine,'before_cursor_execute',sql)
    assert trace==['lock','day','recipients','send','audit','commit','unlock','commit']
    assert len(messages)==1 and messages[0][0]=={w.emails[n] for n in ('reader','sales','admin')}
    assert messages[0][1]=='P8 synthetic: 1 на экране дня, из них тревожных 1'
    assert 'Выручка сети просела' in messages[0][2]
    assert await db.scalar(select(AuditEvent.action).where(AuditEvent.company_id==w.cid))=='pulse.digest'
    assert str(w.cid) not in {cid for cid,_ in await original_due(db)}


@pytest.fixture
async def digest_isolated_factory(world,request):
    if request.node.callspec.params['reason'] not in ('no-recipients','send-error'):
        yield database.async_session_factory
        return
    url=os.environ['TEST_DATABASE_URL'];target=make_url(url)
    expected='api_pulse_day_query_owner_test_20261031'
    assert (target.host,target.port,target.database)==('127.0.0.1',33546,expected)
    engine=create_async_engine(url,poolclass=NullPool)
    assert isinstance(engine.sync_engine.pool,NullPool)
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text('select current_database()'))==expected
        yield async_sessionmaker(engine,expire_on_commit=False)
    finally:
        await engine.dispose()
        # Read only this fresh DB and the exact test-owned digest key; no unlock-all.
        async with engine.connect() as conn:
            assert await conn.scalar(text("select count(*) from pg_locks where locktype='advisory' and database=(select oid from pg_database where datname=current_database()) and classid=0 and objid=CAST(:key AS oid) and objsubid=1"),{'key':pulse_digest.LOCK_KEY})==0
        await engine.dispose()

@pytest.mark.parametrize('reason',['quiet','no-recipients','send-error'],ids=['quiet','no-recipients','send-error'])
async def test_digest_bounded_empty_error_paths_keep_unlock_and_audit(world,db,monkeypatch,reason,pytestconfig,digest_isolated_factory):
    w=world;await populate(w,db,'energy')
    captured_before=len(pytestconfig._pulse_day_query_owner_boundary.capture)
    if reason=='quiet':
        db.add(PulseTarget(company_id=w.cid,key='sales_drop_pct',value=60));await db.commit()
    elif reason=='no-recipients':
        for name in ('reader','sales','admin'):w.users[name].email_notify=[]
        await db.commit()
    original_day=owner.pulse_day_data
    async def day(*a,**kw):return await original_day(*a,**kw)
    monkeypatch.setattr(owner,'pulse_day_data',day)
    monkeypatch.setattr(pulse_digest,'async_session_factory',digest_isolated_factory)
    monkeypatch.setattr(pulse_digest,'_companies_due',AsyncMock(return_value=[(str(w.cid),'P8 synthetic')]))
    sent=[];trace=[]
    async def send(*args):sent.append('captured');raise RuntimeError('synthetic send refusal')
    monkeypatch.setattr(pulse_digest,'send_notice',send)
    def sql(conn,cursor,statement,parameters,context,executemany):
        if 'pg_try_advisory_lock' in statement:trace.append('lock')
        elif 'pg_advisory_unlock' in statement:trace.append('unlock')
        elif 'insert into audit_events' in statement and 'pulse.digest' in statement:trace.append('audit')
    event.listen(Engine,'before_cursor_execute',sql)
    try:
        if reason=='send-error':
            with pytest.raises(RuntimeError,match='synthetic send refusal'):await pulse_digest.run_once()
        else:assert await pulse_digest.run_once()==0
    finally:event.remove(Engine,'before_cursor_execute',sql)
    assert trace==['lock','unlock'] and sent==(['captured'] if reason=='send-error' else [])
    assert len(pytestconfig._pulse_day_query_owner_boundary.capture)==captured_before
    assert await db.scalar(select(AuditEvent.id).where(AuditEvent.company_id==w.cid,AuditEvent.action=='pulse.digest')) is None

async def test_existing_programming_error_rollback_fallbacks_are_not_permission_proof(monkeypatch):
    class Result:
        def scalar(self):return True
    class DB:
        def __init__(self):self.n=0;self.rollbacks=0
        async def execute(self,*a,**kw):
            self.n+=1
            if self.n==1:return Result()
            raise ProgrammingError('synthetic SQL',{},RuntimeError('synthetic missing SELECT contract'))
        async def rollback(self):self.rollbacks+=1
    db=DB()
    assert await owner._cc_targets(db)==owner.CC_DEFAULT_TARGETS and db.rollbacks==1
    async def failed(*a):raise ProgrammingError('synthetic SQL',{},RuntimeError('synthetic unavailable source'))
    monkeypatch.setattr(owner,'_cc_measure',failed);db=DB()
    assert await owner._cc_snapshot(db)=={} and db.rollbacks==1
    monkeypatch.setattr(owner,'pulse_day_data',AsyncMock(side_effect=ValueError('synthetic query error')))
    assert await space_desk._pulse(db,uuid.uuid4())=={'metrics':[]}

async def test_identity_reexports_and_shared_mutable_registries():
    names=('pulse_day_data','build_cards','money','plural','_profile','_data_sources','_sources_snapshot',
        '_thresholds','_sales_snapshot','_office_day_data','_work_day_data','_period_bounds','_result_window','_tax_mode')
    assert all(getattr(native,name) is getattr(owner,name) for name in names)
    assert native.PROFILE_SALES is owner.PROFILE_SALES
    assert native.THRESHOLDS is owner.THRESHOLDS and native.DEFAULT_THRESHOLDS is owner.DEFAULT_THRESHOLDS
    assert native.CARD_SCOPE is owner.CARD_SCOPE and native.KPI_SCOPE is owner.KPI_SCOPE
