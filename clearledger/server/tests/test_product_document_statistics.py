"""Owned document statistics control: unchanged SQL, four plans, two ANALYZE."""
import os
from pathlib import Path
import sys

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_PRODUCT_DOCUMENT_STATISTICS_TESTS"
TARGET = "postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_product_query_scaling_test"
RUNTIME = Path("/srv/projects/api-modernization-test-env-20261029")
EMPTY_CWD = RUNTIME / "product-query-scaling-empty-test"
UPLOAD = RUNTIME / "product-query-scaling-test-uploads"
EVIDENCE = RUNTIME / "private-product-document-statistics-20261030"
CEILING = 256 * 1024 * 1024
PINS = {
    "test_product_query_scaling.py": "054f2c99deba32c25459f68688e5f29cfa4b83f8b3ec0bda2635c844620165c2",
    "test_product_document_query_plans.py": "eeae2aed0780bab54fcd8e92de29cdb721093ef848dbf9ca597d44a6e454a2cf",
}

error = partner_test_safety_error(os.environ, flag=FLAG)
if os.environ.get(FLAG) != "1" and __name__ != "__main__":
    import pytest
    pytest.skip("Opt in with RUN_PRODUCT_DOCUMENT_STATISTICS_TESTS=1", allow_module_level=True)
if error:
    raise RuntimeError("Refusing document statistics: " + error)
if any(os.environ.get(key) != TARGET for key in ("TEST_DATABASE_URL", "DATABASE_URL")):
    raise RuntimeError("Refusing document statistics: both exact canonical owned URIs required")
if (os.environ.get("APP_ENV") != "test" or os.environ.get("UPLOAD_DIR") != str(UPLOAD)
        or any(os.environ.get(key) != "1" for key in ("RUN_PRODUCT_DOCUMENT_QUERY_PLANS_TESTS",
            "RUN_PRODUCT_QUERY_SCALING_TESTS", "RUN_PARTNER_RESOURCE_TESTS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD"))
        or Path.cwd() != EMPTY_CWD or any(EMPTY_CWD.iterdir())):
    raise RuntimeError("Refusing document statistics: explicit flags/test upload/empty cwd required")

import hashlib
for name, expected in PINS.items():
    if hashlib.sha256((SERVER / "tests" / name).read_bytes()).hexdigest() != expected:
        raise RuntimeError("Refusing document statistics: pinned helper source changed")


if __name__ == "__main__":
    import asyncio
    import json
    import signal

    if sys.argv[1:] != ["--execute-approved-document-statistics"]:
        raise RuntimeError("Separate statistics-control SQL/ANALYZE grant required")
    signal.signal(signal.SIGALRM, lambda *_: sys.exit("330s runner bound exceeded; attempt own teardown"))
    signal.alarm(330)

    async def preflight():
        import asyncpg
        if any(os.environ.get(key) != TARGET for key in ("TEST_DATABASE_URL", "DATABASE_URL")):
            raise RuntimeError("Owned URI changed before connect")
        EVIDENCE.mkdir(mode=0o700, exist_ok=True)
        if any((EVIDENCE / name).exists() for name in ("preflight.json", "results.xml", "http-samples.jsonl",
                "safe-summary.json", "analyze.json")) or any(EVIDENCE.glob("*-plan.json")):
            raise RuntimeError("Refusing to overwrite prior statistics evidence")
        connection = await asyncpg.connect(TARGET.replace("postgresql+asyncpg:", "postgresql:", 1),
            timeout=5, server_settings={"statement_timeout": "15000", "lock_timeout": "1000"})
        try:
            value = dict(await connection.fetchrow("SELECT current_database() AS db, current_user AS usr, "
                "current_setting('server_version_num')::int AS version, "
                "current_setting('max_locks_per_transaction')::int AS maxlocks, "
                "pg_database_size(current_database()) AS bytes, "
                "(SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' "
                "AND pid <> pg_backend_pid()) AS other_clients"))
            if (value["db"] != "api_product_query_scaling_test" or value["usr"] != "clearledger"
                    or not 160000 <= value["version"] < 170000 or value["maxlocks"] != 64
                    or value["other_clients"] != 0 or value["bytes"] >= CEILING):
                raise RuntimeError("Synthetic preflight refused: " + json.dumps(value, sort_keys=True))
            (EVIDENCE / "preflight.json").write_text(json.dumps(value, sort_keys=True) + "\n")
        finally:
            await connection.close()

    asyncio.run(preflight())
    import pytest
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), "-c", str(SERVER / "pytest.ini"),
        "-p", "pytest_asyncio.plugin", "-p", "no:cacheprovider", "-q", "-ra", "--maxfail=1",
        "--confcutdir=" + str(SERVER), "--basetemp=" + str(EVIDENCE / "pytest-test-tmp"),
        "-o", "junit_family=legacy", "--junitxml=" + str(EVIDENCE / "results.xml")]))


import json
import time

import pytest
from sqlalchemy import text

from tests import test_product_document_query_plans as plans
from tests.test_partner_resource_query_budget import budget, signing_pem

pytestmark = pytest.mark.asyncio(loop_scope="session")
TABLES = ("doc_cards", "doc_access_grants")
ANALYZE_SQL = (("doc_cards", "ANALYZE public.doc_cards"),
    ("doc_access_grants", "ANALYZE public.doc_access_grants"))
