"""Opt-in, synthetic PostgreSQL proof of M10 additive/backward schema compatibility.

Run separately from the HTTP identity suite: both own and clear their test DB.
The old server is extracted from immutable Git commits and runs in a subprocess;
removing new models from current metadata is NOT an old-schema fixture.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import CheckConstraint, UniqueConstraint, event, inspect, literal, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.partner_test_safety import partner_test_safety_error

SCHEMA_FLAG = "RUN_PARTNER_SCHEMA_TESTS"
if os.environ.get(SCHEMA_FLAG) != "1":
    pytest.skip("Opt in separately with RUN_PARTNER_SCHEMA_TESTS=1", allow_module_level=True)
_safety_error = partner_test_safety_error(os.environ, flag=SCHEMA_FLAG)
if _safety_error:
    raise pytest.UsageError("Refusing partner schema test database: " + _safety_error)
PROFILE = os.environ.get("PARTNER_SCHEMA_PROFILE", "public")
if PROFILE not in {"public", "core", "both"}:
    raise pytest.UsageError("PARTNER_SCHEMA_PROFILE must be public, core or both")
PROFILES = ("public", "core") if PROFILE == "both" else (PROFILE,)

from app import database
from app.auth import token_for
from app.database import Base, get_db
from app.main import app
from app.models import App, Company, CompanyApp, Counterparty, Contract, DocCard, ServiceLocation, User
from app.models_partner import PartnerClient, PartnerGrant, PartnerInstallation, PartnerResourceScope
from app.services import partner_identity

pytestmark = pytest.mark.asyncio(loop_scope="session")
REPO = Path(__file__).resolve().parents[3]
GIT_REPO = Path(os.environ.get("PARTNER_SCHEMA_GIT_REPO", str(REPO))).resolve()
OLD_REVISIONS = ("ce94e2bf", "5ce5779b")
PARTNER_TABLES = frozenset({
    "partner_clients", "partner_credentials", "partner_installations", "partner_installation_locations",
    "partner_resource_scopes", "partner_resource_items", "partner_grants", "partner_authorization_requests",
    "partner_subjects", "partner_codes", "partner_token_families", "partner_tokens",
})
BUDGET_MODEL_TABLES = {"app.models_product_budget": frozenset({"product_api_budgets"})}
OWNED_MODEL_TABLES = {"app.models_partner": PARTNER_TABLES, **BUDGET_MODEL_TABLES}
EXTENSION_MODEL_TABLES = {"app.models_docs_portal": frozenset({"partner_docs_sessions"})}
REQUIRE_PORTAL = os.environ.get("PARTNER_SCHEMA_REQUIRE_PORTAL", "0")
if REQUIRE_PORTAL not in {"0", "1"}:
    raise pytest.UsageError("PARTNER_SCHEMA_REQUIRE_PORTAL must be 0 or 1")


def candidate_model_manifest(registered, require_portal=False):
    manifest = dict(OWNED_MODEL_TABLES)
    for module, expected in BUDGET_MODEL_TABLES.items():
        if registered.get(module, set()) != expected:
            raise ValueError("Required budget model registration differs: " + module)
    for module, expected in EXTENSION_MODEL_TABLES.items():
        actual = registered.get(module, set())
        if actual:
            if actual != expected:
                raise ValueError("Unexpected table in owned extension module: " + module)
            manifest[module] = expected
    if require_portal and "app.models_docs_portal" not in manifest:
        raise ValueError("Required portal model app.models_docs_portal.DocsPortalSession is not registered")
    return manifest


_registered = {}
for _mapper in Base.registry.mappers:
    _registered.setdefault(_mapper.class_.__module__, set()).add(_mapper.local_table.name)
try:
    CANDIDATE_MODEL_TABLES = candidate_model_manifest(_registered, REQUIRE_PORTAL == "1")
except ValueError as exc:
    raise pytest.UsageError(str(exc)) from None
SUPPORT_SQL = re.compile(r'\b(?:from|join|into|update|table)\s+"?public"?\s*\.\s*"?(?:users|companies)"?\b', re.I)


def forbid_support_rows(conn, cursor, statement, parameters, context, executemany):
    assert not SUPPORT_SQL.search(statement), "Core operation explicitly addressed a public Support sentinel"

# No inheritance of production .env, keys, seed passwords, connector settings or
# proxy credentials. The archive has no .env and the child gets a minimal env.
OLD_SERVER_SCRIPT = r'''
import asyncio, json, os, re, sys, uuid
from pathlib import Path
assert os.environ["RUN_PARTNER_IDENTITY_TESTS"] == "1"
assert not (Path.cwd() / ".env").exists()
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from app.main import app
from app import database
from app.auth import token_for
from app.models import (Company, User, UserCompany, Organization, Counterparty, Contract,
    ServiceLocation, EzsEquipmentUnit, DocKind, DocCard, App, CompanyApp)
assert database.settings.database_url == os.environ["TEST_DATABASE_URL"]
if os.environ.get("PARTNER_SCHEMA_TEST_PROFILE") == "core":
    @event.listens_for(database.engine.sync_engine, "before_cursor_execute")
    def forbid_support_rows(conn,cursor,statement,parameters,context,executemany):
        assert not re.search(r'\b(?:from|join|into|update|table)\s+"?public"?\s*\.\s*"?(?:users|companies)"?\b', statement, re.I), "Old Core addressed Support sentinel"

async def check_namespace():
    if os.environ.get("PARTNER_SCHEMA_TEST_PROFILE") == "core":
        async with database.engine.connect() as conn:
            assert await conn.scalar(text("SELECT current_schema()")) == "core"
            for name in ("users", "companies"):
                found = await conn.scalar(text("SELECT n.nspname FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE c.oid=to_regclass(:name)"), {"name": name})
                assert found == "core"

async def main():
    mode = sys.argv[1]
    if mode == "bootstrap":
        await database.create_all()
        await check_namespace()
        async with database.async_session_factory.begin() as db:
            company = Company(name="Synthetic schema company", slug="schema-test", profile_id="energy")
            db.add(company)
            await db.flush()
            user = User(email="schema-test@example.invalid", name="Synthetic schema admin",
                password_hash="synthetic-no-login", company_id=company.id, role="user", is_superadmin=False)
            db.add(user)
            await db.flush()
            db.add(UserCompany(user_id=user.id, company_id=company.id, role="admin"))
            organization = Organization(company_id=company.id, inn="0000000000", name="Synthetic organization")
            counterparty = Counterparty(company_id=company.id, inn=None, name="Synthetic counterparty")
            location = ServiceLocation(id="schema-test-object", company_id=company.id, code="schema-test", name="Synthetic object")
            equipment = EzsEquipmentUnit(company_id=company.id, kind="station", serial_number="SYNTHETIC-TEST-1")
            kind = DocKind(company_id=company.id, code="schema_test", name="Synthetic document kind")
            native_app = App(code="schema-test-app", name="Synthetic native app", kind="app", is_active=True)
            db.add_all([organization, counterparty, location, equipment, kind, native_app])
            await db.flush()
            contract = Contract(company_id=company.id, number="SYNTHETIC-TEST-1", date="2026-01-01",
                organization_id=organization.id, counterparty_id=counterparty.id, type="test")
            document = DocCard(company_id=company.id, kind_id=kind.id, kind_code=kind.code,
                title="Synthetic document", author_id=user.id, object_id=location.id)
            installation = CompanyApp(company_id=company.id, app_id=native_app.id, enabled=True)
            db.add_all([contract, document, installation])
            await db.flush()
            result = {k: str(v.id) for k, v in dict(company=company, user=user, organization=organization,
                counterparty=counterparty, object=location, equipment=equipment, document=document,
                app=native_app, company_app=installation, contract=contract).items()}
        # Settle the same pre-existing bootstrap/backfill twice before taking the
        # baseline; this is the actual old code, not reconstructed candidate DDL.
        await database.create_all()
        await check_namespace()
    else:
        result = json.loads(sys.argv[2])
        # A rolled-back old binary may execute its ordinary bootstrap too.
        await database.create_all()
        await check_namespace()
        async with database.async_session_factory.begin() as db:
            user = await db.get(User, uuid.UUID(result["user"]))
            for model, key in ((Company,"company"), (Organization,"organization"),
                    (Counterparty,"counterparty"), (Contract,"contract"),
                    (EzsEquipmentUnit,"equipment"), (DocCard,"document"),
                    (App,"app"), (CompanyApp,"company_app")):
                assert await db.get(model, uuid.UUID(result[key])) is not None
            location = await db.get(ServiceLocation, result["object"])
            assert location.company_id == uuid.UUID(result["company"])
            location.name = "Written by old Core ORM"
            contract = await db.get(Contract, uuid.UUID(result["contract"]))
            contract.title = "Written by old Core ORM"
            document = await db.get(DocCard, uuid.UUID(result["document"]))
            document.title = "Written by old Core ORM"
            native_app = await db.get(App, uuid.UUID(result["app"]))
            native_app.description = "Written by old Core ORM"
            bearer = token_for(user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                headers={"Authorization": "Bearer " + bearer}) as client:
            response = await client.get("/api/auth/me")
            assert response.status_code == 200, response.text
            assert response.json()["email"] == "schema-test@example.invalid"
            response = await client.get("/api/references/counterparties", params={"company_id": result["company"]})
            assert response.status_code == 200, response.text
            assert any(v["id"] == result["counterparty"] for v in response.json())
            response = await client.patch("/api/references/counterparties/" + result["counterparty"],
                json={"name": "Synthetic counterparty written by old HTTP"})
            assert response.status_code == 200, response.text
            response = await client.post("/api/references/counterparties", json={
                "company_id": result["company"], "name": "Synthetic new counterparty from old HTTP"})
            assert response.status_code == 201, response.text
            result["created_counterparty"] = response.json()["id"]
    await database.engine.dispose()
    print("PARTNER_SCHEMA_RESULT=" + json.dumps(result, sort_keys=True))

asyncio.run(main())
'''


async def run_old_server(tmp_path: Path, revision: str, mode: str, state=None, profile="public") -> dict:
    """Export and execute immutable source; never copy any current .env file."""
    source = tmp_path / revision
    server = source / "clearledger" / "server"
    if not server.exists():
        archive = subprocess.run(["git", "archive", revision, "clearledger/server"], cwd=GIT_REPO,
            check=True, capture_output=True).stdout
        source.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as data:
            data.extractall(source, filter="data")
    assert not (server / ".env").exists()
    script = source / "schema_probe.py"
    script.write_text(OLD_SERVER_SCRIPT, encoding="utf-8")
    assert partner_test_safety_error(os.environ, flag=SCHEMA_FLAG) is None
    env = {
        "PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "PYTHONPATH": str(server),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
        "DATABASE_URL": os.environ["TEST_DATABASE_URL"], "TEST_DATABASE_URL": os.environ["TEST_DATABASE_URL"],
        "RUN_PARTNER_IDENTITY_TESTS": "1", "UPLOAD_DIR": os.environ["UPLOAD_DIR"],
        "SECRET_KEY": "synthetic-partner-schema-test-secret-only",
        "APP_ENV": "test", "ECOSYSTEM_COMPANIES": "", "PARTNER_OAUTH_ENABLED": "false", "PARTNER_API_ENABLED": "false",
        "PARTNER_SCHEMA_TEST_PROFILE": profile,
    }
    if "CI" in os.environ:
        env["CI"] = os.environ["CI"]
    process = await asyncio.create_subprocess_exec(sys.executable, str(script), mode,
        *([json.dumps(state)] if state else []), cwd=server, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        output, errors = await asyncio.wait_for(process.communicate(), timeout=180)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        raise
    assert process.returncode == 0, (revision, mode, errors.decode()[-8000:], output.decode()[-3000:])
    results = [line.removeprefix("PARTNER_SCHEMA_RESULT=") for line in output.decode().splitlines()
               if line.startswith("PARTNER_SCHEMA_RESULT=")]
    assert len(results) == 1
    return json.loads(results[0])


class SchemaDatabase:
    def __init__(self, profile):
        self.profile = profile
        self.namespace = profile
        url = os.environ["TEST_DATABASE_URL"]
        # Control operations are explicit schema SQL, outside ORM observers.
        self.control = create_async_engine(url, connect_args={"server_settings": {"search_path": "pg_catalog"}})
        self.engine = create_async_engine(url, pool_size=5, max_overflow=5)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.role_clause = None
        self.prior_path = None
        self.prepared = False
        self.path_changed = False
        self.sentinel = None
        if profile == "core":
            event.listen(self.engine.sync_engine, "before_cursor_execute", forbid_support_rows)

    def __iter__(self):
        yield self.engine
        yield self.factory

    async def initialize(self):
        assert partner_test_safety_error(os.environ, flag=SCHEMA_FLAG) is None
        async with self.control.begin() as conn:
            actual, role = (await conn.execute(text("SELECT current_database(), current_user"))).one()
            from sqlalchemy.engine import make_url
            assert actual == make_url(os.environ["TEST_DATABASE_URL"]).database
            quote = conn.dialect.identifier_preparer.quote_identifier
            # Never ALTER ROLE globally or ALTER a different database.
            self.role_clause = f"ALTER ROLE {quote(role)} IN DATABASE {quote(actual)}"
            self.prior_path = await conn.scalar(text("""SELECT substring(setting FROM 13)
                FROM pg_db_role_setting s JOIN pg_database d ON d.oid=s.setdatabase
                JOIN pg_roles r ON r.oid=s.setrole CROSS JOIN LATERAL unnest(s.setconfig) setting
                WHERE d.datname=current_database() AND r.rolname=current_user
                AND setting LIKE 'search_path=%'"""))
        self.prepared = True
        await self.reset()
        await self.set_path(self.namespace)

    async def reset(self):
        assert partner_test_safety_error(os.environ, flag=SCHEMA_FLAG) is None
        await self.engine.dispose()
        # A schema-wide CASCADE holds every table/index/FK lock until commit.
        # Bound our cleanup footprint when other isolated jobs share Postgres;
        # changing global max_locks_per_transaction is outside this fixture.
        async with self.control.connect() as conn:
            tables = (await conn.execute(text("""SELECT n.nspname,c.relname
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname IN ('core','public','edge') AND c.relkind IN ('r','p')
                ORDER BY n.nspname,c.relname"""))).all()
            quote = conn.dialect.identifier_preparer.quote_identifier
        for offset in range(0, len(tables), 8):
            names = ", ".join(f"{quote(schema)}.{quote(table)}"
                              for schema, table in tables[offset:offset + 8])
            async with self.control.begin() as conn:
                await conn.execute(text(f"DROP TABLE IF EXISTS {names} CASCADE"))
        for schema in ("edge", "core", "public"):
            async with self.control.begin() as conn:
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        for schema in ("public", "core", "edge"):
            async with self.control.begin() as conn:
                await conn.execute(text(f"CREATE SCHEMA {schema}"))

    async def set_path(self, path):
        assert path in {"public", "core", "core, public"}
        async with self.control.begin() as conn:
            await conn.execute(text(f"{self.role_clause} SET search_path TO {path}"))
        self.path_changed = True
        await self.engine.dispose()  # New pool connections get DB-local role defaults.

    async def check_resolution(self):
        async with self.engine.connect() as conn:
            assert await conn.scalar(text("SELECT current_schema()")) == self.namespace
            for name in ("users", "companies"):
                schema = await conn.scalar(text("SELECT n.nspname FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE c.oid=to_regclass(:name)"), {"name": name})
                assert schema == self.namespace

    async def finish_provisioning(self, state=None):
        if self.profile != "core":
            return
        ids = state or {"user": str(uuid.uuid4()), "company": str(uuid.uuid4())}
        async with self.control.begin() as conn:
            await conn.execute(text("CREATE TABLE public.users (id uuid PRIMARY KEY, email text NOT NULL, name text NOT NULL)"))
            await conn.execute(text("CREATE TABLE public.companies (id uuid PRIMARY KEY, name text NOT NULL)"))
            await conn.execute(text("INSERT INTO public.users VALUES (:id, 'support-sentinel@example.invalid', 'Support sentinel user')"),
                {"id": uuid.UUID(ids["user"])})
            await conn.execute(text("INSERT INTO public.companies VALUES (:id, 'Support sentinel company')"),
                {"id": uuid.UUID(ids["company"])})
        self.sentinel = await self.sentinel_rows()
        await self.set_path("core, public")
        await self.check_resolution()

    async def sentinel_rows(self):
        async with self.control.connect() as conn:
            return {name: (await conn.execute(text(f"SELECT * FROM public.{name} ORDER BY id"))).all()
                    for name in ("users", "companies")}

    async def assert_sentinels(self):
        if self.profile == "core":
            assert await self.sentinel_rows() == self.sentinel

    async def close(self):
        try:
            if self.prepared:
                await self.reset()
        finally:
            if self.path_changed:
                async with self.control.begin() as conn:
                    if self.prior_path is None:
                        await conn.execute(text(f"{self.role_clause} RESET search_path"))
                    else:
                        value = literal(self.prior_path).compile(dialect=conn.dialect, compile_kwargs={"literal_binds": True})
                        await conn.execute(text(f"{self.role_clause} SET search_path TO {value}"))
                async with self.control.connect() as conn:
                    restored = await conn.scalar(text("""SELECT substring(setting FROM 13)
                        FROM pg_db_role_setting s JOIN pg_database d ON d.oid=s.setdatabase
                        JOIN pg_roles r ON r.oid=s.setrole CROSS JOIN LATERAL unnest(s.setconfig) setting
                        WHERE d.datname=current_database() AND r.rolname=current_user
                        AND setting LIKE 'search_path=%'"""))
                    assert restored == self.prior_path
            await self.engine.dispose()
            await self.control.dispose()


@pytest_asyncio.fixture(params=PROFILES, loop_scope="session")
async def schema_db(monkeypatch, request):
    # Refuse to reset a DB that another selected HTTP suite has seeded through
    # session-scoped conftest fixtures; a separate flag alone is insufficient.
    foreign_db_items = [item.nodeid for item in request.session.items
                       if Path(item.path) != Path(__file__) and "setup_database" in item.fixturenames]
    if foreign_db_items:
        pytest.fail("Run schema compatibility in a separate pytest process from HTTP DB suites")
    target = SchemaDatabase(request.param)
    try:
        await target.initialize()
        monkeypatch.setattr(database, "engine", target.engine)
        monkeypatch.setattr(database, "async_session_factory", target.factory)
        async def isolated_db():
            async with target.factory() as session:
                try:
                    yield session
                    await session.commit()
                except BaseException:
                    await session.rollback()
                    raise
        monkeypatch.setitem(app.dependency_overrides, get_db, isolated_db)
        yield target
    finally:
        from tests.helpers import drain_application_tasks
        await drain_application_tasks()
        await target.close()


async def schema_catalog(engine) -> dict:
    """Semantic definitions, excluding OIDs which change on idempotent bootstrap."""
    statements = {
        "tables": """SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('core','public','edge') AND c.relkind IN ('r','p') ORDER BY 1,2""",
        "columns": """SELECT n.nspname,c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),
            a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid)
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            WHERE n.nspname IN ('core','public','edge') AND c.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1,2,3""",
        "constraints": """SELECT n.nspname,c.relname,k.conname,k.contype,k.convalidated,pg_get_constraintdef(k.oid,true)
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('core','public','edge') ORDER BY 1,2,3""",
        "indexes": """SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes
            WHERE schemaname IN ('core','public','edge') ORDER BY 1,2,3""",
        "triggers": """SELECT n.nspname,c.relname,t.tgname,pg_get_triggerdef(t.oid,true)
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('core','public','edge') AND NOT t.tgisinternal ORDER BY 1,2,3""",
    }
    async with engine.connect() as conn:
        return {name: [tuple(row) for row in (await conn.execute(text(sql))).all()]
                for name, sql in statements.items()}


def assert_additive(before, after, namespace="public"):
    old_tables = set(before["tables"])
    allowed = set().union(*CANDIDATE_MODEL_TABLES.values())
    assert set(after["tables"]) - old_tables == {(namespace, table) for table in allowed}
    assert old_tables <= set(after["tables"])
    for key in ("columns", "constraints", "indexes", "triggers"):
        assert [row for row in after[key] if row[:2] in old_tables] == before[key], key


async def assert_partner_catalog(engine, namespace="public"):
    tables = set()
    for module, expected in CANDIDATE_MODEL_TABLES.items():
        declared = {mapper.local_table for mapper in Base.registry.mappers if mapper.class_.__module__ == module}
        assert {table.name for table in declared} == expected, module
        tables.update(declared)
    def check(conn):
        inspector = inspect(conn)
        for table in tables:
            columns = {c["name"]: c for c in inspector.get_columns(table.name, schema=namespace)}
            assert set(columns) == set(table.columns.keys())
            for column in table.columns:
                actual = columns[column.name]
                assert str(actual["type"].compile(dialect=conn.dialect)) == str(column.type.compile(dialect=conn.dialect))
                assert actual["nullable"] == column.nullable
                expected_default = str(column.server_default.arg) if column.server_default is not None else None
                assert actual["default"] == expected_default, (table.name, column.name)
            expected_fk = {(tuple(e.parent.name for e in fk.elements), fk.referred_table.schema or namespace, fk.referred_table.name,
                tuple(e.column.name for e in fk.elements), fk.ondelete or "NO ACTION") for fk in table.foreign_key_constraints}
            actual_fk = {(tuple(fk["constrained_columns"]), fk["referred_schema"] or namespace, fk["referred_table"], tuple(fk["referred_columns"]),
                fk.get("options", {}).get("ondelete", "NO ACTION")) for fk in inspector.get_foreign_keys(table.name,
                    schema=namespace, postgresql_ignore_search_path=True)}
            assert actual_fk == expected_fk, table.name
            assert inspector.get_pk_constraint(table.name, schema=namespace)["constrained_columns"] == [c.name for c in table.primary_key.columns]
            assert {tuple(v["column_names"]) for v in inspector.get_unique_constraints(table.name, schema=namespace)} == {
                tuple(c.name for c in constraint.columns) for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)}, table.name
            assert {v["name"] for v in inspector.get_check_constraints(table.name, schema=namespace)} == {
                c.name for c in table.constraints if isinstance(c, CheckConstraint)}
            actual_indexes = {i["name"]: (tuple(i["column_names"]), bool(i["unique"]))
                              for i in inspector.get_indexes(table.name, schema=namespace)
                              if not i.get("duplicates_constraint")}
            expected_indexes = {i.name: (tuple(c.name for c in i.expressions), bool(i.unique))
                                for i in table.indexes}
            assert actual_indexes == expected_indexes, table.name
            locations = conn.execute(text("SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE c.relname=:name AND c.relkind IN ('r','p') AND n.nspname IN ('core','public','edge')"),
                {"name": table.name}).scalars().all()
            assert locations == [namespace], (table.name, locations)
        invalid = conn.execute(text("""SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema
            AND c.relname=ANY(:names) AND (NOT i.indisvalid OR NOT i.indisready)"""),
            {"names": [t.name for t in tables], "schema": namespace}).all()
        assert not invalid
        unvalidated = conn.execute(text("""SELECT c.relname,k.conname FROM pg_constraint k
            JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=:schema AND c.relname=ANY(:names) AND NOT k.convalidated"""),
            {"names": [t.name for t in tables], "schema": namespace}).all()
        assert not unvalidated
    async with engine.connect() as conn:
        await conn.run_sync(check)


async def assert_registration_consistency(factory, state, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    for field, value in {"partner_oauth_enabled": True, "partner_oauth_issuer": "https://schema-test.example",
            "partner_oauth_audience": "urn:partner:schema:test", "partner_oauth_signing_key": base64.b64encode(key).decode()}.items():
        monkeypatch.setattr(partner_identity.settings, field, value)
    async with factory() as db:
        user = await db.get(User, uuid.UUID(state["user"]))
        assert user.email == "schema-test@example.invalid" and user.name == "Synthetic schema admin"
        headers = {"Authorization": "Bearer " + token_for(user)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as client:
        response = await client.post("/api/developer/clients", json={"companyId": state["company"],
            "name": "Synthetic schema partner", "redirectUris": ["https://schema-client.example/callback"],
            "scopes": ["openid", "docs:read"]})
        assert response.status_code == 201, response.text
        client_id, app_id = response.json()["clientId"], response.json()["appId"]
        assert response.json()["enabled"] is False
        assert (await client.post(f"/api/developer/clients/{client_id}/status", json={"enabled": True})).status_code == 200
        resources = {kind: {"mode": "SET", "ids": [state[field]]} for kind, field in {
            "objects": "object", "equipment": "equipment", "counterparties": "counterparty",
            "contracts": "contract", "documents": "document"}.items()}
        response = await client.post(f"/api/developer/clients/{client_id}/installations", json={
            "companyId": state["company"], "scopes": ["openid", "docs:read"], "locationIds": None, "resourceScopes": resources})
        assert response.status_code == 201, response.text
        installation_id = uuid.UUID(response.json()["installationId"])
    async with factory() as db:
        installed = await db.get(PartnerInstallation, installation_id)
        company_app = await db.get(CompanyApp, installation_id)
        registered = await db.get(PartnerClient, client_id)
        assert installed.company_id == company_app.company_id == uuid.UUID(state["company"])
        assert company_app.app_id == registered.app_id == uuid.UUID(app_id)
        assert installed.client_id == registered.id
        assert len((await db.scalars(select(PartnerResourceScope).where(
            PartnerResourceScope.installation_id == installation_id))).all()) == 5
        assert await db.scalar(select(PartnerGrant.id)) is None  # Installation does not silently consent.
        native = await db.get(CompanyApp, uuid.UUID(state["company_app"]))
        assert native.enabled and native.app_id == uuid.UUID(state["app"])
    return client_id, installation_id


async def test_fresh_and_repeat_bootstrap(schema_db, record_property):
    engine, _ = schema_db
    assert not (await schema_catalog(engine))["tables"]
    await database.create_all()
    first = await schema_catalog(engine)
    await schema_db.check_resolution()
    record_property("profile", schema_db.profile)
    record_property("fresh_tables", len(first["tables"]))
    await assert_partner_catalog(engine, schema_db.namespace)
    await database.create_all()
    assert await schema_catalog(engine) == first
    if schema_db.profile == "core":
        await schema_db.finish_provisioning()
        with_support = await schema_catalog(engine)
        await database.create_all()
        assert await schema_catalog(engine) == with_support
        await assert_partner_catalog(engine, schema_db.namespace)
        await schema_db.assert_sentinels()


@pytest.mark.parametrize("revision", OLD_REVISIONS)
async def test_old_core_upgrade_repeat_and_old_code_coexistence(schema_db, tmp_path, monkeypatch, revision, record_property):
    engine, factory = schema_db
    state = await run_old_server(tmp_path, revision, "bootstrap", profile=schema_db.profile)
    await schema_db.check_resolution()
    await schema_db.finish_provisioning(state)
    old = await schema_catalog(engine)
    record_property("profile", schema_db.profile)
    record_property("baseline_revision", subprocess.run(["git", "rev-parse", revision], cwd=GIT_REPO,
        capture_output=True, text=True, check=True).stdout.strip())
    record_property("baseline_tables", len(old["tables"]))
    assert not {table for _, table in old["tables"]} & PARTNER_TABLES
    await database.create_all()
    upgraded = await schema_catalog(engine)
    assert_additive(old, upgraded, schema_db.namespace)
    record_property("additive_tables", len(set().union(*CANDIDATE_MODEL_TABLES.values())))
    await assert_partner_catalog(engine, schema_db.namespace)
    await database.create_all()
    assert await schema_catalog(engine) == upgraded
    client_id, installation_id = await assert_registration_consistency(factory, state, monkeypatch)
    await schema_db.assert_sentinels()
    result = await run_old_server(tmp_path, revision, "roundtrip", state, profile=schema_db.profile)
    assert await schema_catalog(engine) == upgraded
    await schema_db.check_resolution()
    await schema_db.assert_sentinels()
    async with factory() as db:
        assert (await db.get(Counterparty, uuid.UUID(state["counterparty"]))).name.endswith("written by old HTTP")
        assert (await db.get(Counterparty, uuid.UUID(result["created_counterparty"]))).company_id == uuid.UUID(state["company"])
        assert (await db.get(Contract, uuid.UUID(state["contract"]))).title == "Written by old Core ORM"
        assert (await db.get(ServiceLocation, state["object"])).name == "Written by old Core ORM"
        assert (await db.get(DocCard, uuid.UUID(state["document"]))).title == "Written by old Core ORM"
        assert (await db.get(App, uuid.UUID(state["app"]))).description == "Written by old Core ORM"
        assert (await db.get(PartnerClient, client_id)).enabled
        assert (await db.get(PartnerInstallation, installation_id)).approved


@pytest.mark.parametrize("url,ci,allowed", [
    ("postgresql+asyncpg://u:p@127.0.0.1:55432/partner_ci_test", "", True),
    ("postgresql+asyncpg://u:p@localhost/partner_ci_test", "", True),
    ("postgresql+asyncpg://u:p@[::1]:5432/partner_ci_test", "", True),
    ("postgresql+asyncpg://u:p@postgres/partner_ci_test", "true", True),
    ("postgresql+asyncpg://u:p@postgres-16/partner_ci_test", "1", True),
    ("postgresql+asyncpg://u:p@postgres/partner_ci_test", "", False),
    ("postgresql+asyncpg://u:p@postgres/partner_ci_test", "false", False),
    ("postgresql+asyncpg://u:p@db.example.com/partner_ci_test", "true", False),
    ("postgresql+asyncpg://u:p@10.10.70.53/partner_ci_test", "true", False),
    ("postgresql+asyncpg://u:p@127.0.0.1/elsyplus", "", False),
    ("postgresql+asyncpg://u:p@127.0.0.1/contest", "", False),
    ("postgresql+asyncpg://u:p@127.0.0.1/partner_ci_test?host=prod", "", False),
    ("postgresql+asyncpg://u:p@127.0.0.1/partner_ci_test#fragment", "", False),
    ("postgresql+asyncpg://u:p@127.0.0.1:bad/partner_ci_test", "", False),
    ("postgresql+asyncpg://u:p@127.0.0.1:0/partner_ci_test", "", False),
    ("postgresql+asyncpg://@127.0.0.1/partner_ci_test", "", False),
    ("postgresql://u:p@127.0.0.1/partner_ci_test", "", False),
    ("sqlite:///partner_ci_test", "", False),
    ("", "", False),
])
async def test_portable_database_safety_guard(url, ci, allowed):
    env = {"RUN_PARTNER_IDENTITY_TESTS": "1", "TEST_DATABASE_URL": url,
        "CI": ci, "UPLOAD_DIR": "/tmp/partner-ci-test-uploads"}
    assert (partner_test_safety_error(env) is None) is allowed


async def test_no_default_database_or_upload_fallback():
    env = {"RUN_PARTNER_IDENTITY_TESTS": "1", "DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1/partner_ci_test",
           "UPLOAD_DIR": "/tmp/partner-ci-test-uploads"}
    assert partner_test_safety_error(env) is not None
    env["TEST_DATABASE_URL"] = env.pop("DATABASE_URL")
    for upload in ("", "relative-test-uploads", "/", "/srv/shared-uploads"):
        assert partner_test_safety_error({**env, "UPLOAD_DIR": upload}) is not None
    assert partner_test_safety_error({**env, "RUN_PARTNER_IDENTITY_TESTS": "0"}) is not None
    product = {**env, "RUN_PARTNER_IDENTITY_TESTS": "0", "RUN_PRODUCT_API_TESTS": "1"}
    assert partner_test_safety_error(product, flag="RUN_PRODUCT_API_TESTS") is None
    assert partner_test_safety_error(product) is not None


@pytest.mark.parametrize("opt_in,expected_code,expected_message", [
    ("0", 5, "1 skipped"),
    ("1", 2, "Refusing partner test database"),
])
async def test_real_pytest_guard_stops_before_database_fixture(opt_in, expected_code, expected_message):
    # Deliberately unreachable loopback port and a prohibited DB name. Never
    # point a negative guard probe at a real/customer database to test safety.
    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8",
        "SECRET_KEY": "synthetic-test-only", "RUN_PARTNER_IDENTITY_TESTS": opt_in,
        "TEST_DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/elsyplus",
        "UPLOAD_DIR": "/tmp/partner-guard-test-uploads", "PYTHONDONTWRITEBYTECODE": "1"}
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "pytest",
        "tests/test_partner_identity.py", "-q", cwd=REPO / "clearledger" / "server", env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        raise
    assert process.returncode == expected_code, output.decode()
    assert expected_message in output.decode(), output.decode()
    assert "ConnectionRefusedError" not in output.decode()


async def test_mixed_http_session_fixture_is_refused_before_schema_reset():
    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "SECRET_KEY": "synthetic-test-only",
        "RUN_PARTNER_SCHEMA_TESTS": "1", "PARTNER_SCHEMA_PROFILE": "core",
        "TEST_DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/synthetic_test",
        "UPLOAD_DIR": "/tmp/partner-mixed-test-uploads", "PYTHONDONTWRITEBYTECODE": "1"}
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "pytest",
        "tests/test_partner_schema_compatibility.py::test_fresh_and_repeat_bootstrap",
        "tests/test_auth.py::test_login_success", "-x", "-q", cwd=REPO / "clearledger" / "server", env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        raise
    assert process.returncode == 1, output.decode()
    assert "Run schema compatibility in a separate pytest process" in output.decode()
    assert "ConnectionRefusedError" not in output.decode()


async def test_extension_manifest_is_exact_and_required_portal_cannot_be_omitted():
    registered = {key: set(value) for key, value in BUDGET_MODEL_TABLES.items()}
    with pytest.raises(ValueError, match="Required budget model"):
        candidate_model_manifest({})
    assert candidate_model_manifest(registered) == OWNED_MODEL_TABLES
    with pytest.raises(ValueError, match="Required portal model"):
        candidate_model_manifest(registered, require_portal=True)
    declared = candidate_model_manifest({**registered, "app.models_docs_portal": {"partner_docs_sessions"}}, require_portal=True)
    assert set().union(*declared.values()) == PARTNER_TABLES | {"partner_docs_sessions", "product_api_budgets"}
    with pytest.raises(ValueError, match="Unexpected table"):
        candidate_model_manifest({**registered, "app.models_docs_portal": {"partner_docs_sessions", "unreviewed_table"}})
    with pytest.raises(ValueError, match="Required budget model"):
        candidate_model_manifest({"app.models_product_budget": {"product_api_budgets", "unreviewed_table"}})


async def test_real_required_portal_gate_matches_registered_candidate():
    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "SECRET_KEY": "synthetic-test-only",
        "RUN_PARTNER_SCHEMA_TESTS": "1", "PARTNER_SCHEMA_REQUIRE_PORTAL": "1",
        "TEST_DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/synthetic_test",
        "UPLOAD_DIR": "/tmp/partner-portal-gate-test-uploads", "PYTHONDONTWRITEBYTECODE": "1"}
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "pytest",
        "tests/test_partner_schema_compatibility.py", "--collect-only", "-q",
        cwd=REPO / "clearledger" / "server", env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        raise
    present = "app.models_docs_portal" in CANDIDATE_MODEL_TABLES
    assert process.returncode == (0 if present else 2), output.decode()
    if not present:
        assert "Required portal model app.models_docs_portal.DocsPortalSession is not registered" in output.decode()
    assert "ConnectionRefusedError" not in output.decode()
