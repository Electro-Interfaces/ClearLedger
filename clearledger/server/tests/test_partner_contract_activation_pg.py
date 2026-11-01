"""AUTHOR ONLY / NOTRUN (also collection). ROOT must provide the admitted
activation_admin_factory on isolated schema4/Core, READ COMMITTED. No runner,
environment/URL selection, approval, DDL or positive auth/SQL stand-ins here.
Parent conftest is destructive; do not collect without ROOT's composition.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.auth import token_for
from app.database import get_db
from app.models import (App, AuditEvent, Company, CompanyApp, CompanyRole, Contract,
                        Counterparty, DocCard, DocKind, EzsEquipmentUnit,
                        Organization, ServiceLocation, User, UserCompany)
from app.models_partner import (PartnerClient, PartnerGrant, PartnerInstallation,
                                PartnerInstallationLocation, PartnerResourceScope, PartnerResourceItem)
from app.models_partner_contracts import (PartnerContractCreateProfile as Profile,
    PartnerContractCreatePrincipal as Principal, PartnerContractCreateRef as Ref,
    PartnerContractCreateType as Type, PartnerContractSuccessIntent as Intent)
from app.routers import partner_admin_router
from app.services import partner_identity as identity, contract_write_locks as locks
from app.services import partner_contract_activation as activation
from tests.partner_contract_issuer_fixture import issuer_world, native_org_admin

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def world(activation_admin_factory, monkeypatch):
    factory = activation_admin_factory
    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", True)
    monkeypatch.setattr(identity.settings, "partner_oauth_enabled", True)
    suffix = uuid4().hex
    async with factory() as db:
        assert await db.scalar(text("SHOW transaction_isolation")) == "read committed"
        assert await db.scalar(text("SELECT current_schema()")) == "core"
        company = Company(id=uuid4(), name="Synthetic activation", slug="ac-"+suffix, profile_id="energy")
        home = Company(id=uuid4(), name="Synthetic home", slug="ah-"+suffix, profile_id="energy")
        db.add_all([company, home]); await db.flush()
        admin = User(id=uuid4(), company_id=company.id, name="Activation admin",
            email="a"+suffix+"@activation.invalid", password_hash="synthetic", is_superadmin=False)
        member = User(id=uuid4(), company_id=home.id, name="Activation member",
            email="m"+suffix+"@activation.invalid", password_hash="synthetic", is_superadmin=False)
        role = CompanyRole(id=uuid4(), company_id=company.id, name="Synthetic role", modules=None)
        db.add_all([admin, member, role]); await db.flush()
        cp = Counterparty(id=uuid4(), company_id=company.id, name="Profile CP", aliases=[])
        extra_cp = Counterparty(id=uuid4(), company_id=company.id, name="Member CP", aliases=[])
        org = Organization(id=uuid4(), company_id=company.id, name="Profile Org", inn="", prefix="S")
        extra_org = Organization(id=uuid4(), company_id=company.id, name="Admin Org", inn="", prefix="T")
        loc = ServiceLocation(id="  ОПАК:"+suffix[:16]+"  ", company_id=company.id,
            code="al-"+suffix, name="Profile location", source_bindings=[])
        extra_loc = ServiceLocation(id="extra-"+suffix[:16], company_id=company.id,
            code="ax-"+suffix, name="Canonical location", source_bindings=[])
        db.add_all([cp, extra_cp, org, extra_org, loc, extra_loc]); await db.flush()
        db.add_all([UserCompany(user_id=admin.id, company_id=company.id, role="admin",
                                own_organization_id=extra_org.id),
                    UserCompany(user_id=member.id, company_id=company.id, role="user",
                                role_id=role.id, organization_id=extra_cp.id,
                                own_organization_id=org.id, object_scope=None)])
        app = App(id=uuid4(), code="ac-"+suffix, name="Synthetic partner", kind="partner", is_active=False)
        db.add(app); await db.flush()
        client_id = "ac-"+suffix
        db.add(PartnerClient(id=client_id, app_id=app.id, owner_company_id=home.id,
            auth_method="client_secret_basic", enabled=False, redirect_uris=[], allowed_scopes=[]))
        await db.flush()
        iid = uuid4()
        db.add(CompanyApp(id=iid, company_id=company.id, app_id=app.id, enabled=False)); await db.flush()
        db.add(PartnerInstallation(id=iid, company_id=company.id, client_id=client_id,
            approved=False, scopes=[], all_locations=True)); await db.flush()
        grant = PartnerGrant(id=uuid4(), installation_id=iid, company_id=company.id,
            client_id=client_id, kind="machine", user_id=None, approved=False, scopes=[])
        db.add(grant)
        db.add_all([PartnerResourceScope(installation_id=iid, kind="counterparties", mode="ALL"),
                    PartnerResourceScope(installation_id=iid, kind="objects", mode="SET")])
        await db.flush()
        db.add_all([PartnerResourceItem(installation_id=iid, kind="objects", object_id=loc.id),
                    PartnerResourceItem(installation_id=iid, kind="objects", object_id=extra_loc.id)])
        code, inactive = "ac-"+suffix, "ai-"+suffix
        await db.execute(text("INSERT INTO core.contract_types(code,label,is_active) VALUES (:c,'Synthetic',true),(:i,'Inactive',false)"),
                         {"c": code, "i": inactive})
        await db.commit()
        w = SimpleNamespace(factory=factory, company=company.id, home=home.id, admin=admin.id,
            member=member.id, role=role.id, iid=iid, client_id=client_id, grant=grant.id,
            cp=cp.id, extra_cp=extra_cp.id, org=org.id, extra_org=extra_org.id,
            loc=loc.id, extra_loc=extra_loc.id, code=code, inactive=inactive)
        # Both tokens are signed from their actual own User, never ID-substituted claims.
        w.headers = {"Authorization": "Bearer "+token_for(admin, expires_at=identity.now()+timedelta(minutes=20))}
        w.member_headers = {"Authorization": "Bearer "+token_for(member, expires_at=identity.now()+timedelta(minutes=20))}
    app = FastAPI()
    app.include_router(partner_admin_router.router, prefix="/api")
    async def sessions():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = sessions  # Actual AsyncSession; native auth untouched.
    w.base = f"/api/developer/installations/{iid}/contract-create-profile"
    w.path = w.base+"/activation"
    w.selection = dict(userIds=[str(w.member)], machineGrantIds=[str(w.grant)],
        organizationIds=[str(w.org)], counterpartyIds=[str(w.cp)], locationIds=[w.loc],
        typeCodes=[w.code, w.inactive])
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="https://synthetic.invalid") as http:
        w.http = http
        # Existing replace forbids adding inactive types. First create with the
        # active code, then deactivate that unrelated second selected code.
        async with factory() as db:
            await db.execute(text("UPDATE core.contract_types SET is_active=true WHERE code=:c"), {"c": inactive})
            await db.commit()
        response = await http.put(w.base, headers=w.headers, json=w.selection)
        assert response.status_code == 200, response.text
        assert response.json()["userEnabled"] is False and response.json()["serviceEnabled"] is False
        async with factory() as db:
            await db.execute(text("UPDATE core.contract_types SET is_active=false WHERE code=:c"), {"c": inactive})
            await db.commit()
        yield w


async def put(w, generation=1, user=True, service=True, headers=None):
    return await w.http.put(w.path, headers=w.headers if headers is None else headers,
        json=dict(expectedGeneration=generation, userEnabled=user, serviceEnabled=service))


async def state(w):
    """Independent fresh SQL, including full child rows and business counts."""
    async with w.factory() as db:
        profile = (await db.execute(select(Profile).where(Profile.installation_id == w.iid))).scalar_one()
        children = []
        for model in (Principal, Ref, Type):
            rows = (await db.execute(select(*model.__table__.c).where(model.profile_id == profile.id))).all()
            children.append(tuple(sorted(tuple(map(str, row)) for row in rows)))
        audit = (await db.execute(select(AuditEvent.action, AuditEvent.details).where(
            AuditEvent.company_id == w.company).order_by(AuditEvent.timestamp, AuditEvent.id))).all()
        counts = tuple([await db.scalar(select(func.count()).select_from(model).where(
            model.company_id == w.company)) for model in (Contract, Intent, PartnerGrant)])
        return dict(generation=profile.policy_generation, user=profile.user_enabled,
            service=profile.service_enabled, children=tuple(children), audit=tuple(audit), counts=counts)


async def assert_unchanged(w, before):
    assert await state(w) == before


async def test_enable_same_flags_disable_and_new_cas_rollback_keep_children_and_counts(world):
    w = world
    before = await state(w)
    for generation, user, service in [(1, True, True), (2, True, True), (3, False, False), (4, True, False)]:
        result = await put(w, generation, user, service)
        assert result.status_code == 200, result.text
        assert result.json()["policyGeneration"] == generation+1
        assert (result.json()["userEnabled"], result.json()["serviceEnabled"]) == (user, service)
    after = await state(w)
    assert after["children"] == before["children"] and after["counts"] == before["counts"]
    events = [json.loads(details) for action, details in after["audit"] if action == "partner.contract_profile.activation"]
    assert [e["generation"] for e in events] == [2, 3, 4, 5]
    assert all(set(e) == {"profileId", "generation", "userEnabled", "serviceEnabled"} for e in events)
    assert (await put(w, 1)).status_code == 409


async def test_real_native_nonadmin_invalid_bearer_and_closed_gate(world, monkeypatch):
    w = world
    before = await state(w)
    assert (await put(w, headers=w.member_headers)).status_code == 403
    assert (await put(w, headers={"Authorization": "Bearer invalid"})).status_code == 401
    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", False)
    assert (await put(w)).status_code == 503
    await assert_unchanged(w, before)


@pytest.mark.parametrize("case", ["missing", "stale", "overflow", "revoked"])
async def test_missing_cas_overflow_and_revoked_enable_denied(world, case):
    w = world
    async with w.factory() as db:
        if case == "missing":
            await db.execute(text("DELETE FROM core.partner_contract_create_profiles WHERE installation_id=:i"), {"i": w.iid})
        elif case == "overflow":
            await db.execute(text("UPDATE core.partner_contract_create_profiles SET policy_generation=9223372036854775807 WHERE installation_id=:i"), {"i": w.iid})
        elif case == "revoked":
            await db.execute(text("UPDATE core.partner_contract_create_profiles SET revoked=true WHERE installation_id=:i"), {"i": w.iid})
        await db.commit()
    if case == "missing":
        assert (await put(w)).status_code == 404
        return
    before = await state(w)
    response = await put(w, 2 if case == "stale" else before["generation"])
    assert response.status_code == 409, response.text
    await assert_unchanged(w, before)
    if case == "revoked":
        assert (await put(w, 1, False, False)).status_code == 200


@pytest.mark.parametrize("empty", ["user", "machine", "org", "cp", "loc", "types", "member_scope", "own_org", "objects", "counterparties", "installation"])
async def test_true_requires_corresponding_principal_and_nonempty_legal_selection(world, empty):
    w = world
    async with w.factory() as db:
        pid = await db.scalar(select(Profile.id).where(Profile.installation_id == w.iid))
        if empty in {"user", "machine"}:
            await db.execute(text("DELETE FROM core.partner_contract_create_principals WHERE profile_id=:p AND actor_kind=:k"), {"p": pid, "k": empty})
        elif empty in {"org", "cp", "loc"}:
            kind = {"org": "organization", "cp": "counterparty", "loc": "location"}[empty]
            await db.execute(text("DELETE FROM core.partner_contract_create_refs WHERE profile_id=:p AND kind=:k"), {"p": pid, "k": kind})
        elif empty == "types":
            await db.execute(text("UPDATE core.contract_types SET is_active=false WHERE code=:c"), {"c": w.code})
        elif empty == "member_scope":
            await db.execute(text("UPDATE core.user_companies SET object_scope='[]'::jsonb WHERE user_id=:u AND company_id=:c"), {"u": w.member, "c": w.company})
        elif empty == "own_org":
            await db.execute(text("UPDATE core.user_companies SET own_organization_id=:o WHERE user_id=:u AND company_id=:c"), {"o": w.extra_org, "u": w.member, "c": w.company})
        elif empty in {"objects", "counterparties"}:
            await db.execute(text("UPDATE core.partner_resource_scopes SET mode='EMPTY' WHERE installation_id=:i AND kind=:k"), {"i": w.iid, "k": empty})
        else:
            await db.execute(text("UPDATE core.partner_installations SET all_locations=false WHERE id=:i"), {"i": w.iid})
        await db.commit()
    before = await state(w)
    # User-only constraints cannot incorrectly veto a requested machine-only enable.
    response = await put(w, user=empty != "machine", service=empty not in {"user", "member_scope", "own_org"})
    assert response.status_code == 409, response.text
    await assert_unchanged(w, before)
    assert (await put(w, user=False, service=False)).status_code == 200


async def test_one_original_b_exact_x_keys_full_closure_and_physical_parent_union(world, monkeypatch):
    from collections import Counter
    from sqlalchemy import Column, Integer, Table
    from sqlalchemy.sql import operators, visitors
    from sqlalchemy.sql.annotation import (AnnotatedBinaryExpression, AnnotatedBindParameter,
        AnnotatedBooleanClauseList, AnnotatedColumn, AnnotatedTable)
    from sqlalchemy.sql.base import DialectKWArgs
    from sqlalchemy.sql.dml import Delete, Insert, Update
    from sqlalchemy.sql.elements import (BindParameter, BinaryExpression, BooleanClauseList,
        ClauseList, ColumnClause, False_, Grouping, Null, TextClause, True_, quoted_name)
    from sqlalchemy.sql.selectable import ForUpdateArg, HasHints, HasPrefixes, HasSuffixes, Select
    from sqlalchemy.sql.sqltypes import NullType
    from app.models_partner import PartnerCredential

    w, observed, sql, dml = world, [], [], []
    parent_tables = tuple(model.__table__ for model in
                          (Counterparty, Organization, ServiceLocation, UserCompany))
    # Finite current activation grammar, not an arbitrary SQLAlchemy program.
    # Exact annotation wrappers retain ordinary ORM entity/column SELECTs.
    mapped_tables = tuple(model.__table__ for model in (
        App, AuditEvent, Company, CompanyApp, CompanyRole, Counterparty,
        Organization, ServiceLocation, User, UserCompany, Contract, DocCard,
        EzsEquipmentUnit, PartnerClient, PartnerCredential, PartnerGrant,
        PartnerInstallation, PartnerInstallationLocation, PartnerResourceScope,
        PartnerResourceItem, Profile, Principal, Ref, Type))
    mapped_columns = tuple(column for table in mapped_tables for column in table.c)
    expression_types = (Select, Insert, Update, TextClause, Table, AnnotatedTable,
        Column, AnnotatedColumn, BindParameter, BinaryExpression, BooleanClauseList,
        AnnotatedBindParameter, AnnotatedBinaryExpression, AnnotatedBooleanClauseList,
        ClauseList, Grouping, Null, True_, False_, ForUpdateArg)
    # Exact source-owned text statements only: raw/unclassified SQL must fail
    # closed, including commented or WITH-prefixed DML and driver SQL.
    read_only_text = {
        "SELECT pg_advisory_xact_lock_shared(CAST(:namespace AS INTEGER), CAST(:key AS INTEGER))",
        "SELECT pg_advisory_xact_lock(CAST(:namespace AS INTEGER), CAST(:key AS INTEGER))",
        "SELECT code, is_active FROM core.contract_types WHERE code=:code",
        "SELECT code FROM core.contract_types WHERE code=:code FOR SHARE",
    }

    def bound_identity(statement, compiled, context, table, names):
        where = statement.whereclause
        assert isinstance(where, BooleanClauseList) and where.operator is operators.and_
        values = {name: [] for name in names}
        assert len(context.compiled_parameters) == 1
        parameters = context.compiled_parameters[0]
        for term in where.clauses:
            assert isinstance(term, BinaryExpression)
            column = term.left
            if (getattr(column, "table", None) is not None
                    and column.table._deannotate() is table and column.name in values):
                assert term.operator is operators.eq and isinstance(term.right, BindParameter)
                # compiled may be cached; the current execution owns the values.
                values[column.name].append(parameters[compiled.bind_names[term.right]])
        assert all(items and all(value == items[0] for value in items) for items in values.values())
        return tuple(values[name][0] for name in names)

    original = identity.acquire_scoped_locks
    original_activation = activation.activate_partner_contract_create_profile
    contexts = []
    def observe(db, plan):
        cap = original(db, plan)
        locks.require_scoped_locks(db, cap, plan.requests)
        observed.append((db, db.get_transaction(), db.connection(), cap, plan))
        return cap
    def on_actual_session(db, *args):
        root, connection = db.get_transaction(), db.connection()
        result = original_activation(db, *args)
        assert len(observed) == 1
        actual, acquired_root, acquired_connection, cap, plan = observed[0]
        assert actual is db and acquired_root is root and acquired_connection is connection
        assert db.get_transaction() is root and db.connection() is connection
        locks.require_scoped_locks(db, cap, plan.requests)
        contexts.append((db, root, connection))
        return result
    def statements(conn, cursor, statement, params, context, many):
        compiled = context.compiled
        assert compiled is not None, "Unclassified driver SQL during activation"
        assert not many, "Unexpected executemany during activation"
        invoked = compiled.statement
        state = compiled.compile_state
        actual = invoked if isinstance(invoked, TextClause) else state.statement
        # SQLAlchemy 2.0.36 initializes ctes only upon encountering a CTE;
        # nested WITH rendering can empty that mapping again. Require None,
        # not merely an empty mapping, before accepting ANY statement.
        assert compiled.ctes is None, "Unexpected compiled CTE source during activation"
        if (isinstance(invoked, (Insert, Update, Delete))
                or isinstance(actual, (Insert, Update, Delete))):
            # The pinned ORM flush creates core Table.insert()/update().
            # Seal BOTH roots to those exact primitives: dialect/annotated
            # subclasses may render extensions outside visitor traversal.
            assert type(invoked) is type(actual) and type(actual) in (Insert, Update), \
                "Unexpected nonprimitive DML root during activation"
            assert compiled.dml_compile_state is state
            for expression in (invoked, actual):
                if type(expression) is Insert:
                    # ON CONFLICT SET/WHERE can be opaque traversal leaves.
                    # Reject every post-values extension, even on core Insert.
                    assert expression._post_values_clause is None, \
                        "Unexpected INSERT post-values clause during activation"
                    assert expression.select is None, "Unexpected INSERT SELECT source during activation"
                    # dp_dml_multi_values is another opaque children slot.
                    assert not expression._multi_values, "Unexpected multi-values INSERT during activation"
            # UPDATE infers FROM separately from get_children(), including
            # proxy-column tables in WHERE/SET. Check the compiler-owned
            # collection directly; this flat profile write needs no FROM.
            if type(actual) is Update:
                assert not state._extra_froms, "Unexpected DML FROM source during activation"
        # literal_column renders raw SQL but is a traversal leaf, even inside
        # SELECT/CTE/DML expressions. Check both compiled trees before any
        # acceptance/early return. This activation uses mapped columns/binds;
        # state's count(*) runs outside this listener, so no literal escape.
        for expression in (invoked, actual):
            expression_nodes = tuple(visitors.iterate(expression))
            for node in expression_nodes:
                # Check the owning mixins directly: hints contain plain strings
                # outside get_children(), and dialect options are opaque too.
                # No dialect or literal-specific exception and no getattr-based
                # positive fallback; reject metadata even if PG ignores it.
                if isinstance(node, HasHints):
                    assert not node._statement_hints, "Unexpected statement hints during activation"
                if isinstance(node, (Select, Insert, Update, Delete)):
                    assert not node._hints, "Unexpected table hints during activation"
                if isinstance(node, HasPrefixes):
                    assert not node._prefixes, "Unexpected SQL prefixes during activation"
                if isinstance(node, HasSuffixes):
                    assert not node._suffixes, "Unexpected SQL suffixes during activation"
                if isinstance(node, DialectKWArgs):
                    assert not node.dialect_kwargs, "Unexpected dialect extensions during activation"
                # Unsupported opaque functions, custom nodes, labels, aliases,
                # raw ColumnClause names and operator strings are not admitted.
                assert type(node) in expression_types, "Unexpected SQL construct during activation"
                if type(node) in (Table, AnnotatedTable, Column, AnnotatedColumn):
                    plain = node._deannotate()
                    if isinstance(node, Table):
                        assert any(plain is table for table in mapped_tables)
                        assert node.schema is None and plain.schema is None
                    else:
                        assert any(plain is column for column in mapped_columns)
                        assert node.table is plain.table and node.type is plain.type
                    assert node.name == plain.name
                    name = node.name
                    assert type(name) in (str, quoted_name)
                    assert type(name) is str or name.quote is not False
                    assert (name and name.isascii() and (name[0].isalpha() or name[0] == "_")
                            and all(char.isalnum() or char == "_" for char in name)), \
                        "Unexpected SQL identifier during activation"
                if isinstance(node, BindParameter):
                    assert not node.literal_execute, "Unexpected literal-execute bind during activation"
                    assert (type(node.type) in (NullType, Integer)
                            or any(node.type is column.type for column in mapped_columns)), \
                        "Unexpected bind SQL type during activation"
                if isinstance(node, BinaryExpression):
                    assert any(node.operator is operator for operator in
                               (operators.eq, operators.in_op, operators.is_))
                    assert not node.modifiers
                if isinstance(node, BooleanClauseList):
                    assert node.operator is operators.and_
                if type(node) is ClauseList:
                    assert node.operator is operators.comma_op
            if isinstance(expression, (Insert, Update, Delete)):
                assert not any(isinstance(node, Select) for node in expression_nodes), \
                    "Unexpected DML SELECT source during activation"
            assert not any(isinstance(node, ColumnClause) and node.is_literal
                           for node in expression_nodes), \
                "Unexpected literal column SQL during activation"
            # Only a root Select may own a row lock. Traverse both trees,
            # including scalar subqueries, aliases and CTEs, before any return
            # or DML acceptance: outer nonlocking SELECT/DML cannot hide one.
            # Pinned activation sources require no nested locking SELECT.
            assert not any(isinstance(node, Select) and node is not expression
                           and node._for_update_arg is not None
                           for node in expression_nodes), \
                "Unexpected nested row lock during activation"
            assert not any(node is not expression
                           and isinstance(node, (Insert, Update, Delete, TextClause))
                           for node in expression_nodes), \
                "Unexpected nested DML or textual SQL during activation"
        if isinstance(invoked, TextClause):
            assert invoked.text in read_only_text, "Unexpected textual SQL during activation"
            assert not (context.isinsert or context.isupdate or context.isdelete)
            return
        flags = (context.isinsert, context.isupdate, context.isdelete)
        if isinstance(actual, (Insert, Update, Delete)):
            operation = type(actual)
            assert flags == tuple(operation is kind for kind in (Insert, Update, Delete))
            assert all(node is actual for node in visitors.iterate(actual)
                       if isinstance(node, (Insert, Update, Delete)))
            assert not any(isinstance(node, TextClause) for node in visitors.iterate(actual))
            table = actual.table
            assert isinstance(table, Table)
            expected = {Insert: AuditEvent.__table__, Update: Profile.__table__}
            assert operation in expected and table._deannotate() is expected[operation]
            assert (table.name, table.schema) == (expected[operation].name, expected[operation].schema)
            assert not many and len(context.compiled_parameters) == 1
            assert len(observed) == 1 and conn is observed[0][2]
            dml.append((operation, table.name, table.schema))
            return
        assert isinstance(actual, Select) and flags == (False, False, False)
        nodes = tuple(visitors.iterate(actual))
        assert not any(isinstance(node, (Insert, Update, Delete, TextClause)) for node in nodes), \
            "Unexpected nested DML or textual SQL during activation"
        locking = actual._for_update_arg
        if locking is None:
            return
        tables = [table for table in parent_tables if any(
            isinstance(node, Table) and (node.name, node.schema) == (table.name, table.schema)
            for node in nodes)]
        if not tables:
            return
        assert len(tables) == 1
        table = tables[0]
        froms = actual.get_final_froms()
        assert len(froms) == 1 and isinstance(froms[0], Table)
        assert froms[0]._deannotate() is table
        assert (froms[0].name, froms[0].schema) == (table.name, table.schema)
        assert locking.read is True
        assert not locking.key_share and not locking.nowait and not locking.skip_locked
        assert locking.of is None
        assert not many
        assert len(observed) == 1 and conn is observed[0][2]
        names = ("user_id", "company_id") if table is UserCompany.__table__ else ("id", "company_id")
        ident, company = bound_identity(actual, compiled, context, table, names)
        assert company == w.company
        sql.append((table, ident))
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    monkeypatch.setattr(activation, "activate_partner_contract_create_profile", on_actual_session)
    engine = w.factory.kw["bind"].sync_engine
    event.listen(engine, "before_cursor_execute", statements)
    try:
        assert (await put(w)).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", statements)
    assert len(observed) == 1
    assert len(contexts) == 1
    assert len(dml) == 2
    assert Counter(dml) == Counter({
        (Insert, AuditEvent.__table__.name, AuditEvent.__table__.schema): 1,
        (Update, Profile.__table__.name, Profile.__table__.schema): 1,
    })
    db, root, connection, cap, plan = observed[0]
    assert len(plan.requests) == len({r.key for r in plan.requests})
    keys = {r.key: r.mode for r in plan.requests}
    assert keys[locks.InstallationKey(w.iid)] == locks.LockMode.EXCLUSIVE
    assert keys[locks.CreateProfileKey(UUID((await w.http.get(w.base, headers=w.headers)).json()["profileId"]))] == locks.LockMode.EXCLUSIVE
    assert {locks.CompanyKey(w.home), locks.RoleKey(w.company, w.role), locks.UserKey(w.member)} <= keys.keys()
    expected_parents = [(model.__table__, ident)
        for model, ids in ((Counterparty, (w.cp, w.extra_cp)),
                           (Organization, (w.org, w.extra_org)),
                           (ServiceLocation, (w.loc, w.extra_loc)))
        for ident in sorted(ids)]
    expected_members = [(UserCompany.__table__, ident) for ident in sorted((w.admin, w.member), key=str)]
    # Exactly the physical union, once per ID, in canonical model/ID order;
    # every parent SHARE precedes the first Member SHARE on the original root.
    assert sql == expected_parents + expected_members
    with pytest.raises(locks.ScopedLockError):
        locks.require_scoped_locks(db, cap, plan.requests)  # Completed original root.


async def blocked(w, pid, blocker_pid):
    for _ in range(300):
        async with w.factory() as observer:
            waiting = await observer.scalar(text("SELECT :b=ANY(pg_blocking_pids(:p))"), {"b": blocker_pid, "p": pid})
            rows = (await observer.execute(text("SELECT granted FROM pg_locks WHERE pid=:p"), {"p": pid})).all()
        if waiting:
            assert any(not row.granted for row in rows)
            return
        await asyncio.sleep(.01)
    raise AssertionError("Actual request PID did not wait on the actual blocker")


@pytest.mark.parametrize("phase", ["typed", "parent", "profile", "type", "children"])
@pytest.mark.parametrize("change", ["token", "admin", "closed_gate", "member_pointer"])
async def test_actual_last_wait_rechecks_current_native_and_full_member_pointers(world, monkeypatch, phase, change):
    w, ready, pid_box = world, asyncio.Event(), {}
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        pid_box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); ready.set()
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    before = await state(w)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        assert bp != pid_box.get("pid")
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
            await blocker.execute(select(Principal).where(Principal.profile_id == pid).with_for_update())
        task = asyncio.create_task(put(w))
        try:
            await asyncio.wait_for(ready.wait(), 5)
            await blocked(w, pid_box["pid"], bp)
            injected = []
            marker = {"typed": "pg_advisory_xact_lock", "parent": Organization.__table__.name,
                      "profile": Profile.__table__.name,
                      "type": "core.contract_types", "children": Principal.__table__.name}[phase]
            def after_actual_wait(conn, cursor, statement, params, context, many):
                if injected or marker not in statement or not (
                        phase == "typed" or "FOR SHARE" in statement or "FOR UPDATE" in statement):
                    return
                if conn.scalar(text("SELECT pg_backend_pid()")) != pid_box["pid"]:
                    return
                injected.append(True)
                # Deliberate negative injection into the ACTUAL request root
                # immediately after its proven SQL wait returns. No verifier,
                # auth result or lock success is mocked; same-root UPDATE also
                # works after this request already holds User/Member SHARE.
                if change == "closed_gate":
                    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", False)
                elif change == "member_pointer":
                    conn.execute(text("UPDATE core.user_companies SET own_organization_id=:o WHERE user_id=:u AND company_id=:c"),
                                 {"o": w.extra_org, "u": w.member, "c": w.company})
                elif change == "token":
                    conn.execute(text("UPDATE core.users SET token_version=token_version+1 WHERE id=:u"), {"u": w.admin})
                else:
                    conn.execute(text("UPDATE core.user_companies SET role='user' WHERE user_id=:u AND company_id=:c"),
                                 {"u": w.admin, "c": w.company})
            engine = w.factory.kw["bind"].sync_engine
            event.listen(engine, "after_cursor_execute", after_actual_wait)
            try:
                await blocker.commit()
                response = await asyncio.wait_for(task, 5)
                assert response.status_code in {401, 403, 409, 503}, response.text
                assert injected == [True]
            finally:
                event.remove(engine, "after_cursor_execute", after_actual_wait)
        finally:
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    await assert_unchanged(w, before)


@pytest.mark.parametrize("failure", ["fault", "cancel", "token", "admin", "closed_gate"])
async def test_actual_flush_flags_audit_and_public_auth_failure_roll_back_whole_root(world, monkeypatch, failure):
    w, seen = world, []
    before = await state(w)
    def after_flush(db, context):
        actions = db.scalars(select(AuditEvent).where(AuditEvent.company_id == w.company,
                            AuditEvent.action == "partner.contract_profile.activation")).all()
        if not actions:
            return
        profile = db.scalar(select(Profile).where(Profile.installation_id == w.iid))
        assert profile.policy_generation == 2 and profile.user_enabled and profile.service_enabled
        assert len(actions) == 1
        seen.append(profile.policy_generation)
        if failure == "fault":
            raise RuntimeError("Synthetic fault AFTER actual SQL flush")
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "token":
            db.execute(text("UPDATE core.users SET token_version=token_version+1 WHERE id=:u"), {"u": w.admin})
        elif failure == "admin":
            db.execute(text("UPDATE core.user_companies SET role='user' WHERE user_id=:u AND company_id=:c"), {"u": w.admin, "c": w.company})
        else:
            monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", False)
    event.listen(Session, "after_flush_postexec", after_flush)
    try:
        if failure == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await put(w)
        else:
            assert (await put(w)).status_code in {401, 403, 409, 500, 503}
    finally:
        event.remove(Session, "after_flush_postexec", after_flush)
    assert seen == [2]
    await assert_unchanged(w, before)


@pytest.mark.parametrize("contender", ["replace", "revoke", "activation"])
async def test_concurrent_activation_replace_revoke_are_one_winner_stale_409(world, contender):
    w = world
    before = await state(w)
    other = (put(w, 1, False, False) if contender == "activation" else
        w.http.put(w.base, headers=w.headers, json={**w.selection,
            "typeCodes": [w.code], "expectedGeneration": 1, "revoked": contender == "revoke"}))
    responses = await asyncio.gather(put(w), other)
    assert sorted(r.status_code for r in responses) == [200, 409]
    after = await state(w)
    assert after["generation"] == 2 and len(after["audit"]) == len(before["audit"])+1
    assert after["counts"] == before["counts"]


async def test_unknown_commit_ack_requires_fresh_current_auth_readback_and_new_cas(world, monkeypatch):
    w, original, fired = world, AsyncSession.commit, False
    before = await state(w)
    async def lost_ack(db):
        nonlocal fired
        await original(db)
        if not fired:
            fired = True
            raise ConnectionError("Synthetic loss AFTER commit; outcome unknown to caller")
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", lost_ack)
        assert (await put(w)).status_code == 500
    result = await w.http.get(w.base, headers=w.headers)
    assert result.status_code == 200 and result.json()["policyGeneration"] == 2
    after = await state(w)
    assert after["children"] == before["children"] and after["counts"] == before["counts"]
    assert len(after["audit"]) == len(before["audit"])+1
    assert (await put(w)).status_code == 409
    assert (await put(w, 2, False, False)).status_code == 200


async def test_cancel_during_actual_typed_wait_does_not_mutate(world, monkeypatch):
    w, ready, box = world, asyncio.Event(), {}
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); ready.set()
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    before = await state(w)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await locks.acquire_scoped_locks_async(blocker, locks.LockPlan((
            locks.LockRequest(locks.InstallationKey(w.iid), locks.LockMode.EXCLUSIVE),)))
        task = asyncio.create_task(put(w))
        try:
            await asyncio.wait_for(ready.wait(), 5)
            await blocked(w, box["pid"], bp)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await blocker.rollback()
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
    await assert_unchanged(w, before)


@pytest.mark.parametrize("disabled", ["app", "grant", "both"])
async def test_structural_activation_never_restores_actual_external_oauth_or_post_authority(issuer_world, monkeypatch, disabled):
    """Ratified msg_cc8cade6fd88: configuration can precede OAuth readiness.

