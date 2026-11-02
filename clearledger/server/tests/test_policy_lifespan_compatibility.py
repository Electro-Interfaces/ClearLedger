"""ROOT-gated ASGI lifecycle contracts; no database or application assembly."""
import os

import pytest

if os.environ.get("RUN_POLICY_LIFESPAN_COMPATIBILITY") != "1":
    pytest.skip("ROOT-only isolated lifecycle matrix", allow_module_level=True)
if os.environ.get("ROOT_APPROVED_POLICY_LIFESPAN_COMPATIBILITY") != "1":
    raise pytest.UsageError("Use only the reviewed policy_lifespan_compatibility_approved runner")

from contextlib import asynccontextmanager

from fastapi import Depends, Request
from fastapi.testclient import TestClient
from starlette.routing import Route

from app.api_contracts import (
    AccessContext, PolicyConfigurationError, PolicyRouter, Principal, PrincipalKind,
    ResourcePermission, ResourceScope, RoutePolicy, create_policy_app, get_access_context,
)
from app.api_contracts import routing


def access():
    return AccessContext(Principal(PrincipalKind.PARTNER, "subject", "client", "install", "grant"),
                         "tenant-a", "policy-1", {"documents.read"},
                         (ResourcePermission("document", "read", ResourceScope.selected(["a"]),
                                             ResourceScope.selected(["title"])),), valid=True)


def contract():
    return RoutePolicy(owner="documents", accepted_kinds={PrincipalKind.PARTNER},
                       resource_type="document", action="read", required_scopes={"documents.read"},
                       policy_version="policy-1", tenant_required=True, security_scheme="ProductOAuth")


def app_with_hooks(events):
    app = create_policy_app(context_resolver=lambda request: access())
    app.router.add_event_handler("startup", lambda: events.append("root.start.sync"))

    async def start():
        events.append("root.start.async")

    async def stop():
        events.append("root.stop.async")

    app.router.add_event_handler("startup", start)
    app.router.add_event_handler("shutdown", lambda: events.append("root.stop.sync"))
    app.router.add_event_handler("shutdown", stop)
    return app


def observe_registry(monkeypatch, events, root):
    original = routing.policy_registry

    def observed(value, **kwargs):
        if value is root:
            events.append("registry")
        return original(value, **kwargs)

    monkeypatch.setattr(routing, "policy_registry", observed)


def test_registry_precedes_root_sync_async_hooks_once_each_lifespan(monkeypatch):
    events = []
    app = app_with_hooks(events)
    observe_registry(monkeypatch, events, app)
    for _ in range(2):
        with TestClient(app):
            assert events[-3:] == ["registry", "root.start.sync", "root.start.async"]
    assert events == ["registry", "root.start.sync", "root.start.async",
                      "root.stop.sync", "root.stop.async"] * 2


@pytest.mark.parametrize("with_mount", [False, True])
def test_include_default_hooks_run_once_and_mount_does_not_start_child(with_mount):
    events = []
    app = app_with_hooks(events)
    source = PolicyRouter(context_resolver=lambda request: access(), prefix="/source")
    source.add_event_handler("startup", lambda: events.append("source.start"))
    source.add_event_handler("shutdown", lambda: events.append("source.stop"))
    if with_mount:
        child = create_policy_app(context_resolver=lambda request: access())
        child.router.add_event_handler("startup", lambda: events.append("mounted.start"))
        child.router.add_event_handler("shutdown", lambda: events.append("mounted.stop"))
        child.router.operation("/ok", policy=contract(), methods=["GET"])(lambda: {"ok": True})
        source.mount("/child", child)
    else:
        source.operation("/ok", policy=contract(), methods=["GET"])(lambda: {"ok": True})
    app.include_router(source, prefix="/include")
    with TestClient(app) as client:
        url = "/include/source/child/ok" if with_mount else "/include/source/ok"
        assert client.get(url).json() == {"ok": True}
        assert events == ["root.start.sync", "root.start.async", "source.start"]
    # FastAPI's merged context exits the included context before the root.
    assert events == ["root.start.sync", "root.start.async", "source.start", "source.stop",
                      "root.stop.sync", "root.stop.async"]


def test_nested_custom_lifespans_keep_state_precedence_and_reverse_cleanup(monkeypatch):
    events = []
    app = app_with_hooks(events)

    @asynccontextmanager
    async def outer(application):
        assert application is app
        events.append("outer.enter")
        try:
            yield {"shared": "outer", "outer": "ready"}
        finally:
            events.append("outer.exit")

    @asynccontextmanager
    async def inner(application):
        assert application is app
        events.append("inner.enter")
        try:
            yield {"shared": "inner", "inner": "ready"}
        finally:
            events.append("inner.exit")

    source = PolicyRouter(context_resolver=lambda request: access(), lifespan=outer)
    nested = PolicyRouter(context_resolver=lambda request: access(), lifespan=inner)
    # Custom lifespan replaces the source event lifecycle, as in FastAPI itself.
    source.add_event_handler("startup", lambda: events.append("unused.source.start"))
    source.add_event_handler("shutdown", lambda: events.append("unused.source.stop"))

    @nested.operation("/state", policy=contract(), methods=["GET"])
    async def state(request: Request):
        return {"shared": request.state.shared, "outer": request.state.outer,
                "inner": request.state.inner}

    source.include_router(nested)
    app.include_router(source)
    observe_registry(monkeypatch, events, app)
    with TestClient(app) as client:
        assert client.get("/state").json() == {"shared": "outer", "outer": "ready", "inner": "ready"}
        assert events == ["registry", "root.start.sync", "root.start.async", "outer.enter", "inner.enter"]
    assert events == ["registry", "root.start.sync", "root.start.async", "outer.enter", "inner.enter",
                      "inner.exit", "outer.exit", "root.stop.sync", "root.stop.async"]


