"""Opt-in destructive PostgreSQL namespace tests, confined to one synthetic DB.

Run via unittest, never the repository's destructive pytest conftest.
No role/cluster defaults are changed; search_path belongs to each test engine.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import Column, ForeignKey, Table, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_NAMESPACE_OWNERSHIP_TESTS"
OWN_DATABASE = "api_namespace_ownership_test"
REPO = Path(__file__).resolve().parents[3]


def safety_error(environ):
    error = partner_test_safety_error(environ, flag=FLAG)
    if error:
        return error
    if make_url(environ["TEST_DATABASE_URL"]).database != OWN_DATABASE:
        return "this bounded suite requires its dedicated namespace ownership test database"
    return None


class NamespaceTestSafety(unittest.TestCase):
    def test_explicit_intent_owned_database_and_uploads_required(self):
        values = {FLAG: "1", "TEST_DATABASE_URL":
            "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:33546/" + OWN_DATABASE,
            "UPLOAD_DIR": "/tmp/namespace-ownership-test-uploads"}
        self.assertIsNone(safety_error(values))
        for replacement in ({FLAG: "0"}, {"TEST_DATABASE_URL": ""},
                            {"UPLOAD_DIR": "/tmp/uploads"},
                            {"TEST_DATABASE_URL": values["TEST_DATABASE_URL"].replace(OWN_DATABASE, "other_test")}):
            self.assertIsNotNone(safety_error({**values, **replacement}))

    def test_connection_override_and_remote_host_rejected_without_secret_echo(self):
        for url in (f"postgresql+asyncpg://synthetic:SECRET@192.0.2.1:33546/{OWN_DATABASE}",
                    f"postgresql+asyncpg://synthetic:SECRET@127.0.0.1/{OWN_DATABASE}?options=-csearch_path=public"):
            error = safety_error({FLAG: "1", "TEST_DATABASE_URL": url,
                                  "UPLOAD_DIR": "/tmp/namespace-ownership-test-uploads"})
            self.assertIsNotNone(error)
            self.assertNotIn("SECRET", error)


@unittest.skipUnless(os.environ.get(FLAG) == "1", "SQL requires explicit namespace ownership test window")
class SchemaNamespaceOwnership(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        error = safety_error(os.environ)
        if error:
            raise RuntimeError(error)
        self.url = os.environ["TEST_DATABASE_URL"]
        from app import config
        settings = config.Settings(_env_file=None, database_url=self.url, SECRET_KEY="namespace-test-only")
        with patch.object(config, "get_settings", return_value=settings):
            from app import database
            from app.main import app as model_registration  # Registration only, no lifespan/seed/HTTP.
        self.database = database
        self.assertEqual(database.settings.database_url, self.url)
        self.engines = []
        self.control = self.engine("pg_catalog")
        self.addAsyncCleanup(self.dispose_engines)
        async with self.control.connect() as conn:
            actual, owns = (await conn.execute(text("SELECT current_database(), "
                "(SELECT datdba=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
                "FROM pg_database WHERE datname=current_database())"))).one()
            self.assertEqual(actual, OWN_DATABASE)
            self.assertTrue(owns, "Synthetic test role must own this database")
        self.addAsyncCleanup(self.finish)
        await self.reset()
        self.owned = sorted(t.name for t in database.Base.metadata.tables.values()
                            if t.schema is None and t.name.startswith("partner_"))
        self.assertEqual(len(self.owned), 13)

    def engine(self, path):
        engine = create_async_engine(self.url, pool_size=2, max_overflow=0,
            connect_args={"server_settings": {"search_path": path, "statement_timeout": "60000"}})
        self.engines.append(engine)
        return engine

    async def reset(self):
        async with self.control.connect() as conn:
            names = (await conn.execute(text("SELECT n.nspname,c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname IN ('core','public','edge') AND c.relkind IN ('r','p') ORDER BY 1,2"))).all()
            quote = conn.dialect.identifier_preparer.quote_identifier
        for offset in range(0, len(names), 8):
            batch = ",".join(f"{quote(s)}.{quote(t)}" for s, t in names[offset:offset + 8])
            async with self.control.begin() as conn:
                await conn.execute(text("DROP TABLE IF EXISTS " + batch + " CASCADE"))
        for schema in ("edge", "core", "public"):
            async with self.control.begin() as conn:
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
                await conn.execute(text(f"CREATE SCHEMA {schema}"))

    async def finish(self):
        await self.reset()

    async def dispose_engines(self):
        for engine in self.engines:
            await engine.dispose()

    async def bootstrap(self, path):
        engine = self.engine(path)
        with patch.object(self.database, "engine", engine):
            await self.database.create_all()
        return engine

    async def catalog(self, namespace):
        async with self.control.connect() as conn:
            return [tuple(row) for row in (await conn.execute(text("SELECT c.oid,c.relname,c.relowner,c.relacl::text "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=:schema AND c.relkind IN ('r','p') ORDER BY c.relname"), {"schema": namespace})).all()]

    async def functions(self, namespace):
        async with self.control.connect() as conn:
            return [tuple(row) for row in (await conn.execute(text("SELECT p.oid,p.proname,p.prosrc,p.proowner,p.proacl::text "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=:schema ORDER BY p.oid"), {"schema": namespace})).all()]

    async def public_snapshot(self):
        result = {}
        async with self.control.connect() as conn:
            for oid, name, owner, acl in await self.catalog("public"):
                quoted = conn.dialect.identifier_preparer.quote_identifier(name)
                columns = (await conn.execute(text("SELECT attnum,attname,format_type(atttypid,atttypmod),attnotnull "
                    "FROM pg_attribute WHERE attrelid=:oid AND attnum>0 AND NOT attisdropped ORDER BY attnum"), {"oid": oid})).all()
                constraints = (await conn.execute(text("SELECT oid,conname,contype,pg_get_constraintdef(oid) "
                    "FROM pg_constraint WHERE conrelid=:oid ORDER BY conname"), {"oid": oid})).all()
                rows = (await conn.execute(text(f"SELECT * FROM public.{quoted} ORDER BY id"))).all()
                result[name] = (oid, owner, acl, [tuple(c) for c in columns], [tuple(c) for c in constraints], [tuple(r) for r in rows])
        return result

    async def support(self, partner=False):
        async with self.control.begin() as conn:
            await conn.execute(text("CREATE TABLE public.users (id uuid PRIMARY KEY,email text NOT NULL,name text NOT NULL)"))
            await conn.execute(text("CREATE TABLE public.companies (id uuid PRIMARY KEY,name text NOT NULL)"))
            await conn.execute(text("INSERT INTO public.users VALUES (:id,'support@example.invalid','Support sentinel')"), {"id": uuid.UUID(int=101)})
            await conn.execute(text("INSERT INTO public.companies VALUES (:id,'Support company sentinel')"), {"id": uuid.UUID(int=102)})
            if partner:
                await conn.execute(text("CREATE TABLE public.partner_clients (id varchar(64) PRIMARY KEY,support_marker text NOT NULL)"))
                await conn.execute(text("INSERT INTO public.partner_clients VALUES ('support-client','not Core OAuth')"))
        return await self.public_snapshot()

    async def foreign_fks(self):
        async with self.control.connect() as conn:
            return [tuple(r) for r in (await conn.execute(text("SELECT k.oid,k.conrelid,k.confrelid,c.relname,p.relname "
                "FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_class p ON p.oid=k.confrelid JOIN pg_namespace pn ON pn.oid=p.relnamespace "
                "WHERE k.contype='f' AND n.nspname='core' AND pn.nspname='public' ORDER BY c.relname,k.conname"))).all()]

    async def remove_partner_tables(self):
        async with self.control.begin() as conn:
            for name in self.owned:
                await conn.execute(text(f'DROP TABLE IF EXISTS core."{name}" CASCADE'))

    async def assert_owned(self, engine, namespace):
        async with engine.connect() as conn:
            for name in ("users", "companies", *self.owned):
                visible, qualified, found = (await conn.execute(text("SELECT to_regclass(:name)::oid, "
                    "to_regclass(:qualified)::oid,(SELECT n.nspname FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE c.oid=to_regclass(:name))"),
                    {"name": name, "qualified": namespace + "." + name})).one()
                self.assertIsNotNone(qualified, name)
                self.assertEqual(visible, qualified, name)
                self.assertEqual(found, namespace, name)

    async def attempt_with_evidence(self, label):
        try:
            await self.bootstrap("core, public")
        except Exception as error:
            failure = error
        else:
            failure = None
        core = await self.catalog("core")
        foreign = await self.foreign_fks()
        evidence = dict(case=label, error=type(failure).__name__ if failure else None,
            core_relations=len(core), missing_owned=sorted(set(self.owned) - {row[1] for row in core}),
            foreign_fk_count=len(foreign), foreign_fk_oids=foreign[:5])
        print("NAMESPACE_EVIDENCE " + json.dumps(evidence), flush=True)
        return failure

    async def old_orm_control(self, engine, namespace):
        """Actual ce94e2bf ORM source, no old app startup or implicit DB defaults."""
        from app.models import Company, User
        async with async_sessionmaker(engine, expire_on_commit=False).begin() as session:
            company = Company(name="Synthetic Core master", slug="namespace-old-control", profile_id="energy")
            session.add(company)
            await session.flush()
            user = User(email="namespace-old@example.invalid", name="Synthetic old ORM user",
                        company_id=company.id, password_hash="no-login-test", role="user")
            session.add(user)
            await session.flush()
            ids = dict(company=str(company.id), user=str(user.id))
        script = r'''
import asyncio,json,os,uuid
from sqlalchemy import select,text
from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine
from app.models import Company,User
async def main():
    ids=json.loads(os.environ["NAMESPACE_TEST_IDS"])
    namespace=os.environ["NAMESPACE_TEST_SCHEMA"]
    engine=create_async_engine(os.environ["TEST_DATABASE_URL"],connect_args={"server_settings":{"search_path":namespace+", public"}})
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT current_database()"))=="api_namespace_ownership_test"
            for name in ("users","companies"):
                visible,owned=(await conn.execute(text("SELECT to_regclass(:name)::oid,to_regclass(:owned)::oid"),{"name":name,"owned":namespace+"."+name})).one()
                assert visible==owned and owned is not None
        async with async_sessionmaker(engine).begin() as session:
            user=await session.get(User,uuid.UUID(ids["user"]))
            company=await session.get(Company,uuid.UUID(ids["company"]))
            assert user.company_id==company.id and user.email=="namespace-old@example.invalid"
            company.name="Written by immutable old ORM"
        print("OLD_ORM_CONTROL "+namespace+" ce94e2bf PASS")
    finally:
        await engine.dispose()
asyncio.run(main())
'''
        with TemporaryDirectory(prefix="namespace-old-test-") as folder:
            root = Path(folder)
            (root / "app").mkdir()
            for name in ("__init__.py", "models.py", "database.py", "config.py"):
                source = subprocess.check_output(["git", "show", "ce94e2bf:clearledger/server/app/" + name], cwd=REPO)
                (root / "app" / name).write_bytes(source)
            result = subprocess.run([sys.executable, "-c", script], cwd=root, timeout=60,
                env={"PYTHONPATH": str(root), "TEST_DATABASE_URL": self.url, "DATABASE_URL": self.url,
                     "SECRET_KEY": "old-namespace-test-only", "NAMESPACE_TEST_IDS": json.dumps(ids),
                     "NAMESPACE_TEST_SCHEMA": namespace}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            print(result.stdout.strip())
        async with async_sessionmaker(engine).begin() as session:
            self.assertEqual((await session.get(Company, company.id)).name, "Written by immutable old ORM")

    async def test_partner_shadow_fails_before_ddl_and_preserves_public(self):
        await self.bootstrap("core")  # Real Core masters, not reconstructed table stubs.
        await self.remove_partner_tables()
        before = await self.catalog("core")
        functions = await self.functions("core")
        sentinel = await self.support(partner=True)
        error = await self.attempt_with_evidence("existing-Core-public-partner-shadow")
        self.assertEqual(await self.public_snapshot(), sentinel)
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("schema ownership", str(error).lower())
        self.assertEqual(await self.catalog("core"), before)
        self.assertEqual(await self.functions("core"), functions)
        self.assertEqual(await self.foreign_fks(), [])
        # Explicit synthetic provisioning recovery; no runtime copy/rename of public data.
        await self.bootstrap("core")
        engine = await self.bootstrap("core, public")
        await self.assert_owned(engine, "core")
        self.assertEqual(await self.public_snapshot(), sentinel)
        self.assertEqual(await self.foreign_fks(), [])

    async def test_support_first_fresh_core_fails_before_ddl(self):
        # Explicit prerequisite: Support owns public masters; Core is still empty.
        sentinel = await self.support()
        error = await self.attempt_with_evidence("fresh-Core-after-Support")
        self.assertEqual(await self.public_snapshot(), sentinel)
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("schema ownership", str(error).lower())
        self.assertEqual(await self.catalog("core"), [])
        self.assertEqual(await self.functions("core"), [])

    async def test_missing_current_namespace_fails_without_ddl(self):
        before = await self.catalog("public")
        functions = await self.functions("public")
        with self.assertRaisesRegex(RuntimeError, "schema ownership"):
            await self.bootstrap("namespace_does_not_exist")
        self.assertEqual(await self.catalog("public"), before)
        self.assertEqual(await self.functions("public"), functions)
        self.assertEqual(await self.catalog("core"), [])

    async def test_core_without_shadow_creates_owned_tables_and_repeats(self):
        await self.bootstrap("core")
        await self.remove_partner_tables()
        masters = await self.catalog("core")
        sentinel = await self.support()
        engine = await self.bootstrap("core, public")
        await self.assert_owned(engine, "core")
        self.assertTrue(set(masters) <= set(await self.catalog("core")))
        after = await self.catalog("core")
        await self.bootstrap("core, public")
        self.assertEqual(await self.catalog("core"), after)
        self.assertEqual(await self.public_snapshot(), sentinel)
        self.assertEqual(await self.foreign_fks(), [])
        await self.old_orm_control(engine, "core")
        self.assertEqual(await self.public_snapshot(), sentinel)

    async def test_existing_core_table_wins_over_public_same_name(self):
        await self.bootstrap("core")
        before = await self.catalog("core")
        sentinel = await self.support(partner=True)
        engine = await self.bootstrap("core, public")
        await self.assert_owned(engine, "core")
        self.assertEqual(await self.catalog("core"), before)
        self.assertEqual(await self.public_snapshot(), sentinel)
        self.assertEqual(await self.foreign_fks(), [])

    async def test_explicit_edge_table_does_not_inherit_core_or_public_shadow(self):
        await self.bootstrap("core")
        async with self.control.begin() as conn:
            await conn.execute(text("CREATE TABLE public.namespace_explicit_owner (id uuid PRIMARY KEY,marker text)"))
            await conn.execute(text("INSERT INTO public.namespace_explicit_owner VALUES (:id,'foreign explicit shadow')"),
                               {"id": uuid.UUID(int=103)})
        sentinel = await self.public_snapshot()
        table = Table("namespace_explicit_owner", self.database.Base.metadata,
            Column("id", UUID(as_uuid=True), primary_key=True),
            Column("company_id", UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE")), schema="edge")
        self.addCleanup(self.database.Base.metadata.remove, table)
        await self.bootstrap("core, public")
        self.assertEqual(await self.public_snapshot(), sentinel)
        async with self.control.connect() as conn:
            edge, public, target = (await conn.execute(text("SELECT to_regclass('edge.namespace_explicit_owner')::oid,"
                "to_regclass('public.namespace_explicit_owner')::oid, "
                "(SELECT confrelid FROM pg_constraint WHERE conrelid=to_regclass('edge.namespace_explicit_owner') "
                "AND contype='f')"))).one()
            self.assertIsNotNone(edge)
            self.assertNotEqual(edge, public)
            self.assertEqual(target, await conn.scalar(text("SELECT to_regclass('core.companies')::oid")))

    async def test_standalone_public_bootstrap_and_repeat(self):
        engine = await self.bootstrap("public")
        await self.assert_owned(engine, "public")
        before = await self.catalog("public")
        await self.bootstrap("public")
        self.assertEqual(await self.catalog("public"), before)
        self.assertEqual(await self.catalog("core"), [])
        await self.old_orm_control(engine, "public")


if __name__ == "__main__":
    unittest.main()
