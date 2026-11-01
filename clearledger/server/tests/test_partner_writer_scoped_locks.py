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


def test_identity_free_validation_is_negative_only_before_composition():
    node = symbol(OAUTH, "_protocol_response")
    negative = next(n for n in node.body if isinstance(n, ast.If)
                    and ast.unparse(n.test) == "not (basic[0] or protocol.payload.client_id)")
    prepare, = calls(node, "_prepare_partner_write")
    parser, = calls(node, "extract_basic_authorization")
    assert parser.lineno < negative.lineno < negative.end_lineno < prepare.lineno
    assert ast.unparse(node.body[0].test) == "sync.new or sync.dirty or sync.deleted"
    assert calls(node.body[0], "ScopedLockError")
    context, = [n for n in negative.body if isinstance(n, ast.With)]
    assert ast.unparse(context.items[0].context_expr) == "sync.no_autoflush"
    server, = calls(negative, "PartnerAuthorizationServer")
    assert [ast.unparse(arg) for arg in server.args] == ["sync"] and not server.keywords
    assert len(calls(negative, "create_token_response")) == len(calls(negative, "create_endpoint_response")) == 1
    failure, = [n for n in context.body if isinstance(n, ast.If)]
    guard = ast.unparse(failure.test)
    for term in ("not isinstance(result, tuple)", "len(result) != 3", "result[0] < 400",
                 "not isinstance(result[1], dict)", "not result[1].get('error')",
                 "sync.new", "sync.dirty", "sync.deleted"):
        assert term in guard
    assert ast.unparse(failure.body[0]) == "sync.rollback()"
    assert isinstance(failure.body[1], ast.Raise) and calls(failure, "ScopedLockError")
    assert ast.unparse(context.body[-1]) == "return (result, False)"
    for forbidden in ("_prepare_partner_write", "acquire_scoped_locks", "LockPlan", "checkpoint",
                      "flush", "add", "execute", "commit", "query_token", "issue_token"):
        assert not calls(negative, forbidden)


def test_identity_present_protocol_still_has_one_full_writer_and_final_checks():
    node = symbol(OAUTH, "_protocol_response")
    prepare, = calls(node, "_prepare_partner_write")
    positive = [n for n in node.body if n.lineno >= prepare.lineno]
    assert ast.unparse(positive[0]) == "writer = _prepare_partner_write(sync, protocol=protocol, mutation=mutation)"
    assert ast.unparse(positive[1]) == "server = PartnerAuthorizationServer(sync, writer, protocol)"
    result = positive[2]
    assert isinstance(result.value, ast.IfExp) and ast.unparse(result.value.test) == "revocation"
    assert ast.unparse(result.value.body) == "server.create_endpoint_response('revocation', protocol)"
    assert ast.unparse(result.value.orelse) == "server.create_token_response(protocol)"
    assert ast.unparse(positive[3].test) == "server.reuse_revoked"
    assert ast.unparse(positive[4]) == "if result[0] >= 400:\n    return (result, False)"
    assert [ast.unparse(n) for n in positive[-4:]] == ["server.checkpoint()", "sync.flush()",
        "server.checkpoint()", "return (result, True)"]
    assert len(calls(node, "_prepare_partner_write")) == 1
    assert "if self.writer is None:" in text(IDENTITY, "checkpoint", "PartnerAuthorizationServer")
    assert calls(symbol(IDENTITY, "checkpoint", "PartnerAuthorizationServer"), "ScopedLockError")


