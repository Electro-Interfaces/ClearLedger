"""Native register's single entrance and pending-safe completion boundary.

Scalar discovery precedes every wait. The caller owns the root, error order,
numbering, DML and completion; this module never commits or retries a root.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import UUID
import weakref

from fastapi import HTTPException
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.auth import (assert_company_product, current_token_claims,
                      native_user_from_claims, native_visit_from_claims)
from app.models import (Company, CompanyRole, Counterparty, DocAccessGrant,
                        Department, DocAcquaint, DocApproval, DocCard, DocCase, DocKind,
                        EventSubscription, Organization, PartnerSpace, User,
                        UserCompany, UserSubstitution)
from app.scope import current_organization, set_request_organization
from app.services.contract_write_locks import (
    CompanyKey, LockMode, LockPlan, LockRequest, MemberKey, RefCompositeKey,
    RoleKey, ScopedLockCapability, ScopedLockError, UserKey,
    acquire_scoped_locks_async, require_scoped_locks,
)
from app.services.doc_case_locks import acquire_case_catalog
from app.services.native_doc_create_locks import discover_doc_uuid
from app.utils import resolve_company_id

S, X = LockMode.SHARED, LockMode.EXCLUSIVE
_CARD_USERS = ("author_id", "responsible_id", "signatory_id", "registered_by",
               "archive_accepted_by")
_CARD_POINTERS = ("company_id", "kind_id", *_CARD_USERS, "organization_id",
                  "counterparty_id", "case_id", "department_id", "object_id")
_OWN_CARD = frozenset(("organization_id", "reg_number", "reg_date", "verify_token",
    "registered_by", "number_manual", "status", "approval_status", "case_id",
    "storage_until", "retention_class", "retention_snapshot", "updated_at"))


def changed():
    raise HTTPException(409, "Данные изменились одновременно; повторите запрос")


def _clean(db):
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Native register requires clean entry; roll back entire root")


async def _one(db, model, uid, *names):
    return (await db.execute(select(*(getattr(model, n) for n in names)).where(
        model.id == uid))).one_or_none()


async def _members(db, cid, aid):
    return (await db.execute(select(UserCompany.role_id, UserCompany.role,
        UserCompany.department_id, UserCompany.own_organization_id,
        UserCompany.organization_id, UserCompany.modules, UserCompany.object_scope).where(
        UserCompany.company_id == cid, UserCompany.user_id == aid))).one_or_none()


async def _children(db, model, did):
    names = (("id", "company_id", "assignee_id", "decided_by") if model is DocApproval
             else ("id", "company_id", "user_id", "created_by"))
    return tuple((await db.execute(select(*(getattr(model, n) for n in names)).where(
        model.doc_id == did).order_by(model.id))).all())


async def _substitutions(db, cid, aid):
    # Future/expired candidates belong to B too; native policy recomputes dates.
    return tuple((await db.execute(select(UserSubstitution.id,
        UserSubstitution.company_id, UserSubstitution.user_id,
        UserSubstitution.deputy_id, UserSubstitution.created_by).where(
        UserSubstitution.company_id == cid, UserSubstitution.deputy_id == aid)
        .order_by(UserSubstitution.id))).all())


async def _subscriptions(db, cid):
    return tuple((await db.execute(select(EventSubscription.id,
        EventSubscription.company_id).where(EventSubscription.company_id == cid,
        EventSubscription.enabled.is_(True), EventSubscription.event_types.any(
            "doc.registered")).order_by(EventSubscription.id))).all())


@dataclass(frozen=True)
class RegisterParents:
    company_id: UUID
    actor_id: UUID
    company_ref: str
    selector: UUID | None
    claims: dict | None
    users: dict
    member: tuple | None
    roles: dict
    parents: dict
    companies: tuple
    visit: tuple | None
    plan: LockPlan
    capability: ScopedLockCapability
    actor: User
    doc_id: UUID | None = None
    card_pointer: tuple | None = None
    kind: tuple | None = None
    cases: dict = field(default_factory=dict)
    inference: tuple = ()
    children: dict = field(default_factory=dict)
    substitutions: tuple = ()
    subscriptions: tuple = ()
    baseline: dict | None = None
    writer_pointer: tuple | None = None
    extra_members: dict = field(default_factory=dict)
    epoch_kind: tuple | None = None
    epoch_kind_id: UUID | None = None

    def __post_init__(self):
        for name in ("users", "roles", "parents", "cases", "children", "extra_members"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def require(self, db):
        if self.plan is not self.capability.plan:
            raise ScopedLockError("Register plan changed")
        require_scoped_locks(db.sync_session, self.capability, self.plan.requests)
        state = inspect(self.actor)
        if state.session is not db.sync_session or state.identity != (self.actor_id,):
            raise ScopedLockError("Register actor/session changed")


async def _refresh_clean(db, model, statement):
    # populate_existing discards history. Never use it on pending policy state.
    for obj in db.identity_map.values():
        if isinstance(obj, model) and (obj in db.dirty or obj in db.deleted):
            changed()
    return (await db.execute(statement.execution_options(populate_existing=True))).scalar_one_or_none()


async def _validate_parents(db, p):
    p.require(db)
    if await resolve_company_id(p.company_ref, db) != p.company_id:
        changed()
    for uid, before in p.users.items():
        if await _one(db, User, uid, "company_id", "is_superadmin") != before:
            changed()
    member = await _members(db, p.company_id, p.actor_id)
    # Mutable modules/object scopes are refreshed for native product admission;
    # pointer drift must not silently extend B after its first wait.
    if (None if member is None else tuple(member[:5])) != (
            None if p.member is None else tuple(p.member[:5])):
        changed()
    for uid, before in p.extra_members.items():
        if await _members(db, p.company_id, uid) != before:
            changed()
    if p.epoch_kind_id is not None and await _one(db, DocKind, p.epoch_kind_id, "company_id") != p.epoch_kind:
        changed()
    for rid, before in p.roles.items():
        if await _one(db, CompanyRole, rid, "company_id") != before:
            changed()
    for (model, uid), before in p.parents.items():
        if await _one(db, model, uid, "company_id") != before:
            changed()
    if p.visit is not None:
        if await _one(db, PartnerSpace, p.visit[0], "company_id") != p.visit[1]:
            changed()


async def _fresh_admission(db, p):
    await _validate_parents(db, p)
    for cid in p.companies:
        await _refresh_clean(db, Company, select(Company).where(Company.id == cid))
    for uid in p.users:
        result = await _refresh_clean(db, User, select(User).where(User.id == uid))
        if uid == p.actor_id and result is None:
            raise HTTPException(401, "Пользователь не найден")
    for rid in p.roles:
        await _refresh_clean(db, CompanyRole, select(CompanyRole).where(CompanyRole.id == rid))
    for model, uid in p.parents:
        await _refresh_clean(db, model, select(model).where(model.id == uid))
    if p.visit is not None:
        await _refresh_clean(db, PartnerSpace, select(PartnerSpace).where(PartnerSpace.id == p.visit[0]))
    await _refresh_clean(db, UserCompany, select(UserCompany).where(
        UserCompany.company_id == p.company_id, UserCompany.user_id == p.actor_id))
    for uid in p.extra_members:
        await _refresh_clean(db, UserCompany, select(UserCompany).where(
            UserCompany.company_id == p.company_id, UserCompany.user_id == uid))
    if p.card_pointer is not None:
        await _refresh_clean(db, DocKind, select(DocKind).where(DocKind.id == p.card_pointer[1]))
    if p.claims is not None:
        actor = await native_user_from_claims(p.claims, db)
        if actor.id != p.actor_id:
            changed()
        await native_visit_from_claims(p.claims, actor, db)
    set_request_organization(p.selector)
    if await assert_company_product(p.company_ref, p.actor, db, "docs") != p.company_id:
        changed()
    p.require(db)


async def _entrance(db, actor, company_ref, *, did=None, kind_epoch=None,
                    user_ids=(), deputy=None, writer_pointer=None,
                    subject_type=None, subject_id=None):
    """Complete scalar B, one kernel plan, then parent-first physical rows."""
    _clean(db)
    aid = inspect(actor).identity[0]
    claims = deepcopy(current_token_claims())
    selector = current_organization()
    with db.no_autoflush:
        cid = await resolve_company_id(company_ref, db)
        card = await _one(db, DocCard, did, *_CARD_POINTERS) if did else None
        kind = await _one(db, DocKind, card[1], "company_id", "default_case_id",
                         "number_scope") if card and card[0] == cid else None
        if card is not None and card[0] != cid:
            card = kind = None
        children = {m: await _children(db, m, did) for m in (DocApproval, DocAcquaint)} if card else {}
        substitutions = await _substitutions(db, cid, aid) if did else ()
        subscriptions = await _subscriptions(db, cid) if did else ()
        epoch_kind = await _one(db, DocKind, kind_epoch, "company_id") if kind_epoch else None
        subject = discover_doc_uuid(str(subject_id)) if subject_id else None
        raw_users = {aid, *user_ids}
        if subject_type == "user" and subject:
            raw_users.add(subject)
        if deputy:
            raw_users.add(deputy)
        if card:
            raw_users.update(u for u in card[2:7] if u is not None)
        for rows in (*children.values(), substitutions):
            for row in rows:
                raw_users.update(u for u in row[2:] if u is not None)
        # Child columns use native UUID, User.id uses the canonical codec. Resolve
        # every raw ref through that existing column before forming User keys.
        users = {}
        for raw in sorted(raw_users, key=str):
            uid = await db.scalar(select(User.id).where(User.id == raw))
            key = uid if uid is not None else discover_doc_uuid(str(raw))
            users[key] = await _one(db, User, key, "company_id", "is_superadmin")
        member = await _members(db, cid, aid)
        roles = {}
        if (member and member[0] is not None and member[1] != "admin"
                and users.get(aid) and not users[aid][1]):
            roles[member[0]] = await _one(db, CompanyRole, member[0], "company_id")
        extra_members = {subject: await _members(db, cid, subject)} if subject_type == "user" and subject and subject != aid else {}
        if subject_type == "role" and subject:
            roles[subject] = await _one(db, CompanyRole, subject, "company_id")
        cases = {}
        if card:
            for case_id in sorted({u for u in (card[9], kind[1] if kind else None) if u}):
                cases[case_id] = await _one(db, DocCase, case_id, "company_id", "organization_id")
        inference = ()
        if card and kind and "org" in kind[2] and card[7] is None:
            inference = tuple((await db.execute(select(Organization.id).where(
                Organization.company_id == cid).order_by(Organization.id))).scalars().all())
        parents = {}
        orgs = set(inference) | ({selector} if selector else set())
        cps = set()
        if card:
            orgs.add(card[7])
            cps.add(card[8])
        if member:
            orgs.add(member[3])
            cps.add(member[4])
        orgs.update(v[1] for v in cases.values() if v is not None)
        for model, ids in ((Organization, orgs), (Counterparty, cps)):
            for uid in sorted(u for u in ids if u):
                parents[(model, uid)] = await _one(db, model, uid, "company_id")
        if subject_type == "department" and subject:
            parents[(Department, subject)] = await _one(db, Department, subject, "company_id")
        visit = None
        if claims and claims.get("scp") == "visit":
            pid = discover_doc_uuid(str(claims.get("pvs")))
            if pid:
                visit = (pid, await _one(db, PartnerSpace, pid, "company_id"))
        companies = {cid} | {v[0] for v in (*users.values(), *roles.values(), *parents.values(),
            *cases.values()) if v and v[0]}
        if kind:
            companies.add(kind[0])
        if epoch_kind:
            companies.add(epoch_kind[0])
        if visit and visit[1]:
            companies.add(visit[1][0])
        for rows in (*children.values(), substitutions, subscriptions):
            companies.update(r[1] for r in rows)
        # Native child UUID codecs need not yield exact stdlib UUID. Only
        # canonical Company.id results may enter the frozen typed kernel.
        canonical_companies = set()
        for raw in companies:
            canonical = await db.scalar(select(Company.id).where(Company.id == raw))
            canonical_companies.add(canonical if canonical is not None else discover_doc_uuid(str(raw)))
        companies = tuple(sorted(canonical_companies))
        requests = [LockRequest(CompanyKey(c), S) for c in companies]
        requests += [LockRequest(UserKey(u), X if u == deputy else S) for u in sorted(users)]
        requests += [LockRequest(RoleKey(v[0] if v else cid, rid), S) for rid, v in sorted(roles.items())]
        requests += [LockRequest(MemberKey(cid, u), S) for u in sorted({aid, *extra_members})]
        requests.append(LockRequest(RefCompositeKey(cid), S))
        plan = LockPlan(tuple(requests))
        cap = await acquire_scoped_locks_async(db, plan)
        p = RegisterParents(cid, aid, company_ref, selector, claims, users, member,
            roles, parents, companies, visit, plan, cap, actor, did, card, kind,
            cases, inference, children, substitutions, subscriptions,
            writer_pointer=writer_pointer, extra_members=extra_members,
            epoch_kind=epoch_kind, epoch_kind_id=kind_epoch)
        p.require(db)
        for company in companies:
            await _refresh_clean(db, Company, select(Company).where(Company.id == company).with_for_update(read=True))
            p.require(db)
        # X is chosen before the first User lock, including actor==deputy.
        for uid in sorted(users):
            await _refresh_clean(db, User, select(User).where(User.id == uid).with_for_update(read=uid != deputy))
            p.require(db)
        for rid in sorted(roles):
            await _refresh_clean(db, CompanyRole, select(CompanyRole).where(CompanyRole.id == rid).with_for_update(read=True))
            p.require(db)
        for model, uid in parents:
            await _refresh_clean(db, model, select(model).where(model.id == uid).with_for_update(read=True))
            p.require(db)
        if visit:
            await _refresh_clean(db, PartnerSpace, select(PartnerSpace).where(PartnerSpace.id == visit[0]).with_for_update(read=True))
            p.require(db)
        await _refresh_clean(db, UserCompany, select(UserCompany).where(
            UserCompany.company_id == cid, UserCompany.user_id == aid).with_for_update(read=True))
        p.require(db)
        for uid in extra_members:
            await _refresh_clean(db, UserCompany, select(UserCompany).where(
                UserCompany.company_id == cid, UserCompany.user_id == uid).with_for_update(read=True))
            p.require(db)
        for sid, owner in subscriptions:
            await db.execute(select(EventSubscription).where(EventSubscription.id == sid,
                EventSubscription.company_id == owner).with_for_update(read=True).execution_options(populate_existing=True))
            p.require(db)
        if did:
            await acquire_case_catalog(db, (cid,), "S")
            p.require(db)
        kid = card[1] if card else kind_epoch
        if kid:
            await _refresh_clean(db, DocKind, select(DocKind).where(DocKind.id == kid)
                                 .with_for_update(read=kind_epoch is None))
            p.require(db)
        await _fresh_admission(db, p)
        if did:
            current = await _one(db, DocCard, did, *_CARD_POINTERS)
            if current is not None and current[0] != cid:
                current = None
            if current != card:
                changed()
        return p


async def prepare_register(db, actor, company_ref, doc_id):
    return await _entrance(db, actor, company_ref, did=discover_doc_uuid(doc_id))


async def prepare_kind_grant(db, actor, company_ref, kind_id, *,
                             subject_type=None, subject_id=None, grant_id=None):
    _clean(db)
    with db.no_autoflush:
        before = await _one(db, DocAccessGrant, grant_id, "company_id", "scope_type", "scope_id", "subject_type", "subject_id") if grant_id else None
    if grant_id and (before is None or tuple(before[1:]) != ("kind",
            discover_doc_uuid(str(kind_id)), subject_type, discover_doc_uuid(str(subject_id)))):
        changed()
    p = await _entrance(db, actor, company_ref, kind_epoch=discover_doc_uuid(str(kind_id)),
        subject_type=subject_type, subject_id=subject_id)
    if grant_id and before[0] != p.company_id:
        changed()
    if grant_id and await _one(db, DocAccessGrant, grant_id, "company_id", "scope_type", "scope_id", "subject_type", "subject_id") != before:
        changed()
    return p


async def prepare_kind_grant_delete(db, actor, company_ref, cid, grant_id):
    # Discovery only: the router's one native selector/predicates run after X.
    uid = discover_doc_uuid(grant_id)
    if uid is None:
        return
    with db.no_autoflush:
        before = await _one(db, DocAccessGrant, uid, "company_id", "scope_type", "scope_id", "subject_type", "subject_id")
    if before is not None and before[0] == cid and before[1] == "kind":
        return await prepare_kind_grant(db, actor, company_ref, before[2],
            subject_type=before[3], subject_id=before[4], grant_id=uid)


async def prepare_substitution(db, actor, company_ref, *, principal=None,
                               deputy=None, sub_id=None):
    _clean(db)
    with db.no_autoflush:
        pointer = await _one(db, UserSubstitution, sub_id, "company_id", "user_id", "deputy_id", "created_by") if sub_id else None
    if pointer:
        principal, deputy = pointer[1:3]
    p = await _entrance(db, actor, company_ref,
        user_ids=tuple(u for u in (principal, deputy, pointer[3] if pointer else None) if u),
        deputy=deputy, writer_pointer=pointer)
    if sub_id and await _one(db, UserSubstitution, sub_id, "company_id", "user_id", "deputy_id", "created_by") != pointer:
        changed()
    return p


def retain_register(p, doc):
    """Exact native own delta; no refresh/expire of pending Card/history."""
    # onupdate may expire updated_at after a native autoflush. It is not an
    # admission input: never trigger implicit async I/O to retain that clock.
    values = {c.key: deepcopy(getattr(doc, c.key)) for c in inspect(DocCard).columns
              if c.key != "updated_at"}
    if p.baseline is None:
        if p.card_pointer is None or tuple(values[k] for k in _CARD_POINTERS) != tuple(p.card_pointer):
            changed()
        object.__setattr__(p, "baseline", MappingProxyType(deepcopy(values)))
    elif any(values[k] != before for k, before in p.baseline.items() if k not in _OWN_CARD):
        changed()
    if (values["organization_id"] is not None and (Organization, values["organization_id"]) not in p.parents
            or values["case_id"] is not None and values["case_id"] not in p.cases
            or values["registered_by"] is not None and values["registered_by"] not in p.users):
        changed()
    return values


def _pending_fingerprint(db):
    return tuple((label, tuple(sorted((id(obj), deepcopy({k: v for k, v in inspect(obj).dict.items() if k != "_sa_instance_state"}),
        tuple((attr.key, deepcopy(attr.history.added), deepcopy(attr.history.deleted))
              for attr in inspect(obj).attrs if attr.history.has_changes()))
        for obj in objects))) for label, objects in (
            ("new", db.new), ("dirty", db.dirty), ("deleted", db.deleted)))


async def check_register(db, p, doc, retained, *, phase):
    """No new keys or locks. Preserve pending Card/Acquaint/event/audit history."""
    p.require(db)
    pending = _pending_fingerprint(db)
    with db.no_autoflush:
        await _fresh_admission(db, p)
        before = p.card_pointer
        pointer = await _one(db, DocCard, p.doc_id, *_CARD_POINTERS)
        if before is None or pointer is None:
            changed()
        for i, name in enumerate(_CARD_POINTERS):
            allowed = (before[i], retained[name]) if name in _OWN_CARD else (before[i],)
            if pointer[i] not in allowed:
                changed()
        if await _one(db, DocKind, before[1], "company_id", "default_case_id", "number_scope") != p.kind:
            changed()
        for uid, row in p.cases.items():
            if await _one(db, DocCase, uid, "company_id", "organization_id") != row:
                changed()
        if p.kind and "org" in p.kind[2] and before[7] is None:
            inference = tuple((await db.execute(select(Organization.id).where(
                Organization.company_id == p.company_id).order_by(Organization.id))).scalars().all())
            if inference != p.inference:
                changed()
        for model, rows in p.children.items():
            if await _children(db, model, p.doc_id) != rows:
                changed()
        if await _substitutions(db, p.company_id, p.actor_id) != p.substitutions:
            changed()
        if await _subscriptions(db, p.company_id) != p.subscriptions:
            changed()
        # Compare current retained scalar state after a flush as well as before
        # one; only exact native mutations may replace original persisted values.
        persisted = (await db.execute(select(*inspect(DocCard).columns).where(DocCard.id == p.doc_id))).mappings().one()
        for key, value in retained.items():
            if key == "updated_at":
                continue  # Native server/onupdate clock, never a policy input.
            if getattr(doc, key) != value:
                changed()
            if key != "updated_at" and persisted[key] not in (p.baseline[key], value):
                changed()
        from app.services.doc_access import assert_fresh_doc_edit
        await assert_fresh_doc_edit(db, p.company_id, doc, p.actor)
        p.require(db)
        if _pending_fingerprint(db) != pending:
            changed()


async def supersede_register_acquaints(db, p):
    """At the old supersede point, sorted child X after the original Card X."""
    p.require(db)
    with db.no_autoflush:
        if await _children(db, DocAcquaint, p.doc_id) != p.children.get(DocAcquaint, ()):
            changed()
        rows = (await db.execute(select(DocAcquaint).where(DocAcquaint.doc_id == p.doc_id,
            DocAcquaint.status == "pending").order_by(DocAcquaint.id).with_for_update())).scalars().all()
        p.require(db)
        for row in rows:
            row.status = "superseded"


@dataclass(frozen=True)
class PreparedSubscriptions:
    issuer: weakref.ReferenceType
    capability: ScopedLockCapability
    plan: LockPlan
    parents: tuple

    def require(self, db):
        if self.issuer() is not db.sync_session or self.capability.plan is not self.plan:
            raise ScopedLockError("Subscription parents belong to another root")
        require_scoped_locks(db.sync_session, self.capability, self.plan.requests)
        return dict(self.parents)


def subscription_parents(db, p):
    p.require(db)
    return PreparedSubscriptions(weakref.ref(db.sync_session), p.capability, p.plan, p.subscriptions)


# Weak ownership: a sealed request cannot retain a Session or affect G3's next
# root. Kernel capability also detects physical commit/rollback/invalidation.
_SEALS = weakref.WeakKeyDictionary()


def _before_flush(session, flush_context, instances):
    seal = _SEALS.get(session)
    if seal is None:
        return
    root, capability, requests = seal
    if session.get_transaction() is not root():
        _SEALS.pop(session, None)
        return
    require_scoped_locks(session, capability, requests)
    if session.new or session.dirty or session.deleted:
        raise ScopedLockError("Unexpected DML after native register final check")


def _root_end(session, transaction):
    seal = _SEALS.get(session)
    if seal is not None and transaction is seal[0]():
        _SEALS.pop(session, None)


def seal_register(db, p):
    p.require(db)
    _clean(db)
    root = db.sync_session.get_transaction()
    _SEALS[db.sync_session] = (weakref.ref(root), p.capability, p.plan.requests)


event.listen(Session, "before_flush", _before_flush)
event.listen(Session, "after_transaction_end", _root_end)
