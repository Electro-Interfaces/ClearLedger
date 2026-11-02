"""ROOT-only actual PG cases; no application/driver imports before approval.

Setup writes use one disposable owned database. Observation scopes around the
read gate are separate from setup/caller writes and include raw asyncpg queries.
The immutable old gate fixture is characterized with the current strict default
framework; this is not a rerun of the whole historical application binary.
"""
import asyncio
from contextlib import asynccontextmanager
import contextvars
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import uuid


FIELDS = ("revision", "ordinal", "parent_revision", "artifact_sha256", "contract_sha256",
          "predecessor_sha256", "runner_format", "app_commit", "applied_by", "action")
PREFIX_IDS = ("P1-created-no-successor-prerequisites", "P1-adopted",
              "P2-created-no-pulse-prerequisites", "P2-adopted", "P3-created", "P3-adopted")
HISTORY_IDS = ("H-empty", "H-missing-journal", "H-gap-1", "H-gap-2", "H-unknown-row",
               "H-future-row", "H-extra-over-bound", "H-duplicate-or-reordered", "H-required-absent")
CATALOG_IDS = ("C-budget-column", "C-budget-fk-trigger", "C-journal-shape", "C-parent-ownership",
               "C-calendar-managed-column", "C-calendar-managed-check", "C-calendar-owner",
               "C-pulse-shape", "C-pulse-fk", "C-pulse-trigger-acl", "C-public-sentinel")
CONNECTION_IDS = ("T-borrowed-lazy-TX", "T-borrowed-readwrite-continuation",
                  "T-borrowed-readonly-enforcement", "T-borrowed-isolation-path-options",
                  "T-owned-RR-readonly", "T-actual-public-refusal", "T-actual-identity-refusal",
                  "T-no-writes-locks-options-extra-connect", "T-safe-error-redaction", "T-gate-repeat-invariance",
                  "T-cold-jit-on", "T-cold-jit-off")
OLD_IDS = ("OLD-immutable-harness-closure-preserved", "OLD-gate-P2-refusal",
           "OLD-explicit-default-runner-P2-refusal")
CASE_IDS = (PREFIX_IDS + HISTORY_IDS + tuple("H" + str(n) + "-" + field for n in (1, 2, 3) for field in FIELDS)
            + CATALOG_IDS + CONNECTION_IDS + OLD_IDS)
COMPANY = uuid.UUID("c3000000-0000-4000-8000-000000000001")
APP = uuid.UUID("c3000000-0000-4000-8000-000000000002")
INSTALL = uuid.UUID("c3000000-0000-4000-8000-000000000003")
ROLE = uuid.UUID("c3000000-0000-4000-8000-000000000010")
VIEW = uuid.UUID("c3000000-0000-4000-8000-000000000011")
OLD_GATE_SHA = "6e51660673e40188705e243c34de61c2e7b1f2cf9c93811bea476839460ba7e4"
OLD_HARNESS_SHA = "188a4b52a3baa47db6a405a7bc854539b8a893ece334909fd5cb8532e04fd447"
OLD_APPROVAL_SHA = "9ddb84c05921ceee195590f97ae1093888c2d265a6f86811c751d325c1fa886f"
KEYWORD_ENUM = frozenset(("select", "show", "begin", "start", "commit", "rollback", "with", "set",
                          "insert", "update", "delete", "create", "alter", "drop", "truncate", "do", "grant", "revoke"))
DRIVER_PROTOCOL = {
    "5a24207b94a0f3a752fab41284a1ebd49873d5b0986320b49c11a285fd897bdb": "off",
    "628039f6ba4473bab8d8bcd8736c285e22d8e3359cc652577840549bafb067f7": "types",
    "ca2d0b7ded10c57e11b08283ba9d03ee4b9088b0d2e749746985b1d58292cfe1": "restore",
}
LEGACY_MODEL_SHA = "f066910e5bf5e2e37346edc8c78693d3673868186c925e1aad67f1d816f2104e"


