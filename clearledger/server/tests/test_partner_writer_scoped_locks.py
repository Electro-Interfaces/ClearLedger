"""AUTHORED / NOTRUN source oracles; no application imports or fake capabilities.

These definitions describe source contracts, not runtime lock/ACL acceptance.
Even collection was not executed by the author. Function-body traversal excludes
decorators, annotations and dependency defaults from call-order evidence.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "app/services/partner_identity.py"
ADMIN = ROOT / "app/routers/partner_admin_router.py"
OAUTH = ROOT / "app/routers/partner_oauth_router.py"


def tree(path):
    return ast.parse(path.read_bytes(), filename=str(path))


def symbol(path, name, owner=None):
    nodes = tree(path).body
    if owner:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == owner).body
    return next(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def body_nodes(node):
    # This intentionally does not walk ast.walk(function), which sees Depends
    # and route decorators as though they executed in the endpoint body.
    yield node
    children = node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else ast.iter_child_nodes(node)
    for child in children:
        yield from body_nodes(child)


def calls(node, name):
    return [n for n in body_nodes(node) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name)
                 or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def text(path, name, owner=None):
    return ast.get_source_segment(path.read_text(), symbol(path, name, owner))


def test_all_eight_admin_roots_enter_shared_composer_before_changes():
    via = {"register": "_prepare_partner_write", "client_status": "owned_client",
        "issue_credential": "owned_client", "revoke_credential": "owned_client",
        "approve_installation": "_prepare_partner_write", "revoke_installation": "admin_install",
        "machine_grant": "admin_install", "revoke_grant": "_prepare_partner_write"}
    for name, entrance in via.items():
        node = symbol(ADMIN, name)
        assert len(calls(node, entrance)) == 1
        assert len(calls(node, "finish")) == 1
        assert len(calls(node, "_native_authority")) == 1
        guards = calls(node, entrance)
        mutations = calls(node, "add") + calls(node, "flush") + calls(node, "execute")
        assert all(guards[0].lineno < mutation.lineno for mutation in mutations)


def test_oauth_seven_named_roots_and_three_token_branches_share_composition():
    # 8 admin + authorize/consent3/token3/revoke/userinfo = exact17.
    for name in ("authorize", "get_request", "approve", "deny", "userinfo"):
        assert len(calls(symbol(OAUTH, name), "_prepare_partner_write")) == 1
    dispatcher = text(OAUTH, "_protocol_response")
    assert all(label in dispatcher for label in ("token-code", "token-refresh", "token-machine", "revoke"))
    assert len(calls(symbol(OAUTH, "_protocol_response"), "_prepare_partner_write")) == 1
    for name in ("token", "revoke"):
        assert calls(symbol(OAUTH, name), "run_sync") and "_protocol_response" in text(OAUTH, name)


def test_discovery_has_one_full_plan_and_acquisition_before_row_locks():
    node = symbol(IDENTITY, "_prepare_partner_write")
    assert len(calls(node, "LockPlan")) == len(calls(node, "acquire_scoped_locks")) == 1
    acquire = calls(node, "acquire_scoped_locks")[0].lineno
    rowlocks = calls(node, "with_for_update")
    assert rowlocks and all(call.lineno > acquire for call in rowlocks)
    for forbidden in ("flush", "add", "add_all", "get_consent_grant", "begin_nested"):
        assert not calls(node, forbidden)
    assert "with db.no_autoflush" in text(IDENTITY, "_prepare_partner_write")


def test_row_protocol_is_canonical_share_or_update_and_tenant_before_lock():
    module = tree(IDENTITY)
    assignment = next(n for n in module.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "_ROW_ORDER" for t in n.targets))
    assert [n.id for n in assignment.value.elts] == ["Company", "App", "PartnerClient", "User", "CompanyRole",
        "UserCompany", "CompanyApp", "PartnerInstallation", "PartnerGrant", "PartnerCredential",
        "PartnerTokenFamily", "PartnerToken", "PartnerAuthorizationRequest", "PartnerCode"]
    statement = text(IDENTITY, "statement", "_PartnerRow")
    assert "where(*terms)" in statement and "populate_existing=True" in statement
    prepare = text(IDENTITY, "_prepare_partner_write")
    assert "read=not spec.update" in prepare and "key_share" not in prepare
    assert ".pointers" in statement


def test_native_reverification_uses_original_bearer_and_public_auth_same_session():
    node = symbol(IDENTITY, "_native_authority")
    for name in ("decode_token", "native_user_from_claims", "native_visit_from_claims", "native_claims_context", "require_core_user", "await_only"):
        assert len(calls(node, name)) == 1
    raw = text(IDENTITY, "_native_authority")
    assert "credentials.credentials" in raw
    for forbidden in ("get_current_user", "prepare_native_write", "prepare_auth_write", "commit", "Session", "AsyncSession"):
        assert not calls(node, forbidden)
    assert "native_user_from_claims(claims, db)" in raw and "native_visit_from_claims(claims, user, db)" in raw


def test_seam_reuses_one_verifier_and_compares_original_stable_identity():
    node = symbol(IDENTITY, "verify_locked_partner_access")
    assert len(calls(node, "verify_access")) == 1
    assert calls(node, "require_scoped_locks")
    for forbidden in ("decode", "decode_token", "live_grant", "acquire_scoped_locks", "commit", "Session"):
        assert not calls(node, forbidden)
    raw = text(IDENTITY, "verify_locked_partner_access")
    assert all('"' + name + '"' in raw for name in ("token_id", "client_id", "app_id", "installation_id", "company_id", "grant_id", "user_id", "is_machine", "subject"))
    assert "return current" in raw and "NOT row locks/ACL" in ast.get_docstring(node)


def test_userinfo_canonical_rows_before_seam_and_rechecks_after_subject_flush():
    node = symbol(OAUTH, "userinfo")
    prepare, = calls(node, "_prepare_partner_write")
    first, last = calls(node, "verify_locked_partner_access")
    subject, = calls(node, "user_info")
    flush, = calls(node, "flush")
    assert prepare.lineno < first.lineno < subject.lineno < flush.lineno < last.lineno
    assert calls(node, "commit")
    for name in ("discovery", "jwks"):
        assert not calls(symbol(OAUTH, name), "_prepare_partner_write")


def test_conflict_winner_checked_before_new_ca_lock_and_root_rollback():
    raw = text(ADMIN, "approve_installation")
    assert "ca_id = writer.ca_id" in raw
    assert raw.index("actual_id != ca_id") < raw.index(".with_for_update()")
    assert "CompanyApp.id == ca_id" in raw and "_writer_drift(sync)" in raw
    drift = text(IDENTITY, "_writer_drift")
    assert "db.rollback()" in drift and "409" in drift
    assert not calls(symbol(IDENTITY, "_writer_drift"), "begin_nested")


def test_consent_selected_company_and_self_revoke_policy_remain_distinct():
    assert "eligible_installations(sync, row, user, body.companyId)" in text(OAUTH, "approve")
    prepare = text(IDENTITY, "_prepare_partner_write")
    assert "original_grant.user_id != actor.id else None" in prepare
    revoke = text(ADMIN, "revoke_grant")
    assert "if grant.user_id != user.id:" in revoke
    assert not calls(symbol(ADMIN, "revoke_grant"), "live_grant")


def test_reuse_is_only_explicit_oauth_error_durability_exception():
    raw = text(OAUTH, "_protocol_response")
    assert raw.index("if server.reuse_revoked:") < raw.index("if result[0] >= 400:")
    assert "return result, False" in raw and "return result, True" in raw
    refresh = text(IDENTITY, "authenticate_refresh_token", "RotatingRefreshGrant")
    assert refresh.index("family.revoked = True") < refresh.index("self.server.reuse_revoked = True")
    for name in ("token", "revoke"):
        endpoint = text(OAUTH, name)
        assert "if durable:" in endpoint and "await db.rollback()" in endpoint and "await db.commit()" in endpoint


def test_family_before_token_and_no_late_protocol_identity():
    for name, owner in (("authenticate_refresh_token", "RotatingRefreshGrant"), ("query_token", "RevokeEndpoint")):
        raw = text(IDENTITY, name, owner)
        assert "writer.discovered(PartnerToken, row.id)" in raw
        assert raw.index("writer.discovered") < raw.index("select(PartnerTokenFamily)")
    code = text(IDENTITY, "query_authorization_code", "CodeGrant")
    assert code.index("writer.discovered") < code.index(".with_for_update()")


def test_final_callbacks_and_native_checks_never_acquire_another_plan():
    for name, owner in (("checkpoint", "_PartnerWrite"), ("checkpoint", "PartnerAuthorizationServer"),
                        ("issue_token", "PartnerAuthorizationServer"), ("save_token", "PartnerAuthorizationServer")):
        node = symbol(IDENTITY, name, owner)
        assert not calls(node, "acquire_scoped_locks") and not calls(node, "LockPlan")
    node = symbol(OAUTH, "_protocol_response")
    assert calls(node, "checkpoint")[-1].lineno > calls(node, "flush")[-1].lineno
    assert "if self.server.writer is not None:" in text(IDENTITY, "revoke_token", "RevokeEndpoint")


def test_protocol_nonce_and_subject_uniqueness_are_preserved():
    nonce = text(IDENTITY, "exists_nonce", "PartnerOpenIDCode")
    assert "2**63" in nonce and "2**64" in nonce and "pg_advisory_xact_lock(lock_key)" in nonce
    assert nonce.index("pg_advisory_xact_lock") < nonce.index("self.server.checkpoint()")
    assert "on_conflict_do_nothing" in text(IDENTITY, "pairwise_subject")
    assert "index_elements=[\"user_id\", \"client_id\"]" in text(IDENTITY, "pairwise_subject")


def test_absent_members_roles_and_parent_pointer_drift_are_explicit():
    raw = text(IDENTITY, "_prepare_partner_write")
    assert "_PartnerRow(model, identity, (), update, True)" in raw
    assert "CompanyRole.company_id == cid" in raw
    assert "(row is None) != spec.missing" in raw
    assert "_writer_drift(db)" in raw
    assert not any(name in raw for name in ("CreateProfileKey(", "EmailKey(", "RefCompositeKey("))


def test_protocol_graph_selection_uses_endpoint_mutation_and_only_its_fields():
    # PW-R1: inspect the composer BODY, never endpoint decorators/defaults.
    # This source oracle rejects the old data.grant_type branch; it does not
    # execute the composer or prove any actual lock, row or durable revocation.
    node = symbol(IDENTITY, "_prepare_partner_write")
    protocol = next(n for n in body_nodes(node) if isinstance(n, ast.If)
                    and ast.unparse(n.test) == "protocol is not None")
    reads = [n for n in body_nodes(protocol) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
             and n.func.value.id == "data" and n.func.attr == "get"]
    assert {n.args[0].value for n in reads} == {"code", "grant_id", "refresh_token", "token"}
    for mutation, field in (("token-code", "code"), ("token-machine", "grant_id"),
                            ("token-refresh", "refresh_token"), ("revoke", "token")):
        branch = next(n for n in body_nodes(protocol) if isinstance(n, ast.If)
                      and ast.unparse(n.test) == f"mutation == {mutation!r}")
        branch_reads = [n for statement in branch.body for n in body_nodes(statement)
                       if n in reads]
        assert len(branch_reads) == 1 and branch_reads[0].args[0].value == field
    value_selection = next(n for n in body_nodes(protocol) if isinstance(n, ast.If)
                           and ast.unparse(n.test) == "mutation == 'token-refresh'")
    assert ast.unparse(value_selection.body[0]) == "value = data.get('refresh_token')"
    assert ast.unparse(value_selection.orelse[0].test) == "mutation == 'revoke'"
    assert ast.unparse(value_selection.orelse[0].body[0]) == "value = data.get('token')"
    assert not value_selection.orelse[0].orelse
    lookup = next(n for n in body_nodes(protocol) if isinstance(n, ast.IfExp))
    assert ast.unparse(lookup.test) == "mutation == 'token-refresh'"
    assert "PartnerToken.refresh_hash == h" in ast.unparse(lookup.body)
    assert "PartnerToken.access_hash == h" in ast.unparse(lookup.orelse)
    assert "PartnerToken.refresh_hash == h" in ast.unparse(lookup.orelse)
    dispatcher = text(OAUTH, "_protocol_response")
    assert 'mutation = "revoke" if revocation else' in dispatcher
    assert len(calls(symbol(OAUTH, "_protocol_response"), "_prepare_partner_write")) == 1
