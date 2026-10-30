"""Two actual document query plans, owned synthetic DB, explicit SQL grant only."""
import os
from pathlib import Path
import sys

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_PRODUCT_DOCUMENT_QUERY_PLANS_TESTS"
TARGET = "postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_product_query_scaling_test"
RUNTIME = Path("/srv/projects/api-modernization-test-env-20261029")
UPLOAD = RUNTIME / "product-query-scaling-test-uploads"
EMPTY_CWD = RUNTIME / "product-query-scaling-empty-test"
EVIDENCE = RUNTIME / "private-product-document-plans-20261030"
CEILING = 256 * 1024 * 1024
BASELINE_SHA = "054f2c99deba32c25459f68688e5f29cfa4b83f8b3ec0bda2635c844620165c2"

# Shared safety predicate runs before pytest/application/baseline imports.
error = partner_test_safety_error(os.environ, flag=FLAG)
if os.environ.get(FLAG) != "1" and __name__ != "__main__":
    import pytest
    pytest.skip("Opt in with RUN_PRODUCT_DOCUMENT_QUERY_PLANS_TESTS=1", allow_module_level=True)
if error:
    raise RuntimeError("Refusing document plans: " + error)
if any(os.environ.get(key) != TARGET for key in ("TEST_DATABASE_URL", "DATABASE_URL")):
    raise RuntimeError("Refusing document plans: both exact canonical owned URIs required")
if (os.environ.get("APP_ENV") != "test" or os.environ.get("UPLOAD_DIR") != str(UPLOAD)
        or any(os.environ.get(key) != "1" for key in (
            "RUN_PRODUCT_QUERY_SCALING_TESTS", "RUN_PARTNER_RESOURCE_TESTS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD"))
        or Path.cwd() != EMPTY_CWD or any(EMPTY_CWD.iterdir())):
    raise RuntimeError("Refusing document plans: explicit flags/test upload/empty cwd required")

import hashlib
if hashlib.sha256((SERVER / "tests/test_product_query_scaling.py").read_bytes()).hexdigest() != BASELINE_SHA:
    raise RuntimeError("Refusing document plans: baseline helper source changed")


if __name__ == "__main__":
    import asyncio
    import json
    import signal

    if sys.argv[1:] != ["--execute-approved-document-plans"]:
        raise RuntimeError("Separate coordinator document-plan SQL grant required")
    signal.signal(signal.SIGALRM, lambda *_: sys.exit("270s runner bound exceeded; attempt own teardown"))
    signal.alarm(270)

    async def preflight():
        import asyncpg
        if any(os.environ.get(key) != TARGET for key in ("TEST_DATABASE_URL", "DATABASE_URL")):
            raise RuntimeError("Owned URI changed before connect")
        EVIDENCE.mkdir(mode=0o700, exist_ok=True)
        if any((EVIDENCE / name).exists() for name in ("preflight.json", "results.xml", "http-samples.jsonl",
                "safe-summary.json", "count-statement.json", "page-statement.json", "count-plan.json", "page-plan.json")):
            raise RuntimeError("Refusing to overwrite prior document-plan evidence")
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


from contextlib import contextmanager
import json
import time

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

# Import the module as a helper namespace, never its parametrized test function.
# Its exact DB/cwd/upload guards and transaction-local timeouts remain intact.
from tests import test_product_query_scaling as baseline
from tests.test_partner_resource_query_budget import budget, signing_pem

pytestmark = pytest.mark.asyncio(loop_scope="session")
SCALE = 5000


def private_json(name, value):
    with (EVIDENCE / name).open("x") as output:
        json.dump(value, output, sort_keys=True, indent=2, default=str)
        output.write("\n")