def test_primary_no_client_methods_fail_before_lookup_and_protocol_callbacks():
    # Future source oracle reads installed library TEXT, never calls its parser,
    # authentication methods or any extracted application/library function.
    from importlib.metadata import distribution
    primary = Path(distribution("Authlib").locate_file("authlib/oauth2"))
    authentication = primary / "rfc6749/authenticate_client.py"
    dispatch = symbol(primary / "rfc6749/authorization_server.py", "create_token_response", "AuthorizationServer")
    assert calls(dispatch, "get_token_grant")[0].lineno < calls(dispatch, "validate_token_request")[0].lineno
    constructor = symbol(IDENTITY, "__init__", "PartnerAuthorizationServer")
    assert [ast.unparse(n.args[0]) for n in calls(constructor, "register_grant")] == [
        "CodeGrant", "RotatingRefreshGrant", "MachineGrant"]
    assert not calls(constructor, "register_client_auth_method")
    for name, predicate in (("authenticate_client_secret_basic", "client_id and client_secret"),
                            ("authenticate_none", "client_id and (not request.payload.data.get('client_secret'))")):
        node = symbol(authentication, name)
        gate = next(n for n in node.body if isinstance(n, ast.If))
        assert ast.unparse(gate.test) == predicate
        queries = calls(node, "_validate_client")
        assert len(queries) == 1 and gate.lineno < queries[0].lineno <= gate.end_lineno
        assert not any(isinstance(n, ast.Return) for n in node.body)
    authenticate = symbol(authentication, "authenticate", "ClientAuthentication")
    assert "status_code=401" in ast.unparse(authenticate)
    assert calls(authenticate, "InvalidClientError")
    for owner, name in (("CodeGrant", "TOKEN_ENDPOINT_AUTH_METHODS"),
                        ("RotatingRefreshGrant", "TOKEN_ENDPOINT_AUTH_METHODS"),
                        ("RevokeEndpoint", "CLIENT_AUTH_METHODS")):
        cls = next(n for n in tree(IDENTITY).body if isinstance(n, ast.ClassDef) and n.name == owner)
        assignment = next(n for n in cls.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
        assert ast.literal_eval(assignment.value) == ["client_secret_basic", "none"]
    base = next(n for n in tree(primary / "rfc6749/grants/base.py").body
                if isinstance(n, ast.ClassDef) and n.name == "BaseGrant")
    assert ast.literal_eval(base.body[0].value) == ["client_secret_basic"]
    # MachineGrant inherits client_credentials -> BaseGrant's basic-only method.
    machine = next(n for n in tree(IDENTITY).body if isinstance(n, ast.ClassDef) and n.name == "MachineGrant")
    assert [ast.unparse(n) for n in machine.bases] == ["ClientCredentialsGrant"]
    assert not any(isinstance(n, ast.Assign) for n in machine.body)
    parent = next(n for n in tree(primary / "rfc6749/grants/client_credentials.py").body
                  if isinstance(n, ast.ClassDef) and n.name == "ClientCredentialsGrant")
    assert "BaseGrant" in [ast.unparse(n) for n in parent.bases]
    assert not any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name)
                   and t.id == "TOKEN_ENDPOINT_AUTH_METHODS" for t in n.targets) for n in parent.body)
    for file, owner, method in (("authorization_code.py", "AuthorizationCodeGrant", "validate_token_request"),
                               ("refresh_token.py", "RefreshTokenGrant", "_validate_request_client"),
                               ("client_credentials.py", "ClientCredentialsGrant", "validate_token_request")):
        node = symbol(primary / "rfc6749/grants" / file, method, owner)
        first, = calls(node, "authenticate_token_endpoint_client")
        # Authentication is the first call in each actual validation body.
        assert next(n for n in body_nodes(node) if isinstance(n, ast.Call)) is first
    refresh = symbol(primary / "rfc6749/grants/refresh_token.py", "validate_token_request", "RefreshTokenGrant")
    assert calls(refresh, "_validate_request_client")[0].lineno < calls(refresh, "_validate_request_token")[0].lineno
    revoke = symbol(primary / "rfc7009/revocation.py", "create_endpoint_response", "RevocationEndpoint")
    assert calls(revoke, "authenticate_endpoint_client")[0].lineno < calls(revoke, "authenticate_token")[0].lineno


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


