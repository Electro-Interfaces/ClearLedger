"""Bridge from the M10 verifier to product policies; no token parsing/issuance."""
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from collections.abc import Mapping
import uuid

from fastapi import HTTPException, Request

from app.api_contracts import AccessContext, Principal, PrincipalKind, ResourcePermission, ResourceScope
from . import budget

RESOURCES = ("objects", "equipment", "counterparties", "contracts", "documents")
POLICY_VERSION = "product-read-1"
READ_SCOPES = {resource: f"{resource}:read" for resource in RESOURCES}
DOWNLOAD_SCOPE = "documents.files:download"


@dataclass(frozen=True)
class Facts:
    company_id: uuid.UUID
    user: object | None
    objects: ResourceScope
    organization_id: uuid.UUID | None
    grants: Mapping


def scope_of(value) -> ResourceScope:
    if value is None:
        return ResourceScope.empty()
    mode = value.get("mode") if isinstance(value, Mapping) else getattr(value, "mode", None)
    ids = value.get("ids", frozenset()) if isinstance(value, Mapping) else getattr(value, "ids", frozenset())
    mode = str(getattr(mode, "value", mode)).lower()
    if mode == "all":
        if ids:
            raise ValueError("ALL with identifiers")
        return ResourceScope.all()
    if mode == "set":
        return ResourceScope.selected(ids)
    if mode == "empty" and not ids:
        return ResourceScope.empty()
    raise ValueError("Invalid verified resource grant")


async def configured_verifier(token, db):
    # Owned by M10; importing the product package does not require that module.
    try:
        from app.services.partner_identity import PartnerProblem, verify_partner_access_token
    except ImportError:
        raise HTTPException(503, "Partner verifier is unavailable") from None
    try:
        return await verify_partner_access_token(token, db)
    except PartnerProblem as error:
        raise HTTPException(error.status, "Partner verification is unavailable") from None


def configured_enabled():
    from app.config import get_settings
    return getattr(get_settings(), "partner_api_enabled", False) is True


def configured_sessions():
    from app.database import async_session_factory
    return async_session_factory()


async def resolve(request: Request) -> AccessContext:
    settings = request.app.state.product_settings
    if settings.enabled() is not True:
        raise HTTPException(503, "Partner API is disabled")
    if request.query_params.get("access_token") is not None or request.query_params.get("token") is not None:
        raise HTTPException(401, "Bearer credentials required")
    authorization = request.headers.getlist("authorization")
    if len(authorization) != 1:
        raise HTTPException(401, "Bearer credentials required")
    parts = authorization[0].split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, "Bearer credentials required")
    policy = request.scope["route"].binding.policy
    async with settings.sessions() as db:
        token = await settings.verifier(parts[1], db)
        try:
            cid = uuid.UUID(str(token.company_id))
            for value in (token.app_id, token.installation_id, token.grant_id, token.token_id):
                uuid.UUID(str(value))
            if type(token.is_machine) is not bool or not token.client_id or not token.subject:
                raise ValueError("Incomplete verified identity")
            if token.expires_at <= datetime.now(timezone.utc):
                raise ValueError("Expired verified identity")
            if not isinstance(token.scopes, frozenset) or not isinstance(token.resource_scopes, Mapping):
                raise ValueError("Mutable verified grants")
            grants = MappingProxyType({key: scope_of(token.resource_scopes.get(key)) for key in RESOURCES})
            kind = PrincipalKind.SERVICE if token.is_machine else PrincipalKind.PARTNER
            principal = Principal(kind, token.subject, token.client_id,
                                  str(token.installation_id), str(token.grant_id))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(401, "Invalid verified identity") from None
        # Reject missing OAuth/resource authority before reading domain/user data.
        if not policy.required_scopes <= token.scopes:
            raise HTTPException(403, "Required scope is not granted")
        if kind not in policy.accepted_kinds:
            raise HTTPException(403, "Principal kind is not accepted")
        if not grants[policy.resource_type].contains([]):
            raise HTTPException(403, "Resource access is not granted")
        user = None
        objects = ResourceScope.all()
        try:
            own_org = getattr(token, "own_organization_id", None)
            own_org = uuid.UUID(str(own_org)) if own_org is not None else None
            compatibility = getattr(token, "location_ids", None)
            if compatibility is not None:
                objects = objects.intersect(ResourceScope.selected(compatibility))
            user_id = uuid.UUID(str(token.user_id)) if token.user_id is not None else None
        except (ValueError, TypeError):
            raise HTTPException(401, "Invalid verified identity") from None
        if not token.is_machine:
            from app.models import User, UserCompany
            if token.user_id is None:
                raise HTTPException(401, "User grant requires an authoritative user")
            user = await db.get(User, user_id)
            membership = await db.get(UserCompany, (user_id, cid))
            if user is None or membership is None or user.mail_only:
                raise HTTPException(403, "Current membership is required")
            if membership.object_scope is not None:
                objects = objects.intersect(ResourceScope.selected(membership.object_scope))
            if membership.own_organization_id is not None:
                if own_org is not None and own_org != membership.own_organization_id:
                    raise HTTPException(403, "Organization constraints do not intersect")
                own_org = membership.own_organization_id
            if policy.resource_type == "documents" and not (user.is_superadmin or membership.role == "admin"):
                from app.auth import resolve_member_modules
                modules = await resolve_member_modules(membership, db)
                if modules is not None and not any(item == "docs" or item.startswith("docs:") for item in modules):
                    raise HTTPException(403, "Document product access is required")
        elif token.user_id is not None:
            raise HTTPException(401, "Machine identity cannot impersonate a user")
        if own_org is not None:
            from app.models import Organization
            org = await db.get(Organization, own_org)
            if org is None or org.company_id != cid:
                raise HTTPException(403, "Organization context is not available")
        permissions = tuple(ResourcePermission(resource, action, grants[resource], ResourceScope.all())
                            for resource in RESOURCES for action in ("read", "download"))
        context = AccessContext(principal, str(cid), POLICY_VERSION, token.scopes, permissions, valid=True)
        request.state.product_facts = Facts(cid, user, objects, own_org, grants)
    # Release the identity connection before checking out the independent quota
    # transaction. Every request still performs the current live ACL above.
    await budget.enforce(settings.budget_policy(), settings.sessions,
                         budget.Key(cid, uuid.UUID(str(token.installation_id)), token.client_id))
    return context
