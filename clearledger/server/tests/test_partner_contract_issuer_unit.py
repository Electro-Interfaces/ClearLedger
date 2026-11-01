"""AUTHOR ONLY / NOTRUN, including collection. Source assertions use stdlib.

Positive authority, token parsing and SQL evidence are exercised ONLY by the
separately admitted real PG definitions, never by a fabricated unit verifier.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "app/services/partner_identity.py"
AUTHORITY = ROOT / "app/services/partner_contract_authority.py"
COMMAND = ROOT / "app/services/partner_contract_commands.py"


def node(path, name, owner=None):
    body = ast.parse(path.read_bytes()).body
    if owner:
        body = next(n for n in body if isinstance(n, ast.ClassDef) and n.name == owner).body
    return next(n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def calls(n, name):
    return [c for c in ast.walk(n) if isinstance(c, ast.Call) and (
        isinstance(c.func, ast.Name) and c.func.id == name or
        isinstance(c.func, ast.Attribute) and c.func.attr == name)]


def test_single_b_discovery_freeze_and_legacy_seam_precede_canonical_rows():
    n = node(IDENTITY, "_prepare_partner_write")
    b, = calls(n, "acquire_scoped_locks")
    freeze, = calls(n, "freeze")
    legacy, = calls(n, "after_b")
    row, = calls(n, "with_for_update")
    assert calls(n, "discover")[0].lineno < freeze.lineno < b.lineno < legacy.lineno < row.lineno
    assert calls(n, "checkpoint")[-1].lineno > row.lineno
    after_b = node(AUTHORITY, "after_b", "CreateOperation")
    assert "('counterparty', 'contract')" in ast.unparse(after_b)
    assert calls(after_b, "checkpoint")[0].lineno > calls(after_b, "lock_manual_creation")[0].lineno


def test_create_purpose_is_exact_and_does_not_change_native_profile_cleanup():
    source = ast.unparse(node(IDENTITY, "_prepare_partner_write"))
    assert "create_purpose = mutation == 'contract-create'" in source
    assert "type(contract_profile) is not CreateOperation" in source
    assert "actor is not None or native is not None" in source
    profile = ROOT / "app/services/partner_contract_profiles.py"
    assert not calls(node(profile, "discover", "ProfileOperation"), "live_grant")
    replace_profile = ast.unparse(node(profile, "replace_partner_contract_create_profile"))
    assert "profile.user_enabled = profile.service_enabled = False" in replace_profile


def test_sql_stamp_and_admission_are_exact_registered_instances_not_dataclass_values():
    issue = ast.unparse(node(AUTHORITY, "_prepare"))
    require = ast.unparse(node(AUTHORITY, "_require"))
    assert "_ISSUED[stamp] = _Issued(" in issue
    for predicate in ("issued.admission() is not admission", "issued.session() is not db",
                      "issued.root() is not db.get_transaction()", "issued.connection() is not db.connection()",
                      "issued.generation != admission._stamp.generation"):
        assert predicate in require
    assert "canonical_contract_create_bytes(body) != issued.body_bytes" in require
    assert "body.creationKey != issued.namespace[-1]" in require
    assert calls(node(AUTHORITY, "_require"), "require_scoped_locks")
    assert calls(node(AUTHORITY, "_require"), "checkpoint")


def test_full_sql_sets_and_original_absence_are_requeried_before_live_policy():
    n = node(AUTHORITY, "recheck", "CreateOperation")
    source = ast.unparse(n)
    for frozen in ("expected_profile", "expected_receipt", "identity_rows", "installation_sets",
                   "credential_sets", "guards", "types", "previous_card_locations"):
        assert frozen in source
    assert calls(n, "profile_snapshot")[0].lineno < calls(n, "verify_locked_partner_access")[0].lineno
    assert calls(n, "verify_locked_partner_access")[0].lineno < calls(n, "policy")[0].lineno
    assert not calls(n, "acquire_scoped_locks") and not calls(n, "LockPlan")


def test_empty_scopes_and_every_location_have_explicit_intersections():
    source = ast.unparse(node(AUTHORITY, "policy", "CreateOperation"))
    for fragment in ("WRITE_SCOPE not in current.scopes", "not profile['service_enabled']",
                     "not profile['user_enabled']", "current.own_organization_id", "current.location_ids",
                     "member.object_scope is not None", "loc not in locs", "not locations"):
        assert fragment in source
    assert "current.resource_scopes.get('objects')" in source
    assert "current.resource_scopes.get('counterparties')" in source
    assert "current.resource_scopes.get('contracts')" not in source
    permits = ast.unparse(node(AUTHORITY, "_permits"))
    assert "scope.mode == 'ALL'" in permits and "scope.mode == 'SET'" in permits
    assert "or not scope.ids" not in permits


def test_replay_original_binding_checked_before_hash_conflict_or_return():
    discovery = ast.unparse(node(AUTHORITY, "discover", "CreateOperation"))
    for field in ("original_grant_id", "client_id", "create_profile_id", "actor_kind", "actor_key",
                  "current_user_id", "current_contract_id", "created_organization_id", "created_counterparty_id"):
        assert field in discovery
    command = node(COMMAND, "create_partner_contract")
    conflict = next(n for n in ast.walk(command) if isinstance(n, ast.If)
                    and "operation.previous.request_hash != operation.request_hash" == ast.unparse(n.test))
    assert calls(command, "prepare_create")[0].lineno < calls(command, "_require")[0].lineno < conflict.lineno
    assert "Contract identity conflicts" in ast.unparse(command)
    assert "join(sorted" not in ast.unparse(command)


def test_actual_card_primitives_and_atomic_parent_before_child_flushes():
    n = node(COMMAND, "create_partner_contract")
    assert len(calls(n, "create_contract_card")) == len(calls(n, "find_contract_card_duplicates")) == 1
    assert calls(n, "contract_identity")
    source = ast.unparse(n)
    assert "creation_key=None" in source and "creation_actor_id=None" in source and "creation_request_hash=None" in source
    assert source.index("intent = Intent(") < source.index("db.add(intent)") < source.index("db.add_all([IntentLocation(")
    assert calls(n, "AuditEvent") and calls(n, "ContractLocation")
    for flush in calls(n, "flush") + calls(n, "create_contract_card"):
        assert any(check.lineno > flush.lineno for check in calls(n, "require_create"))
    for forbidden in ("commit", "begin_nested", "create_native_contract", "log_audit", "notify", "create_task"):
        assert not calls(n, forbidden)
    handler = next(h for t in ast.walk(n) if isinstance(t, ast.Try) for h in t.handlers)
    assert ast.unparse(handler.type) == "BaseException" and calls(handler, "rollback")


def test_no_secondary_session_engine_issuer_or_http_activation_surface():
    for path in (AUTHORITY, COMMAND):
        tree = ast.parse(path.read_bytes())
        for forbidden in ("create_async_engine", "sessionmaker", "async_sessionmaker", "LockPlan",
                          "acquire_scoped_locks", "prepare_native_reference_write", "resolve"):
            assert not calls(tree, forbidden)
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert not any("router." in ast.unparse(d) for d in n.decorator_list)
