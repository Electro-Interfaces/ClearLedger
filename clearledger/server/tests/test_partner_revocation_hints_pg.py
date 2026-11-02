"""AUTHORED / NOTCOLLECTED / NOTRUN: real HTTP, Authlib and PostgreSQL.

Reuse canonical admission, full schema, env/rsa_key and real issuer helpers.
No runner, URL or reduced fixtures. ROOT must isolate parent conftest BEFORE
collection: its application imports precede these module admission checks.
"""
import os

import pytest
from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_PARTNER_IDENTITY_TESTS") != "1":
    pytest.skip("Existing partner opt-in required; author execution NOT_GRANTED", allow_module_level=True)
if error := partner_test_safety_error(os.environ):
    raise RuntimeError(error)
if os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL"):
    raise RuntimeError("Existing isolated partner composition must use matching URLs")

from copy import deepcopy
from uuid import uuid4

from authlib.oauth2.rfc6749 import InvalidGrantError
from sqlalchemy import event, select

from app.models import App, Company, CompanyApp, ServiceLocation, User, UserCompany
from app.models_partner import (PartnerAuthorizationRequest, PartnerClient, PartnerCode,
    PartnerCredential, PartnerGrant, PartnerInstallation, PartnerInstallationLocation,
    PartnerResourceItem, PartnerResourceScope, PartnerSubject, PartnerToken, PartnerTokenFamily)
from app.routers import partner_oauth_router as oauth
from app.services import contract_write_locks as locks
from app.services import partner_identity as identity
from tests.conftest import _test_engine, _test_session_factory
from tests.test_partner_identity import env, rsa_key, registration, consent, tokens

pytestmark = pytest.mark.asyncio(loop_scope="session")


def form_for(app, token, token_field, hint):
    form = {"token": token}
    if hint != "missing":
        form["token_type_hint"] = ("unregistered-hint" if hint == "unknown" else
            "refresh_token" if token_field == "access_token" else "access_token")
    auth = (app["client_id"], app["secret"]) if "secret" in app else None
    if auth is None:
        form["client_id"] = app["client_id"]
    return form, auth


def wire(response, status=200, error=None):
    assert response.status_code == status, (response.status_code, response.text)
    assert response.json() == ({} if error is None else {"error": error})
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


async def setup_pair(env, confidential):
    app = await registration(env, confidential=confidential)
    other = await registration(env, confidential=confidential)
    issued, _ = await tokens(env, app)
    unrelated, _ = await tokens(env, other)
    # Leave actual, legitimate codes unconsumed in both client closures.
    await consent(env, app)
    await consent(env, other)
    async with _test_session_factory() as reader:
        actual = await reader.scalar(select(PartnerToken).where(
            PartnerToken.access_hash == identity.digest(issued["access_token"])))
        decoy = await reader.scalar(select(PartnerToken).where(
            PartnerToken.access_hash == identity.digest(unrelated["access_token"])))
        return app, other, issued, unrelated, (actual.id, actual.family_id), (decoy.id, decoy.family_id)


async def bound_state(env, app, other):
    """Every persisted column of both bound closures, read in a fresh Session.

    Predicates include all current/future rows beneath these real clients, not
    only the known family IDs, so new tokens/codes/grants cannot escape the oracle.
    Core parent/membership/location rows are included without changing fixtures.
    """
    clients = (app["client_id"], other["client_id"])
    installs = (app["installation_id"], other["installation_id"])
    grants = select(PartnerGrant.id).where(PartnerGrant.client_id.in_(clients))
    families = select(PartnerTokenFamily.id).where(PartnerTokenFamily.grant_id.in_(grants))
    targets = (
        (App, App.id.in_((app["app_id"], other["app_id"]))),
        (Company, Company.id.in_((env["company"].id, env["other"].id))),
        (CompanyApp, CompanyApp.id.in_(installs)),
        (User, User.id.in_((env["user"].id, env["member"].id))),
        (UserCompany, UserCompany.user_id.in_((env["user"].id, env["member"].id))),
        (ServiceLocation, ServiceLocation.id.in_((env["location"].id, env["foreign_location"].id))),
        (PartnerClient, PartnerClient.id.in_(clients)),
        (PartnerCredential, PartnerCredential.client_id.in_(clients)),
        (PartnerInstallation, PartnerInstallation.client_id.in_(clients)),
        (PartnerInstallationLocation, PartnerInstallationLocation.installation_id.in_(installs)),
        (PartnerResourceScope, PartnerResourceScope.installation_id.in_(installs)),
        (PartnerResourceItem, PartnerResourceItem.installation_id.in_(installs)),
        (PartnerAuthorizationRequest, PartnerAuthorizationRequest.client_id.in_(clients)),
        (PartnerSubject, PartnerSubject.client_id.in_(clients)),
        (PartnerGrant, PartnerGrant.client_id.in_(clients)),
        (PartnerCode, PartnerCode.client_id.in_(clients)),
        (PartnerTokenFamily, PartnerTokenFamily.grant_id.in_(grants)),
        (PartnerToken, PartnerToken.family_id.in_(families)),
    )
    result = {}
    async with _test_session_factory() as reader:
        for model, condition in targets:
            table = model.__table__
            rows = (await reader.execute(select(table).where(condition))).mappings().all()
            result[table.name] = {
                tuple(row[column.name] for column in table.primary_key): dict(row) for row in rows}
    return result