@contextmanager
def observe(engine):
    value = {"sql_count": 0, "document_hydrated": 0, "domain": [], "id_validation": 0}

    def capture(conn, cursor, sql, parameters, context, executemany):
        value["sql_count"] += 1
        statement = getattr(getattr(context, "compiled", None), "statement", None)
        if not getattr(statement, "is_select", False):
            return
        sources = statement.get_final_froms()
        if len(sources) != 1 or getattr(sources[0], "name", None) != "doc_cards":
            return
        normalized = " ".join(sql.lower().replace('"', '').split())
        entity = any(getattr(getattr(item.get("expr"), "__table__", None), "name", None) == "doc_cards"
            for item in getattr(statement, "column_descriptions", []))
        kind = ("count" if normalized.startswith("select count(") else "page" if entity
            and " order by " in normalized and " limit " in normalized else "detail" if entity else None)
        if kind is None:
            value["id_validation"] += 1
            return
        assert not executemany
        assert "doc_cards.company_id = " in normalized and "doc_access_grants" in normalized
        assert "denied_permissions" in normalized and "not (exists" in normalized
        value["domain"].append({"kind": kind, "sql": sql, "parameters": tuple(parameters),
            "sql_sha256": hashlib.sha256(normalized.encode()).hexdigest()})

    def hydrate(session, row):
        if row.__tablename__ == "doc_cards":
            value["document_hydrated"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    event.listen(Session, "loaded_as_persistent", hydrate)
    started = time.perf_counter()
    try:
        yield value
    finally:
        value["http_wall_seconds"] = time.perf_counter() - started
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        event.remove(Session, "loaded_as_persistent", hydrate)


async def request(b, phase, name, path, *, params=None):
    with observe(b.engine) as seen:
        response = await b.http.get(path, params=params)
    # Safe fields only: no IDs, raw SQL, binds, Bearer credentials or cursors.
    sample = {"phase": phase, "case": name, "status": response.status_code,
        "response_bytes": len(response.content), "sql_count": seen["sql_count"],
        "document_hydrated": seen["document_hydrated"], "id_validation": seen["id_validation"],
        "domain_kinds": [item["kind"] for item in seen["domain"]],
        "http_wall_seconds": seen["http_wall_seconds"]}
    with (EVIDENCE / "http-samples.jsonl").open("a") as output:
        output.write(json.dumps(sample, sort_keys=True) + "\n")
    return response, seen


async def golden(b, d, phase):
    ids = baseline.expected(d, "documents", False, False)
    indexes = {str(row.id): i for i, row in enumerate(d.rows["documents"])}
    assert len(ids) == 2000
    first, seen = await request(b, phase, "page200", "/documents", params={"q": "Scaling", "pageSize": 200})
    assert first.status_code == 200
    page = first.json()
    assert page["total"] == len(ids) and [row["id"] for row in page["items"]] == ids[:200]
    assert page["nextCursor"] and seen["document_hydrated"] == 201
    assert [item["kind"] for item in seen["domain"]] == ["count", "page"]
    for item in page["items"]:
        i = indexes[item["id"]]
        assert item["objectId"] == d.rows["objects"][i].id
        assert item["counterpartyId"] == (str(d.rows["documents"][i].counterparty_id)
            if d.labels[i]["party_visible"] else None)
    second, second_seen = await request(b, phase, "cursor200", "/documents", params={
        "q": "Scaling", "pageSize": 200, "cursor": page["nextCursor"]})
    assert second.status_code == 200 and second.json()["total"] == 2000
    assert [row["id"] for row in second.json()["items"]] == ids[200:400]
    assert second_seen["document_hydrated"] == 201 and second.json()["nextCursor"]
    detail, detail_seen = await request(b, phase, "positive-detail", "/documents/" + ids[0])
    assert detail.status_code == 200 and detail_seen["document_hydrated"] == 1
    assert all(detail.json()[key] == value for key, value in page["items"][0].items())
    for name, identifier in (("tenant", str(b.foreign["documents"].id)),
            ("private", str(d.rows["documents"][2].id)), ("deny", str(d.rows["documents"][3].id)),
            ("strict", str(d.rows["documents"][4].id))):
        denied, denied_seen = await request(b, phase, name, "/documents/" + identifier)
        assert denied.status_code == 404 and denied_seen["document_hydrated"] == 0
    # Restore synthetic user/family state after the real machine control.
    original = [(b.grant, {key: getattr(b.grant, key) for key in ("kind", "user_id", "scopes")}),
        (b.family, {key: getattr(b.family, key) for key in ("token_version", "auth_time", "expires_at")}),
        (b.token, {key: getattr(b.token, key) for key in ("access_hash", "scope", "expires_at")}),
        (b.member, {key: getattr(b.member, key) for key in ("object_scope", "own_organization_id")})]
    payload, raw, header = dict(b.payload), b.raw, b.http.headers["Authorization"]
    try:
        await baseline.policy(b, d, False, True)
        denied, denied_seen = await request(b, phase, "service-denied", "/documents", params={"pageSize": 200})
        assert denied.status_code == 403 and denied_seen["document_hydrated"] == 0
        assert denied_seen["domain"] == []
    finally:
        for row, attributes in original:
            for key, value in attributes.items():
                setattr(row, key, value)
        b.payload.clear()
        b.payload.update(payload)
        b.raw = raw
        await b.db.commit()
        b.http.headers["Authorization"] = header
    return page, seen["domain"]


def safe_plan(kind, statement, value):
    document = value[0]
    nodes = []

    def walk(node, depth=0):
        allowed = ("Node Type", "Relation Name", "Actual Rows", "Actual Loops", "Plan Rows",
            "Actual Startup Time", "Actual Total Time",
            "Rows Removed by Filter", "Shared Hit Blocks", "Shared Read Blocks",
            "Shared Dirtied Blocks", "Shared Written Blocks", "Temp Read Blocks", "Temp Written Blocks")
        nodes.append({"depth": depth, **{key: node[key] for key in allowed if key in node}})
        for child in node.get("Plans", []):
            walk(child, depth + 1)

    walk(document["Plan"])
    assert len(nodes) <= 128, "Bounded public plan summary exceeded; retain raw private plan"
    return {"kind": kind, "sql_sha256": statement["sql_sha256"],
        "plan_sha256": hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(),
        "planning_ms": document["Planning Time"], "execution_ms": document["Execution Time"],
        "root_actual_rows": document["Plan"]["Actual Rows"], "nodes": nodes}


@pytest.mark.asyncio(loop_scope="session")
async def test_actual_document_count_and_page_plans(budget, record_property):
    b = budget
    d = await baseline.dataset(b, SCALE)
    await baseline.policy(b, d, False, False)
    before, statements = await golden(b, d, "before")
    assert [item["kind"] for item in statements] == ["count", "page"]
    for item in statements:
        private_json(item["kind"] + "-statement.json", item)
    # Exact original driver SQL + typed original bind tuple; no literalization,
    # manual predicate reconstruction, Query override or planner configuration.
    assert all(os.environ.get(key) == TARGET for key in ("TEST_DATABASE_URL", "DATABASE_URL"))
    assert b.engine.url.render_as_string(hide_password=False) == TARGET
    plans = []
    async with b.engine.connect() as connection:
        async with connection.begin():
            await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            assert await connection.scalar(text("SELECT current_setting('transaction_read_only')")) == "on"
            for item in statements:
                result = await connection.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + item["sql"], item["parameters"])
                value = result.scalar_one()
                if isinstance(value, str):
                    value = json.loads(value)
                private_json(item["kind"] + "-plan.json", value)
                plan = safe_plan(item["kind"], item, value)
                assert plan["root_actual_rows"] == (1 if item["kind"] == "count" else 201)
                plans.append(plan)
    after, after_statements = await golden(b, d, "after")
    assert after == before
    assert [(item["sql"], item["parameters"]) for item in after_statements] == [
        (item["sql"], item["parameters"]) for item in statements]
    summary = {"scale": SCALE, "http_samples": 16, "explain_count": 2, "read_only": True,
        "visible_total": 2000, "response_rows": 200, "hydrated_page_rows": 201,
        "database_bytes_after_dataset": d.bytes, "database_bytes_after_queries": await baseline.database_size(b.db),
        "plans": plans}
    private_json("safe-summary.json", summary)
    record_property("product_document_query_plans", json.dumps(summary, sort_keys=True))
