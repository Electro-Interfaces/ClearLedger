"""M15 real PostgreSQL definitions: AUTHORED / NOTRUN, also collection.

Original native activation/issuer fixtures only. ROOT must admit the actual
factories, schema4/Core/READ COMMITTED and cleanup of m15_owned IDs separately.
No env/URL/DDL/runner or positive auth/Session/SQL/receipt substitutes.
An external commit is injected between passes at the first post-B checkpoint,
before row SHARE locks; later protected rows use same-root negative SQL faults
because an external UPDATE cannot commit through the original held SHARE lock.
"""
import asyncio
from collections import Counter
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.util import await_only

from app.models import App, AuditEvent, Company, CompanyApp, CompanyRole, Counterparty, Organization, ServiceLocation, User, UserCompany
from app.models_partner import PartnerClient, PartnerCredential, PartnerGrant, PartnerInstallation, PartnerResourceItem
from app.models_partner_contracts import (PartnerContractCreateProfile as Profile,
    PartnerContractCreatePrincipal as Principal, PartnerContractCreateRef as Ref,
    PartnerContractCreateType as Type)
from app.schemas_partner import ActivateContractCreateProfile
from app.services import partner_contract_activation as activation, partner_identity as identity
from app.services import contract_write_locks as locks
from app.services.partner_contract_profiles import profile_core_user
from tests.test_partner_contract_activation_pg import world, put, state, blocked
from tests.partner_contract_issuer_fixture import issuer_world, native_org_admin

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _snapshot(w):
    """Tolerates committed deletion of a company/profile; compares real SQL."""
    async with w.factory() as db:
        profile = tuple(tuple(row) for row in (await db.execute(select(*Profile.__table__.c).where(
            Profile.installation_id == w.iid))).all())
        audit = tuple(tuple(row) for row in (await db.execute(select(AuditEvent.id, AuditEvent.action,
            AuditEvent.details).where(AuditEvent.company_id.in_((w.company, w.home))).order_by(AuditEvent.id))).all())
        return profile, audit


async def _external_second_id(w, model, ident, fault):
    """Actual independent writer/commit, including FK cascades on deletion."""
    async with w.factory() as other:
        assert isinstance(other, AsyncSession)
        if fault == "drift":
            row = await other.get(model, ident)
            row.name = "M15 changed full-column value"
        elif fault == "foreign" and model is ServiceLocation:
            (await other.get(model, ident)).company_id = w.home
        else:
            if model is Company:
                # Exact synthetic FK closure, no disabled constraints/DDL.
                # The delete may remove the profile too; _snapshot is tolerant.
                await other.execute(delete(Profile).where(Profile.installation_id == w.iid))
                await other.execute(delete(PartnerInstallation).where(PartnerInstallation.id == w.iid))
                await other.execute(text("DELETE FROM core.eco_company_apps WHERE id=:i"), {"i": w.iid})
                await other.execute(text("DELETE FROM core.partner_clients WHERE id=:c"), {"c": w.client_id})
                await other.execute(delete(UserCompany).where(UserCompany.company_id == w.company))
                await other.execute(delete(Counterparty).where(Counterparty.company_id == w.company))
                await other.execute(delete(Organization).where(Organization.company_id == w.company))
                await other.execute(delete(ServiceLocation).where(ServiceLocation.company_id == w.company))
                await other.execute(delete(AuditEvent).where(AuditEvent.company_id == w.company))
                await other.execute(text("UPDATE core.users SET company_id=NULL WHERE company_id=:c"), {"c": ident})
            await other.execute(delete(model).where(model.id == ident))
            await other.flush()
            if fault == "foreign":
                # Company/User have global PKs and no tenant pointer predicate.
                # A different real row must never fill the missing frozen ID.
                replacement = uuid4()
                if model is Company:
                    other.add(Company(id=replacement, name="M15 unrelated company",
                        slug="m15-" + uuid4().hex, profile_id="energy"))
                elif model is User:
                    # No company FK needed; avoid relying on a cascaded home.
                    other.add(User(id=replacement, company_id=None, name="M15 unrelated user",
                        email=uuid4().hex + "@m15.invalid", password_hash="synthetic"))
                else:
                    replacement = "  M15 foreign:" + uuid4().hex + "  "
                    other.add(ServiceLocation(id=replacement, company_id=w.home,
                        code="m15-"+uuid4().hex, name="M15 unrelated object", source_bindings=[]))
                w.m15_owned = (*getattr(w, "m15_owned", ()), (model.__name__, replacement))
        await other.commit()
    return await _snapshot(w)


@pytest.mark.parametrize("kind", ["Company", "User", "ServiceLocation"])
@pytest.mark.parametrize("fault", ["drift", "delete", "foreign"])
async def test_external_commit_on_second_id_between_independent_current_passes(world, monkeypatch, kind, fault):
    w, injected, snapshots = world, [], []
    model = {"Company": Company, "User": User, "ServiceLocation": ServiceLocation}[kind]
    original = activation.ActivationOperation.refresh_identity
    def after_ORM(operation, db, specs):
        result = original(operation, db, specs)
        if not injected:
            batches = [batch for batch in activation._identity_batches(specs)
                       if len(batch) >= 2 and batch[0].model is model]
            assert len(batches) == 1
            ident = batches[0][1].identity[0]  # second ID, never a representative
            injected.append(ident)
            snapshots.append(await_only(_external_second_id(w, model, ident, fault)))
        return result
    monkeypatch.setattr(activation.ActivationOperation, "refresh_identity", after_ORM)
    response = await put(w)
    assert len(injected) == 1 and response.status_code in {401, 403, 409}, response.text
    assert await _snapshot(w) == snapshots[0]  # only the independent commit survives