@pytest.mark.parametrize("mutation", ["root", "mounted", "metadata"])
def test_late_invalid_policy_blocks_every_startup_effect(mutation):
    events = []
    app = app_with_hooks(events)
    source = PolicyRouter(context_resolver=lambda request: access())
    source.add_event_handler("startup", lambda: events.append("source.start"))
    source.add_event_handler("shutdown", lambda: events.append("source.stop"))
    child = create_policy_app(context_resolver=lambda request: access())
    child.router.operation("/ok", policy=contract(), methods=["GET"])(lambda: "ok")
    source.mount("/child", child)
    app.include_router(source)
    if mutation == "metadata":
        child.routes[0].openapi_extra = {}
    else:
        target = app if mutation == "root" else child
        target.router.routes.append(Route("/late", lambda request: None))
    with pytest.raises(PolicyConfigurationError):
        with TestClient(app):
            pytest.fail("invalid policy entered lifespan")
    assert events == []


def test_startup_failure_keeps_framework_no_shutdown_semantics():
    events = []
    app = app_with_hooks(events)

    async def fail():
        events.append("startup.fail")
        raise RuntimeError("startup failed")

    app.router.add_event_handler("startup", fail)
    app.router.add_event_handler("startup", lambda: events.append("unreached"))
    with pytest.raises(RuntimeError, match="^startup failed$"):
        with TestClient(app):
            pytest.fail("startup failure swallowed")
    assert events == ["root.start.sync", "root.start.async", "startup.fail"]


@pytest.mark.parametrize("phase", ["enter", "exit"])
def test_custom_lifespan_failure_unwinds_root_and_preserves_exception(phase):
    events = []
    app = app_with_hooks(events)

    @asynccontextmanager
    async def failing(application):
        events.append("custom.enter")
        if phase == "enter":
            raise RuntimeError("custom enter failed")
        try:
            yield {"ready": True}
        finally:
            events.append("custom.exit")
            raise RuntimeError("custom exit failed")

    app.include_router(PolicyRouter(context_resolver=lambda request: access(), lifespan=failing))
    with pytest.raises(RuntimeError, match="^custom " + phase + " failed$"):
        with TestClient(app):
            assert events == ["root.start.sync", "root.start.async", "custom.enter"]
    expected = ["root.start.sync", "root.start.async", "custom.enter"]
    if phase == "exit":
        expected.append("custom.exit")
    assert events == expected + ["root.stop.sync", "root.stop.async"]


def test_shutdown_failure_propagates_and_does_not_repeat_handlers():
    events = []
    app = app_with_hooks(events)

    def fail():
        events.append("shutdown.fail")
        raise RuntimeError("shutdown failed")

    app.router.add_event_handler("shutdown", fail)
    app.router.add_event_handler("shutdown", lambda: events.append("unreached"))
    with pytest.raises(RuntimeError, match="^shutdown failed$"):
        with TestClient(app):
            pass
    assert events == ["root.start.sync", "root.start.async", "root.stop.sync",
                      "root.stop.async", "shutdown.fail"]


def test_resource_guard_dependency_and_schema_survive_real_lifespan():
    events = []
    app = app_with_hooks(events)

    def dependency():
        events.append("dependency")
        return "ready"

    @app.router.operation("/documents/{identifier}", policy=contract(), methods=["GET"],
                          selector=lambda request: ResourceScope.selected([request.path_params["identifier"]]))
    async def document(identifier: str, value=Depends(dependency),
                       context: AccessContext = Depends(get_access_context)):
        events.append("handler")
        return {"tenant": context.company_id, "ids": sorted(context.permission("document", "read").resources.ids),
                "dependency": value}

    with TestClient(app) as client:
        assert client.get("/documents/outside").status_code == 403
        assert events == ["root.start.sync", "root.start.async"]
        response = client.get("/documents/a")
        assert response.status_code == 200
        assert response.json() == {"tenant": "tenant-a", "ids": ["a"], "dependency": "ready"}
        operation = app.openapi()["paths"]["/documents/{identifier}"]["get"]
        assert operation["security"] == [{"ProductOAuth": ["documents.read"]}]
        assert operation["x-access-policy"]["tenantRequired"] is True
    assert events == ["root.start.sync", "root.start.async", "dependency", "handler",
                      "root.stop.sync", "root.stop.async"]
