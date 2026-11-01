"""Определения unit-приёмки P1; NOTRUN, включая collection.

Импорт conftest небезопасен без отдельной изоляции. Проверки ниже вызывают
настоящие plan/helper/route; подмены I/O не доказывают работу PostgreSQL.
"""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

A, U, C, HOME, ROLE, ORG = (UUID(int=i) for i in range(1, 7))


@pytest.mark.parametrize("options", [
    {}, {"account": True}, {"new_role_id": ROLE}, {"role_id": ROLE},
    {"account": True, "role_id": ROLE},
])
@pytest.mark.parametrize("self_target", [False, True])
def test_scope_flag_only_adds_shared_ref_without_changing_existing_modes(options, self_target):
    from app.services import native_user_role_locks as native
    from app.services import contract_write_locks as locks
    target = A if self_target else U
    args = dict(actor_id=A, target_id=target, company_id=C, companies=(C, HOME),
                member_pointers={A: (ROLE, "admin"), target: (ROLE, "user")}, **options)
    old = native.native_plan(**args)
    explicit = native.native_plan(**args, scope_org=False)
    scoped = native.native_plan(**args, scope_org=True)
    assert old.requests == explicit.requests
    assert scoped.requests == old.requests + (locks.LockRequest(locks.RefCompositeKey(C), native.S),)
    assert not any(isinstance(r.key, locks.RefCompositeKey) for r in old.requests)
    target_key = locks.MemberKey(C, target)
    assert any(r.key == target_key and r.mode == native.X for r in scoped.requests)
    for lock in old.locks:
        assert lock in scoped.locks


def test_scope_has_no_invented_company_for_global_account_operation():
    from app.services import native_user_role_locks as native
    from app.services import contract_write_locks as locks
    plan = native.native_plan(actor_id=A, target_id=U, company_id=None,
                              companies=(HOME,), member_pointers={}, scope_org=True)
    assert not any(isinstance(r.key, locks.RefCompositeKey) for r in plan.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
@pytest.mark.parametrize("entry", ["helper", "route", "refresh"])
async def test_pending_entry_is_rejected_without_sql_expiry_or_discard(pending, entry):
    from app.services import native_user_role_locks as native
    from app.services.contract_write_locks import ScopedLockError
    from app.routers import users_router
    marker = object()
    db = SimpleNamespace(new=set(), dirty=set(), deleted=set(), execute=AsyncMock(),
                         expire_all=AsyncMock(), rollback=AsyncMock(), flush=AsyncMock())
    setattr(db, pending, {marker})
    with pytest.raises(ScopedLockError, match="clean entry"):
        if entry == "helper":
            await native.prepare_native_write(db, None, company_id=C, target_id=U, scope_org=True)
        elif entry == "route":
            await users_router.set_member_scope("bad", None, db, None)
        else:
            await native._refresh_native_scope(db, None)
    for method in (db.execute, db.expire_all, db.rollback, db.flush):
        method.assert_not_called()
    assert getattr(db, pending) == {marker}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "partial_B"])
async def test_real_helper_never_touches_rows_or_completes_after_failed_initial_B(monkeypatch, failure):
    from app.services import native_user_role_locks as native
    from app.services.contract_write_locks import ScopedLockError
    import asyncio
    reads = []
    async def user_pointer(db, uid):
        reads.append("user")
        return (C, False)
    async def member_pointer(db, uid, cid):
        reads.append("member")
        return (None, "admin" if uid == A else "user")
    class Result:
        def one_or_none(self):
            return (None,)
        def scalar_one_or_none(self):
            return None
    class DB:
        new, dirty, deleted = (), (), ()
        no_autoflush = nullcontext()
        execute = AsyncMock(return_value=Result())
        commit, rollback, flush = AsyncMock(), AsyncMock(), AsyncMock()
        def expire_all(self):
            raise AssertionError("До полного B запрещён переход к строкам")
    db = DB()
    from app.models import User
    from sqlalchemy.orm import make_transient_to_detached
    actor = User(id=A)
    make_transient_to_detached(actor)
    error = asyncio.CancelledError() if failure == "cancel" else ScopedLockError("partial B")
    acquire = AsyncMock(side_effect=error)
    monkeypatch.setattr(native, "_user_pointer", user_pointer)
    monkeypatch.setattr(native, "_member_pointer", member_pointer)
    monkeypatch.setattr(native, "acquire_scoped_locks_async", acquire)
    with pytest.raises(type(error)):
        await native.prepare_native_write(db, actor, company_id=C,
                                           target_id=U, scope_org=True, scope_company_ref=str(C))
    assert acquire.await_count == 1
    assert reads == ["user", "user", "member", "member"]
    for call in db.execute.call_args_list:
        assert call.args[0]._for_update_arg is None
    for method in (db.commit, db.rollback, db.flush):
        method.assert_not_called()


