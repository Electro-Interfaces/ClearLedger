"""Offline ASGI/schema contract; fake verifier/projections, no M10/SQL/network proof."""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from openapi_spec_validator import OpenAPIV31SpecValidator

from app.api_contracts import policy_registry
from app.product_api import app as product, dto
from tests import test_product_http_profile as fixtures


def local_schema_gate(document):
    """Reject unresolved/external refs and unsupported formats before validation I/O."""
    def visit(node):
        if isinstance(node, dict):
            for keyword in ("$ref", "$dynamicRef"):
                if keyword not in node:
                    continue
                ref = node[keyword]
                if not isinstance(ref, str) or not ref.startswith("#/"):
                    raise ValueError("Only local references are supported")
                target = document
                for part in ref[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
            if "format" in node and node["format"] not in {*FormatChecker.checkers, "binary"}:
                raise ValueError("Unsupported schema format")
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(document)
    OpenAPIV31SpecValidator(document).validate()


def local_examples_gate(document):
    """Validate local response/header example payloads against their exact schemas."""
    local_schema_gate(document)

    def resolve(value):
        seen = set()
        while True:
            if "externalValue" in value:
                raise ValueError("External example values are not supported")
            if "$ref" not in value:
                return value
            ref = value["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                raise ValueError("Only local references are supported")
            if ref in seen:
                raise ValueError("Cyclic example/response/header reference")
            seen.add(ref)
            value = document
            for part in ref[2:].split("/"):
                value = value[part.replace("~1", "/").replace("~0", "~")]

    def examples(container):
        values = []
        if "example" in container:
            values.append(container["example"])
        for example in container.get("examples", {}).values():
            example = resolve(example)
            if "value" not in example:
                raise ValueError("Local Example Object must contain value")
            values.append(example["value"])
        if values:
            validator = Draft202012Validator(
                {**container["schema"], "components": document["components"]},
                format_checker=FormatChecker())
            for value in values:
                validator.validate(value)

    def response(contract):
        contract = resolve(contract)
        for media in contract["content"].values():
            examples(media)
        for header in contract.get("headers", {}).values():
            examples(resolve(header))

    for path in document["paths"].values():
        for operation in path.values():
            for contract in operation["responses"].values():
                response(contract)
    for header in document["components"]["headers"].values():
        examples(resolve(header))
    for contract in document["components"]["responses"].values():
        response(contract)


class ProductOpenAPIHTTPContract(unittest.IsolatedAsyncioTestCase):
    # Reuse only fixture lifecycle/helpers; do not inherit or rediscover its test cases.
    request = fixtures.ProductHTTPProfile.request
    problem = fixtures.ProductHTTPProfile.problem

    async def asyncSetUp(self):
        await fixtures.ProductHTTPProfile.asyncSetUp(self)
        self.schema = product.curated_openapi(self.app)

    def dereference(self, value):
        while "$ref" in value:
            for index, part in enumerate(value["$ref"][2:].split("/")):
                value = (self.schema if index == 0 else value)[part.replace("~1", "/").replace("~0", "~")]
        return value

    def validate_value(self, value, schema):
        Draft202012Validator({**schema, "components": self.schema["components"]},
                             format_checker=FormatChecker()).validate(value)

    def assert_response_contract(self, response, contract):
        contract = self.dereference(contract)
        media = response.headers["content-type"].split(";")[0]
        self.assertIn(media, contract["content"])
        if media != "application/octet-stream":
            self.validate_value(response.json(), contract["content"][media]["schema"])
        for name, definition in contract["headers"].items():
            header = self.dereference(definition)
            if header.get("required", False):
                self.assertIn(name, response.headers)
            if name in response.headers:
                self.validate_value(response.headers[name], header["schema"])
        self.assertNotIn("SECRET", response.text if media != "application/octet-stream" else "")
        if media == "application/problem+json":
            body = self.problem(response, response.status_code)
            example = contract["content"][media]["example"]
            self.assertEqual({key: value for key, value in body.items() if key != "requestId"},
                             {key: value for key, value in example.items() if key != "requestId"})

    def operation_path(self, entry):
        path = entry["path"]
        for name, value in (("objectId", "point"), ("equipmentId", fixtures.FILE),
                            ("counterpartyId", fixtures.FILE), ("contractId", fixtures.FILE),
                            ("docId", fixtures.DOC), ("versionId", fixtures.VERSION)):
            path = path.replace("{" + name + "}", str(value))
        return path

    @asynccontextmanager
    async def transport_projection(self):
        """Fake domain queries/ACL; actual FastAPI serialization and file streaming."""
        version = SimpleNamespace(file_id=fixtures.FILE, file_name="../Скан 1.pdf")
        source = SimpleNamespace(id=fixtures.FILE, storage_path=str(self.path))
        class DB:
            def __init__(inner): inner.answers = iter((version, source, False))
            async def scalars(inner, statement): return SimpleNamespace(all=lambda: [])
            async def scalar(inner, statement): return next(inner.answers)
        self.domain.db = DB()
        now = datetime.now(timezone.utc)
        sample = dto.Monitoring(point_id="point", status="unknown", last_seen_at=None,
            window=dto.MonitoringWindow(days=90, start=now - timedelta(days=90), end=now),
            totals=dto.MonitoringTotals(sessions=0, visits=0, successful_visits=0,
                                       unsuccessful_visits=0, energy_kwh=0),
            provenance=dto.MonitoringProvenance(as_of=now, data_through=None, data_lag_hours=None,
                requested_date=None, catalog_mode="current", snapshot_note="Synthetic transport fixture"))
        async def monitoring(query, object_id, params):
            await query.detail("objects", object_id)
            return sample
        with patch.object(product.monitoring, "detail", monitoring), \
             patch("app.services.doc_access._can_doc", AsyncMock(return_value=True)), \
             patch("app.services.doc_access.authorize_docs_file_download", AsyncMock()):
            yield

    async def test_formal_oas_local_refs_formats_and_examples(self):
        from json import dumps
        from fastapi.routing import APIRoute

        local_examples_gate(self.schema)
        routes = [route for route in self.app.routes
                  if isinstance(route, APIRoute) and route.include_in_schema]
        declarations = [deepcopy(route.responses) for route in routes]
        public = product.public_client_openapi(self.schema)
        local_examples_gate(public)
        for document in (self.schema, public):
            checked = 0
            for route in routes:
                for method in route.methods:
                    operation = document["paths"][route.path_format][method.lower()]
                    for status, response in route.responses.items():
                        status_key = str(status).upper()
                        if status_key == "DEFAULT":
                            status_key = "default"
                        produced = operation["responses"][status_key]
                        for section in ("content", "headers"):
                            for name, container in response.get(section, {}).items():
                                for keyword in ("example", "examples"):
                                    if keyword not in container:
                                        continue
                                    expected = container[keyword]
                                    actual = produced[section][name][keyword]
                                    self.assertEqual(actual, expected)
                                    self.assertEqual(dumps(actual, sort_keys=True, allow_nan=False),
                                                     dumps(expected, sort_keys=True, allow_nan=False))
                                    if isinstance(expected, (dict, list)):
                                        self.assertIsNot(actual, expected)
                                    checked += 1
            self.assertEqual(checked, 14)

        # Mutating either schema must not alter route declarations or the other view.
        canonical_value = self.schema["paths"]["/objects"]["get"]["responses"]["200"]["content"][
            "application/json"]["examples"]["fictional"]["value"]
        public_value = public["paths"]["/objects"]["get"]["responses"]["200"]["content"][
            "application/json"]["examples"]["fictional"]["value"]
        original = deepcopy(canonical_value)
        public_value["items"][0]["name"] = "Fictional public example mutation"
        self.assertEqual(canonical_value, original)
        canonical_value["items"][0]["name"] = "Fictional canonical example mutation"
        self.assertEqual([route.responses for route in routes], declarations)

    async def test_gate_rejects_external_refs_unknown_formats_and_bad_examples(self):
        for poisoned in ({"$ref": "https://untrusted.invalid/schema"},
                         {"$dynamicRef": "https://untrusted.invalid/schema"},
                         {"type": "string", "format": "uuuid"}):
            schema = deepcopy(self.schema)
            schema["components"]["schemas"]["Poison"] = poisoned
            with self.assertRaises(ValueError):
                local_schema_gate(schema)
        schema = deepcopy(self.schema)
        schema["components"]["headers"]["ProductRequestId"]["example"] = "not-a-uuid"
        header = schema["components"]["headers"]["ProductRequestId"]
        with self.assertRaisesRegex(ValidationError, "not-a-uuid"):
            self.validate_value(header["example"], header["schema"])
        response = self.schema["paths"]["/objects"]["get"]["responses"]["500"]["content"]["application/problem+json"]
        invalid = {**response["example"], "status": "500"}
        with self.assertRaises(ValidationError):
            self.validate_value(invalid, response["schema"])

        # Keep these inside the existing primary test: no extra subtest reports.
        for path, status, media_type, name, location, invalid in (
                ("/objects", "200", "application/json", "fictional", ("total",), "1"),
                ("/objects", "200", "application/json", "fictional", ("items", 0, "latitude"), "55.75"),
                ("/objects/{objectId}/monitoring", "200", "application/json", "fictional",
                 ("window", "start"), "not-a-date-time"),
                ("/objects", "429", "application/problem+json", "quotaExhausted", ("status",), "429"),
                ("/objects", "429", "application/problem+json", "injectedHTTP429", ("status",), "429")):
            schema = deepcopy(self.schema)
            media = schema["paths"][path]["get"]["responses"][status]["content"][media_type]
            target = media["examples"][name]["value"]
            for part in location[:-1]:
                target = target[part]
            target[location[-1]] = invalid
            with self.assertRaises(ValidationError) as rejected:
                local_examples_gate(schema)
            self.assertEqual(list(rejected.exception.absolute_path), list(location))

        # A chained local Example reference must be validated at the use site's
        # schema, including nested component refs.
        schema = deepcopy(self.schema)
        media = schema["paths"]["/objects"]["get"]["responses"]["200"]["content"]["application/json"]
        schema["components"]["examples"] = {
            "ResponseExample": media["examples"]["fictional"],
            "Alias": {"$ref": "#/components/examples/ResponseExample"}}
        media["examples"]["fictional"] = {"$ref": "#/components/examples/Alias"}
        local_examples_gate(schema)
        payload = schema["components"]["examples"]["ResponseExample"]["value"]
        payload["items"][0]["latitude"] = "55.75"
        with self.assertRaises(ValidationError) as rejected:
            local_examples_gate(schema)
        self.assertEqual(list(rejected.exception.absolute_path), ["items", 0, "latitude"])

        for example, message in (
                ({"$ref": "https://untrusted.invalid/example"}, "Only local references"),
                ({"externalValue": "https://untrusted.invalid/payload.json"}, "External example values"),
                ({"$ref": "#/components/examples/Blocked"}, "External example values"),
                ({"$ref": "#/components/examples/Cycle"}, "Cyclic")):
            schema = deepcopy(self.schema)
            schema["components"]["examples"] = {
                "Blocked": {"externalValue": "https://untrusted.invalid/payload.json"},
                "Cycle": {"$ref": "#/components/examples/Cycle"}}
            media = schema["paths"]["/objects"]["get"]["responses"]["200"]["content"]["application/json"]
            media["examples"]["fictional"] = example
            with self.assertRaisesRegex(ValueError, message):
                local_examples_gate(schema)

    async def test_actual_positive_12_handlers_match_response_headers_and_schemas(self):
        async with self.transport_projection():
            for entry in (e for e in policy_registry(self.app) if "GET" in e["methods"]):
                with self.subTest(operation=entry["operationId"]):
                    response = await self.request(path=self.operation_path(entry))
                    self.assertEqual(response.status_code, 200, response.text)
                    operation = self.schema["paths"][entry["path"]]["get"]
                    self.assert_response_contract(response, operation["responses"]["200"])
                    if entry["operationId"] == "downloadDocumentVersion":
                        self.assertEqual(response.content, self.bytes)
                        self.assertNotIn("content-range", response.headers)
                        self.assertNotIn("206", operation["responses"])
                        self.assertNotIn("ETag", operation["responses"]["200"]["headers"])

    async def test_actual_negative_12_handlers_match_problem_contract_and_have_no_domain_effect(self):
        for entry in (e for e in policy_registry(self.app) if "GET" in e["methods"]):
            operation = self.schema["paths"][entry["path"]]["get"]
            for status in (401, 403, 422, 503):
                with self.subTest(operation=entry["operationId"], status=status):
                    self.state.update(enabled=status != 503,
                                      scopes=frozenset() if status == 403 else fixtures.SCOPES)
                    response = await self.request(path=self.operation_path(entry) + ("?unknown=SECRET" if status == 422 else ""),
                                                  token=None if status == 401 else "valid")
                    self.assertEqual(response.status_code, status, response.text)
                    self.assert_response_contract(response, operation["responses"][str(status)])
        self.assertEqual(self.state["domain"], [])

    async def test_precise_challenges_and_optional_retry_after_match_header_contract(self):
        for token, status in (("invalid", 401), ("scope-error", 403), ("unavailable", 503)):
            response = await self.request(token=token)
            self.assertEqual(response.status_code, status)
            self.assert_response_contract(response, self.schema["paths"]["/objects"]["get"]["responses"][str(status)])
            if status == 503:
                self.assertEqual(response.headers["retry-after"], "17")
            else:
                self.assertIn("error=", response.headers["www-authenticate"])
        self.state["enabled"] = False
        response = await self.request()
        self.assert_response_contract(response, self.schema["paths"]["/objects"]["get"]["responses"]["503"])
        self.assertNotIn("retry-after", response.headers)
        self.assertEqual(self.state["domain"], [])

    async def test_actual_400_404_500_all_handlers_match_problem_contract(self):
        async with self.transport_projection():
            for status in (400, 404, 500):
                self.state["failure"] = RuntimeError("SECRET internal state") if status == 500 else HTTPException(status, "SECRET detail")
                for entry in (e for e in policy_registry(self.app) if "GET" in e["methods"]):
                    with self.subTest(operation=entry["operationId"], status=status):
                        response = await self.request(path=self.operation_path(entry))
                        self.assertEqual(response.status_code, status, response.text)
                        self.assert_response_contract(response, self.schema["paths"][entry["path"]]["get"]["responses"][str(status)])

    async def test_405_profile_and_injected_429_are_application_only_not_new_operations(self):
        profile = self.schema["x-elsy-http-profile"]
        self.assertEqual(profile["scope"], "product-child-application")
        known = profile["knownPaths"]
        self.assertEqual(known["methods"], ["GET"])
        self.assertEqual(known["methodOverrides"], {"/contracts": {"methods": ["GET", "POST"],
            "unsupportedMethodResponse": {"$ref": "#/components/responses/ProductContractsMethodNotAllowed"}}})
        for entry in (e for e in policy_registry(self.app) if "GET" in e["methods"]):
            response = await self.request("DELETE", path=self.operation_path(entry))
            self.assertEqual(response.status_code, 405, response.text)
            self.assertEqual(response.headers["allow"], "GET, POST" if entry["path"] == "/contracts" else "GET")
            contract = known["methodOverrides"].get(entry["path"], known)["unsupportedMethodResponse"]
            self.assert_response_contract(response, contract)
            if entry["path"] == "/contracts":
                self.assertEqual(self.schema["paths"][entry["path"]]["post"]["operationId"], "createContract")
            else:
                self.assertNotIn("post", self.schema["paths"][entry["path"]])
        self.assertEqual(self.state["domain"], [])
        async def rate_limited(token, db):
            raise HTTPException(429, "SECRET limiter", headers={"Retry-After": "17"})
        self.app.state.product_settings = replace(self.app.state.product_settings, verifier=rate_limited)
        response = await self.request()
        self.assertEqual(response.status_code, 429)
        self.assert_response_contract(response, profile["injectedApplicationRateLimit"]["response"])
        self.assertEqual(response.json()["code"], "internal_error")  # Existing formatter, not a new rate limiter.
        self.assertEqual(response.headers["retry-after"], "17")
        self.assertIn("outside", profile["edgeErrors"])
        self.assertNotIn("default", self.schema["paths"]["/objects"]["get"]["responses"])

    async def test_allow_path_consts_and_contracts_description_remain_strict(self):
        description = self.schema["paths"]["/contracts"]["get"]["description"]
        self.assertIn("Known-path unsupported methods use 405 method_not_allowed with "
                      "Allow: GET, POST. Cache-Control: no-store", description)
        self.assertNotIn("Allow: GET.", description)
        header = self.schema["components"]["headers"]["ProductAllow"]
        self.assertEqual(header, {
            "description": "Methods permitted on a matched application path (RFC 9110 section 15.5.6).",
            "required": True, "schema": {"type": "string", "const": "GET"}, "example": "GET"})
        alias = self.schema["components"]["headers"]["ProductContractsAllow"]
        self.assertEqual(alias["schema"], {"type": "string", "const": "GET, POST"})
        self.assertIs(alias["required"], True)
        self.assertEqual(alias["example"], "GET, POST")
        self.validate_value("GET", header["schema"])
        self.validate_value("GET, POST", alias["schema"])
        for value, schema in (("GET, POST", header["schema"]), ("GET", alias["schema"])):
            with self.assertRaises(ValidationError):
                self.validate_value(value, schema)
        for value in ("", "POST", "HEAD", "GET,POST", "GET, POST, DELETE"):
            for schema in (header["schema"], alias["schema"]):
                with self.assertRaises(ValidationError):
                    self.validate_value(value, schema)
        self.assertEqual(self.schema["components"]["responses"]["ProductContractsMethodNotAllowed"]["headers"]["Allow"],
                         {"$ref": "#/components/headers/ProductContractsAllow"})
        self.assertEqual(self.schema["components"]["responses"]["ProductMethodNotAllowed"]["headers"]["Allow"],
                         {"$ref": "#/components/headers/ProductAllow"})

    async def test_registry_policy_security_and_readiness_unchanged(self):
        registry = product.export_runtime_registry(self.app)
        self.assertEqual(registry["kind"], "policy-runtime-registry")
        self.assertEqual(registry["sourceRevision"], "offline-http-profile")
        self.assertEqual(self.schema["x-elsy-runtime-registry"], registry)
        fixtures.assert_product_manifest(self.schema, registry)
        entries = policy_registry(self.app)
        fixtures.assert_product_policy_manifest(entries)
        for entry in entries:
            for method in entry["methods"]:
                operation = self.schema["paths"][entry["path"]][method.lower()]
                self.assertEqual(operation["operationId"], entry["operationId"])
                expected = [{"ProductOAuth": sorted(entry["scopes"])}]
                if "service" in entry["principalKinds"]:
                    expected.append({"ProductServiceOAuth": sorted(entry["scopes"])})
                self.assertEqual(operation["security"], expected)
                self.assertEqual(operation["x-elsy-readiness"], "candidate")
                self.assertEqual(operation["x-elsy-owner"], entry["owner"])


if __name__ == "__main__":
    unittest.main()
