"""Frozen Core-only calendar-column contract, reusing unchanged v1 primitives."""
from schema_migrations.revisions.catalog_v1 import (
    columns, constraint_flags, constraints, indexes, normalize_check, relation, require, verify_columns,
)


async def inspect_calendar(conn, contract, owner):
    table = await relation(conn, contract["table"], owner)
    require(table is not None, "calendar_prerequisite")
    oid = table["oid"]
    actual = await columns(conn, oid)
    present = any(row["name"] == contract["managed_column"]["name"] for row in actual)
    expected = contract["legacy_columns"] + ([contract["managed_column"]] if present else [])
    names = verify_columns(actual, expected)
    keys = await constraints(conn, oid)
    managed = [key for key in keys if key["name"] == contract["managed_check"]]
    require(len(managed) == int(present), "calendar_partial_shape")
    if managed:
        key = managed[0]
        require(key["kind"] == "c" and [names.get(n) for n in key["keys"]] == ["protocol_sequence"]
                and normalize_check(key["expression"]) == normalize_check(contract["managed_expression"]),
                "calendar_check")
        constraint_flags(key)
    require(await conn.fetchval("SELECT NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='core' AND c.relname=$1)", contract["managed_check"]), "calendar_reserved_name")
    return {"header": table, "present": present,
            "legacy": {"columns": [row for row in actual if row["name"] != "protocol_sequence"],
                       "constraints": [row for row in keys if row["name"] != contract["managed_check"]],
                       "indexes": await indexes(conn, oid)}}


async def verify_cutover(conn, contract, acknowledgement):
    bound = contract["legacy_sent_before"]
    require(type(acknowledgement) is int and acknowledgement == bound, "legacy_acknowledgement")
    times = await conn.fetchrow("""SELECT extract(epoch FROM pg_catalog.clock_timestamp()) AS current_epoch,
        extract(epoch FROM max(created_at)) AS created_epoch,
        extract(epoch FROM max(updated_at)) AS updated_epoch FROM core.calendar_events""")
    require(times is not None and times["current_epoch"] is not None and times["current_epoch"] < bound
            and all(times[key] is None or times[key] < bound for key in ("created_epoch", "updated_epoch")), "legacy_time_bound")


async def verify_preserved(before, after):
    require(before["header"]["oid"] == after["header"]["oid"]
            and before["legacy"] == after["legacy"], "calendar_legacy_catalog_changed")