@pytest.fixture
def route_io(monkeypatch):
    from app.routers import users_router as route
    events = []
    class Member:
        own_organization_id = ORG
        object_scope = ["old"]
        def __setattr__(self, key, value):
            events.append(("set", key, value))
            object.__setattr__(self, key, value)
    member = Member()
    actor = SimpleNamespace(id=A, email="fresh@example.invalid")
    target = SimpleNamespace(id=U, email="target@example.invalid")
    write = SimpleNamespace(actor=actor, target=target, member=member,
                            capability=object(), plan=SimpleNamespace(requests=()),
                            scope_organization_id=ORG)
    async def prepare(*args, **kwargs):
        events.append(("prepare", kwargs))
        return write
    async def refresh(*args):
        events.append(("refresh",))
        return write
    async def execute(stmt):
        assert not any(e[0] == "set" for e in events)
        events.append(("objects",))
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: ["own-object"]))
    async def audit(db, **kwargs):
        events.append(("audit", kwargs))
    async def commit():
        events.append(("commit",))
    async def response(*args, **kwargs):
        events.append(("response", args, kwargs))
        return {"synthetic": True}
    def require(*args):
        events.append(("require",))
    db = SimpleNamespace(new=(), dirty=(), deleted=(), no_autoflush=nullcontext(),
                         sync_session=object(), execute=AsyncMock(side_effect=execute),
                         commit=AsyncMock(side_effect=commit))
    monkeypatch.setattr(route, "require_company_admin", AsyncMock(return_value=C))
    monkeypatch.setattr(route, "prepare_native_write", prepare)
    monkeypatch.setattr(route, "_refresh_native_scope", refresh)
    monkeypatch.setattr(route, "require_scoped_locks", require)
    monkeypatch.setattr(route, "log_audit", audit)
    monkeypatch.setattr(route, "_resp", response)
    return SimpleNamespace(route=route, db=db, events=events, member=member,
                           write=write, actor=actor, target=target)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, "", " ", "bad", str(ORG)])
async def test_actual_route_resolves_all_reads_before_setters_and_keeps_audit_commit_response(route_io, raw):
    io = route_io
    from app.schemas import MemberScopeUpdate
    payload = MemberScopeUpdate(company_id="synthetic", object_scope=["own-object", "foreign"],
                                own_organization_id=raw)
    original_actor = SimpleNamespace(id=A, email="stale@example.invalid")
    io.write.scope_organization_id = None if raw is not None and raw != str(ORG) else ORG
    result = await io.route.set_member_scope(str(U), payload, io.db, original_actor)
    assert result == {"synthetic": True}
    prepare = next(e for e in io.events if e[0] == "prepare")[1]
    assert prepare["scope_org"] is True
    assert prepare["scope_company_ref"] == "synthetic"
    assert prepare["scope_organization_id"] == raw
    names = [e[0] for e in io.events]
    assert names.index("objects") < names.index("refresh") < names.index("set")
    assert names.index("set") < names.index("audit") < names.index("commit") < names.index("response")
    assert io.member.object_scope == ["own-object"]
    assert io.member.own_organization_id == io.write.scope_organization_id
    audit = next(e[1] for e in io.events if e[0] == "audit")
    assert audit == {"actor": io.actor, "company_id": C, "action": "member.scope",
                     "target": "target@example.invalid",
                     "details": {"objects": 1, "организация": str(io.member.own_organization_id)
                                 if io.member.own_organization_id else "все юрлица"}}
    io.db.commit.assert_awaited_once()
    assert io.events[-1][1][0] is io.target


@pytest.mark.asyncio
@pytest.mark.parametrize("objects", [None, [], ["  "]])
async def test_actual_route_empty_scope_is_all_and_null_org_retains(route_io, objects):
    from app.schemas import MemberScopeUpdate
    io = route_io
    await io.route.set_member_scope(str(U), MemberScopeUpdate(company_id=str(C), object_scope=objects),
                                    io.db, SimpleNamespace(id=A))
    assert io.member.object_scope is None
    assert io.member.own_organization_id == ORG
    io.db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_actual_route_stops_on_final_capability_failure_before_any_setter(route_io, monkeypatch):
    from app.schemas import MemberScopeUpdate
    from app.services.contract_write_locks import ScopedLockError
    io = route_io
    def lost(*args):
        raise ScopedLockError("root ended")
    monkeypatch.setattr(io.route, "require_scoped_locks", lost)
    with pytest.raises(ScopedLockError):
        await io.route.set_member_scope(str(U), MemberScopeUpdate(company_id=str(C)), io.db,
                                        SimpleNamespace(id=A))
    assert not any(e[0] in {"set", "audit", "commit"} for e in io.events)
