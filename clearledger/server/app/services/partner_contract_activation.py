"""Private native-admin activation; one original B, no child replacement.

The nested read-only ProfileOperation owns its unchanged graph helpers. This
operation owns only activation closure, physical staging and flags/CAS/audit.
It neither authenticates a partner nor issues CREATE authority or consent.
"""
from __future__ import annotations

from copy import deepcopy
import json

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (AuditEvent, Company, CompanyRole, Counterparty,
                        Organization, ServiceLocation, User, UserCompany)
from app.models_partner import (PartnerClient, PartnerCredential, PartnerInstallation,
                                PartnerInstallationLocation)
from app.models_partner_contracts import PartnerContractCreateProfile as Profile
from app.schemas_partner import ActivateContractCreateProfile
from app.services.contract_write_locks import (
    CreateProfileKey, RoleKey, LockMode, ScopedLockError,
)
from app.services.partner_contract_profiles import (
    ProfileOperation, _PROFILE, _CHILDREN, _error,
    require_profile_admin_enabled, profile_core_user,
)


def _request(body):
    if (type(body) is not ActivateContractCreateProfile
            or set(vars(body)) != set(ActivateContractCreateProfile.model_fields)
            or body.__pydantic_extra__):
        _error(422, "Invalid activation request")
    try:
        return ActivateContractCreateProfile.model_validate(body.model_dump())
    except (ValidationError, ValueError, TypeError):
        _error(422, "Invalid activation request")


def _rows(db, statement):
    # Full SQL values include JSON scopes and Member's two canonical pointers.
    return deepcopy(tuple(tuple(row) for row in db.execute(statement)))


