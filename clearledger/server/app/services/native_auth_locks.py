"""Account writer entrance; no router imports or transaction completion.

One complete plan belongs to one clean managed handler DB root. Discovery is
MVCC-only; a changed identity/parent needs whole-root rollback and a new request.
Authentication policy remains in app.auth and the calling route.
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_token_claims, native_user_from_claims, native_visit_from_claims
from app.models import Company, User
from app.services.contract_write_locks import (
    CompanyKey, LockMode, LockPlan, LockRequest, MemberKey, ScopedLockCapability,
    ScopedLockError, UserKey, acquire_scoped_locks_async, require_scoped_locks,
)

S, X = LockMode.SHARED, LockMode.EXCLUSIVE


def assert_auth_clean(db: AsyncSession) -> None:
    """No I/O, including before a legacy SELECT which could autoflush."""
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Auth writer requires clean entry")


class AuthIdentityChanged(HTTPException):
    """Only pre-mutation identity/parent drift, never lock/driver failure."""

    def __init__(self) -> None:
        super().__init__(409, "Данные учётной записи изменились одновременно; повторите запрос")


def auth_conflict() -> None:
    raise AuthIdentityChanged()


@dataclass(frozen=True)
class AuthWrite:
    capability: ScopedLockCapability
    plan: LockPlan
    user: User | None
    actor: User | None

    def require(self, db: AsyncSession) -> None:
        # Deliberately permits authorized pending writes, e.g. new-login notice.
        require_scoped_locks(db.sync_session, self.capability, self.plan.requests)


def auth_plan(*, target_id: UUID | None, actor_id: UUID | None,
              companies: tuple[UUID, ...], member_company: UUID | None = None) -> LockPlan:
    requests = [LockRequest(CompanyKey(cid), S) for cid in companies]
    if actor_id is not None:
        requests.append(LockRequest(UserKey(actor_id), S))
    if target_id is not None:
        requests.append(LockRequest(UserKey(target_id), X))
    if member_company is not None:
        requests.append(LockRequest(MemberKey(member_company, target_id), X))
    return LockPlan(tuple(requests))


async def _pointer(db: AsyncSession, uid: UUID):
    return (await db.execute(select(User.email, User.company_id).where(
        User.id == uid))).one_or_none()


async def prepare_auth_write(
    db: AsyncSession, *, target_id: UUID | None, actor: User | None = None,
    companies: tuple[UUID, ...] = (), new_user: bool = False,
    member_company: UUID | None = None,
    email_pointer: tuple[str, UUID | None] | None = None,
    expected_pointer: tuple[str, UUID | None] | None = None,
) -> AuthWrite:
    """Acquire once, Company→User rows, then repeat the same native session policy.

    New register UUID and absent Member key are declared before add/flush. No
    role key is needed: register preserves UserCompany's default role/NULL role_id.
    Self routes do not inherit an unrelated native-admin ACL.
    """
    assert_auth_clean(db)
    aid = actor.id if actor is not None else None
    claims = current_token_claims() if actor is not None else None
    with db.no_autoflush:
        ids = sorted(({aid} if aid is not None else set()) |
                     ({target_id} if target_id is not None else set()))
        before = {uid: await _pointer(db, uid) for uid in ids}
        if new_user:
            if target_id is None or before[target_id] is not None:
                auth_conflict()
        elif target_id is not None:
            if before[target_id] is None:
                auth_conflict()
            if expected_pointer is not None and tuple(before[target_id]) != expected_pointer:
                auth_conflict()
        parents = tuple(sorted(set(companies) | {
            p[1] for p in before.values() if p is not None and p[1] is not None
        } | ({member_company} if member_company is not None else set())))
        plan = auth_plan(target_id=target_id, actor_id=aid, companies=parents,
                         member_company=member_company)
        capability = await acquire_scoped_locks_async(db, plan)
        require_scoped_locks(db.sync_session, capability, plan.requests)
        # Also clear cached visit/membership objects used by the frozen auth API.
        db.expire_all()
        for cid in parents:
            parent = (await db.execute(select(Company).where(Company.id == cid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            if parent is None:
                auth_conflict()
        users = {}
        for uid in ids:
            users[uid] = (await db.execute(select(User).where(User.id == uid)
                .with_for_update(read=uid != target_id)
                .execution_options(populate_existing=True))).scalar_one_or_none()
            if await _pointer(db, uid) != before[uid]:
                auth_conflict()
        if email_pointer is not None:
            email, expected_id = email_pointer
            actual_id = (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
            if actual_id != expected_id:
                auth_conflict()
        fresh_actor = None
        if actor is not None:
            if claims is None:
                raise HTTPException(401, "Требуется авторизация")
            fresh_actor = await native_user_from_claims(claims, db)
            if fresh_actor.id != aid:
                auth_conflict()
            await native_visit_from_claims(claims, fresh_actor, db)
        write = AuthWrite(capability, plan, users.get(target_id), fresh_actor)
        write.require(db)
        return write
