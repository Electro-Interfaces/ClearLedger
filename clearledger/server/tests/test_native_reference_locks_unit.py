"""AUTHORED / NOTRUN: native plan and clean-entrance behavior, actual helper.

ROOT must review an isolated preimport composition BEFORE imports/collection.
Repository conftest may import app and DROP schemas before this guard. No
runner, schema creation, fallback connection or execution approval is provided.
"""
import os
from urllib.parse import urlsplit

_URL = os.environ.get("NATIVE_REFERENCE_R1_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (
    _URL and _URL == os.environ.get("NATIVE_REFERENCE_R1_ROOT_APPROVED_URL")
    and _URL == os.environ.get("DATABASE_URL") == os.environ.get("TEST_DATABASE_URL")
    and os.environ.get("NATIVE_REFERENCE_R1_APPROVAL") == "ROOT-reviewed-synthetic-native-r1-v1"
    and _TARGET.scheme == "postgresql+asyncpg" and _TARGET.hostname == "127.0.0.1"
    and _TARGET.port and _TARGET.password
    and _TARGET.path == "/api_native_reference_r1_test_20261101"
    and not _TARGET.query and not _TARGET.fragment
):
    raise RuntimeError("Separate ROOT-reviewed native R1 preimport composition required")

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services import contract_write_locks as locks
from app.services import native_reference_locks as native

S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE


def test_actual_native_plan_has_shared_authority_and_contract_only_reference_keys():
    actor, company, home = uuid4(), uuid4(), uuid4()
    plan = native.native_reference_plan(actor, company, home)
    assert set((r.key, r.mode) for r in plan.requests) == {
        (locks.UserKey(actor), S), (locks.CompanyKey(company), S), (locks.CompanyKey(home), S),
        (locks.MemberKey(company, actor), S), (locks.RefCompositeKey(company), S),
    }
    assert all(r.mode is S for r in plan.requests)
    assert [(r.namespace, r.key) for r in plan.locks] == sorted((r.namespace, r.key) for r in plan.locks)


def test_catalog_keys_preserve_exact_codes_without_active_policy_or_normalization():
    plan = native.native_reference_plan(uuid4(), uuid4(), None, ("", "Type-A", " type-a ", "Type-A"))
    assert {r.key.type_code for r in plan.requests if type(r.key) is locks.TypeCatalogKey} == {
        "Type-A", " type-a ",
    }
    assert all(r.mode is S for r in plan.requests)


def test_home_company_can_be_absent_and_named_role_is_not_native_admission():
    actor, company = uuid4(), uuid4()
    plan = native.native_reference_plan(actor, company, None)
    assert len(plan.requests) == 4
    assert not any(type(r.key) is locks.RoleKey for r in plan.requests)


@pytest.mark.parametrize("value", [None, "", "bad", " ", "0", False])
def test_reference_user_discovery_defers_invalid_input_to_original_req_value(value):
    assert native.discover_native_reference_user(value) is None


def test_reference_users_add_only_exact_user_and_actual_company_keys():
    actor, company, ref, foreign = uuid4(), uuid4(), uuid4(), uuid4()
    assert native.discover_native_reference_user(str(ref)) == ref
    plan = native.native_reference_plan(actor, company, None,
        reference_users=(ref,), reference_companies=(foreign,))
    keys = {r.key for r in plan.requests}
    assert keys == {locks.UserKey(actor), locks.UserKey(ref), locks.CompanyKey(company),
                    locks.CompanyKey(foreign), locks.MemberKey(company, actor),
                    locks.RefCompositeKey(company)}
    assert all(r.mode is S for r in plan.requests)


@pytest.mark.parametrize("bad", ["not-a-uuid", str(uuid4()), None])
def test_actual_helper_rejects_unvalidated_actor_keys(bad):
    with pytest.raises(TypeError):
        native.native_reference_plan(bad, uuid4(), None)


@pytest.mark.asyncio
async def test_dirty_entrance_rejects_before_discovery_without_flush_or_discard(monkeypatch):
    async with AsyncSession() as db:
        row = User(id=uuid4(), email="synthetic@unit.invalid", password_hash="synthetic", name="Synthetic")
        db.add(row)
        async def forbidden(*args, **kwargs):
            raise AssertionError("Dirty entry must fail before I/O")
        monkeypatch.setattr(db, "execute", forbidden)
        monkeypatch.setattr(db, "flush", forbidden)
        with pytest.raises(locks.ScopedLockError, match="clean entry"):
            await native.prepare_native_reference_write(db, row, uuid4())
        assert row in db.new and row.email == "synthetic@unit.invalid"


@pytest.mark.asyncio
async def test_constructed_capability_cannot_authorize_reference_command():
    actor = User(id=uuid4())
    company = uuid4()
    plan = native.native_reference_plan(actor.id, company, None)
    cap = locks.ScopedLockCapability(plan)
    prepared = native.NativeReferenceWrite(company, actor.id, cap, plan, actor, None, (), None, False, None)
    async with AsyncSession() as db:
        with pytest.raises(locks.ScopedLockError):
            native.require_native_reference_write(db, prepared)
        with pytest.raises(locks.ScopedLockError):
            native.require_native_reference_write(db, replace(prepared, company_id=uuid4()))
