"""Closed CREATE-profile administration, not partner CREATE authority.

One original identity B entrance, actual native policy, profile CAS and coherent
readback. No OAuth scope issuance, success receipt, native card write or notify.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (decode_token, native_user_from_claims,
                      native_visit_from_claims, native_claims_context)
from app.models import AuditEvent, Counterparty, Organization, ServiceLocation, User, UserCompany
from app.models_partner import PartnerGrant, PartnerInstallation
from app.models_partner_contracts import (
    PartnerContractCreateProfile as Profile,
    PartnerContractCreatePrincipal as Principal,
    PartnerContractCreateRef as Ref,
    PartnerContractCreateType as Type,
)
from app.schemas_partner import ReplaceContractCreateProfile, ContractCreateProfileReadback
from app.services.contract_write_locks import (
    CreateProfileKey, RefCompositeKey, TypeCatalogKey, UserKey, MemberKey,
    LockMode, ScopedLockError,
)

_PROFILE = ("id", "installation_id", "client_id", "company_id", "user_enabled",
            "service_enabled", "revoked", "policy_generation")
_CHILDREN = ((Principal, ("id", "profile_id", "actor_kind", "user_id", "machine_grant_id")),
             (Ref, ("id", "profile_id", "kind", "organization_id", "counterparty_id", "location_id")),
             (Type, ("profile_id", "type_code")))
_REFS = ((Counterparty, "counterpartyIds", "counterparty_id"),
         (Organization, "organizationIds", "organization_id"),
         (ServiceLocation, "locationIds", "location_id"))


def _error(status, detail):
    from app.services.partner_identity import NO_STORE
    raise HTTPException(status, detail, headers=NO_STORE)


def require_profile_admin_enabled():
    from app.services.partner_identity import settings
    if settings.partner_contract_create_admin_enabled is not True:
        _error(503, "Contract profile administration is disabled")


async def profile_core_user(db: AsyncSession, credentials):
    """Actual public native auth, without get_current_user/presence/commit."""
    from app.services.partner_identity import require_core_user
    if credentials is None:
        _error(401, "Core Bearer credentials required")
    with db.no_autoflush:
        claims = decode_token(credentials.credentials)
        user = await native_user_from_claims(claims, db)
        visit = await native_visit_from_claims(claims, user, db)
        with native_claims_context(claims, visit):
            await require_core_user(user)
        return user


def _tuples(rows):
    return tuple(sorted((tuple(row) for row in rows), key=lambda row: tuple(map(str, row))))


class ProfileOperation:
    """Private composition state, never a caller-provided authorization receipt.

    The public policy and original B issuer remain in partner_identity. This
    state freezes only the profile-specific graph and checks its current SQL
    contents on that same root, including whole child sets and missing parents.
    """
    def __init__(self, installation_id, body):
        self.installation_id, self.body = installation_id, body
        self.write = body is not None
        self.profile_id = uuid4()  # Original absent-profile candidate, BEFORE B.
        self.expected = None
        self.homes, self.refs, self.types = {}, {}, {}

    def snapshot(self, db):
        profile = db.execute(select(*(getattr(Profile, n) for n in _PROFILE)).where(
            Profile.installation_id == self.installation_id)).one_or_none()
        children = tuple(_tuples(db.execute(select(*(getattr(model, n) for n in names)).where(
            model.profile_id == self.profile_id))) for model, names in _CHILDREN)
        return (tuple(profile) if profile else None, children)

    def discover(self, db, *, company_id, client_id, actor, get, key, company):
        self.company_id, self.client_id = company_id, client_id
        installation = db.execute(select(PartnerInstallation.company_id, PartnerInstallation.client_id)
            .where(PartnerInstallation.id == self.installation_id)).one_or_none()
        if installation is None or tuple(installation) != (company_id, client_id):
            self.drift(db)
        original = db.execute(select(*(getattr(Profile, n) for n in _PROFILE)).where(
            Profile.installation_id == self.installation_id)).one_or_none()
        if original:
            if original.company_id != company_id or original.client_id != client_id:
                self.drift(db)
            self.profile_id = original.id
        self.expected = self.snapshot(db)
        key(CreateProfileKey(self.profile_id), LockMode.EXCLUSIVE if self.write else LockMode.SHARED)
        key(RefCompositeKey(company_id))
        principal_rows, ref_rows, type_rows = self.expected[1]
        users = {r[3] for r in principal_rows if r[3] is not None}
        grants = {r[4] for r in principal_rows if r[4] is not None}
        users |= set(self.body.userIds) if self.write else set()
        grants |= set(self.body.machineGrantIds) if self.write else set()
        for uid in sorted(users | {actor.id}):
            key(UserKey(uid)); key(MemberKey(company_id, uid))
            user = get(User, uid)
            get(UserCompany, (uid, company_id))
            home = (user.company_id,) if user else None
            self.homes[uid] = home
            if user and user.company_id is not None:
                company(user.company_id)
        for gid in sorted(grants):
            # Do not follow or lock a new foreign graph discovered through a
            # malicious FK. Matching machine identity is needed, NOT live_grant.
            grant = db.scalar(select(PartnerGrant).where(
                PartnerGrant.id == gid, PartnerGrant.company_id == company_id,
                PartnerGrant.installation_id == self.installation_id,
                PartnerGrant.client_id == client_id, PartnerGrant.kind == "machine",
                PartnerGrant.user_id.is_(None)).execution_options(populate_existing=True))
            if grant is None:
                _error(422, "Invalid machine grant binding")
            get(PartnerGrant, gid)
        for model, name, column in _REFS:
            index = {"organization_id": 3, "counterparty_id": 4, "location_id": 5}[column]
            ids = {r[index] for r in ref_rows if r[index] is not None}
            ids |= set(getattr(self.body, name)) if self.write else set()
            for rid in sorted(ids):
                exists = db.scalar(select(model.id).where(model.id == rid, model.company_id == company_id)) is not None
                if not exists:
                    _error(422, "Invalid company reference")
                self.refs[(model, rid)] = exists
        codes = {r[1] for r in type_rows}
        self.added_codes = set(self.body.typeCodes) - codes if self.write else set()
        codes |= set(self.body.typeCodes) if self.write else set()
        for code in sorted(codes):
            key(TypeCatalogKey(code))
            row = db.execute(text("SELECT code, is_active FROM core.contract_types WHERE code=:code"),
                             {"code": code}).one_or_none()
            self.types[code] = tuple(row) if row else None

    @staticmethod
    def drift(db):
        from app.services.partner_identity import _writer_drift
        _writer_drift(db)

    def recheck(self, db):
        if self.snapshot(db) != self.expected:
            self.drift(db)
        for uid, home in self.homes.items():
            row = db.execute(select(User.company_id).where(User.id == uid)).one_or_none()
            if (tuple(row) if row else None) != home:
                self.drift(db)
        for (model, rid), expected in self.refs.items():
            actual = db.scalar(select(model.id).where(model.id == rid, model.company_id == self.company_id)) is not None
            if actual != expected:
                self.drift(db)
        for code, expected in self.types.items():
            row = db.execute(text("SELECT code, is_active FROM core.contract_types WHERE code=:code"), {"code": code}).one_or_none()
            if (tuple(row) if row else None) != expected:
                self.drift(db)

    def lock(self, writer):
        db = writer.db
        writer.checkpoint()  # Current native authority after all B/identity waits.
        profile = db.scalar(select(Profile).where(Profile.id == self.profile_id,
            Profile.installation_id == self.installation_id, Profile.company_id == self.company_id,
            Profile.client_id == self.client_id).with_for_update(read=not self.write)
            .execution_options(populate_existing=True))
        writer.checkpoint()
        for model, _, _ in _REFS:
            for rid in sorted(rid for (kind, rid) in self.refs if kind is model):
                db.scalar(select(model).where(model.id == rid, model.company_id == self.company_id)
                    .with_for_update(read=True).execution_options(populate_existing=True))
                writer.checkpoint()
        for code in sorted(self.types):
            db.execute(text("SELECT code FROM core.contract_types WHERE code=:code FOR SHARE"), {"code": code}).all()
            writer.checkpoint()
        # All FK parent rows precede child locks, avoiding cascade inversions.
        for model, names in _CHILDREN:
            db.execute(select(*(getattr(model, n) for n in names)).where(
                model.profile_id == self.profile_id).order_by(*(getattr(model, n) for n in names))
                .with_for_update(read=not self.write)).all()
            writer.checkpoint()
        return profile

    def validate_new_selection(self, db):
        if not self.write:
            return
        for uid in self.body.userIds:
            if (self.homes.get(uid) is None or db.get(UserCompany, (uid, self.company_id)) is None):
                _error(422, "Current company member required")
        for code in self.added_codes:
            if self.types[code] is None or self.types[code][1] is not True:
                _error(422, "Active contract type required when adding a code")

    def readback(self, profile):
        _, (principals, refs, types) = self.expected
        return ContractCreateProfileReadback(
            profileId=profile.id, installationId=profile.installation_id,
            clientId=profile.client_id, companyId=profile.company_id,
            policyGeneration=profile.policy_generation, userEnabled=profile.user_enabled,
            serviceEnabled=profile.service_enabled, revoked=profile.revoked,
            userIds=tuple(sorted(r[3] for r in principals if r[3] is not None)),
            machineGrantIds=tuple(sorted(r[4] for r in principals if r[4] is not None)),
            organizationIds=tuple(sorted(r[3] for r in refs if r[3] is not None)),
            counterpartyIds=tuple(sorted(r[4] for r in refs if r[4] is not None)),
            locationIds=tuple(sorted(r[5] for r in refs if r[5] is not None)),
            typeCodes=tuple(sorted(r[1] for r in types)))


def _prepare(db, installation_id, actor, native, body):
    from app.services.partner_identity import _prepare_partner_write
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Profile administration requires clean discovery")
    install = db.get(PartnerInstallation, installation_id, populate_existing=True)
    if install is None:
        _error(404, "Installation not found")
    operation = ProfileOperation(installation_id, body)
    writer = _prepare_partner_write(db, installation_id=installation_id,
        client_id=install.client_id, company_id=install.company_id,
        actor=actor, native=native, admin_company=install.company_id,
        mutation="contract-profile-write" if body is not None else "contract-profile-read",
        contract_profile=operation)
    profile = operation.lock(writer)
    operation.validate_new_selection(db)
    writer.checkpoint()
    return writer, operation, profile


def read_partner_contract_create_profile(db, installation_id, actor, native):
    require_profile_admin_enabled()
    writer, operation, profile = _prepare(db, installation_id, actor, native, None)
    if profile is None:
        _error(404, "Contract create profile not found")
    result = operation.readback(profile)
    writer.checkpoint()
    return result


def replace_partner_contract_create_profile(db, installation_id, actor, native, body):
    require_profile_admin_enabled()
    if type(body) is not ReplaceContractCreateProfile:
        _error(422, "Invalid profile request")
    # Revalidate forged model_construct/copy instances as well as ordinary DTOs.
    if (set(vars(body)) != set(ReplaceContractCreateProfile.model_fields)
            or body.__pydantic_extra__):
        _error(422, "Invalid profile request")
    try:
        body = ReplaceContractCreateProfile.model_validate(body.model_dump())
    except (ValidationError, ValueError, TypeError):
        _error(422, "Invalid profile request")
    writer, operation, profile = _prepare(db, installation_id, actor, native, body)
    if profile is None:
        if body.expectedGeneration is not None:
            _error(409, "Profile generation changed")
        profile = Profile(id=operation.profile_id, installation_id=installation_id,
            client_id=operation.client_id, company_id=operation.company_id,
            user_enabled=False, service_enabled=False, revoked=body.revoked, policy_generation=1)
    else:
        if (body.expectedGeneration != profile.policy_generation or
                profile.policy_generation >= 9223372036854775807):
            _error(409, "Profile generation changed")
    # Explicit DELETEs precede inserts with the same unique business keys.
    for index, (model, names) in enumerate(_CHILDREN):
        db.execute(delete(model).where(model.profile_id == operation.profile_id),
                   execution_options={"synchronize_session": False})
        children = list(operation.expected[1]); children[index] = ()
        operation.expected = (operation.expected[0], tuple(children))
        writer.checkpoint()
    if operation.expected[0] is not None:
        profile.policy_generation += 1
    profile.user_enabled = profile.service_enabled = False
    profile.revoked = body.revoked
    db.add(profile)
    # Models intentionally have no ORM relationships. Establish the FK parent
    # explicitly before child INSERTs, retaining the SAME root and atomicity.
    operation.expected = (tuple(getattr(profile, n) for n in _PROFILE), operation.expected[1])
    db.flush()
    writer.checkpoint()  # Current native authority after the parent FK wait.
    # Explicit IDs keep the expected SQL snapshot independent from DB output.
    principals = [Principal(id=uuid4(), profile_id=profile.id, actor_kind="user", user_id=uid)
                  for uid in body.userIds]
    principals += [Principal(id=uuid4(), profile_id=profile.id, actor_kind="machine", machine_grant_id=gid)
                   for gid in body.machineGrantIds]
    refs = []
    for model, name, column in _REFS:
        for rid in getattr(body, name):
            refs.append(Ref(id=uuid4(), profile_id=profile.id,
                kind={"organization_id": "organization", "counterparty_id": "counterparty", "location_id": "location"}[column], **{column: rid}))
    types = [Type(profile_id=profile.id, type_code=code) for code in body.typeCodes]
    db.add_all(principals + refs + types)
    operation.expected = (tuple(getattr(profile, n) for n in _PROFILE), tuple(
        _tuples(tuple(getattr(row, n) for n in names) for row in rows)
        for (model, names), rows in zip(_CHILDREN, (principals, refs, types))))
    audit = AuditEvent(company_id=operation.company_id, user_id=str(writer.actor.id),
        user_name=writer.actor.name, action="partner.contract_profile.replace",
        details=json.dumps({"profileId": str(profile.id), "generation": profile.policy_generation,
                            "revoked": profile.revoked}, sort_keys=True))
    db.add(audit)
    db.flush()  # Profile, children and audit use this actual root; NO COMMIT here.
    writer.checkpoint()  # Every unique/FK/flush wait has finished; recheck public auth.
    result = operation.readback(profile)
    writer.checkpoint()
    return result


async def profile_admin_request(db: AsyncSession, installation_id: UUID, credentials, body=None):
    """Own root completion/rollback; cancellation and unknown commit propagate."""
    from app.services.partner_identity import _native_authority
    try:
        require_profile_admin_enabled()
        actor = await profile_core_user(db, credentials)
        native = _native_authority(db, credentials, actor)
        function = read_partner_contract_create_profile if body is None else replace_partner_contract_create_profile
        args = (installation_id, actor, native) + (() if body is None else (body,))
        result = await db.run_sync(function, *args)
        if body is not None:
            await db.commit()
        else:
            await db.rollback()  # GET has no DML; release its SHARE snapshot locks.
        return result
    except BaseException:
        await db.rollback()
        raise  # A commit transport failure still has UNKNOWN outcome.