class ActivationOperation:
    """Exact private composition, never a ProfileOperation subclass or receipt."""
    parent_models = (Counterparty, Organization, ServiceLocation)

    def __init__(self, installation_id, body):
        self.installation_id, self.body = installation_id, body
        self.graph = ProfileOperation(installation_id, None)
        self.parents = {}
        self.writer = None

    def parent(self, db, model, ident):
        rows = _rows(db, select(*model.__table__.c).where(
            model.id == ident, model.company_id == self.company_id))
        if len(rows) != 1:
            _error(409, "Activation profile graph is invalid")
        self.parents[(model, ident)] = rows

    def discover(self, db, *, company_id, client_id, actor, get, key, company):
        self.company_id, self.client_id = company_id, client_id
        # Original discovery/snapshot/readback code remains wholly unchanged.
        def graph_key(value, mode=LockMode.SHARED):
            key(value, LockMode.EXCLUSIVE if type(value) is CreateProfileKey else mode)
        self.graph.discover(db, company_id=company_id, client_id=client_id,
            actor=actor, get=get, key=graph_key, company=company)
        if self.graph.expected[0] is None:
            _error(404, "Contract create profile not found")
        self.profile_id = self.graph.profile_id
        principals, refs, types = self.graph.expected[1]
        users = {row[3] for row in principals if row[3] is not None}
        for uid in sorted(users | {actor.id}):
            user = get(User, uid)
            member = get(UserCompany, (uid, company_id))
            if uid in users and (user is None or member is None):
                _error(409, "Activation profile graph is invalid")
            if user and user.company_id is not None:
                company(user.company_id)
                if get(Company, user.company_id) is None:
                    _error(409, "Activation profile graph is invalid")
            if member is not None:
                if member.role_id is not None:
                    # Tenant predicate BEFORE following a Role; never expand a
                    # foreign owner graph, even if the FK itself is valid.
                    role = db.scalar(select(CompanyRole).where(
                        CompanyRole.id == member.role_id, CompanyRole.company_id == company_id))
                    if role is None:
                        _error(409, "Activation profile graph is invalid")
                    key(RoleKey(company_id, role.id)); get(CompanyRole, role.id)
                for model, ident in ((Counterparty, member.organization_id),
                                     (Organization, member.own_organization_id)):
                    if ident is not None:
                        self.parent(db, model, ident)
        for model, ident in self.graph.refs:
            self.parent(db, model, ident)
        # Principal discriminants are frozen children, not arbitrary FK unions.
        if any(not ((row[2] == "user" and row[3] is not None and row[4] is None)
                    or (row[2] == "machine" and row[3] is None and row[4] is not None))
               for row in principals):
            _error(409, "Activation profile graph is invalid")

    def freeze(self, db, ordered, installation_sets, credential_sets):
        from app.services.partner_identity import RESOURCE_MODELS, _installation_sets
        self.installation_sets = deepcopy(installation_sets)
        if self.installation_id not in self.installation_sets:
            self.installation_sets[self.installation_id] = deepcopy(_installation_sets(db, self.installation_id))
        # Original references(selected=False) omits foreign/missing targets.
        # Validate the UNFILTERED canonical sets, even for all_locations,
        # ALL/EMPTY resources and false/false, before admitting the one B.
        # Use the original typed mapping; preserve native IDs literally and
        # never discover or lock a foreign target's owner/parent graph.
        descriptors = {(spec.model, spec.identity) for spec in ordered if not spec.missing}
        for locations, _scopes, items in self.installation_sets.values():
            targets = [(ServiceLocation, set(locations))]
            targets.extend((model, {row[index] for row in items if row[1] == kind})
                for index, (kind, (model, _column)) in enumerate(RESOURCE_MODELS.items(), start=2))
            for model, ids in targets:
                if not ids:
                    continue
                actual = set(db.scalars(select(model.id).where(
                    model.company_id == self.company_id, model.id.in_(ids))))
                if actual != ids or any((model, (ident,)) not in descriptors for ident in ids):
                    _error(409, "Activation profile graph is invalid")
        self.ordered = ordered
        if any(spec.missing and spec.model is not UserCompany for spec in ordered):
            _error(409, "Activation profile graph is invalid")
        self.identity_rows = tuple(_rows(db, spec.statement().with_only_columns(*spec.model.__table__.c))
                                   for spec in ordered)
        self.credential_sets = deepcopy(credential_sets)
        # Union includes canonical read resources, not just profile selection.
        for spec in ordered:
            if spec.model in self.parent_models and not spec.missing:
                self.parent(db, spec.model, spec.identity[0])
        # Discovery is complete here; no new key or parent is admitted after B.

    def recheck(self, db):
        from app.services import partner_identity as identity
        require_profile_admin_enabled()
        self.graph.recheck(db)
        for spec, expected in zip(self.ordered, self.identity_rows):
            if _rows(db, spec.statement().with_only_columns(*spec.model.__table__.c)) != expected:
                identity._writer_drift(db)
        for (model, ident), expected in self.parents.items():
            if _rows(db, select(*model.__table__.c).where(
                    model.id == ident, model.company_id == self.company_id)) != expected:
                identity._writer_drift(db)
        for iid, expected in self.installation_sets.items():
            if identity._installation_sets(db, iid) != expected:
                identity._writer_drift(db)
        for cid, expected in self.credential_sets.items():
            actual = tuple(sorted(db.scalars(select(PartnerCredential.id).where(
                PartnerCredential.client_id == cid)), key=str))
            if actual != expected:
                identity._writer_drift(db)

    def lock_parents(self):
        db, writer = self.writer.db, self.writer
        # An explicit boundary also exists for an empty Member stage.
        writer.checkpoint()
        for model in self.parent_models:
            for ident in sorted(rid for kind, rid in self.parents if kind is model):
                db.execute(select(model.id).where(model.id == ident,
                    model.company_id == self.company_id).with_for_update(read=True)).all()
                writer.checkpoint()
        writer.checkpoint()

    def lock(self):
        db, writer = self.writer.db, self.writer
        profile = db.scalar(select(Profile).where(Profile.id == self.profile_id,
            Profile.installation_id == self.installation_id, Profile.company_id == self.company_id,
            Profile.client_id == self.client_id).with_for_update()
            .execution_options(populate_existing=True))
        writer.checkpoint()
        for code in sorted(self.graph.types):
            db.execute(text("SELECT code FROM core.contract_types WHERE code=:code FOR SHARE"), {"code": code}).all()
            writer.checkpoint()
        for model, names in _CHILDREN:
            db.execute(select(*(getattr(model, name) for name in names)).where(
                model.profile_id == self.profile_id).order_by(*(getattr(model, name) for name in names))
                .with_for_update(read=True)).all()
            writer.checkpoint()
        return profile

    def validate_enable(self, db, profile):
        from app.services import partner_identity as identity
        if not (self.body.userEnabled or self.body.serviceEnabled):
            return
        if profile.revoked:
            _error(409, "Revoked contract profile cannot be enabled")
        principals, refs, types = self.graph.expected[1]
        orgs = {row[3] for row in refs if row[2] == "organization"}
        cps = {row[4] for row in refs if row[2] == "counterparty"}
        locs = {row[5] for row in refs if row[2] == "location"}
        active_types = {code for code, row in self.graph.types.items()
                        if row is not None and row[1] is True}
        install = identity.fresh(db, PartnerInstallation, self.installation_id)
        locations = None if install.all_locations else frozenset(db.scalars(select(
            PartnerInstallationLocation.location_id).where(
                PartnerInstallationLocation.installation_id == self.installation_id)))
        resources = identity.resource_scopes(db, self.installation_id, self.company_id, locations)
        def permits(scope, value):
            return scope.mode == "ALL" or (scope.mode == "SET" and value in scope.ids)
        legal_cps = {cp for cp in cps if permits(resources["counterparties"], str(cp))}
        legal_locs = {loc for loc in locs if permits(resources["objects"], loc)
                      and (locations is None or loc in locations)}
        if not orgs or not legal_cps or not legal_locs or not active_types:
            _error(409, "Nonempty legal contract selection required for activation")
        if self.body.serviceEnabled:
            client = identity.fresh(db, PartnerClient, self.client_id)
            if client.auth_method != "client_secret_basic" or not any(row[2] == "machine" for row in principals):
                _error(409, "Configured machine principal required for activation")
        if self.body.userEnabled:
            eligible = False
            for row in principals:
                if row[2] != "user":
                    continue
                member = identity.fresh(db, UserCompany, (row[3], self.company_id))
                if ((member.own_organization_id is None or member.own_organization_id in orgs)
                        and (member.object_scope is None or legal_locs & set(member.object_scope))):
                    eligible = True
            if not eligible:
                _error(409, "Configured user principal with legal selection required for activation")


