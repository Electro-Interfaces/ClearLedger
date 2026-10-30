"""Offline schema/policy and actual docs-route wiring; no SQL or real OAuth proof."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api_contracts import policy_registry
from app.database import get_db
from app.models_docs_portal import DocsPortalSession
from app.models_partner import PartnerToken, PartnerTokenFamily
from app.product_api import create_product_api, curated_openapi
from app.product_api.app import public_client_openapi
from app.routers import docs_portal_router as routes
from app.services import docs_portal as portal
from tests.test_product_openapi_http_contract import local_schema_gate

ORIGIN = "https://service-schema.example.invalid"


class ProductServiceSchema(unittest.TestCase):
    def setUp(self):
        self.app = create_product_api(enabled=False, issuer=ORIGIN)
        self.registry = policy_registry(self.app)
        self.schema = curated_openapi(self.app)

    def test_machine_alternatives_exactly_match_runtime_principal_kinds_and_and_scopes(self):
        machine = user_only = 0
        for entry in self.registry:
            for method in entry["methods"]:
                operation = self.schema["paths"][entry["path"]][method.lower()]
                scopes = sorted(entry["scopes"])
                expected = [{"ProductOAuth": scopes}]
                if "service" in entry["principalKinds"]:
                    machine += 1
                    expected.append({"ProductServiceOAuth": scopes})
                else:
                    user_only += 1
                    self.assertEqual(entry["owner"], "documents")
                self.assertEqual(operation["security"], expected)
                self.assertEqual(operation["x-access-policy"]["securityScheme"], "ProductOAuth")
        self.assertEqual((machine, user_only), (10, 4))
        self.assertEqual(policy_registry(self.app), self.registry)
        self.assertEqual(len(self.schema["tags"]), 6)
        self.assertEqual(len(self.schema["paths"]), 14)
        self.assertEqual(curated_openapi(self.app), self.schema)

    def test_machine_profile_standard_flow_and_explicit_nonstandard_form_extension(self):
        schemes = self.schema["components"]["securitySchemes"]
        self.assertEqual(set(schemes), {"ProductOAuth", "ProductServiceOAuth"})
        self.assertEqual(set(schemes["ProductOAuth"]["flows"]), {"authorizationCode"})
        service = schemes["ProductServiceOAuth"]
        flow = service["flows"]["clientCredentials"]
        self.assertEqual(flow["tokenUrl"], ORIGIN + "/api/oauth2/token")
        self.assertNotIn("authorizationUrl", flow)
        self.assertNotIn("refreshUrl", flow)
        expected = {scope for entry in self.registry if "service" in entry["principalKinds"] for scope in entry["scopes"]}
        self.assertEqual(set(flow["scopes"]), expected)
        self.assertFalse(set(flow["scopes"]) & {"openid", "offline_access", "docs:read", "documents:read", "documents.files:download"})
        form = service["x-elsy-token-request"]
        self.assertEqual(form["clientAuthentication"], "client_secret_basic")
        self.assertEqual(form["contentType"], "application/x-www-form-urlencoded")
        self.assertEqual(set(form["body"]["required"]), {"grant_type", "grant_id", "scope"})
        self.assertEqual(form["body"]["properties"]["grant_id"]["format"], "uuid")
        self.assertIn("custom", form["body"]["properties"]["grant_id"]["description"])
        self.assertFalse(form["browserExecution"])
        self.assertFalse(form["refreshTokenIssued"])
        self.assertNotIn("/api/oauth2/token", self.schema["paths"])

    def test_formal_canonical_projection_refs_and_deepcopy_no_policy_mutation(self):
        original = deepcopy(self.schema)
        projected = public_client_openapi(self.schema)
        local_schema_gate(self.schema)
        local_schema_gate(projected)
        self.assertEqual(set(projected["components"]["securitySchemes"]), {"ProductOAuth"})
        for path in projected["paths"].values():
            self.assertEqual(list(path), ["get"])
            self.assertEqual(len(path["get"]["security"]), 1)
            self.assertEqual(set(path["get"]["security"][0]), {"ProductOAuth"})
        metadata = projected["x-elsy-authentication-projection"]
        self.assertEqual(metadata["kind"], "public-code-pkce")
        self.assertEqual(metadata["canonicalContract"], portal.PREFIX + "/openapi.server.json")
        self.assertIn("clientCredentials", metadata["serverOnlyProfiles"]["ProductServiceOAuth"]["flows"])
        self.assertEqual(projected["tags"], self.schema["tags"])
        self.assertEqual(projected["x-elsy-runtime-registry"], self.schema["x-elsy-runtime-registry"])
        projected["tags"][0]["name"] = "mutated projection"
        metadata["serverOnlyProfiles"]["ProductServiceOAuth"]["flows"].clear()
        self.assertEqual(self.schema, original)

    def test_projection_rejects_new_server_only_or_ambiguous_public_profiles(self):
        for security in ([{"ProductServiceOAuth": ["objects:read"]}],
                         [{"ProductOAuth": []}, {"ProductOAuth": ["objects:read"]}]):
            candidate = deepcopy(self.schema)
            candidate["paths"]["/objects"]["get"]["security"] = security
            with self.assertRaises(ValueError):
                public_client_openapi(candidate)


class ProtectedServiceContractHTTP(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(portal.settings, "partner_docs_enabled", True))
        self.stack.enter_context(patch.object(portal.identity, "require_enabled", return_value=None))
        self.stack.enter_context(patch.object(portal.identity.settings, "partner_oauth_issuer", ORIGIN))
        self.stack.enter_context(patch.object(portal, "verification_profile", return_value="synthetic-profile"))
        self.stack.enter_context(patch.object(portal, "client_config", return_value=SimpleNamespace(id="public-docs")))
        self.stack.enter_context(patch.object(portal.identity, "live_grant",
            return_value=SimpleNamespace(client=SimpleNamespace(id="public-docs"), user=object())))
        token, family = uuid.UUID(int=1), uuid.UUID(int=2)
        self.row = SimpleNamespace(token_id=token, revoked=False, verification_profile="synthetic-profile",
                                   expires_at=portal.identity.now() + timedelta(minutes=2))
        rows = {(DocsPortalSession, portal.identity.digest("synthetic-docs-cookie")): self.row,
                (PartnerToken, token): SimpleNamespace(revoked=False, family_id=family,
                    expires_at=portal.identity.now() + timedelta(minutes=2), scope="docs:read"),
                (PartnerTokenFamily, family): SimpleNamespace(grant_id=uuid.UUID(int=3))}

        class Sync:
            def get(self, model, key, **kwargs): return rows.get((model, key))

        class Async:
            async def run_sync(self, callback): return callback(Sync())

        async def database(): yield Async()
        self.app = FastAPI()
        self.app.state.product_api = create_product_api(enabled=False, issuer=ORIGIN)
        self.app.include_router(routes.router, prefix="/api")
        self.app.dependency_overrides[get_db] = database
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url=ORIGIN)
        self.addAsyncCleanup(self.client.aclose)
        self.url = portal.PREFIX + "/openapi.server.json"

    async def test_anonymous_core_bearer_and_revoked_expired_cookie_are_denied(self):
        for headers in ({}, {"Authorization": "Bearer synthetic-core-or-product"}):
            response = await self.client.get(self.url, headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.client.cookies.set(portal.COOKIE, "synthetic-docs-cookie")
        self.row.revoked = True
        self.assertEqual((await self.client.get(self.url)).status_code, 401)
        self.row.revoked = False
        self.row.expires_at = portal.identity.now() - timedelta(seconds=1)
        self.assertEqual((await self.client.get(self.url)).status_code, 401)

    async def test_authorized_canonical_and_browser_projection_are_separate_no_store_views(self):
        self.client.cookies.set(portal.COOKIE, "synthetic-docs-cookie")
        canonical = await self.client.get(self.url)
        browser = await self.client.get(portal.PREFIX + "/openapi.json")
        for response in (canonical, browser):
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertIn("ProductServiceOAuth", canonical.json()["components"]["securitySchemes"])
        self.assertNotIn("ProductServiceOAuth", browser.json()["components"]["securitySchemes"])
        self.assertEqual((await self.client.get(self.url + "?client_secret=synthetic")).status_code, 400)
        with patch.object(portal.settings, "partner_docs_enabled", False):
            response = await self.client.get(self.url)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_portal_projection_does_not_mutate_a_cached_canonical_schema(self):
        canonical = curated_openapi(self.app.state.product_api)
        original = deepcopy(canonical)
        with patch("app.product_api.curated_openapi", return_value=canonical):
            projected = portal.product_schema(self.app)
            self.assertEqual(canonical, original)
            projected["paths"].clear()
            self.assertEqual(portal.product_schema(self.app, browser=False), original)


if __name__ == "__main__": unittest.main()
