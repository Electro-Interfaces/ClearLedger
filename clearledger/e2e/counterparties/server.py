"""Изолированный HTTP API с настоящими роутерами, без startup/фоновых задач."""
import asyncio
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

URL = os.environ['TEST_DATABASE_URL']
from sqlalchemy.engine import make_url
assert make_url(URL).host in {'localhost', '127.0.0.1'} and make_url(URL).database == 'counterparties_test'
os.environ['DATABASE_URL'] = URL
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import Base, get_db
from app.auth import get_current_user
from app.models import Company, User, UserCompany, Counterparty, CounterpartyContact, Contract, Organization, ServiceLocation, ContractLocation
from app.routers import references_router, locations_router
from app.services.phone_e164 import PHONE_FUNCTION_DDL

engine = create_async_engine(URL)
sessions = async_sessionmaker(engine, expire_on_commit=False)
actor = None
actors = {}

async def seed():
    global actor, actors
    async with engine.begin() as c:
        await c.execute(text('TRUNCATE companies, users CASCADE'))
    async with sessions() as db:
        company = Company(name='Тестовая сеть', slug='counterparty-test', profile_id='energy')
        foreign = Company(name='Другая сеть', slug='foreign-test', profile_id='energy')
        actor = User(name='Тестовый администратор', email='qa@example.invalid', password_hash='fake', is_superadmin=True)
        member = User(name='Тестовый участник', email='member@example.invalid', password_hash='fake')
        db.add_all([company, foreign, actor, member]); await db.flush()
        db.add(UserCompany(user_id=member.id,company_id=company.id,role='user'))
        actors = {'admin': actor, 'member': member}
        cps = [Counterparty(company_id=company.id, name='Тест Альфа', inn='7701234567', kpp='770101001', phone='+7 000 000 0001', email='alpha@example.invalid', aliases=['energy']),
               Counterparty(company_id=company.id, name='Тест Бета', inn='', aliases=['rent']),
               Counterparty(company_id=company.id, name='Тест Длинное название организации для проверки читаемости карточки и её реквизитов', inn='7707654321', aliases=['service']),
               Counterparty(company_id=foreign.id, name='Чужой контрагент', inn='1234567890')]
        db.add_all(cps); await db.flush()
        org = Organization(company_id=company.id, name='Тестовое юрлицо', inn='7700000000')
        db.add(org); await db.flush()
        ct = Contract(company_id=company.id, counterparty_id=cps[0].id, organization_id=org.id, number='ТЕСТ-42', date='2026-10-23', type='Энергоснабжение', scope_type='locations')
        loc = ServiceLocation(id='qa-station', company_id=company.id, name='Тестовая станция', code='0042')
        db.add_all([ct,loc]); await db.flush()
        db.add_all([ContractLocation(company_id=company.id,contract_id=ct.id,location_id=loc.id), CounterpartyContact(company_id=company.id,counterparty_id=cps[0].id,name='Тест Контакт с длинной фамилией',role='tech',position='Главный инженер',phone='+7 000 000 0002',email='engineer@example.invalid')])
        await db.commit()

@asynccontextmanager
async def life(app):
    async with engine.begin() as c:
        await c.execute(text(PHONE_FUNCTION_DDL))
        await c.run_sync(Base.metadata.create_all)
        await c.execute(text('CREATE TABLE IF NOT EXISTS contract_types (code TEXT PRIMARY KEY, label TEXT, gk_basis TEXT, direction TEXT, sort_order INTEGER DEFAULT 0, is_active BOOLEAN DEFAULT TRUE)'))
    await seed()
    yield
    await engine.dispose()

app = FastAPI(lifespan=life)
app.include_router(references_router.router, prefix='/api')
app.include_router(locations_router.router, prefix='/api')
async def user(): return actor
async def session():
    async with sessions() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise
app.dependency_overrides[get_current_user] = user
app.dependency_overrides[get_db] = session

@app.post('/api/__test/reset')
async def reset():
    await seed()
    return {'reset': True}

@app.post('/api/__test/actor/{role}')
async def change_actor(role: str):
    global actor
    actor = actors[role]
    return {'role': role}

# Бухгалтерский контур не входит в этот изолированный прогон.
@app.get('/api/books/counterparties')
async def stats(): return {'rows': []}

@app.get('/api/channels')
async def channels(): return []

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=18547, log_level='warning')
