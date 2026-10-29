"""Executable route contracts for a new API surface, independent of legacy auth."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from inspect import isawaitable, iscoroutinefunction
import re
from typing import Awaitable, Callable

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.routing import Mount

from .context import AccessContext, PrincipalKind, ResourceScope, ScopeMode, _names


class PolicyConfigurationError(ValueError):
    pass


ContextResolver = Callable[[Request], AccessContext | Awaitable[AccessContext]]
ResourceSelector = Callable[[Request], ResourceScope | Awaitable[ResourceScope]]
TenantSelector = Callable[[Request], str | Awaitable[str]]
_CONTEXT_KEY = "elsy.api_contracts.access_context"


@dataclass(frozen=True)
class RoutePolicy:
    owner: str
    accepted_kinds: frozenset[PrincipalKind]
    resource_type: str
    action: str
    required_scopes: frozenset[str]
    policy_version: str
    tenant_required: bool
    security_scheme: str | None = None
    required_fields: frozenset[str] = frozenset()

    def __post_init__(self):
        _names([self.owner, self.resource_type, self.action, self.policy_version])
        object.__setattr__(self, "accepted_kinds", frozenset(self.accepted_kinds))
        object.__setattr__(self, "required_scopes", _names(self.required_scopes))
        object.__setattr__(self, "required_fields", _names(self.required_fields))
        if (not self.accepted_kinds
                or any(type(kind) is not PrincipalKind for kind in self.accepted_kinds)
                or type(self.tenant_required) is not bool):
            raise PolicyConfigurationError("Explicit kinds and tenant requirement required")
        if PrincipalKind.PUBLIC in self.accepted_kinds:
            if self.accepted_kinds != {PrincipalKind.PUBLIC}:
                raise PolicyConfigurationError("Public and authenticated contracts must be separate")
            if self.required_scopes or self.security_scheme:
                raise PolicyConfigurationError("Public operation cannot claim authenticated scopes")
        elif not self.required_scopes or not self.security_scheme:
            raise PolicyConfigurationError("Private operation requires scopes and security scheme")
        if self.security_scheme is not None:
            _names([self.security_scheme])

    @property
    def public(self) -> bool:
        return self.accepted_kinds == {PrincipalKind.PUBLIC}

    def metadata(self) -> dict:
        return {
            "owner": self.owner, "principalKinds": sorted(kind.value for kind in self.accepted_kinds),
            "resourceType": self.resource_type, "action": self.action,
            "scopes": sorted(self.required_scopes), "policyVersion": self.policy_version,
            "tenantRequired": self.tenant_required, "fields": sorted(self.required_fields),
            "securityScheme": self.security_scheme,
        }


@dataclass(frozen=True)
class _Binding:
    policy: RoutePolicy
    resolver: ContextResolver
    selector: ResourceSelector | None = None
    tenant_selector: TenantSelector | None = None


async def _call(callback, request):
    # Async and synchronous server resolvers are supported. There is no model
    # binding from body/query/header and no dependency override impersonation.
    if iscoroutinefunction(callback):
        return await callback(request)
    value = await run_in_threadpool(callback, request)
    return await value if isawaitable(value) else value


def authorize(context: AccessContext, policy: RoutePolicy) -> None:
    if type(context) is not AccessContext or not context.valid:
        raise HTTPException(401, "Invalid access context")
    if context.policy_version != policy.policy_version:
        raise HTTPException(401, "Invalid access context")
    if context.principal.kind not in policy.accepted_kinds:
        raise HTTPException(403, "Principal kind is not accepted")
    if policy.tenant_required and not context.company_id:
        raise HTTPException(403, "Tenant context is required")
    if not policy.required_scopes <= context.scopes:
        raise HTTPException(403, "Required scope is not granted")
    permission = context.permission(policy.resource_type, policy.action)
    if permission.resources.mode in (ScopeMode.EMPTY, ScopeMode.UNINITIALIZED):
        raise HTTPException(403, "Resource access is not granted")
    if policy.required_fields and not permission.fields.contains(policy.required_fields):
        raise HTTPException(403, "Field access is not granted")


def get_access_context(request: Request) -> AccessContext:
    """Dependency for handlers/queries, usable only after PolicyRoute's guard."""
    context = request.scope.get(_CONTEXT_KEY)
    if type(context) is not AccessContext or not context.valid:
        raise HTTPException(401, "Invalid access context")
    return context