def only_family_revoked(before, family_id):
    expected = deepcopy(before)
    assert expected[PartnerTokenFamily.__tablename__][(family_id,)]["revoked"] is False
    expected[PartnerTokenFamily.__tablename__][(family_id,)]["revoked"] = True
    return expected


@pytest.mark.parametrize("confidential", [False, True])
@pytest.mark.parametrize("token_field", ["access_token", "refresh_token"])
@pytest.mark.parametrize("hint", ["unknown", "opposite", "missing"])
async def test_real_hint_fallback_revokes_only_actual_family_and_repeats(env, monkeypatch, confidential, token_field, hint):
    app, other, issued, unrelated, actual, decoy = await setup_pair(env, confidential)
    before = await bound_state(env, app, other)
    prepare, prepared = oauth._prepare_partner_write, []
    check, checks = identity.RevokeEndpoint.check_params, []
    revoke, revoked = identity.RevokeEndpoint.revoke_token, []

    def real_prepare(sync, **kwargs):
        writer = prepare(sync, **kwargs)  # Actual issuer and capability on actual root.
        assert kwargs["mutation"] == "revoke"
        locks.require_scoped_locks(sync, writer.capability, writer.capability.plan.requests)
        assert sync.get_transaction() is not None
        keys = {request.key for request in writer.capability.plan.requests}
        assert locks.ClientKey(other["client_id"]) not in keys
        assert locks.InstallationKey(other["installation_id"]) not in keys
        assert not writer.discovered(PartnerToken, decoy[0])
        assert not writer.discovered(PartnerTokenFamily, decoy[1])
        assert not any(row.model is PartnerCode for row in writer.rows)
        if kwargs["protocol"].form["token"] == issued[token_field]:
            assert writer.discovered(PartnerToken, actual[0])
            assert writer.discovered(PartnerTokenFamily, actual[1])
        prepared.append((sync, sync.get_transaction(), writer))
        return writer

    def real_check(endpoint, request, client):
        result = check(endpoint, request, client)
        checks.append((request.form["token"], request.form.get("token_type_hint")))
        return result

    def real_revoke(endpoint, token, request):
        sync, root, writer = prepared[-1]
        assert endpoint.server.db is sync and endpoint.server.writer is writer
        assert sync.get_transaction() is root and root.is_active
        result = revoke(endpoint, token, request)
        assert endpoint.server.family.id == actual[1]
        revoked.append(actual[1])
        return result

    # The inherited Authlib client authentication / authenticate_token /
    # check_client / create_endpoint_response are never replaced.
    with monkeypatch.context() as trace:
        trace.setattr(oauth, "_prepare_partner_write", real_prepare)
        trace.setattr(identity.RevokeEndpoint, "check_params", real_check)
        trace.setattr(identity.RevokeEndpoint, "revoke_token", real_revoke)
        form, auth = form_for(app, "unknown-" + uuid4().hex, token_field, hint)
        wire(await env["client"].post("/api/oauth2/revoke", data=form, auth=auth))
        assert await bound_state(env, app, other) == before
        form, auth = form_for(app, issued[token_field], token_field, hint)
        wire(await env["client"].post("/api/oauth2/revoke", data=form, auth=auth))
        expected = only_family_revoked(before, actual[1])
        assert await bound_state(env, app, other) == expected
        wire(await env["client"].post("/api/oauth2/revoke", data=form, auth=auth))
        assert await bound_state(env, app, other) == expected
        assert len(prepared) == len(checks) == 3 and revoked == [actual[1], actual[1]]
        assert all(not root.is_active for _, root, _ in prepared)
    assert (await env["client"].get("/api/oauth2/userinfo",
        headers={"Authorization": "Bearer " + issued["access_token"]})).status_code == 401
    assert (await env["client"].get("/api/oauth2/userinfo",
        headers={"Authorization": "Bearer " + unrelated["access_token"]})).status_code == 200


