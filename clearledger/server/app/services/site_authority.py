"""Live, default-deny Site boundary; no writers and no transaction ownership.

Native callers pass the User returned by canonical native authentication, never
an actorId from a payload. Partner callers pass the bearer to the SAME canonical
issuer verifier on the actual caller Session. A token snapshot is not authority.
This boundary supplements, and cannot substitute for, native document/file ACL.
"""
from __future__ import annotations

import uuid

from sqlalchemy import and_, exists, func, inspect, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstanceState, Session
from sqlalchemy.util import await_only

from app.models import EzsProject, EzsSite, Organization, ServiceLocation, User, UserCompany
from app.models_site_authority import SITE_ACTIONS, SiteAuthorityContext, SiteUserPermission


def require_schema(db: Session) -> None:
    """Before any new ORM query: full current seven-artifact catalogue, no repair.

    Called in AsyncSession.run_sync's actual greenlet; raw driver belongs to the
    same transaction. No cached admission, second connection or credential input.
    """
    from fastapi import HTTPException
    from schema_migrations.runner import require_doc_site_prefix
    try:
        with db.no_autoflush:
            connection = db.connection()
            connection.execute(text("SELECT pg_catalog.current_schema()"))
            driver = connection.connection.driver_connection
            if not driver.is_in_transaction():
                raise RuntimeError("Site authority requires the caller transaction")
            await_only(require_doc_site_prefix(driver))
    except Exception:
        raise HTTPException(503, "Site authority schema is not ready") from None


def _clause(company_id, user_id, organization_id, action):
    # All fields below are read by SQL, including the actual membership's raw
    # object_scope. JSON [] denies a bound Site even for admin/superadmin.
    member = UserCompany
    context = SiteAuthorityContext
    permission = SiteUserPermission
    site = EzsSite
    # Project pointers are real too. Contradiction/multiple distinct links fail
    # closed, rather than choosing the first/current project as new authority.
    conflicting_project = exists(select(EzsProject.id).where(
        EzsProject.site_id == site.id,
        EzsProject.location_id.is_not(None),
        or_(EzsProject.company_id != company_id, site.location_id.is_(None),
            EzsProject.location_id != site.location_id),
    )).correlate(site)
    location_valid = exists(select(ServiceLocation.id).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.id == site.location_id,
    )).correlate(site)
    return exists(select(site.id).join(context, and_(
        context.company_id == site.company_id, context.site_id == site.id,
    )).join(permission, and_(
        permission.company_id == context.company_id, permission.site_id == context.site_id,
    )).join(member, and_(
        member.company_id == permission.company_id, member.user_id == permission.user_id,
    )).join(Organization, and_(
        Organization.company_id == context.company_id, Organization.id == context.organization_id,
    )).join(User, User.id == member.user_id).where(
        site.company_id == company_id, member.user_id == user_id,
        context.organization_id == organization_id,
        member.own_organization_id == context.organization_id,
        context.approved.is_(True), context.revoked.is_(False), context.policy_generation > 0,
        permission.approved.is_(True), permission.action == action,
        User.mail_only.is_(False), User.password_hash != "",
        or_(User.locked_until.is_(None), User.locked_until <= func.now()),
        ~conflicting_project,
        or_(site.location_id.is_(None), and_(location_valid,
            or_(member.object_scope.is_(None), member.object_scope.contains(func.jsonb_build_array(site.location_id))))),
    ))


def _allowed(db: Session, *, company_id: uuid.UUID, user_id: uuid.UUID,
             site_id: uuid.UUID, organization_id: uuid.UUID, action: str,
             partner=None) -> bool:
    if action not in SITE_ACTIONS or organization_id is None:
        return False
    clause = _clause(company_id, user_id, organization_id, action)
    # Constrain the Site within the same EXISTS, not a separate broad permission.
    clause = clause.where(EzsSite.id == site_id)
    if not db.scalar(select(clause)):
        return False
    if partner is not None:
        sites = partner.resource_scopes.get("sites")
        if sites is None or sites.mode != "SET" or str(site_id) not in sites.ids:
            return False
        location = db.scalar(select(EzsSite.location_id).where(
            EzsSite.company_id == company_id, EzsSite.id == site_id))
        if location is not None:
            objects = partner.resource_scopes.get("objects")
            if (objects is None or objects.mode == "EMPTY"
                    or (objects.mode == "SET" and location not in objects.ids)
                    or (partner.location_ids is not None and location not in partner.location_ids)):
                return False
    return True


async def native_site_allowed(db: AsyncSession, authenticated_user: User, *,
                              company_id: uuid.UUID, site_id: uuid.UUID,
                              organization_id: uuid.UUID, action: str) -> bool:
    """Additional native boundary for an already authenticated canonical User."""
    if type(authenticated_user) is not User or action not in SITE_ACTIONS:
        return False
    # populate_existing discards pending fields, even under no_autoflush.
    # Admit only a clean, persistent identity owned by the actual caller Session;
    # a delete queued before flush still has a persistent InstanceState.
    sync = db.sync_session
    state = inspect(authenticated_user)
    if (not isinstance(sync, Session) or not isinstance(state, InstanceState)
            or state.session is not sync or not state.persistent or state.modified
            or authenticated_user in sync.new or authenticated_user in sync.dirty
            or authenticated_user in sync.deleted):
        return False
    from app.auth import current_token_claims, native_user_from_claims, native_visit_from_claims
    claims = current_token_claims()
    if claims is None:
        return False
    await db.run_sync(require_schema)
    # Refresh canonical identity before its token_version/session policy check.
    with db.no_autoflush:
        await db.execute(select(User).where(User.id == authenticated_user.id)
            .execution_options(populate_existing=True))
        current = await native_user_from_claims(claims, db)
        visit_company = await native_visit_from_claims(claims, current, db)
        if current.id != authenticated_user.id or (visit_company is not None and visit_company != company_id):
            return False
        return await db.run_sync(lambda sync: _allowed(sync, company_id=company_id,
            user_id=current.id, site_id=site_id, organization_id=organization_id, action=action))


async def partner_site_allowed(db: AsyncSession, bearer: str, *, site_id: uuid.UUID,
                               organization_id: uuid.UUID, action: str) -> bool:
    """Reverify canonical identity and fresh Site SET for every decision."""
    if action not in SITE_ACTIONS:
        return False
    from app.services.partner_identity import verify_access
    def check(sync):
        with sync.no_autoflush:
            current = verify_access(sync, bearer)
            if current.is_machine or current.user_id is None:
                return False
            return _allowed(sync, company_id=current.company_id, user_id=current.user_id,
                site_id=site_id, organization_id=organization_id, action=action, partner=current)
    return await db.run_sync(check)