def activate_partner_contract_create_profile(db, installation_id, actor, native, body):
    from app.services.partner_identity import _prepare_partner_write
    require_profile_admin_enabled()
    body = _request(body)
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Activation requires clean discovery")
    with db.no_autoflush:
        install = db.get(PartnerInstallation, installation_id, populate_existing=True)
        if install is None:
            _error(404, "Installation not found")
        operation = ActivationOperation(installation_id, body)
        writer = _prepare_partner_write(db, installation_id=installation_id,
            client_id=install.client_id, company_id=install.company_id,
            actor=actor, native=native, admin_company=install.company_id,
            mutation="contract-profile-activation", contract_profile=operation)
        profile = operation.lock()
        if profile is None:
            _error(404, "Contract create profile not found")
        if (body.expectedGeneration != profile.policy_generation
                or profile.policy_generation >= 9223372036854775807):
            _error(409, "Profile generation changed")
        operation.validate_enable(db, profile)
        writer.checkpoint()
        profile.policy_generation += 1
        profile.user_enabled, profile.service_enabled = body.userEnabled, body.serviceEnabled
        operation.graph.expected = (tuple(getattr(profile, name) for name in _PROFILE),
                                    operation.graph.expected[1])
        db.add(AuditEvent(company_id=operation.company_id, user_id=str(writer.actor.id),
            user_name=writer.actor.name, action="partner.contract_profile.activation",
            details=json.dumps({"profileId": str(profile.id), "generation": profile.policy_generation,
                                "userEnabled": profile.user_enabled,
                                "serviceEnabled": profile.service_enabled}, sort_keys=True)))
    db.flush()  # Actual flags+audit SQL; retain the original root/capability.
    writer.checkpoint()
    result = operation.graph.readback(profile)
    writer.checkpoint()
    return result


async def activation_admin_request(db: AsyncSession, installation_id, credentials, body):
    """Whole-root ownership; an unknown commit ACK remains an error, not retry."""
    from app.services.partner_identity import _native_authority
    try:
        require_profile_admin_enabled()
        actor = await profile_core_user(db, credentials)
        native = _native_authority(db, credentials, actor)
        result = await db.run_sync(activate_partner_contract_create_profile,
                                  installation_id, actor, native, body)
        await db.commit()
        return result
    except BaseException:
        await db.rollback()
        raise