The SAME Authlib-issued bearer first passes the real canonical verifier, then
loses actual SQL eligibility, then stays denied after successful activation.
"""
    from app.product_api.app import create_product_api
    from app.product_api import budget
    w = issuer_world
    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", True)
    async with w.factory() as db:
        current = await identity.verify_partner_access_token(w.machine, db)
        assert current.is_machine and current.grant_id == w.machine_grant
        assert "contracts:create" in current.scopes
    admin_token = await native_org_admin(w)  # Actual new admin SQL + own signed claims.
    headers = {"Authorization": "Bearer "+admin_token}
    parent = FastAPI()
    parent.include_router(partner_admin_router.router, prefix="/api")
    async def get_sessions():
        async with w.factory() as db:
            yield db
    parent.dependency_overrides[get_db] = get_sessions
    path = f"/api/developer/installations/{w.iid}/contract-create-profile/activation"
    async with AsyncClient(transport=ASGITransport(app=parent), base_url="https://synthetic.invalid") as http:
        off = await http.put(path, headers=headers,
            json=dict(expectedGeneration=1, userEnabled=False, serviceEnabled=False))
        assert off.status_code == 200 and off.json()["policyGeneration"] == 2
        async with w.factory() as db:
            if disabled in {"app", "both"}:
                (await db.get(App, w.app_id)).is_active = False
            if disabled in {"grant", "both"}:
                (await db.get(PartnerGrant, w.machine_grant)).approved = False
            await db.commit()
        async def oauth_state():
            async with w.factory() as db:
                queries = [select(*PartnerGrant.__table__.c).where(PartnerGrant.installation_id == w.iid),
                    select(*PartnerInstallation.__table__.c).where(PartnerInstallation.id == w.iid),
                    select(*CompanyApp.__table__.c).where(CompanyApp.id == w.iid),
                    select(*PartnerResourceScope.__table__.c).where(PartnerResourceScope.installation_id == w.iid),
                    select(*PartnerResourceItem.__table__.c).where(PartnerResourceItem.installation_id == w.iid)]
                return tuple([tuple(sorted(tuple(map(str, row)) for row in (await db.execute(query)).all()))
                              for query in queries])
        before, oauth_before = await state(w), await oauth_state()
        assert before["counts"][:2] == (0, 0)
        async with w.factory() as db:
            with pytest.raises(HTTPException) as error:
                await identity.verify_partner_access_token(w.machine, db)
            assert error.value.status_code == 401
        on = await http.put(path, headers=headers,
            json=dict(expectedGeneration=2, userEnabled=True, serviceEnabled=True))
        assert on.status_code == 200, on.text
        assert on.json()["policyGeneration"] == 3 and on.json()["userEnabled"] and on.json()["serviceEnabled"]
    async with w.factory() as db:
        with pytest.raises(HTTPException) as error:
            await identity.verify_partner_access_token(w.machine, db)
        assert error.value.status_code == 401
    @asynccontextmanager
    async def actual_sessions():
        async with w.factory() as db:
            yield db
    child = create_product_api(session_factory=actual_sessions, enabled=True,
        issuer="https://issuer.synthetic.invalid", cursor_key=b"synthetic-activation-key-32bytes!!",
        budget_policy=budget.Policy(enabled=False))
    external = FastAPI()
    external.mount("/api/v1", child)
    async with AsyncClient(transport=ASGITransport(app=external), base_url="https://issuer.synthetic.invalid") as http:
        denied = await http.post("/api/v1/contracts", headers={"Authorization": "Bearer "+w.machine,
                                 "Content-Type": "application/json"},
                                 content=w.body.model_dump_json())
    assert denied.status_code == 401
    after = await state(w)
    assert after["children"] == before["children"] and after["counts"] == before["counts"]
    assert len(after["audit"]) == len(before["audit"])+1
    assert await oauth_state() == oauth_before  # No consent/grant/resource issuance or rewrites.


async def test_exact_type_purpose_and_subclass_rejection_on_actual_native_session(world):
    from app.services.partner_contract_profiles import ProfileOperation, profile_core_user
    from app.schemas_partner import ActivateContractCreateProfile
    w = world
    class Child(activation.ActivationOperation):
        pass
    body = ActivateContractCreateProfile(expectedGeneration=1, userEnabled=False, serviceEnabled=False)
    for purpose, operation in [
            ("contract-profile-activation", Child(w.iid, body)),
            ("contract-profile-activation", ProfileOperation(w.iid, None)),
            ("contract-profile-read", activation.ActivationOperation(w.iid, body)),
            ("contract-profile-write", activation.ActivationOperation(w.iid, body)),
            ("contract-create", activation.ActivationOperation(w.iid, body))]:
        async with w.factory() as db:
            credentials = SimpleNamespace(credentials=w.headers["Authorization"][7:])
            actor = await profile_core_user(db, credentials)
            native = identity._native_authority(db, credentials, actor)
            with pytest.raises(locks.ScopedLockError):
                await db.run_sync(lambda sync: identity._prepare_partner_write(sync,
                    installation_id=w.iid, company_id=w.company, client_id=w.client_id,
                    admin_company=w.company, actor=actor, native=native,
                    mutation=purpose, contract_profile=operation))
            await db.rollback()


@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_internal_service_leaves_original_root_completion_to_actual_caller(world, finish):
    from app.schemas_partner import ActivateContractCreateProfile
    from app.services.partner_contract_profiles import profile_core_user
    w = world
    before = await state(w)
    async with w.factory() as db:
        credentials = SimpleNamespace(credentials=w.headers["Authorization"][7:])
        actor = await profile_core_user(db, credentials)
        native = identity._native_authority(db, credentials, actor)
        root = db.sync_session.get_transaction()
        result = await db.run_sync(activation.activate_partner_contract_create_profile,
            w.iid, actor, native, ActivateContractCreateProfile(
                expectedGeneration=1, userEnabled=True, serviceEnabled=True))
        assert result.policyGeneration == 2 and db.sync_session.get_transaction() is root
        await assert_unchanged(w, before)  # Fresh SQL cannot see uncommitted flags/audit.
        if finish == "commit":
            await db.commit()
        else:
            await db.rollback()
    after = await state(w)
    if finish == "rollback":
        assert after == before
    else:
        assert after["generation"] == 2 and len(after["audit"]) == len(before["audit"])+1
        assert after["children"] == before["children"] and after["counts"] == before["counts"]


async def test_empty_actual_member_rows_keep_explicit_parent_boundary(world, monkeypatch):
    w = world
    async with w.factory() as db:
        await db.execute(text("DELETE FROM core.partner_contract_create_principals WHERE profile_id=(SELECT id FROM core.partner_contract_create_profiles WHERE installation_id=:i) AND actor_kind='user'"), {"i": w.iid})
        await db.execute(text("DELETE FROM core.user_companies WHERE company_id=:c"), {"c": w.company})
        await db.execute(text("UPDATE core.users SET is_superadmin=true WHERE id=:u"), {"u": w.admin})
        await db.commit()
    original = activation.ActivationOperation.lock_parents
    boundaries = []
    def boundary(operation):
        assert not operation.writer.db.execute(select(UserCompany.user_id).where(
            UserCompany.company_id == w.company)).all()
        boundaries.append(True)
        return original(operation)
    monkeypatch.setattr(activation.ActivationOperation, "lock_parents", boundary)
    response = await put(w, user=False, service=True)
    assert response.status_code == 200, response.text
    assert boundaries == [True]


@pytest.mark.parametrize("drift", ["home", "role", "member_cp", "children"])
async def test_external_committed_graph_drift_during_real_b_wait_never_expands_plan(world, monkeypatch, drift):
    w, ready, box, issued = world, asyncio.Event(), {}, []
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); ready.set()
        issued.append(plan)
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    before = await state(w)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await locks.acquire_scoped_locks_async(blocker, locks.LockPlan((
            locks.LockRequest(locks.TypeCatalogKey(w.code), locks.LockMode.EXCLUSIVE),)))
        task = asyncio.create_task(put(w))
        try:
            await asyncio.wait_for(ready.wait(), 5)
            await blocked(w, box["pid"], bp)
            if drift == "home":
                await blocker.execute(text("UPDATE core.users SET company_id=NULL WHERE id=:u"), {"u": w.member})
            elif drift == "role":
                await blocker.execute(text("UPDATE core.company_roles SET modules='[]'::jsonb WHERE id=:r"), {"r": w.role})
            elif drift == "member_cp":
                await blocker.execute(text("UPDATE core.user_companies SET organization_id=:p WHERE user_id=:u AND company_id=:c"),
                                      {"p": w.cp, "u": w.member, "c": w.company})
            else:
                await blocker.execute(text("DELETE FROM core.partner_contract_create_types WHERE type_code=:t AND profile_id=(SELECT id FROM core.partner_contract_create_profiles WHERE installation_id=:i)"),
                                      {"t": w.inactive, "i": w.iid})
            await blocker.commit()
            response = await asyncio.wait_for(task, 5)
            assert response.status_code == 409, response.text
            assert len(issued) == 1
        finally:
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    after = await state(w)
    assert after["generation"] == before["generation"]
    assert after["audit"] == before["audit"] and after["counts"] == before["counts"]


@pytest.mark.parametrize("corruption", ["role_owner", "profile_ref_owner", "member_ref_owner"])
async def test_full_graph_foreign_owner_corruption_is_denied_before_b(world, monkeypatch, corruption):
    w, calls = world, []
    async with w.factory() as db:
        if corruption == "role_owner":
            await db.execute(text("UPDATE core.company_roles SET company_id=:c WHERE id=:r"), {"c": w.home, "r": w.role})
        else:
            rid = w.cp if corruption == "profile_ref_owner" else w.extra_cp
            await db.execute(text("UPDATE core.counterparties SET company_id=:c WHERE id=:p"), {"c": w.home, "p": rid})
        await db.commit()
    before = await state(w)
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        calls.append(plan)
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    response = await put(w)
    assert response.status_code in {409, 422}, response.text
    assert calls == []
    await assert_unchanged(w, before)


async def canonical_targets(w, *, foreign):
    """Existing native FK targets; no altered constraints or fake graph rows."""
    suffix = uuid4().hex
    async with w.factory() as db:
        cid = w.company
        if foreign:
            cid = uuid4()
            db.add(Company(id=cid, name="Other canonical tenant", slug="cf-"+suffix, profile_id="energy"))
            await db.flush()
        cp = Counterparty(id=uuid4(), company_id=cid, name="Canonical-only CP", aliases=[])
        org = Organization(id=uuid4(), company_id=cid, name="Canonical-only Org", inn="", prefix="C")
        # An unrequested whitespace-only ID is valid in native ServiceLocation
        # (the stricter profile-ref rule does not apply to canonical extras).
        location_id = ("  EXTRA:"+suffix[:16]+"  " if foreign else
                       "".join(" \t\n\r"[int(digit, 16) % 4] for digit in suffix))
        loc = ServiceLocation(id=location_id, company_id=cid,
            code="ce-"+suffix, name="Canonical-only location", source_bindings=[])
        kind = DocKind(id=uuid4(), company_id=cid, code="ce-"+suffix, name="Synthetic canonical kind")
        equipment = EzsEquipmentUnit(id=uuid4(), company_id=cid, current_location_id=loc.id)
        db.add_all([cp, org, loc, kind]); await db.flush()
        contract = Contract(id=uuid4(), company_id=cid, number="Synthetic", date="2026-11-01",
            counterparty_id=cp.id, organization_id=org.id, type="Synthetic")
        document = DocCard(id=uuid4(), company_id=cid, kind_id=kind.id,
            title="Synthetic canonical document", organization_id=org.id,
            counterparty_id=cp.id, object_id=loc.id)
        db.add_all([equipment, contract, document]); await db.commit()
        return SimpleNamespace(company=cid, location=loc.id, cp=cp.id, org=org.id,
            kind=kind.id, equipment=equipment.id, contract=contract.id, document=document.id,
            items={"objects": ("object_id", loc.id), "counterparties": ("counterparty_id", cp.id),
                   "equipment": ("equipment_id", equipment.id), "contracts": ("contract_id", contract.id),
                   "documents": ("document_id", document.id)})


async def canonical_state(w, targets):
    """Fresh SQL over raw children and both tenants' actual parent/business rows."""
    async with w.factory() as db:
        statements = [select(*model.__table__.c).where(model.installation_id == w.iid)
            for model in (PartnerInstallationLocation, PartnerResourceScope, PartnerResourceItem, PartnerGrant)]
        statements.append(select(*PartnerInstallation.__table__.c).where(PartnerInstallation.id == w.iid))
        statements.extend(select(*model.__table__.c).where(model.company_id.in_({w.company, targets.company}))
            for model in (Counterparty, Organization, ServiceLocation, EzsEquipmentUnit, Contract, DocKind, DocCard, Intent))
        return tuple([tuple(sorted(tuple(map(str, row)) for row in (await db.execute(statement)).all()))
                      for statement in statements])