async def run(settings, progress):
    from tests.schema_gate_history_compatibility_approved import require_running_approval, running_counters
    require_running_approval()
    import asyncpg
    from sqlalchemy import event, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from app import database
    from app.models import App, Company, CompanyApp, CompanyRole, PulseView, PulseViewRoleGrant
    from app.models_partner import PartnerClient, PartnerInstallation
    from app.models_product_budget import ProductAPIBudget
    from app.services import schema_version_gate as gate
    from schema_migrations import journal, manifest, runner
    from schema_migrations.errors import MigrationError
    from tests.pulse_view_role_schema_support import prepare_parents

    assert "app.main" not in sys.modules
    config = gate._config(settings)
    head = manifest.load_known_head()
    completed, details = [], {}
    phase = contextvars.ContextVar("schema_gate_query_phase", default=None)
    observations = []
    observation_errors = []
    observation_counts = {"raw": 0, "sqlalchemy": 0}
    probe_receipts = []
    legacy_fixture_receipts = []
    owned_pairs = []
    checkouts = []
    engines = []

    def record(case_id, **detail):
        assert case_id in CASE_IDS and case_id not in completed
        completed.append(case_id)
        details[case_id] = detail
        progress(case_id, detail)

    def capture(statement, source, pid):
        scope = phase.get()
        if scope is None:
            return
        sql = " ".join(statement.lower().split())
        keyword = sql.split(" ", 1)[0].rstrip(";")
        keyword = keyword if keyword in KEYWORD_ENUM else "other"
        normalized_sha = hashlib.sha256(statement.strip().encode("utf-8")).hexdigest()
        if len(observations) >= 6000:
            if not observation_errors:
                observation_errors.append("query observation bound exceeded")
            return
        observation_counts[source] += 1
        observations.append((scope, pid, source, keyword, any(word in sql for word in (
            "pg_advisory_", "pg_try_advisory_", "set_config(")), normalized_sha))

    def engine_for(path="core, public", *, jit=None):
        settings_for_connection = {"search_path": path}
        if jit is not None:
            assert jit in {"on", "off"}
            settings_for_connection["jit"] = jit  # Only two new fresh synthetic engines.
        engine = create_async_engine(settings.database_url, pool_size=2, max_overflow=0,
            connect_args={"server_settings": settings_for_connection})
        engines.append(engine)

        def connected(adapted, record):
            pid = adapted.driver_connection.get_server_pid()
            adapted.driver_connection.add_query_logger(lambda query: capture(query.query, "raw", pid))

        def checkout(*args):
            if phase.get() is not None:
                checkouts.append(phase.get())

        def prepared_statement(conn, cursor, statement, parameters, context, many):
            # SQLAlchemy uses PreparedStatement.fetch directly; asyncpg's
            # Connection query logger does not cover this protocol path.
            capture(statement, "sqlalchemy", conn.connection.driver_connection.get_server_pid())

        event.listen(engine.sync_engine, "connect", connected)
        event.listen(engine.sync_engine, "checkout", checkout)
        event.listen(engine.sync_engine, "before_cursor_execute", prepared_statement)
        return engine

    async def scalar_probe(driver):
        # Builtin int/text only. A raw autocommit scalar cannot start the lazy
        # SQLAlchemy caller transaction or warm metadata array codecs.
        token = phase.set(None)
        try:
            active = driver.is_in_transaction()
            row = await driver.fetchrow("""SELECT pg_catalog.pg_backend_pid() AS pid,
                pg_catalog.current_setting('jit') AS jit,
                pg_catalog.current_setting('search_path') AS path,
                pg_catalog.current_setting('transaction_read_only') AS read_only,
                pg_catalog.current_setting('transaction_isolation') AS isolation""")
            assert driver.is_in_transaction() == active, "test scalar changed actual transaction state"
            assert row["pid"] == driver.get_server_pid()
            await asyncio.sleep(0)
            return {**dict(row), "in_transaction": active}
        finally:
            phase.reset(token)

    class ProbedEngine:
        """Delegate to the real engine and yield the SAME actual connection."""
        def __init__(self, real):
            self.real = real

        @asynccontextmanager
        async def connect(self):
            async with self.real.connect() as connection:
                driver = (await connection.get_raw_connection()).driver_connection
                before = await scalar_probe(driver)
                options_before = copy.deepcopy(dict(connection.sync_connection.get_execution_options()))
                try:
                    yield connection
                finally:
                    # Gate's owned transaction has exited; pool reset/close has
                    # NOT happened, so reset cannot mask a leaked JIT setting.
                    after = await scalar_probe(driver)
                    options_after = copy.deepcopy(dict(connection.sync_connection.get_execution_options()))
                    owned_pairs.append((before, after, options_before, options_after))

    engine = engine_for()
    control = await asyncpg.connect(config.dsn, timeout=5, command_timeout=20,
        server_settings={"search_path": "pg_catalog", "statement_timeout": "20000", "lock_timeout": "2000"})
    owned_core = False

    async def execute(sql, *args):
        return await control.execute(sql, *args)

    async def seed_budget():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all([Company(id=COMPANY, name="C3 synthetic", slug="schema-gate-c3", profile_id="energy"),
                             App(id=APP, code="schema-gate-c3", name="C3 synthetic", kind="partner", is_active=True)])
            await session.flush()
            session.add_all([PartnerClient(id="schema-gate-c3", app_id=APP, owner_company_id=COMPANY,
                                redirect_uris=["https://example.invalid/callback"], allowed_scopes=[],
                                auth_method="client_secret_basic", enabled=True),
                             CompanyApp(id=INSTALL, company_id=COMPANY, app_id=APP, enabled=True)])
            await session.flush()
            session.add(PartnerInstallation(id=INSTALL, company_id=COMPANY, client_id="schema-gate-c3",
                        approved=True, scopes=[], all_locations=True))
            await session.commit()
        await execute("INSERT INTO core.product_api_budgets VALUES ($1,$2,$3,1,'2026-10-31T12:00:00+00',10,60)",
                      COMPANY, INSTALL, "schema-gate-c3")

    def current_orm_identity():
        return [(name, id(table), tuple((c.name, id(c)) for c in table.columns),
                 tuple(sorted(id(c) for c in table.constraints)), tuple(sorted(id(i) for i in table.indexes)))
                for name, table in database.Base.metadata.tables.items()]

    def legacy_calendar_table():
        # Same reviewed source-exec/OnlyBase semantics as immutable M09
        # calendar_protocol_cases.model_source; no env path or real Base mutation.
        from sqlalchemy.orm import DeclarativeBase
        path = Path(__file__).with_name("schema_gate_history_legacy_models_20261031.py")
        raw = path.read_bytes()
        assert len(raw) == 965484 and hashlib.sha256(raw).hexdigest() == LEGACY_MODEL_SHA
        class OnlyBase(DeclarativeBase):
            pass
        adapter = ModuleType("app.database")
        adapter.Base = OnlyBase
        previous = sys.modules.get("app.database")
        name = "_schema_gate_history_m09_legacy_models"
        module = ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        sys.modules["app.database"] = adapter
        try:
            exec(compile(raw, str(path), "exec"), module.__dict__)
        finally:
            if previous is None:
                sys.modules.pop("app.database", None)
            else:
                sys.modules["app.database"] = previous
        assert sys.modules.get("app.database") is previous
        return module.CalendarEvent.__table__

    async def protected_calendar_neighbors():
        # Calendar's own table/index/rowtype and its three RI-trigger sets are
        # replaced by this EMPTY fixture. Preserve every other semantic catalog
        # row, not merely relation counts. No volatile planner/freeze statistics.
        rows = await control.fetch("""WITH target AS (
            SELECT 'core.calendar_events'::regclass::oid AS oid), owned AS (
            SELECT oid FROM target UNION SELECT indexrelid FROM pg_index WHERE indrelid=(SELECT oid FROM target)),
            relations AS (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname IN ('core','public') AND c.oid NOT IN (SELECT oid FROM owned)),
            calendar_fks AS (SELECT oid FROM pg_constraint WHERE conrelid=(SELECT oid FROM target) AND contype='f'),
            items AS (
            SELECT 'namespace' AS kind,n.oid::text AS key,to_jsonb(n) AS value FROM pg_namespace n WHERE n.nspname IN ('core','public')
            UNION ALL SELECT 'class',c.oid::text,to_jsonb(c)-ARRAY['relpages','reltuples','relallvisible','relallfrozen','relfrozenxid','relminmxid']
                FROM pg_class c WHERE c.oid IN (SELECT oid FROM relations)
            UNION ALL SELECT 'attribute',a.attrelid::text||':'||a.attnum::text,to_jsonb(a)
                FROM pg_attribute a WHERE a.attrelid IN (SELECT oid FROM relations)
            UNION ALL SELECT 'default',d.oid::text,to_jsonb(d) FROM pg_attrdef d WHERE d.adrelid IN (SELECT oid FROM relations)
            UNION ALL SELECT 'constraint',k.oid::text,to_jsonb(k) FROM pg_constraint k WHERE k.conrelid IN (SELECT oid FROM relations)
            UNION ALL SELECT 'index',i.indexrelid::text,to_jsonb(i) FROM pg_index i WHERE i.indrelid IN (SELECT oid FROM relations)
            UNION ALL SELECT 'trigger',t.oid::text,to_jsonb(t) FROM pg_trigger t WHERE t.tgrelid IN (SELECT oid FROM relations)
                AND NOT(t.tgisinternal AND t.tgconstraint IN (SELECT oid FROM calendar_fks))
            UNION ALL SELECT 'policy',p.oid::text,to_jsonb(p) FROM pg_policy p WHERE p.polrelid IN (SELECT oid FROM relations)
            UNION ALL SELECT 'rewrite',r.oid::text,to_jsonb(r) FROM pg_rewrite r WHERE r.ev_class IN (SELECT oid FROM relations)
            UNION ALL SELECT 'sequence',s.seqrelid::text,to_jsonb(s) FROM pg_sequence s WHERE s.seqrelid IN (SELECT oid FROM relations)
            UNION ALL SELECT 'function',p.oid::text,to_jsonb(p) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('core','public')
            UNION ALL SELECT 'type',t.oid::text,to_jsonb(t) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                WHERE n.nspname IN ('core','public') AND t.typrelid<>(SELECT oid FROM target)
                AND t.typelem<>(SELECT reltype FROM pg_class WHERE oid=(SELECT oid FROM target)))
            SELECT kind,key,value::text FROM items ORDER BY kind,key""")
        assert len(rows) < 6000
        protected = {}
        for name in ("product_api_budgets", "core_schema_versions"):
            protected[name] = [tuple(r) for r in await control.fetch(
                'SELECT xmin::text,ctid::text,* FROM core."' + name + '" ORDER BY 1,2')]
        return [tuple(r) for r in rows], protected

    async def recreate_empty_legacy_calendar():
        from sqlalchemy.dialects.postgresql import dialect
        from sqlalchemy.schema import CheckConstraint, CreateIndex, CreateTable, ForeignKeyConstraint, PrimaryKeyConstraint
        from schema_migrations.revisions.catalog_v1 import (
            columns, constraints, indexes, normalize_check, verify_columns, verify_fk_triggers, verify_index,
        )
        model_identity = current_orm_identity()
        table = legacy_calendar_table()
        assert current_orm_identity() == model_identity
        spec = head.parent.contract
        assert list(table.columns.keys()) == [c["name"] for c in spec["legacy_columns"]]
        assert "protocol_sequence" not in table.columns
        assert all(c.name != spec["managed_check"] for c in table.constraints)
        expected_fks = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]

        async def canonical_fk_receipt(calendar_oid):
            keys = await constraints(control, calendar_oid)
            local_names = {r["attnum"]: r["attname"] for r in await control.fetch(
                "SELECT attnum,attname FROM pg_attribute WHERE attrelid=$1 AND attnum>0 AND NOT attisdropped", calendar_oid)}
            assert sum(row["kind"] == "f" for row in keys) == len(expected_fks)
            result = []
            for wanted in expected_fks:
                target = next(iter(wanted.elements)).column.table
                target_oid = await control.fetchval("SELECT to_regclass($1)::oid", "core." + target.name)
                target_names = {r["attnum"]: r["attname"] for r in await control.fetch(
                    "SELECT attnum,attname FROM pg_attribute WHERE attrelid=$1 AND attnum>0 AND NOT attisdropped", target_oid)}
                matches = [row for row in keys if row["kind"] == "f" and row["target_oid"] == target_oid
                           and [local_names[k] for k in row["keys"]] == list(wanted.column_keys)
                           and [target_names[k] for k in row["target_keys"]] == [e.column.name for e in wanted.elements]]
                assert len(matches) == 1
                row = matches[0]
                assert wanted.ondelete == "CASCADE" and wanted.onupdate is None
                assert row["delete_action"] == "c" and row["update_action"] == "a"
                assert row["validated"] and not row["deferrable"] and not row["deferred"]
                await verify_fk_triggers(control, row["oid"], calendar_oid, target_oid)
                triggers = await control.fetch("""SELECT t.oid,t.tgrelid,t.tgconstrrelid,t.tgenabled::text AS enabled,
                    t.tgisinternal AS internal,t.tgdeferrable AS deferrable,t.tginitdeferred AS deferred,
                    t.tgtype AS kind,n.nspname AS function_schema,p.proname AS function_name
                    FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=p.pronamespace
                    WHERE t.tgconstraint=$1 ORDER BY t.oid""", row["oid"])
                result.append({"constraint_oid": row["oid"], "name": row["name"], "target_oid": target_oid,
                               "columns": list(wanted.column_keys), "target": target.name,
                               "triggers": [dict(t) for t in triggers]})
            return sorted(result, key=lambda row: row["columns"])

        old_oid = await control.fetchval("SELECT 'core.calendar_events'::regclass::oid")
        old_fk_receipt = await canonical_fk_receipt(old_oid)
        before = await protected_calendar_neighbors()
        async with engine.begin() as conn:
            actual = (await conn.execute(text("SELECT current_database(),current_user,current_schema()"))).one()
            assert tuple(actual) == (config.database, config.user, "core")
            assert await conn.scalar(text("SELECT count(*) FROM core.calendar_events")) == 0
            assert await conn.scalar(text("""SELECT NOT EXISTS(SELECT 1 FROM pg_constraint
                WHERE confrelid='core.calendar_events'::regclass AND conrelid<>confrelid)"""))
            await conn.execute(text("DROP TABLE core.calendar_events"))  # No CASCADE, no live/current rows.
            await conn.execute(text(str(CreateTable(table).compile(dialect=dialect()))))
            for index in sorted(table.indexes, key=lambda item: item.name):
                await conn.execute(text(str(CreateIndex(index).compile(dialect=dialect()))))
        assert await protected_calendar_neighbors() == before
        assert current_orm_identity() == model_identity
        oid = await control.fetchval("SELECT 'core.calendar_events'::regclass::oid")
        attributes = await control.fetch("SELECT attnum,attname,attisdropped FROM pg_attribute WHERE attrelid=$1 AND attnum>0 ORDER BY attnum", oid)
        assert [(r["attnum"], r["attname"], r["attisdropped"]) for r in attributes] == [
            (n, name, False) for n, name in enumerate(table.columns.keys(), 1)]
        names = verify_columns(await columns(control, oid), spec["legacy_columns"])
        type_oids = {}
        model_columns = []
        for column in table.columns:
            sql_type = str(column.type.compile(dialect=dialect()))
            type_oid = await control.fetchval("SELECT pg_catalog.to_regtype($1::text)::oid", sql_type)
            actual = await control.fetchrow("""SELECT a.atttypid,a.attnotnull,
                pg_get_expr(d.adbin,d.adrelid) AS default_expr FROM pg_attribute a
                LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                WHERE a.attrelid=$1 AND a.attname=$2 AND NOT a.attisdropped""", oid, column.name)
            default = None if column.server_default is None else str(column.server_default.arg.compile(dialect=dialect()))
            assert actual["atttypid"] == type_oid and actual["attnotnull"] == (not column.nullable)
            assert actual["default_expr"] == default
            type_oids[column.name] = type_oid
            model_columns.append({"name": column.name, "type": sql_type,
                                  "nullable": column.nullable, "server_default": default})
        actual_keys = await constraints(control, oid)
        expected_pk = next(c for c in table.constraints if isinstance(c, PrimaryKeyConstraint))
        expected_checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        assert len(actual_keys) == len(table.constraints)
        assert {k: sum(r["kind"] == k for r in actual_keys) for k in ("p", "f", "c")} == {
            "p": 1, "f": len(expected_fks), "c": len(expected_checks)}
        actual_pk = next(r for r in actual_keys if r["kind"] == "p")
        assert [names[k] for k in actual_pk["keys"]] == list(expected_pk.columns.keys())
        for wanted in expected_checks:
            row = next(r for r in actual_keys if r["kind"] == "c" and r["name"] == wanted.name)
            assert normalize_check(row["expression"]) == normalize_check(str(wanted.sqltext))
        for wanted in expected_fks:
            target_table = next(iter(wanted.elements)).column.table
            target_oid = await control.fetchval("SELECT to_regclass($1)::oid", "core." + target_table.name)
            target_names = {r["attnum"]: r["attname"] for r in await control.fetch(
                "SELECT attnum,attname FROM pg_attribute WHERE attrelid=$1 AND attnum>0 AND NOT attisdropped", target_oid)}
            matches = [r for r in actual_keys if r["kind"] == "f" and r["target_oid"] == target_oid
                       and [names[k] for k in r["keys"]] == list(wanted.column_keys)
                       and [target_names[k] for k in r["target_keys"]] == [e.column.name for e in wanted.elements]]
            assert len(matches) == 1 and wanted.ondelete == "CASCADE" and wanted.onupdate is None
            assert matches[0]["delete_action"] == "c" and matches[0]["update_action"] == "a"
            await verify_fk_triggers(control, matches[0]["oid"], oid, target_oid)
        assert all(r["validated"] and not r["deferrable"] and not r["deferred"] for r in actual_keys)
        new_fk_receipt = await canonical_fk_receipt(oid)
        actual_indexes = await indexes(control, oid)
        assert len(actual_indexes) == len(table.indexes) + 1
        model_indexes = []

        async def verify_model_index(row, columns, *, name, unique, primary):
            opclasses = []
            for column_name in columns:
                candidates = await control.fetch("""SELECT n.nspname||'.'||p.opcname AS name
                    FROM pg_opclass p JOIN pg_namespace n ON n.oid=p.opcnamespace JOIN pg_am a ON a.oid=p.opcmethod
                    WHERE a.amname='btree' AND p.opcdefault AND p.opcintype=$1""", type_oids[column_name])
                assert len(candidates) == 1
                opclasses.append(candidates[0]["name"])
            expected = {"name": name, "columns": columns, "unique": unique, "primary": primary, "opclasses": opclasses}
            verify_index(row, expected, names, config.user)
            model_indexes.append({**expected, "observed_name": row["name"]})

        for wanted in table.indexes:
            matches = [r for r in actual_indexes if r["name"] == wanted.name]
            assert len(matches) == 1
            row = matches[0]
            await verify_model_index(row, list(wanted.columns.keys()), name=wanted.name,
                                     unique=bool(wanted.unique), primary=False)
        assert sum(r["primary"] and r["unique"] for r in actual_indexes) == 1
        await verify_model_index(next(r for r in actual_indexes if r["primary"]), list(expected_pk.columns.keys()),
                                 name=expected_pk.name, unique=True, primary=True)
        legacy_fixture_receipts.append({"old_calendar_oid": old_oid, "legacy_calendar_oid": oid,
            "old_model_sha256": LEGACY_MODEL_SHA, "columns": model_columns, "indexes": model_indexes,
            "constraints": [{"name": r["name"], "kind": r["kind"], "oid": r["oid"]} for r in actual_keys],
            "calendar_owned_fk_before": old_fk_receipt, "calendar_owned_fk_after": new_fk_receipt,
            "outside_catalog_and_budget_journal_xmin_same": True, "current_ORM_metadata_identity_same": True,
            "fixture_only_DDL": True, "source_exec_is_actual_old_model_code": True})

    async def fixture(prefix=3, *, budget_adopt=False, calendar_created=False,
                      pulse_adopt=False, absent_unapplied=False):
        nonlocal owned_core
        # Drop/recreate is fixture setup on the control connection. Discard the
        # prior SQLAlchemy pool before it so no cached ORM plan survives a new
        # relation OID/type; the actual gate never disposes a borrowed pool.
        await engine.dispose()
        if owned_core:
            await execute("DROP SCHEMA core CASCADE")
            owned_core = False
        await execute("CREATE SCHEMA core")
        owned_core = True
        await prepare_parents(engine)  # Exact accepted B literal fixture; no main/bootstrap/seed.
        if budget_adopt:
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync: ProductAPIBudget.__table__.create(sync, checkfirst=False))
            await seed_budget()
        actions = [(await runner.execute(config, "apply"))["action"]]
        if not budget_adopt:
            await seed_budget()
        if prefix >= 2:
            if calendar_created:
                await recreate_empty_legacy_calendar()
            actions.append((await runner.execute(config, "apply", revision=manifest.CALENDAR_ID,
                                               legacy_sent_before=2000000000))["action"])
        if prefix == 3:
            if pulse_adopt:
                async with engine.begin() as conn:
                    await conn.run_sync(lambda sync: PulseViewRoleGrant.__table__.create(sync, checkfirst=False))
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    session.add_all([CompanyRole(id=ROLE, company_id=COMPANY, name="C3 synthetic role", modules=["pulse"]),
                                     PulseView(id=VIEW, company_id=COMPANY, name="C3 synthetic view")])
                    await session.flush()
                    session.add(PulseViewRoleGrant(view_id=VIEW, role_id=ROLE))
                    await session.commit()
                # Canonical explicit owner-only ACL, already accepted by B;
                # this setup grant is outside every read-gate observation.
                await execute("GRANT SELECT ON core.pulse_view_role_grants TO clearledger")
            actions.append((await runner.execute(config, "apply", revision=manifest.PULSE_ID))["action"])
        if absent_unapplied and prefix < 3:
            await execute("DROP TABLE core.pulse_views, core.company_roles")
            if prefix == 1:
                await execute("DROP TABLE core.calendar_events")
        rows = await control.fetch("SELECT revision FROM core.core_schema_versions ORDER BY ordinal")
        assert [r[0] for r in rows] == [manifest.ID, manifest.CALENDAR_ID, manifest.PULSE_ID][:prefix]
        assert "app.main" not in sys.modules
        return actions

    async def snapshot():
        # Independent actual metadata/rows; no private verifier or app projection.
        catalog = await control.fetch("""SELECT c.oid,c.relname,c.relkind::text,c.relowner,c.relacl::text,
            c.relrowsecurity,c.relforcerowsecurity,
            (SELECT json_agg(row(a.attnum,a.attname,a.atttypid,a.atttypmod,a.attnotnull,a.attisdropped,
                pg_get_expr(d.adbin,d.adrelid)) ORDER BY a.attnum)::text
             FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
             WHERE a.attrelid=c.oid AND a.attnum>0) AS columns,
            (SELECT json_agg(row(k.oid,k.conname,pg_get_constraintdef(k.oid),k.convalidated) ORDER BY k.oid)::text
             FROM pg_constraint k WHERE k.conrelid=c.oid) AS constraints,
            (SELECT json_agg(row(t.oid,t.tgenabled,t.tgisinternal,t.tgfoid) ORDER BY t.oid)::text
             FROM pg_trigger t WHERE t.tgrelid=c.oid) AS triggers,
            (SELECT json_agg(pg_get_indexdef(i.indexrelid) ORDER BY i.indexrelid)::text
             FROM pg_index i WHERE i.indrelid=c.oid) AS indexes
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('core','public') AND c.relkind IN ('r','p','v','m','f','S') ORDER BY c.oid""")
        rows = {}
        for name in ("product_api_budgets", "core_schema_versions", "pulse_view_role_grants"):
            exists = await control.fetchval("SELECT to_regclass($1)::oid", "core." + name)
            if exists:
                rows[name] = [tuple(r) for r in await control.fetch(
                    'SELECT xmin::text,ctid::text,* FROM core."' + name + '" ORDER BY 1,2')]
        if await control.fetchval("SELECT to_regclass('public.product_api_budgets')::oid"):
            rows["public.product_api_budgets"] = [tuple(r) for r in await control.fetch(
                "SELECT xmin::text,ctid::text,* FROM public.product_api_budgets ORDER BY 1,2")]
        return [tuple(row) for row in catalog], rows

    @asynccontextmanager
    async def observe(kind, *, connection=None):
        start, checkout_start = len(observations), len(checkouts)
        pairs_start = len(owned_pairs)
        if kind == "borrowed":
            assert connection is not None
            driver = (await connection.get_raw_connection()).driver_connection
            before = await scalar_probe(driver)
            options_before = copy.deepcopy(dict(connection.sync_connection.get_execution_options()))
        else:
            assert kind == "owned" and connection is None
        connects_before = running_counters()["pg_connect"]
        summary = {}
        token = phase.set(kind)
        try:
            yield summary
        finally:
            await asyncio.sleep(0)  # Flush real asyncpg query logger callbacks.
            phase.reset(token)
            if kind == "borrowed":
                after = await scalar_probe(driver)
                options_after = copy.deepcopy(dict(connection.sync_connection.get_execution_options()))
                assert options_after == options_before, "borrowed execution options changed"
                assert after["in_transaction"], "borrowed caller transaction finished"
                # A lazy caller has no physical TX yet. Compare its requested
                # options to the now-real TX, not the pre-TX session defaults.
                expected_read_only = before["read_only"]
                expected_isolation = before["isolation"]
                if not before["in_transaction"]:
                    if "postgresql_readonly" in options_before:
                        expected_read_only = "on" if options_before["postgresql_readonly"] else "off"
                    if "isolation_level" in options_before:
                        expected_isolation = options_before["isolation_level"].lower().replace("_", " ")
                assert after["read_only"] == expected_read_only and after["isolation"] == expected_isolation
            else:
                assert len(owned_pairs) - pairs_start == 1, "owned gate must use exactly one observed physical connection"
                before, after, options_before, options_after = owned_pairs[-1]
                assert not before["in_transaction"] and not after["in_transaction"]
                assert after["read_only"] == before["read_only"] and after["isolation"] == before["isolation"]
                assert options_after.get("postgresql_readonly") is True
                assert options_after.get("isolation_level") == "REPEATABLE READ"
                owned_keys = {"postgresql_readonly", "isolation_level"}
                assert {k: v for k, v in options_after.items() if k not in owned_keys} == {
                    k: v for k, v in options_before.items() if k not in owned_keys}
            assert before["pid"] == after["pid"] and before["jit"] == after["jit"]
            assert before["path"] == after["path"], "gate changed actual search_path"
            assert before["jit"] in {"on", "off"}
            assert not observation_errors, "async query callback observation failed"
            seen = observations[start:]
            assert seen and any(source == "sqlalchemy" and keyword == "select"
                                for _, _, source, keyword, _, _ in seen), "actual SQLAlchemy probe observation missing"
            allowed = {"select", "begin", "start"} if kind == "borrowed" else {"select", "show", "begin", "start", "commit", "rollback"}
            state = "idle"
            groups = 0
            offending = []
            for row in seen:
                scope, pid, origin, keyword, lock, digest = row
                if pid != before["pid"]:
                    offending.append(row)
                    continue
                label = DRIVER_PROTOCOL.get(digest) if origin == "raw" else None
                if label is not None:
                    shape = ((keyword == "with" and not lock) if label == "types"
                             else (keyword == "select" and lock))
                    if not shape:
                        offending.append(row)
                    elif label == "off" and state == "idle":
                        state = "types"
                    elif label == "types" and state == "types":
                        if before["jit"] == "on":
                            state = "restore"
                        else:
                            groups += 1
                            state = "idle"
                    elif label == "restore" and state == "restore" and before["jit"] == "on":
                        groups += 1
                        state = "idle"
                    else:
                        offending.append(row)
                elif keyword not in allowed or lock or (origin == "raw" and state != "idle"):
                    offending.append(row)
            if offending:
                unique = list(dict.fromkeys(offending))
                records = [{"scope": scope, "origin": origin, "keywordEnum": keyword,
                            "lockOrGuc": lock, "normalizedSQLSHA": digest}
                           for scope, _, origin, keyword, lock, digest in unique[:8]]
                diagnostic = json.dumps({"records": records, "offendingCount": len(offending),
                                         "truncated": len(unique) > 8}, sort_keys=True, separators=(",", ":"))
                assert len(diagnostic.encode("utf-8")) <= 4096, "observer diagnostic bound exceeded"
                # No raw SQL/args/env, and never a PASS progress event on refusal.
                raise AssertionError("read gate observation refused: " + diagnostic)
            assert state == "idle", "driver codec protocol was incomplete"
            assert len(checkouts) - checkout_start == (1 if kind == "owned" else 0), "gate opened extra connection"
            # These engine pools are warm from canonical fixture preparation.
            # Count raw-driver connections too; checkout alone cannot detect a
            # hidden asyncpg.connect call inside the verifier.
            assert running_counters()["pg_connect"] == connects_before, "gate opened an extra raw connection"
            summary.update(kind=kind, pid=before["pid"], jit_before=before["jit"], jit_after=after["jit"],
                           path_same=True, transaction_before=before["in_transaction"],
                           transaction_after=after["in_transaction"], driver_codec_groups=groups,
                           options_verified=True, owned_before_pool_reset=kind == "owned")
            assert len(probe_receipts) < 6000
            probe_receipts.append(dict(summary))

    async def check(*, refused=False, candidate=None, owned=False, module=gate, target_engine=engine):
        before = await snapshot()
        if owned:
            async with observe("owned"):
                try:
                    receipt = await module.require_engine(ProbedEngine(target_engine), candidate or settings)
                except RuntimeError as error:
                    assert refused and str(error) == "Managed Core budget schema is not ready"
                    receipt = None
                else:
                    assert not refused and receipt.driver_in_transaction
                    assert receipt.read_only and receipt.isolation == "repeatable read"
        else:
            async with target_engine.begin() as conn:
                async with observe("borrowed", connection=conn):
                    try:
                        receipt = await module.require_connection(conn, candidate or settings)
                    except RuntimeError as error:
                        assert refused and str(error) == "Managed Core budget schema is not ready"
                        assert error.__suppress_context__
                        receipt = None
                    else:
                        assert not refused and receipt.driver_in_transaction
                assert (await conn.get_raw_connection()).driver_connection.is_in_transaction()
        assert await snapshot() == before, "gate changed actual catalog/rows/xmin/OIDs"
        return receipt

    async def append_unknown(ordinal):
        await execute("""INSERT INTO core.core_schema_versions
            (revision,ordinal,parent_revision,artifact_sha256,contract_sha256,predecessor_sha256,action,applied_by,app_commit,runner_format)
            VALUES($1,$2,$3,$4,$5,$4,'created',$6,$7,1)""",
            "9999_unknown_" + str(ordinal), ordinal, manifest.PULSE_ID, "0" * 64, "1" * 64, config.user, "0" * 40)

    def quote(name):
        return '"' + name.replace('"', '""') + '"'

    try:
        identity = await control.fetchrow("""SELECT current_database() AS db,current_user AS usr,
            (SELECT pg_get_userbyid(datdba)=current_user FROM pg_database WHERE datname=current_database()) AS owner,
            current_setting('server_version_num')::int AS version,
            (SELECT count(*) FROM pg_namespace WHERE nspname='core') AS core""")
        assert (identity["db"], identity["usr"], identity["owner"], identity["core"]) == (config.database, config.user, True, 0)
        assert 160000 <= identity["version"] < 170000
        admission = await control.fetchrow("""SELECT current_setting('max_locks_per_transaction')::int AS locks,
            pg_database_size(current_database()) AS bytes,
            (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()) AS other_clients,
            (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
             WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
             AND c.relkind IN ('r','p','v','m','f','S')) AS relations""")
        assert admission["locks"] == 64 and admission["bytes"] < 256 * 1024 * 1024
        assert admission["other_clients"] == admission["relations"] == 0, "dedicated database must be empty/exclusive"
        for case_id, prefix, kwargs, expected in (
            (PREFIX_IDS[0], 1, {"absent_unapplied": True}, ["created"]),
            (PREFIX_IDS[1], 1, {"budget_adopt": True}, ["adopted"]),
            (PREFIX_IDS[2], 2, {"calendar_created": True, "absent_unapplied": True}, ["created", "created"]),
            (PREFIX_IDS[3], 2, {}, ["created", "adopted"]),
            (PREFIX_IDS[4], 3, {}, ["created", "adopted", "created"]),
            (PREFIX_IDS[5], 3, {"pulse_adopt": True}, ["created", "adopted", "adopted"]),
        ):
            assert await fixture(prefix, **kwargs) == expected
            await check()
            await check(owned=True)
            record(case_id, actions=expected)

        for case_id in HISTORY_IDS:
            await fixture(1 if case_id == "H-required-absent" else 3)
            if case_id == "H-required-absent":
                async with engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                    raw = (await conn.get_raw_connection()).driver_connection
                    before = await snapshot()
                    try:
                        await runner.require_applied_prefix(raw, config, head, required_revision=manifest.CALENDAR_ID)
                    except MigrationError as error:
                        assert error.phase == "unapplied"
                    else:
                        raise AssertionError("minimum revision ignored")
                    assert await snapshot() == before
            else:
                if case_id == "H-empty": await execute("DELETE FROM core.core_schema_versions")
                if case_id == "H-missing-journal": await execute("DROP TABLE core.core_schema_versions")
                if case_id == "H-gap-1": await execute("DELETE FROM core.core_schema_versions WHERE ordinal=1")
                if case_id == "H-gap-2": await execute("DELETE FROM core.core_schema_versions WHERE ordinal=2")
                if case_id == "H-unknown-row": await execute("UPDATE core.core_schema_versions SET revision='9999_unknown' WHERE ordinal=2")
                if case_id in {"H-future-row", "H-extra-over-bound"}:
                    await append_unknown(4)
                    if case_id == "H-extra-over-bound": await append_unknown(5)
                if case_id == "H-duplicate-or-reordered":
                    try:
                        await execute("INSERT INTO core.core_schema_versions SELECT * FROM core.core_schema_versions WHERE ordinal=1")
                    except asyncpg.UniqueViolationError:
                        pass
                    else:
                        raise AssertionError("journal lost uniqueness")
                    await execute("UPDATE core.core_schema_versions SET ordinal=9 WHERE ordinal=1")
                await check(refused=True)
                await check(refused=True, owned=True)
            record(case_id)

        for ordinal in (1, 2, 3):
            for field in FIELDS:
                await fixture()
                case_id = "H" + str(ordinal) + "-" + field
                value = {"revision": "9999_corrupt", "ordinal": 9, "parent_revision": "wrong_parent",
                         "artifact_sha256": "0" * 64, "contract_sha256": "0" * 64,
                         "predecessor_sha256": "0" * 64, "runner_format": 2, "app_commit": "0" * 40,
                         "applied_by": "other_test_actor", "action": "repaired"}[field]
                if field == "action":
                    before = await snapshot()
                    try:
                        await execute("UPDATE core.core_schema_versions SET action=$1 WHERE ordinal=$2", value, ordinal)
                    except asyncpg.CheckViolationError:
                        pass
                    else:
                        raise AssertionError("journal lost action CHECK")
                    assert await snapshot() == before
                    rows = [dict(r) for r in await control.fetch("SELECT * FROM core.core_schema_versions ORDER BY ordinal")]
                    rows[ordinal - 1][field] = value
                    try:
                        journal.validate_history(rows, head, config.user)
                    except MigrationError:
                        pass
                    else:
                        raise AssertionError("row action verifier accepted invalid action")
                    record(case_id, evidence="SQL CHECK refusal + actual pure validator; not persisted bad action")
                else:
                    await execute('UPDATE core.core_schema_versions SET ' + quote(field) + '=$1 WHERE ordinal=$2', value, ordinal)
                    await check(refused=True)
                    record(case_id, evidence="persisted bad row; borrowed actual gate refusal")

        for case_id in CATALOG_IDS:
            await fixture()
            if case_id == "C-budget-column": await execute("ALTER TABLE core.product_api_budgets ALTER COLUMN used SET DEFAULT 1")
            if case_id in {"C-budget-fk-trigger", "C-pulse-fk"}:
                table = "product_api_budgets" if case_id == "C-budget-fk-trigger" else "pulse_view_role_grants"
                name = await control.fetchval("SELECT conname FROM pg_constraint WHERE conrelid=$1::regclass AND contype='f' ORDER BY conname LIMIT 1", "core." + table)
                assert name
                await execute("ALTER TABLE core." + quote(table) + " DROP CONSTRAINT " + quote(name))
            if case_id == "C-journal-shape": await execute("ALTER TABLE core.core_schema_versions ADD COLUMN unexpected text")
            if case_id in {"C-parent-ownership", "C-calendar-owner"}:
                await execute("GRANT USAGE,CREATE ON SCHEMA core TO pg_database_owner")
                table = "partner_installations" if case_id == "C-parent-ownership" else "calendar_events"
                await execute("ALTER TABLE core." + quote(table) + " OWNER TO pg_database_owner")
            if case_id == "C-calendar-managed-column": await execute("ALTER TABLE core.calendar_events DROP CONSTRAINT ck_calendar_event_protocol_sequence, DROP COLUMN protocol_sequence")
            if case_id == "C-calendar-managed-check": await execute("ALTER TABLE core.calendar_events DROP CONSTRAINT ck_calendar_event_protocol_sequence")
            if case_id == "C-pulse-shape": await execute("ALTER TABLE core.pulse_view_role_grants ADD COLUMN unexpected text")
            if case_id == "C-pulse-trigger-acl": await execute("GRANT SELECT ON core.pulse_view_role_grants TO PUBLIC")
            if case_id == "C-public-sentinel":
                await execute("CREATE TABLE public.product_api_budgets(marker text PRIMARY KEY)")
                await execute("INSERT INTO public.product_api_budgets VALUES('synthetic sentinel')")
                try:
                    await check()
                    assert await control.fetchval("SELECT marker FROM public.product_api_budgets") == "synthetic sentinel"
                finally:
                    await execute("DROP TABLE public.product_api_budgets")
            else:
                await check(refused=True)
                await check(refused=True, owned=True)
            record(case_id)

        await fixture()
        async with engine.begin() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            assert not raw.is_in_transaction(), "fixture accidentally started the lazy caller transaction"
            async with observe("borrowed", connection=conn):
                receipt = await gate.require_connection(conn, settings)
            assert raw.is_in_transaction() and receipt.driver_in_transaction
        record("T-borrowed-lazy-TX")

        await execute("CREATE TABLE core.schema_gate_caller_probe(id int PRIMARY KEY,value int NOT NULL)")
        await execute("INSERT INTO core.schema_gate_caller_probe VALUES(1,1)")
        async with engine.begin() as conn:
            async with observe("borrowed", connection=conn):
                await gate.require_connection(conn, settings)
            await conn.execute(text("UPDATE core.schema_gate_caller_probe SET value=2 WHERE id=1"))
            assert await control.fetchval("SELECT value FROM core.schema_gate_caller_probe") == 1
        assert await control.fetchval("SELECT value FROM core.schema_gate_caller_probe") == 2
        record("T-borrowed-readwrite-continuation")

        async with engine.connect() as conn:
            conn = await conn.execution_options(postgresql_readonly=True)
            async with conn.begin():
                async with observe("borrowed", connection=conn):
                    receipt = await gate.require_connection(conn, settings)
                assert receipt.read_only
                try:
                    await conn.execute(text("UPDATE core.schema_gate_caller_probe SET value=3 WHERE id=1"))
                except Exception as error:
                    assert getattr(getattr(error, "orig", None), "sqlstate", None) == "25006"
                    await conn.rollback()  # Caller cleanup after its deliberate forbidden write.
                else:
                    raise AssertionError("actual readonly caller transaction allowed a write")
        record("T-borrowed-readonly-enforcement")

        async with engine.connect() as conn:
            conn = await conn.execution_options(isolation_level="SERIALIZABLE", postgresql_readonly=True,
                                                schema_translate_map={"c3_test": "core"})
            async with conn.begin():
                before = tuple((await conn.execute(text("SELECT current_setting('search_path'),current_setting('transaction_read_only'),current_setting('transaction_isolation')"))).one())
                options = dict(conn.sync_connection.get_execution_options())
                async with observe("borrowed", connection=conn):
                    receipt = await gate.require_connection(conn, settings)
                after = tuple((await conn.execute(text("SELECT current_setting('search_path'),current_setting('transaction_read_only'),current_setting('transaction_isolation')"))).one())
                assert before == after and options == dict(conn.sync_connection.get_execution_options())
                assert receipt.read_only and receipt.isolation == "serializable"
        record("T-borrowed-isolation-path-options")
        await check(owned=True)
        record("T-owned-RR-readonly")
        public_engine = engine_for("public")
        await check(refused=True, target_engine=public_engine)
        record("T-actual-public-refusal")
        other = make_url(settings.database_url).set(database="other_expected_test_database")
        changed = SimpleNamespace(**vars(settings))
        changed.database_url = other.render_as_string(hide_password=False)
        changed.managed_core_budget_expected_database = "other_expected_test_database"
        await check(refused=True, candidate=changed)
        record("T-actual-identity-refusal", evidence="valid Config for different expected DB; actual borrowed connection unchanged")
        await check()
        await check(owned=True)
        record("T-no-writes-locks-options-extra-connect", raw_query_observation=True,
               sqlalchemy_query_observation=True)
        await execute("UPDATE core.core_schema_versions SET applied_by='synthetic_sensitive_actor' WHERE ordinal=3")
        await check(refused=True)
        record("T-safe-error-redaction")
        await fixture()
        await check()
        await check()
        await check(owned=True)
        record("T-gate-repeat-invariance")

        for jit in ("on", "off"):
            # Fresh physical connections with a true session startup baseline,
            # not SET LOCAL whose scope a driver set_config(false) can alter.
            cold = engine_for(jit=jit)
            async with cold.begin() as conn:
                raw = (await conn.get_raw_connection()).driver_connection
                assert not raw.is_in_transaction()
                async with observe("borrowed", connection=conn) as measured:
                    receipt = await gate.require_connection(conn, settings)
                assert receipt.driver_in_transaction
                assert measured["jit_before"] == measured["jit_after"] == jit
                assert measured["driver_codec_groups"] >= 1, "fresh metadata codecs were unexpectedly warm"
                pid = measured["pid"]
            # Check the same physical session after caller commit as well.
            async with cold.connect() as conn:
                raw = (await conn.get_raw_connection()).driver_connection
                committed = await scalar_probe(raw)
                assert committed["pid"] == pid and committed["jit"] == jit
                assert not committed["in_transaction"]
            record("T-cold-jit-" + jit, jit=jit, same_pid=True, after_caller_commit_same=True,
                   codec_groups=measured["driver_codec_groups"])

        tests = Path(__file__).resolve().parent
        for name, wanted in (("schema_gate_history_old_gate_20261030.py", OLD_GATE_SHA),
                             ("run_managed_schema_cutover.py", OLD_HARNESS_SHA),
                             ("managed_schema_cutover_approved.py", OLD_APPROVAL_SHA)):
            assert hashlib.sha256((tests / name).read_bytes()).hexdigest() == wanted
        record("OLD-immutable-harness-closure-preserved", evidence="exact gate/harness/wrapper bytes; historical app489/schema16 independently source-hashed, not rerun")
        old_name = "_schema_gate_history_old_fixture"
        spec = importlib.util.spec_from_file_location(old_name, tests / "schema_gate_history_old_gate_20261030.py")
        old_gate = importlib.util.module_from_spec(spec)
        sys.modules[old_name] = old_gate
        try:
            spec.loader.exec_module(old_gate)
            await fixture(2)
            await check(refused=True, module=old_gate)
        finally:
            sys.modules.pop(old_name, None)
        record("OLD-gate-P2-refusal", evidence="immutable old gate bytes + current unchanged strict default-target behavior; not whole old binary")
        before = await snapshot()
        try:
            await runner.execute(config, "check")
        except MigrationError:
            pass
        else:
            raise AssertionError("explicit default target stopped refusing newer history")
        assert await snapshot() == before
        record("OLD-explicit-default-runner-P2-refusal")
        assert set(completed) == set(CASE_IDS) and len(completed) == len(CASE_IDS) == 71
        assert all(count > 0 for count in observation_counts.values()), "both query capture channels must be live"
        assert "app.main" not in sys.modules
        return {"completed": completed, "details": details, "observed_gate_queries": len(observations),
                "observed_gate_queries_by_source": observation_counts,
                "connection_probe_receipts": probe_receipts,
                "legacy_calendar_fixture_receipts": legacy_fixture_receipts,
                "driver_codec_groups": sum(row["driver_codec_groups"] for row in probe_receipts),
                "driver_jit_scope": "observed/restored on tested normal paths; cold cancellation/error unproven",
                "observed_gate_checkouts": len(checkouts), "without_app_main": True}
    finally:
        try:
            if owned_core:
                await execute("DROP SCHEMA core CASCADE")
        finally:
            try:
                await control.close()
            finally:
                try:
                    for owned_engine in engines:
                        await owned_engine.dispose()
                finally:
                    await database.engine.dispose()


if __name__ == "__main__":
    raise SystemExit("ROOT immutable approval helper required; direct execution is refused")