@pytest.mark.parametrize("confidential", [False, True])
@pytest.mark.parametrize("token_field", ["access_token", "refresh_token"])
@pytest.mark.parametrize("hint", ["unknown", "opposite", "missing"])
async def test_foreign_client_hint_cannot_authorize_or_write_any_bound_row(env, confidential, token_field, hint):
    app, other, issued, _, _, _ = await setup_pair(env, confidential)
    before = await bound_state(env, app, other)
    form, auth = form_for(other, issued[token_field], token_field, hint)
    dml = []
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")):
            dml.append(statement)
    event.listen(_test_engine.sync_engine, "before_cursor_execute", record)
    try:
        wire(await env["client"].post("/api/oauth2/revoke", data=form, auth=auth), 400, "invalid_grant")
    finally:
        event.remove(_test_engine.sync_engine, "before_cursor_execute", record)
    assert not dml
    assert await bound_state(env, app, other) == before


@pytest.mark.parametrize("confidential,case", [
    (False, "missing-token"), (True, "missing-token"),
    (False, "missing-client"), (True, "missing-client"),
    (False, "unknown-client"), (True, "unknown-client"), (True, "bad-secret")])
@pytest.mark.parametrize("hint", ["unknown", "opposite", "missing"])
async def test_required_token_and_auth_errors_keep_real_rows_unchanged(env, confidential, case, hint):
    app, other, issued, _, _, _ = await setup_pair(env, confidential)
    before = await bound_state(env, app, other)
    form, auth = form_for(app, issued["access_token"], "access_token", hint)
    if case == "missing-token":
        form.pop("token")
    elif case == "missing-client":
        form.pop("client_id", None)
        auth = None
    elif case == "unknown-client":
        unknown = "missing-" + uuid4().hex
        if confidential:
            auth = (unknown, "synthetic-secret")
        else:
            form["client_id"] = unknown
    else:
        auth = (app["client_id"], "synthetic-wrong-secret")
    dml = []
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")):
            dml.append(statement)
    event.listen(_test_engine.sync_engine, "before_cursor_execute", record)
    try:
        response = await env["client"].post("/api/oauth2/revoke", data=form, auth=auth)
    finally:
        event.remove(_test_engine.sync_engine, "before_cursor_execute", record)
    wire(response, 400 if (case == "missing-token" or
        (not confidential and case == "unknown-client")) else 401,
        "invalid_request" if case == "missing-token" else "invalid_client")
    assert not dml
    assert await bound_state(env, app, other) == before


@pytest.mark.parametrize("confidential", [False, True])
@pytest.mark.parametrize("token_field", ["access_token", "refresh_token"])
@pytest.mark.parametrize("hint", ["unknown", "opposite", "missing"])
@pytest.mark.parametrize("fault", ["after-revoke-flush", "after-protocol"])
async def test_real_revoke_fault_rolls_back_complete_root_before_publication(env, monkeypatch, confidential, token_field, hint, fault):
    app, other, issued, _, actual, _ = await setup_pair(env, confidential)
    before = await bound_state(env, app, other)
    prepare, roots, rolled_back, flushed = oauth._prepare_partner_write, [], [], []
    revoke, protocol = identity.RevokeEndpoint.revoke_token, oauth._protocol_response

    def real_prepare(sync, **kwargs):
        writer = prepare(sync, **kwargs)
        locks.require_scoped_locks(sync, writer.capability, writer.capability.plan.requests)
        root = sync.get_transaction()
        assert root is not None and root.parent is None and root.is_active
        roots.append(root)
        event.listen(sync, "after_rollback", lambda session: rolled_back.append(root), once=True)
        return writer

    def real_revoke_then_fault(endpoint, token, request):
        result = revoke(endpoint, token, request)  # Real family write and real flush.
        assert endpoint.server.family.id == actual[1] and endpoint.server.family.revoked
        assert endpoint.server.db.get_transaction() is roots[-1] and roots[-1].is_active
        flushed.append(True)
        if fault == "after-revoke-flush":
            raise InvalidGrantError()
        return result

    def real_protocol_then_fault(sync, request, revocation):
        result = protocol(sync, request, revocation)
        if fault == "after-protocol":
            assert result[0][0] == 200 and result[0][1] == {} and result[1] is True
            assert sync.get_transaction() is roots[-1] and roots[-1].is_active
            raise InvalidGrantError()
        return result

    with monkeypatch.context() as trace:
        trace.setattr(oauth, "_prepare_partner_write", real_prepare)
        trace.setattr(identity.RevokeEndpoint, "revoke_token", real_revoke_then_fault)
        trace.setattr(oauth, "_protocol_response", real_protocol_then_fault)
        form, auth = form_for(app, issued[token_field], token_field, hint)
        wire(await env["client"].post("/api/oauth2/revoke", data=form, auth=auth), 400, "invalid_grant")
    assert len(roots) == 1 and flushed == [True] and rolled_back == roots
    assert not roots[0].is_active
    assert await bound_state(env, app, other) == before
