"""One complete native document-create entrance; caller owns the transaction.

Discovery is scalar MVCC only. No document ACL evaluation here: replay's native
read permission may record break-glass use. No router imports or completion.
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    assert_company_product, current_token_claims, native_user_from_claims,
    native_visit_from_claims,
)
from app.models import (
    Company, CompanyRole, Counterparty, DocCard, DocKind, Organization,
    User, UserCompany,
)
from app.scope import current_organization, set_request_organization
from app.services.contract_write_locks import (
    CompanyKey, LockMode, LockPlan, LockRequest, MemberKey, RefCompositeKey,
    RoleKey, ScopedLockCapability, ScopedLockError, UserKey,
    acquire_scoped_locks_async, require_scoped_locks,
)
from app.utils import resolve_company_id

S = LockMode.SHARED


def assert_doc_create_clean(db: AsyncSession) -> None:
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Native document create requires clean entry; roll back entire root")


def _changed() -> None:
    raise HTTPException(409, "Данные изменились одновременно; повторите запрос")


def discover_doc_uuid(value: str | None) -> UUID | None:
    """Candidate only; original validators still own UUID errors and their order."""
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError):
        return None


def doc_create_plan(*, companies: tuple[UUID, ...], users: tuple[UUID, ...],
                    company_id: UUID, members: tuple[UUID, ...],
                    role: tuple[UUID, UUID] | None) -> LockPlan:
    requests = [LockRequest(CompanyKey(cid), S) for cid in sorted(set(companies))]
    requests.extend(LockRequest(UserKey(uid), S) for uid in sorted(set(users)))
    if role is not None:
        requests.append(LockRequest(RoleKey(*role), S))
    requests.extend(LockRequest(MemberKey(company_id, uid), S) for uid in sorted(set(members)))
    requests.append(LockRequest(RefCompositeKey(company_id), S))
    return LockPlan(tuple(requests))


async def _user_pointer(db, uid):
    return (await db.execute(select(User.company_id, User.is_superadmin).where(
        User.id == uid))).one_or_none()


async def _member_pointer(db, cid, uid):
    return (await db.execute(select(UserCompany.role_id, UserCompany.role).where(
        UserCompany.company_id == cid, UserCompany.user_id == uid))).one_or_none()


async def _owner(db, model, uid):
    return (await db.execute(select(model.company_id).where(model.id == uid))).one_or_none()


async def _replay_pointer(db, cid, source_ref):
    if source_ref is None:
        return None
    return (await db.execute(select(
        DocCard.id, DocCard.author_id, DocCard.responsible_id, DocCard.signatory_id,
        DocCard.registered_by, DocCard.archive_accepted_by,
        DocCard.counterparty_id, DocCard.organization_id,
    ).where(DocCard.company_id == cid, DocCard.source == "manual",
            DocCard.source_ref == source_ref))).one_or_none()


@dataclass(frozen=True)
class NativeDocCreate:
    company_id: UUID
    actor_id: UUID
    actor: User
    plan: LockPlan
    capability: ScopedLockCapability
    company_ref: str
    organization_selector: UUID | None
    user_pointers: dict
    member_pointers: dict
    role: tuple[UUID, UUID] | None
    role_pointer: tuple | None
    parents: dict
    kind_id: UUID | None
    source_ref: str | None
    replay_pointer: tuple | None

    def require(self, db: AsyncSession) -> None:
        if self.plan is not self.capability.plan:
            raise ScopedLockError("Native document plan changed")
        require_scoped_locks(db.sync_session, self.capability, self.plan.requests)
        state = inspect(self.actor)
        if state.identity != (self.actor_id,) or state.session is not db.sync_session:
            raise ScopedLockError("Native document actor identity/session changed")


async def prepare_doc_create(
    db: AsyncSession, actor: User, company_ref: str, *, kind_id: str,
    organization_id: str | None = None, counterparty_id: str | None = None,
    responsible_id: str | None = None, signatory_id: str | None = None,
    source: str = "manual", source_ref: str | None = None,
) -> NativeDocCreate:
    """Full B before any legacy/advisory/row/FK wait or mutation.

    Org/CP SHARE must precede Member SHARE: legacy reference deletion updates
    the parent first and then SET NULLs membership pointers. No foreign ban is
    added; parent validators and product admission remain the native functions.
    """
    assert_doc_create_clean(db)
    identity = inspect(actor).identity
    aid = identity[0] if identity else actor.id
    selector = current_organization()
    with db.no_autoflush:
        cid = await resolve_company_id(company_ref, db)
        replay_ref = None
        if source == "manual" and (source_ref or "").startswith("contract-document:"):
            token = discover_doc_uuid(source_ref.split(":", 1)[1])
            if token is not None:
                replay_ref = f"contract-document:{token}"
        replay = await _replay_pointer(db, cid, replay_ref)
        new_users = {uid for uid in (discover_doc_uuid(responsible_id),
                                     discover_doc_uuid(signatory_id)) if uid is not None}
        users = {aid} | new_users | ({u for u in replay[1:6] if u is not None} if replay else set())
        user_pointers = {uid: await _user_pointer(db, uid) for uid in sorted(users)}
        member_pointers = {uid: await _member_pointer(db, cid, uid) for uid in sorted({aid} | new_users)}
        actor_pointer, member = user_pointers[aid], member_pointers[aid]
        role = role_pointer = None
        if (actor_pointer is not None and not actor_pointer[1] and member is not None
                and member[1] != "admin" and member[0] is not None):
            role_pointer = await _owner(db, CompanyRole, member[0])
            # Missing named role uses the native modules fallback; absent key
            # is fenced in the membership company, without inventing a row.
            role = (role_pointer[0] if role_pointer else cid, member[0])
        companies = {cid} | {p[0] for p in user_pointers.values() if p and p[0] is not None}
        if role_pointer is not None:
            companies.add(role_pointer[0])
        parents = {}
        for model, ids in (
            (Counterparty, {discover_doc_uuid(counterparty_id)} | ({replay[6]} if replay else set())),
            (Organization, {discover_doc_uuid(organization_id)} | ({replay[7]} if replay else set())),
        ):
            for uid in sorted(u for u in ids if u is not None):
                parents[(model, uid)] = await _owner(db, model, uid)
        plan = doc_create_plan(companies=tuple(companies), users=tuple(users),
                               company_id=cid, members=tuple(member_pointers), role=role)
        capability = await acquire_scoped_locks_async(db, plan)
        require_scoped_locks(db.sync_session, capability, plan.requests)
        assert_doc_create_clean(db)
        db.expire_all()
        for parent_cid in sorted(companies):
            parent = (await db.execute(select(Company).where(Company.id == parent_cid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            require_scoped_locks(db.sync_session, capability, plan.requests)
            if parent is None:
                _changed()
        fresh_users = {}
        for uid, before in user_pointers.items():
            if await _user_pointer(db, uid) != before:
                _changed()
            fresh_users[uid] = (await db.execute(select(User).where(User.id == uid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            require_scoped_locks(db.sync_session, capability, plan.requests)
            if await _user_pointer(db, uid) != before:
                _changed()
        if fresh_users[aid] is None:
            raise HTTPException(401, "Пользователь не найден")
        if role is not None:
            if await _owner(db, CompanyRole, role[1]) != role_pointer:
                _changed()
            (await db.execute(select(CompanyRole).where(
                CompanyRole.company_id == role[0], CompanyRole.id == role[1])
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            require_scoped_locks(db.sync_session, capability, plan.requests)
        # Do not take Member SHARE until all Org/CP SHARE waits have finished.
        for (model, uid), before in parents.items():
            if await _owner(db, model, uid) != before:
                _changed()
            (await db.execute(select(model).where(model.id == uid, model.company_id == cid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            require_scoped_locks(db.sync_session, capability, plan.requests)
        for uid, before in member_pointers.items():
            if await _member_pointer(db, cid, uid) != before:
                _changed()
            (await db.execute(select(UserCompany).where(
                UserCompany.company_id == cid, UserCompany.user_id == uid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            require_scoped_locks(db.sync_session, capability, plan.requests)
        kid = discover_doc_uuid(kind_id)
        if kid is not None:
            (await db.execute(select(DocKind).where(DocKind.id == kid, DocKind.company_id == cid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            require_scoped_locks(db.sync_session, capability, plan.requests)
        prepared = NativeDocCreate(cid, aid, fresh_users[aid], plan, capability,
            company_ref, selector, user_pointers, member_pointers, role, role_pointer,
            parents, kid, replay_ref, replay)
        await refresh_doc_create(db, prepared)
        return prepared


async def refresh_doc_create(db: AsyncSession, prepared: NativeDocCreate) -> None:
    """After the last wait, refresh clean retained state and native admission.

    Call only before replay permission evaluation/add/flush. Never re-plan and
    never expire pending state produced by the native break-glass policy.
    """
    assert_doc_create_clean(db)
    prepared.require(db)
    cid = prepared.company_id
    with db.no_autoflush:
        if await resolve_company_id(prepared.company_ref, db) != cid:
            _changed()
        for uid, before in prepared.user_pointers.items():
            if await _user_pointer(db, uid) != before:
                _changed()
        for uid, before in prepared.member_pointers.items():
            if await _member_pointer(db, cid, uid) != before:
                _changed()
        if prepared.role is not None:
            if await _owner(db, CompanyRole, prepared.role[1]) != prepared.role_pointer:
                _changed()
        for (model, uid), before in prepared.parents.items():
            if await _owner(db, model, uid) != before:
                _changed()
        replay = await _replay_pointer(db, cid, prepared.source_ref)
        if prepared.replay_pointer is not None and replay != prepared.replay_pointer:
            _changed()
        if replay is not None:
            if any(uid is not None and uid not in prepared.user_pointers for uid in replay[1:6]):
                _changed()
            for model, uid in ((Counterparty, replay[6]), (Organization, replay[7])):
                if uid is not None and (model, uid) not in prepared.parents:
                    _changed()
        # Includes retained User/Member/Role/Kind, PartnerSpace and replay rows.
        db.expire_all()
        # Refresh retained identities without another row-lock phase. These
        # rows are already SHARE-held, and no parent is discovered here.
        company_ids = {r.key.company_id for r in prepared.plan.requests
                       if type(r.key) is CompanyKey}
        for parent_cid in sorted(company_ids):
            (await db.execute(select(Company).where(Company.id == parent_cid)
                .execution_options(populate_existing=True))).scalar_one_or_none()
        for uid in prepared.user_pointers:
            (await db.execute(select(User).where(User.id == uid)
                .execution_options(populate_existing=True))).scalar_one_or_none()
        if prepared.role is not None:
            (await db.execute(select(CompanyRole).where(CompanyRole.id == prepared.role[1])
                .execution_options(populate_existing=True))).scalar_one_or_none()
        for uid in prepared.member_pointers:
            (await db.execute(select(UserCompany).where(
                UserCompany.company_id == cid, UserCompany.user_id == uid)
                .execution_options(populate_existing=True))).scalar_one_or_none()
        for model, uid in prepared.parents:
            # Foreign parents remain subject to the original native error.
            (await db.execute(select(model).where(model.company_id == cid, model.id == uid)
                .execution_options(populate_existing=True))).scalar_one_or_none()
        if prepared.kind_id is not None:
            (await db.execute(select(DocKind).where(DocKind.company_id == cid,
                DocKind.id == prepared.kind_id).execution_options(populate_existing=True))).scalar_one_or_none()
        actor = (await db.execute(select(User).where(User.id == prepared.actor_id)
            .execution_options(populate_existing=True))).scalar_one_or_none()
        if actor is None:
            raise HTTPException(401, "Пользователь не найден")
        prepared.require(db)
        claims = current_token_claims()
        if claims is not None:
            user = await native_user_from_claims(claims, db)
            if user.id != prepared.actor_id:
                _changed()
            await native_visit_from_claims(claims, user, db)
        set_request_organization(prepared.organization_selector)
        if await assert_company_product(prepared.company_ref, actor, db, "docs") != cid:
            _changed()
        prepared.require(db)