@pytest.mark.parametrize("kind", ["Company", "User", "ServiceLocation"])
@pytest.mark.parametrize("fault", ["drift", "delete", "foreign"])
async def test_external_second_id_before_first_original_ORM_after_freeze_and_B(world, monkeypatch, kind, fault):
    """Separate from interpass coverage: observe actual ORM, never a getter.

    Company/User have no tenant predicate. A same-PK name drift must refresh
    successfully, then fail the independent full scalar comparison. A foreign
    Location leaves its original predicate; Company/User foreign replaces PK.
    """
    w = world
    model = {"Company": Company, "User": User, "ServiceLocation": ServiceLocation}[kind]
    if model is User:
        # Whichever UUID sorts second has a legitimate foreign home BEFORE
        # discovery. Membership/native admin remain real and unchanged.
        async with w.factory() as setup:
            second = sorted((w.member, w.admin), key=str)[1]
            (await setup.get(User, second)).company_id = w.home
            await setup.commit()
    frozen, issued, entered, observed, rejected, graph_done, scalar_rows = [], [], [], [], [], [], []
    physical, active = [], []
    original_freeze, original_b = activation.ActivationOperation.freeze, identity.acquire_scoped_locks
    original_refresh, original_graph = activation.ActivationOperation.refresh_identity, activation.ProfileOperation.recheck
    original_rows = activation._rows
    def freeze(operation, db, ordered, installation_sets, credential_sets):
        result = original_freeze(operation, db, ordered, installation_sets, credential_sets)
        # Independent ordering, not the grouping function under test.
        specs = [spec for spec in ordered if spec.model is model]
        assert len(specs) == 2 and all(not spec.missing and not spec.update for spec in specs)
        selected = sorted(specs, key=lambda spec: tuple(map(str, spec.identity)))[1]
        expected = operation.identity_rows[ordered.index(selected)]
        assert len(expected) == 1
        frozen.append((operation, selected, expected))
        return result
    def issuer(db, plan):
        cap = original_b(db, plan)
        assert len(frozen) == 1
        issued.append((db, db.get_transaction(), db.connection(), cap))
        return cap
    def loaded(target, context):
        if active:
            values = vars(target)  # load/refresh event; no attribute loader SQL
            if values.get("id") == frozen[0][1].identity[0]:
                observed.append((values.get("id"), values.get("name"), values.get("company_id")))
    def refreshed(target, context, attrs):
        loaded(target, context)
    def sql(conn, cursor, statement, params, context, many):
        if "FOR SHARE" in statement or "FOR UPDATE" in statement:
            physical.append(statement)
    def refresh(operation, db, specs):
        assert not entered and len(issued) == 1 and not physical
        assert frozen[0][0] is operation and operation.ordered is specs
        assert issued[0][:3] == (db, db.get_transaction(), db.connection())
        selected = frozen[0][1]
        entered.append(await_only(_external_second_id(w, model, selected.identity[0], fault)))
        assert not physical  # external writer committed before ANY physical lock
        active.append(True)
        try:
            try:
                result = original_refresh(operation, db, specs)
            except HTTPException as error:
                rejected.append(error.status_code)
                raise
            # Only drift is allowed through the original first pass.
            assert fault == "drift" and observed
            assert observed[-1][0:2] == (selected.identity[0], "M15 changed full-column value")
            if model is User:
                assert observed[-1][2] == w.home
            return result
        finally:
            active.pop()
    def graph(operation, db):
        result = original_graph(operation, db)
        graph_done.append(True)
        return result
    def rows(db, statement):
        result = original_rows(db, statement)
        if graph_done and entered:
            tables = statement.get_final_froms()
            if len(tables) == 1 and tables[0].name == model.__tablename__:
                columns = tuple(column.name for column in statement.selected_columns)
                assert columns == tuple(column.name for column in model.__table__.c)
                index = columns.index("id")
                scalar_rows.extend(row for row in result if row[index] == frozen[0][1].identity[0])
        return result
    monkeypatch.setattr(activation.ActivationOperation, "freeze", freeze)
    monkeypatch.setattr(identity, "acquire_scoped_locks", issuer)
    monkeypatch.setattr(activation.ActivationOperation, "refresh_identity", refresh)
    monkeypatch.setattr(activation.ProfileOperation, "recheck", graph)
    monkeypatch.setattr(activation, "_rows", rows)
    engine = w.factory.kw["bind"].sync_engine
    event.listen(model, "load", loaded)
    event.listen(model, "refresh", refreshed)
    event.listen(engine, "before_cursor_execute", sql)
    try:
        response = await put(w)
    finally:
        event.remove(engine, "before_cursor_execute", sql)
        event.remove(model, "refresh", refreshed)
        event.remove(model, "load", loaded)
    assert response.status_code == 409, response.text
    assert len(entered) == 1 and not physical
    if fault == "drift":
        assert not rejected and graph_done == [True]
        assert len(scalar_rows) == 1 and (scalar_rows[0],) != frozen[0][2]
    else:
        assert rejected == [409] and not graph_done and not scalar_rows
        assert not observed  # missing/out-of-predicate/replaced frozen PK
    assert await _snapshot(w) == entered[0]


@pytest.mark.parametrize("role_present", [False, True])
@pytest.mark.parametrize("column,value", [("object_scope", []), ("modules", []), ("own_organization_id", None)])
async def test_unbatched_member_role_null_and_present_keep_exact_full_row(world, monkeypatch, role_present, column, value):
    w, fired = world, []
    async with w.factory() as db:
        member = await db.get(UserCompany, (w.member, w.company))
        member.role_id = w.role if role_present else None
        member.object_scope = [w.loc]
        member.modules = None
        await db.commit()
    original = activation.ActivationOperation.refresh_identity
    def external_after_ORM(operation, db, specs):
        result = original(operation, db, specs)
        if not fired:
            members = [spec for spec in specs if spec.model is UserCompany]
            assert len(members) == 2
            assert all(len(batch) == 1 for batch in activation._identity_batches(members))
            selected = next(spec for spec in members if spec.identity == (w.member, w.company))
            assert selected.pointers[2] == (w.role if role_present else None)
            async def change():
                async with w.factory() as writer:
                    row = await writer.get(UserCompany, (w.member, w.company))
                    setattr(row, column, value)
                    await writer.commit()
            await_only(change()); fired.append(True)
        return result
    monkeypatch.setattr(activation.ActivationOperation, "refresh_identity", external_after_ORM)
    before = await _snapshot(w)
    response = await put(w)
    assert response.status_code == 409 and fired == [True], response.text
    assert await _snapshot(w) == before


