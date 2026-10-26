"""Переприменение обогащения не перезаписывает то, что уже стоит.

Обогащение корп-клиентов прогоняют после каждой загрузки сессий. Раньше каждый
прогон писал client_name/тариф/сумму ВСЕМ сессиям организации заново, теми же
значениями: на rushydro так накопилось 9.4 млн обновлений на 221 353 строки —
43 полных прохода по таблице в 372 МБ. Для Postgres перезапись тем же значением
создаёт новую версию строки: работа для autovacuum и лишние блокировки.

Проверяем две вещи, которые легко сломать одной правкой: повторный прогон ничего
не пишет, и при этом организация по-прежнему считается сопоставленной — отчёт
пользователю не должен превращаться в «0 организаций» там, где всё на месте.
"""
import uuid
from datetime import datetime

import pytest

from app.models import ChargeSession, Company, CorporateClient, ServiceLocation
from app.services.charge_sessions_normalize import enrich_from_registry


async def _park(db):
    company = Company(name='Обогащение', slug='enrich-' + uuid.uuid4().hex, profile_id='energy')
    db.add(company)
    await db.flush()
    loc = ServiceLocation(id='en-' + uuid.uuid4().hex, company_id=company.id,
                          code=uuid.uuid4().hex, name='Площадка', type='ev_charging')
    db.add(loc)
    await db.flush()
    db.add(CorporateClient(company_id=company.id, name='ООО Ромашка',
                           phone='79990000001', mode='flat', rate=25))
    db.add_all([
        ChargeSession(company_id=company.id, session_ext_id='s1', location_id=loc.id,
                      user_id='79990000001', user_type='ЮЛ', started_at=datetime(2026, 10, 1),
                      energy_kwh=10, tariff=20, result='Complete'),
        ChargeSession(company_id=company.id, session_ext_id='s2', location_id=loc.id,
                      user_id='79990000001', user_type='ЮЛ', started_at=datetime(2026, 10, 2),
                      energy_kwh=5, tariff=20, result='Complete'),
    ])
    await db.flush()
    return company.id


@pytest.mark.asyncio(loop_scope='session')
async def test_povtornyj_progon_nichego_ne_pishet(db):
    cid = await _park(db)

    first = await enrich_from_registry(db, cid, commit=False)
    assert first['updated'] == 2, 'первый прогон обогащает обе сессии'
    assert first['orgs_matched'] == 1

    second = await enrich_from_registry(db, cid, commit=False)
    assert second['updated'] == 0, 'повторный прогон не должен перезаписывать то же значение'
    assert second['priced'] == 0
    # Организация остаётся сопоставленной: её сессии на месте, менять просто нечего.
    assert second['orgs_matched'] == 1
    # И значения никуда не делись.
    assert second['revenue'] == first['revenue'] > 0


@pytest.mark.asyncio(loop_scope='session')
async def test_izmenenie_tarifa_snova_pishet(db):
    cid = await _park(db)
    await enrich_from_registry(db, cid, commit=False)

    client = (await db.execute(
        __import__('sqlalchemy').select(CorporateClient).where(
            CorporateClient.company_id == cid))).scalars().one()
    client.rate = 30
    await db.flush()

    third = await enrich_from_registry(db, cid, commit=False)
    assert third['priced'] == 2, 'новый тариф должен доехать до сессий'
