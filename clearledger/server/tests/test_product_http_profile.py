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


# Current child application: retain the original GET subset as an exact oracle.
EXPECTED_GET_MANIFEST = frozenset({
    ("GET", "/objects", "listObjects"),
    ("GET", "/objects/{objectId}", "getObject"),
    ("GET", "/objects/{objectId}/monitoring", "getObjectMonitoring"),
    ("GET", "/equipment", "listEquipment"),
    ("GET", "/equipment/{equipmentId}", "getEquipment"),
    ("GET", "/counterparties", "listCounterparties"),
    ("GET", "/counterparties/{counterpartyId}", "getCounterparty"),
    ("GET", "/contracts", "listContracts"),
    ("GET", "/contract-types", "getContractTypeMetadata"),
    ("GET", "/contracts/{contractId}", "getContract"),
    ("GET", "/contracts/{contractId}/objects", "listContractObjects"),
    ("GET", "/contracts/{contractId}/documents", "listContractDocuments"),
    ("GET", "/documents", "listDocuments"),
    ("GET", "/documents/{docId}", "getDocument"),
    ("GET", "/documents/{docId}/versions/{versionId}/content", "downloadDocumentVersion"),
})
OPTIONS_MANIFEST = frozenset({("GET", "/contracts/create-options", "getContractCreateOptions")})
NETWORK_STATE_MANIFEST = frozenset({("GET", "/monitoring/network-state", "getNetworkState")})
EXPECTED_PRODUCT_MANIFEST = EXPECTED_GET_MANIFEST | NETWORK_STATE_MANIFEST | OPTIONS_MANIFEST | {("POST", "/contracts", "createContract")}
USER_ONLY_GET_IDS = frozenset({"listContractDocuments", "listDocuments", "getDocument", "downloadDocumentVersion"})


def assert_product_manifest(schema, registry):
    """Exact method/path/id oracle; no HTTP or fixture execution."""
    operations = registry["operations"]
    assert len(operations) == 18
    assert {(e["method"], e["path"], e["operationId"]) for e in operations} == EXPECTED_PRODUCT_MANIFEST
    assert len({e["operationId"] for e in operations}) == 18
    assert {(e["method"], e["path"], e["operationId"]) for e in operations
            if e["method"] == "GET"} == EXPECTED_GET_MANIFEST | NETWORK_STATE_MANIFEST | OPTIONS_MANIFEST
    documented = [(method.upper(), path, op["operationId"])
                  for path, item in schema["paths"].items() for method, op in item.items()]
    assert len(documented) == 18 and set(documented) == EXPECTED_PRODUCT_MANIFEST
    assert len(schema["paths"]) == 17


def assert_product_policy_manifest(entries):
    """Preserve the original 15 READs, plus network-state and CREATE/options."""
    assert len(entries) == 18
    assert {(method, e["path"], e["operationId"]) for e in entries
            for method in e["methods"]} == EXPECTED_PRODUCT_MANIFEST
    reads = [e for e in entries if e["operationId"] in {item[2] for item in EXPECTED_GET_MANIFEST}]
    assert len(reads) == 15 and all(e["methods"] == ["GET"] for e in reads)
    assert {(method, e["path"], e["operationId"]) for e in reads
            for method in e["methods"]} == EXPECTED_GET_MANIFEST
    assert sum("service" in e["principalKinds"] for e in reads) == 11
    assert sum("service" not in e["principalKinds"] for e in reads) == 4
    assert {e["operationId"] for e in reads if e["principalKinds"] == ["partner"]} == USER_ONLY_GET_IDS
    assert all(e["principalKinds"] == (["partner"] if e["operationId"] in USER_ONLY_GET_IDS
                                      else ["partner", "service"]) for e in reads)
    network, = [e for e in entries if e["operationId"] == "getNetworkState"]
    assert (network["methods"], network["path"]) == (["GET"], "/monitoring/network-state")
    assert network["principalKinds"] == ["partner", "service"]
    assert network["scopes"] == ["monitoring:read", "objects:read"]
    assert network["owner"] == network["resourceType"] == "objects" and network["action"] == "read"
    assert network["tenantRequired"] is True and network["securityScheme"] == "ProductOAuth"
    writes = [e for e in entries if "POST" in e["methods"]]
    assert len(writes) == 1
    create = writes[0]
    assert (create["methods"], create["path"], create["operationId"]) == (["POST"], "/contracts", "createContract")
    assert create["principalKinds"] == ["partner", "service"]
    assert create["scopes"] == ["contracts:create"]
    assert create["owner"] == create["resourceType"] == "contracts" and create["action"] == "create"
    assert create["tenantRequired"] is True and create["securityScheme"] == "ProductOAuth"
    assert create["resourceStage"] == "create-newborn" and create["fields"] == []
    assert "databaseAuthorityKinds" not in create

    options, = [e for e in entries if e["operationId"] == "getContractCreateOptions"]
    assert (options["methods"], options["path"]) == (["GET"], "/contracts/create-options")
    assert options["principalKinds"] == ["partner", "service"]
    assert options["scopes"] == ["contracts:create"] and options["resourceStage"] == "create-options"
    assert options["resourceType"] == options["owner"] == "contracts" and options["action"] == "create-options"
    assert options["tenantRequired"] is True and options["fields"] == []
    assert options["securityScheme"] == "ProductOAuth" and "databaseAuthorityKinds" not in options


