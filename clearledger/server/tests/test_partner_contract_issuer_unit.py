"""AUTHOR ONLY / NOTRUN, including collection. Source assertions use stdlib.

The exact row-order helper regression carries no authority. Positive authority,
token parsing and SQL evidence are exercised ONLY by the
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
    require, = (call for call in calls(command, "run_sync")
                if ast.unparse(call.func) == "db.run_sync" and call.args
                and isinstance(call.args[0], ast.Name) and call.args[0].id == "_require")
    assert calls(command, "prepare_create")[0].lineno < require.lineno < conflict.lineno
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


def test_both_location_snapshots_and_expected_rows_use_same_lossless_ordering():
    helper = node(AUTHORITY, "_location_rows")
    # No set, normalization, filtering, projection or SQL configuration here.
    assert ast.unparse(helper.body[-1]) == "return tuple(sorted(rows))"
    assert {c.func.id for c in ast.walk(helper) if isinstance(c, ast.Call)} == {"tuple", "sorted"}
    receipt = node(AUTHORITY, "receipt_snapshot", "CreateOperation")
    assert ast.unparse(receipt.body[-1]) == "return (intents, _location_rows(children))"
    recheck = node(AUTHORITY, "recheck", "CreateOperation")
    own, = (n for n in ast.walk(recheck) if isinstance(n, ast.Compare)
             and ast.unparse(n.comparators[0]) == "self.own_locations")
    assert isinstance(own.left, ast.Call) and own.left.func.id == "_location_rows"
    assert calls(own.left, "_rows")  # Fresh actual SQL rows, then Python order.
    command = node(COMMAND, "create_partner_contract")
    assignments = {ast.unparse(n.targets[0]): n.value for n in ast.walk(command)
                   if isinstance(n, ast.Assign) and len(n.targets) == 1}
    assert assignments["operation.own_locations"].func.id == "_location_rows"
    # expected_receipt is assigned twice; this is the final children snapshot.
    assert assignments["operation.expected_receipt"].elts[1].func.id == "_location_rows"


def test_location_rows_preserve_exact_ids_cardinality_and_duplicates():
    # AUTHORED NOTRUN: normal import only if ROOT later admits this definition.
    from app.services.partner_contract_authority import _location_rows
    from uuid import UUID
    parent = UUID("00000000-0000-0000-0000-000000000001")
    rows = ((parent, " zAa  "), (parent, " Zaa  "), (parent, " Яя  "))
    expected = _location_rows(rows)
    assert _location_rows(reversed(rows)) == expected
    assert len(expected) == len(rows) == 3
    assert _location_rows((*rows, rows[0])) != expected
    assert len(_location_rows((*rows, rows[0]))) == 4
    assert _location_rows(rows[:-1]) != expected
    for changed in (" zaa  ", "zAa", " zAa ", " ЯЯ  "):
        assert _location_rows((*rows[1:], (parent, changed))) != expected
    other = UUID("00000000-0000-0000-0000-000000000002")
    assert _location_rows(((other, rows[0][1]), *rows[1:])) != expected


def test_create_parent_stage_is_explicit_after_prefix_even_without_members():
    composer = node(IDENTITY, "_prepare_partner_write")
    stage_loop, = (n for n in ast.walk(composer) if isinstance(n, ast.For)
                   and ast.unparse(n.target) == "(stage_index, stage)")
    row_loop = stage_loop.body[0]
    assert isinstance(row_loop, ast.For) and ast.unparse(row_loop.iter) == "stage"
    boundary = stage_loop.body[1]
    assert isinstance(boundary, ast.If)
    assert ast.unparse(boundary.test) == "create_writer is not None and stage_index == 0"
    assert ast.unparse(boundary.body[0]) == "contract_profile.lock_parents()"
    assert len(stage_loop.body) == 2  # Boundary is outside the row loop.
    source = ast.unparse(composer)
    assert "row_stages = (ordered,)" in source
    assert "before_member = (Company, App, PartnerClient, User, CompanyRole)" in source
    assert "spec.model in before_member" in source
    assert "spec.model not in before_member and spec.model not in contract_profile.parent_models" in source
    assert calls(composer, "freeze")[0].lineno < calls(composer, "acquire_scoped_locks")[0].lineno
    assert calls(composer, "after_b")[0].lineno < stage_loop.lineno
    # ast.walk is breadth-first, so its last match need not be the final call.
    final_check = composer.body[-2]
    assert isinstance(final_check, ast.Expr)
    assert ast.unparse(final_check) == "writer.checkpoint()"
    assert stage_loop.end_lineno < final_check.lineno


def test_parent_stage_uses_only_frozen_union_fixed_order_and_checks_each_wait():
    tree = ast.parse(AUTHORITY.read_bytes())
    operation = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CreateOperation")
    parents, = (n for n in operation.body if isinstance(n, ast.Assign)
                and ast.unparse(n.targets[0]) == "parent_models")
    assert ast.unparse(parents.value) == "(Counterparty, Organization, ServiceLocation, Contract)"
    stage = node(AUTHORITY, "lock_parents", "CreateOperation")
    source = ast.unparse(stage)
    for fragment in ("for model in self.parent_models", "spec.identity[0]: spec for spec in self.ordered",
                     "self.guards", "canonical.keys()", "for rid in sorted(ids)",
                     "spec.statement().with_only_columns(model.id)", "model.company_id == self.company_id"):
        assert fragment in source
    lock, = calls(stage, "with_for_update")
    check, = calls(stage, "checkpoint")
    assert ast.unparse(lock.keywords[0].value) == "True" and lock.lineno < check.lineno
    inner, = (n for n in ast.walk(stage) if isinstance(n, ast.For) and ast.unparse(n.target) == "rid")
    assert ast.unparse(inner.body[-1]) == "writer.checkpoint()"
    for forbidden in ("discover", "guard", "acquire_scoped_locks", "LockPlan", "key", "flush"):
        assert not calls(stage, forbidden)
    assert not any(ast.unparse(call.func) == "db.get" for call in calls(stage, "get"))


def test_late_operation_locks_keep_profile_types_children_and_final_original_admission():
    late = node(AUTHORITY, "lock", "CreateOperation")
    source = ast.unparse(late)
    assert "parent_models" not in source and "self.guards" not in source
    for fragment in ("select(Profile.id)", "for code in sorted(self.types)", "for model, names in _CHILDREN",
                     "self.intent_statement()", "select(IntentLocation)", "select(ContractLocation)"):
        assert fragment in source
    prepare = node(AUTHORITY, "_prepare")
    late_call, = calls(prepare, "lock")
    checkpoint, = calls(prepare, "checkpoint")
    assert calls(prepare, "_prepare_partner_write")[0].lineno < late_call.lineno < checkpoint.lineno
    assert checkpoint.lineno < next(n.lineno for n in ast.walk(prepare) if isinstance(n, ast.Assign)
        and ast.unparse(n.targets[0]) == "generation")