async def assert_raw_canonical_denied_before_b(w, targets, monkeypatch, *, user, service):
    before, raw_before = await state(w), await canonical_state(w, targets)
    calls, actors, statements = [], [], []
    original_b, original_auth = identity.acquire_scoped_locks, activation.profile_core_user
    def observe_b(db, plan):
        calls.append(plan)
        return original_b(db, plan)  # Real original B if reached, never a success stand-in.
    async def observe_auth(db, credentials):
        actor = await original_auth(db, credentials)
        actors.append(actor.id)
        return actor
    def observe_sql(conn, cursor, statement, params, context, many):
        statements.append((statement, str(params)))
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe_b)
    monkeypatch.setattr(activation, "profile_core_user", observe_auth)
    engine = w.factory.kw["bind"].sync_engine
    event.listen(engine, "before_cursor_execute", observe_sql)
    try:
        response = await put(w, user=user, service=service)
    finally:
        event.remove(engine, "before_cursor_execute", observe_sql)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Activation profile graph is invalid"
    assert calls == [] and actors == [w.admin]
    assert all("pg_advisory_xact_lock" not in sql and "FOR SHARE" not in sql and "FOR UPDATE" not in sql
               for sql, params in statements)
    # The unrelated foreign tenant is not an original client/home company.
    # Target IDs may be used in tenant-filtered existence checks; their owner
    # and dependent FK graph must never become discovery or lock inputs.
    assert all(str(targets.company) not in params for sql, params in statements)
    for ident in (targets.org, targets.kind):
        assert all(str(ident) not in params for sql, params in statements)
    assert all(not sql.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE "))
               for sql, params in statements)
    await assert_unchanged(w, before)
    assert await canonical_state(w, targets) == raw_before