@pytest.mark.parametrize("column,first,second", [
    ("object_scope", None, []), ("object_scope", [], ["  M15:Ёё  "]),
    ("modules", None, []), ("modules", [], ["references"]),
])
async def test_full_scalar_json_null_empty_and_literal_opaque_drift(world, monkeypatch, column, first, second):
    w = world
    async with w.factory() as db:
        setattr(await db.get(UserCompany, (w.member, w.company)), column, first)
        await db.commit()
    original, fired = activation.ActivationOperation.refresh_identity, []
    def drift(operation, db, specs):
        result = original(operation, db, specs)
        if not fired:
            async def commit():
                async with w.factory() as external:
                    setattr(await external.get(UserCompany, (w.member, w.company)), column, second)
                    await external.commit()
            await_only(commit()); fired.append(True)
        return result
    monkeypatch.setattr(activation.ActivationOperation, "refresh_identity", drift)
    assert (await put(w, user=False, service=False)).status_code == 409
    assert fired == [True]


FAULTS = ("gate", "token_version", "password", "lock", "member", "organization",
          "role", "home", "parent", "epoch", "revoke", "grant_discriminator")


def _negative_current_fault(w, db, monkeypatch, fault):
    """Negative data/clock fault on actual held root; never grant success."""
    if fault == "gate":
        monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", False)
    elif fault in {"token_version", "password", "lock", "home"}:
        statements = {
            "token_version": "UPDATE core.users SET token_version=token_version+1 WHERE id=:u",
            "password": "UPDATE core.users SET password_hash='' WHERE id=:u",
            "lock": "UPDATE core.users SET locked_until=now()+interval '1 hour' WHERE id=:u",
            "home": "UPDATE core.users SET company_id=NULL WHERE id=:u",
        }
        db.execute(text(statements[fault]), {"u": w.admin})
    elif fault == "member":
        db.execute(text("UPDATE core.user_companies SET role='user' WHERE user_id=:u AND company_id=:c"),
            {"u": w.admin, "c": w.company})
    elif fault == "organization":
        db.execute(text("UPDATE core.user_companies SET own_organization_id=NULL WHERE user_id=:u AND company_id=:c"),
            {"u": w.member, "c": w.company})
    elif fault == "role":
        db.execute(text("UPDATE core.company_roles SET modules='[]'::jsonb WHERE id=:r"), {"r": w.role})
    elif fault == "parent":
        db.execute(text("UPDATE core.counterparties SET aliases=aliases || ARRAY['m15-parent-drift']::varchar[] WHERE id=:p"), {"p": w.extra_cp})
    elif fault in {"epoch", "revoke"}:
        statement = ("UPDATE core.partner_contract_create_profiles SET policy_generation=policy_generation+1 WHERE installation_id=:i"
                     if fault == "epoch" else "UPDATE core.partner_contract_create_profiles SET revoked=true WHERE installation_id=:i")
        db.execute(text(statement), {"i": w.iid})
    else:
        db.execute(text("UPDATE core.partner_grants SET kind='user',user_id=:u WHERE id=:g"), {"u": w.member, "g": w.grant})


@pytest.mark.parametrize("checkpoint_index", tuple(range(1, 32)))
@pytest.mark.parametrize("fault", FAULTS)
async def test_all_original_31_checkpoint_boundaries_reject_current_negative_fault(world, monkeypatch, checkpoint_index, fault):
    w, seen, fired = world, [], []
    before = await state(w)
    original = identity._PartnerWrite.checkpoint
    def current(writer):
        if type(getattr(writer, "contract_profile", None)) is activation.ActivationOperation:
            seen.append(len(seen) + 1)
            if len(seen) == checkpoint_index:
                _negative_current_fault(w, writer.db, monkeypatch, fault)
                fired.append(True)
        return original(writer)
    monkeypatch.setattr(identity._PartnerWrite, "checkpoint", current)
    response = await put(w)
    assert fired == [True] and len(seen) == checkpoint_index
    assert response.status_code in {401, 403, 409, 503}, response.text
    assert await state(w) == before


@pytest.mark.parametrize("phase", ["typed", "parent", "profile", "type", "children"])
@pytest.mark.parametrize("fault", FAULTS)
async def test_actual_listener_barrier_after_wait_keeps_fresh_auth_full_scalar_and_gates(world, monkeypatch, phase, fault):
    w, ready, box, injected = world, asyncio.Event(), {}, []
    original = identity.acquire_scoped_locks
    def issuer(db, plan):
        box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); ready.set()
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", issuer)
    before = await state(w)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        if phase == "typed":
            await locks.acquire_scoped_locks_async(blocker, locks.LockPlan((
                locks.LockRequest(locks.TypeCatalogKey(w.code), locks.LockMode.EXCLUSIVE),)))
        elif phase == "parent":
            await blocker.execute(select(Organization).where(Organization.id == w.extra_org).with_for_update())
        elif phase == "profile":
            await blocker.execute(select(Profile).where(Profile.installation_id == w.iid).with_for_update())
        elif phase == "type":
            await blocker.execute(text("SELECT code FROM core.contract_types WHERE code=:c FOR UPDATE"), {"c": w.code})
        else:
            pid = await blocker.scalar(select(Profile.id).where(Profile.installation_id == w.iid))
            await blocker.execute(text("SELECT id FROM core.partner_contract_create_principals WHERE profile_id=:p FOR UPDATE"), {"p": pid})
        task = asyncio.create_task(put(w))
        engine = w.factory.kw["bind"].sync_engine
        marker = {"typed": "pg_advisory_xact_lock", "parent": "FROM organizations",
                  "profile": "FROM partner_contract_create_profiles", "type": "core.contract_types",
                  "children": "FROM partner_contract_create_principals"}[phase]
        def after_wait(conn, cursor, statement, params, context, many):
            if injected or marker not in statement or not (phase == "typed" or "FOR SHARE" in statement or "FOR UPDATE" in statement):
                return
            if conn.scalar(text("SELECT pg_backend_pid()")) != box["pid"]:
                return
            injected.append(True)
            _negative_current_fault(w, conn, monkeypatch, fault)
        try:
            await asyncio.wait_for(ready.wait(), 5)
            await blocked(w, box["pid"], bp)
            event.listen(engine, "after_cursor_execute", after_wait)
            try:
                await blocker.commit()
                response = await asyncio.wait_for(task, 10)
                assert injected == [True], f"after-wait fault did not run: phase={phase}, fault={fault}, injected={injected}"
                assert response.status_code in {401, 403, 409, 503}, response.text
            finally:
                event.remove(engine, "after_cursor_execute", after_wait)
        finally:
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    assert await state(w) == before


