"""Pure OpenAPI publisher checks; no requests, sessions, lifespan or SQL."""
from copy import deepcopy
import os

import pytest

if os.environ.get("RUN_PRODUCT_OBJECTID_SCHEMA_COMPATIBILITY") != "1":
    pytest.skip("Explicit pure schema opt-in required", allow_module_level=True)

from app.product_api import create_product_api, curated_openapi
from app.product_api.app import _canonical_object_id_paths, public_client_openapi


REF = {"$ref": "#/components/schemas/ObjectId"}
# Independent wire-contract oracle; production reads the generated component.
OBJECT_ID = {"type": "string", "minLength": 1, "maxLength": 40, "pattern": r"^[^\x00]+$"}
PATHS = {"/objects/{objectId}": "getObject", "/objects/{objectId}/monitoring": "getObjectMonitoring"}


def sample(*, inline=True):
    return {"components": {"schemas": {"ObjectId": deepcopy(OBJECT_ID),
                                       "Other": {"type": "string", "format": "uuid"}},
                            "securitySchemes": {"sentinel": {"type": "http", "scheme": "bearer"}}},
            "paths": {path: {"get": {"operationId": name, "tags": ["keep"],
                "security": [{"sentinel": ["scope"]}], "responses": {"200": {"description": "keep"}},
                "parameters": [{"name": "objectId", "in": "path", "required": True,
                    "description": "keep", "schema": {**OBJECT_ID, "title": "Objectid"} if inline else dict(REF)},
                    {"name": "objectId", "in": "query", "schema": {"type": "integer"}}]}}
                for path, name in PATHS.items()}}


def parameter(schema, path="/objects/{objectId}"):
    return schema["paths"][path]["get"]["parameters"][0]


def rejected_without_mutation(schema):
    before = deepcopy(schema)
    with pytest.raises(ValueError, match="ObjectId"):
        _canonical_object_id_paths(schema)
    assert schema == before


def test_equivalent_inline_changes_only_two_schema_nodes():
    schema = sample()
    expected = deepcopy(schema)
    for path in PATHS:
        parameter(expected, path)["schema"] = dict(REF)
    _canonical_object_id_paths(schema)
    assert schema == expected


def test_existing_references_are_unchanged_and_idempotent():
    schema = sample(inline=False)
    before = deepcopy(schema)
    identities = [parameter(schema, path)["schema"] for path in PATHS]
    _canonical_object_id_paths(schema)
    _canonical_object_id_paths(schema)
    assert schema == before
    assert all(parameter(schema, path)["schema"] is identity for path, identity in zip(PATHS, identities))


def test_inline_without_display_title_and_component_annotations():
    schema = sample()
    schema["components"]["schemas"]["ObjectId"]["title"] = "ObjectId"
    for path in PATHS:
        parameter(schema, path)["schema"].pop("title")
    _canonical_object_id_paths(schema)
    assert all(parameter(schema, path)["schema"] == REF for path in PATHS)
    assert schema["components"]["schemas"]["ObjectId"]["title"] == "ObjectId"


def test_constraint_drift_is_rejected_atomically():
    for field, value in (("minLength", 0), ("maxLength", 41), ("pattern", ".*"),
                         ("type", "integer"), ("nullable", True), ("format", "uuid"),
                         ("enum", ["one"]), ("description", "unreviewed"),
                         ("anyOf", [OBJECT_ID, {"type": "null"}])):
        schema = sample()
        parameter(schema, "/objects/{objectId}/monitoring")["schema"][field] = value
        rejected_without_mutation(schema)
    for field in OBJECT_ID:
        schema = sample()
        parameter(schema)["schema"].pop(field)
        rejected_without_mutation(schema)


def test_wrong_reference_and_reference_siblings_are_rejected():
    for value in ({"$ref": "#/components/schemas/Id"}, {**REF, "maxLength": 1},
                  {**REF, "title": "Objectid"}, None, [], "ObjectId"):
        schema = sample()
        parameter(schema)["schema"] = value
        rejected_without_mutation(schema)


def test_wrong_parameter_identity_or_required_flag_is_rejected():
    for field, value in (("name", "equipmentId"), ("in", "query"), ("required", False),
                         ("required", 1)):
        schema = sample()
        parameter(schema)[field] = value
        rejected_without_mutation(schema)
    schema = sample()
    schema["paths"]["/objects/{objectId}"]["get"]["parameters"].append(deepcopy(parameter(schema)))
    rejected_without_mutation(schema)


def test_missing_component_or_route_is_rejected():
    for value in (None, {}, REF, "string"):
        schema = sample()
        schema["components"]["schemas"]["ObjectId"] = value
        rejected_without_mutation(schema)
    schema = sample()
    del schema["paths"]["/objects/{objectId}"]
    rejected_without_mutation(schema)


