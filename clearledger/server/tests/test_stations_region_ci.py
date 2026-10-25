"""Загрузка станций не спотыкается о регистр в названии региона.

У `regions` уникальность регистронезависимая (`uq_regions_company_name_ci`: btrim+lower).
Загрузка станций держала кэш регионов по ТОЧНОМУ имени, а `canon_region` возвращает
НЕопознанный субъект как есть — поэтому «Тест» и «тест» из паспортов станций считались
разными регионами. До появления индекса это была лишняя строка в справочнике, после —
UniqueViolation и упавшая загрузка витрины.

Тот же корень 25.10.2026 уронил старт Ядра РусГидро через миграцию заполнения регионов
(исправлено отдельно); здесь закрыт второй путь — рантайм загрузки.
"""
import uuid

import pytest
from sqlalchemy import func, select

from app.models import Company, Region
from app.services.stations_normalize import _make_region_resolver


async def _company(db):
    company = Company(name='Регионы', slug='reg-ci-' + uuid.uuid4().hex, profile_id='energy')
    db.add(company)
    await db.flush()
    return company.id


async def _skolko(db, cid, key: str) -> int:
    return int((await db.execute(
        select(func.count()).select_from(Region).where(
            Region.company_id == cid,
            func.btrim(func.lower(Region.name)) == key))).scalar() or 0)


@pytest.mark.asyncio(loop_scope='session')
async def test_dva_napisaniya_dayut_odin_region(db):
    cid = await _company(db)
    region_id = await _make_region_resolver(db, cid)

    first = await region_id('Неопознанный Субъект')
    second = await region_id('неопознанный субъект')
    third = await region_id('  НЕОПОЗНАННЫЙ СУБЪЕКТ  ')

    assert first is not None
    assert second == first and third == first, 'регистр и пробелы не создают новый регион'
    assert await _skolko(db, cid, 'неопознанный субъект') == 1


@pytest.mark.asyncio(loop_scope='session')
async def test_uzhe_lezhashchij_region_nahoditsya_v_drugom_registre(db):
    cid = await _company(db)
    db.add(Region(company_id=cid, name='Тест'))
    await db.flush()

    region_id = await _make_region_resolver(db, cid)
    rid = await region_id('тест')

    assert rid is not None
    assert await _skolko(db, cid, 'тест') == 1, 'второй строки быть не должно'


@pytest.mark.asyncio(loop_scope='session')
async def test_raznye_subekty_ostayutsya_raznymi(db):
    cid = await _company(db)
    region_id = await _make_region_resolver(db, cid)
    a = await region_id('Первый Субъект')
    b = await region_id('Второй Субъект')
    assert a != b, 'нормализация не должна склеивать разные названия'
