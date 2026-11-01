"""Clean native party command entrance; policy and completion stay with callers.

Card mutations exclude reference readers. Contact commands share the reference
barrier and hold their CP parent before the contact row. Organization deletion
and other owners are deliberately outside this entrance's supported commands.
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, current_token_claims, native_user_from_claims, native_visit_from_claims
from app.models import Company, Counterparty, CounterpartyContact, Organization, PartnerSpace, User, UserCompany
from app.scope import set_request_organization
from app.services.contract_write_locks import (
    CompanyKey, LockMode, LockPlan, LockRequest, MemberKey, RefCompositeKey,
    ScopedLockCapability, ScopedLockError, UserKey, acquire_scoped_locks_async,
    require_scoped_locks,
)
from app.services.reference_identity import lock_manual_creation
from app.utils import resolve_company_id


S, X = LockMode.SHARED, LockMode.EXCLUSIVE
_RETAINED = (Company, User, UserCompany, Counterparty, Organization, CounterpartyContact, PartnerSpace)


@dataclass(frozen=True)
class NativePartyWrite:
    company_id: UUID
    actor_id: UUID
    actor_home: UUID | None
    plan: LockPlan
    capability: ScopedLockCapability
    actor: User
    entity: str
    party_id: UUID | None
    contact_id: UUID | None
    organization_selector: UUID | None
    contact_pointer: tuple[UUID, UUID] | None = None


def assert_native_party_clean(db: AsyncSession) -> None:
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Native parties require clean entry; roll back the entire root")


def native_party_plan(actor_id: UUID, company_id: UUID, actor_home: UUID | None,
                      *, contacts: bool = False,
                      reference_companies: tuple[UUID, ...] = ()) -> LockPlan:
    if type(contacts) is not bool:
        raise TypeError("Exact contact-purpose flag required")
    companies = {company_id} | set(reference_companies) | ({actor_home} if actor_home is not None else set())
    requests = [LockRequest(CompanyKey(cid), S) for cid in sorted(companies)]
    requests.extend((LockRequest(UserKey(actor_id), S),
                     LockRequest(MemberKey(company_id, actor_id), S),
                     LockRequest(RefCompositeKey(company_id), S if contacts else X)))
    return LockPlan(tuple(requests))


def _changed_parent() -> None:
    raise HTTPException(409, "Данные изменились одновременно; повторите запрос")


def require_native_party_write(db: AsyncSession, prepared: NativePartyWrite) -> None:
    if (type(prepared) is not NativePartyWrite
            or prepared.plan is not prepared.capability.plan
            or prepared.entity not in ("counterparty", "organization", "contact")
            or (prepared.entity != "contact" and prepared.contact_id is not None)
            or (prepared.entity == "contact" and prepared.party_id is None)
            or (prepared.contact_id is not None and (type(prepared.contact_pointer) is not tuple
                or len(prepared.contact_pointer) != 2 or prepared.contact_pointer[1] != prepared.party_id))
            or (prepared.contact_id is None and prepared.contact_pointer is not None)):
        raise ScopedLockError("Native party preparation required; roll back the entire root")
    require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
    expected = native_party_plan(prepared.actor_id, prepared.company_id, prepared.actor_home,
        contacts=prepared.entity == "contact",
        reference_companies=(prepared.contact_pointer[0],) if prepared.contact_pointer else ())
    if prepared.plan != expected:
        raise ScopedLockError("Native party purpose changed; roll back the entire root")
    actor = inspect(prepared.actor)
    if (actor.session is not db.sync_session or actor.identity != (prepared.actor_id,)
            or actor.dict.get("company_id") != prepared.actor_home):
        raise ScopedLockError("Native party actor changed; roll back the entire root")


async def check_native_party_authority(db: AsyncSession, prepared: NativePartyWrite) -> None:
    """Repeat the native session/visit checks without presence or completion.

    The router repeats its original member/get_owned policy after the final wait.
    A direct native User without claims remains supported, as in native contracts.
    """
    require_native_party_write(db, prepared)
    assert_native_party_clean(db)
    set_request_organization(prepared.organization_selector)
    claims = current_token_claims()
    if claims is not None:
        for row in tuple(db.sync_session.identity_map.values()):
            if type(row) is PartnerSpace:
                db.sync_session.expire(row)
        actor = await native_user_from_claims(claims, db)
        if actor.id != prepared.actor_id:
            _changed_parent()
        await native_visit_from_claims(claims, actor, db)
    require_native_party_write(db, prepared)


async def assert_native_party_member(db: AsyncSession, prepared: NativePartyWrite,
                                     company_ref: str) -> UUID:
    require_native_party_write(db, prepared)
    with db.no_autoflush:
        cid = await resolve_company_id(company_ref, db)
        if cid != prepared.company_id:
            _changed_parent()
        set_request_organization(prepared.organization_selector)
        return await assert_company_member(str(cid), prepared.actor, db)


async def _check_pointers(db: AsyncSession, actor_id: UUID, home: UUID | None,
                          model, company_id: UUID, party_id: UUID | None,
                          contact_id: UUID | None, contact_pointer: tuple[UUID, UUID] | None) -> None:
    pointer = (await db.execute(select(User.company_id).where(User.id == actor_id))).one_or_none()
    if pointer is None:
        raise HTTPException(401, "Пользователь не найден")
    if pointer[0] != home:
        _changed_parent()
    if party_id is not None:
        owner = (await db.execute(select(model.company_id).where(model.id == party_id))).scalar_one_or_none()
        if owner is not None and owner != company_id:
            _changed_parent()
    if contact_id is not None:
        # Only an initially admitted id+CP child reaches this scalar recheck.
        # A surviving moved child is a conflict, never a late parent key.
        pointer = (await db.execute(select(CounterpartyContact.company_id,
            CounterpartyContact.counterparty_id).where(CounterpartyContact.id == contact_id))).one_or_none()
        if pointer is None:
            raise HTTPException(404, "Контакт не найден")
        if tuple(pointer) != contact_pointer:
            _changed_parent()


async def prepare_native_party_write(
    db: AsyncSession, actor: User, company_id: UUID, *, entity: str,
    party_id: UUID | None = None, contact_id: UUID | None = None,
    organization_selector: UUID | None = None,
    contact_pointer: tuple[UUID, UUID] | None = None,
) -> NativePartyWrite:
    """One complete B, legacy CP when needed, then fresh authority/party rows.

    Discovery may share an already-autobegun clean root. Call only before the
    command's first row/advisory/FK lock or pending write; cleanliness cannot
    prove that another caller did not previously flush SQL in that root.
    """
    assert_native_party_clean(db)
    if (entity not in ("counterparty", "organization", "contact")
            or (entity != "contact" and contact_id is not None)
            or (entity == "contact" and party_id is None)
            or (contact_id is not None and (type(contact_pointer) is not tuple
                or len(contact_pointer) != 2 or contact_pointer[1] != party_id))
            or (contact_id is None and contact_pointer is not None)):
        raise ScopedLockError("Explicit native party purpose and parent required")
    identity = inspect(actor).identity
    aid = identity[0] if identity is not None else actor.id
    model = Organization if entity == "organization" else Counterparty
    with db.no_autoflush:
        actor_pointer = (await db.execute(select(User.company_id).where(User.id == aid))).one_or_none()
        if actor_pointer is None:
            raise HTTPException(401, "Пользователь не найден")
        home = actor_pointer[0]
        if party_id is not None:
            owner = (await db.execute(select(model.company_id).where(model.id == party_id))).scalar_one_or_none()
            if owner is not None and owner != company_id:
                _changed_parent()
        if contact_id is not None:
            observed = (await db.execute(select(CounterpartyContact.company_id,
                CounterpartyContact.counterparty_id).where(
                CounterpartyContact.id == contact_id,
                CounterpartyContact.counterparty_id == party_id))).one_or_none()
            if observed is None:
                # Initial caller already admitted this child. Distinguish a
                # vanished row from a surviving moved pointer before any lock.
                await _check_pointers(db, aid, home, model, company_id, party_id,
                                      contact_id, contact_pointer)
            elif tuple(observed) != contact_pointer:
                _changed_parent()
        reference_companies = (contact_pointer[0],) if contact_pointer else ()
        companies = {company_id} | set(reference_companies) | ({home} if home is not None else set())
        plan = native_party_plan(aid, company_id, home, contacts=entity == "contact",
                                 reference_companies=reference_companies)
        capability = await acquire_scoped_locks_async(db, plan)
        require_scoped_locks(db.sync_session, capability, plan.requests)
        await _check_pointers(db, aid, home, model, company_id, party_id, contact_id, contact_pointer)
        require_scoped_locks(db.sync_session, capability, plan.requests)
        if entity == "counterparty":
            await lock_manual_creation(db, company_id, "counterparty")
            require_scoped_locks(db.sync_session, capability, plan.requests)
            await _check_pointers(db, aid, home, model, company_id, party_id, contact_id, contact_pointer)
            require_scoped_locks(db.sync_session, capability, plan.requests)
        assert_native_party_clean(db)
        for row in tuple(db.sync_session.identity_map.values()):
            if type(row) in _RETAINED:
                db.sync_session.expire(row)
        for cid in sorted(companies):
            company = (await db.execute(select(Company).where(Company.id == cid)
                .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
            require_scoped_locks(db.sync_session, capability, plan.requests)
            if company is None:
                _changed_parent()
        pointer = (await db.execute(select(User.company_id).where(User.id == aid))).one_or_none()
        if pointer is None:
            raise HTTPException(401, "Пользователь не найден")
        if pointer[0] != home:
            _changed_parent()
        require_scoped_locks(db.sync_session, capability, plan.requests)
        fresh_actor = (await db.execute(select(User).where(User.id == aid)
            .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
        require_scoped_locks(db.sync_session, capability, plan.requests)
        if fresh_actor is None:
            raise HTTPException(401, "Пользователь не найден")
        if fresh_actor.company_id != home:
            _changed_parent()
        # No Role row: the historical member/get_owned/verified policies don't read it.
        (await db.execute(select(UserCompany).where(
            UserCompany.user_id == aid, UserCompany.company_id == company_id)
            .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
        require_scoped_locks(db.sync_session, capability, plan.requests)
        await _check_pointers(db, aid, home, model, company_id, party_id, contact_id, contact_pointer)
        require_scoped_locks(db.sync_session, capability, plan.requests)
        if party_id is not None:
            pointer = (await db.execute(select(model.company_id).where(model.id == party_id))).scalar_one_or_none()
            if pointer is not None and pointer != company_id:
                _changed_parent()
            require_scoped_locks(db.sync_session, capability, plan.requests)
            party = (await db.execute(select(model).where(
                model.id == party_id, model.company_id == company_id)
                .with_for_update(read=entity == "contact")
                .execution_options(populate_existing=True))).scalar_one_or_none()
            require_scoped_locks(db.sync_session, capability, plan.requests)
            if party is None:
                owner = (await db.execute(select(model.company_id).where(model.id == party_id))).scalar_one_or_none()
                if owner is not None and owner != company_id:
                    _changed_parent()
        if contact_id is not None:
            await _check_pointers(db, aid, home, model, company_id, party_id, contact_id, contact_pointer)
            require_scoped_locks(db.sync_session, capability, plan.requests)
            (await db.execute(select(CounterpartyContact).where(
                CounterpartyContact.id == contact_id,
                CounterpartyContact.counterparty_id == party_id)
                .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
            require_scoped_locks(db.sync_session, capability, plan.requests)
        # Ownership/membership errors remain in the caller's native validators.
        # Recheck parent after the final contact wait without widening the plan.
        await _check_pointers(db, aid, home, model, company_id, party_id, contact_id, contact_pointer)
        prepared = NativePartyWrite(company_id, aid, home, plan, capability, fresh_actor,
                                    entity, party_id, contact_id, organization_selector, contact_pointer)
        await check_native_party_authority(db, prepared)
        return prepared
