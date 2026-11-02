"""Additional Site boundary for internal document policy callers.

Authentication belongs to the native/product entrance or the recipient owner,
not to this SQL predicate. A User/payload/boolean is never proof of a login.
Every decision rereads membership, organization, approved context, assignment
and the raw ObjectId ceiling through P1c's one subject predicate. No refresh,
flush, transaction ownership or portable boolean authority is introduced here.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import and_, false, inspect, or_, select, text

from app.models import DocCard, EzsSite, User
from app.models_site_authority import SITE_ACTIONS
from app.services.site_authority import _clause, require_schema


async def require_document_schema(db):
    """Core requires7; legacy fresh public has only the NULL-Site branch.

    Public bootstrap remains its original owner; it must not provision Core
    contexts/FKs or join nonexistent Site authority tables. Foreign namespaces
    still deny before selecting any newly declared business columns.
    """
    with db.no_autoflush:
        namespace = await db.scalar(text("SELECT pg_catalog.current_schema()"))
        if namespace == "core":
            await db.run_sync(require_schema)
            return True
        if namespace == "public":
            return False
        raise HTTPException(503, "Document schema is not ready")


async def document_site_filter(db, company_id, user_id, permission):
    if not await require_document_schema(db):
        return DocCard.site_id.is_(None)
    return document_site_clause(company_id, user_id, permission)


def document_site_clause(company_id, user_id, permission):
    """SQL boundary before count/limit; NULL Site retains the legacy branch."""
    action = "document." + permission
    subject = false()
    if user_id is not None and action in SITE_ACTIONS:
        subject = _clause(company_id, user_id, DocCard.organization_id, action).where(
            EzsSite.id == DocCard.site_id).correlate(DocCard)
    return or_(DocCard.site_id.is_(None), and_(
        DocCard.company_id == company_id, DocCard.object_id.is_(None),
        DocCard.organization_id.is_not(None), subject,
    ))


async def document_site_allowed(db, company_id, doc, user, permission):
    """Internal policy: stored Site identity AND pending identity must agree.

    A background recipient has no JWT and the product resolver's User is
    detached. Both are legitimate trusted callers; neither needs a fabricated
    native session. Scalar projections preserve pending Card/User fields.
    """
    with db.no_autoflush:
        core = await require_document_schema(db)
        state = inspect(doc)
        if doc in db.deleted or state.deleted:
            return False
        stored = (await db.execute(select(
            DocCard.company_id, DocCard.site_id, DocCard.organization_id, DocCard.object_id,
            document_site_clause(company_id, user.id, permission) if core else DocCard.site_id.is_(None),
        ).where(DocCard.id == doc.id))).one_or_none()
        if stored is None:
            # Existing native draft construction can ask policy before INSERT.
            # New Site drafts have no writer admission and always deny here.
            return (state.transient or state.pending) and doc.site_id is None and doc.company_id == company_id
        if stored.company_id != company_id or doc.company_id != stored.company_id:
            return False
        if stored.site_id is None and doc.site_id is None:
            return True
        if (stored.site_id, stored.organization_id, stored.object_id) != (
                doc.site_id, doc.organization_id, doc.object_id):
            return False
        return bool(stored[4])


def _verified_scope(column, scope, *, uuid_ids=False):
    if scope is None:
        return false()
    if scope.mode == "ALL":
        return column.is_not(None)
    if scope.mode != "SET":
        return false()
    values = [uuid.UUID(value) for value in scope.ids] if uuid_ids else list(scope.ids)
    return column.in_(values)


async def partner_document_boundary(db, facts, context, permission):
    """Original canonical issuer, actual query Session, current Site intersection.

    Returns (SQL, current canonical User). The SQL contains a NULL-Site legacy
    branch; the additional partner/native boundary applies only to Site rows.
    No VerifiedToken is fabricated and the detached resolver User is never
    refreshed. Pending identity/card state is rejected before M10's refreshes.
    """
    from app.services.partner_identity import verify_partner_access_token
    legacy = DocCard.site_id.is_(None)
    if facts._site_bearer is None or facts.user is None:
        return legacy, facts.user
    with db.no_autoflush:
        if any(isinstance(row, (User, DocCard)) for row in (
                *db.new, *db.dirty, *db.deleted)):
            raise HTTPException(409, "Pending document identity state")
        current = await verify_partner_access_token(facts._site_bearer, db)
        principal = context.principal
        if (current.is_machine or current.user_id is None
                or str(current.company_id) != str(facts.company_id)
                or str(current.company_id) != context.company_id
                or str(current.user_id) != str(facts.user.id)
                or current.client_id != principal.client_id
                or str(current.installation_id) != principal.installation_id
                or str(current.grant_id) != principal.grant_id
                or current.subject != principal.subject
                or str(getattr(principal.kind, "value", principal.kind)).lower() != "partner"):
            raise HTTPException(403, "Current document identity is required")
        required = {"documents:read"}
        if permission == "download":
            required.add("documents.files:download")
        if not required <= current.scopes:
            raise HTTPException(403, "Current document scope is required")
        user = await db.get(User, current.user_id)  # canonical verifier refreshed this clean identity
        if user is None:
            raise HTTPException(403, "Current document identity is required")
        sites = current.resource_scopes.get("sites")
        site = false()
        if sites is not None and sites.mode == "SET":
            # Both canonical issuer ObjectId ceiling and raw membership [] are
            # required. An unbound Site needs no fabricated ServiceLocation.
            location = and_(
                _verified_scope(EzsSite.location_id, current.resource_scopes.get("objects")),
                EzsSite.location_id.in_(current.location_ids) if current.location_ids is not None else True,
            )
            site = select(EzsSite.id).where(
                EzsSite.company_id == facts.company_id, EzsSite.id == DocCard.site_id,
                _verified_scope(EzsSite.id, sites, uuid_ids=True),
                or_(EzsSite.location_id.is_(None), location),
            ).correlate(DocCard).exists()
        boundary = and_(
            DocCard.site_id.is_not(None), site,
            document_site_clause(facts.company_id, current.user_id, permission),
            _verified_scope(DocCard.id, current.resource_scopes.get("documents"), uuid_ids=True),
        )
        if current.own_organization_id is not None:
            boundary = and_(boundary, DocCard.organization_id == current.own_organization_id)
        return or_(legacy, boundary), user
