"""ROOT-only Core migration and actual old/new ORM DML on one disposable DB.

No module-level DB/app imports; the approved adapter installs exact target,
source, environment and I/O boundaries before unittest discovers these cases.
"""
import asyncio
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
import uuid

from schema_migrations import catalog, manifest, runner
from schema_migrations.errors import MigrationError

SERVER = Path(__file__).resolve().parents[2]
DATABASE = "api_calendar_protocol_version_test_20261031"
RAW = "postgresql://clearledger:api_test_only@127.0.0.1:33546/" + DATABASE
BASE_MODEL = "f066910e5bf5e2e37346edc8c78693d3673868186c925e1aad67f1d816f2104e"
CID = uuid.UUID("c2090000-0000-4000-8000-000000000001")
UID = uuid.UUID("c2090000-0000-4000-8000-000000000002")


def config(**kwargs):
    return runner.Config(RAW, DATABASE, "clearledger", "core", **kwargs)


@lru_cache(maxsize=2)
def model_source(legacy):
    """Actual source, schema-only Base adapter; no real app.database/config/main."""
    from sqlalchemy.orm import DeclarativeBase

    path = Path(os.environ["M09_BASELINE_BLOB"]) if legacy else SERVER / "app/models.py"
    raw = path.read_bytes()
    if legacy and hashlib.sha256(raw).hexdigest() != BASE_MODEL:
        raise RuntimeError("Old model source differs from frozen Git blob")
    class OnlyBase(DeclarativeBase):
        pass
    database = ModuleType("app.database")
    database.Base = OnlyBase
    previous = sys.modules.get("app.database")
    name = "m09_legacy_models" if legacy else "m09_current_models"
    module = ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    sys.modules["app.database"] = database
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
    finally:
        if previous is None:
            sys.modules.pop("app.database", None)
        else:
            sys.modules["app.database"] = previous
    return module.CalendarEvent


