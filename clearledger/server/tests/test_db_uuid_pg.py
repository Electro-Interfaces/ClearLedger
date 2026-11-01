"""Фактическое чтение UUID через ORM; ROOT поднимает отдельную native БД."""
import os
from urllib.parse import urlsplit

_URL = os.environ.get("UUID_DRIVER_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (
    _URL and _URL == os.environ.get("UUID_DRIVER_ROOT_APPROVED_URL")
    and _URL == os.environ.get("DATABASE_URL") == os.environ.get("TEST_DATABASE_URL")
    and os.environ.get("UUID_DRIVER_APPROVAL") == "ROOT-reviewed-uuid-driver-boundary-v1"
    and _TARGET.scheme == "postgresql+asyncpg" and _TARGET.hostname == "127.0.0.1"
    and _TARGET.port and _TARGET.password
    and _TARGET.path == "/onec_catalog_root_synthetic_20261101"
    and not _TARGET.query and not _TARGET.fragment
):
    raise RuntimeError("Нужна отдельная ROOT-композиция UUID/native PostgreSQL")

from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, select, update

from app.models import Company, Contract, Counterparty, OneCConnection, Organization, User
from app.services.contract_write_locks import CompanyKey, LockPlan, LockRequest, LockMode, require_scoped_locks
from app.services.onec.catalog_root_locks import prepare_catalog_root
from app.services.counterparty_usage import counterparty_usage
from tests.test_onec_catalog_root_locks_pg import world

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_new_session_real_mapped_identity_and_parent_fields_are_exact_uuid(world):
    async with world.factory() as db:
        for model, identity, fields in [
            (Company, world.cid, ("id",)), (User, world.uid, ("id", "company_id")),
            (Counterparty, world.cp, ("id", "company_id")),
            (Organization, world.orgs[0], ("id", "company_id")),
            (Contract, world.contract, ("id", "company_id", "counterparty_id", "organization_id")),
            (OneCConnection, world.connection, ("id", "company_id")),
        ]:
            row = await db.get(model, identity)
            assert type(inspect(row).identity[0]) is UUID
            assert all(type(getattr(row, field)) is UUID for field in fields)
        connection = await db.get(OneCConnection, world.connection)
        prepared = await prepare_catalog_root(db, connection)
        assert type(prepared.connection_id) is type(prepared.company_id) is UUID
        require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
        assert LockPlan((LockRequest(CompanyKey(connection.company_id), LockMode.SHARED),))


async def test_typed_scalar_returning_refresh_and_nullable_results(world):
    async with world.factory() as db:
        connection = await db.get(OneCConnection, world.connection)
        values = (await db.execute(select(OneCConnection.id, OneCConnection.company_id).where(OneCConnection.id == world.connection))).one()
        assert all(type(value) is UUID for value in values)
        returned = (await db.execute(update(OneCConnection).where(OneCConnection.id == world.connection)
            .values(name="Synthetic UUID refresh " + uuid4().hex).returning(OneCConnection.id, OneCConnection.company_id))).one()
        assert all(type(value) is UUID for value in returned)
        await db.refresh(connection)
        assert type(inspect(connection).identity[0]) is type(connection.company_id) is UUID
        assert await db.scalar(select(Contract.responsible_id).where(Contract.id == world.contract)) is None
        await db.rollback()


async def test_real_uuid_dependency_is_reported_before_counterparty_delete(world):
    async with world.factory() as db:
        cp = await db.get(Counterparty, world.cp)
        assert "contracts" in await counterparty_usage(db, cp)
        assert cp not in db.deleted and not db.new and not db.dirty
