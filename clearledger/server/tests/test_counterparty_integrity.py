"""Проверки целостности на выделенной TEST_DATABASE_URL по conftest проекта."""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.models import Company, Counterparty, ServiceLocation, StationContractSettlement

pytestmark = pytest.mark.asyncio(loop_scope='session')


async def create(client, **fields):
    body = dict(company_id='gig', name='Тест '+uuid.uuid4().hex[:8], inn='') | fields
    response = await client.post('/api/references/counterparties', json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_duplicate_update_and_competing_updates(auth_client):
    first, second = await create(auth_client), await create(auth_client)
    body = dict(inn='7766666666',kpp='776601001')
    results = await asyncio.gather(*[auth_client.patch('/api/references/counterparties/'+p['id'],json=body) for p in [first,second]])
    assert sorted(r.status_code for r in results)==[200,409]
    winner = next(r.json() for r in results if r.status_code==200)
    r = await auth_client.patch('/api/references/counterparties/'+winner['id'],json={'name':'Новое название',**body})
    assert r.status_code==200,r.text


async def test_soft_settlement_and_warehouse_metadata_prevent_delete(auth_client,db):
    company = (await db.execute(select(Company).where(Company.slug=='gig'))).scalar_one()
    company_id = company.id
    for source in ['settlement','warehouse']:
        cp = await create(auth_client)
        location = ServiceLocation(id='qa-'+uuid.uuid4().hex[:20],company_id=company_id,code='test-'+uuid.uuid4().hex[:8],name='Тест объект',type='warehouse')
        if source=='warehouse': location.extra_metadata={'warehouse':{'counterpartyId':cp['id']}}
        db.add(location);await db.flush()
        if source=='settlement':db.add(StationContractSettlement(company_id=company_id,location_id=location.id,role='rent',counterparty_id=cp['id']))
        await db.commit()
        response=await auth_client.delete('/api/references/counterparties/'+cp['id'])
        assert response.status_code==409,response.text
        await db.rollback()
        assert await db.get(Counterparty,uuid.UUID(cp['id'])) is not None


async def test_validations_reject_blanks_and_keep_record(auth_client):
    cp = await create(auth_client,phone='123')
    for body in [{'name':''},{'name':'   '},{'phone':'x'*101}]:
        r=await auth_client.patch('/api/references/counterparties/'+cp['id'],json=body)
        assert r.status_code==422,r.text
    r=await auth_client.patch('/api/references/counterparties/'+cp['id'],json={'phone':None})
    assert r.status_code==200 and r.json()['phone'] is None