class ProtocolMigration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncpg
        self.conn = await asyncpg.connect(RAW, timeout=5, command_timeout=10,
            server_settings={"search_path": "pg_catalog", "statement_timeout": "10000", "lock_timeout": "1000"})
        self.addAsyncCleanup(self.conn.close)
        existing = await self.conn.fetch("""SELECT n.nspname,c.relname FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
            AND n.nspname NOT LIKE 'pg_temp%' AND c.relkind IN ('r','p','v','m','S','f')""")
        self.assertEqual(existing, [], "Only a fresh exact owned test DB is accepted")
        self.addAsyncCleanup(self.cleanup)
        await self.conn.execute("CREATE SCHEMA core")
        await self.conn.execute("""CREATE TABLE core.partner_installations (
            id uuid PRIMARY KEY,client_id varchar(64) NOT NULL,company_id uuid NOT NULL,
            CONSTRAINT uq_partner_install_client_company UNIQUE(id,client_id,company_id));
            CREATE TABLE core.companies (id uuid PRIMARY KEY);
            CREATE TABLE core.users (id uuid PRIMARY KEY);
            CREATE TABLE public.calendar_protocol_sentinel (value text NOT NULL)""")
        await self.conn.execute("INSERT INTO core.companies VALUES ($1)", CID)
        await self.conn.execute("INSERT INTO core.users VALUES ($1)", UID)
        await self.conn.execute("INSERT INTO public.calendar_protocol_sentinel VALUES ('unchanged')")
        self.package = manifest.load(revision=manifest.CALENDAR_ID)
        await runner.execute(config(), "apply")

    async def cleanup(self):
        for name in ("calendar_events", "users", "companies", "product_api_budgets", "core_schema_versions", "partner_installations"):
            if await self.conn.fetchval("SELECT pg_catalog.to_regclass($1)", "core." + name):
                await self.conn.execute("DROP TABLE core." + name)
        await self.conn.execute("DROP TABLE public.calendar_protocol_sentinel")
        await self.conn.execute("DROP SCHEMA core")

    async def calendar(self, *, legacy=True):
        from sqlalchemy.dialects.postgresql import dialect
        from sqlalchemy.schema import CreateIndex, CreateTable
        cls = model_source(legacy)
        await self.conn.execute("SET search_path TO core")
        await self.conn.execute(str(CreateTable(cls.__table__).compile(dialect=dialect())))
        for index in cls.__table__.indexes:
            await self.conn.execute(str(CreateIndex(index).compile(dialect=dialect())))
        return cls

    async def old_insert(self, *, legacy=True):
        from datetime import datetime, timedelta, timezone
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        cls = model_source(legacy)
        engine = create_async_engine(RAW.replace("postgresql:", "postgresql+asyncpg:", 1),
            connect_args={"server_settings": {"search_path": "core"}})
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                start = datetime(2026, 11, 1, tzinfo=timezone.utc)
                event = cls(company_id=CID, organizer_id=UID, title="Old ORM compatibility",
                            starts_at=start, ends_at=start + timedelta(hours=1))
                session.add(event)
                await session.commit()
                event.title = "Old-column update"
                await session.commit()
                return event.id
        finally:
            await engine.dispose()

    async def apply(self, **kwargs):
        return await runner.execute(config(**kwargs), "apply", revision=manifest.CALENDAR_ID, legacy_sent_before=2_000_000_000)

    async def snapshot(self):
        result = {}
        for name in ("calendar_events", "product_api_budgets", "core_schema_versions", "partner_installations"):
            if await self.conn.fetchval("SELECT pg_catalog.to_regclass($1)", "core." + name):
                result[name] = [dict(row) for row in await self.conn.fetch(
                    "SELECT xmin::text AS tuple_xmin,ctid::text AS tuple_ctid,* FROM core." + name + " ORDER BY 1,2")]
        result["public_sentinel"] = list(await self.conn.fetch("SELECT * FROM public.calendar_protocol_sentinel"))
        return result

    async def reject(self, code=4):
        before = await self.snapshot()
        with self.assertRaises(MigrationError) as error:
            await self.apply()
        self.assertEqual(error.exception.code, code)
        self.assertEqual(await self.snapshot(), before)

    async def test_01_upgrade_repeat_old_orm_and_new_orm_defaults(self):
        await self.calendar()
        # Before upgrade the exact old ORM DML succeeds with its original columns.
        old_id = await self.old_insert()
        before = await self.snapshot()
        self.assertEqual((await self.apply())["action"], "created")
        first = await self.snapshot()
        row = next(r for r in first["calendar_events"] if r["id"] == old_id)
        self.assertEqual(row["protocol_sequence"], 2_000_000_000)
        self.assertEqual({k:v for k,v in row.items() if k != "protocol_sequence"}, before["calendar_events"][0])
        old_again = await self.old_insert()
        new_id = await self.old_insert(legacy=False)
        values = dict(await self.conn.fetch("SELECT id,protocol_sequence FROM core.calendar_events"))
        self.assertEqual(values[old_again], 2_000_000_000)
        self.assertEqual(values[new_id], 0)
        stable = await self.snapshot()
        self.assertEqual((await self.apply())["action"], "verified")
        self.assertEqual((await runner.execute(config(), "check", revision=manifest.CALENDAR_ID))["action"], "verified")
        self.assertEqual(await self.snapshot(), stable)
        with self.assertRaises(MigrationError):
            await runner.execute(config(), "check")  # old default owner refuses newer history

    async def test_02_fresh_model_adoption_preserves_data_and_history_prefix(self):
        await self.calendar(legacy=False)
        new_id = await self.old_insert(legacy=False)
        before = await self.snapshot()
        self.assertEqual((await self.apply())["action"], "adopted")
        after = await self.snapshot()
        self.assertEqual(before["calendar_events"], after["calendar_events"])
        self.assertEqual(before["core_schema_versions"][0], after["core_schema_versions"][0])
        self.assertEqual(await self.conn.fetchval("SELECT protocol_sequence FROM core.calendar_events WHERE id=$1", new_id), 0)
        self.assertEqual(after["public_sentinel"], before["public_sentinel"])

    async def test_03_partial_column_refuses_without_repair(self):
        await self.calendar()
        await self.conn.execute("ALTER TABLE core.calendar_events ADD COLUMN protocol_sequence integer")
        await self.reject()

    async def test_04_future_stored_timestamp_refuses_before_ddl(self):
        await self.calendar()
        event_id = await self.old_insert()
        await self.conn.execute("UPDATE core.calendar_events SET updated_at='2035-01-01' WHERE id=$1", event_id)
        await self.reject()
        self.assertFalse(await self.conn.fetchval("SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_attribute "
            "WHERE attrelid='core.calendar_events'::regclass AND attname='protocol_sequence')"))

    async def test_05_acknowledgement_and_verified_parent_required(self):
        await self.calendar()
        with self.assertRaises(MigrationError) as error:
            await runner.execute(config(), "apply", revision=manifest.CALENDAR_ID)
        self.assertEqual(error.exception.code, 2)
        await self.conn.execute("DELETE FROM core.core_schema_versions")
        await self.reject()

    async def test_06_chain_tampering_and_unknown_history_refuse(self):
        await self.calendar()
        await self.apply()
        await self.conn.execute("UPDATE core.core_schema_versions SET predecessor_sha256=$1 WHERE ordinal=2", "0"*64)
        await self.reject()

    async def test_07_two_actual_migrators_serialize_and_recheck(self):
        await self.calendar()
        results = await asyncio.gather(self.apply(), self.apply())
        self.assertEqual(sorted(r["action"] for r in results), ["created", "verified"])
        self.assertEqual(await self.conn.fetchval("SELECT count(*) FROM core.core_schema_versions"), 2)

    async def test_08_blocked_application_writer_times_out_without_schema_change(self):
        import asyncpg
        await self.calendar()
        event_id = await self.old_insert()
        blocker = await asyncpg.connect(RAW, timeout=5)
        try:
            async with blocker.transaction():
                await blocker.execute("UPDATE core.calendar_events SET title=title WHERE id=$1", event_id)
                before = await self.snapshot()
                with self.assertRaises(MigrationError):
                    await self.apply(total_seconds=1)
                self.assertEqual(await self.snapshot(), before)
        finally:
            await blocker.close()

    async def test_09_failure_after_alter_rolls_back_column_and_history(self):
        from unittest.mock import patch
        await self.calendar()
        before = await self.snapshot()
        async def fail(*args):
            raise MigrationError(6, "injected_postcondition")
        with patch.object(catalog, "verify_calendar_preserved", fail):
            with self.assertRaises(MigrationError):
                await self.apply()
        self.assertEqual(await self.snapshot(), before)
        self.assertFalse(await self.conn.fetchval("SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_attribute "
            "WHERE attrelid='core.calendar_events'::regclass AND attname='protocol_sequence')"))
