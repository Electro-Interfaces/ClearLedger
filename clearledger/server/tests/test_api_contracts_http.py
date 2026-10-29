from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.routing import Mount, Route

from app.api_contracts import (
    AccessContext, PolicyConfigurationError, PolicyRoute, PolicyRouter, Principal,
    PrincipalKind, ResourcePermission, ResourceScope, RoutePolicy, ScopeMode,
    create_policy_app, get_access_context, policy_registry,
)
from tests.test_api_contracts_context import context


def contract(**overrides):
    values = dict(owner="documents", accepted_kinds={PrincipalKind.PARTNER},
                  resource_type="document", action="read", required_scopes={"documents.read"},
                  policy_version="policy-1", tenant_required=True, security_scheme="ProductOAuth")
    values.update(overrides)
    return RoutePolicy(**values)


class Payload(BaseModel):
    title: str


def fixture_api(value, *, policy=None, selector=None, tenant_selector=None):
    state = {"context": value, "calls": [], "resolved": 0}

    async def resolve(request):
        state["resolved"] += 1
        return state["context"]

    app = create_policy_app(context_resolver=resolve)
    router = PolicyRouter(context_resolver=resolve)

    @router.operation("/companies/{company}/documents/{doc_id}", policy=policy or contract(),
                      selector=selector, tenant_selector=tenant_selector, methods=["POST"])
    async def handler(company: str, doc_id: str, payload: Payload,
                      access: AccessContext = Depends(get_access_context)):
        state["calls"].append(payload.title)
        allowed = access.permission("document", "read").resources
        return {"company": access.company_id, "mode": allowed.mode.value, "ids": sorted(allowed.ids)}

    app.include_router(router, prefix="/v1")
    return app, state


URL = "/v1/companies/company-a/documents/a"


@pytest.mark.parametrize("value,status", [
    (None, 401), ({"is_superadmin": True}, 401), (SimpleNamespace(is_superadmin=True), 401),
    (context(valid=False), 401), (replace(context(), policy_version="revoked-policy"), 401),
    (context(kind=PrincipalKind.USER), 403), (context(kind=PrincipalKind.SERVICE), 403),
    (context(kind=PrincipalKind.PUBLIC), 403), (replace(context(), company_id=None), 403),
    (context(scopes=set()), 403),
    (replace(context(), permissions=()), 403),
    (context(resources=ResourceScope.empty()), 403), (context(resources=ResourceScope()), 403),
    (replace(context(), permissions=(ResourcePermission("source_file", "read", ResourceScope.all()),)), 403),
    (replace(context(), permissions=(ResourcePermission("document", "edit", ResourceScope.all()),)), 403),
])
def test_missing_invalid_wrong_kind_tenant_scope_resource_or_action_deny_before_handler(value, status):
    app, state = fixture_api(value)
    with TestClient(app) as client:
        response = client.post(URL, json={"title": "must not execute", "is_superadmin": True},
                               headers={"X-Company-Id": "company-a", "X-Access-Context": "admin"})
    assert response.status_code == status, response.text
    assert state["calls"] == [] and state["resolved"] == 1


def test_guard_runs_before_body_validation_and_cannot_be_dependency_overridden():
    app, state = fixture_api(None)
    # The resolver is bound by server registration, not a client DTO/User adapter.
    app.dependency_overrides[get_access_context] = lambda: context()
    with TestClient(app) as client:
        denied = client.post(URL, content="broken json", headers={"Content-Type": "application/json"})
        assert denied.status_code == 401
        state["context"] = context()
        assert client.post(URL, json={}).status_code == 422
        assert client.post(URL, json={"title": "valid"}).status_code == 200
    assert state["calls"] == ["valid"]


def test_resolver_verdict_is_checked_again_after_grant_revocation():
    app, state = fixture_api(context())
    with TestClient(app) as client:
        assert client.post(URL, json={"title": "before revocation"}).status_code == 200
        # Future grant resolver returns its invalid verdict for revoked/stale grants.
        state["context"] = replace(state["context"], valid=False)
        assert client.post(URL, json={"title": "revoked"}).status_code == 401
    assert state["resolved"] == 2 and state["calls"] == ["before revocation"]


def test_guard_precedes_handler_dependencies_and_normal_di_is_preserved():
    state = {"context": None}
    events = []
    app = create_policy_app(context_resolver=lambda request: state["context"])
    router = PolicyRouter(context_resolver=lambda request: state["context"])

    def side_effect():
        events.append("dependency")
        return "original"

    @router.operation("/effects", policy=contract())
    def endpoint(value=Depends(side_effect)):
        events.append("handler")
        return value

    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/effects").status_code == 401
        assert not events
        state["context"] = context()
        app.dependency_overrides[side_effect] = lambda: "overridden"
        assert client.get("/effects").json() == "overridden"
    assert events == ["handler"]


