"""Регрессия аудита рынка: период, страницы, полнота расшифровки и цена."""
import uuid
from datetime import date, timedelta
import pytest
from sqlalchemy import select
from app.models import Company, MarketSite, MarketObservation, ServiceLocation
from app.services.market_registry import split_address
from app.services import ru_geo


def test_abbreviated_region_overrides_city_guess():
    region, city = split_address('Ленингр. обл., п. Синявино, М18 Кола (46 км)')
    assert ru_geo.resolve(region, city) == ('Ленинградская область', 'source')
    # Одноимённый город другого региона не сильнее явно указанного субъекта.
    assert ru_geo.resolve(region, 'Кировск') == ('Ленинградская область', 'source')


@pytest.mark.asyncio(loop_scope='session')
async def test_observation_period_and_pages(auth_client, db):
    cid = (await db.execute(select(Company.id).where(Company.slug == 'gig'))).scalar_one()
    site = MarketSite(company_id=cid, name='QA дата и страницы', kind='ezs', region='Ленинградская область')
    db.add(site); await db.flush()
    for i in range(205):
        db.add(MarketObservation(company_id=cid, site_id=site.id, kind='price', observed_on='2026-09-13', price_per_kwh=20))
    db.add(MarketObservation(company_id=cid, site_id=site.id, kind='price', observed_on='2026-10-01', price_per_kwh=21))
    await db.commit()
    base = {'company_id':str(cid), 'site_id':str(site.id), 'date_from':'2026-09-01','date_to':'2026-09-30'}
    first = await auth_client.get('/api/market/observations', params=base)
    assert first.status_code == 200, first.text
    a=first.json(); assert a['total']==205 and len(a['observations'])==200
    b=(await auth_client.get('/api/market/observations',params={**base,'offset':200})).json()
    assert b['total']==205 and len(b['observations'])==5
    assert len({o['id'] for o in a['observations']+b['observations']})==205
    octo=(await auth_client.get('/api/market/observations',params={**base,'date_from':'2026-10-01','date_to':'2026-10-01'})).json()
    assert octo['total']==1 and octo['observations'][0]['pricePerKwh']==21
    empty=(await auth_client.get('/api/market/observations',params={**base,'date_from':'2026-11-01','date_to':'2026-11-30'})).json()
    assert empty['total']==0
    bad=await auth_client.get('/api/market/observations',params={**base,'date_from':'2026-10-01'})
    assert bad.status_code==422
    other=(await auth_client.get('/api/market/observations',params={**base,'regions':'Мурманская область'})).json()
    assert other['total']==0


@pytest.mark.asyncio(loop_scope='session')
async def test_position_full_neighbours_and_stale_price(auth_client, db):
    cid=(await db.execute(select(Company.id).where(Company.slug=='gig'))).scalar_one()
    loc=ServiceLocation(id='qa-market-'+uuid.uuid4().hex[:15],company_id=cid,code='qa-market',name='QA окружение',latitude=55,longitude=37,is_test=False)
    db.add(loc)
    today=date.today()
    for i in range(12):
        site=MarketSite(company_id=cid,name=f'QA сосед {i}',kind='ezs',site_class='network',latitude=55+i/10000,longitude=37,current_type='DC',max_power_kw=150)
        db.add(site);await db.flush()
        db.add(MarketObservation(company_id=cid,site_id=site.id,kind='price',observed_on=(today-timedelta(days=42 if i else 1)).isoformat(),price_per_kwh=100 if i else 20,basis='реестр, круглосуточно'))
    await db.commit()
    params={'company_id':str(cid),'radius_km':2,'date_from':today.isoformat(),'date_to':today.isoformat()}
    reply=await auth_client.get('/api/market/position',params=params)
    assert reply.status_code==200,reply.text
    body=reply.json();row=next(x for x in body['objects'] if x['locationId']==loc.id)
    assert len(row['neighbours'])==12 and row['rivals']==12
    assert row['priceCoverage']==1 and row['stalePrices']==11
    assert row['marketPricePerKwh']==20
    assert sum(n['includedInPrice'] for n in row['neighbours'])==1
    assert body['salesFrom']==today.isoformat()==body['salesTo']
    reply=await auth_client.get('/api/market/position',params={**params,'current_type':'AC'})
    row=next(x for x in reply.json()['objects'] if x['locationId']==loc.id)
    assert row['marketPricePerKwh'] is None and row['priceCoverage']==0
    assert len(row['neighbours'])==12