def test_installation_preflight_clean_guard_precedes_actor_and_all_sql():
    node = symbol(ADMIN, "_installation_selection")
    guard = next(n for n in node.body if not isinstance(n, ast.Expr))
    assert ast.unparse(guard.test) == "sync.new or sync.dirty or sync.deleted"
    assert calls(guard, "ScopedLockError")
    context, = [n for n in node.body if isinstance(n, ast.With)]
    assert ast.unparse(context.items[0].context_expr) == "sync.no_autoflush"
    assert all(guard.end_lineno < call.lineno for call in calls(node, "admin") + calls(node, "get") + calls(node, "scalars"))
    for forbidden in ("flush", "expire", "expire_all", "rollback", "commit", "add", "add_all",
                      "execute", "with_for_update", "_prepare_partner_write", "acquire_scoped_locks"):
        assert not calls(node, forbidden)


def test_installation_single_policy_preserves_legacy_error_precedence():
    node = symbol(ADMIN, "_installation_selection")
    context, = [n for n in node.body if isinstance(n, ast.With)]
    client = next(n for n in context.body if isinstance(n, ast.If)
                  and "client is None" in ast.unparse(n.test))
    location = next(n for n in context.body if isinstance(n, ast.If) and ast.unparse(n.test) == "ids")
    resource = next(n for n in context.body if isinstance(n, ast.For))
    assert calls(node, "admin")[0].lineno < client.lineno < location.lineno < resource.lineno
    assert 'HTTPException(422, \'Invalid client or scopes\', headers=NO_STORE)' in ast.unparse(client)
    assert 'HTTPException(422, \'Invalid company resource IDs\', headers=NO_STORE)' in ast.unparse(location)
    mode, parse, ownership = [n for n in resource.body if isinstance(n, (ast.If, ast.Try))]
    assert "SET requires IDs; ALL/EMPTY forbid IDs" in ast.unparse(mode)
    assert "Invalid resource ID type" in ast.unparse(parse)
    assert "Invalid company resource IDs" in ast.unparse(ownership)
    assert mode.lineno < parse.lineno < ownership.lineno
    assert ast.unparse(resource.iter) == "body.resourceScopes.items()"
    assert "kind == 'objects'" in ast.unparse(parse) and calls(parse, "UUID")
    assert len(calls(node, "admin")) == 1


def test_installation_closed_selection_revalidated_after_one_complete_plan():
    node = symbol(ADMIN, "approve_installation")
    first, second = calls(node, "_installation_selection")
    prepare, = calls(node, "_prepare_partner_write")
    dml = calls(node, "execute")[0]
    assert first.lineno < prepare.lineno < second.lineno < calls(node, "checkpoint")[0].lineno < dml.lineno
    assert ast.unparse(first.args[3]) == "user" and ast.unparse(second.args[3]) == "writer.actor"
    assert next(k.value.id for k in prepare.keywords if k.arg == "selections") == "selections"
    assert not calls(node, "admin")  # Policy lives only in the reused validator.
    raw = text(ADMIN, "approve_installation")
    assert "((ServiceLocation, ids),) + tuple" in raw
    assert "RESOURCE_MODELS[kind][0], values" in raw
    assert "body.locationIds is None" in raw and "for v in ids" in raw
    helper = text(ADMIN, "_installation_selection")
    assert "populate_existing=True" in helper and "return client, ids, tuple(resources)" in helper
    assert "frozenset(body.locationIds or [])" in helper and "frozenset(selection.ids)" in helper
    assert not calls(symbol(ADMIN, "_installation_selection"), "LockPlan")


def test_installation_revalidation_retains_current_native_after_query_waits():
    prepare = symbol(IDENTITY, "_prepare_partner_write")
    assert calls(prepare, "checkpoint")[-1].lineno > calls(prepare, "with_for_update")[-1].lineno
    checkpoint = symbol(IDENTITY, "checkpoint", "_PartnerWrite")
    assert calls(checkpoint, "native") and calls(checkpoint, "admin")
    node = symbol(ADMIN, "approve_installation")
    second = calls(node, "_installation_selection")[-1]
    assert second.lineno < calls(node, "checkpoint")[0].lineno < calls(node, "execute")[0].lineno
    assert calls(symbol(ADMIN, "finish"), "checkpoint")[-1].lineno > calls(symbol(ADMIN, "finish"), "flush")[0].lineno