def _validate_extra(policy: RoutePolicy, extra: dict) -> None:
    if "x-access-policy" in extra and extra["x-access-policy"] != policy.metadata():
        raise PolicyConfigurationError("Route policy metadata cannot be overridden")
    expected = [] if policy.public else [{policy.security_scheme: sorted(policy.required_scopes)}]
    if "security" in extra and extra["security"] != expected:
        raise PolicyConfigurationError("Security contract cannot be overridden")


class PolicyRoute(APIRoute):
    binding: _Binding | None = None

    def __init__(self, *args, **kwargs):
        if type(self.binding) is not _Binding:
            raise PolicyConfigurationError("Every new operation requires RoutePolicy and resolver")
        extra = dict(kwargs.get("openapi_extra") or {})
        _validate_extra(self.binding.policy, extra)
        extra["x-access-policy"] = self.binding.policy.metadata()
        extra["security"] = ([] if self.binding.policy.public else [
            {self.binding.policy.security_scheme: sorted(self.binding.policy.required_scopes)}])
        kwargs["openapi_extra"] = extra
        if kwargs.get("callbacks"):
            raise PolicyConfigurationError("Callbacks require a separate explicit contract")
        super().__init__(*args, **kwargs)

    def get_route_handler(self):
        original = super().get_route_handler()
        binding = self.binding

        async def guarded(request: Request):
            context = await _call(binding.resolver, request)
            authorize(context, binding.policy)
            if binding.tenant_selector is not None:
                try:
                    tenant = await _call(binding.tenant_selector, request)
                except (ValueError, TypeError, KeyError):
                    raise HTTPException(403, "Invalid tenant selector") from None
                if not isinstance(tenant, str) or not tenant or tenant != context.company_id:
                    raise HTTPException(403, "Tenant does not match access context")
            if binding.selector is not None:
                try:
                    selection = await _call(binding.selector, request)
                except (ValueError, TypeError, KeyError):
                    raise HTTPException(403, "Invalid resource selector") from None
                if type(selection) is not ResourceScope or selection.mode is not ScopeMode.SET:
                    raise HTTPException(403, "Explicit nonempty resource selection required")
                permission = context.permission(binding.policy.resource_type, binding.policy.action)
                if not permission.resources.contains(selection.ids):
                    raise HTTPException(403, "Resource selection is not granted")
                context = context.select(binding.policy.resource_type, binding.policy.action, selection)
                authorize(context, binding.policy)
            request.scope[_CONTEXT_KEY] = context
            return await original(request)

        return guarded