@pytest.mark.parametrize("all_locations", [True, False])
@pytest.mark.parametrize("user,service", [(True, True), (False, False)])
async def test_canonical_only_foreign_installation_location_denied_before_b(world, monkeypatch, all_locations, user, service):
    w = world
    targets = await canonical_targets(w, foreign=True)
    async with w.factory() as db:
        (await db.get(PartnerInstallation, w.iid)).all_locations = all_locations
        db.add_all([PartnerInstallationLocation(installation_id=w.iid, location_id=w.loc),
                    PartnerInstallationLocation(installation_id=w.iid, location_id=targets.location)])
        await db.commit()
        # L keeps legal intersection nonempty even when all_locations=false;
        # F is canonical-only, absent from both profile and object resource items.
        assert await db.scalar(select(PartnerResourceItem.id).where(
            PartnerResourceItem.installation_id == w.iid, PartnerResourceItem.object_id == targets.location)) is None
        assert await db.scalar(select(Ref.id).where(Ref.location_id == targets.location)) is None
    await assert_raw_canonical_denied_before_b(w, targets, monkeypatch, user=user, service=service)


@pytest.mark.parametrize("kind", ["objects", "equipment", "counterparties", "contracts", "documents"])
@pytest.mark.parametrize("mode", ["ALL", "EMPTY", "SET"])
@pytest.mark.parametrize("user,service", [(True, True), (False, False)])
async def test_each_foreign_typed_canonical_item_denied_in_every_mode_before_b(world, monkeypatch, kind, mode, user, service):
    w = world
    targets = await canonical_targets(w, foreign=True)
    async with w.factory() as db:
        scope = await db.get(PartnerResourceScope, (w.iid, kind))
        if scope is None:
            db.add(PartnerResourceScope(installation_id=w.iid, kind=kind, mode=mode))
        else:
            scope.mode = mode
        await db.flush()
        column, ident = targets.items[kind]
        db.add(PartnerResourceItem(installation_id=w.iid, kind=kind, **{column: ident}))
        await db.commit()
    await assert_raw_canonical_denied_before_b(w, targets, monkeypatch, user=user, service=service)


