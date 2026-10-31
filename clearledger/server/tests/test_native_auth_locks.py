"""Auth account acceptance specifications: authored NOTRUN, even collection.

Parent conftest imports the application and can destroy schemas before this
module. These cases are not a runner or permission to collect ordinary pytest.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app/routers/auth_router.py"
ADAPTER = ROOT / "app/services/native_auth_locks.py"
WRITERS = ("login", "demo_session", "forgot_password", "reset_password",
           "change_password", "register", "logout_all", "twofa_setup",
           "twofa_enable", "twofa_disable")
SELF = ("change_password", "logout_all", "twofa_setup", "twofa_enable", "twofa_disable")
A, U, C, D = (UUID(int=i) for i in range(1, 5))


def functions(path):
    return {n.name: n for n in ast.parse(path.read_text()).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name)
                 or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


@pytest.mark.parametrize("name", WRITERS)
def test_actual_route_clean_check_precedes_discovery_and_writes(name):
    node = functions(ROUTER)[name]
    guard = calls(node, "assert_auth_clean")
    assert len(guard) == 1
    assert guard[0].lineno < min(n.lineno for n in calls(node, "prepare_auth_write"))
    for call in calls(node, "execute") + calls(node, "resolve_company_id"):
        assert guard[0].lineno < call.lineno
    mutations = [n.lineno for n in ast.walk(node) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Attribute) for t in n.targets)]
    mutations += [n.lineno for n in calls(node, "add")]
    assert min(n.lineno for n in calls(node, "prepare_auth_write")) < min(mutations)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", WRITERS)
async def test_dirty_actual_route_fails_before_any_select_or_side_effect(name):
    from app.routers import auth_router as routes
    from app.services.contract_write_locks import ScopedLockError
    class Dirty:
        new, dirty, deleted = (), (object(),), ()
        def execute(self, *args, **kwargs):
            raise AssertionError("SQL before clean entrance")
    db = Dirty()
    actor = SimpleNamespace(id=A, is_superadmin=True)
    arguments = {
        "login": dict(body=None, request=None), "demo_session": dict(request=None),
        "forgot_password": dict(body=None), "reset_password": dict(body=None),
        "change_password": dict(body=None, current_user=actor),
        "register": dict(body=None, current_user=actor),
        "logout_all": dict(response=None, current_user=actor),
        "twofa_setup": dict(current_user=actor),
        "twofa_enable": dict(body=None, current_user=actor),
        "twofa_disable": dict(body=None, current_user=actor),
    }
    with pytest.raises(ScopedLockError, match="clean entry"):
        await getattr(routes, name)(db=db, **arguments[name])


def test_plan_declares_account_exclusive_parents_and_absent_member():
    from app.services.native_auth_locks import auth_plan, S, X
    from app.services.contract_write_locks import CompanyKey, UserKey, MemberKey, advisory_key
    plan = auth_plan(target_id=U, actor_id=A, companies=(C, D), member_company=C)
    assert {(CompanyKey(C), S), (CompanyKey(D), S), (UserKey(A), S),
            (UserKey(U), X), (MemberKey(C, U), X)} == {(r.key, r.mode) for r in plan.requests}
    assert [(r.namespace, r.key) for r in plan.locks] == sorted(
        (r.namespace, r.key) for r in plan.locks)
    self_plan = auth_plan(target_id=A, actor_id=A, companies=())
    key = advisory_key(UserKey(A))
    actual = [r for r in self_plan.locks if (r.namespace, r.key) == key]
    assert len(actual) == 1 and actual[0].mode == X
    assert len(self_plan.requests) == 2  # full originals retained


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
async def test_adapter_clean_guard_precedes_pointer_discovery(pending):
    from app.services.native_auth_locks import prepare_auth_write
    from app.services.contract_write_locks import ScopedLockError
    class Dirty:
        new, dirty, deleted = (), (), ()
        def execute(self, *args, **kwargs):
            raise AssertionError("preflight autoflush")
    db = Dirty()
    setattr(db, pending, (object(),))
    with pytest.raises(ScopedLockError, match="clean entry"):
        await prepare_auth_write(db, target_id=U)


def test_adapter_single_entrance_and_frozen_policy_without_admin_acl():
    node = functions(ADAPTER)["prepare_auth_write"]
    source = ast.get_source_segment(ADAPTER.read_text(), node)
    assert len(calls(node, "acquire_scoped_locks_async")) == 1
    assert not any(calls(node, name) for name in ("commit", "rollback", "begin_nested"))
    assert source.index("assert_auth_clean(db)") < source.index("with db.no_autoflush:")
    assert source.index("acquire_scoped_locks_async") < source.index("db.expire_all()")
    assert source.index("select(Company)") < source.index("select(User)")
    assert source.index(".with_for_update") < source.index("native_user_from_claims(claims, db)")
    assert "native_visit_from_claims(claims, fresh_actor, db)" in source
    assert "populate_existing=True" in source
    assert "is_superadmin" not in source and "prepare_native_write" not in source


def test_source_commit_counts_and_inner_notice_share_login_capability():
    nodes = functions(ROUTER)
    counts = {"login": 3, "demo_session": 1, "forgot_password": 0,
              "reset_password": 0, "change_password": 1, "register": 0,
              "logout_all": 1, "twofa_setup": 1, "twofa_enable": 1, "twofa_disable": 1}
    for name, expected in counts.items():
        assert len(calls(nodes[name], "commit")) == expected
        assert len(calls(nodes[name], "rollback")) == int(name == "forgot_password")
    assert len(calls(nodes["login"], "prepare_auth_write")) == 1
    assert not calls(nodes["_notify_new_login"], "prepare_auth_write")
    assert len(calls(nodes["_notify_new_login"], "require")) == 1
    login = ast.get_source_segment(ROUTER.read_text(), nodes["login"])
    assert login.index("prepare_auth_write") < login.index("now = datetime.now")
    assert login.index("user.failed_logins =") < login.index("await db.commit()")
    assert login.index('action="auth.login_failed"') > login.index("await db.commit()")
    assert 'headers={"X-Need-OTP": "1"}' in login


def test_source_reset_consumes_current_hash_and_strict_expiry_after_wait():
    node = functions(ROUTER)["reset_password"]
    source = ast.get_source_segment(ROUTER.read_text(), node)
    assert source.index("prepare_auth_write") < source.index("user.reset_token_hash !=")
    assert source.index("user.reset_token_hash !=") < source.index("user.password_hash =")
    assert "user.reset_token_expires < datetime.now(timezone.utc)" in source
    assert not calls(node, "_valid_reset_user")  # preview helper is still read-only
    assert len(calls(functions(ROUTER)["reset_password_preview"], "_valid_reset_user")) == 1


def test_source_register_uuid_and_complete_plan_precede_first_add():
    node = functions(ROUTER)["register"]
    source = ast.get_source_segment(ROUTER.read_text(), node)
    assert source.index("user_id = uuid.uuid4()") < source.index("prepare_auth_write")
    assert source.index("member_company=company_uuid") < source.index("db.add(user)")
    assert "id=user_id," in source and "UserCompany(user_id=user.id, company_id=company_uuid)" in source
    assert source.count("if not current_user.is_superadmin:") == 2
    assert source.index("current_user = write.actor") < source.rindex("if not current_user.is_superadmin:")
    assert source.index("existing =") < source.index("resolve_company_id")


def test_invite_resend_classification_and_demo_exact_selector():
    nodes = functions(ROUTER)
    source = ast.get_source_segment(ROUTER.read_text(), nodes["forgot_password"])
    assert "target_id=None, companies=(cid,)" in source
    assert "Invitation.company_id == cid" in source and "Invitation.status == \"pending\"" in source
    assert source.index(".with_for_update()") < source.index("inv.token_hash =")
    assert source.index("inv.expires_at < datetime.now") < source.index("inv.token_hash =")
    assert "inv.token_hash, inv.status, inv.expires_at" in source
    demo = ast.get_source_segment(ROUTER.read_text(), nodes["demo_session"])
    assert demo.count("func.lower(User.email) == email") == 2
    assert "user.email.lower()" not in demo
    handlers = [n for n in ast.walk(nodes["forgot_password"]) if isinstance(n, ast.ExceptHandler)]
    conflicts = [n for n in handlers if isinstance(n.type, ast.Name) and n.type.id == "AuthIdentityChanged"]
    assert len(conflicts) == 1 and len(calls(conflicts[0], "rollback")) == 1
    assert ast.literal_eval(conflicts[0].body[-1].value) == {"ok": True}


@pytest.mark.parametrize("name", ["refresh_token", "gate_issue", "gate_check", "logout",
                                 "get_me", "my_logins", "my_devices", "revoke_device",
                                 "twofa_status", "reset_password_preview", "_valid_reset_user"])
def test_read_cookie_and_push_only_roots_do_not_claim_user_writer_authority(name):
    assert not calls(functions(ROUTER)[name], "prepare_auth_write")