def _m15_current_record(item, context):
    """Read actual compiler/Connection metadata only; never execute extra SQL.

    Expanding binds may already be split into native per-parameter entries.
    Keep those exact test-memory values, including UUID vs opaque TEXT IDs.
    No SQL text/bind dump is logged or persisted by this collector.
    """
    from sqlalchemy.sql import operators, visitors
    from sqlalchemy.sql.elements import BinaryExpression, BindParameter, Null
    from sqlalchemy.sql.selectable import Select
    assert isinstance(item, Select) and item._for_update_arg is None
    compiled = context.compiled
    assert compiled is not None and isinstance(compiled.statement, Select)
    assert len(context.compiled_parameters) == 1
    parameters = context.compiled_parameters[0]
    tables = item.get_final_froms()
    assert len(tables) == 1
    table = tables[0].name
    assert tuple(column.name for column in item.selected_columns) == tuple(
        column.name for column in compiled.statement.selected_columns)
    predicates = []
    # A cached compiled.statement can be a previous equivalent Select. Its
    # bind_names belong to THAT tree; values belong to THIS execution context.
    for node in visitors.iterate(compiled.statement.whereclause):
        if not isinstance(node, BinaryExpression):
            continue
        assert getattr(getattr(node.left, "table", None), "name", None) == table
        name = node.left.name
        if isinstance(node.right, Null):
            assert node.operator is operators.is_
            predicates.append((name, "is", None))
            continue
        assert isinstance(node.right, BindParameter)
        bind = compiled.bind_names[node.right]
        if node.operator is operators.in_op:
            if bind in parameters:
                values = tuple(parameters[bind])
            else:
                keys = context._expanded_parameters[bind]
                assert keys and len(keys) == len(set(keys))
                values = tuple(parameters[key] for key in keys)
            assert 1 <= len(values) <= 256 and len(values) == len(set(values))
            predicates.append((name, "in", values))
        else:
            assert node.operator is operators.eq
            predicates.append((name, "eq", parameters[bind]))
    return (table, tuple(column.name for column in item.selected_columns),
            tuple(sorted(predicates, key=lambda value: (value[0], value[1], repr(value[2])))))


def _m15_expected_record(model, ids, pointers, *, grouped):
    """Expected native predicates from the independently checked frozen plan.

    This builds metadata, not a SQL statement or simulated SQL result.
    Preserve repeated Member predicates and its NULL/present role shape.
    """
    pointer_names = {
        Company: (), App: (), User: (), PartnerClient: ("app_id", "owner_company_id"),
        CompanyRole: ("company_id",), UserCompany: ("company_id", "user_id", "role_id"),
        CompanyApp: ("company_id", "app_id"), PartnerInstallation: ("company_id", "client_id"),
        PartnerGrant: ("company_id", "client_id", "installation_id", "user_id", "kind"),
        PartnerCredential: ("client_id",), ServiceLocation: ("company_id",),
        Counterparty: ("company_id",), Organization: ("company_id",),
    }
    if grouped:
        assert model in (Company, User, ServiceLocation, Counterparty, Organization)
        predicates = [("id", "in", tuple(ident[0] for ident in ids))]
    else:
        assert len(ids) == 1
        names = ("user_id", "company_id") if model is UserCompany else ("id",)
        predicates = [(name, "eq", value) for name, value in zip(names, ids[0])]
    predicates.extend((name, "is" if value is None else "eq", value)
                      for name, value in zip(pointer_names[model], pointers))
    return (model.__tablename__, tuple(column.name for column in model.__table__.c),
            tuple(sorted(predicates, key=lambda value: (value[0], value[1], repr(value[2])))))


def _m15_assert_current_records(actual, expected):
    # List equality enforces model/tenant/chunk order, native IDs and statement
    # count. Counter also makes omission/duplicate/unexpected obligations explicit.
    assert len(actual) == len(expected)
    assert Counter(actual) == Counter(expected)
    assert actual == expected


