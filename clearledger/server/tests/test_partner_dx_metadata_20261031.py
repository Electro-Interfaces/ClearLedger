"""WRITTEN_NOTRUN: future ROOT source/policy regression tests.

Do not collect/run under the source-only task. The repository conftest imports
the application and can prepare/drop test schemas; execution needs a separately
approved isolated ROOT test environment. No database fixtures are requested here.
"""
import ast
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "clearledger/scripts/verify_partner_dx_metadata_20261031.py"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("partner_dx_source_checker_20261031", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_complete_normalized_wire_route_policy_and_handler_ast(checker):
    dto_source = (ROOT / checker.DTO).read_text(encoding="utf-8")
    app_source = (ROOT / checker.APP).read_text(encoding="utf-8")
    dto_proof = checker.normalize_dto(checker.base_source(checker.DTO), dto_source)
    app_proof = checker.normalize_app(checker.base_source(checker.APP), app_source)
    assert dto_proof["allOtherAstIdentical"] and dto_proof["requiredAndDefaultPreserved"]
    assert app_proof["allOtherAstIdentical"]
    assert {o["operationId"] for o in app_proof["operations"]} == set(checker.EXPECTED_OPERATIONS)
    assert len(app_proof["operations"]) == 15
    for operation in app_proof["operations"]:
        expected = "PARTNER" if operation["resource"] == "documents" else "PARTNER|SERVICE"
        assert operation["principalRule"] == expected
        assert operation["routeAndPolicyAstPreserved"] and operation["handlerAstPreserved"]


def _change_field(source, class_name, field_name, change):
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    field = next(n for n in cls.body if isinstance(n, ast.AnnAssign) and n.target.id == field_name)
    change(field)
    return ast.unparse(tree)


@pytest.mark.parametrize("class_name,field_name,mutation", [
    ("Object", "address", "default"),
    ("Object", "id", "annotation"),
    ("Contract", "valid_until", "max_length"),
    ("ListQuery", "pageSize", "default"),
    ("ContractTypeMetadata", "label", "nullable"),
    ("Version", "file_name", "alias"),
])
def test_normalizer_rejects_wire_drift(checker, class_name, field_name, mutation):
    source = (ROOT / checker.DTO).read_text(encoding="utf-8")

    def mutate(field):
        if mutation == "annotation":
            field.annotation = ast.Name(id="Id", ctx=ast.Load())
        elif mutation == "nullable":
            field.annotation = ast.Name(id="str", ctx=ast.Load())
        elif mutation == "max_length":
            next(k for k in field.value.keywords if k.arg == "max_length").value = ast.Constant(21)
        elif mutation == "alias":
            field.value.keywords.append(ast.keyword(arg="alias", value=ast.Constant("filename")))
        elif field_name == "pageSize":
            next(k for k in field.value.keywords if k.arg == "default").value = ast.Constant(51)
        else:
            # Required nullable is not equivalent to optional/default None.
            field.value.keywords.append(ast.keyword(arg="default", value=ast.Constant(None)))

    changed = _change_field(source, class_name, field_name, mutate)
    with pytest.raises(AssertionError):
        checker.normalize_dto(checker.base_source(checker.DTO), changed)


@pytest.mark.parametrize("mutation", [
    "binary_schema", "binary_header", "extra_status", "response_model",
    "extra_scope", "extra_kwarg", "handler", "principal", "problem_profile", "helper",
])
def test_normalizer_never_hides_response_kwargs_or_runtime_changes(checker, mutation):
    tree = ast.parse((ROOT / checker.APP).read_text(encoding="utf-8"))
    ops = checker.operations(tree)
    call, handler = ops["downloadDocumentVersion"]
    response_kw = checker.keyword(call, "responses")
    responses = ast.literal_eval(response_kw.value)
    if mutation == "binary_schema":
        responses[200]["content"]["application/octet-stream"]["schema"]["format"] = "byte"
    elif mutation == "binary_header":
        responses[200]["headers"] = {"X-Unreviewed": {"schema": {"type": "string"}}}
    elif mutation == "extra_status":
        responses[201] = {"description": "Unreviewed status must not disappear"}
    elif mutation == "response_model":
        call.keywords.append(ast.keyword(arg="response_model", value=ast.parse("dto.Version", mode="eval").body))
    elif mutation == "extra_scope":
        call.keywords.append(ast.keyword(arg="extra_scopes", value=ast.parse("{'other:read'}", mode="eval").body))
    elif mutation == "extra_kwarg":
        call.keywords.append(ast.keyword(arg="include_in_schema", value=ast.Constant(False)))
    elif mutation == "handler":
        handler.body = [ast.Return(value=ast.Constant(None))]
    elif mutation == "principal":
        policy = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_policy")
        branch = next(n for n in ast.walk(policy) if isinstance(n, ast.IfExp))
        branch.body = deepcopy(branch.orelse)
    elif mutation == "problem_profile":
        profile = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_describe_http_responses")
        profile.body = [ast.Pass()]
    elif mutation == "helper":
        factory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_product_api")
        helper = next(n for n in factory.body if isinstance(n, ast.FunctionDef) and n.name == "operation")
        helper.body = [ast.Return(value=ast.Constant(None))]
    response_kw.value = ast.parse(repr(responses), mode="eval").body
    with pytest.raises(AssertionError):
        checker.normalize_app(checker.base_source(checker.APP), ast.unparse(tree))


def test_protected_helpers_and_guards_are_byte_identical_to_immutable_base(checker):
    paths = checker.git("ls-files", "clearledger/server/app/product_api", "clearledger/server/app/api_contracts").decode().splitlines()
    assert paths
    for path in paths:
        if path not in {checker.DTO, checker.APP}:
            assert (ROOT / path).read_bytes() == checker.git("show", checker.BASE + ":" + path), path


def test_actual_registered_principals_scopes_methods_and_tenant_policy(checker):
    # Future execution only: inspect real factory/registry, never serve a request.
    from app.api_contracts import PrincipalKind, policy_registry
    from app.product_api.app import create_product_api

    def no_io(*args, **kwargs):
        raise AssertionError("DX schema tests must not use sessions or credentials")

    product = create_product_api(session_factory=no_io, verifier=no_io, enabled=False,
        cursor_key=b"fictional-source-metadata-test-key", upload_dir=Path("/fictional-unused"),
        issuer="https://sandbox.example.invalid", source_revision=checker.BASE)
    entries = {e["operationId"]: e for e in policy_registry(product)}
    assert set(entries) == set(checker.EXPECTED_OPERATIONS)
    for name, (path, resource) in checker.EXPECTED_OPERATIONS.items():
        entry = entries[name]
        assert entry["methods"] == ["GET"] and entry["path"] == path
        assert entry["owner"] == entry["resourceType"] == resource
        expected_kinds = {PrincipalKind.PARTNER.value}
        if resource != "documents":
            expected_kinds.add(PrincipalKind.SERVICE.value)
        assert set(entry["principalKinds"]) == expected_kinds
        scopes = {resource + ":read"}
        if name == "getObjectMonitoring":
            scopes.add("monitoring:read")
        if name == "listContractObjects":
            scopes.add("objects:read")
        if name == "listContractDocuments":
            scopes.add("contracts:read")
        if name == "downloadDocumentVersion":
            scopes.add("documents.files:download")
        assert set(entry["scopes"]) == scopes
        assert entry["action"] == ("download" if name == "downloadDocumentVersion" else "read")
        assert entry["tenantRequired"] is True and entry["fields"] == []
        assert entry["securityScheme"] == "ProductOAuth"
