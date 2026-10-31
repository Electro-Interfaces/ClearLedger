"""Прозрачный alias Поддержки: только отдельная локальная БД, SOURCE / NOTRUN.

Следует unittest/NullPool-конвенции test_contract_usage_sources_integration.py.
Общий conftest не нужен; будущий запуск требует отдельного разрешения.
"""
import os
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.services.contract_usage import _sources, contract_usage, usage_by_contract

def _isolated_url(value):
    """Разобрать один раз; query не может переопределить адрес или базу драйвера."""
    try:
        url = make_url(value)
    except (ArgumentError, ValueError, TypeError):
        return None
    if (url.drivername == "postgresql+asyncpg" and not url.query
            and url.host in {"localhost", "127.0.0.1"}
            and url.database == "contract_usage_alias_test"):
        return url
    return None


URL = _isolated_url(os.getenv("TEST_DATABASE_URL", ""))
RUN = URL is not None
LABEL = "Сервисные договоры «Поддержки»"
CORE = "core.service_contracts"
PUBLIC = "public.service_contracts"


class ContractUsageAliasURLGuard(unittest.TestCase):
    def test_exact_local_database_without_query_is_allowed(self):
        for host in ("localhost", "127.0.0.1"):
            with self.subTest(host=host):
                url = _isolated_url(f"postgresql+asyncpg://test:test@{host}/contract_usage_alias_test")
                self.assertIsNotNone(url)
                self.assertEqual(url.host, host)
                self.assertEqual(url.database, "contract_usage_alias_test")
                self.assertEqual(dict(url.query), {})

    def test_query_overrides_are_rejected_before_engine(self):
        base = "postgresql+asyncpg://test:test@127.0.0.1/contract_usage_alias_test"
        for query in ("database=unrelated_db", "host=remote.invalid", "port=9999",
                      "database=contract_usage_alias_test", "ssl=disable", "unknown=1"):
            with self.subTest(query=query):
                self.assertIsNone(_isolated_url(base + "?" + query))

    def test_unknown_malformed_driver_host_and_database_are_rejected(self):
        for value in (
            "", None, "invalid-url",
            "postgresql+asyncpg://test@127.0.0.1:bad/contract_usage_alias_test",
            "postgresql://test@127.0.0.1/contract_usage_alias_test",
            "postgresql+psycopg://test@127.0.0.1/contract_usage_alias_test",
            "sqlite:///contract_usage_alias_test",
            "postgresql+asyncpg://test@remote.invalid/contract_usage_alias_test",
            "postgresql+asyncpg://test@/contract_usage_alias_test",
            "postgresql+asyncpg://test@127.0.0.1/unrelated_db",
        ):
            with self.subTest(value=value):
                self.assertIsNone(_isolated_url(value))


