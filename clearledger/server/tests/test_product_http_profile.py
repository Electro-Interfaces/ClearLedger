"""Offline ASGI protocol probes, not M10/JWT/SQL/production conformance."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from openapi_spec_validator import OpenAPIV31SpecValidator

from app.api_contracts import policy_registry
from app.models import User, UserCompany
from app.product_api import create_product_api, curated_openapi, export_runtime_registry
from app.product_api import app as product
from app.product_api import dto

CID, USER, DOC, VERSION, FILE = (uuid.UUID(int=i) for i in range(1, 6))
SCOPES = frozenset({key + ":read" for key in product.access.RESOURCES} |
                   {"monitoring:read", "documents.files:download"})


@dataclass(frozen=True)
class Verified:
    client_id: str = "synthetic-client"
    subject: str = "synthetic-subject"
    app_id: uuid.UUID = uuid.UUID(int=10)
    installation_id: uuid.UUID = uuid.UUID(int=11)
    grant_id: uuid.UUID = uuid.UUID(int=12)
    token_id: uuid.UUID = uuid.UUID(int=13)
    company_id: uuid.UUID = CID
    user_id: uuid.UUID = USER
    is_machine: bool = False
    own_organization_id: object = None
    location_ids: object = None


class ProductHTTPProfile(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(prefix="http-profile-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bytes = b"synthetic binary\x00\xff"
        self.path = self.root / "sample.bin"
        self.path.write_bytes(self.bytes)
        self.state = dict(enabled=True, scopes=SCOPES, mode="ALL", sessions=0, domain=[], failure=None)
        state = self.state

        class IdentityDB:
            async def get(inner, model, key):
                if model is User:
                    return SimpleNamespace(id=USER, mail_only=False, is_superadmin=False)
                if model is UserCompany:
                    return SimpleNamespace(role="admin", object_scope=None, own_organization_id=None)
                raise AssertionError("Unexpected identity read in offline probe")

        @asynccontextmanager
        async def sessions():
            state["sessions"] += 1
            yield IdentityDB()  # Fixture methods only; never opens a connection.

        async def verify(raw, db):
            if raw == "invalid":
                raise HTTPException(401, "SECRET invalid-token debugging", headers={
                    "WWW-Authenticate": 'Bearer error="invalid_token"'})
            if raw == "unavailable":
                raise HTTPException(503, "SECRET upstream", headers={"Retry-After": "17",
                    "Set-Cookie": "SECRET", "Location": "https://untrusted.invalid", "X-Debug": "SECRET"})
            if raw == "scope-error":
                raise HTTPException(403, "SECRET scope", headers={
                    "WWW-Authenticate": 'Bearer error="insufficient_scope", scope="objects:read"'})
            if raw == "notfound":
                raise HTTPException(404, "SECRET lookup", headers={"Allow": "POST",
                    "WWW-Authenticate": "Basic", "Retry-After": "17", "Set-Cookie": "SECRET"})
            token = Verified()
            # Mutable control belongs to this server verifier fixture, never a request body.
            return SimpleNamespace(**token.__dict__, scopes=state["scopes"],
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                resource_scopes=MappingProxyType({kind: MappingProxyType({"mode": state["mode"], "ids": frozenset()})
                                                  for kind in product.access.RESOURCES}))

        self.app = create_product_api(session_factory=sessions, verifier=verify,
            enabled=lambda: state["enabled"], upload_dir=self.root,
            issuer="https://synthetic.example", source_revision="offline-http-profile")

        class Domain:
            facts = SimpleNamespace(company_id=CID, user=SimpleNamespace(id=USER))

            async def listing(inner, resource, params):
                state["domain"].append(("list", resource))
                if state["failure"]:
                    raise state["failure"]
                return dict(items=[], next_cursor=None, total=0)

            async def detail(inner, resource, identifier):
                state["domain"].append(("detail", resource))
                if state["failure"]:
                    raise state["failure"]
                return SimpleNamespace(id=DOC if resource == "documents" else "point")

            async def project(inner, resource, rows):
                values = {
                    "objects": dict(id="point", code="P", name="Synthetic", type="ev_charging", status="active",
                                    address=None, latitude=None, longitude=None),
                    "equipment": dict(id=str(FILE), vendor=None, model=None, serial_number=None, power_kw=None,
                                      state="in_operation", object_id=None),
                    "counterparties": dict(id=str(FILE), name="Synthetic", inn=None, kpp=None),
                    "contracts": dict(id=str(FILE), number="S", date=None, title=None, is_closed=False,
                                      scope_type="company", counterparty_id=None),
                    "documents": dict(id=str(DOC), title="Synthetic", status="draft", registration_number=None,
                                      registration_date=None, current_revision=1, object_id=None, counterparty_id=None),
                }
                return [getattr(dto, {"objects": "Object", "equipment": "Equipment", "counterparties": "Counterparty",
                                     "contracts": "Contract", "documents": "Document"}[resource])(**values[resource])]

        self.domain = Domain()

        async def domain_query():
            return self.domain
        self.app.dependency_overrides[product.query_dependency] = domain_query
        self.client = AsyncClient(transport=ASGITransport(app=self.app, raise_app_exceptions=False),
                                  base_url="https://synthetic.example")
        self.addAsyncCleanup(self.client.aclose)

    async def request(self, method="GET", path="/objects", token="valid", **kwargs):
        headers = kwargs.pop("headers", {})
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        return await self.client.request(method, path, headers=headers, **kwargs)

    def problem(self, response, status):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.headers["content-type"], "application/problem+json")
        body = response.json()
        self.assertEqual(body["status"], status)
        self.assertEqual(body["type"], "about:blank")
        self.assertEqual(body["requestId"], response.headers["x-request-id"])
        uuid.UUID(body["requestId"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("SECRET", response.text)
        return body

    async def test_missing_credentials_challenge_has_params_without_invented_error(self):
        response = await self.request(token=None)
        self.problem(response, 401)
        self.assertEqual(response.headers["www-authenticate"], 'Bearer realm="product-api"')
        self.assertNotIn("error=", response.headers["www-authenticate"])
        self.assertEqual(self.state["sessions"], 0)

    async def test_invalid_token_preserves_canonical_challenge(self):
        response = await self.request(token="invalid")
        self.problem(response, 401)
        self.assertEqual(response.headers["www-authenticate"], 'Bearer error="invalid_token"')
        self.assertEqual(self.state["domain"], [])

    async def test_405_preserves_framework_allow_without_executing_handler(self):
        response = await self.request("POST")
        self.problem(response, 405)
        self.assertEqual(set(response.headers["allow"].replace(" ", "").split(",")), {"GET"})
        self.assertEqual(self.state["sessions"], 0)
        self.assertEqual(self.state["domain"], [])

    async def test_forbidden_scope_has_challenge_but_no_guessed_scope_error(self):
        self.state["scopes"] = frozenset()
        response = await self.request()
        self.problem(response, 403)
        self.assertEqual(response.headers["www-authenticate"], 'Bearer realm="product-api"')
        self.assertEqual(self.state["domain"], [])

    async def test_500_has_safe_correlated_headers_outside_user_middleware(self):
        self.state["failure"] = RuntimeError("SECRET stack/path/token")
        response = await self.request(headers={"X-Request-Id": "attacker-chosen"})
        body = self.problem(response, 500)
        self.assertEqual(body["code"], "internal_error")
        self.assertNotEqual(body["requestId"], "attacker-chosen")

    async def test_domain_400_keeps_status_and_safe_problem_without_debug_input(self):
        self.state["failure"] = HTTPException(400, "SECRET cursor/filter debugging")
        response = await self.request()
        body = self.problem(response, 400)
        self.assertEqual(body["code"], "invalid_cursor")
        self.assertNotIn("www-authenticate", response.headers)

    async def test_retry_after_is_preserved_but_unrelated_headers_are_not(self):
        response = await self.request(token="unavailable")
        self.problem(response, 503)
        self.assertEqual(response.headers["retry-after"], "17")
        for name in ("set-cookie", "location", "x-debug"):
            self.assertNotIn(name, response.headers)

    async def test_protocol_headers_are_status_specific_and_precise_scope_error_survives(self):
        response = await self.request(token="notfound")
        self.problem(response, 404)
        for name in ("allow", "www-authenticate", "retry-after", "set-cookie"):
            self.assertNotIn(name, response.headers)
        response = await self.request(token="scope-error")
        self.problem(response, 403)
        self.assertEqual(response.headers["www-authenticate"],
                         'Bearer error="insufficient_scope", scope="objects:read"')
        self.assertEqual(self.state["domain"], [])

    async def test_404_validation_defaultoff_and_query_token_controls(self):
        self.problem(await self.request(path="/not-an-operation"), 404)
        for path in ("/objects?pageSize=0", "/objects?pageSize=SECRET", "/objects?unknown=SECRET",
                     "/objects?dateFrom=null", "/objects/" + "x" * 41):
            self.problem(await self.request(path=path), 422)
        self.problem(await self.request(path="/objects?access_token=SECRET"), 401)
        self.problem(await self.request(path="/objects?token=SECRET"), 401)
        self.assertEqual(self.state["domain"], [])
        self.state["enabled"] = False
        prior = self.state["sessions"]
        self.problem(await self.request(token="invalid"), 503)
        self.assertEqual(self.state["sessions"], prior)

    async def test_curated_handlers_and_and_scopes_match_runtime_denials(self):
        schema = curated_openapi(self.app)
        OpenAPIV31SpecValidator(schema).validate()
        entries = policy_registry(self.app)
        registry = export_runtime_registry(self.app)
        self.assertEqual(len(entries), 12)
        self.assertEqual(len({v["operationId"] for v in registry["operations"]}), 12)
        for entry in entries:
            with self.subTest(path=entry["path"]):
                operation = schema["paths"][entry["path"]]["get"]
                scopes = set(entry["scopes"])
                self.assertEqual(operation["security"], [{"ProductOAuth": sorted(scopes)}])
                self.assertEqual(operation["operationId"], entry["operationId"])
                for status in ("400", "401", "403", "404", "422", "503"):
                    self.assertEqual(set(operation["responses"][status]["content"]), {"application/problem+json"})
                path = entry["path"].replace("{objectId}", "point").replace("{equipmentId}", str(FILE))
                for name, value in (("counterpartyId", FILE), ("contractId", FILE), ("docId", DOC), ("versionId", VERSION)):
                    path = path.replace("{" + name + "}", str(value))
                for missing in scopes:
                    self.state["scopes"] = SCOPES - {missing}
                    self.problem(await self.request(path=path), 403)
        self.assertEqual(self.state["domain"], [])

    async def test_all_json_handlers_have_typed_success_media_and_correlated_headers(self):
        # Only transport/projection fixtures: no SQL or monitoring aggregation claim.
        class DocumentDB:
            async def scalars(inner, statement):
                return SimpleNamespace(all=lambda: [])
        self.domain.db = DocumentDB()
        now = datetime.now(timezone.utc)
        sample = dto.Monitoring(point_id="point", status="unknown", last_seen_at=None,
            window=dto.MonitoringWindow(days=90, start=now - timedelta(days=90), end=now),
            totals=dto.MonitoringTotals(sessions=0, visits=0, successful_visits=0,
                                       unsuccessful_visits=0, energy_kwh=0),
            provenance=dto.MonitoringProvenance(as_of=now, data_through=None, data_lag_hours=None,
                requested_date=None, catalog_mode="current", snapshot_note="Synthetic transport fixture"))
        schema = curated_openapi(self.app)
        checked = []
        with patch.object(product.monitoring, "detail", AsyncMock(return_value=sample)):
            for entry in policy_registry(self.app):
                if entry["operationId"] == "downloadDocumentVersion":
                    continue
                path = entry["path"].replace("{objectId}", "point").replace("{equipmentId}", str(FILE))
                for name, value in (("counterpartyId", FILE), ("contractId", FILE), ("docId", DOC)):
                    path = path.replace("{" + name + "}", str(value))
                with self.subTest(operation=entry["operationId"]):
                    response = await self.request(path=path)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.headers["content-type"], "application/json")
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    uuid.UUID(response.headers["x-request-id"])
                    self.assertNotIn("www-authenticate", response.headers)
                    self.assertEqual(set(schema["paths"][entry["path"]]["get"]["responses"]["200"]["content"]),
                                     {"application/json"})
                    checked.append(entry["operationId"])
        self.assertEqual(len(checked), 11)

    async def test_binary_representation_and_range_ignore_are_explicit(self):
        version = SimpleNamespace(file_id=FILE, file_name="../Скан 1.pdf")
        source = SimpleNamespace(id=FILE, storage_path=str(self.path))
        class BinaryDB:
            def __init__(inner): inner.answers = iter((version, source, False))
            async def scalar(inner, statement): return next(inner.answers)
        path = f"/documents/{DOC}/versions/{VERSION}/content"
        schema = curated_openapi(self.app)["paths"]["/documents/{docId}/versions/{versionId}/content"]["get"]
        self.assertEqual(set(schema["responses"]["200"]["content"]), {"application/octet-stream"})
        with patch("app.services.doc_access._can_doc", AsyncMock(return_value=True)), \
             patch("app.services.doc_access.authorize_docs_file_download", AsyncMock()):
            for headers in ({}, {"Range": "bytes=0-2"}, {"Accept": "application/json"}):
                with self.subTest(headers=headers):
                    self.domain.db = BinaryDB()
                    response = await self.request(path=path, headers=headers)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.content, self.bytes)
                    self.assertEqual(response.headers["content-type"], "application/octet-stream")
                    self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertIn("filename*=UTF-8''%D0%A1%D0%BA%D0%B0%D0%BD%201.pdf", response.headers["content-disposition"])
                    self.assertNotIn("../", response.headers["content-disposition"])
                    self.assertNotIn("content-range", response.headers)


if __name__ == "__main__":
    unittest.main()
