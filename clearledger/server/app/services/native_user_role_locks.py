"""Native user/role writer entrance; no transaction ownership or router imports.

Discovery is MVCC-only. A changed parent/pointer aborts the caller's whole root
with 409; retry belongs to a new request, never to a late plan extension.
"""
from dataclasses import dataclass
from dataclasses import replace
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_token_claims, native_user_from_claims, native_visit_from_claims
from app.models import Company, CompanyRole, User, UserCompany
from app.models import Organization
from app.utils import resolve_company_id
from app.services.contract_write_locks import RefCompositeKey
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
    scope_snapshot: dict | None = None
    scope_organization_id: UUID | None = None


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
                role_id: UUID | None = None, scope_org: bool = False) -> LockPlan:
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
    if scope_org and company_id is not None:
        requests.append(LockRequest(RefCompositeKey(company_id), S))
    return LockPlan(tuple(requests))


async def prepare_native_write(
    db: AsyncSession, actor: User, *, company_id: UUID | None,
    target_id: UUID | None = None, account: bool = False,
    new_role_id: UUID | None = None, role_id: UUID | None = None,
    email_pointer: tuple[str, UUID | None] | None = None,
    expected_member: tuple[UUID | None, str] | None = None,
    scope_org: bool = False, scope_company_ref: str | None = None,
    scope_organization_id: str | None = None,
) -> NativeWrite:
    """One clean managed handler root, complete keys, parent-first rows, fresh ACL.

    Caller preserves legacy validation order before entering; no write, row lock
    or autoflush may precede this entrance. No commit/rollback/retry here.
    Role deletion holds Role X over holder updates, without late holder User keys.
    """
    assert_native_clean(db)
    actor_identity = inspect(actor).identity if scope_org else None
    aid = actor_identity[0] if actor_identity else actor.id
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
        scope_snapshot = None
        if scope_org:
            old_org = (await db.execute(select(UserCompany.own_organization_id).where(
                UserCompany.company_id == company_id, UserCompany.user_id == target_id))).one_or_none()
            candidate = None
            if scope_organization_id is not None:
                try:
                    candidate = UUID(scope_organization_id.strip())
                except ValueError:
                    pass
            # Только scalar MVCC discovery; старое foreign-юрлицо не блокируем.
            proposed_before = None
            if candidate is not None:
                proposed_before = (await db.execute(select(Organization.company_id).where(
                    Organization.id == candidate))).one_or_none()
            scope_snapshot = dict(actor_id=aid, target_id=target_id, company_id=company_id,
                company_ref=scope_company_ref, companies=companies, users_before=users_before,
                members_before=members_before, old_org=old_org, candidate=candidate,
                proposed_before=proposed_before, org_requested=scope_organization_id is not None,
                old_role_ids=old_role_ids, org_phase_done=False, locked_candidate=None)
        plan = native_plan(actor_id=aid, target_id=target_id, company_id=company_id,
                           companies=companies, member_pointers=members_before,
                           account=account, new_role_id=new_role_id, role_id=role_id,
                           scope_org=scope_org)
        capability = await acquire_scoped_locks_async(db, plan)
        require_scoped_locks(db.sync_session, capability, plan.requests)

        # Expire discovery objects, including visit dependencies: get() must not
        # reuse an identity-map snapshot predating the advisory wait.
        if scope_org:
            assert_native_clean(db)
        db.expire_all()
        for cid in companies:
            company = (await db.execute(select(Company).where(Company.id == cid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            if scope_org:
                require_scoped_locks(db.sync_session, capability, plan.requests)
            if company is None:
                _conflict()
        users = {}
        for uid in user_ids:
            users[uid] = (await db.execute(select(User).where(User.id == uid)
                .with_for_update(read=not (account and uid == target_id))
                .execution_options(populate_existing=True))).scalar_one_or_none()
            if scope_org:
                require_scoped_locks(db.sync_session, capability, plan.requests)
        # Detect changed User parents before touching CompanyRole/UserCompany.
        for uid in user_ids:
            if await _user_pointer(db, uid) != users_before[uid]:
                _conflict()
            if scope_org:
                require_scoped_locks(db.sync_session, capability, plan.requests)
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
            if scope_org:
                require_scoped_locks(db.sync_session, capability, plan.requests)
        if any(roles.get(rid) is None for rid in old_role_ids):
            _conflict()
        if scope_org:
            prepared = NativeWrite(capability, plan, actor, users.get(target_id), None,
                                   roles.get(role_id), scope_snapshot)
            # Ошибки native ACL/member404 не должны ждать дополнительную Org-фазу.
            await _refresh_native_scope(db, prepared)
            require_scoped_locks(db.sync_session, capability, plan.requests)
            candidate = scope_snapshot["candidate"]
            if candidate is not None:
                scope_snapshot["locked_candidate"] = (await db.execute(select(Organization.id).where(
                    Organization.company_id == company_id, Organization.id == candidate)
                    .with_for_update(read=True))).scalar_one_or_none()
                require_scoped_locks(db.sync_session, capability, plan.requests)
            scope_snapshot["org_phase_done"] = True
        members = {}
        for uid in sorted(members_before):
            # Do not wait on an unplanned new parent: MVCC pointer first, then
            # lock the member, then compare again under its row lock.
            if await _member_pointer(db, uid, company_id) != members_before[uid]:
                _conflict()
            if scope_org:
                require_scoped_locks(db.sync_session, capability, plan.requests)
            members[uid] = (await db.execute(select(UserCompany).where(
                UserCompany.company_id == company_id, UserCompany.user_id == uid)
                .with_for_update(read=uid != target_id)
                .execution_options(populate_existing=True))).scalar_one_or_none()
            if scope_org:
                require_scoped_locks(db.sync_session, capability, plan.requests)
            if await _member_pointer(db, uid, company_id) != members_before[uid]:
                _conflict()
            if scope_org:
                require_scoped_locks(db.sync_session, capability, plan.requests)
        if scope_org:
            return await _refresh_native_scope(db, prepared)
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


async def _refresh_native_scope(db: AsyncSession, prepared: NativeWrite) -> NativeWrite:
    """Перечитать scope/ACL после ожиданий, без новых ключей и владения root."""
    assert_native_clean(db)
    require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
    snapshot = prepared.scope_snapshot
    if snapshot is None:
        raise ScopedLockError("Native scope snapshot required")
    cid, aid, uid = (snapshot[k] for k in ("company_id", "actor_id", "target_id"))
    with db.no_autoflush:
        # Обновляем только чистые снимки; сохранённым ORM-объектам не доверяем.
        db.expire_all()
        async def read(statement):
            result = await db.execute(statement.execution_options(populate_existing=True))
            require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
            return result

        for company_id in snapshot["companies"]:
            if (await read(select(Company.id).where(Company.id == company_id))).scalar_one_or_none() is None:
                _conflict()
        users = {}
        for user_id, before in snapshot["users_before"].items():
            actual = (await read(select(User.company_id, User.is_superadmin).where(
                User.id == user_id))).one_or_none()
            if actual != before:
                _conflict()
            users[user_id] = (await read(select(User).where(User.id == user_id))).scalar_one_or_none()
        for user_id, before in snapshot["members_before"].items():
            actual = (await read(select(UserCompany.role_id, UserCompany.role).where(
                UserCompany.company_id == cid, UserCompany.user_id == user_id))).one_or_none()
            if actual != before:
                _conflict()
        for rid in sorted(snapshot["old_role_ids"]):
            owner = (await read(select(CompanyRole.company_id).where(CompanyRole.id == rid))).scalar_one_or_none()
            if owner != cid:
                _conflict()
        old_org = (await read(select(UserCompany.own_organization_id).where(
            UserCompany.company_id == cid, UserCompany.user_id == uid))).one_or_none()
        if old_org != snapshot["old_org"]:
            _conflict()
        if snapshot["company_ref"] is not None:
            try:
                actual_cid = await resolve_company_id(snapshot["company_ref"], db)
            except HTTPException as exc:
                if exc.status_code != 400:
                    raise
                _conflict()
            require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
            if actual_cid != cid:
                _conflict()
        effective = old_org[0] if old_org is not None else None
        if snapshot["org_requested"]:
            effective = None
            if snapshot["candidate"] is not None:
                effective = (await read(select(Organization.id).where(
                    Organization.company_id == cid,
                    Organization.id == snapshot["candidate"]))).scalar_one_or_none()
        # Новый effective SET после Member-фазы не получает поздний FK-parent lock.
        # RETAIN старого (в том числе foreign) и legacy CLEAR сюда не попадают.
        if (snapshot["org_phase_done"] and snapshot["org_requested"] and effective is not None
                and effective != snapshot["locked_candidate"]):
            _conflict()
        claims = current_token_claims()
        if claims is None:
            raise HTTPException(401, "Требуется авторизация")
        fresh_actor = await native_user_from_claims(claims, db)
        require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
        if fresh_actor.id != aid:
            _conflict()
        await native_visit_from_claims(claims, fresh_actor, db)
        require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
        actor_member = (await read(select(UserCompany).where(
            UserCompany.company_id == cid, UserCompany.user_id == aid))).scalar_one_or_none()
        if not fresh_actor.is_superadmin and (actor_member is None or actor_member.role != "admin"):
            raise HTTPException(403, "Требуются права администратора компании")
        member = (await read(select(UserCompany).where(
            UserCompany.company_id == cid, UserCompany.user_id == uid))).scalar_one_or_none()
        if member is None:
            raise HTTPException(404, "Пользователь не член компании")
        require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
        return replace(prepared, actor=fresh_actor, target=users.get(uid), member=member,
                       scope_organization_id=effective)
