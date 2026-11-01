"""AUTHORDEFINITIONS / NOTRUN, including collection; ROOT isolates conftest.

Actual plan/entrance/handler are called. Mocked I/O stops at failed issuance;
no fake capability, fake policy or fake handler success is used.
"""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

A, R, C, HOME, ROLE, O = (UUID(int=i) for i in range(1, 7))


@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
@pytest.mark.parametrize("entrance", ["helper", "handler", "refresh"])
@pytest.mark.asyncio
async def test_pending_stays_pending_without_io_or_internal_rollback(pending, entrance):
    from app.routers import docs_router
    from app.services import native_doc_create_locks as native
    from app.services.contract_write_locks import ScopedLockError
    marker = object()
    db = SimpleNamespace(new=set(), dirty=set(), deleted=set(), execute=AsyncMock(),
        flush=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock(), expire_all=AsyncMock())
    setattr(db, pending, {marker})
    with pytest.raises(ScopedLockError, match="clean entry"):
        if entrance == "helper":
            await native.prepare_doc_create(db, None, "invalid", kind_id="invalid")
        elif entrance == "handler":
            await docs_router.create_doc(None, db, None)
        else:
            await native.refresh_doc_create(db, None)
    assert getattr(db, pending) == {marker}
    for method in (db.execute, db.flush, db.commit, db.rollback, db.expire_all):
        method.assert_not_called()


def test_plan_covers_actual_role_home_users_and_absent_members_without_kind_namespace():
    from app.services import native_doc_create_locks as native
    from app.services import contract_write_locks as locks
    role_owner = UUID(int=99)
    plan = native.doc_create_plan(companies=(C, HOME, role_owner), users=(A, R, A),
        company_id=C, members=(A, R), role=(role_owner, ROLE))
    expected = {
        locks.CompanyKey(C), locks.CompanyKey(HOME), locks.CompanyKey(role_owner),
        locks.UserKey(A), locks.UserKey(R), locks.MemberKey(C, A), locks.MemberKey(C, R),
        locks.RoleKey(role_owner, ROLE), locks.RefCompositeKey(C),
    }
    assert {r.key for r in plan.requests} == expected
    assert all(r.mode is locks.LockMode.SHARED for r in plan.requests)
    assert len(plan.requests) == len(expected)
    assert [(l.namespace, l.key) for l in plan.locks] == sorted((l.namespace, l.key) for l in plan.locks)
    no_role = native.doc_create_plan(companies=(C,), users=(A,), company_id=C,
                                    members=(A,), role=None)
    assert not any(isinstance(r.key, locks.RoleKey) for r in no_role.requests)


@pytest.mark.parametrize("raw,expected", [(None, None), ("", None), ("malformed", None),
                                         (str(O).upper(), O), ("{" + str(O) + "}", O)])
def test_candidate_discovery_does_not_take_over_original_uuid_errors(raw, expected):
    from app.services.native_doc_create_locks import discover_doc_uuid
    assert discover_doc_uuid(raw) == expected


@pytest.mark.parametrize("failure", ["cancel", "partial_B"])
@pytest.mark.asyncio
async def test_failed_real_entrance_has_only_scalar_discovery_and_no_side_effects(monkeypatch, failure):
    from app.models import User
    from app.services import native_doc_create_locks as native
    from app.services.contract_write_locks import ScopedLockError
    from sqlalchemy.orm import make_transient_to_detached
    actor = User(id=A)
    make_transient_to_detached(actor)
    class Result:
        def one_or_none(self):
            return None
    db = SimpleNamespace(new=(), dirty=(), deleted=(), no_autoflush=nullcontext(),
        execute=AsyncMock(return_value=Result()), expire_all=AsyncMock(),
        flush=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock(), add=AsyncMock())
    monkeypatch.setattr(native, "resolve_company_id", AsyncMock(return_value=C))
    monkeypatch.setattr(native, "_user_pointer", AsyncMock(return_value=(HOME, False)))
    monkeypatch.setattr(native, "_member_pointer", AsyncMock(return_value=(ROLE, "user")))
    monkeypatch.setattr(native, "_owner", AsyncMock(return_value=(C,)))
    error = asyncio.CancelledError() if failure == "cancel" else ScopedLockError("partial B")
    acquire = AsyncMock(side_effect=error)
    monkeypatch.setattr(native, "acquire_scoped_locks_async", acquire)
    with pytest.raises(type(error)):
        await native.prepare_doc_create(db, actor, str(C), kind_id=str(O),
            organization_id=str(O), responsible_id=str(R))
    assert acquire.await_count == 1
    plan = acquire.call_args.args[1]
    from app.services.contract_write_locks import CompanyKey, RoleKey, MemberKey, RefCompositeKey
    assert {CompanyKey(C), CompanyKey(HOME), RoleKey(C, ROLE),
            MemberKey(C, A), MemberKey(C, R), RefCompositeKey(C)} <= {r.key for r in plan.requests}
    for call in db.execute.call_args_list:
        assert call.args[0]._for_update_arg is None
    for method in (db.expire_all, db.flush, db.commit, db.rollback, db.add):
        method.assert_not_called()