@pytest.mark.parametrize("selection,status", [
    (ResourceScope.selected(["a"]), 200), (ResourceScope.selected(["b"]), 403),
    (ResourceScope.selected(["a", "b"]), 403), (ResourceScope.selected([]), 403),
    (ResourceScope.all(), 403), (ResourceScope(), 403), ({"mode": "all"}, 403),
])
def test_selected_resources_cannot_expand_partner_grant(selection, status):
    app, state = fixture_api(context(resources=ResourceScope.selected(["a"])),
                             selector=lambda request: selection)
    with TestClient(app) as client:
        response = client.post(URL, json={"title": "selected"})
    assert response.status_code == status
    if status == 200:
        assert response.json()["ids"] == ["a"]
    else:
        assert not state["calls"]


def test_explicit_path_selector_and_all_scope_narrow_context_for_query():
    app, state = fixture_api(context(), selector=lambda request: ResourceScope.selected(
        [request.path_params["doc_id"]]), tenant_selector=lambda request: request.path_params["company"])
    with TestClient(app) as client:
        response = client.post(URL, json={"title": "ok"})
        assert response.status_code == 200
        assert response.json() == {"company": "company-a", "mode": "set", "ids": ["a"]}
        assert client.post(URL.replace("company-a", "company-b"), json={"title": "no"}).status_code == 403
    assert state["calls"] == ["ok"]


def test_invalid_selector_does_not_fall_back_to_all():
    def invalid(request):
        return ResourceScope.selected(request.query_params.get("ids"))

    app, state = fixture_api(context(), selector=invalid)
    with TestClient(app) as client:
        assert client.post(URL, json={"title": "no"}).status_code == 403
        assert client.post(URL + "?ids=a,b", json={"title": "no"}).status_code == 403
    assert not state["calls"]


def test_user_admin_cannot_replace_partner_grant_or_bypass_kind():
    partner = context(resources=ResourceScope.selected(["a"]))
    user_admin = context(kind=PrincipalKind.USER)
    with pytest.raises(ValueError):
        partner.intersect(user_admin)
    app, state = fixture_api(partner, selector=lambda request: ResourceScope.selected(["b"]))
    with TestClient(app) as client:
        assert client.post(URL, json={"title": "admin", "role": "admin", "is_superadmin": True}).status_code == 403
        state["context"] = user_admin
        assert client.post(URL, json={"title": "admin"}).status_code == 403
    assert not state["calls"]


@pytest.mark.parametrize("fields,status", [
    (ResourceScope.all(), 200), (ResourceScope.selected(["title"]), 200),
    (ResourceScope.selected(["secret"]), 403), (ResourceScope.empty(), 403), (ResourceScope(), 403),
])
def test_field_permission_is_independent_from_resource_action(fields, status):
    app, state = fixture_api(context(fields=fields), policy=contract(required_fields={"title"}))
    with TestClient(app) as client:
        assert client.post(URL, json={"title": "ok"}).status_code == status
    assert bool(state["calls"]) is (status == 200)


def test_nested_fastapi_includes_preserve_policy_resolver_and_metadata():
    app, state = fixture_api(context())
    bridge = APIRouter()
    bridge.include_router(app.router, prefix="/bridge")
    outer = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    outer.include_router(bridge, prefix="/outer")
    with TestClient(outer) as client:
        assert client.post("/outer/bridge" + URL, json={"title": "ok"}).status_code == 200
        state["context"] = None
        assert client.post("/outer/bridge" + URL, json={"title": "no"}).status_code == 401
    registry = policy_registry(outer)
    assert registry[0]["path"] == "/outer/bridge/v1/companies/{company}/documents/{doc_id}"
    assert registry[0]["owner"] == "documents" and registry[0]["action"] == "read"
    operation = outer.openapi()["paths"][registry[0]["path"]]["post"]
    assert operation["security"] == [{"ProductOAuth": ["documents.read"]}]
    assert operation["x-access-policy"]["tenantRequired"] is True
    assert state["calls"] == ["ok"]


def test_mount_retains_runtime_guard_and_recursive_registry():
    child, state = fixture_api(None)
    root = create_policy_app(context_resolver=lambda request: context())
    root.mount("/product", child)
    with TestClient(root) as client:
        assert client.post("/product" + URL, json={"title": "no"}).status_code == 401
        state["context"] = context()
        assert client.post("/product" + URL, json={"title": "yes"}).status_code == 200
    assert policy_registry(root)[0]["path"] == "/product/v1/companies/{company}/documents/{doc_id}"
    assert state["calls"] == ["yes"]


def test_policy_include_preserves_mount_prefixes_order_and_lifecycle():
    child, state = fixture_api(None)
    source = PolicyRouter(context_resolver=lambda request: context(), prefix="/source")
    source.mount("/mounted", child)
    events = []
    source.add_event_handler("startup", lambda: events.append("started"))
    source.add_event_handler("shutdown", lambda: events.append("stopped"))
    root = create_policy_app(context_resolver=lambda request: context())
    root.include_router(source, prefix="/include")
    expected = "/include/source/mounted" + URL
    assert policy_registry(root)[0]["path"].startswith("/include/source/mounted/")
    with TestClient(root) as client:
        assert client.post(expected, json={"title": "no"}).status_code == 401
        state["context"] = context()
        assert client.post(expected, json={"title": "yes"}).status_code == 200
    assert events == ["started", "stopped"]
    assert state["calls"] == ["yes"]


