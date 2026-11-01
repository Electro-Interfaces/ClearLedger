"""Internal SQL CREATE issuer. No HTTP admission, activation or transaction end.

Only the exact registered admission carries SQL evidence; it is distinct from
the current CREATE policy, which is evaluated again on every use. Existing B
capability lifetime rejects ended/nested/borrowed-again/multibind DB roots.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import weakref

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import await_only

from app.models import (CompanyRole, Contract, ContractLocation, Counterparty,
                        Organization, ServiceLocation, User, UserCompany)
from app.models_partner import PartnerClient, PartnerCredential, PartnerGrant
from app.models_partner_contracts import (
    PartnerContractCreateProfile as Profile,
    PartnerContractSuccessIntent as Intent, PartnerContractIntentLocation as IntentLocation,
)
from app.product_api.contract_create_body import (
    ContractCreateBody, _revalidate, canonical_contract_create_bytes, contract_create_hash,
)
from app.services import partner_identity as identity
from app.services.contract_write_locks import (
    CreateProfileKey, RefCompositeKey, TypeCatalogKey, UserKey, MemberKey, RoleKey,
    LockMode, ScopedLockError, require_scoped_locks,
)
from app.services.partner_contract_profiles import _PROFILE, _CHILDREN
from app.services.reference_identity import lock_manual_creation

WRITE_SCOPE = "contracts:create"
OPERATION = "createContract"


def _deny():
    raise HTTPException(403, "Contract CREATE is not permitted", headers=identity.NO_STORE)


def _rows(db, statement):
    # Freeze mutable JSON too: ORM retention or caller mutations are not SQL.
    return deepcopy(tuple(tuple(row) for row in db.execute(statement)))


def _location_rows(rows):
    # Exact full-row ordering on BOTH SQL and expected snapshots. Python keeps
    # opaque strings and duplicate rows intact, independent of DB collation.
    return tuple(sorted(rows))


def _one(db, model, ident):
    return _rows(db, select(*model.__table__.c).where(model.id == ident))


def _permits(scope, identifier):
    # UUID-valued resource scopes are canonical strings at the existing verifier
    # boundary. Opaque location IDs are never parsed, stripped or case-folded.
    return scope is not None and (scope.mode == "ALL" or (
        scope.mode == "SET" and identifier in scope.ids))


class CreateOperation:
    """Private whole-graph snapshot extension of the ONE identity composer."""
    def __init__(self, async_db, bearer, body, verified):
        self.async_db, self.bearer, self.body, self.verified = async_db, bearer, body, verified
        self.installation_id = verified.installation_id
        self.company_id, self.client_id = verified.company_id, verified.client_id
        self.body_bytes = canonical_contract_create_bytes(body)
        self.request_hash = contract_create_hash(body)
        self.namespace = (verified.company_id, verified.app_id, verified.installation_id,
                          OPERATION, body.creationKey)
        self.writer = None
        self.guards = {}
        self.own_contract_id = None
        self.own_intent_id = None
        self.own_locations = ()

    def intent_statement(self):
        return select(Intent).where(*(getattr(Intent, name) == value for name, value in zip(
            ("company_id", "app_id", "installation_id", "operation", "creation_key"), self.namespace)))

    def profile_snapshot(self, db):
        parent = _rows(db, select(*(getattr(Profile, n) for n in _PROFILE)).where(
            Profile.installation_id == self.installation_id))
        children = tuple(_rows(db, select(*(getattr(model, n) for n in names)).where(
            model.profile_id == self.profile_id).order_by(*(getattr(model, n) for n in names)))
            for model, names in _CHILDREN)
        return parent, children

    def receipt_snapshot(self, db):
        intents = _rows(db, self.intent_statement().with_only_columns(*Intent.__table__.c))
        iid = self.own_intent_id or (self.previous.id if self.previous else None)
        children = _rows(db, select(IntentLocation.intent_id, IntentLocation.location_id).where(
            IntentLocation.intent_id == iid).order_by(IntentLocation.location_id)) if iid else ()
        return intents, _location_rows(children)

    def guard(self, db, model, ident):
        frozen = _one(db, model, ident)
        if len(frozen) != 1 or frozen[0][list(model.__table__.c.keys()).index("company_id")] != self.company_id:
            _deny()
        self.guards[(model, ident)] = frozen

    def discover(self, db, *, company_id, client_id, actor, get, key, company):
        if (company_id, client_id, actor) != (self.company_id, self.client_id, None):
            raise ScopedLockError("CREATE identity composition changed")
        profile = db.scalar(select(Profile).where(Profile.installation_id == self.installation_id)
                            .execution_options(populate_existing=True))
        if profile is None or (profile.company_id, profile.client_id) != (company_id, client_id):
            _deny()
        self.profile_id = profile.id
        self.expected_profile = self.profile_snapshot(db)
        key(CreateProfileKey(self.profile_id)); key(RefCompositeKey(company_id))
        principals, refs, types = self.expected_profile[1]
        for uid in sorted({r[3] for r in principals if r[3] is not None}
                          | ({self.verified.user_id} if self.verified.user_id else set())):
            key(UserKey(uid)); key(MemberKey(company_id, uid))
            user = get(User, uid)
            member = get(UserCompany, (uid, company_id))
            if user and user.company_id is not None:
                company(user.company_id)
            if member and member.role_id is not None:
                key(RoleKey(company_id, member.role_id))
                role = get(CompanyRole, member.role_id)
                if role is None or role.company_id != company_id:
                    _deny()
        for gid in sorted({r[4] for r in principals if r[4] is not None}):
            row = get(PartnerGrant, gid)
            # Cleanup's policy is untouched; CREATE itself needs exact machine
            # principal binding. Never follow another installation/client graph.
            if row is None or (row.company_id, row.client_id, row.installation_id,
                               row.kind, row.user_id) != (company_id, client_id,
                                                        self.installation_id, "machine", None):
                _deny()
        self.previous = db.scalar(self.intent_statement().execution_options(populate_existing=True))
        self.previous_locations = ()
        if self.previous:
            old = self.previous
            if (old.client_id != client_id or old.original_grant_id != self.verified.grant_id
                    or old.create_profile_id != self.profile_id
                    or old.actor_kind != ("machine" if self.verified.is_machine else "user")
                    or old.actor_key != (client_id if self.verified.is_machine else str(self.verified.user_id))
                    or old.current_user_id != self.verified.user_id
                    or old.current_contract_id != old.newborn_id or not old.succeeded):
                _deny()
            self.guard(db, Contract, old.newborn_id)
            self.previous_locations = tuple(db.scalars(select(IntentLocation.location_id).where(
                IntentLocation.intent_id == old.id).order_by(IntentLocation.location_id)))
            self.previous_card_locations = _rows(db, select(*ContractLocation.__table__.c).where(
                ContractLocation.contract_id == old.newborn_id).order_by(ContractLocation.id))
            card = db.get(Contract, old.newborn_id, populate_existing=True)
            if (card.organization_id, card.counterparty_id, card.type_code) != (
                    old.created_organization_id, old.created_counterparty_id, old.created_type_code):
                _deny()
            locations = tuple(db.scalars(select(ContractLocation.location_id).where(
                ContractLocation.contract_id == old.newborn_id, ContractLocation.company_id == company_id)))
            if not locations or set(locations) != set(self.previous_locations) or len(set(locations)) != len(locations):
                _deny()
        ref_specs = ((Organization, 3, {self.body.organizationId}),
                     (Counterparty, 4, {self.body.counterpartyId}),
                     (ServiceLocation, 5, set(self.body.coverage.locationIds)))
        for model, offset, requested in ref_specs:
            requested |= {r[offset] for r in refs if r[offset] is not None}
            if self.previous:
                requested |= ({self.previous.created_organization_id} if model is Organization else
                              {self.previous.created_counterparty_id} if model is Counterparty else
                              set(self.previous_locations))
            for rid in sorted(requested):
                self.guard(db, model, rid)
        codes = {r[1] for r in types} | {self.body.typeCode}
        if self.previous:
            codes.add(self.previous.created_type_code)
        self.types = {}
        for code in sorted(codes):
            key(TypeCatalogKey(code))
            self.types[code] = _rows(db, text(
                "SELECT code,is_active FROM core.contract_types WHERE code=:code").bindparams(code=code))
        self.expected_receipt = self.receipt_snapshot(db)
        self.policy(db, self.verified)

    def freeze(self, db, ordered, installation_sets, credential_sets):
        self.ordered = ordered
        self.identity_rows = tuple(_rows(db, spec.statement().with_only_columns(*spec.model.__table__.c))
                                   for spec in ordered)
        self.installation_sets = deepcopy(installation_sets)
        self.credential_sets = deepcopy(credential_sets)

    def after_b(self, writer):
        if writer.db is not self.async_db.sync_session:
            raise ScopedLockError("Actual AsyncSession required")
        for entity in ("counterparty", "contract"):
            await_only(lock_manual_creation(self.async_db, self.company_id, entity))
            writer.checkpoint()

    def policy(self, db, current):
        if WRITE_SCOPE not in current.scopes:
            _deny()
        profile_rows, (principals, refs, types) = self.expected_profile
        profile = dict(zip(_PROFILE, profile_rows[0]))
        if profile["revoked"] or profile["policy_generation"] <= 0:
            _deny()
        if current.is_machine:
            grant = identity.fresh(db, PartnerGrant, current.grant_id)
            client = identity.fresh(db, PartnerClient, current.client_id)
            if (not profile["service_enabled"] or grant.kind != "machine" or grant.user_id is not None
                    or client.auth_method != "client_secret_basic"
                    or not any(r[2:] == ("machine", None, grant.id) for r in principals)):
                _deny()
        elif (not profile["user_enabled"] or current.user_id is None
              or not any(r[2:] == ("user", current.user_id, None) for r in principals)):
            _deny()
        orgs = {r[3] for r in refs if r[2] == "organization"}
        cps = {r[4] for r in refs if r[2] == "counterparty"}
        locs = {r[5] for r in refs if r[2] == "location"}
        allowed_types = {r[1] for r in types}
        requests = [(self.body.organizationId, self.body.counterpartyId,
                     self.body.typeCode, self.body.coverage.locationIds)]
        if self.previous:
            requests.append((self.previous.created_organization_id, self.previous.created_counterparty_id,
                             self.previous.created_type_code, self.previous_locations))
        member = identity.fresh(db, UserCompany, (current.user_id, self.company_id)) if current.user_id else None
        for org, cp, code, locations in requests:
            if (org not in orgs or cp not in cps or not locations or code not in allowed_types
                    or self.types.get(code) != ((code, True),)
                    or (current.own_organization_id is not None and current.own_organization_id != org)
                    or not _permits(current.resource_scopes.get("counterparties"), str(cp))):
                _deny()
            for loc in locations:
                if (loc not in locs or not _permits(current.resource_scopes.get("objects"), loc)
                        or (current.location_ids is not None and loc not in current.location_ids)
                        or (member is not None and member.object_scope is not None and loc not in member.object_scope)):
                    _deny()
        # contracts read resources intentionally do not confer CREATE or veto a
        # newborn's own immutable intent receipt. verify_access still validates
        # every existing canonical resource profile, including EMPTY/SET/ALL.

    def recheck(self, db):
        if self.profile_snapshot(db) != self.expected_profile or self.receipt_snapshot(db) != self.expected_receipt:
            identity._writer_drift(db)
        for spec, expected in zip(self.ordered, self.identity_rows):
            if _rows(db, spec.statement().with_only_columns(*spec.model.__table__.c)) != expected:
                identity._writer_drift(db)
        for iid, expected in self.installation_sets.items():
            if identity._installation_sets(db, iid) != expected:
                identity._writer_drift(db)
        for cid, expected in self.credential_sets.items():
            if tuple(sorted(db.scalars(select(PartnerCredential.id).where(
                    PartnerCredential.client_id == cid)), key=str)) != expected:
                identity._writer_drift(db)
        for (model, ident), expected in self.guards.items():
            if _one(db, model, ident) != expected:
                identity._writer_drift(db)
        for code, expected in self.types.items():
            if _rows(db, text("SELECT code,is_active FROM core.contract_types WHERE code=:code").bindparams(code=code)) != expected:
                identity._writer_drift(db)
        if self.previous and _rows(db, select(*ContractLocation.__table__.c).where(
                ContractLocation.contract_id == self.previous.newborn_id).order_by(ContractLocation.id)) != self.previous_card_locations:
            identity._writer_drift(db)
        if self.own_contract_id:
            if _one(db, Contract, self.own_contract_id) != self.own_card:
                identity._writer_drift(db)
            if _location_rows(_rows(db, select(ContractLocation.company_id, ContractLocation.location_id).where(
                    ContractLocation.contract_id == self.own_contract_id)
                    .order_by(ContractLocation.location_id, ContractLocation.id))) != self.own_locations:
                identity._writer_drift(db)
        current = identity.verify_locked_partner_access(db, self.bearer,
            capability=self.writer.capability, expected=self.verified)
        self.policy(db, current)

    def lock(self):
        db, writer = self.writer.db, self.writer
        db.execute(select(Profile.id).where(Profile.id == self.profile_id,
            Profile.installation_id == self.installation_id, Profile.company_id == self.company_id,
            Profile.client_id == self.client_id).with_for_update(read=True)).all()
        writer.checkpoint()
        for model in (Counterparty, Organization, ServiceLocation, Contract):
            for rid in sorted(rid for kind, rid in self.guards if kind is model):
                db.execute(select(model.id).where(model.id == rid, model.company_id == self.company_id)
                           .with_for_update(read=True)).all()
                writer.checkpoint()
        for code in sorted(self.types):
            db.execute(text("SELECT code FROM core.contract_types WHERE code=:code FOR SHARE"), {"code": code}).all()
            writer.checkpoint()
        for model, names in _CHILDREN:
            db.execute(select(*(getattr(model, n) for n in names)).where(model.profile_id == self.profile_id)
                       .order_by(*(getattr(model, n) for n in names)).with_for_update(read=True)).all()
            writer.checkpoint()
        if self.previous:
            db.execute(self.intent_statement().with_for_update(read=True)).all()
            writer.checkpoint()
            db.execute(select(IntentLocation).where(IntentLocation.intent_id == self.previous.id)
                       .order_by(IntentLocation.location_id).with_for_update(read=True)).all()
            writer.checkpoint()
            db.execute(select(ContractLocation).where(ContractLocation.company_id == self.company_id,
                ContractLocation.contract_id == self.previous.newborn_id).order_by(ContractLocation.id)
                .with_for_update(read=True)).all()
            writer.checkpoint()


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class _SQLStamp:
    """No public constructor can register an issued instance."""
    generation: int


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class CreateAdmission:
    """Opaque internal handle, not a portable token, ACL or caller binding."""
    _stamp: _SQLStamp


@dataclass
class _Issued:
    admission: weakref.ReferenceType
    session: weakref.ReferenceType
    root: weakref.ReferenceType
    connection: weakref.ReferenceType
    capability: object
    generation: int
    body_bytes: bytes
    namespace: tuple
    operation: CreateOperation


_ISSUED = weakref.WeakKeyDictionary()


def _prepare(db, async_db, bearer, body):
    if db is not async_db.sync_session or db.new or db.dirty or db.deleted:
        raise ScopedLockError("CREATE requires clean actual Session")
    with db.no_autoflush:
        verified = identity.verify_access(db, bearer)
        operation = CreateOperation(async_db, bearer, body, verified)
        writer = identity._prepare_partner_write(db, token_id=verified.token_id,
            client_id=verified.client_id, installation_id=verified.installation_id,
            company_id=verified.company_id, mutation="contract-create", contract_profile=operation)
        operation.lock()
        writer.checkpoint()
        generation = operation.expected_profile[0][0][_PROFILE.index("policy_generation")]
        stamp = _SQLStamp(generation)
        admission = CreateAdmission(stamp)
        _ISSUED[stamp] = _Issued(weakref.ref(admission), weakref.ref(db),
            weakref.ref(db.get_transaction()), weakref.ref(db.connection()), writer.capability,
            generation, operation.body_bytes, operation.namespace, operation)
        return admission


async def prepare_create(db: AsyncSession, bearer: str, body: ContractCreateBody) -> CreateAdmission:
    try:
        if not isinstance(db, AsyncSession) or type(bearer) is not str or len(bearer) > 8192:
            raise ScopedLockError("Actual session and bounded bearer required")
        checked = _revalidate(body)
        return await db.run_sync(_prepare, db, bearer, checked)
    except BaseException:
        await db.rollback()
        raise


def _require(db, admission, body):
    issued = _ISSUED.get(admission._stamp) if type(admission) is CreateAdmission else None
    if (issued is None or issued.admission() is not admission or issued.session() is not db
            or issued.root() is not db.get_transaction()
            or issued.generation != admission._stamp.generation
            or canonical_contract_create_bytes(body) != issued.body_bytes
            or body.creationKey != issued.namespace[-1]):
        if issued is not None:
            _ISSUED.pop(admission._stamp, None)
        raise ScopedLockError("Exact current SQL-issued CREATE admission required")
    try:
        require_scoped_locks(db, issued.capability, issued.capability.plan.requests)
        if issued.connection() is not db.connection():
            raise ScopedLockError("CREATE Connection changed")
        issued.operation.writer.checkpoint()
    except BaseException:
        _ISSUED.pop(admission._stamp, None)
        raise
    return issued.operation


async def require_create(db: AsyncSession, admission: CreateAdmission, body: ContractCreateBody) -> None:
    try:
        await db.run_sync(_require, admission, body)
    except BaseException:
        await db.rollback()
        raise
