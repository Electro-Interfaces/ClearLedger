"""WRITTEN_NOTRUN: future ROOT validation of actual DTO/OpenAPI examples.

Do not execute/collect in a source-only session. Repository conftest imports the
application; future ROOT must select an approved isolated environment first.
Tests use real schemas/DTOs; no HTTP, database fixtures or generated types.
"""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
APP_SOURCE = ROOT / "clearledger/server/app/product_api/app.py"


def _source_examples():
    result = {}
    for node in ast.walk(ast.parse(APP_SOURCE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "operation":
            name = ast.literal_eval(node.args[2])
            success = ast.literal_eval(next(k.value for k in node.keywords if k.arg == "responses"))[200]
            if name != "downloadDocumentVersion":
                result[name] = success["content"]["application/json"]["examples"]
    assert len(result) == 14
    return result


@pytest.fixture(scope="module")
def contract():
    from app.product_api import dto
    from app.product_api.app import create_product_api, curated_openapi

    def no_io(*args, **kwargs):
        raise AssertionError("DTO/schema construction must not perform runtime I/O")

    product = create_product_api(session_factory=no_io, verifier=no_io, enabled=False,
        cursor_key=b"fictional-source-metadata-test-key", upload_dir=Path("/fictional-unused"),
        issuer="https://sandbox.example.invalid", source_revision="fictional-source-examples")
    schema = curated_openapi(product)
    models = {
        "listObjects": dto.Page[dto.Object], "getObject": dto.Object,
        "getObjectMonitoring": dto.Monitoring,
        "listEquipment": dto.Page[dto.Equipment], "getEquipment": dto.Equipment,
        "listCounterparties": dto.Page[dto.Counterparty], "getCounterparty": dto.Counterparty,
        "listContracts": dto.Page[dto.Contract], "getContract": dto.Contract,
        "getContractTypeMetadata": dto.ContractTypeMetadata,
        "listContractObjects": dto.ContractObjects, "listContractDocuments": dto.ContractDocuments,
        "listDocuments": dto.Page[dto.Document], "getDocument": dto.DocumentDetail,
    }
    operations = {op["operationId"]: op for item in schema["paths"].values()
                  for method, op in item.items() if method == "get"}
    assert len(operations) == 15 and set(models) == set(operations) - {"downloadDocumentVersion"}
    return dto, schema, models, operations


def _validator(schema, node):
    # Resolve against the actual full schema, not a copied approximation.
    from jsonschema import Draft202012Validator, FormatChecker
    return Draft202012Validator({"allOf": [node], "components": schema["components"]},
                                format_checker=FormatChecker())


def test_complete_success_examples_validate_against_actual_dto_and_openapi(contract):
    _, schema, models, operations = contract
    sources = _source_examples()
    for name, model in models.items():
        media = operations[name]["responses"]["200"]["content"]["application/json"]
        assert media["examples"] == sources[name], name
        validator = _validator(schema, media["schema"])
        for example in media["examples"].values():
            value = example["value"]
            validator.validate(value)
            parsed = model.model_validate_json(json.dumps(value), strict=True)
            # This also catches omitted default/required-nullable keys at every depth.
            assert parsed.model_dump(mode="json", by_alias=True) == value, name


def test_all_field_and_alias_examples_match_actual_schema(contract):
    _, schema, _, _ = contract
    for name, node in schema["components"]["schemas"].items():
        for value in node.get("examples", []):
            _validator(schema, node).validate(value)
        for field_name, field in node.get("properties", {}).items():
            for example in field.get("examples", []):
                try:
                    _validator(schema, field).validate(example)
                except Exception as error:
                    raise AssertionError(name + "." + field_name) from error


def test_required_nullable_and_wire_type_failures_are_detected(contract):
    from jsonschema import ValidationError as SchemaError
    from pydantic import ValidationError

    _, schema, models, operations = contract
    examples = _source_examples()
    for name, field in [("getObject", "address"), ("getEquipment", "objectId"),
                        ("getContract", "validUntil"), ("getContract", "typeCode"),
                        ("getDocument", "registrationDate"), ("getContractTypeMetadata", "label")]:
        value = deepcopy(examples[name]["fictional"]["value"])
        del value[field]
        validator = _validator(schema, operations[name]["responses"]["200"]["content"]["application/json"]["schema"])
        with pytest.raises(ValidationError):
            models[name].model_validate_json(json.dumps(value), strict=True)
        with pytest.raises(SchemaError):
            validator.validate(value)
    for name, field, invalid in [("getObject", "id", 2), ("getObject", "id", "x" * 41),
                                 ("getEquipment", "powerKw", "50 kW"),
                                 ("getContract", "isClosed", "false"),
                                 ("getContract", "validUntil", "x" * 21),
                                 ("getContractTypeMetadata", "isActive", "unknown")]:
        value = deepcopy(examples[name]["fictional"]["value"])
        value[field] = invalid
        with pytest.raises(ValidationError):
            models[name].model_validate_json(json.dumps(value), strict=True)
        validator = _validator(schema, operations[name]["responses"]["200"]["content"]["application/json"]["schema"])
        with pytest.raises(SchemaError):
            validator.validate(value)


def test_opaque_object_id_other_id_and_raw_validity_remain_distinct(contract):
    from pydantic import TypeAdapter, ValidationError

    dto, _, _, _ = contract
    objects, other_ids = TypeAdapter(dto.ObjectId), TypeAdapter(dto.Id)
    for value in [" Точка Ё 1 ", "Я" * 40, "20000000-0000-4000-8000-000000000001"]:
        assert objects.validate_python(value) == value
    for value in ["", "Я" * 41, "point\x00id"]:
        with pytest.raises(ValidationError):
            objects.validate_python(value)
    for value in ["id_1:A.b-c", "30000000-0000-4000-8000-000000000001"]:
        assert other_ids.validate_python(value) == value
    with pytest.raises(ValidationError):
        other_ids.validate_python(" Точка Ё 1 ")
    value = deepcopy(_source_examples()["getContract"]["fictional"]["value"])
    for raw in [None, "до сверки", "", "2026-99-99", "x" * 20]:
        value["validUntil"] = raw
        assert dto.Contract.model_validate_json(json.dumps(value)).valid_until == raw
    for source_code in [None, "", " unknown source "]:
        value["typeCode"] = source_code
        assert dto.Contract.model_validate_json(json.dumps(value)).type_code == source_code


def test_monitoring_example_time_units_and_unknowns_are_honest(contract):
    from datetime import datetime, timedelta

    dto, schema, _, operations = contract
    value = deepcopy(_source_examples()["getObjectMonitoring"]["fictional"]["value"])
    start, end = (datetime.fromisoformat(value["window"][key]) for key in ("start", "end"))
    assert end - start == timedelta(days=value["window"]["days"])
    assert start.utcoffset() == end.utcoffset() == timedelta(hours=3)
    assert value["window"]["timeZone"] == "Europe/Moscow" and value["window"]["interval"] == "inclusive"
    assert value["totals"]["visits"] == value["totals"]["successfulVisits"] + value["totals"]["unsuccessfulVisits"]
    assert value["totals"]["energyKwh"] == 12.5
    value["status"] = "unknown"
    value["lastSeenAt"] = None
    for key in ("dataThrough", "dataLagHours", "requestedDate"):
        value["provenance"][key] = None
    value["totals"] = {"sessions": 0, "visits": 0, "successfulVisits": 0, "unsuccessfulVisits": 0, "energyKwh": 0.0}
    assert dto.Monitoring.model_validate_json(json.dumps(value), strict=True).model_dump(mode="json", by_alias=True) == value
    _validator(schema, operations["getObjectMonitoring"]["responses"]["200"]["content"]["application/json"]["schema"]).validate(value)
    assert value["provenance"]["catalogMode"] == "current"


def test_examples_form_one_fictional_read_chain_and_binary_stays_bytes(contract):
    _, _, _, operations = contract
    examples = {k: v["fictional"]["value"] for k, v in _source_examples().items()}
    for plural, singular in [("listObjects", "getObject"), ("listEquipment", "getEquipment"),
                             ("listCounterparties", "getCounterparty"), ("listContracts", "getContract")]:
        assert examples[plural]["items"] == [examples[singular]]
        assert examples[plural]["nextCursor"] is None and examples[plural]["total"] == 1
    assert examples["getEquipment"]["objectId"] == examples["getObject"]["id"]
    assert examples["getContract"]["counterpartyId"] == examples["getCounterparty"]["id"]
    assert examples["getContract"]["typeCode"] == examples["getContractTypeMetadata"]["typeCode"] == "fictional-type"
    assert examples["getContract"]["validUntil"] is None
    assert examples["listContractObjects"]["items"] == [{"objectId": examples["getObject"]["id"]}]
    assert examples["listContractDocuments"]["items"] == [{"documentId": examples["getDocument"]["id"]}]
    assert examples["listContractObjects"]["contractId"] == examples["listContractDocuments"]["contractId"] == examples["getContract"]["id"]
    detail = examples["getDocument"]
    assert detail["versionsTruncated"] is False and len(detail["versions"]) == 1
    version = detail["versions"][0]
    assert version == {"id": "70000000-0000-4000-8000-000000000001", "revision": 1,
        "role": "main", "fileName": "example.txt", "mimeType": "text/plain", "sizeBytes": len(b"Fictional file\n")}
    response = operations["downloadDocumentVersion"]["responses"]["200"]
    assert response["content"] == {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}
    assert "Fictional file +LF" in response["description"] and "15 bytes" in response["description"]
    assert {"Content-Disposition", "X-Content-Type-Options", "Cache-Control", "X-Request-Id"} <= set(response["headers"])


def test_existing_problem_content_and_headers_remain_present(contract):
    _, schema, _, operations = contract
    for operation in operations.values():
        responses = operation["responses"]
        for status in ("400", "401", "403", "404", "422", "429", "500", "503"):
            response = responses[status]
            media = response["content"]["application/problem+json"]
            assert media["schema"] == {"$ref": "#/components/schemas/Problem"}
            examples = [media["example"]] if "example" in media else [e["value"] for e in media["examples"].values()]
            for value in examples:
                _validator(schema, media["schema"]).validate(value)
            assert {"Cache-Control", "X-Request-Id"} <= set(response["headers"])
        for status in ("401", "403"):
            assert "WWW-Authenticate" in responses[status]["headers"]
        for status in ("429", "503"):
            assert "Retry-After" in responses[status]["headers"]
