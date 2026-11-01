"""SOURCE AUTHOR DEFINITIONS / NOTRUN, including imports and collection.

Pure DTO/encoding contracts and source boundaries. No positive SQL/auth fakes;
real auth and database behavior belongs to the separate ROOT-admitted PG suite.
"""
import ast
from copy import copy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api_contracts.context import (AccessContext, CREATE_OPTIONS_KEY, CreateOptionsPreflight,
    Principal, PrincipalKind, ResourcePermission, ResourceScope)
from app.api_contracts.routing import ResourceStage, RoutePolicy, authorize
from app.product_api import budget, contract_create_options as options, dto

KEY = b"fictional-existing-cursor-key-32-bytes"
BINDING = ("GET", "/api/v1/contracts/create-options", "getContractCreateOptions",
    UUID("10000000-0000-4000-8000-000000000001"), frozenset({"  Аа  ", "  аа  "}), None, frozenset())
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("resource", options.RESOURCES)
@pytest.mark.parametrize("size", [1, 50, 100])
def test_options_query_and_required_null_wire(resource, size):
    query = dto.ContractCreateOptionsQuery(resource=resource, pageSize=size)
    assert query.pageSize == size and query.cursor is None
    value = dto.ContractCreateOptions(resource=resource, items=[], selection_version="opaque", next_cursor=None)
    assert value.model_dump(by_alias=True) == dict(resource=resource, items=[], selectionVersion="opaque", nextCursor=None)
    with pytest.raises(ValidationError):
        dto.ContractCreateOptions(resource=resource, items=[], selection_version="opaque")


@pytest.mark.parametrize("changes", [dict(resource="contracts"), dict(pageSize=0), dict(pageSize=101),
    dict(cursor="x"*2049), dict(cursor=""), dict(profileId="private"), dict(q="search")])
def test_query_bounds_and_closed_shape(changes):
    with pytest.raises(ValidationError):
        dto.ContractCreateOptionsQuery(**(dict(resource="type") | changes))


@pytest.mark.parametrize("value", [" ТИП ", "  ОбЪект  ", "é", "e\u0301", "a", "A"])
def test_literal_utf8_not_normalized(value):
    item = dto.ContractCreateOption(value=value)
    assert item.value.encode() == value.encode()
    assert options._pack(value) != options._pack(value + " ")
    cursor = options.encode_cursor(KEY, BINDING, "location", 1, value, 1300)
    assert options.decode_cursor(cursor, KEY, BINDING, "location", 1, 1000) == (value, 1300)
    payload = options._unb64(cursor.split(".")[0])
    assert payload[:3] == bytes((2, 2, 1))
    assert int.from_bytes(payload[11:13], "big") == len(value.encode("utf-8"))
    assert payload[45:] == value.encode("utf-8")


@pytest.mark.parametrize("value", ["\x01"*255+"a", "\U00010000"*256,
    " \U0001f600" + "\U0010ffff"*253 + " ", "  Unstripped Type  "])
def test_legal_type_cursor_capacity_and_exact_roundtrip(value):
    cursor = options.encode_cursor(KEY, BINDING, "type", 1, value, 1300)
    assert len(cursor) <= 1470 < 2048
    assert len(options._unb64(cursor.split(".")[0])) == 45 + len(value.encode("utf-8"))
    assert options.decode_cursor(cursor, KEY, BINDING, "type", 1, 1000) == (value, 1300)


@pytest.mark.parametrize("resource,value", [("organization", str(UUID(int=1))),
    ("counterparty", str(UUID(int=2))), ("location", "\U0010ffff"*40)])
def test_other_legal_cursor_domains_are_bounded(resource, value):
    cursor = options.encode_cursor(KEY, BINDING, resource, 100, value, 1300)
    assert len(cursor) <= 318  # location: 45 + 40*4 bytes, 274 + 1 + 43 chars.
    assert options.decode_cursor(cursor, KEY, BINDING, resource, 100, 1000) == (value, 1300)


