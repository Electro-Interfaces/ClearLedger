"""AUTHORED / NOTRUN, including imports and collection.

ROOT must isolate the repository conftest before any future execution.
"""
import ast
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OneCConnection
from app.services.contract_write_locks import CompanyKey, LockMode, RefCompositeKey, ScopedLockError
from app.services.onec.catalog_root_locks import catalog_root_plan, prepare_catalog_root


CID = UUID("00000000-0000-0000-0000-000000000101")
APP = Path(__file__).parents[1] / "app"


def test_catalog_plan_excludes_native_actor_authority_and_separates_companies():
    plan = catalog_root_plan(CID)
    assert [(type(r.key), r.mode) for r in plan.requests] == [
        (CompanyKey, LockMode.SHARED), (RefCompositeKey, LockMode.EXCLUSIVE)]
    assert all(r.key.company_id == CID for r in plan.requests)
    other = catalog_root_plan(UUID("00000000-0000-0000-0000-000000000102"))
    assert set(r.key for r in plan.requests).isdisjoint(r.key for r in other.requests)


@pytest.mark.parametrize("company", [None, str(CID), 1, True])
def test_company_identity_never_coerces(company):
    with pytest.raises(TypeError):
        catalog_root_plan(company)


@pytest.mark.asyncio
async def test_new_entry_is_refused_without_flush_or_discard():
    async with AsyncSession() as db:
        pending = OneCConnection(id=UUID(int=501), company_id=CID, name="Synthetic pending")
        db.add(pending)
        root = db.sync_session.get_transaction()
        with pytest.raises(ScopedLockError, match="clean entry"):
            await prepare_catalog_root(db, pending)
        assert pending in db.new
        assert db.sync_session.get_transaction() is root


@pytest.mark.asyncio
async def test_transient_connection_has_no_server_identity():
    async with AsyncSession() as db:
        with pytest.raises(ScopedLockError, match="Persisted OneCConnection identity"):
            await prepare_catalog_root(db, OneCConnection(id=UUID(int=502), company_id=CID))
        assert not db.in_transaction()


def test_actual_sync_entrance_precedes_first_log_and_preserves_stage_order():
    tree = ast.parse((APP / "services/onec/sync_service.py").read_text())
    service = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OneCSyncService")
    root = next(n for n in service.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "sync_catalogs")
    calls = sorted((n.lineno, ast.unparse(n.func)) for n in ast.walk(root) if isinstance(n, ast.Call))
    ordered = [name for _, name in calls]
    assert ordered.index("prepare_catalog_root") < ordered.index("self._start_log")
    stages = [name for name in ordered if name.startswith("self._sync_")]
    assert stages == ["self._sync_organizations", "self._sync_counterparties", "self._sync_contracts",
                      "self._sync_warehouses", "self._sync_nomenclature"]
    assert [a.arg for a in root.args.args] == ["self", "connection"]


def test_adapter_and_catalog_root_do_not_take_transaction_ownership():
    adapter = ast.parse((APP / "services/onec/catalog_root_locks.py").read_text())
    source = ast.parse((APP / "services/onec/sync_service.py").read_text())
    root = next(n for n in ast.walk(source) if isinstance(n, ast.AsyncFunctionDef) and n.name == "sync_catalogs")
    forbidden = {"commit", "rollback", "begin", "begin_nested", "close", "reset", "invalidate"}
    for node in (adapter, root):
        assert not [n for n in ast.walk(node) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr in forbidden]
    # The only flush stays in historical _start_log/leaf methods.
    assert not [n for n in ast.walk(adapter) if isinstance(n, ast.Attribute) and n.attr == "flush"]
