"""Регрессии обновления рынка: неизвестные оценки и сопоставимые сводки."""
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from app.models import Company, MarketOperator, MarketPlayer, MarketSite
from app.services.market_quality import observed_rating
from app.services.market_registry import ingest_registry


@pytest.mark.parametrize('rating,count,expected', [(0,0,None),(4,0,None),(0,None,None),(None,3,None),(4.5,2,4.5),(0,2,0.0),(6,1,None),(float('nan'),1,None)])
def test_rating_requires_reviews(rating,count,expected):
    assert observed_rating(rating,count)==expected


@pytest.mark.asyncio(loop_scope='session')
async def test_live_metrics_share_one_scope_and_ignore_unrated(auth_client,db):
    cid=(await db.scalars(select(Company.id).where(Company.slug=='gig'))).one()
    other=(await db.scalars(select(Company.id).where(Company.slug=='rushydro'))).one()
    op=MarketOperator(company_id=cid,name='QA network '+uuid.uuid4().hex,cities=999,avg_power_kw=999,points_total=999)
    db.add(op);await db.flush()
    player=MarketPlayer(company_id=cid,app='QA app '+uuid.uuid4().hex,package='qa.market.'+uuid.uuid4().hex,operator_id=op.id,own_stations=777)
    db.add(player)
    seen=datetime(2026,10,25,tzinfo=timezone.utc)
    for i,(rating,count,power,city) in enumerate([(3,1,10,'Город А'),(5,2,20,' город а '),(0,0,None,'Город Б')]):
        db.add(MarketSite(company_id=cid,operator_id=op.id,kind='ezs',site_class='network',status='active',name=f'QA {op.id} {i}',city=city,region='Регион А',max_power_kw=power,rating=rating,reviews_count=count,last_seen_at=seen,raw={'federal_district_id':str(1 if i<2 else 2)}))
    await db.flush()
    canonical=(await db.scalars(select(MarketSite.id).where(MarketSite.operator_id==op.id))).first()
    for klass,status,duplicate in [('home','active',None),('network','closed',None),('network','active',canonical)]:
        db.add(MarketSite(company_id=cid,operator_id=op.id,kind='ezs',site_class=klass,status=status,name='QA excluded',max_power_kw=1000,city='Не считать',duplicate_of_id=duplicate))
    db.add(MarketSite(company_id=other,operator_id=op.id,kind='ezs',site_class='network',name='QA other tenant',city='Чужой',max_power_kw=1000))
    await db.commit()
    params={'company_id':str(cid)}
    res=await auth_client.get('/api/market/operators',params=params);assert res.status_code==200,res.text
    row=next(x for x in res.json()['operators'] if x['id']==str(op.id));assert row['rating']==4
    card=(await auth_client.get('/api/market/operators/'+str(op.id),params=params)).json()
    assert card['totals']['rating']==4
    assert all(x['rating'] is None for x in card['sites'] if x['name'].endswith(' 2'))
    landscape=await auth_client.get('/api/market/landscape',params=params);assert landscape.status_code==200,landscape.text
    row=next(x for x in landscape.json()['networks'] if x['id']==str(op.id))
    assert row['sites']==3 and row['citiesCount']==2 and row['avgPowerKw']==15 and row['districts']==2
    scoped=(await auth_client.get('/api/market/landscape',params={**params,'cities':'Город Б'})).json()
    row=next(x for x in scoped['networks'] if x['id']==str(op.id));assert row['sites']==1 and row['citiesCount']==1 and row['avgPowerKw'] is None
    players=(await auth_client.get('/api/market/players',params=params)).json()
    row=next(x for x in players['players'] if x['id']==str(player.id))
    assert row['networkSites']==3 and row['ownStations']==777
    assert row['networkObservedAt'].startswith('2026-10-25')


@pytest.mark.asyncio(loop_scope='session')
async def test_registry_keeps_raw_zero_but_not_an_observed_rating(db):
    cid=(await db.scalars(select(Company.id).where(Company.slug=='gig'))).one()
    ext=uuid.uuid4().hex
    await ingest_registry(db,cid,[{'uuid':ext,'lat':'60','lon':'40','time_zone':'Europe/Moscow','name':'QA no reviews','rating':'0','reviews_count':'0'}],snapshot_date='2026-10-25')
    site=(await db.scalars(select(MarketSite).where(MarketSite.company_id==cid,MarketSite.external_id==ext))).one()
    assert site.rating is None and site.reviews_count==0
    assert site.raw['rating']=='0'
