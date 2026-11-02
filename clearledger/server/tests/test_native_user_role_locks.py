"""Authored unit/source acceptance cases, NOTRUN (including collection).

Repository conftest imports the app and configures a destructive test database
before test modules. ROOT must isolate collection; this file is not a safe runner.
"""
import ast
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
A, U, C, OLD, NEW = (UUID(int=i) for i in range(1, 6))
MEMBER_ROOTS = {
    "create_user", "update_user", "set_member_modules", "set_member_access",
    "set_member_scope", "set_member_business_grants", "set_member_contracts",
    "set_station_pin", "reset_sessions", "reset_2fa", "issue_reset_link",
    "remove_user", "grant_company", "revoke_company",
}
ACCOUNT_ROOTS = {"set_station_pin", "reset_sessions", "reset_2fa", "issue_reset_link", "remove_user"}


def functions(path):
    return {node.name: node for node in ast.parse((ROOT / path).read_text()).body
            if isinstance(node, ast.AsyncFunctionDef)}


def calls(node, name):
    # Только вызовы из тела, без метаданных определения функции.
    return [n for n in ast.walk(ast.Module(body=node.body, type_ignores=[])) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name)
                 or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def test_actual_writer_roots_enter_before_mutation_and_keep_commit_ownership():
    nodes = functions("app/routers/users_router.py")
    commits = {"set_member_access", "set_member_scope", "set_member_business_grants",
               "set_station_pin", "set_member_contracts", "reset_sessions", "reset_2fa"}
    for name in MEMBER_ROOTS:
        node = nodes[name]
        entrances = calls(node, "prepare_native_write")
        assert calls(node, "assert_native_clean")[0].lineno < min(n.lineno for n in entrances)
        assert len(entrances) == (2 if name == "update_user" else 1)
        mutation_lines = [n.lineno for n in ast.walk(node) if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Attribute) for t in n.targets)]
        mutation_lines += [n.lineno for n in calls(node, "add") + calls(node, "delete")]
        assert max(n.lineno for n in entrances) < min(mutation_lines)
        assert len(calls(node, "commit")) == int(name in commits)
        assert not calls(node, "rollback")
        if name in ACCOUNT_ROOTS:
            assert any(k.arg == "account" and isinstance(k.value, ast.Constant)
                       and k.value.value is True for k in entrances[0].keywords)
    assert not calls(nodes["push_station_roster"], "prepare_native_write")
    roles = functions("app/routers/roles_router.py")
    for name in ("update_role", "delete_role"):
        assert len(calls(roles[name], "prepare_native_write")) == 1
        assert len(calls(roles[name], "commit")) == 1
    assert not calls(roles["create_role"], "prepare_native_write")


def test_complete_old_new_role_plan_and_absent_member():
    from app.services.native_user_role_locks import native_plan, S, X
    from app.services.contract_write_locks import UserKey, CompanyKey, RoleKey, MemberKey
    plan = native_plan(actor_id=A, target_id=U, company_id=C, companies=(C,),
                       member_pointers={A: (None, "admin"), U: (OLD, "user")}, new_role_id=NEW)
    requested = {(r.key, r.mode) for r in plan.requests}
    assert {(UserKey(A), S), (UserKey(U), S), (CompanyKey(C), S),
            (MemberKey(C, A), S), (MemberKey(C, U), X),
            (RoleKey(C, OLD), S), (RoleKey(C, NEW), S)} <= requested
    absent = native_plan(actor_id=A, target_id=U, company_id=C, companies=(C,),
                         member_pointers={A: (None, "admin"), U: None})
    assert any(r.key == MemberKey(C, U) and r.mode == X for r in absent.requests)


def test_account_and_self_actor_modes_merge_upfront():
    from app.services.native_user_role_locks import native_plan, S, X
    from app.services.contract_write_locks import UserKey, RoleKey, advisory_key
    plan = native_plan(actor_id=A, target_id=A, company_id=C, companies=(C,),
                       member_pointers={A: (OLD, "admin")}, account=True, role_id=OLD)
    for key in (UserKey(A), RoleKey(C, OLD)):
        ns, value = advisory_key(key)
        actual = [r for r in plan.locks if (r.namespace, r.key) == (ns, value)]
        assert len(actual) == 1 and actual[0].mode == X
    assert any(r.key == UserKey(A) and r.mode == S for r in plan.requests)


@pytest.mark.asyncio
async def test_dirty_entry_refuses_even_read_discovery():
    from app.services.native_user_role_locks import prepare_native_write
    from app.services.contract_write_locks import ScopedLockError
    class Dirty:
        new, dirty, deleted = (), (object(),), ()
        def execute(self, *args, **kwargs):
            raise AssertionError("dirty entrance must issue no SQL")
    with pytest.raises(ScopedLockError, match="clean entry"):
        await prepare_native_write(Dirty(), None, company_id=C, target_id=U)


def test_remove_and_role_delete_source_schedule():
    users = functions("app/routers/users_router.py")
    remove = users["remove_user"]
    assert calls(remove, "prepare_native_write")[0].lineno < calls(remove, "delete")[0].lineno
    assert len(calls(remove, "delete")) == 2  # member first, possible global account second
    source = ast.get_source_segment((ROOT / "app/routers/roles_router.py").read_text(),
                                   functions("app/routers/roles_router.py")["delete_role"])
    assert source.index("prepare_native_write") < source.index("select(UserCompany)")
    assert "UserCompany.company_id == cid" in source and ".with_for_update()" in source
    assert source.index("m.role_id = None") < source.index("db.delete(role)")


@pytest.mark.asyncio
@pytest.mark.parametrize("router,name,kwargs", [
    ("users", "reset_sessions", {"user_id": "bad", "company_id": "bad"}),
    ("users", "create_user", {"payload": None}),
    ("users", "set_member_access", {"user_id": "bad", "payload": None}),
    ("roles", "delete_role", {"role_id": "bad", "company_id": "bad"}),
])
async def test_actual_route_dirty_preflight_cannot_autoflush(router, name, kwargs):
    from app.routers import users_router, roles_router
    from app.services.contract_write_locks import ScopedLockError
    class Dirty:
        new, dirty, deleted = (object(),), (), ()
        def execute(self, *args, **kwargs):
            raise AssertionError("legacy auth/discovery must not flush dirty entry")
    module = users_router if router == "users" else roles_router
    with pytest.raises(ScopedLockError, match="clean entry"):
        await getattr(module, name)(db=Dirty(), current_user=None, **kwargs)
