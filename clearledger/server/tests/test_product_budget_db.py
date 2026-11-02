"""Standalone synthetic PostgreSQL/ASGI/process acceptance. Never use pytest conftest.

Requires RUN_PRODUCT_BUDGET_DB_TESTS=1, explicit loopback TEST_DATABASE_URL ending
in /api_product_budget_test and a test UPLOAD_DIR. Creates only the actual quota
table and a minimal synthetic installation contract, not an entire Core schema.
Full fresh/old Core namespace compatibility belongs to the schema harness.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def safety_error(environ):
    if environ.get("RUN_PRODUCT_BUDGET_DB_TESTS") != "1":
        return "requires explicit RUN_PRODUCT_BUDGET_DB_TESTS=1"
    raw = environ.get("TEST_DATABASE_URL", "")
    try:
        url = make_url(raw)
    except Exception:
        return "requires explicit synthetic TEST_DATABASE_URL"
    if (url.drivername != "postgresql+asyncpg" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or not url.port or url.database != "api_product_budget_test"):
        return "requires explicit loopback /api_product_budget_test with port"
    upload = environ.get("UPLOAD_DIR", "")
    if not Path(upload).is_absolute() or "test" not in upload.lower():
        return "requires absolute test UPLOAD_DIR"
    return None


SAFETY_ERROR = safety_error(os.environ)
if os.environ.get("RUN_PRODUCT_BUDGET_DB_TESTS") == "1" and SAFETY_ERROR:
    raise RuntimeError("Refusing quota DB suite: " + SAFETY_ERROR)
if not SAFETY_ERROR:
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.models_partner import PartnerInstallation  # FK declarations, not copied quota DDL
from app.product_api import create_product_api, budget
from app.product_api import app as product

KEY = budget.Key(uuid.UUID(int=101), uuid.UUID(int=102), "synthetic-budget-client")


def application(sessions, policy, key=KEY):
    state = {"verify": True, "domain_calls": 0}

    async def verify(raw, db):
        if not state["verify"]:
            raise product.HTTPException(403, "SECRET revoked authoritative grant")
        return SimpleNamespace(company_id=key.company_id, installation_id=key.installation_id,
            client_id=key.client_id, app_id=uuid.UUID(int=103), grant_id=uuid.uuid4(), token_id=uuid.uuid4(),
            subject="synthetic-budget-subject", user_id=None, is_machine=True, scopes=frozenset({"objects:read"}),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            resource_scopes=MappingProxyType({"objects": MappingProxyType({"mode": "ALL", "ids": frozenset()})}))

    app = create_product_api(session_factory=sessions, verifier=verify, enabled=True, budget_policy=policy,
        issuer="https://synthetic-budget.example", cursor_key=b"synthetic-budget-cursor-key-32bytes")

    class Domain:
        async def listing(self, resource, params):
            state["domain_calls"] += 1
            return {"items": [], "total": 0, "nextCursor": None}

    async def domain():
        return Domain()

    app.dependency_overrides[product.query_dependency] = domain
    return app, state


async def request(app, path="/objects"):
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="https://synthetic-budget.example") as client:
        return await client.get(path, headers={"Authorization": "Bearer synthetic-token"})


async def process_requests(count):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"], pool_size=2, max_overflow=0)
    try:
        app, _ = application(async_sessionmaker(engine, expire_on_commit=False), budget.Policy(True, 7, 60, 2000))
        responses = [await request(app) for _ in range(count)]
        return {"pid": os.getpid(), "statuses": [r.status_code for r in responses]}
    finally:
        await engine.dispose()


class ProductBudgetSafety(unittest.TestCase):
    def test_refuses_ambient_or_unowned_database(self):
        base = {"RUN_PRODUCT_BUDGET_DB_TESTS": "1", "TEST_DATABASE_URL":
            "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:33546/api_product_budget_test",
            "UPLOAD_DIR": "/tmp/synthetic-budget-test-uploads"}
        self.assertIsNone(safety_error(base))
        for field, value in (("RUN_PRODUCT_BUDGET_DB_TESTS", "0"), ("TEST_DATABASE_URL", ""),
                ("TEST_DATABASE_URL", "postgresql+asyncpg://synthetic@customer.example:5432/api_product_budget_test"),
                ("TEST_DATABASE_URL", "postgresql+asyncpg://synthetic@127.0.0.1:33546/api_integrated_test"),
                ("UPLOAD_DIR", "/app/uploads")):
            self.assertIsNotNone(safety_error({**base, field: value}))


@unittest.skipIf(SAFETY_ERROR is not None, SAFETY_ERROR or "")
class ProductBudgetPostgres(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(os.environ["TEST_DATABASE_URL"], pool_size=10, max_overflow=0)
        self.addAsyncCleanup(self.engine.dispose)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        # Only the dedicated role/database pair may own this bounded fixture.
        async with self.engine.begin() as conn:
            actual, owned = (await conn.execute(text("SELECT current_database(), "
                "(SELECT pg_get_userbyid(datdba)=current_user FROM pg_database WHERE datname=current_database())"))).one()
            self.assertEqual(actual, "api_product_budget_test")
            self.assertTrue(owned)
            await conn.execute(text("CREATE TABLE IF NOT EXISTS partner_installations "
                "(id uuid NOT NULL, client_id varchar(64) NOT NULL, company_id uuid NOT NULL, "
                "UNIQUE(id,client_id,company_id))"))
            await conn.run_sync(lambda sync: budget.ProductAPIBudget.__table__.create(sync, checkfirst=True))
            await conn.execute(text("DELETE FROM partner_installations"))
        await self.register(KEY)
        self.policy = budget.Policy(True, 2, 60, 2000)
        self.app, self.state = application(self.sessions, self.policy)
        # Force cleanup only in its dedicated test; no probabilistic assertions.
        sampler = patch.object(budget.secrets, "randbelow", return_value=1)
        sampler.start()
        self.addCleanup(sampler.stop)

    async def register(self, key):
        async with self.engine.begin() as conn:
            await conn.execute(text("INSERT INTO partner_installations(id,client_id,company_id) "
                "VALUES (:installation_id,:client_id,:company_id)"), key.__dict__)

    def problem(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.headers["content-type"], "application/problem+json")
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        self.assertEqual((body["status"], body["code"]), (status, code))
        self.assertEqual(body["requestId"], response.headers["x-request-id"])
        uuid.UUID(body["requestId"])
        self.assertNotIn("SECRET", response.text)

    async def counter(self, key=KEY):
        async with self.engine.connect() as conn:
            return (await conn.execute(text("SELECT * FROM product_api_budgets WHERE company_id=:company_id "
                "AND installation_id=:installation_id AND client_id=:client_id"), key.__dict__)).mappings().one_or_none()

    async def test_enabled_hit_exhaust_retry_reset_and_counter_cap(self):
        self.assertEqual((await request(self.app)).status_code, 200)
        self.assertEqual((await request(self.app)).status_code, 200)
        denied = await request(self.app)
        self.problem(denied, 429, "rate_limited")
        self.assertTrue(1 <= int(denied.headers["retry-after"]) <= 60)
        self.assertEqual(self.state["domain_calls"], 2)
        for _ in range(3):
            self.problem(await request(self.app), 429, "rate_limited")
        self.assertEqual((await self.counter())["used"], 3)
        async with self.engine.begin() as conn:
            await conn.execute(text("UPDATE product_api_budgets SET reset_at=clock_timestamp()-interval '1 second'"))
        self.assertEqual((await request(self.app)).status_code, 200)
        self.assertEqual((await self.counter())["used"], 1)

    async def test_parallel_apps_share_one_counter(self):
        policy = replace(self.policy, request_limit=9)
        apps = [application(self.sessions, policy)[0] for _ in range(2)]
        responses = await asyncio.gather(*(request(apps[i % 2]) for i in range(40)))
        self.assertEqual([r.status_code for r in responses].count(200), 9)
        self.assertEqual([r.status_code for r in responses].count(429), 31)
        self.assertEqual((await self.counter())["used"], 10)

    async def test_separate_processes_share_postgres_budget(self):
        processes = [await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).resolve()),
            "--worker", "12", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE) for _ in range(3)]
        try:
            outputs = await asyncio.wait_for(asyncio.gather(*(p.communicate() for p in processes)), 40)
        finally:
            for process in processes:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        results = []
        for process, (output, errors) in zip(processes, outputs):
            self.assertEqual(process.returncode, 0, errors.decode())
            results.append(json.loads(output))
        self.assertEqual(len({r["pid"] for r in results}), 3)
        statuses = [s for r in results for s in r["statuses"]]
        self.assertEqual((statuses.count(200), statuses.count(429)), (7, 29))
        self.assertEqual((await self.counter())["used"], 8)

    async def test_company_installation_client_isolation_not_request_headers(self):
        await request(self.app)
        await request(self.app)
        self.problem(await request(self.app), 429, "rate_limited")
        for key in (replace(KEY, company_id=uuid.UUID(int=201)),
                    replace(KEY, installation_id=uuid.UUID(int=202)), replace(KEY, client_id="other-client")):
            await self.register(key)
            app, _ = application(self.sessions, self.policy, key)
            self.assertEqual((await request(app)).status_code, 200)
            self.assertEqual((await self.counter(key))["used"], 1)

    async def test_live_acl_denial_before_quota_and_no_false_release(self):
        await request(self.app)
        self.state["verify"] = False
        self.problem(await request(self.app), 403, "access_denied")
        self.assertEqual((await self.counter())["used"], 1)
        self.state["verify"] = True
        self.problem(await request(self.app, "/objects?limit=0"), 422, "invalid_request")
        self.problem(await request(self.app), 429, "rate_limited")

    async def test_disabled_zero_quota_queries_even_without_table(self):
        app, _ = application(self.sessions, budget.Policy(False))
        async with self.engine.begin() as conn:
            await conn.execute(text("ALTER TABLE product_api_budgets RENAME TO product_api_budgets_hidden"))
        try:
            for _ in range(4):
                self.assertEqual((await request(app)).status_code, 200)
        finally:
            async with self.engine.begin() as conn:
                await conn.execute(text("ALTER TABLE product_api_budgets_hidden RENAME TO product_api_budgets"))

    async def test_store_missing_table_fails_closed_with_safe_problem503(self):
        async with self.engine.begin() as conn:
            await conn.execute(text("ALTER TABLE product_api_budgets RENAME TO product_api_budgets_hidden"))
        try:
            self.problem(await request(self.app), 503, "api_unavailable")
            self.assertEqual(self.state["domain_calls"], 0)
        finally:
            async with self.engine.begin() as conn:
                await conn.execute(text("ALTER TABLE product_api_budgets_hidden RENAME TO product_api_budgets"))

    async def test_db_clock_is_evaluated_after_conflicting_row_lock_wait(self):
        app, _ = application(self.sessions, replace(self.policy, request_limit=1, window_seconds=1))
        self.assertEqual((await request(app)).status_code, 200)
        async with self.engine.connect() as conn:
            transaction = await conn.begin()
            await conn.execute(text("UPDATE product_api_budgets SET reset_at=clock_timestamp()+interval '0.2 seconds'"))
            waiting = asyncio.create_task(request(app))
            try:
                await asyncio.sleep(0.45)
                self.assertFalse(waiting.done(), "Probe must really wait on the locked row")
                await transaction.commit()
                response = await waiting
            finally:
                if transaction.is_active:
                    await transaction.rollback()
                if not waiting.done():
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
        self.assertEqual(response.status_code, 200, response.text)
        async with self.engine.connect() as conn:
            remaining = await conn.scalar(text("SELECT EXTRACT(EPOCH FROM reset_at-clock_timestamp()) FROM product_api_budgets"))
        self.assertGreater(float(remaining), 0.6, "Reset clock must come from effective update, not pre-lock insert")

    async def test_lock_timeout_and_active_policy_drift_fail_closed(self):
        await request(self.app)
        app, _ = application(self.sessions, replace(self.policy, request_limit=3))
        self.problem(await request(app), 503, "api_unavailable")
        self.assertEqual((await self.counter())["used"], 1)
        async with self.engine.begin() as conn:
            await conn.execute(text("SELECT 1 FROM product_api_budgets FOR UPDATE"))
            app, _ = application(self.sessions, replace(self.policy, timeout_ms=100))
            self.problem(await request(app), 503, "api_unavailable")
        self.assertEqual((await self.counter())["used"], 1)

    async def test_bounded_cleanup_skips_locked_and_preserves_active_rows(self):
        await request(self.app)
        async with self.engine.begin() as conn:
            await conn.execute(text("INSERT INTO partner_installations(id,client_id,company_id) "
                "SELECT md5(i::text)::uuid, 'cleanup-client', :company FROM generate_series(1,70) i"), {"company": KEY.company_id})
            await conn.execute(text("INSERT INTO product_api_budgets "
                "SELECT company_id,id,client_id,1,clock_timestamp()-interval '25 hours'-interval '1 second'*row_number() OVER (),2,60 "
                "FROM partner_installations WHERE client_id='cleanup-client'"))
        async with self.engine.begin() as locked:
            await locked.execute(text("SELECT 1 FROM product_api_budgets WHERE client_id='cleanup-client' ORDER BY reset_at LIMIT 1 FOR UPDATE"))
            with patch.object(budget.secrets, "randbelow", return_value=0):
                self.assertEqual((await request(self.app)).status_code, 200)
        async with self.engine.connect() as conn:
            self.assertEqual(await conn.scalar(text("SELECT count(*) FROM product_api_budgets WHERE client_id='cleanup-client'")), 6)
            self.assertEqual((await self.counter())["used"], 2)
            async with conn.begin_nested():
                await conn.execute(text("SET LOCAL enable_seqscan=off"))
                plan = (await conn.execute(text("EXPLAIN SELECT * FROM product_api_budgets "
                    "WHERE reset_at < statement_timestamp()-interval '24 hours' ORDER BY reset_at LIMIT 64"))).scalars().all()
                self.assertIn("ix_product_api_budgets_reset", " ".join(plan))

    async def test_installation_delete_cascades_budget(self):
        await request(self.app)
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM partner_installations"))
        self.assertIsNone(await self.counter())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        if SAFETY_ERROR:
            raise RuntimeError("Worker requires synthetic DB opt-in")
        print(json.dumps(asyncio.run(process_requests(int(sys.argv[2])))))
    else:
        unittest.main()
