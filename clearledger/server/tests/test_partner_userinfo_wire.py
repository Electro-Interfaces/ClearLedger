"""Offline ASGI header regression; stubs do not prove JWT/persistence policy.

Run with unittest (no destructive pytest conftest). The real UserInfo router,
Bearer dependency, async verifier wrapper and user_info serializer are used;
only the synchronous verifier and pairwise lookup are controlled test seams.
"""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.database import engine, get_db
from app.routers import partner_oauth_router as routes
from app.services import partner_identity as identity


REALM = 'Bearer realm="partner-api"'
INVALID = REALM + ', error="invalid_token"'
SCOPE = REALM + ', error="insufficient_scope"'


class UserInfoWire(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # An accidental real session/network connection is a test failure.
        self.stack.enter_context(patch.object(type(engine), "connect", side_effect=AssertionError("SQL forbidden")))
        self.stack.enter_context(patch("asyncpg.connect", side_effect=AssertionError("SQL forbidden")))
        self.calls = []
        owner = self

        class Sync:
            def get(self, model, key):
                owner.calls.append(("user", model, key))
                return SimpleNamespace(id="synthetic-user", name="Synthetic name", email="user@example.invalid")

        class Async:
            async def run_sync(self, callback, *args):
                return callback(Sync(), *args)

        async def database():
            yield Async()

        def verify(sync, raw):
            owner.calls.append(("verify", raw))
            if raw == "invalid":
                raise HTTPException(401, "Invalid partner access token", headers={
                    **identity.NO_STORE, "WWW-Authenticate": 'Bearer error="invalid_token"'})
            if raw in {"http401", "http403", "http503"}:
                raise HTTPException(int(raw[4:]), "Synthetic denial", headers={"Retry-After": "17"})
            if raw == "lowercase-invalid":
                raise HTTPException(401, "Synthetic denial", headers={
                    "www-authenticate": 'Bearer error="invalid_token"', "cache-control": "public", "pragma": "cache"})
            if raw in {"problem401", "problem403", "problem503"}:
                raise identity.PartnerProblem(int(raw[7:]), "SYNTHETIC_DENIAL", "Synthetic denial")
            scopes = {"openid", "profile", "email"}
            if raw in {"noopenid", "machine"}:
                scopes = {"docs:read"}
            elif raw == "openidonly":
                scopes = {"openid"}
            return SimpleNamespace(is_machine=raw == "machine", scopes=frozenset(scopes),
                                   user_id="synthetic-user", client_id="synthetic-client")

        self.stack.enter_context(patch.object(identity, "verify_access", side_effect=verify))
        self.pairwise = self.stack.enter_context(patch.object(identity, "pairwise_subject", return_value="pairwise-subject"))
        self.app = FastAPI()
        self.app.add_exception_handler(identity.PartnerProblem, identity.problem_handler)
        # A nonstandard prefix detects any accidental route-name inference.
        self.app.include_router(routes.router, prefix="/unrelated-prefix")
        self.app.dependency_overrides[get_db] = database

        @self.app.get("/unrelated-resource")
        async def resource(verified=Depends(identity.get_verified_partner_token)):
            return {"client": verified.client_id}

        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="https://offline.example.invalid")
        self.addAsyncCleanup(self.client.aclose)
        self.url = "/unrelated-prefix/oauth2/userinfo"

    async def request(self, raw=None, *, authorization=None, url=None):
        headers = {}
        if raw is not None:
            headers["Authorization"] = "Bearer " + raw
        if authorization is not None:
            headers["Authorization"] = authorization
        return await self.client.get(url or self.url, headers=headers)

    def assert_private(self, response):
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.headers.get("pragma"), "no-cache")

    async def test_existing_status_body_and_access_decisions(self):
        cases = [(None, 401, {"detail": "Partner bearer required"}),
                 ("x" * 8193, 401, {"detail": "Invalid partner access token"}),
                 ("invalid", 401, {"detail": "Invalid partner access token"}),
                 ("noopenid", 403, {"error": "insufficient_scope"}),
                 ("machine", 403, {"error": "insufficient_scope"}),
                 ("http401", 401, {"detail": "Synthetic denial"}),
                 ("http403", 403, {"detail": "Synthetic denial"})]
        for raw, status, body in cases:
            with self.subTest(raw="oversized" if raw and len(raw) > 8192 else raw):
                response = await self.request(raw)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json(), body)
                self.assert_private(response)
        self.assertFalse(any(call[0] == "user" for call in self.calls))
        self.assertFalse(any(call[0] == "verify" and len(call[1]) > 8192 for call in self.calls))
        self.pairwise.assert_not_called()

    async def test_valid_userinfo_and_subject_only_keep_serialization(self):
        for raw, expected in (("valid", {"sub": "pairwise-subject", "name": "Synthetic name", "email": "user@example.invalid"}),
                              ("openidonly", {"sub": "pairwise-subject"})):
            with self.subTest(raw=raw):
                response = await self.request(raw)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), expected)
                self.assert_private(response)
                self.assertNotIn("www-authenticate", response.headers)
        self.assertEqual(self.pairwise.call_count, 2)

    async def test_missing_and_unsupported_authentication_challenge_without_error(self):
        for authorization in (None, "Basic c3ludGhldGljOg==", "Bearer", "Digest synthetic"):
            with self.subTest(authorization=authorization):
                response = await self.request(authorization=authorization)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": "Partner bearer required"})
                self.assertEqual(response.headers.get("www-authenticate"), REALM)
        self.assertEqual(self.calls, [])

    async def test_oversized_challenge_before_verifier(self):
        response = await self.request("x" * 8193)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("www-authenticate"), REALM)
        self.assertEqual(self.calls, [])

    async def test_precise_existing_invalid_token_survives_with_realm(self):
        response = await self.request("invalid")
        self.assertEqual(response.headers.get("www-authenticate"), INVALID)
        self.assert_private(response)

    async def test_case_insensitive_metadata_and_no_duplicate_private_headers(self):
        response = await self.request("lowercase-invalid")
        self.assertEqual(response.headers.get_list("www-authenticate"), [INVALID])
        self.assertEqual(response.headers.get_list("cache-control"), ["no-store"])
        self.assertEqual(response.headers.get_list("pragma"), ["no-cache"])

    async def test_userinfo_explicit_scope_denial_has_challenge_without_scope_hint(self):
        for raw in ("noopenid", "machine"):
            with self.subTest(raw=raw):
                response = await self.request(raw)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"error": "insufficient_scope"})
                self.assertEqual(response.headers.get("www-authenticate"), SCOPE)
                self.assert_private(response)

    async def test_generic_http_denials_do_not_invent_error_or_scope(self):
        for raw in ("http401", "http403"):
            with self.subTest(raw=raw):
                response = await self.request(raw)
                self.assertEqual(response.status_code, int(raw[4:]))
                self.assertEqual(response.json(), {"detail": "Synthetic denial"})
                self.assertEqual(response.headers.get("www-authenticate"), REALM)
                self.assertEqual(response.headers["retry-after"], "17")
                self.assert_private(response)

    async def test_partner_problem_denials_keep_problem_body(self):
        for raw in ("problem401", "problem403"):
            with self.subTest(raw=raw):
                response = await self.request(raw)
                status = int(raw[7:])
                self.assertEqual(response.status_code, status)
                body = response.json()
                self.assertTrue(body.pop("requestId"))
                self.assertEqual(body, {"type": "about:blank", "title": "Synthetic denial", "status": status,
                                        "code": "SYNTHETIC_DENIAL", "detail": "Synthetic denial"})
                self.assertEqual(response.headers["content-type"], "application/problem+json")
                self.assertEqual(response.headers.get("www-authenticate"), REALM)
                self.assert_private(response)

    async def test_common_bearer_boundary_without_userinfo_path(self):
        for raw in (None, "invalid", "http401", "http403", "problem401", "problem403"):
            with self.subTest(raw=raw):
                response = await self.request(raw, url="/unrelated-resource")
                self.assertEqual(response.status_code, 403 if raw and raw.endswith("403") else 401)
                self.assertEqual(response.headers.get("www-authenticate"), INVALID if raw == "invalid" else REALM)

    async def test_unrelated_failures_and_unmarked_problem_do_not_get_bearer(self):
        for raw in ("http503", "problem503"):
            with self.subTest(raw=raw):
                response = await self.request(raw)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("www-authenticate", response.headers)
        error = identity.PartnerProblem(401, "UNMARKED", "Synthetic unmarked")
        response = await identity.problem_handler(SimpleNamespace(state=SimpleNamespace()), error)
        self.assertNotIn("www-authenticate", response.headers)

    async def test_partner_problem_forwards_only_explicit_challenge_and_cannot_override_no_store(self):
        error = identity.PartnerProblem(401, "SYNTHETIC", "Synthetic denial")
        error.headers = {"www-authenticate": REALM, "Set-Cookie": "synthetic", "Location": "https://example.invalid",
                         "X-Debug": "synthetic", "cache-control": "public", "Pragma": "cache"}
        response = await identity.problem_handler(SimpleNamespace(state=SimpleNamespace()), error)
        self.assertEqual(response.headers.get("www-authenticate"), REALM)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.headers.get("pragma"), "no-cache")
        for header in ("set-cookie", "location", "x-debug"):
            self.assertNotIn(header, response.headers)

    async def test_exact_limit_still_reaches_existing_verifier(self):
        response = await self.request("x" * 8192)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(call[0] == "verify" and len(call[1]) == 8192 for call in self.calls))

    def test_authorization_server_error_helper_keeps_basic_behavior(self):
        response = routes.protocol_error("invalid_client", 401)
        self.assertEqual(response.headers["www-authenticate"], "Basic")
        self.assertEqual(response.body, b'{"error":"invalid_client"}')


if __name__ == "__main__":
    unittest.main()
