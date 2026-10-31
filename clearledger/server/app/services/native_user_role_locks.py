"""Native user/role writer entrance; no transaction ownership or router imports.

Discovery is MVCC-only. A changed parent/pointer aborts the caller's whole root
with 409; retry belongs to a new request, never to a late plan extension.
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_token_claims, native_user_from_claims, native_visit_from_claims
from app.models import Company, CompanyRole, User, UserCompany
from app.services.contract_write_locks import (
    CompanyKey, LockMode, LockPlan, LockRequest, MemberKey, RoleKey,
    ScopedLockCapability, ScopedLockError, UserKey, acquire_scoped_locks_async,
    require_scoped_locks,
)

S, X = LockMode.SHARED, LockMode.EXCLUSIVE


@dataclass(frozen=True)
class NativeWrite:
    capability: ScopedLockCapability
    plan: LockPlan
    actor: User
    target: User | None
    member: UserCompany | None
    role: CompanyRole | None


def assert_native_clean(db: AsyncSession) -> None:
    """No-I/O check before even the router's legacy read-only preflight."""
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Native writer requires clean entry")


def _conflict() -> None:
    raise HTTPException(409, "Данные доступа изменились одновременно; повторите запрос")


async def _user_pointer(db: AsyncSession, uid: UUID):
    return (await db.execute(select(User.company_id, User.is_superadmin).where(
        User.id == uid))).one_or_none()


async def _member_pointer(db: AsyncSession, uid: UUID, cid: UUID):
    return (await db.execute(select(UserCompany.role_id, UserCompany.role).where(
        UserCompany.company_id == cid, UserCompany.user_id == uid))).one_or_none()


def native_plan(*, actor_id: UUID, target_id: UUID | None, company_id: UUID | None,
                companies: tuple[UUID, ...], member_pointers: dict,
                account: bool = False, new_role_id: UUID | None = None,
                role_id: UUID | None = None) -> LockPlan:
    """Complete logical declaration; frozen helper merges actor==target modes."""
    requests = [LockRequest(UserKey(actor_id), S)]
    requests.extend(LockRequest(CompanyKey(cid), S) for cid in companies)
    if target_id is not None:
        requests.append(LockRequest(UserKey(target_id), X if account else S))
    if company_id is not None:
        for uid, pointer in member_pointers.items():
            requests.append(LockRequest(MemberKey(company_id, uid),
                                        X if uid == target_id else S))
            if pointer is not None and pointer[0] is not None:
                requests.append(LockRequest(RoleKey(company_id, pointer[0]), S))
        if new_role_id is not None:
            requests.append(LockRequest(RoleKey(company_id, new_role_id), S))
        if role_id is not None:
            requests.append(LockRequest(RoleKey(company_id, role_id), X))
    return LockPlan(tuple(requests))


async def prepare_native_write(
    db: AsyncSession, actor: User, *, company_id: UUID | None,
    target_id: UUID | None = None, account: bool = False,
    new_role_id: UUID | None = None, role_id: UUID | None = None,
    email_pointer: tuple[str, UUID | None] | None = None,
    expected_member: tuple[UUID | None, str] | None = None,
) -> NativeWrite:
    """One clean managed handler root, complete keys, parent-first rows, fresh ACL.

    Caller preserves legacy validation order before entering; no write, row lock
    or autoflush may precede this entrance. No commit/rollback/retry here.
    Role deletion holds Role X over holder updates, without late holder User keys.
    """
    assert_native_clean(db)
    aid = actor.id
    claims = current_token_claims()
    with db.no_autoflush:
        user_ids = sorted({aid} | ({target_id} if target_id is not None else set()))
        users_before = {uid: await _user_pointer(db, uid) for uid in user_ids}
        members_before = {}
        if company_id is not None:
            members_before = {uid: await _member_pointer(db, uid, company_id)
                              for uid in user_ids}
        if expected_member is not None and members_before.get(target_id) != expected_member:
            _conflict()
        companies = tuple(sorted({p[0] for p in users_before.values()
                                  if p is not None and p[0] is not None}
                                 | ({company_id} if company_id is not None else set())))
        # role_id is a single FK, not a tenant-composite FK. Refuse corrupt
        # legacy cross-company pointers instead of guarding an invented owner.
        old_role_ids = {p[0] for p in members_before.values()
                        if p is not None and p[0] is not None}
        for rid in sorted(old_role_ids):
            owner = (await db.execute(select(CompanyRole.company_id).where(
                CompanyRole.id == rid))).scalar_one_or_none()
            if owner != company_id:
                _conflict()
        plan = native_plan(actor_id=aid, target_id=target_id, company_id=company_id,
                           companies=companies, member_pointers=members_before,
                           account=account, new_role_id=new_role_id, role_id=role_id)
        capability = await acquire_scoped_locks_async(db, plan)
        require_scoped_locks(db.sync_session, capability, plan.requests)

        # Expire discovery objects, including visit dependencies: get() must not
        # reuse an identity-map snapshot predating the advisory wait.
        db.expire_all()
        for cid in companies:
            company = (await db.execute(select(Company).where(Company.id == cid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            if company is None:
                _conflict()
        users = {}
        for uid in user_ids:
            users[uid] = (await db.execute(select(User).where(User.id == uid)
                .with_for_update(read=not (account and uid == target_id))
                .execution_options(populate_existing=True))).scalar_one_or_none()
        # Detect changed User parents before touching CompanyRole/UserCompany.
        for uid in user_ids:
            if await _user_pointer(db, uid) != users_before[uid]:
                _conflict()
        role_ids = {p[0] for p in members_before.values()
                    if p is not None and p[0] is not None}
        role_ids.update(rid for rid in (new_role_id, role_id) if rid is not None)
        roles = {}
        for rid in sorted(role_ids):
            # Tenant predicate belongs before FOR SHARE/UPDATE, not after get().
            roles[rid] = (await db.execute(select(CompanyRole).where(
                CompanyRole.company_id == company_id, CompanyRole.id == rid)
                .with_for_update(read=rid != role_id)
                .execution_options(populate_existing=True))).scalar_one_or_none()
        if any(roles.get(rid) is None for rid in old_role_ids):
            _conflict()
        members = {}
        for uid in sorted(members_before):
            # Do not wait on an unplanned new parent: MVCC pointer first, then
            # lock the member, then compare again under its row lock.
            if await _member_pointer(db, uid, company_id) != members_before[uid]:
                _conflict()
            members[uid] = (await db.execute(select(UserCompany).where(
                UserCompany.company_id == company_id, UserCompany.user_id == uid)
                .with_for_update(read=uid != target_id)
                .execution_options(populate_existing=True))).scalar_one_or_none()
            if await _member_pointer(db, uid, company_id) != members_before[uid]:
                _conflict()
        if email_pointer is not None:
            email, expected_uid = email_pointer
            actual_uid = (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
            if actual_uid != expected_uid:
                _conflict()
        if claims is None:
            raise HTTPException(401, "Требуется авторизация")
        fresh_actor = await native_user_from_claims(claims, db)
        if fresh_actor.id != aid:
            _conflict()
        await native_visit_from_claims(claims, fresh_actor, db)
        if company_id is None:
            if not fresh_actor.is_superadmin:
                raise HTTPException(403, "Укажите company_id")
        elif not fresh_actor.is_superadmin:
            am = members.get(aid)
            if am is None or am.role != "admin":
                raise HTTPException(403, "Требуются права администратора компании")
        require_scoped_locks(db.sync_session, capability, plan.requests)
        return NativeWrite(capability, plan, fresh_actor, users.get(target_id),
                           members.get(target_id), roles.get(role_id))
