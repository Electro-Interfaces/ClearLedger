"""Owned synthetic product-query baseline; see PRODUCT_QUERY_SCALING_20261030.md.

Run this file as the guarded runner only after the coordinator grants the SQL
window. No verifier/ACL/listener substitution, latency threshold or EXPLAIN.
"""
import os
from pathlib import Path
import sys

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_PRODUCT_QUERY_SCALING_TESTS"
TARGET = "postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_product_query_scaling_test"
RUNTIME = Path("/srv/projects/api-modernization-test-env-20261029")
UPLOAD = RUNTIME / "product-query-scaling-test-uploads"
EMPTY_CWD = RUNTIME / "product-query-scaling-empty-test"
EVIDENCE = RUNTIME / "private-product-query-scaling-20261030"
CEILING = 256 * 1024 * 1024

# BEFORE pytest/application imports; the __main__ runner repeats these checks
# before its first connection and before importing pytest/conftest.
error = partner_test_safety_error(os.environ, flag=FLAG)
if os.environ.get(FLAG) != "1" and __name__ != "__main__":
    import pytest
    pytest.skip("Opt in with RUN_PRODUCT_QUERY_SCALING_TESTS=1", allow_module_level=True)
if error:
    raise RuntimeError("Refusing product scaling run: " + error)
if any(os.environ.get(key) != TARGET for key in ("TEST_DATABASE_URL", "DATABASE_URL")):
    raise RuntimeError("Refusing product scaling run: both exact owned URIs required")
if (os.environ.get("APP_ENV") != "test" or os.environ.get("UPLOAD_DIR") != str(UPLOAD)
        or os.environ.get("RUN_PARTNER_RESOURCE_TESTS") != "1"
        or os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1"
        or Path.cwd() != EMPTY_CWD or any(EMPTY_CWD.iterdir())):
    raise RuntimeError("Refusing product scaling run: explicit flags/test upload/empty cwd required")


if __name__ == "__main__":
    import asyncio
    import json
    import signal

    if sys.argv[1:] != ["--execute-approved-baseline"]:
        raise RuntimeError("Explicit coordinator SQL grant required before executing this runner")
    # Includes imports, schema setup, seeding, requests and teardown; no retries.
    signal.signal(signal.SIGALRM, lambda *_: sys.exit("1150s runner bound exceeded; attempt own teardown"))
    signal.alarm(1150)

    async def preflight():
        import asyncpg
        if any(os.environ.get(key) != TARGET for key in ("TEST_DATABASE_URL", "DATABASE_URL")):
            raise RuntimeError("Owned URI changed before connect")
        connection = await asyncpg.connect(TARGET.replace("postgresql+asyncpg:", "postgresql:", 1),
            timeout=5, server_settings={"statement_timeout": "15000", "lock_timeout": "1000"})
        try:
            row = await connection.fetchrow("SELECT current_database() AS db, current_user AS usr, "
                "current_setting('server_version_num')::int AS version, "
                "current_setting('max_locks_per_transaction')::int AS maxlocks, "
                "pg_database_size(current_database()) AS bytes, "
                "(SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' "
                "AND pid <> pg_backend_pid()) AS other_clients")
            value = dict(row)
            if (value["db"] != "api_product_query_scaling_test" or value["usr"] != "clearledger"
                    or not 160000 <= value["version"] < 170000 or value["maxlocks"] != 64
                    or value["other_clients"] != 0 or value["bytes"] >= CEILING):
                raise RuntimeError("Synthetic preflight refused: " + json.dumps(value, sort_keys=True))
            EVIDENCE.mkdir(mode=0o700, exist_ok=True)
            (EVIDENCE / "preflight.json").write_text(json.dumps(value, sort_keys=True) + "\n")
        finally:
            await connection.close()

    asyncio.run(preflight())
    # Guard already passed before pytest can load destructive conftest.
    import pytest
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), "-c", str(SERVER / "pytest.ini"),
        "-p", "pytest_asyncio.plugin", "-p", "no:cacheprovider", "-q", "-ra", "--maxfail=1",
        "--confcutdir=" + str(SERVER), "--basetemp=" + str(EVIDENCE / "pytest-test-tmp"),
        "-o", "junit_family=legacy", "--junitxml=" + str(EVIDENCE / "results.xml")]))


