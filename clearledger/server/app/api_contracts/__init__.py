"""Opt-in contracts for new product APIs; legacy routes are unchanged."""
from .context import AccessContext, Principal, PrincipalKind, ResourcePermission, ResourceScope, ScopeMode
from .routing import (
    ContextResolver, PolicyConfigurationError, PolicyRoute, PolicyRouter, ResourceSelector,
    RoutePolicy, TenantSelector, authorize,
    create_policy_app, get_access_context, policy_registry,
)

__all__ = [
    "AccessContext", "Principal", "PrincipalKind", "ResourcePermission", "ResourceScope", "ScopeMode",
    "PolicyConfigurationError", "PolicyRoute", "PolicyRouter", "RoutePolicy", "authorize",
    "create_policy_app", "get_access_context", "policy_registry",
    "ContextResolver", "ResourceSelector", "TenantSelector",
]
