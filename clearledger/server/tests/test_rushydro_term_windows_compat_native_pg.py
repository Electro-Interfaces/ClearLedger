"""Export the five unchanged legacy window cases; native execution belongs to ROOT."""
import os
from urllib.parse import urlsplit

import pytest

FLAG = "RUN_RUSHYDRO_TERM_WINDOWS_COMPAT_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip("Explicit native window compatibility admission required", allow_module_level=True)
from tests.partner_test_safety import partner_test_safety_error
if partner_test_safety_error(os.environ, flag=FLAG):
    raise pytest.UsageError("Native window compatibility pre-import safety refused")
_target = urlsplit(os.environ["TEST_DATABASE_URL"])
if (os.environ.get("RUN_RUSHYDRO_PRODUCT_READS_TESTS") != "1"
        or os.environ.get("ROOT_APPROVED_RUSHYDRO_PRODUCT_READS") != "1"
        or os.environ.get("APP_ENV") != "test"
        or os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL")
        or (_target.hostname, _target.port, _target.path, _target.username) != (
            "127.0.0.1", 5432, "/api_rushydro_reads25_test_20261101", "clearledger")):
    raise pytest.UsageError("Exact external native READ admission required")

from uuid import UUID

import pytest_asyncio
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, OpsCostItem
from tests.test_rushydro_product_reads_native_pg import read_world
from tests.test_ops_term_windows import (
    test_overlapping_create_and_update_are_rejected,
    test_new_version_closes_old_window_and_preserves_history,
    test_invalid_windows_are_rejected,
    test_waiting_patch_checks_fresh_slot_after_concurrent_change,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Direct imports retain the original function objects, decorators and helper.
__all__ = [
    "test_overlapping_create_and_update_are_rejected",
    "test_new_version_closes_old_window_and_preserves_history",
    "test_invalid_windows_are_rejected",
    "test_waiting_patch_checks_fresh_slot_after_concurrent_change",
]
COMPANY_ID = UUID("a6701101-0000-4000-8000-000000000051")
COMPANY_NAME = "Synthetic legacy-window compatibility"
COST_ITEMS = {
    "synthetic-window-compat-20261101-a": "Synthetic legacy window A",
    "synthetic-window-compat-20261101-b": "Synthetic legacy window B",
}
# The unchanged helper selects global codes without active/order predicates.
# These two owned active rows ensure availability, not exclusive selection.


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def compat_seed(read_world):
    """Own rows only; ROOT supplies the shared pool and disposes the entire DB."""
    factory = read_world.factory
    assert getattr(factory, "_rushydro_native_reads_world") is read_world
    async with factory() as setup:
        try:
            assert isinstance(setup, AsyncSession)
            assert setup.bind.pool.size() == 8
            assert not setup.in_nested_transaction()
            assert await setup.scalar(text("SHOW transaction_isolation")) == "read committed"
            # Historical helper needs this exact slug. Never adopt an existing row.
            existing = (await setup.scalars(select(Company.id).where(or_(
                Company.slug == "gig", Company.id == COMPANY_ID)))).all()
            if existing:
                raise AssertionError("Synthetic compatibility company collision")
            existing_costs = (await setup.scalars(select(OpsCostItem.code).where(
                OpsCostItem.code.in_(COST_ITEMS)))).all()
            if existing_costs:
                raise AssertionError("Synthetic compatibility cost collision")
            setup.add(Company(id=COMPANY_ID, name=COMPANY_NAME, slug="gig", profile_id="energy"))
            setup.add_all([OpsCostItem(code=code, label=label, measure="fixed",
                default_estimate_basis="contract", is_active=True, sort_order=100)
                for code, label in COST_ITEMS.items()])
            await setup.commit()
            # Re-read persisted ownership, including both unique company selectors.
            company = (await setup.execute(select(Company.id, Company.name, Company.slug,
                Company.profile_id).where(or_(Company.slug == "gig", Company.id == COMPANY_ID)))).one()
            assert tuple(company) == (COMPANY_ID, COMPANY_NAME, "gig", "energy")
            costs = (await setup.execute(select(OpsCostItem.code, OpsCostItem.label,
                OpsCostItem.measure, OpsCostItem.default_estimate_basis, OpsCostItem.is_active,
                OpsCostItem.sort_order).where(OpsCostItem.code.in_(COST_ITEMS)))).all()
            assert {tuple(row) for row in costs} == {
                (code, label, "fixed", "contract", True, 100) for code, label in COST_ITEMS.items()}
        finally:
            await setup.rollback()
    return factory


@pytest_asyncio.fixture(loop_scope="session")
async def db(compat_seed):
    """Yield the actual shared-factory AsyncSession, without savepoints or proxies."""
    async with compat_seed() as session:
        try:
            assert isinstance(session, AsyncSession)
            assert not session.in_nested_transaction()
            yield session
        finally:
            await session.rollback()
    # The concurrent legacy case commits its own rows and uses the unchanged
    # app.database.async_session_factory. ROOT closes both engines in this loop.