@pytest.mark.parametrize("fault", ["short", "oversize", "version", "resource", "page_size",
    "length", "trailing", "utf8", "nul", "blank", "long_value", "digest", "uuid"])
def test_authenticated_malformed_binary_cursor_is400(fault):
    # Valid MAC deliberately isolates the bounded binary decoder from MAC rejection.
    raw = options._unb64(options.encode_cursor(KEY, BINDING, "type", 1, "type", 1300).split(".")[0])
    resource = "type"
    if fault == "short": raw = raw[:44]
    elif fault == "oversize": raw += b"x"*1070
    elif fault == "version": raw = b"\x01" + raw[1:]
    elif fault == "resource": raw = raw[:1] + b"\xff" + raw[2:]
    elif fault == "page_size": raw = raw[:2] + b"\x00" + raw[3:]
    elif fault == "length": raw = raw[:11] + b"\xff\xff" + raw[13:]
    elif fault == "trailing": raw += b"x"
    elif fault == "digest": raw = raw[:13] + bytes([raw[13] ^ 1]) + raw[14:]
    else:
        value = {"utf8": b"\xff", "nul": b"a\x00", "blank": b" \t ",
            "long_value": b"x"*257, "uuid": b"not-a-uuid"}[fault]
        raw = raw[:11] + len(value).to_bytes(2, "big") + raw[13:45] + value
        if fault == "uuid":
            resource = "organization"
            raw = raw[:1] + b"\x00" + raw[2:]
    encoded = options._b64(raw)
    cursor = encoded + "." + options._b64(options._mac(KEY, "cursor-v2", (BINDING, encoded)))
    with pytest.raises(HTTPException) as failure:
        options.decode_cursor(cursor, KEY, BINDING, resource, 1, 1000)
    assert failure.value.status_code == 400


@pytest.mark.parametrize("error", [HTTPException(403), StarletteHTTPException(429, headers={"Retry-After": "7"}),
    budget.BudgetExceeded(7), RequestValidationError([])])
def test_lifetime_source_reraises_framework_protocol_after_mandatory_cleanup(error):
    # No Session/verifier stand-in. Actual cross-yield 422 and quota429 are PG cases.
    module = ast.parse((ROOT / "app/product_api/contract_create_options.py").read_bytes())
    lifetime = next(n for n in module.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "request_lifetime")
    outer = next(n for n in lifetime.body if isinstance(n, ast.Try))
    handler = outer.handlers[0]
    assert ast.dump(handler.type) == ast.dump(ast.parse("(StarletteHTTPException, RequestValidationError)", mode="eval").body)
    assert isinstance(error, (options.StarletteHTTPException, options.RequestValidationError))
    assert len(handler.body) == 1 and isinstance(handler.body[0], ast.Raise) and handler.body[0].exc is None
    cleanups = [n for n in ast.walk(outer) if isinstance(n, ast.Try) and n.finalbody
        and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_rollback"
            for statement in n.finalbody for c in ast.walk(statement))]
    assert len(cleanups) == 2 and all(not n.handlers for n in cleanups)
    assert outer.finalbody and "request.scope.pop" in ast.unparse(outer.finalbody[0])


def test_canonical_length_prefix_domain_separation_and_set_order():
    assert options._pack(("ab", "c")) != options._pack(("a", "bc"))
    assert options._pack(None) != options._pack(frozenset())
    assert options._pack(True) != options._pack(1)
    assert options._pack({"a", "b"}) == options._pack(frozenset(("b", "a")))
    assert options.selection_version(KEY, BINDING) == options.selection_version(KEY, tuple(BINDING))
    assert options._mac(KEY, "cursor", BINDING) != options._mac(KEY, "selection", BINDING)
    with pytest.raises(UnicodeError):
        options._pack("\ud800")
    with pytest.raises(HTTPException) as failure:
        options.selection_version(b"short", BINDING)
    assert failure.value.status_code == 503