def test_unannotated_routes_fail_at_registration_include_and_startup():
    router = PolicyRouter(context_resolver=lambda request: context())
    with pytest.raises(PolicyConfigurationError):
        router.get("/unmarked")(lambda: "unsafe")
    with pytest.raises(PolicyConfigurationError):
        PolicyRoute("/unmarked", lambda: "unsafe")
    legacy = APIRouter()
    legacy.get("/unmarked")(lambda: "unsafe")
    with pytest.raises(PolicyConfigurationError):
        router.include_router(legacy)
    assert not router.routes
    app = create_policy_app(context_resolver=lambda request: context())
    app.router.routes.append(Route("/sneaked", lambda request: None))
    with pytest.raises(PolicyConfigurationError):
        with TestClient(app):
            pass


def test_unannotated_and_opaque_mounts_are_rejected():
    app = create_policy_app(context_resolver=lambda request: context())
    legacy = FastAPI()
    with pytest.raises(PolicyConfigurationError):
        app.mount("/legacy", legacy)

    async def opaque(scope, receive, send):
        pass

    with pytest.raises(PolicyConfigurationError):
        app.mount("/opaque", opaque)
    assert not app.routes


def test_startup_checks_late_mutation_inside_mounted_app():
    child, _ = fixture_api(context())
    root = create_policy_app(context_resolver=lambda request: context())
    root.mount("/product", child)
    child.router.routes.append(Route("/late-unmarked", lambda request: None))
    with pytest.raises(PolicyConfigurationError):
        with TestClient(root):
            pass


def test_recursive_registry_rejects_cyclic_mount():
    root = create_policy_app(context_resolver=lambda request: context())
    root.router.routes.append(Mount("/cycle", root))
    with pytest.raises(PolicyConfigurationError, match="Cyclic"):
        policy_registry(root)


@pytest.mark.parametrize("path,operation_id", [("/first", "second"), ("/other", "duplicate")])
def test_duplicate_paths_or_operation_ids_cannot_start(path, operation_id):
    app = create_policy_app(context_resolver=lambda request: context())
    router = PolicyRouter(context_resolver=lambda request: context())
    router.operation("/first", policy=contract(), operation_id="duplicate")(lambda: "first")
    router.operation(path, policy=contract(), operation_id=operation_id)(lambda: "second")
    with pytest.raises(PolicyConfigurationError, match="Duplicate"):
        app.include_router(router)
    assert not app.routes


@pytest.mark.parametrize("changed", [{"security": []}, {"security": [{}]}, {}])
def test_startup_rejects_late_anonymous_or_missing_metadata(changed):
    app, _ = fixture_api(context())
    app.routes[0].openapi_extra = changed
    with pytest.raises(PolicyConfigurationError):
        with TestClient(app):
            pass


@pytest.mark.parametrize("extra", [
    {"security": []}, {"security": [{}]}, {"security": [{"OtherAuth": []}]},
    {"x-access-policy": {"owner": "anonymous"}},
])
def test_private_security_metadata_cannot_be_overridden(extra):
    router = PolicyRouter(context_resolver=lambda request: context())
    with pytest.raises(PolicyConfigurationError):
        router.operation("/private", policy=contract(), openapi_extra=extra)(lambda: "no")
    assert not router.routes


def test_explicit_public_route_still_requires_valid_public_context():
    policy = contract(accepted_kinds={PrincipalKind.PUBLIC}, required_scopes=set(),
                      tenant_required=False, security_scheme=None)
    app, state = fixture_api(replace(context(kind=PrincipalKind.PUBLIC), company_id=None), policy=policy)
    with TestClient(app) as client:
        assert client.post(URL, json={"title": "public"}).status_code == 200
        state["context"] = None
        assert client.post(URL, json={"title": "no"}).status_code == 401
    assert list(app.openapi()["paths"].values())[0]["post"]["security"] == []


@pytest.mark.parametrize("changed", [
    {"accepted_kinds": set()}, {"accepted_kinds": {"partner"}},
    {"accepted_kinds": {PrincipalKind.PUBLIC, PrincipalKind.USER}},
    {"required_scopes": set()}, {"security_scheme": None},
])
def test_incomplete_or_mixed_policy_is_not_registered(changed):
    with pytest.raises(PolicyConfigurationError):
        contract(**changed)


def test_synchronous_server_resolver_and_missing_context_dependency():
    app = create_policy_app(context_resolver=lambda request: context())
    router = PolicyRouter(context_resolver=lambda request: context())
    router.operation("/sync", policy=contract())(lambda: {"ok": True})
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/sync").json() == {"ok": True}
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
    from fastapi import HTTPException
    from starlette.requests import Request
    with pytest.raises(HTTPException) as error:
        get_access_context(Request({"type": "http"}))
    assert error.value.status_code == 401