@pytest.mark.parametrize("all_locations", [True, False])
@pytest.mark.parametrize("mode", ["ALL", "EMPTY", "SET"])
async def test_local_canonical_extras_keep_literal_unrequested_opaque_ids_and_full_union(world, monkeypatch, all_locations, mode):
    w, calls, sql = world, [], []
    targets = await canonical_targets(w, foreign=False)
    async with w.factory() as db:
        (await db.get(PartnerInstallation, w.iid)).all_locations = all_locations
        db.add_all([PartnerInstallationLocation(installation_id=w.iid, location_id=w.loc),
                    PartnerInstallationLocation(installation_id=w.iid, location_id=targets.location)])
        for kind, (column, ident) in targets.items.items():
            scope = await db.get(PartnerResourceScope, (w.iid, kind))
            if scope is None:
                db.add(PartnerResourceScope(installation_id=w.iid, kind=kind, mode=mode))
            else:
                scope.mode = mode
            await db.flush()
            db.add(PartnerResourceItem(installation_id=w.iid, kind=kind, **{column: ident}))
        # In SET, selected CP must still be legal alongside the unrequested CP.
        db.add(PartnerResourceItem(installation_id=w.iid, kind="counterparties", counterparty_id=w.cp))
        await db.commit()
    before, raw_before = await state(w), await canonical_state(w, targets)
    original = identity.acquire_scoped_locks
    def observe_b(db, plan):
        calls.append(plan)
        return original(db, plan)
    def observe_sql(conn, cursor, statement, params, context, many):
        if "FOR SHARE" in statement or "FOR UPDATE" in statement:
            sql.append((statement, str(params)))
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe_b)
    engine = w.factory.kw["bind"].sync_engine
    event.listen(engine, "before_cursor_execute", observe_sql)
    enabled = mode != "EMPTY"
    try:
        response = await put(w, user=enabled, service=enabled)
    finally:
        event.remove(engine, "before_cursor_execute", observe_sql)
    assert response.status_code == 200, response.text
    assert len(calls) == 1 and response.json()["policyGeneration"] == 2
    assert (response.json()["userEnabled"], response.json()["serviceEnabled"]) == (enabled, enabled)
    assert len(targets.location) == 32 and targets.location.isspace()
    assert targets.location not in response.json()["locationIds"]
    member_index = next(i for i, (statement, params) in enumerate(sql) if UserCompany.__table__.name in statement)
    for table, ident in ((ServiceLocation.__table__.name, targets.location), (Counterparty.__table__.name, targets.cp)):
        literal = repr(ident) if isinstance(ident, str) else str(ident)
        entries = [(i, params) for i, (statement, params) in enumerate(sql) if table in statement and literal in params]
        assert len(entries) == 1 and entries[0][0] < member_index
    after = await state(w)
    assert after["children"] == before["children"] and after["counts"] == before["counts"]
    assert len(after["audit"]) == len(before["audit"])+1
    assert await canonical_state(w, targets) == raw_before