@pytest.mark.parametrize("case_id,principal_count,ref_count,canonical_count,credential_count", [
    ("graph-1", 1, 1, 1, 0), ("graph-2", 2, 2, 2, 0), ("graph-8", 8, 8, 8, 0),
    ("graph-100", 100, 100, 100, 0), ("mixed-large-100-257", 100, 100, 257, 0),
    ("principals-1", 1, 1, 1, 0), ("principals-2", 2, 1, 1, 0),
    ("principals-8", 8, 1, 1, 0), ("principals-100", 100, 1, 1, 0),
    ("refs-1", 1, 1, 1, 0), ("refs-2", 1, 2, 1, 0),
    ("refs-8", 1, 8, 1, 0), ("refs-100", 1, 100, 1, 0),
    ("canonical-1", 1, 1, 1, 0), ("canonical-2", 1, 1, 2, 0),
    ("canonical-8", 1, 1, 8, 0), ("canonical-257", 1, 1, 257, 0),
    ("credentials-1", 1, 1, 1, 1), ("credentials-2", 1, 1, 1, 2), ("credentials-8", 1, 1, 1, 8),
])
async def test_scaling_principals_refs_targets_chunk_tail_same_root_B_and_DML2(
        world, monkeypatch, case_id, principal_count, ref_count, canonical_count, credential_count):
    """Original five worlds plus separate principal/ref/canonical/credential axes.

    Credential cardinality is UNBOUNDED in inspected model/issuer/discovery
    source; 1/2/8 are samples, never maximum coverage or a production limit.
    Largest worlds remain LARGE NOTRUN / ROOT resource admission needed;
    canonical-257 keeps p=r=1 for a separate smaller 258-ID chunk proof.
    All cases are authored, not skipped or run by this source-only repair.
    """
    w = world
    suffix = uuid4().hex[:12]
    users, locations, cps, orgs = [w.member], [w.loc], [w.cp], [w.org]
    canonical_locations, credentials, owned = [w.loc], [], []
    async with w.factory() as db:
        for index in range(max(canonical_count, ref_count) - 1):
            loc = "  M15:Ёё:" + suffix + ":" + str(index) + "  "
            owned.append(("ServiceLocation", loc))
            db.add(ServiceLocation(id=loc, company_id=w.company, code="m15-"+suffix+str(index),
                                   name="M15 opaque", source_bindings=[]))
            await db.flush()
            if index < canonical_count - 1:
                rid = uuid4(); owned.append(("PartnerResourceItem", rid))
                db.add(PartnerResourceItem(id=rid, installation_id=w.iid, kind="objects", object_id=loc))
                canonical_locations.append(loc)
            if index < ref_count - 1:
                cp, org = uuid4(), uuid4()
                owned.extend((("Counterparty", cp), ("Organization", org)))
                db.add_all([Counterparty(id=cp, company_id=w.company, name="M15 CP", aliases=[]),
                    Organization(id=org, company_id=w.company, name="M15 Org", inn="", prefix="S")])
                locations.append(loc); cps.append(cp); orgs.append(org)
        await db.flush()
        for index in range(principal_count - 1):
            uid = uuid4()
            owned.extend((("User", uid), ("UserCompany", (uid, w.company))))
            db.add(User(id=uid, company_id=w.home, name="M15 member", email=uuid4().hex+"@m15.invalid", password_hash="synthetic"))
            await db.flush()
            db.add(UserCompany(user_id=uid, company_id=w.company, role="user", role_id=w.role,
                               own_organization_id=orgs[min(index+1, len(orgs)-1)], object_scope=None))
            users.append(uid)
        for _index in range(credential_count):
            cid = uuid4()
            credentials.append(cid); owned.append(("PartnerCredential", cid))
            db.add(PartnerCredential(id=cid, client_id=w.client_id,
                secret_hash=sha256(uuid4().bytes).hexdigest(), enabled=True,
                expires_at=identity.now()+timedelta(hours=1)))
        w.m15_owned = (*getattr(w, "m15_owned", ()), *owned)
        await db.commit()
    assert len(owned) == (2 * principal_count + 2 * ref_count + max(ref_count, canonical_count)
                          + canonical_count - 6 + credential_count)
    response = await w.http.put(w.base, headers=w.headers, json={**w.selection,
        "userIds": list(map(str, users)), "locationIds": locations,
        "counterpartyIds": list(map(str, cps)), "organizationIds": list(map(str, orgs)),
        "typeCodes": [w.code], "expectedGeneration": 1})
    assert response.status_code == 200, response.text
    async with w.factory() as db:
        app_id = (await db.get(PartnerClient, w.client_id)).app_id
        profile_id = await db.scalar(select(Profile.id).where(Profile.installation_id == w.iid))
        # Include actual route-generated replacement descendants in cleanup
        # metadata. ROOT still owns admission and deletion in FK-safe order.
        descendants = []
        for model, names in ((Principal, ("id",)), (Ref, ("id",)), (Type, ("profile_id", "type_code"))):
            rows = (await db.execute(select(*(getattr(model, name) for name in names)).where(
                model.profile_id == profile_id))).all()
            descendants.extend((model.__name__, row[0] if len(row) == 1 else tuple(row)) for row in rows)
        assert len(descendants) == principal_count + 3 * ref_count + 2
        w.m15_owned = (*w.m15_owned, *descendants)
    # Full fixture closure: includes admin, foreign home and each extra_* row.
    expected_specs = [
        (Company, (w.company,), ()), (Company, (w.home,), ()), (App, (app_id,), ()),
        (PartnerClient, (w.client_id,), (app_id, w.home)),
        (CompanyRole, (w.role,), (w.company,)),
        (CompanyApp, (w.iid,), (w.company, app_id)),
        (PartnerInstallation, (w.iid,), (w.company, w.client_id)),
        (PartnerGrant, (w.grant,), (w.company, w.client_id, w.iid, None, "machine")),
    ]
    expected_specs += [(User, (uid,), ()) for uid in (*users, w.admin)]
    expected_specs += [(UserCompany, (uid, w.company), (w.company, uid, w.role)) for uid in users]
    expected_specs += [(UserCompany, (w.admin, w.company), (w.company, w.admin, None))]
    expected_specs += [(PartnerCredential, (cid,), (w.client_id,)) for cid in credentials]
    expected_specs += [(ServiceLocation, (loc,), (w.company,)) for loc in (*canonical_locations, w.extra_loc)]
    expected_parents = {Counterparty: tuple(sorted((*cps, w.extra_cp))),
                        Organization: tuple(sorted((*orgs, w.extra_org))),
                        ServiceLocation: tuple(sorted(set((*locations, *canonical_locations, w.extra_loc))))}
    frozen, expected_identity, expected_parent = [], [], []
    original_freeze = activation.ActivationOperation.freeze
    def freeze(operation, db, ordered, installation_sets, credential_sets):
        result = original_freeze(operation, db, ordered, installation_sets, credential_sets)
        actual = [(spec.model, spec.identity, spec.pointers) for spec in ordered]
        assert len(actual) == len(expected_specs) and Counter(actual) == Counter(expected_specs)
        assert all(not spec.missing and not spec.update for spec in ordered)
        assert operation.credential_sets == {w.client_id: tuple(sorted(credentials, key=str))}
        assert set(operation.parents) == {(model, ident) for model, ids in expected_parents.items() for ident in ids}
        frozen.append(tuple(actual))
        covered = set()
        for model, ident, pointers in actual:
            if model in (Company, User, ServiceLocation):
                key = (model, pointers)
                if key in covered:
                    continue
                covered.add(key)
                ids = tuple(row[1] for row in actual if (row[0], row[2]) == key)
                for start in range(0, len(ids), 256):
                    chunk = ids[start:start+256]
                    expected_identity.append(_m15_expected_record(model, chunk, pointers, grouped=len(chunk) > 1))
            else:
                expected_identity.append(_m15_expected_record(model, (ident,), pointers, grouped=False))
        # Parent insertion order is owned by unchanged freeze/discover. Check
        # its COMPLETE IDs independently, then preserve exact native chunk order.
        for model in (Counterparty, Organization, ServiceLocation):
            ids = tuple(ident for kind, ident in operation.parents if kind is model)
            assert set(ids) == set(expected_parents[model]) and len(ids) == len(expected_parents[model])
            for start in range(0, len(ids), 256):
                expected_parent.append(_m15_expected_record(model, tuple((ident,) for ident in ids[start:start+256]),
                                                           (w.company,), grouped=True))
        return result
    calls, roots, checkpoints, current_passes, physical, dml = [], [], [], [], [], []
    active_pass, executing, current_entities = [], {}, []
    all_sql_count = [0]
    original_b, original_call = identity.acquire_scoped_locks, activation.activate_partner_contract_create_profile
    original_checkpoint, original_refresh = identity._PartnerWrite.checkpoint, activation.ActivationOperation.refresh_identity
    original_recheck, original_graph, original_rows = activation.ActivationOperation.recheck, activation.ProfileOperation.recheck, activation._rows
    def issuer(db, plan):
        cap = original_b(db, plan)
        calls.append((db, db.get_transaction(), db.connection(), cap, plan))
        return cap
    def invoke(db, *args):
        roots.append((db, db.get_transaction(), db.connection()))
        return original_call(db, *args)
    def checkpoint(writer):
        frame = {"index": len(checkpoints)+1, "passes": [], "rows": 0, "graph": 0, "SQL": 0}
        checkpoints.append(frame)
        result = original_checkpoint(writer)
        assert frame["passes"] == [("ORM", len(expected_identity)),
                                   ("SCALAR_IDENTITY", len(expected_identity)), ("PARENT", len(expected_parent))]
        assert frame["rows"] == len(expected_identity) + len(expected_parent) and frame["graph"] == 1
        return result
    def refresh(operation, db, specs):
        assert tuple((spec.model, spec.identity, spec.pointers) for spec in specs) == frozen[0]
        current_passes.append(len(specs))
        actual, entities = [], []
        active_pass.append(("ORM", actual, None))
        current_entities.append(entities)
        try:
            result = original_refresh(operation, db, specs)
        finally:
            current_entities.pop()
            active_pass.pop()
        _m15_assert_current_records(actual, expected_identity)
        expected_entities = [(model, ident) for model, ident, _pointers in expected_specs]
        assert len(entities) == len(expected_entities) and Counter(entities) == Counter(expected_entities)
        checkpoints[-1]["passes"].append(("ORM", len(actual)))
        return result
    def loaded(target, context):
        if current_entities:
            model, values = type(target), vars(target)
            names = ("user_id", "company_id") if model is UserCompany else ("id",)
            # Event data only: no new ORM getters, strong refs or fallback SQL.
            current_entities[-1].append((model, tuple(values[name] for name in names)))
    def refreshed(target, context, attrs):
        loaded(target, context)
    def graph(operation, db):
        active_pass.append(("GRAPH", None, None))
        try:
            result = original_graph(operation, db)
        finally:
            active_pass.pop()
        checkpoints[-1]["graph"] += 1
        return result
    def rows(db, statement):
        if not active_pass or active_pass[-1][0] != "RECHECK":
            return original_rows(db, statement)
        frame = checkpoints[-1]
        assert frame["graph"] == 1  # independent scalar follows original graph
        index = frame["rows"]
        expected = expected_identity + expected_parent
        assert index < len(expected)
        phase = "SCALAR_IDENTITY" if index < len(expected_identity) else "PARENT"
        actual = []
        active_pass.append((phase, actual, statement))
        try:
            result = original_rows(db, statement)
        finally:
            active_pass.pop()
        _m15_assert_current_records(actual, [expected[index]])
        table, columns, predicates = expected[index]
        # Exact actual returned cardinality/native keys, without replacing any
        # row or trusting a representative. Original full frozen comparison runs.
        key_names = ("user_id", "company_id") if table == "user_companies" else ("id",)
        indexes = tuple(columns.index(name) for name in key_names)
        actual_keys = [tuple(row[position] for position in indexes) for row in result]
        in_values = [value for name, op, value in predicates if name == "id" and op == "in"]
        expected_keys = ([(value,) for value in in_values[0]] if in_values else
                         [tuple(next(value for name, op, value in predicates if name == key and op == "eq") for key in key_names)])
        assert len(actual_keys) == len(expected_keys) and Counter(actual_keys) == Counter(expected_keys)
        frame["rows"] += 1
        return result
    def recheck(operation, db):
        residual = []
        active_pass.append(("RECHECK", residual, None))
        try:
            result = original_recheck(operation, db)
        finally:
            active_pass.pop()
        expected_sets = [
            ("partner_installation_locations", ("location_id",), (("installation_id", "eq", w.iid),)),
            ("partner_resource_scopes", ("kind", "mode"), (("installation_id", "eq", w.iid),)),
            ("partner_resource_items", ("id", "kind", "object_id", "equipment_id", "counterparty_id", "contract_id", "document_id"),
             (("installation_id", "eq", w.iid),)),
            ("partner_credentials", ("id",), (("client_id", "eq", w.client_id),)),
        ]
        _m15_assert_current_records(residual, expected_sets)
        checkpoints[-1]["passes"].extend((("SCALAR_IDENTITY", len(expected_identity)), ("PARENT", len(expected_parent))))
        return result
    from sqlalchemy.sql import operators, visitors
    from sqlalchemy.sql.elements import BinaryExpression, BindParameter
    from sqlalchemy.sql.selectable import Select
    def before_execute(conn, clauseelement, multiparams, params, execution_options):
        if active_pass and active_pass[-1][0] != "GRAPH":
            assert conn is calls[0][2]
            assert conn not in executing
            executing[conn] = clauseelement  # identity of REAL original statement
    def sql(conn, cursor, statement, params, context, many):
        all_sql_count[0] += 1
        if checkpoints:
            checkpoints[-1]["SQL"] += 1
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            dml.append(statement)
        compiled = context.compiled
        item = compiled.statement if compiled else None
        if active_pass and active_pass[-1][0] != "GRAPH":
            phase, records, original_statement = active_pass[-1]
            actual_statement = executing.pop(conn)
            if original_statement is not None:
                assert actual_statement is original_statement
            if phase == "ORM":
                assert context.execution_options.get("populate_existing") is True
            records.append(_m15_current_record(actual_statement, context))
        if not isinstance(item, Select) or item._for_update_arg is None:
            return
        tables = item.get_final_froms()
        if len(tables) != 1 or tables[0].name not in {"counterparties", "organizations", "service_locations", "user_companies"}:
            return
        table = tables[0].name
        name = "user_id" if table == "user_companies" else "id"
        parameters = context.compiled_parameters[0]
        ids = [parameters[compiled.bind_names[node.right]] for node in visitors.iterate(item.whereclause)
               if isinstance(node, BinaryExpression) and node.operator is operators.eq
               and getattr(node.left, "name", None) == name and isinstance(node.right, BindParameter)]
        assert ids and len(set(ids)) == 1
        assert item._for_update_arg.read and not item._for_update_arg.key_share
        physical.append((table, ids[0]))
    monkeypatch.setattr(activation.ActivationOperation, "freeze", freeze)
    monkeypatch.setattr(identity, "acquire_scoped_locks", issuer)
    monkeypatch.setattr(activation, "activate_partner_contract_create_profile", invoke)
    monkeypatch.setattr(identity._PartnerWrite, "checkpoint", checkpoint)
    monkeypatch.setattr(activation.ActivationOperation, "refresh_identity", refresh)
    monkeypatch.setattr(activation.ActivationOperation, "recheck", recheck)
    monkeypatch.setattr(activation.ProfileOperation, "recheck", graph)
    monkeypatch.setattr(activation, "_rows", rows)
    engine = w.factory.kw["bind"].sync_engine
    observed_models = tuple(dict.fromkeys(model for model, _ident, _pointers in expected_specs))
    for model in observed_models:
        event.listen(model, "load", loaded)
        event.listen(model, "refresh", refreshed)
    event.listen(engine, "before_execute", before_execute)
    event.listen(engine, "before_cursor_execute", sql)
    try:
        response = await put(w, generation=2)
    finally:
        event.remove(engine, "before_cursor_execute", sql)
        event.remove(engine, "before_execute", before_execute)
        for model in observed_models:
            event.remove(model, "refresh", refreshed)
            event.remove(model, "load", loaded)
    assert response.status_code == 200, response.text
    assert not executing and not active_pass and len(frozen) == 1
    assert len(calls) == len(roots) == 1
    db, root, connection, cap, plan = calls[0]
    assert roots[0] == (db, root, connection)
    expected = {key: locks.LockMode.SHARED for key in (
        locks.CompanyKey(w.company), locks.CompanyKey(w.home), locks.AppKey(app_id),
        locks.ClientKey(w.client_id), locks.RoleKey(w.company, w.role),
        locks.RefCompositeKey(w.company), locks.TypeCatalogKey(w.code))}
    expected.update({locks.UserKey(uid): locks.LockMode.SHARED for uid in (*users, w.admin)})
    expected.update({locks.MemberKey(w.company, uid): locks.LockMode.SHARED for uid in (*users, w.admin)})
    expected[locks.InstallationKey(w.iid)] = locks.LockMode.EXCLUSIVE
    expected[locks.CreateProfileKey(profile_id)] = locks.LockMode.EXCLUSIVE
    assert len(plan.requests) == len(expected)
    assert {request.key: request.mode for request in plan.requests} == expected
    expected_physical = [(table, ident) for table, ids in (
        ("counterparties", (*cps, w.extra_cp)), ("organizations", (*orgs, w.extra_org)),
        ("service_locations", set((*locations, *canonical_locations, w.extra_loc)))) for ident in sorted(ids)]
    expected_physical += [("user_companies", uid) for uid in sorted((*users, w.admin), key=str)]
    assert physical == expected_physical
    assert len(checkpoints) == len(current_passes)
    # Original checkpoint formula; credentials add real identity locks/checkpoints.
    identity_count = 2 + 1 + 1 + (principal_count + 1) + 1 + (principal_count + 1) + 1 + 1 + 1 + credential_count
    parent_count = (ref_count + 1) * 2 + max(ref_count, canonical_count) + 1
    assert len(checkpoints) == identity_count + parent_count + 1 + 11
    assert all(count == len(expected_specs) for count in current_passes)
    assert len(dml) == 2
    assert sum("partner_contract_create_profiles" in statement for statement in dml) == 1
    assert sum("audit_events" in statement for statement in dml) == 1
    for records, ids in ((expected_identity, (*canonical_locations, w.extra_loc)),
                         (expected_parent, tuple(set((*locations, *canonical_locations, w.extra_loc))))):
        loc_chunks = [value for table, _columns, predicates in records if table == "service_locations"
                      for name, op, value in predicates if name == "id" and op == "in"]
        assert Counter(value for chunk in loc_chunks for value in chunk) == Counter(ids)
        if canonical_count == 257:
            assert tuple(map(len, loc_chunks)) == (256, 2)  # fixture extra_loc counts
    assert all(frame["SQL"] > 0 for frame in checkpoints) and all_sql_count[0] > 0
    with pytest.raises(locks.ScopedLockError):
        locks.require_scoped_locks(db, cap, plan.requests)  # completed original root
    assert (await state(w))["generation"] == 3


