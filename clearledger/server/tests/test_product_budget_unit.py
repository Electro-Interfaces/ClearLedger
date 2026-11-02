"""Offline wiring/configuration probes; real shared counters have a separate suite."""
from dataclasses import replace
import os
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.config import Settings
from app.product_api import budget, curated_openapi
from tests import test_product_http_profile as profile


class ProductBudgetConfiguration(unittest.IsolatedAsyncioTestCase):
    async def test_default_off_never_opens_a_store(self):
        def forbidden():
            raise AssertionError("Disabled quota opened a store")
        await budget.enforce(budget.Policy(), forbidden, None)
        self.assertFalse(Settings(_env_file=None).partner_api_budget_enabled)

    def test_strict_policy_bounds_and_environment_integer_configuration(self):
        for field, values in {"request_limit": [0, -1, True, 1.5, 1_000_001],
                "window_seconds": [0, 3601, False], "timeout_ms": [49, 5001], "enabled": [1, "true"]}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    budget.Policy(**{field: value})
        with patch.dict(os.environ, {"PARTNER_API_BUDGET_ENABLED": "true", "PARTNER_API_BUDGET_LIMIT": "7",
                "PARTNER_API_BUDGET_WINDOW_SECONDS": "17", "PARTNER_API_BUDGET_TIMEOUT_MS": "500"}):
            value = Settings(_env_file=None)
            self.assertEqual((value.partner_api_budget_enabled, value.partner_api_budget_limit,
                value.partner_api_budget_window_seconds, value.partner_api_budget_timeout_ms), (True, 7, 17, 500))
        for value in (True, 1.5, "1.0", "-1", "99999999999999999999999"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Settings(_env_file=None, partner_api_budget_limit=value)

    def test_model_fk_cascade_and_cleanup_index(self):
        table = budget.ProductAPIBudget.__table__
        self.assertEqual([c.name for c in table.primary_key], ["company_id", "installation_id", "client_id"])
        self.assertEqual({fk.ondelete for fk in table.foreign_key_constraints}, {"CASCADE"})
        self.assertEqual({tuple(c.name for c in i.columns) for i in table.indexes}, {("reset_at",)})


class ProductBudgetHTTP(profile.ProductHTTPProfile):
    async def test_exhaustion_has_problem_retry_after_and_request_id(self):
        with patch.object(budget, "enforce", AsyncMock(side_effect=budget.BudgetExceeded(17))) as store:
            response = await self.request(headers={"X-Company-Id": "untrusted", "X-Request-Id": "untrusted"})
        body = self.problem(response, 429)
        self.assertEqual(body["code"], "rate_limited")
        self.assertEqual(response.headers["retry-after"], "17")
        self.assertEqual(store.call_args.args[2], budget.Key(profile.CID, profile.Verified.installation_id,
                                                           profile.Verified.client_id))
        self.assertEqual(self.state["domain"], [])

    async def test_enabled_store_failure_is_closed_safe_503(self):
        self.app.state.product_settings = replace(self.app.state.product_settings, budget_policy=lambda: budget.Policy(True))
        # The offline identity fixture has no begin()/execute(): a real quota
        # store failure must become 503, never silently admit the request.
        response = await self.request()
        self.assertEqual(self.problem(response, 503)["code"], "api_unavailable")
        self.assertEqual(self.state["domain"], [])

    async def test_denials_happen_before_store(self):
        with patch.object(budget, "enforce", AsyncMock(side_effect=AssertionError("quota reached before ACL"))) as store:
            self.problem(await self.request(token="invalid"), 401)
            self.state["scopes"] = frozenset()
            self.problem(await self.request(), 403)
            store.assert_not_awaited()

    async def test_membership_revocation_happens_before_store(self):
        from contextlib import asynccontextmanager

        class RevokedDB:
            async def get(self, model, key):
                return None

        @asynccontextmanager
        async def sessions():
            yield RevokedDB()

        self.app.state.product_settings = replace(self.app.state.product_settings, sessions=sessions)
        with patch.object(budget, "enforce", AsyncMock()) as store:
            self.problem(await self.request(), 403)
            store.assert_not_awaited()

    async def test_authorized_422_and_404_consume_before_domain(self):
        with patch.object(budget, "enforce", AsyncMock()) as store:
            self.problem(await self.request(path="/objects?limit=0"), 422)
            self.state["failure"] = profile.HTTPException(404, "SECRET")
            self.problem(await self.request(), 404)
            self.assertEqual(store.await_count, 2)

    async def test_generic_injected429_compatibility_and_schema_conditions(self):
        async def injected(token, db):
            raise profile.HTTPException(429, "SECRET", headers={"Retry-After": "7"})
        self.app.state.product_settings = replace(self.app.state.product_settings, verifier=injected)
        response = await self.request()
        self.assertEqual(self.problem(response, 429)["code"], "internal_error")
        schema = curated_openapi(self.app)
        examples = schema["paths"]["/objects"]["get"]["responses"]["429"]["content"]["application/problem+json"]["examples"]
        self.assertEqual({item["value"]["code"] for item in examples.values()}, {"rate_limited", "internal_error"})
        self.assertFalse(schema["x-elsy-http-profile"]["productRequestBudget"]["defaultEnabled"])


if __name__ == "__main__":
    unittest.main()
