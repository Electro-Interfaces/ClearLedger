"""OneC mixed catalog entrance; policy and transaction completion stay with callers.

Discovery is read only. Callers must enter before any row/FK/advisory write in
the root; a clean identity map cannot prove the absence of earlier flushed SQL.
"""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Contract, Counterparty, OneCConnection, Organization
from app.services.contract_write_locks import (
    CompanyKey, LockMode, LockPlan, LockRequest, RefCompositeKey,
    ScopedLockCapability, ScopedLockError, acquire_scoped_locks_async,
    require_scoped_locks,
)


@dataclass(frozen=True)
class CatalogRoot:
    connection_id: UUID
    company_id: UUID
    connection: OneCConnection
    plan: LockPlan
    capability: ScopedLockCapability


def assert_catalog_clean(db: AsyncSession) -> None:
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Catalogs require clean entry; roll back the entire root")


def catalog_root_plan(company_id: UUID) -> LockPlan:
    return LockPlan((
        LockRequest(CompanyKey(company_id), LockMode.SHARED),
        LockRequest(RefCompositeKey(company_id), LockMode.EXCLUSIVE),
    ))


def require_catalog_root(db: AsyncSession, prepared: CatalogRoot) -> None:
    if type(prepared) is not CatalogRoot or prepared.plan is not prepared.capability.plan:
        raise ScopedLockError("Catalog root preparation required; roll back the entire root")
    require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
    require_scoped_locks(db.sync_session, prepared.capability, (
        LockRequest(CompanyKey(prepared.company_id), LockMode.SHARED),
        LockRequest(RefCompositeKey(prepared.company_id), LockMode.EXCLUSIVE),
    ))
    state = inspect(prepared.connection)
    # Inspect loaded values without allowing an expired/foreign object to issue
    # implicit SQL. Every catalog stage uses this freshly loaded command object.
    if (state.session is not db.sync_session or state.identity != (prepared.connection_id,)
            or state.dict.get("id") != prepared.connection_id
            or state.dict.get("company_id") != prepared.company_id):
        raise ScopedLockError("Catalog connection changed; roll back the entire root")


async def prepare_catalog_root(db: AsyncSession, connection: OneCConnection) -> CatalogRoot:
    assert_catalog_clean(db)
    if not isinstance(connection, OneCConnection):
        raise ScopedLockError("Persisted OneCConnection required")
    identity = inspect(connection).identity
    if identity is None or len(identity) != 1 or type(identity[0]) is not UUID:
        raise ScopedLockError("Persisted OneCConnection identity required")
    connection_id = identity[0]
    with db.no_autoflush:
        company_id = (await db.execute(select(OneCConnection.company_id).where(
            OneCConnection.id == connection_id))).scalar_one_or_none()
        if company_id is None:
            raise ScopedLockError("Catalog connection no longer exists")
        plan = catalog_root_plan(company_id)
        capability = await acquire_scoped_locks_async(db, plan)
        require_scoped_locks(db.sync_session, capability, plan.requests)
        fresh_company = (await db.execute(select(OneCConnection.company_id).where(
            OneCConnection.id == connection_id))).scalar_one_or_none()
        require_scoped_locks(db.sync_session, capability, plan.requests)
        if fresh_company != company_id:
            raise ScopedLockError("Catalog company changed while waiting; roll back the entire root")
        # Parent first, only after the complete B plan. The scalar pointer is
        # checked again by the locked connection predicate, never widened.
        company = (await db.execute(select(Company.id).where(Company.id == company_id)
            .with_for_update(read=True))).scalar_one_or_none()
        require_scoped_locks(db.sync_session, capability, plan.requests)
        if company is None:
            raise ScopedLockError("Catalog company no longer exists")
        fresh = (await db.execute(select(OneCConnection).where(
            OneCConnection.id == connection_id, OneCConnection.company_id == company_id)
            .with_for_update(read=True).execution_options(populate_existing=True))).scalar_one_or_none()
        require_scoped_locks(db.sync_session, capability, plan.requests)
        if fresh is None:
            raise ScopedLockError("Catalog connection changed while waiting; roll back the entire root")
        assert_catalog_clean(db)
        # The org loop has no populate_existing. Expire its retained rows once,
        # before the first write; later expiry would discard this sync's edits.
        for row in tuple(db.sync_session.identity_map.values()):
            if type(row) in (Organization, Counterparty, Contract):
                db.sync_session.expire(row)
        prepared = CatalogRoot(connection_id, company_id, fresh, plan, capability)
        require_catalog_root(db, prepared)
        return prepared
