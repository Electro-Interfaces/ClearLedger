"""Portable pure checks: no PostgreSQL, application startup or test fixtures."""
from datetime import date, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api_contracts import policy_registry
from app.product_api import create_product_api, curated_openapi, export_runtime_registry
from app.product_api.dto import MonitoringQuery
from app.product_api.monitoring import detail
from app.services.ops_monitor_context import visit_summary


class MonitoringContractTest(unittest.TestCase):
    def test_portable_explicit_test_database_guard(self):
        from tests.partner_test_safety import partner_test_safety_error
        flag = "RUN_MONITORING_SQL_TESTS"
        valid = {flag: "1", "TEST_DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@localhost:5432/monitoring_ci_test",
                 "UPLOAD_DIR": "/tmp/monitoring_test_uploads"}
        self.assertIsNone(partner_test_safety_error(valid, flag))
        self.assertIsNotNone(partner_test_safety_error({}, flag))
        self.assertIsNotNone(partner_test_safety_error({flag: "1"}, flag))
        self.assertIsNotNone(partner_test_safety_error({**valid, "UPLOAD_DIR": "relative"}, flag))
        self.assertIsNotNone(partner_test_safety_error({**valid, "TEST_DATABASE_URL": valid["TEST_DATABASE_URL"].replace("localhost", "203.0.113.5")}, flag))
        self.assertIsNone(partner_test_safety_error({**valid, "CI": "true", "TEST_DATABASE_URL": valid["TEST_DATABASE_URL"].replace("localhost", "postgres")}, flag))

    def test_dates_and_bounded_window(self):
        self.assertEqual(MonitoringQuery(asOf="2026-10-01", days="366").asOf, date(2026, 10, 1))
        for value in ("20261001", "2026-10-01T00:00:00Z", "01.10.2026", "2026-02-30", 1790812800):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                MonitoringQuery(asOf=value)
        for days in (0, 367, -1):
            with self.assertRaises(ValidationError):
                MonitoringQuery(days=days)
        for key in ("cursor", "q", "companyId", "locationIds", "dateFrom"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                MonitoringQuery(**{key: "anything"})

    def test_curated_operation_scopes_registry_and_private_spec(self):
        app = create_product_api(issuer="https://synthetic.example", enabled=True)
        schema = curated_openapi(app)
        path = "/objects/{objectId}/monitoring"
        operation = schema["paths"][path]["get"]
        self.assertEqual(operation["security"], [{"ProductOAuth": ["monitoring:read", "objects:read"]},
                                                {"ProductServiceOAuth": ["monitoring:read", "objects:read"]}])
        self.assertEqual(operation["operationId"], "getObjectMonitoring")
        scopes = schema["components"]["securitySchemes"]["ProductOAuth"]["flows"]["authorizationCode"]["scopes"]
        self.assertIn("monitoring:read", scopes)
        binding = next(entry for entry in policy_registry(app) if entry["path"] == path)
        self.assertEqual(binding["scopes"], ["monitoring:read", "objects:read"])
        self.assertTrue(any(row["operationId"] == "getObjectMonitoring" for row in export_runtime_registry(app)["operations"]))
        self.assertFalse(any(route.path in {"/docs", "/openapi.json", "/redoc"} for route in app.routes))
        props = schema["components"]["schemas"]["Monitoring"]["properties"]
        self.assertEqual(set(props), {"pointId", "status", "window", "totals", "lastSeenAt", "provenance"})


class MonitoringSeamTest(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_is_unavailable_without_database_and_post_is_not_supported(self):
        def no_database():
            raise AssertionError("Disabled read must not connect")
        app = create_product_api(session_factory=no_database, enabled=False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://synthetic.example") as client:
            response = await client.get("/objects/point/monitoring")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["cache-control"], "no-store")
            response = await client.post("/objects/point/monitoring", json={})
            self.assertEqual(response.status_code, 405)

    async def test_not_visible_object_never_reads_aggregate_helpers(self):
        query = SimpleNamespace(detail=AsyncMock(side_effect=HTTPException(404)), db=AsyncMock())
        with patch("app.product_api.monitoring.session_boundary", AsyncMock()) as boundary:
            with self.assertRaises(HTTPException) as raised:
                await detail(query, "foreign", MonitoringQuery())
            self.assertEqual(raised.exception.status_code, 404)
            boundary.assert_not_awaited()
            query.db.scalar.assert_not_awaited()

    async def test_non_energy_never_reads_aggregates(self):
        query = SimpleNamespace(detail=AsyncMock(return_value=SimpleNamespace(id="x")),
            db=SimpleNamespace(scalar=AsyncMock(return_value="fuel")), facts=SimpleNamespace(company_id="company"))
        with patch("app.product_api.monitoring.session_boundary", AsyncMock()) as boundary:
            with self.assertRaises(HTTPException) as raised:
                await detail(query, "x", MonitoringQuery())
            self.assertEqual(raised.exception.status_code, 404)
            boundary.assert_not_awaited()

    async def test_unknown_status_empty_data_and_object_ceiling(self):
        query = SimpleNamespace(detail=AsyncMock(return_value=SimpleNamespace(id="opaque", operational_status="NEW-RAW")),
            db=SimpleNamespace(scalar=AsyncMock(return_value="energy")), facts=SimpleNamespace(company_id="company"))
        with patch("app.product_api.monitoring.session_boundary", AsyncMock(return_value=None)) as boundary, \
             patch("app.product_api.monitoring.session_summary", AsyncMock(return_value={"sessions": 0, "energyKwh": 0})) as sessions, \
             patch("app.product_api.monitoring.visit_summary", AsyncMock(return_value={})) as visits:
            result = await detail(query, "opaque", MonitoringQuery(asOf="2026-10-01", days=1))
        self.assertEqual(result.status, "unknown")
        self.assertIsNone(result.provenance.data_through)
        self.assertIsNone(result.provenance.data_lag_hours)
        self.assertIsNone(result.last_seen_at)
        self.assertEqual(result.totals.visits, 0)
        for call in [*boundary.await_args_list, sessions.await_args, visits.await_args]:
            self.assertEqual(call.kwargs["location_ids"], {"opaque"})
        self.assertEqual(result.window.end.isoformat(), "2026-10-01T23:59:59.999999+03:00")
        self.assertEqual((result.window.end - result.window.start).days, 1)

    async def test_visit_filter_precedes_grouping_default_contract_and_empty(self):
        rows = SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))
        db = SimpleNamespace(execute=AsyncMock(return_value=rows))
        now = datetime(2026, 1, 1)
        for scope in (None, set(), {"point"}):
            await visit_summary(db, "company", now, now, location_ids=scope)
            sql, params = db.execute.await_args.args
            sql = str(sql)
            if scope is None:
                self.assertNotIn("location_ids", params)
                self.assertNotIn("ANY(", sql)
            else:
                self.assertEqual(params["location_ids"], sorted(scope))
                self.assertLess(sql.index("ANY("), sql.index("GROUP BY"))
        self.assertIn("bool_or(energy_kwh>0)", sql)


if __name__ == "__main__":
    unittest.main()