def read_entries(entries):
    """The original fixed 15 READ handlers, never fake SQL options success."""
    reads = [e for e in entries if ("GET", e["path"], e["operationId"]) in EXPECTED_GET_MANIFEST]
    assert len(reads) == 15
    assert {("GET", e["path"], e["operationId"]) for e in reads} == EXPECTED_GET_MANIFEST
    return reads


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

            async def contract_objects(inner, identifier, params):
                state["domain"].append(("contract-objects", identifier))
                if state["failure"]:
                    raise state["failure"]
                return dict(contract_id=identifier, scope_type="locations", items=[], total=0, next_cursor=None)

            async def contract_documents(inner, identifier, params):
                state["domain"].append(("contract-documents", identifier))
                if state["failure"]:
                    raise state["failure"]
                return dict(contract_id=identifier, items=[], total=0, next_cursor=None)

            async def contract_type_metadata(inner, params):
                state["domain"].append(("contract-type-metadata", params.typeCode))
                if state["failure"]:
                    raise state["failure"]
                return dto.ContractTypeMetadata(type_code=params.typeCode, label=None, gk_basis=None,
                                                direction=None, is_active=None)

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
                    "contracts": dict(type_code=None, valid_until=None, id=str(FILE), number="S", date=None, title=None, is_closed=False,
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
        if path == "/contract-types" and "params" not in kwargs:
            kwargs["params"] = {"typeCode": "synthetic"}
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
        response = await self.request("DELETE")
        self.problem(response, 405)
        self.assertEqual(response.headers["allow"], "GET")
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
        assert_product_manifest(schema, registry)
        assert_product_policy_manifest(entries)
        for entry in read_entries(entries):
            with self.subTest(path=entry["path"]):
                operation = schema["paths"][entry["path"]]["get"]
                scopes = set(entry["scopes"])
                expected = [{"ProductOAuth": sorted(scopes)}]
                if "service" in operation["x-access-policy"]["principalKinds"]:
                    expected.append({"ProductServiceOAuth": sorted(scopes)})
                self.assertEqual(operation["security"], expected)
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

    def test_network_state_metadata_is_separate_from_legacy_read_transport(self):
        # Source/schema expectation only; actual owner/PG admission has its own suite.
        schema = curated_openapi(self.app)
        operation = schema["paths"]["/monitoring/network-state"]["get"]
        self.assertEqual(operation["operationId"], "getNetworkState")
        self.assertEqual(operation["security"], [
            {"ProductOAuth": ["monitoring:read", "objects:read"]},
            {"ProductServiceOAuth": ["monitoring:read", "objects:read"]}])
        self.assertEqual({p["name"] for p in operation["parameters"] if p["in"] == "query"},
                         {"pageSize", "cursor", "asOf", "region", "onlyProblems"})
        self.assertEqual(operation["responses"]["200"]["content"]["application/json"]["schema"],
                         {"$ref": "#/components/schemas/NetworkState"})
        self.assertEqual(set(operation["responses"]),
                         {"200", "400", "401", "403", "404", "405", "422", "429", "500", "503"})
        components = schema["components"]["schemas"]
        self.assertEqual(set(components["NetworkStateItem"]["required"]),
                         {"objectId", "status", "lastChargeAt", "silentDays", "mismatch"})
        self.assertEqual(set(components["NetworkStateContext"]["required"]),
                         {"asOf", "dataThrough", "dataLagHours", "requestedDate", "catalogMode",
                          "boundaryScope", "availability"})
        self.assertEqual(set(components["NetworkStateStatusCounts"]["required"]),
                         {"working", "no_link", "disabled", "decommissioned", "on_repair",
                          "maintenance", "not_working", "unknown"})
        self.assertEqual(self.state["sessions"], 0)
        self.assertEqual(self.state["domain"], [])

    async def test_create_contract_metadata_is_separate_from_get_transport_fixtures(self):
        # Metadata only: the legacy read verifier has no CREATE preflight/authority.
        schema = curated_openapi(self.app)
        assert_product_manifest(schema, export_runtime_registry(self.app))
        assert_product_policy_manifest(policy_registry(self.app))
        operation = schema["paths"]["/contracts"]["post"]
        self.assertEqual(operation["operationId"], "createContract")
        self.assertEqual(operation["security"], [{"ProductOAuth": ["contracts:create"]},
                                                 {"ProductServiceOAuth": ["contracts:create"]}])
        self.assertEqual(operation["x-access-policy"]["resourceStage"], "create-newborn")
        self.assertEqual(operation["x-elsy-resource-policy"], "contracts:create")
        self.assertEqual(operation["x-elsy-readiness"], "candidate")
        self.assertEqual(operation["requestBody"], {"required": True, "content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/ContractCreateBody"}}}})
        self.assertEqual(set(operation["responses"]),
                         {"200", "201", "401", "403", "405", "409", "413", "415", "422", "429", "500", "503"})
        self.assertEqual(operation["responses"]["405"],
                         {"$ref": "#/components/responses/ProductContractsMethodNotAllowed"})
        self.assertEqual(schema["components"]["responses"]["ProductContractsMethodNotAllowed"]["headers"]["Allow"],
                         {"$ref": "#/components/headers/ProductContractsAllow"})
        allow = schema["components"]["headers"]["ProductContractsAllow"]
        self.assertIs(allow["required"], True)
        self.assertEqual(allow["schema"], {"type": "string", "const": "GET, POST"})
        self.assertEqual(allow["example"], "GET, POST")
        self.assertEqual(self.state["sessions"], 0)
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
            for entry in read_entries(policy_registry(self.app)):
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
        self.assertEqual(len(checked), 14)

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