class PolicyRouter(APIRouter):
    def __init__(self, *, context_resolver: ContextResolver, **kwargs):
        if not callable(context_resolver):
            raise PolicyConfigurationError("Server context resolver is required")
        if kwargs.get("routes") or "route_class" in kwargs:
            raise PolicyConfigurationError("Routes must be registered through explicit policy")
        self.context_resolver = context_resolver
        super().__init__(route_class=PolicyRoute, **kwargs)

    def operation(self, path: str, *, policy: RoutePolicy,
                  selector: ResourceSelector | None = None,
                  tenant_selector: TenantSelector | None = None, **kwargs):
        if type(policy) is not RoutePolicy:
            raise PolicyConfigurationError("Explicit RoutePolicy required")
        if any(item is not None and not callable(item) for item in (selector, tenant_selector)):
            raise PolicyConfigurationError("Selectors must be server callables")
        binding = _Binding(policy, self.context_resolver, selector, tenant_selector)
        route_class = type("BoundPolicyRoute", (PolicyRoute,), {"binding": binding})

        def register(endpoint):
            self.add_api_route(path, endpoint, route_class_override=route_class, **kwargs)
            return endpoint

        return register

    def add_api_route(self, path, endpoint, **kwargs):
        route_class = kwargs.get("route_class_override")
        if (not isinstance(route_class, type) or not issubclass(route_class, PolicyRoute)
                or type(route_class.binding) is not _Binding):
            raise PolicyConfigurationError("Unannotated operation is forbidden")
        super().add_api_route(path, endpoint, **kwargs)

    def include_router(self, router, **kwargs):
        # Preflight the whole router before mutating the destination.
        policy_registry(router)
        if not any(isinstance(route, Mount) for route in router.routes):
            proxy = APIRouter(routes=list(router.routes), lifespan=router.lifespan_context,
                              default_response_class=router.default_response_class,
                              generate_unique_id_function=router.generate_unique_id_function)
            super().include_router(proxy, **kwargs)
            return
        # FastAPI 0.115 silently skips Mount during include_router. Preserve
        # order and bound ASGI applications, then merge the source lifecycle.
        for route in router.routes:
            if isinstance(route, Mount):
                self.mount(kwargs.get("prefix", "") + route.path, route.app, name=route.name)
            else:
                single = APIRouter(routes=[route], default_response_class=router.default_response_class,
                                   generate_unique_id_function=router.generate_unique_id_function)
                super().include_router(single, **kwargs)
        # Source hooks belong to its lifespan, not to two copied hook lists.
        lifecycle = APIRouter(lifespan=router.lifespan_context)
        super().include_router(lifecycle, **kwargs)

    def add_route(self, *args, **kwargs):
        raise PolicyConfigurationError("Native HTTP routes need an explicit policy adapter")

    def add_api_websocket_route(self, *args, **kwargs):
        raise PolicyConfigurationError("WebSocket needs a separate explicit policy adapter")

    def add_websocket_route(self, *args, **kwargs):
        raise PolicyConfigurationError("WebSocket needs a separate explicit policy adapter")

    def mount(self, path, app, name=None):
        policy_registry(app)
        super().mount(self.prefix + path, app, name=name)


def policy_registry(app, *, prefix: str = "", _seen: frozenset[int] = frozenset()) -> list[dict]:
    """Validate the entire *new* API surface, including mounted ASGI apps."""
    if id(app) in _seen:
        raise PolicyConfigurationError("Cyclic mount")
    routes = getattr(app, "routes", None)
    if routes is None:
        raise PolicyConfigurationError("Opaque mounted ASGI application is forbidden")
    seen = _seen | {id(app)}
    entries = []
    for route in routes:
        if isinstance(route, Mount):
            entries.extend(policy_registry(route.app, prefix=prefix + route.path, _seen=seen))
        elif isinstance(route, PolicyRoute) and type(route.binding) is _Binding:
            _validate_extra(route.binding.policy, route.openapi_extra or {})
            if (route.openapi_extra or {}).get("x-access-policy") != route.binding.policy.metadata():
                raise PolicyConfigurationError("Missing route policy metadata")
            if "security" not in (route.openapi_extra or {}):
                raise PolicyConfigurationError("Missing route security metadata")
            entries.append({"path": prefix + route.path, "methods": sorted(route.methods),
                            "operationId": route.operation_id or route.unique_id,
                            "includeInSchema": route.include_in_schema,
                            **route.binding.policy.metadata()})
        else:
            raise PolicyConfigurationError(f"Unannotated route: {getattr(route, 'path', '?')}")
    operations, ids = set(), set()
    for entry in entries:
        for method in entry["methods"]:
            key = (re.sub(r"\{[^}]+\}", "{}", entry["path"]), method)
            if key in operations:
                raise PolicyConfigurationError("Duplicate or ambiguous route template")
            operations.add(key)
        if entry["operationId"] in ids:
            raise PolicyConfigurationError("Duplicate operationId")
        ids.add(entry["operationId"])
    return entries


def create_policy_app(*, context_resolver: ContextResolver, title: str = "Product API",
                      version: str = "1") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        policy_registry(app)
        await app.router.startup()
        try:
            yield
        finally:
            await app.router.shutdown()

    # Specs remain available as Python data for a future curated publisher.
    # No anonymous documentation HTTP surface is installed by this foundation.
    app = FastAPI(title=title, version=version, docs_url=None, redoc_url=None, openapi_url=None)
    app.router = PolicyRouter(context_resolver=context_resolver, lifespan=lifespan,
                              dependency_overrides_provider=app)
    return app
