"""Одинаковые таблицы Поддержки разных поколений: отдельная локальная БД."""
import os
import unittest
import uuid

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.services.contract_usage import _sources

URL = os.getenv('TEST_DATABASE_URL', '')
RUN = bool(URL and make_url(URL).host in {'localhost', '127.0.0.1'}
           and make_url(URL).database == 'contract_sources_test')


@unittest.skipUnless(RUN, 'Нужна отдельная локальная contract_sources_test')
class ContractSourcesIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(URL, poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as c:
            await c.execute(text('DROP SCHEMA IF EXISTS core CASCADE'))
            await c.execute(text('DROP SCHEMA public CASCADE'))
            await c.execute(text('CREATE SCHEMA core'))
            await c.execute(text('CREATE SCHEMA public'))

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def check(self, tables, expected):
        contract_id = uuid.uuid4()
        async with self.sessions() as db:
            for name, linked in tables:
                await db.execute(text(f'CREATE TABLE {name} (id UUID PRIMARY KEY'
                                      + (', contract_id UUID)' if linked else ')')))
                if linked:
                    await db.execute(text(f'INSERT INTO {name} VALUES (:id,:contract)'),
                                     {'id': uuid.uuid4(), 'contract': contract_id})
            support = [sql for app, _, sql in await _sources(db) if app == 'support']
            self.assertEqual({name for name, _ in tables if any(name in sql for sql in support)}, set(expected))
            for sql in support:
                self.assertEqual((await db.execute(text(sql))).scalars().all(), [contract_id])
            self.assertEqual(await db.scalar(text('SELECT 1')), 1)

    async def test_core_modern_public_legacy(self):
        await self.check([('core.service_contracts', True), ('public.service_contracts', False)], ['core.service_contracts'])

    async def test_public_modern_standalone(self):
        await self.check([('public.service_contracts', True)], ['public.service_contracts'])

    async def test_both_modern_tables_keep_both_sources(self):
        await self.check([('core.service_contracts', True), ('public.service_contracts', True)], ['core.service_contracts', 'public.service_contracts'])

    async def test_no_optional_tables(self):
        await self.check([], [])

    async def test_legacy_standalone_is_not_a_link_source(self):
        await self.check([('public.service_contracts', False)], [])

    async def test_dropped_column_is_not_a_link_source(self):
        async with self.sessions() as db:
            await db.execute(text('CREATE TABLE core.service_contracts (id UUID, contract_id UUID)'))
            await db.execute(text('ALTER TABLE core.service_contracts DROP COLUMN contract_id'))
            self.assertFalse([s for app, _, s in await _sources(db) if app == 'support'])