def test_unreviewed_path_method_or_operation_is_rejected():
    for path in ("/objects/{objectId}/new", "/objects/{objectId}Suffix", "/unrelated/{id}"):
        schema = sample()
        schema["paths"][path] = deepcopy(schema["paths"]["/objects/{objectId}"])
        rejected_without_mutation(schema)
    schema = sample()
    schema["paths"]["/objects/{objectId}"]["post"] = deepcopy(schema["paths"]["/objects/{objectId}"]["get"])
    rejected_without_mutation(schema)
    schema = sample()
    schema["paths"]["/objects/{objectId}"]["get"]["operationId"] = "other"
    rejected_without_mutation(schema)


def test_unrelated_schema_branches_and_query_parameters_are_preserved():
    schema = sample()
    schema["paths"]["/other/{equipmentId}"] = {"get": {"operationId": "other", "parameters": [
        {"name": "equipmentId", "in": "path", "schema": {"type": "string", "format": "uuid"}},
        {"name": "objectId", "in": "query", "schema": {"type": "string", "pattern": "other"}}]}}
    schema["components"]["schemas"]["Other"]["anyOf"] = [REF, {"type": "null"}]
    expected = deepcopy(schema)
    for path in PATHS:
        parameter(expected, path)["schema"] = dict(REF)
    _canonical_object_id_paths(schema)
    assert schema == expected


def test_authoritative_component_future_keyword_must_match():
    schema = sample()
    schema["components"]["schemas"]["ObjectId"]["not"] = {"const": "reserved"}
    rejected_without_mutation(schema)
    for path in PATHS:
        parameter(schema, path)["schema"]["not"] = {"const": "reserved"}
    _canonical_object_id_paths(schema)
    assert schema["components"]["schemas"]["ObjectId"]["not"] == {"const": "reserved"}


def test_real_canonical_contract_and_codegen_identity_controls():
    schema = curated_openapi(create_product_api(enabled=False, issuer="https://synthetic.example",
        cursor_key=b"objectid-schema-synthetic-key-32!"))
    models = schema["components"]["schemas"]
    assert models["ObjectId"] == OBJECT_ID
    assert models["Id"] == {"type": "string", "minLength": 1, "maxLength": 128,
                            "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$"}
    for path, operation in PATHS.items():
        assert schema["paths"][path]["get"]["operationId"] == operation
        assert parameter(schema, path)["schema"] == REF
    for model in ("Equipment", "Document"):
        assert models[model]["properties"]["objectId"]["anyOf"] == [REF, {"type": "null"}]
    assert models["Monitoring"]["properties"]["pointId"] == REF
    for path, name in (("/equipment/{equipmentId}", "equipmentId"),
                       ("/contracts/{contractId}", "contractId"),
                       ("/documents/{docId}/versions/{versionId}/content", "versionId")):
        actual = next(p for p in schema["paths"][path]["get"]["parameters"] if p["name"] == name)["schema"]
        assert actual != REF
        assert actual == {"$ref": "#/components/schemas/Id"} or {
            k: v for k, v in actual.items() if k != "title"} == models["Id"]
    assert set(schema["components"]["securitySchemes"]) == {"ProductOAuth", "ProductServiceOAuth"}
    assert schema["servers"] == [{"url": "https://synthetic.example/api/v1"}]


def test_real_public_projection_preserves_refs_and_canonical_security():
    schema = curated_openapi(create_product_api(enabled=False, issuer="https://synthetic.example"))
    before = deepcopy(schema)
    public = public_client_openapi(schema)
    assert schema == before
    assert set(public["components"]["securitySchemes"]) == {"ProductOAuth"}
    assert public["components"]["schemas"] == schema["components"]["schemas"]
    for path in PATHS:
        assert parameter(public, path)["schema"] == REF
        assert len(schema["paths"][path]["get"]["security"]) == 2
        assert public["paths"][path]["get"]["security"] == [
            {"ProductOAuth": ["monitoring:read", "objects:read"] if path.endswith("/monitoring") else ["objects:read"]}]


def test_curated_export_rejects_generator_constraint_drift(monkeypatch):
    import app.product_api.app as publisher
    original = publisher.get_openapi

    def drifted(**kwargs):
        schema = original(**kwargs)
        parameter(schema)["schema"] = {**OBJECT_ID, "maxLength": 41}
        return schema

    monkeypatch.setattr(publisher, "get_openapi", drifted)
    with pytest.raises(ValueError, match="ObjectId path constraints differ"):
        curated_openapi(create_product_api(enabled=False, issuer="https://synthetic.example"))
