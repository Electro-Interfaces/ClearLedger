"""Реестр приложений не пересобирается по пять раз за один запрос.

`company_apps` собирает ответ пятью выборками, а зовут её ради одного факта
(«включён ли voice») из двенадцати мест. За 4.7 часа на rushydro это 21 565 вызовов
при 4.6 тыс. запросов к API — по 4–5 полных пересборок на запрос.

Проверяем ровно то, что легко сломать правкой: повторный вызов в одной сессии не идёт
в базу, а изменение состава приложений кэш сбрасывает — иначе администратор включил бы
приложение и не увидел его в том же запросе.
"""
import uuid

import pytest
from sqlalchemy import event

from app.models import App, Company
from app.services import app_registry


class _Schyotchik:
    """Считает запросы к базе на синхронном движке под сессией."""

    def __init__(self, db):
        self.db = db
        self.n = 0

    async def __aenter__(self):
        conn = await self.db.connection()
        self.sync_engine = conn.sync_engine
        event.listen(self.sync_engine, "before_cursor_execute", self._hit)
        return self

    async def __aexit__(self, *exc):
        event.remove(self.sync_engine, "before_cursor_execute", self._hit)

    def _hit(self, conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            self.n += 1


async def _company(db):
    company = Company(name='Реестр', slug='reg-' + uuid.uuid4().hex, profile_id='energy')
    db.add(company)
    await db.flush()
    return company.id


async def _prilozhenie(db):
    """Своё приложение в реестре: в тестовой базе seed их не заводит, и опираться
    на состав реестра тест не должен — он проверяет кэш, а не каталог продуктов."""
    app = App(code='probe-' + uuid.uuid4().hex[:8], name='Проба', is_active=True, sort=999)
    db.add(app)
    await db.flush()
    return app


@pytest.mark.asyncio(loop_scope='session')
async def test_povtornyj_vyzov_v_odnom_zaprose_ne_idyot_v_bazu(db):
    cid = await _company(db)
    await _prilozhenie(db)

    async with _Schyotchik(db) as s:
        first = await app_registry.company_apps(db, cid)
        posle_pervogo = s.n
        second = await app_registry.company_apps(db, cid)
        posle_vtorogo = s.n

    assert posle_pervogo > 0, 'первый вызов обязан собрать данные'
    assert posle_vtorogo == posle_pervogo, 'повторный вызов не должен делать ни одного запроса'
    assert second == first


@pytest.mark.asyncio(loop_scope='session')
async def test_raznye_kompanii_ne_putayutsya(db):
    one, two = await _company(db), await _company(db)
    await _prilozhenie(db)
    a = await app_registry.company_apps(db, one)
    b = await app_registry.company_apps(db, two)
    assert [x['code'] for x in a] == [x['code'] for x in b]
    # ключ кэша включает компанию: подмены быть не должно
    assert ('company_apps', str(one)) in db.info['_app_registry_cache']
    assert ('company_apps', str(two)) in db.info['_app_registry_cache']


@pytest.mark.asyncio(loop_scope='session')
async def test_izmenenie_sostava_sbrasyvaet_kesh(db):
    cid = await _company(db)
    app = await _prilozhenie(db)

    before = await app_registry.company_apps(db, cid)
    target = next(a for a in before if a['code'] == app.code)
    # Переключаем в ОБРАТНОЕ состояние, а не «включаем»: у профиля `energy` часть
    # приложений включена по умолчанию (`_default_app_on`), и тест на «включить»
    # проверял бы дефолт, а не сброс кэша.
    novoe = not target['enabled']

    await app_registry.set_app(db, cid, app.id, novoe)

    after = await app_registry.company_apps(db, cid)
    stal = next(a for a in after if a['code'] == app.code)
    assert stal['enabled'] is novoe, 'изменение состава обязано быть видно в том же запросе'
