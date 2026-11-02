"""Native contract entrance: caller policy and transaction ownership are retained.

One complete B plan precedes legacy CP -> contract barriers and every row lock.
Native membership policy does not read named CompanyRole: no Role admission is
invented here. Discovery is readonly, including an already-autobegun clean root.
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    assert_company_member, current_token_claims, native_user_from_claims, native_visit_from_claims,
)
from app.models import (
    Company, Contract, ContractDimension, ContractLink, ContractLocation,
    Counterparty, Organization, PartnerSpace, ServiceLocation, User, UserCompany,
)
from app.services.contract_write_locks import (
    CompanyKey, LockMode, LockPlan, LockRequest, MemberKey, RefCompositeKey,
    ScopedLockCapability, ScopedLockError, TypeCatalogKey, UserKey,
    acquire_scoped_locks_async, require_scoped_locks,
)
from app.services.reference_identity import lock_manual_creation
from app.scope import current_organization, set_request_organization
from app.utils import resolve_company_id


S = LockMode.SHARED
_UNSET = object()
_REFERENCE_ROWS = (Contract, Counterparty, Organization, ContractLink,
                   ContractLocation, ContractDimension, ServiceLocation, PartnerSpace, UserCompany)


@dataclass(frozen=True)
class NativeReferenceWrite:
    company_id: UUID
    actor_id: UUID
    capability: ScopedLockCapability
    plan: LockPlan
    actor: User
    member: UserCompany | None
    companies: tuple[Company, ...]
    contract_id: UUID | None
    type_change: bool
    old_type_code: str | None
    organization_selector: UUID | None = None
    user_pointers: tuple[tuple[UUID, bool, UUID | None], ...] = ()
    contract_users: tuple[UUID | None, UUID | None] = (None, None)


@dataclass(frozen=True)
class NativeReferenceRows:
    contract: Contract | None
    locations: tuple[ServiceLocation, ...]


def assert_native_reference_clean(db: AsyncSession) -> None:
    """Reject pending state before discovery; never flush or discard it."""
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Native references require clean entry; roll back the entire root")


def _changed_parent() -> None:
    raise HTTPException(409, "Данные изменились одновременно; повторите запрос")


def native_reference_plan(actor_id: UUID, company_id: UUID, home_company_id: UUID | None,
                          type_codes: tuple[str, ...] = (), *,
                          reference_users: tuple[UUID, ...] = (),
                          reference_companies: tuple[UUID, ...] = ()) -> LockPlan:
    """Exact native policy keys; the frozen helper sorts physical acquisition."""
    companies = ({company_id} | set(reference_companies)
                 | ({home_company_id} if home_company_id is not None else set()))
    requests = [LockRequest(CompanyKey(cid), S) for cid in sorted(companies)]
    requests.extend(LockRequest(UserKey(uid), S) for uid in sorted({actor_id} | set(reference_users)))
    requests.extend((LockRequest(MemberKey(company_id, actor_id), S),
                     LockRequest(RefCompositeKey(company_id), S)))
    requests.extend(LockRequest(TypeCatalogKey(code), S) for code in sorted(set(type_codes)) if code)
    return LockPlan(tuple(requests))


def discover_native_reference_user(value: str | None) -> UUID | None:
    """Только кандидат для плана: прежний _req_val выдаёт ошибку позднее."""
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError):
        return None


def require_native_reference_write(db: AsyncSession, prepared: NativeReferenceWrite) -> None:
    if (type(prepared) is not NativeReferenceWrite
            or prepared.plan is not prepared.capability.plan):
        raise ScopedLockError("Native reference preparation required; roll back the entire root")
    require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
    actor_state = inspect(prepared.actor)
    if actor_state.identity != (prepared.actor_id,) or actor_state.session is not db.sync_session:
        raise ScopedLockError("Prepared actor identity/session changed; roll back the entire root")
    require_scoped_locks(db.sync_session, prepared.capability, (
        LockRequest(CompanyKey(prepared.company_id), S),
        LockRequest(RefCompositeKey(prepared.company_id), S),
        LockRequest(UserKey(prepared.actor_id), S),
        LockRequest(MemberKey(prepared.company_id, prepared.actor_id), S),
    ))
    require_scoped_locks(db.sync_session, prepared.capability, tuple(
        LockRequest(UserKey(uid), S) for uid, exists, home in prepared.user_pointers))


async def assert_native_reference_member(
    db: AsyncSession, prepared: NativeReferenceWrite, company_ref: str,
) -> UUID:
    """A slug may move while waiting; never admit an unplanned company.

    Resolve scalars first, then repeat the actual native policy for the held
    company. Company SHARE keeps that company's existence/slug stable here.
    """
    require_native_reference_write(db, prepared)
    with db.no_autoflush:
        cid = await resolve_company_id(company_ref, db)
        if cid != prepared.company_id:
            _changed_parent()
        set_request_organization(prepared.organization_selector)
        return await assert_company_member(str(cid), prepared.actor, db)


async def prepare_native_reference_write(
    db: AsyncSession, actor: User, company_id: UUID, *, contract_id: UUID | None = None,
    type_change: bool = False, type_code: str | None = None,
    responsible_id: str | None = None, organization_selector=_UNSET,
) -> NativeReferenceWrite:
    assert_native_reference_clean(db)
    # Expired retained Users must not cause a synchronous attribute load.
    identity = inspect(actor).identity
    aid = identity[0] if identity is not None else actor.id
    incoming_org = current_organization() if organization_selector is _UNSET else organization_selector
    with db.no_autoflush:
        old_type = None
        old_users = (None, None)
        if contract_id is not None:
            target = (await db.execute(select(Contract.company_id, Contract.type_code,
                Contract.responsible_id, Contract.creation_actor_id).where(
                Contract.id == contract_id))).one_or_none()
            if target is not None:
                if target[0] != company_id:
                    _changed_parent()
                old_type = target[1]
                old_users = (target[2], target[3])
        user_ids = {aid} | {uid for uid in (*old_users, discover_native_reference_user(responsible_id))
                            if uid is not None}
        user_pointers = []
        for uid in sorted(user_ids):
            pointer = (await db.execute(select(User.company_id).where(User.id == uid))).one_or_none()
            user_pointers.append((uid, pointer is not None, pointer[0] if pointer is not None else None))
        actor_pointer = next(pointer for pointer in user_pointers if pointer[0] == aid)
        home = actor_pointer[2]
        # Нет вымышленного Company для отсутствующего User; его UUID всё равно защищён.
        companies_before = {company_id} | {home for uid, exists, home in user_pointers if home is not None}
        codes = tuple(code for code in (type_code, old_type if type_change else None) if code)
        plan = native_reference_plan(aid, company_id, home, codes,
            reference_users=tuple(sorted(user_ids)), reference_companies=tuple(sorted(companies_before)))
        capability = await acquire_scoped_locks_async(db, plan)
        require_scoped_locks(db.sync_session, capability, plan.requests)
        # No authority/reference row lock may precede these two legacy waits.
        await lock_manual_creation(db, company_id, "counterparty")
        require_scoped_locks(db.sync_session, capability, plan.requests)
        await lock_manual_creation(db, company_id, "contract")
        require_scoped_locks(db.sync_session, capability, plan.requests)
        assert_native_reference_clean(db)
        # Full expiry of clean retained references makes get()/matcher observe
        # rows current after ALL barriers; no pending state may be discarded.
        for row in tuple(db.sync_session.identity_map.values()):
            if type(row) in _REFERENCE_ROWS:
                db.sync_session.expire(row)
        companies = []
        for cid in sorted(companies_before):
            company = (await db.execute(select(Company).where(Company.id == cid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            if company is not None:
                companies.append(company)
            else:
                _changed_parent()
        users = {}
        # Канонический числовой UUID-порядок до любых reference/Contract row locks.
        for uid, existed, old_home in user_pointers:
            pointer = (await db.execute(select(User.company_id).where(User.id == uid))).one_or_none()
            if uid == aid and pointer is None:
                raise HTTPException(401, "Пользователь не найден")
            if (pointer is not None) != existed or (pointer is not None and pointer[0] != old_home):
                _changed_parent()
            user = (await db.execute(select(User).where(User.id == uid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            if uid == aid and user is None:
                raise HTTPException(401, "Пользователь не найден")
            if (user is not None) != existed or (user is not None and user.company_id != old_home):
                _changed_parent()
            users[uid] = user
        fresh_actor = users[aid]
        if not actor_pointer[1] or fresh_actor.company_id != home:
            _changed_parent()
        member = (await db.execute(select(UserCompany).where(
            UserCompany.user_id == aid, UserCompany.company_id == company_id)
            .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
        if contract_id is not None:
            # Populate the caller's retained Contract before get_owned reads
            # its parent. No admission/read of another company's membership.
            owner = (await db.execute(select(Contract.company_id, Contract.responsible_id,
                Contract.creation_actor_id).where(Contract.id == contract_id))).one_or_none()
            if owner is not None and (owner[0] != company_id or (owner[1], owner[2]) != old_users):
                _changed_parent()
            (await db.execute(select(Contract).where(
                Contract.id == contract_id, Contract.company_id == company_id)
                .execution_options(populate_existing=True))).scalar_one_or_none()
        prepared = NativeReferenceWrite(company_id, aid, capability, plan, fresh_actor, member,
            tuple(companies), contract_id, type_change, old_type, incoming_org,
            tuple(user_pointers), old_users)
        require_native_reference_write(db, prepared)
        await check_native_reference_authority(db, prepared)
        return prepared


async def check_native_reference_authority(db: AsyncSession, prepared: NativeReferenceWrite) -> None:
    """Fresh native session/visit when present; direct native Users need no JWT.

    The caller repeats its original get_owned/assert_company_member after all
    waits. No admin role requirement, presence write or internal completion.
    """
    require_native_reference_write(db, prepared)
    set_request_organization(prepared.organization_selector)
    claims = current_token_claims()
    if claims is not None:
        assert_native_reference_clean(db)
        # _check_visit uses get(); a retained PartnerSpace is not authority.
        for row in tuple(db.sync_session.identity_map.values()):
            if type(row) is PartnerSpace:
                db.sync_session.expire(row)
        actor = await native_user_from_claims(claims, db)
        if actor.id != prepared.actor_id:
            _changed_parent()
        await native_visit_from_claims(claims, actor, db)
    require_native_reference_write(db, prepared)


async def lock_native_reference_rows(
    db: AsyncSession, prepared: NativeReferenceWrite, *, parties: bool = False,
    counterparty_id: UUID | None = None, organization_id: UUID | None = None,
    location_ids: tuple[str, ...] = (),
) -> NativeReferenceRows:
    """Readonly reference rows precede Contract UPDATE; opaque locations stay opaque.

    Call after repeating historical admission against the refreshed authority.
    This function is a single phase, not a second B acquisition or LocationSet.
    """
    require_native_reference_write(db, prepared)
    assert_native_reference_clean(db)
    cid, uid = prepared.company_id, prepared.contract_id
    with db.no_autoflush:
        pointer = None
        if uid is not None:
            pointer = (await db.execute(select(
                Contract.company_id, Contract.counterparty_id, Contract.organization_id, Contract.type_code,
                Contract.responsible_id, Contract.creation_actor_id,
            ).where(Contract.id == uid))).one_or_none()
            if pointer is not None and (pointer[0] != cid or
                    (prepared.type_change and pointer[3] != prepared.old_type_code)
                    or (pointer[4], pointer[5]) != prepared.contract_users):
                _changed_parent()
        if parties:
            for model, references in (
                (Counterparty, {counterparty_id, pointer[1] if pointer else None}),
                (Organization, {organization_id, pointer[2] if pointer else None}),
            ):
                for reference_id in sorted(ref for ref in references if ref is not None):
                    (await db.execute(select(model).where(model.id == reference_id, model.company_id == cid)
                        .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
                    require_native_reference_write(db, prepared)
        locations = ()
        if location_ids:
            locations = tuple((await db.execute(select(ServiceLocation).where(
                ServiceLocation.company_id == cid, ServiceLocation.id.in_(location_ids))
                .order_by(ServiceLocation.id).with_for_update(read=True)
                .execution_options(populate_existing=True))).scalars().all())
            require_native_reference_write(db, prepared)
        contract = None
        if uid is not None:
            contract = (await db.execute(select(Contract).where(Contract.id == uid, Contract.company_id == cid)
                .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
            require_native_reference_write(db, prepared)
            if contract is None:
                owner = (await db.execute(select(Contract.company_id).where(
                    Contract.id == uid))).scalar_one_or_none()
                if owner is not None and owner != cid:
                    _changed_parent()
            if contract is not None and pointer is not None and (
                    contract.counterparty_id != pointer[1] or contract.organization_id != pointer[2]
                    or (prepared.type_change and contract.type_code != pointer[3])
                    or (contract.responsible_id, contract.creation_actor_id) != prepared.contract_users):
                _changed_parent()
        await check_native_reference_authority(db, prepared)
        require_native_reference_write(db, prepared)
        return NativeReferenceRows(contract, locations)