@unittest.skipUnless(RUN, "Нужна отдельная локальная contract_usage_alias_test")
class ContractUsageAliasIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(URL, "Отказ до engine: URL не прошёл защитный guard")
        self.engine = create_async_engine(URL, poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.company, self.other_company = uuid.uuid4(), uuid.uuid4()
        self.contract, self.other_contract = uuid.uuid4(), uuid.uuid4()
        async with self.engine.begin() as conn:
            for statement in (
                "DROP SCHEMA IF EXISTS core CASCADE",
                "DROP SCHEMA public CASCADE",
                "CREATE SCHEMA core", "CREATE SCHEMA public",
                "CREATE TABLE public.contracts (id UUID PRIMARY KEY, company_id UUID)",
                "CREATE TABLE public.contract_links (contract_id UUID, company_id UUID, "
                "app_code TEXT, project_ref TEXT)",
                "CREATE TABLE public.ezs_sites (id UUID, contract_id UUID, workspace_data JSONB)",
                "CREATE TABLE public.ezs_projects (id UUID, contract_id UUID, site_id UUID)",
            ):
                await conn.execute(text(statement))
            await conn.execute(text("INSERT INTO public.contracts VALUES (:id, :company)"), [
                {"id": self.contract, "company": self.company},
                {"id": self.other_contract, "company": self.other_company},
            ])

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def table(self, db, name, *, row_id=None, linked=True):
        await db.execute(text(f"CREATE TABLE {name} (id UUID PRIMARY KEY, company_id UUID, "
                              "active BOOLEAN" + (", contract_id UUID)" if linked else ")")))
        if linked:
            await db.execute(text(f"INSERT INTO {name} VALUES (:id, :co, true, :cid)"),
                             {"id": row_id or uuid.uuid4(), "co": self.company,
                              "cid": self.contract})

    async def check(self, db, expected_tables, counts):
        # Изолируем только посторонние приложения; SQL Поддержки, payload и
        # company-предикат usage_by_contract остаются настоящими.
        with patch("app.services.contract_usage._SOURCES", []):
            sources = await _sources(db)
            self.assertEqual([sql for _, _, sql in sources], [
                f"SELECT contract_id AS cid FROM {t} WHERE contract_id IS NOT NULL"
                for t in expected_tables
            ])
            self.assertTrue(all((app, label) == ("support", LABEL)
                                for app, label, _ in sources))
            self.assertEqual(await contract_usage(db, self.contract), [
                {"app": "support", "label": LABEL, "count": count} for count in counts
            ])
            self.assertEqual(await usage_by_contract(db, self.company),
                             {self.contract: {"apps": {"support"}, "projects": set()}})

    async def test_physical_and_full_alias_count_each_row_once(self):
        async with self.sessions() as db:
            await self.table(db, CORE)
            await db.execute(text(f"INSERT INTO {CORE} VALUES (:id, :co, false, :cid)"),
                             {"id": uuid.uuid4(), "co": self.company, "cid": self.contract})
            await db.execute(text(f"CREATE VIEW {PUBLIC} AS "
                                  f"SELECT id, company_id, active, contract_id FROM {CORE}"))
            # Схема скрыта в deparse: разрешение имени должно остаться доказанным.
            for search_path in ("public, core", "core, public", "pg_catalog"):
                await db.execute(text(f"SET LOCAL search_path TO {search_path}"))
                support = [sql for app, _, sql in await _sources(db) if app == "support"]
                self.assertEqual(support, [
                    f"SELECT contract_id AS cid FROM {CORE} WHERE contract_id IS NOT NULL"
                ])
            await db.execute(text("SET LOCAL search_path TO public, core"))
            await self.check(db, [CORE], [2])

    async def test_reverse_alias_keeps_public_physical_source(self):
        async with self.sessions() as db:
            await self.table(db, PUBLIC)
            await db.execute(text(f"CREATE VIEW {CORE} AS SELECT * FROM {PUBLIC}"))
            await self.check(db, [PUBLIC], [1])

    async def independent_tables(self, same_id):
        async with self.sessions() as db:
            first_id = uuid.uuid4()
            await self.table(db, CORE, row_id=first_id)
            await self.table(db, PUBLIC, row_id=first_id if same_id else uuid.uuid4())
            await self.check(db, [CORE, PUBLIC], [1, 1])

    async def test_two_independent_tables_keep_both(self):
        await self.independent_tables(False)

    async def test_same_uuid_in_two_physical_tables_is_not_deduplicated(self):
        await self.independent_tables(True)

    async def test_old_public_view_without_contract_column(self):
        async with self.sessions() as db:
            await self.table(db, CORE)
            await db.execute(text(f"CREATE VIEW {PUBLIC} AS "
                                  f"SELECT id, company_id, active FROM {CORE}"))
            await self.check(db, [CORE], [1])

    async def test_old_public_physical_without_contract_column(self):
        async with self.sessions() as db:
            await self.table(db, CORE)
            await self.table(db, PUBLIC, linked=False)
            await self.check(db, [CORE], [1])

    async def test_filtered_view_keeps_its_own_count(self):
        async with self.sessions() as db:
            await self.table(db, CORE)
            await db.execute(text(f"INSERT INTO {CORE} VALUES (:id, :co, false, :cid)"),
                             {"id": uuid.uuid4(), "co": self.company, "cid": self.contract})
            await db.execute(text(f"CREATE VIEW {PUBLIC} AS SELECT * FROM {CORE} WHERE active"))
            await self.check(db, [CORE, PUBLIC], [2, 1])

    async def test_multibase_view_keeps_both_sources(self):
        async with self.sessions() as db:
            await self.table(db, CORE)
            await db.execute(text("CREATE TABLE public.extra (enabled BOOLEAN)"))
            await db.execute(text("INSERT INTO public.extra VALUES (true)"))
            await db.execute(text(f"CREATE VIEW {PUBLIC} AS SELECT sc.* FROM {CORE} sc "
                                  "JOIN public.extra e ON e.enabled"))
            await self.check(db, [CORE, PUBLIC], [1, 1])

    async def test_complex_and_uncertain_projections_are_not_merged(self):
        async with self.sessions() as db:
            await self.table(db, CORE)
            cases = (
                (f"SELECT DISTINCT * FROM {CORE}", 1),
                (f"SELECT sc.* FROM {CORE} sc", 1),
                (f"SELECT * FROM {CORE} UNION ALL SELECT * FROM {CORE}", 2),
                (f"SELECT * FROM {CORE} ORDER BY id LIMIT 1", 1),
                (f"SELECT * FROM ONLY {CORE}", 1),
                (f"WITH c AS (SELECT * FROM {CORE}) SELECT * FROM c", 1),
                (f"SELECT id, contract_id FROM {CORE}", 1),
                (f"SELECT id, company_id, active, contract_id FROM {CORE} "
                 "GROUP BY id, company_id, active, contract_id", 1),
                (f"SELECT contract_id AS id, company_id, active, id AS contract_id FROM {CORE}", 0),
                (f"SELECT id, company_id, active, CASE WHEN active THEN contract_id "
                 f"END AS contract_id FROM {CORE}", 1),
            )
            for definition, count in cases:
                with self.subTest(definition=definition):
                    await db.execute(text(f"CREATE VIEW {PUBLIC} AS {definition}"))
                    await self.check(db, [CORE, PUBLIC], [1, count] if count else [1])
                    await db.execute(text(f"DROP VIEW {PUBLIC}"))

    async def test_rls_and_security_options_are_not_merged(self):
        async with self.sessions() as db:
            await self.table(db, CORE)
            await db.execute(text(f"CREATE VIEW {PUBLIC} AS SELECT * FROM {CORE}"))
            for setting in ("ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY"):
                await db.execute(text(f"ALTER TABLE {CORE} {setting}"))
                self.assertEqual(len([s for s in await _sources(db) if s[0] == "support"]), 2)
            await db.execute(text(f"ALTER TABLE {CORE} DISABLE ROW LEVEL SECURITY"))
            await db.execute(text(f"ALTER TABLE {CORE} NO FORCE ROW LEVEL SECURITY"))
            for option in ("security_barrier=true", "security_invoker=true"):
                await db.execute(text(f"ALTER VIEW {PUBLIC} SET ({option})"))
                await self.check(db, [CORE, PUBLIC], [1, 1])
                await db.execute(text(f"ALTER VIEW {PUBLIC} RESET ({option.split('=')[0]})"))
            await db.execute(text(f"ALTER TABLE {CORE} SET (fillfactor=80)"))
            await self.check(db, [CORE, PUBLIC], [1, 1])

    async def test_unknown_quoted_column_shape_keeps_both(self):
        async with self.sessions() as db:
            await self.table(db, CORE)
            await db.execute(text(f'ALTER TABLE {CORE} ADD COLUMN "x y" TEXT'))
            await db.execute(text(f"CREATE VIEW {PUBLIC} AS SELECT * FROM {CORE}"))
            await self.check(db, [CORE, PUBLIC], [1, 1])

    async def test_inheritance_and_partition_topology_keep_both_sources(self):
        columns = "(id UUID, company_id UUID, active BOOLEAN, contract_id UUID)"
        for topology in ("parent", "child", "partition-root", "partition-leaf"):
            with self.subTest(topology=topology):
                # Каждая сессия откатывает собственный синтетический DDL.
                async with self.sessions() as db:
                    if topology == "parent":
                        await self.table(db, CORE)
                        await db.execute(text(f"CREATE TABLE public.child () INHERITS ({CORE})"))
                        insert_table = "public.child"
                    elif topology == "child":
                        await db.execute(text(f"CREATE TABLE public.parent {columns}"))
                        await db.execute(text(f"CREATE TABLE {CORE} () INHERITS (public.parent)"))
                        insert_table = CORE
                    elif topology == "partition-root":
                        await db.execute(text(f"CREATE TABLE {CORE} {columns} PARTITION BY HASH (id)"))
                        await db.execute(text(f"CREATE TABLE public.leaf PARTITION OF {CORE} "
                                              "FOR VALUES WITH (MODULUS 1, REMAINDER 0)"))
                        insert_table = CORE
                    else:
                        await db.execute(text(f"CREATE TABLE public.parent {columns} PARTITION BY HASH (id)"))
                        await db.execute(text(f"CREATE TABLE {CORE} PARTITION OF public.parent "
                                              "FOR VALUES WITH (MODULUS 1, REMAINDER 0)"))
                        insert_table = CORE
                    await db.execute(text(f"INSERT INTO {insert_table} VALUES (:id, :co, true, :cid)"),
                                     {"id": uuid.uuid4(), "co": self.company, "cid": self.contract})
                    await db.execute(text(f"CREATE VIEW {PUBLIC} AS SELECT * FROM {CORE}"))
                    await self.check(db, [CORE, PUBLIC], [2, 2] if topology == "parent" else [1, 1])

    async def test_tenant_scope_null_links_and_old_payload(self):
        async with self.sessions() as db:
            await self.table(db, CORE)
            await db.execute(text(f"INSERT INTO {CORE} VALUES (:id, :co, true, :cid)"), [
                {"id": uuid.uuid4(), "co": self.other_company, "cid": self.other_contract},
                {"id": uuid.uuid4(), "co": self.company, "cid": None},
            ])
            await db.execute(text(f"CREATE VIEW {PUBLIC} AS SELECT * FROM {CORE}"))
            await self.check(db, [CORE], [1])
            with patch("app.services.contract_usage._SOURCES", []):
                self.assertEqual(await usage_by_contract(db, self.other_company),
                                 {self.other_contract: {"apps": {"support"}, "projects": set()}})
                self.assertEqual(await contract_usage(db, uuid.uuid4()), [])
                self.assertEqual(await usage_by_contract(db, uuid.uuid4()), {})