async def test_original_fixture_same_call_budget_is_only_a_proposal_and_pending_flags_survive(world, monkeypatch):
    w, checkpoints, sessions, statements = world, [], [], []
    original = identity._PartnerWrite.checkpoint
    def checkpoint(writer):
        sessions.append((writer.db, writer.db.get_transaction(), writer.db.connection()))
        checkpoints.append(True)
        return original(writer)
    monkeypatch.setattr(identity._PartnerWrite, "checkpoint", checkpoint)
    engine = w.factory.kw["bind"].sync_engine
    def count(conn, cursor, statement, params, context, many):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", count)
    try:
        response = await put(w)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert response.status_code == 200, response.text
    assert len(checkpoints) == 31
    assert all(item == sessions[0] for item in sessions)
    assert len(statements) <= 1600  # Proposed same original synthetic CALL only.
    after = await state(w)
    assert after["generation"] == 2 and after["user"] and after["service"]


@pytest.mark.parametrize("fault", ["cancel", "exception"])
async def test_no_cache_survives_cancel_rollback_new_transaction_or_new_request(world, monkeypatch, fault):
    w, seen = world, []
    before = await state(w)
    original = activation.ActivationOperation.refresh_identity
    def fail(operation, db, specs):
        result = original(operation, db, specs)
        seen.append((operation, db, db.get_transaction()))
        if fault == "cancel":
            raise asyncio.CancelledError()
        raise RuntimeError("M15 negative fault after original ORM refresh")
    with monkeypatch.context() as patch:
        patch.setattr(activation.ActivationOperation, "refresh_identity", fail)
        if fault == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await put(w)
        else:
            assert (await put(w)).status_code == 500
    assert len(seen) == 1 and await state(w) == before
    # Actual committed drift in a fresh transaction must be seen by a new request.
    async with w.factory() as db:
        (await db.get(User, w.admin)).token_version += 1
        await db.commit()
    assert (await put(w)).status_code == 401
    assert await state(w) == before