@pytest.mark.parametrize("change", ["binding", "token", "key", "resource", "size", "expired", "future", "tamper", "padded", "garbage"])
def test_cursor_failure_is_generic400(change):
    token = options.encode_cursor(KEY, BINDING, "type", 50, "literal", 1300)
    key, binding, resource, size, now = KEY, BINDING, "type", 50, 1000
    if change == "binding": binding += ("changed-domain",)
    elif change == "token": binding += (UUID("10000000-0000-4000-8000-000000000002"),)
    elif change == "key": key = b"rotated-existing-cursor-key-32-bytes"
    elif change == "resource": resource = "organization"
    elif change == "size": size = 1
    elif change == "expired": now = 1300
    elif change == "future": now = 999
    elif change == "tamper": token = ("A" if token[0] != "A" else "B") + token[1:]
    elif change == "padded": token = token.replace(".", "=.")
    else: token = "not.a.cursor"
    with pytest.raises(HTTPException) as failure:
        options.decode_cursor(token, key, binding, resource, size, now)
    assert failure.value.status_code == 400


@pytest.mark.parametrize("field", ["token_id", "grant_id", "user_id", "company_id", "app_id", "installation_id",
    "client_id", "is_machine", "scopes", "own_organization_id", "location_ids", "resource_scopes"])
def test_each_identity_dimension_changes_binding(field):
    values = dict(token_id=UUID(int=1), grant_id=UUID(int=2), user_id=UUID(int=3), company_id=UUID(int=4),
        app_id=UUID(int=5), installation_id=UUID(int=6), client_id="client", is_machine=False,
        scopes=frozenset({"contracts:create"}), own_organization_id=None, location_ids=None,
        resource_scopes={"objects": SimpleNamespace(mode="ALL", ids=frozenset())})
    profile = dict(id=UUID(int=7), policy_generation=1)
    domains = (frozenset({str(UUID(int=8))}), frozenset(), frozenset({" A "}), frozenset({"type"}))
    original = options._binding(SimpleNamespace(**values), profile, domains, None)
    mutations = dict(token_id=UUID(int=11), grant_id=UUID(int=12), user_id=UUID(int=13), company_id=UUID(int=14),
        app_id=UUID(int=15), installation_id=UUID(int=16), client_id="another", is_machine=True,
        scopes=frozenset({"contracts:create", "contracts:read"}), own_organization_id=UUID(int=18),
        location_ids=frozenset(), resource_scopes={"objects": SimpleNamespace(mode="EMPTY", ids=frozenset())})
    values[field] = mutations[field]
    changed = options._binding(SimpleNamespace(**values), profile, domains, None)
    assert options.selection_version(KEY, original) != options.selection_version(KEY, changed)
    assert options.selection_version(KEY, original) != options.selection_version(KEY, options._binding(
        SimpleNamespace(**values), profile, domains, frozenset()))


@pytest.mark.parametrize("mutation", ["copy", "request", "method", "operation", "tenant", "permissions", "stage"])
def test_descriptor_exact_request_method_operation_tenant_and_stage(mutation):
    principal = Principal(PrincipalKind.PARTNER, "subject", "client", str(UUID(int=1)), str(UUID(int=2)))
    policy = RoutePolicy(owner="contracts", accepted_kinds={PrincipalKind.PARTNER, PrincipalKind.SERVICE},
        resource_type="contracts", action="create-options", required_scopes={"contracts:create"},
        policy_version="product-read-1", tenant_required=True, security_scheme="ProductOAuth",
        resource_stage=ResourceStage.CREATE_OPTIONS)
    request = SimpleNamespace(scope={"route": SimpleNamespace(operation_id="getContractCreateOptions", path="/contracts/create-options")}, method="GET")
    descriptor = CreateOptionsPreflight(request, str(UUID(int=3)), principal, "product-read-1")
    request.scope[CREATE_OPTIONS_KEY] = descriptor
    context = AccessContext(principal, descriptor.company_id, "product-read-1", frozenset({"contracts:create"}),
        valid=True, create_options=descriptor)
    authorize(context, policy, request)
    if mutation == "copy": context = replace(context, create_options=copy(descriptor))
    elif mutation == "request": request = SimpleNamespace(scope=dict(request.scope), method="GET")
    elif mutation == "method": request.method = "POST"
    elif mutation == "operation": request.scope["route"].operation_id = "getContract"
    elif mutation == "tenant": context = replace(context, company_id=str(UUID(int=4)))
    elif mutation == "permissions": context = replace(context, permissions=(
        ResourcePermission("contracts", "read", ResourceScope.all(), ResourceScope.all()),))
    else: policy = replace(policy, resource_stage=ResourceStage.EXISTING)
    with pytest.raises(HTTPException) as failure:
        authorize(context, policy, request)
    assert failure.value.status_code == 403