STATISTICS = text("""
SELECT current_database() AS database_name, s.schemaname AS schema_name,
       pg_catalog.pg_get_userbyid(c.relowner) AS owner, c.relkind::text AS relation_kind,
       s.relname, c.reltuples::double precision AS reltuples, c.relpages,
       c.relallvisible, s.n_live_tup, s.n_dead_tup, s.n_mod_since_analyze,
       s.analyze_count, s.autoanalyze_count, s.last_analyze, s.last_autoanalyze
FROM pg_catalog.pg_stat_all_tables s
JOIN pg_catalog.pg_class c ON c.oid = s.relid
WHERE s.schemaname = 'public' AND s.relname IN ('doc_cards', 'doc_access_grants')
ORDER BY s.relname
""")


def target_guard(engine):
    assert all(os.environ.get(key) == TARGET for key in ("TEST_DATABASE_URL", "DATABASE_URL"))
    assert engine.url.render_as_string(hide_password=False) == TARGET


async def read_only(connection):
    # Imported baseline listener issues only transaction-local timeout commands
    # on begin. This mode declaration precedes every SELECT in this transaction.
    await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    assert await connection.scalar(text("SELECT current_setting('transaction_read_only')")) == "on"


async def statistics(connection):
    rows = [dict(row) for row in (await connection.execute(STATISTICS)).mappings().all()]
    assert {row["relname"] for row in rows} == set(TABLES)
    assert all(row["database_name"] == "api_product_query_scaling_test" and row["schema_name"] == "public"
        and row["owner"] == "clearledger" and row["relation_kind"] == "r" for row in rows)
    return rows


async def plan_phase(b, statements, phase):
    target_guard(b.engine)
    measured = []
    async with b.engine.connect() as connection:
        async with connection.begin():
            await read_only(connection)
            start = await statistics(connection)
            for item in statements:
                result = await connection.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + item["sql"], item["parameters"])
                raw = result.scalar_one()
                if isinstance(raw, str):
                    raw = json.loads(raw)
                plans.private_json(phase + "-" + item["kind"] + "-plan.json", raw)
                value = plans.safe_plan(item["kind"], item, raw)
                assert value["root_actual_rows"] == (1 if item["kind"] == "count" else 201)
                measured.append(value)
    # A separate RO transaction avoids reusing this transaction's cached
    # pg_stat snapshot. Counters can still have publication lag; retain times.
    async with b.engine.connect() as connection:
        async with connection.begin():
            await read_only(connection)
            end = await statistics(connection)
    fields = ("relname", "analyze_count", "autoanalyze_count", "last_analyze", "last_autoanalyze")
    changed = ([{key: row[key] for key in fields} for row in start]
        != [{key: row[key] for key in fields} for row in end])
    summary = {"phase": phase, "read_only": True, "statistics_start": start,
        "statistics_end": end, "observed_analyze_counter_change_during_phase": changed, "plans": measured}
    plans.private_json(phase + "-phase.json", summary)
    return summary


@pytest.mark.asyncio(loop_scope="session")
async def test_actual_document_statistics_control(budget, monkeypatch, record_property):
    b = budget
    # Local test-harness namespace in this fresh process only. The pinned
    # tracked helper files and the product API are never changed.
    monkeypatch.setattr(plans, "EVIDENCE", EVIDENCE)
    d = await plans.baseline.dataset(b, 5000)
    await plans.baseline.policy(b, d, False, False)
    before_page, statements = await plans.golden(b, d, "before")
    assert [item["kind"] for item in statements] == ["count", "page"]
    for item in statements:
        plans.private_json(item["kind"] + "-statement.json", item)
    before = await plan_phase(b, statements, "before")
    target_guard(b.engine)
    analyzed = []
    async with b.engine.connect() as connection:
        async with connection.begin():
            await read_only(connection)
            targets = await statistics(connection)
        # Same owned connection after RO metadata commit. Writable transaction
        # contains exactly these two literal maintenance commands plus the
        # inherited SET LOCAL limits, no metadata SELECT or other table target.
        async with connection.begin():
            for table, command in ANALYZE_SQL:
                started = time.perf_counter()
                await connection.exec_driver_sql(command)
                analyzed.append({"table": table, "wall_seconds": time.perf_counter() - started})
    plans.private_json("analyze.json", analyzed)
    after = await plan_phase(b, statements, "after")
    after_page, after_statements = await plans.golden(b, d, "after")
    assert after_page == before_page
    assert [(item["sql"], item["parameters"]) for item in after_statements] == [
        (item["sql"], item["parameters"]) for item in statements]
    samples = [json.loads(line) for line in (EVIDENCE / "http-samples.jsonl").read_text().splitlines()]
    assert len(samples) == 16
    for key in ("page200", "cursor200", "positive-detail", "tenant", "private", "deny", "strict", "service-denied"):
        pair = [{name: value for name, value in sample.items() if name not in ("phase", "http_wall_seconds")}
            for sample in samples if sample["case"] == key]
        assert len(pair) == 2 and pair[0] == pair[1]
    summary = {"scale": 5000, "http_samples": 16, "explain_count": 4, "analyze_count": 2,
        "visible_total": 2000, "response_rows": 200, "hydrated_page_rows": 201,
        "database_bytes_after_dataset": d.bytes, "database_bytes_after_queries": await plans.baseline.database_size(b.db),
        "phases": [before, after], "analyzed_tables": list(TABLES), "verified_analyze_targets": targets}
    plans.private_json("safe-summary.json", summary)
    record_property("product_document_statistics", json.dumps(summary, sort_keys=True, default=str))