async def test_real_canonical_issuer_activation_remains_structural_only(issuer_world, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.database import get_db
    from app.routers import partner_admin_router
    w = issuer_world
    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", True)
    token = await native_org_admin(w)
    async with w.factory() as db:
        (await db.get(PartnerGrant, w.machine_grant)).approved = False
        await db.commit()
    app = FastAPI(); app.include_router(partner_admin_router.router, prefix="/api")
    async def actual_sessions():
        async with w.factory() as db:
            yield db
    app.dependency_overrides[get_db] = actual_sessions
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://issuer.synthetic.invalid") as http:
        response = await http.put(f"/api/developer/installations/{w.iid}/contract-create-profile/activation",
            headers={"Authorization": "Bearer " + token},
            json={"expectedGeneration": 1, "userEnabled": True, "serviceEnabled": True})
    assert response.status_code == 200, response.text
    async with w.factory() as db:
        with pytest.raises(HTTPException) as error:
            await identity.verify_partner_access_token(w.machine, db)
        assert error.value.status_code == 401


@pytest.mark.parametrize("kind,column,first,second", [
    ("Company", "customization", None, {}),
    ("Company", "customization", {}, {"nested": {"values": [None, [], {"opaque": "  Ёё  "}]}}),
    ("ServiceLocation", "source_bindings", [], [{"nested": {"values": [None, [], "  Ёё  "]}}]),
])
async def test_grouped_second_row_mutable_full_scalar_json_is_deeply_frozen(world, monkeypatch, kind, column, first, second):
    w, fired = world, []
    model = {"Company": Company, "ServiceLocation": ServiceLocation}[kind]
    original_freeze = activation.ActivationOperation.freeze
    selected = []
    def freeze(operation, db, ordered, installation_sets, credential_sets):
        batches = [batch for batch in activation._identity_batches(ordered) if len(batch) > 1 and batch[0].model is model]
        assert len(batches) == 1
        selected.append(batches[0][1].identity[0])
        # Setup belongs to a separate committed transaction BEFORE the tested
        # activation; no mutation is hidden inside discovery/freeze itself.
        return original_freeze(operation, db, ordered, installation_sets, credential_sets)
    # Determine second literal ID from source-admitted fixture ordering.
    ids = sorted((w.company, w.home), key=str) if model is Company else sorted((w.loc, w.extra_loc))
    ident = ids[1]
    async with w.factory() as db:
        setattr(await db.get(model, ident), column, first)
        await db.commit()
    original = activation.ActivationOperation.refresh_identity
    def external(operation, db, specs):
        result = original(operation, db, specs)
        if not fired:
            async def commit():
                async with w.factory() as writer:
                    setattr(await writer.get(model, ident), column, second)
                    await writer.commit()
            await_only(commit()); fired.append(True)
        return result
    monkeypatch.setattr(activation.ActivationOperation, "freeze", freeze)
    monkeypatch.setattr(activation.ActivationOperation, "refresh_identity", external)
    before = await _snapshot(w)
    response = await put(w)
    assert selected == [ident] and fired == [True] and response.status_code == 409, response.text
    assert await _snapshot(w) == before


async def test_each_checkpoint_emits_both_fresh_passes_in_original_order_without_per_id_fallback(world, monkeypatch):
    w, trace, current = world, [], []
    original_refresh, original_recheck = activation.ActivationOperation.refresh_identity, activation.ActivationOperation.recheck
    original_graph = activation.ProfileOperation.recheck
    def refresh(operation, db, specs):
        current.append("ORM"); trace.append("ORM.enter")
        try:
            return original_refresh(operation, db, specs)
        finally:
            trace.append("ORM.exit"); current.pop()
    def graph(operation, db):
        trace.append("ProfileOperation.recheck")
        return original_graph(operation, db)
    def recheck(operation, db):
        current.append("scalar"); trace.append("scalar.enter")
        try:
            return original_recheck(operation, db)
        finally:
            trace.append("scalar.exit"); current.pop()
    def sql(conn, cursor, statement, params, context, many):
        if not current or not statement.lstrip().upper().startswith("SELECT"):
            return
        item = context.compiled.statement if context.compiled else None
        # Observe only the three explicitly grouped models, not a universal
        # SQL detector. Native/admin reads occur outside these pass scopes.
        tables = item.get_final_froms() if hasattr(item, "get_final_froms") else ()
        if len(tables) == 1 and tables[0].name in {"companies", "users", "service_locations"}:
            trace.append((current[-1], tables[0].name, statement, conn))
    monkeypatch.setattr(activation.ActivationOperation, "refresh_identity", refresh)
    monkeypatch.setattr(activation.ActivationOperation, "recheck", recheck)
    monkeypatch.setattr(activation.ProfileOperation, "recheck", graph)
    engine = w.factory.kw["bind"].sync_engine
    event.listen(engine, "before_cursor_execute", sql)
    try:
        response = await put(w)
    finally:
        event.remove(engine, "before_cursor_execute", sql)
    assert response.status_code == 200, response.text
    assert trace.count("ORM.enter") == trace.count("scalar.enter") == trace.count("ProfileOperation.recheck") == 31
    position = 0
    for _checkpoint in range(31):
        start = trace.index("ORM.enter", position)
        orm_end = trace.index("ORM.exit", start)
        scalar_start = trace.index("scalar.enter", orm_end)
        profile = trace.index("ProfileOperation.recheck", scalar_start)
        scalar_end = trace.index("scalar.exit", profile)
        orm = [row for row in trace[start:orm_end] if isinstance(row, tuple)]
        assert sorted(row[1] for row in orm) == ["companies", "service_locations", "users"]
        assert all(" IN (" in row[2] for row in orm)
        # scalar includes untouched home/ref reads; exactly one full-column IN
        # per grouped model plus a separate ServiceLocation parent IN.
        scalar = [row for row in trace[profile:scalar_end] if isinstance(row, tuple) and " IN (" in row[2]]
        assert sorted(row[1] for row in scalar) == ["companies", "service_locations", "service_locations", "users"]
        assert all(row[3] is orm[0][3] for row in (*orm, *scalar))
        position = scalar_end + 1