def test_offline_module_boundary_and_no_write_or_lock_calls():
    module = ast.parse((ROOT / "app/product_api/contract_create_options.py").read_bytes())
    for node in module.body:
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("app.services", "app.auth", "app.config", "app.main", "app.models"))
    names = {node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(module) if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))}
    assert not names & {"commit", "add", "add_all", "flush", "begin_nested", "with_for_update", "prepare_create", "require_create", "acquire_scoped_locks"}
    lifetime = next(n for n in module.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "request_lifetime")
    source = ast.unparse(lifetime)
    assert source.index("execution_options=") < source.index("db.execute(") < source.index("bind=True")
    assert "REPEATABLE READ" in source and "postgresql_readonly" in source
    assert "asyncio.timeout(DEADLINE_SECONDS)" in source
    assert "budget.enforce" in source and "_rollback" in source


def test_literal_route_precedes_dynamic_and_old_read_manifest_is_fixed15():
    module = ast.parse((ROOT / "app/product_api/app.py").read_bytes())
    create = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "create_product_api")
    routes = [n for n in create.body if isinstance(n, ast.AsyncFunctionDef) and n.decorator_list]
    names = [n.name for n in routes]
    assert names.index("contract_create_options_get") < names.index("contract_detail")
    from tests.test_product_http_profile import EXPECTED_GET_MANIFEST, EXPECTED_PRODUCT_MANIFEST, OPTIONS_MANIFEST
    assert len(EXPECTED_GET_MANIFEST) == 15 and len(EXPECTED_PRODUCT_MANIFEST) == 17
    assert OPTIONS_MANIFEST == {("GET", "/contracts/create-options", "getContractCreateOptions")}


@pytest.mark.parametrize("member_scope", [None, frozenset(), frozenset({" A "})])
@pytest.mark.parametrize("resource_mode", ["ALL", "SET", "EMPTY"])
def test_pure_shared_selector_preserves_existing_intersections(member_scope, resource_mode):
    from app.services.partner_contract_authority import select_create_domains
    org, cp = UUID(int=20), UUID(int=21)
    token = SimpleNamespace(own_organization_id=org, location_ids=frozenset({" A ", "a"}),
        resource_scopes={"objects": SimpleNamespace(mode=resource_mode, ids=frozenset({" A "})),
            "counterparties": SimpleNamespace(mode=resource_mode, ids=frozenset({str(cp)})),
            "contracts": SimpleNamespace(mode="EMPTY", ids=frozenset())})
    refs = ((None, None, "organization", org, None, None),
        (None, None, "organization", UUID(int=22), None, None),
        (None, None, "counterparty", None, cp, None),
        (None, None, "location", None, None, " A "),
        (None, None, "location", None, None, "a"))
    domains = select_create_domains(token, refs, ((None, " Type "), (None, "inactive")),
        {" Type ": ((" Type ", True),), "inactive": (("inactive", False),)}, member_scope)
    expected_locations = {" A ", "a"} if resource_mode == "ALL" else {" A "} if resource_mode == "SET" else set()
    if member_scope is not None:
        expected_locations &= member_scope
    assert domains == (frozenset({org}), frozenset({cp}) if resource_mode != "EMPTY" else frozenset(),
        frozenset(expected_locations), frozenset({" Type "}))