from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
import tracemalloc
from types import SimpleNamespace
import uuid

import jwt
import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.models import Contract, ContractLocation, DocAccessGrant, DocCard, Organization, ServiceLocation
from app.models_partner import PartnerResourceItem, PartnerResourceScope
from app.services import partner_identity as identity
from tests.conftest import _test_engine
from tests.test_partner_resource_query_budget import SCOPES, budget, profiles, signing_pem

pytestmark = pytest.mark.asyncio(loop_scope="session")
SCALES = (100, 1000, 5000)
RESOURCES = ("objects", "contracts", "documents")
TABLES = {"objects": "service_locations", "contracts": "contracts", "documents": "doc_cards"}
PAGES = (1, 50, 200)


def transaction_limits(connection):
    # Transaction-local only, including shared conftest DDL; retain all listeners.
    connection.exec_driver_sql("SET LOCAL statement_timeout = '15000ms'")
    connection.exec_driver_sql("SET LOCAL lock_timeout = '1000ms'")


event.listen(_test_engine.sync_engine, "begin", transaction_limits)


async def database_size(db):
    size = await db.scalar(text("SELECT pg_database_size(current_database())"))
    assert size < CEILING, "Own DB reached 256MiB; stop before next scale (no other DB cleanup)"
    return size


async def dataset(b, n):
    """N labelled triples, real ORM inserts, bounded payloads, no file blobs."""
    await database_size(b.db)  # After shared seed and before each new scale.
    cid = b.company.id
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-product-query-scaling:{n}")
    ident = lambda kind, i: uuid.uuid5(namespace, f"scaling:{kind}:{i}")
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    org_a = b.data["contracts"][0].organization_id
    org_b = Organization(id=ident("organization", 0), company_id=cid,
        name="Synthetic scaling second organization", inn="9999999998")
    b.db.add(org_b)
    await b.db.flush()
    rows = {key: [] for key in RESOURCES}
    labels = []
    for i in range(n):
        location = ServiceLocation(id=ident("object", i).hex, company_id=cid,
            code=f"S-{i:06}", name=f"Scaling object {i:06}", type="ezs", created_at=at)
        party = b.data["counterparties"][(i // 2) % 2].id
        organization = org_a if i % 2 == 0 else org_b.id
        contract = Contract(id=ident("contract", i), company_id=cid,
            number=f"Scaling contract {i:06}", date="2026-01-01", type="service",
            counterparty_id=party, organization_id=organization,
            scope_type="locations", created_at=at)
        document = DocCard(id=ident("document", i), company_id=cid,
            kind_id=b.data["documents"][0].kind_id, title=f"Scaling document {i:06}",
            confidentiality="company" if i % 5 in (0, 3) else "strict" if i % 5 == 4 else "private",
            author_id=None, object_id=location.id, organization_id=organization,
            counterparty_id=party, created_at=at)
        for key, row in zip(RESOURCES, (location, contract, document)):
            rows[key].append(row)
        labels.append(dict(index=i, member=i % 3 != 0, organization=i % 2 == 0,
            resource=i % 4 != 0, object_grant=i % 7 != 0, doc_read=i % 5 in (0, 1),
            party_visible=(i // 2) % 2 == 0))
    b.db.add_all(rows["objects"])
    await b.db.flush()
    b.db.add_all(rows["contracts"] + rows["documents"])
    await b.db.flush()
    for i in range(n):
        b.db.add(ContractLocation(id=ident("location-link", i), company_id=cid,
            contract_id=rows["contracts"][i].id, location_id=rows["objects"][i].id))
        if i % 5 in (1, 3):
            b.db.add(DocAccessGrant(id=ident("acl", i), company_id=cid,
                scope_type="doc", scope_id=rows["documents"][i].id,
                subject_type="user", subject_id=b.user.id,
                permissions=["read"] if i % 5 == 1 else [],
                denied_permissions=["read"] if i % 5 == 3 else []))
    # Same searchable prefix + earlier timestamp: a tenant leak affects count
    # and page 1 even at the largest scale. The foreign row remains foreign.
    for key, attribute in (("objects", "name"), ("contracts", "number"), ("documents", "title")):
        setattr(b.foreign[key], attribute, "Scaling foreign negative control")
        b.foreign[key].created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    await b.db.commit()
    size = await database_size(b.db)
    return SimpleNamespace(rows=rows, labels=labels, org_a=org_a, bytes=size)


async def policy(b, d, restricted, machine):
    await database_size(b.db)
    # Only synthetic persisted/token claims change. Keep real verifier expiry
    # checks and the actual clock; cover the entire 20-minute outer bound.
    expires = identity.now() + timedelta(minutes=25)
    b.family.expires_at = b.token.expires_at = expires
    b.payload.update(iat=int(time.time()), exp=int(expires.timestamp()))
    await profiles(b)  # Real stored ALL profiles; no verifier override.
    selections = {"counterparties": [b.data["counterparties"][0].id]}
    if restricted:
        selections.update({key: [row.id for row, label in zip(d.rows[key], d.labels)
            if label["object_grant" if key == "objects" else "resource"]] for key in RESOURCES})
    for kind, ids in selections.items():
        scope = await b.db.get(PartnerResourceScope, (b.installation.id, kind))
        scope.mode = "SET"
        column = identity.RESOURCE_MODELS[kind][1]
        b.db.add_all([PartnerResourceItem(installation_id=b.installation.id, kind=kind,
            **{column: value}) for value in ids])
    # Membership applies to user identities only. Service profiles deliberately
    # run while restrictive user membership remains stored, proving that it is
    # not borrowed by a machine identity.
    b.member.object_scope = ([row.id for row, label in zip(d.rows["objects"], d.labels)
        if label["member"]] if restricted or machine else None)
    b.member.own_organization_id = d.org_a if restricted or machine else None
    scopes = sorted(SCOPES)
    if machine:
        scopes = sorted(set(scopes) - {"openid", "documents:read"})
        b.grant.kind, b.grant.user_id = "machine", None
        b.family.token_version = b.family.auth_time = None
        b.payload["sub"] = "client:" + b.client.id
    b.grant.scopes = scopes
    b.payload["scope"] = " ".join(scopes)
    b.raw = jwt.encode(b.payload, b.signing_pem, algorithm="RS256",
        headers={"typ": "at+jwt", "kid": identity.settings.partner_oauth_kid})
    b.token.access_hash, b.token.scope = identity.digest(b.raw), b.payload["scope"]
    await b.db.commit()
    b.http.headers["Authorization"] = "Bearer " + b.raw


@contextmanager
def observations(engine):
    statements, loaded = [], Counter()

    def capture(conn, cursor, sql, parameters, context, executemany):
        statement = getattr(getattr(context, "compiled", None), "statement", None)
        sources = statement.get_final_froms() if getattr(statement, "is_select", False) else []
        table = getattr(sources[0], "name", None) if len(sources) == 1 else None
        entity = any(getattr(getattr(item.get("expr"), "__table__", None), "name", None) == table
            for item in getattr(statement, "column_descriptions", []))
        statements.append({"table": table, "sql": " ".join(sql.lower().replace('"', '').split()),
            "entity": entity, "cursor_rows": None})

    def returned(conn, cursor, sql, parameters, context, executemany):
        statements[-1]["cursor_rows"] = cursor.rowcount if cursor.rowcount >= 0 else None

    def hydrate(session, row):
        loaded[row.__tablename__] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    event.listen(engine.sync_engine, "after_cursor_execute", returned)
    event.listen(Session, "loaded_as_persistent", hydrate)
    tracemalloc.start()
    started = time.perf_counter()
    value = {"statements": statements, "hydrated": loaded}
    try:
        yield value
    finally:
        value["wall_seconds"] = time.perf_counter() - started
        value["peak_python_bytes"] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        event.remove(engine.sync_engine, "after_cursor_execute", returned)
        event.remove(Session, "loaded_as_persistent", hydrate)


def expected(d, resource, restricted, machine):
    accepted = []
    for row, label in zip(d.rows[resource], d.labels):
        if resource == "documents" and not label["doc_read"]:
            continue
        if restricted and not label["object_grant" if resource == "objects" else "resource"]:
            continue
        if restricted and not machine and not (label["member"] and label["organization"]):
            continue
        accepted.append(str(row.id))
    return sorted(accepted)  # All triples have equal created_at; UUID/native string tie-break.


def domain_shape(observed, resource, restricted, machine, *, listing):
    table = TABLES[resource]
    selects = [item["sql"] for item in observed["statements"] if item["table"] == table
        and (listing or item["entity"])]
    if listing:
        count = [sql for sql in selects if sql.startswith("select count(")]
        limited = [sql for sql in selects if " order by " in sql and " limit " in sql]
        assert len(count) == len(limited) == 1, selects
        selects = count + limited
        assert " limit " not in count[0]
    else:
        assert len(selects) == 1, selects
    for sql in selects:
        assert f"{table}.company_id = " in sql and " where " in sql
        predicates = sql.split(" where ", 1)[1].split(" order by ", 1)[0]
        if restricted:
            assert f"{table}.id in (" in predicates
            if not machine:
                if resource == "objects":
                    assert predicates.count("service_locations.id in (") >= 2
                if resource in ("objects", "contracts"):
                    assert "contract_locations" in predicates and "exists (select" in predicates
                if resource in ("contracts", "documents"):
                    assert f"{table}.organization_id = " in predicates
        if resource == "documents":
            assert "doc_access_grants" in predicates and "denied_permissions" in predicates
            assert "not (exists" in predicates and "doc_cards.confidentiality = " in predicates


def evidence(observed, response, **case):
    # Keep SQL shapes hashed and parameters/tokens/row IDs out of artifacts.
    sample = {**case, "status": response.status_code, "response_bytes": len(response.content),
        "sql_statements": len(observed["statements"]), "hydrated_rows": dict(observed["hydrated"]),
        "cursor_returned_rows": [item["cursor_rows"] for item in observed["statements"]],
        "sql_shape_sha256": [hashlib.sha256(item["sql"].encode()).hexdigest()
            for item in observed["statements"]],
        "wall_seconds": observed["wall_seconds"], "peak_python_bytes": observed["peak_python_bytes"]}
    # Persist completed samples even when a later assertion aborts this scale;
    # writing is outside the observed request, and never goes into Git.
    with (EVIDENCE / f"samples-scale-{case['scale']}.jsonl").open("a") as output:
        output.write(json.dumps(sample, sort_keys=True) + "\n")
    return sample


@pytest.mark.parametrize("scale", SCALES)
async def test_product_query_scaling(budget, scale, record_property):
    b = budget
    d = await dataset(b, scale)
    samples = []
    for machine, restricted in ((False, False), (False, True), (True, False), (True, True)):
        await policy(b, d, restricted, machine)
        profile = ("service" if machine else "user") + ("-intersection" if restricted else "-all")
        for resource in RESOURCES[:2] if machine else RESOURCES:
            indexes = {str(row.id): index for index, row in enumerate(d.rows[resource])}
            ids = expected(d, resource, restricted, machine)
            assert ids, (scale, resource, profile)
            first_page = None
            for size in PAGES:
                with observations(b.engine) as observed:
                    response = await b.http.get("/" + resource, params={"pageSize": size, "q": "Scaling"})
                assert response.status_code == 200, response.text
                value = response.json()
                assert value["total"] == len(ids)
                assert [item["id"] for item in value["items"]] == ids[:size]
                assert bool(value["nextCursor"]) == (len(ids) > size)
                domain_shape(observed, resource, restricted, machine, listing=True)
                # Hydration includes lookahead; cannot grow with hidden dataset
                # rows. Verifier profile validation selects IDs, not ORM cards.
                assert observed["hydrated"][TABLES[resource]] == min(len(ids), size + 1)
                for item in value["items"]:
                    index = indexes[item["id"]]
                    label = d.labels[index]
                    if resource in ("contracts", "documents"):
                        assert item["counterpartyId"] == (str(d.rows[resource][index].counterparty_id)
                            if label["party_visible"] else None)
                    if resource == "documents":
                        visible = not restricted or label["object_grant"]
                        assert item["objectId"] == (d.rows["objects"][index].id if visible else None)
                samples.append(evidence(observed, response, scale=scale, profile=profile,
                    resource=resource, operation="listing", page_size=size,
                    visible_total=value["total"], response_rows=len(value["items"])))
                if size == 1:
                    first_page = value
            # A bounded second page proves tie-break/cursor behavior at every
            # scale, without turning this suite into an unbounded load test.
            with observations(b.engine) as observed:
                response = await b.http.get("/" + resource, params={"pageSize": 1, "q": "Scaling",
                    "cursor": first_page["nextCursor"]})
            assert response.status_code == 200 and response.json()["total"] == len(ids)
            assert [item["id"] for item in response.json()["items"]] == ids[1:2]
            domain_shape(observed, resource, restricted, machine, listing=True)
            samples.append(evidence(observed, response, scale=scale, profile=profile,
                resource=resource, operation="cursor", page_size=1))
            with observations(b.engine) as observed:
                response = await b.http.get(f"/{resource}/{ids[0]}")
            assert response.status_code == 200 and response.json()["id"] == ids[0]
            assert all(response.json()[key] == value for key, value in first_page["items"][0].items())
            domain_shape(observed, resource, restricted, machine, listing=False)
            samples.append(evidence(observed, response, scale=scale, profile=profile,
                resource=resource, operation="detail", response_rows=1))
            # Foreign detail + independent resource/member/org negatives. Pick
            # a row that passes every other dimension, so each is causal.
            negatives = [(str(b.foreign[resource].id), "tenant")]
            if resource == "documents":
                negatives += [(str(d.rows[resource][i].id), cause)
                    for i, cause in ((2, "private"), (3, "explicit-deny"), (4, "strict"))]
            if restricted:
                axes = ["object_grant" if resource == "objects" else "resource"]
                if not machine:
                    axes += ["member", "organization"]
                for axis in axes:
                    index = next(label["index"] for label in d.labels if not label[axis]
                        and all(label[other] for other in axes if other != axis)
                        and (resource != "documents" or label["doc_read"]))
                    negatives.append((str(d.rows[resource][index].id), axis))
            for identifier, cause in negatives:
                with observations(b.engine) as observed:
                    response = await b.http.get(f"/{resource}/{identifier}")
                assert response.status_code == 404, (cause, response.text)
                assert observed["hydrated"][TABLES[resource]] == 0
                samples.append(evidence(observed, response, scale=scale, profile=profile,
                    resource=resource, operation="negative-detail", cause=cause, response_rows=0))
        if machine:
            with observations(b.engine) as observed:
                response = await b.http.get("/documents", params={"pageSize": 200})
            validation = [item for item in observed["statements"] if item["table"] == "doc_cards"]
            samples.append(evidence(observed, response, scale=scale, profile=profile,
                resource="documents", operation="service-denied", response_rows=0,
                document_id_validation_statements=len(validation)))
            assert response.status_code == 403
            assert observed["hydrated"]["doc_cards"] == 0
            # Stored unused SET profiles are still validated by the real
            # verifier. Permit that scalar tenant/ID check, never a domain
            # COUNT, entity projection or document list/detail query.
            for item in validation:
                assert not item["entity"]
                assert item["sql"].split(" from ", 1)[0] == "select doc_cards.id"
                assert "doc_cards.company_id = " in item["sql"] and "doc_cards.id in (" in item["sql"]
                assert all(fragment not in item["sql"] for fragment in ("count(", " order by ", " limit "))
    # Session-scoped schema teardown belongs to the existing conftest. Each
    # scale has a separate synthetic company, never global DELETE/other DBs.
    record_property("product_query_scaling", json.dumps({"scale": scale,
        "database_bytes_after_dataset": d.bytes, "database_bytes_after_queries": await database_size(b.db),
        "samples": samples}, sort_keys=True))
