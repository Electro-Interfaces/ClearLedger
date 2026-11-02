"""Opt-in PostgreSQL contract for aliases recorded by supported location commands."""
import asyncio
from datetime import datetime
import json
import os
import uuid

import pytest
from sqlalchemy import select, text

from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_LOCATION_NUMBER_HISTORY_TESTS") != "1":
    pytest.skip("Opt in with RUN_LOCATION_NUMBER_HISTORY_TESTS=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag="RUN_LOCATION_NUMBER_HISTORY_TESTS"):
    raise RuntimeError(error)

from tests.test_location_commands import world, mutate, native_payload
from app.models import AuditEvent, ServiceLocation
from app.services import location_commands, space_projection
from app.services.session_scope import station_locations_sql
from app.services.stations_normalize import build_station_index


def aliases(metadata):
    return [entry["было"] for entry in metadata["numberHistory"]]


def code_aliases(metadata):
    return [entry["old"] for entry in metadata.get("identifierHistory", []) if entry["domain"] == "code"]


async def persisted(w):
    async with w.factory() as session:
        return await session.get(ServiceLocation, w.locations[0].id)


@pytest.mark.parametrize("path", ["native", "upsert", "registry"])
async def test_allowed_rename_records_old_alias(world, path):
    w = world
    response = await mutate(w, path, {"code": "new-code"})
    assert response.status_code == 200, response.text
    row = await persisted(w)
    assert aliases(row.extra_metadata) == ["old-0"]
    assert code_aliases(row.extra_metadata) == ["code-0"]
    entry = row.extra_metadata["identifierHistory"][-1]
    assert entry["field"] == "code"
    assert entry["domain"] == "code" and entry["new"] == "new-code"
    assert entry["source"] == ("registry.objects" if path == "registry" else "native.locations")
    assert entry["actor"] == str(w.user.id)
    assert datetime.fromisoformat(entry["recordedAt"]).utcoffset().total_seconds() == 0
    assert not {"validFrom", "validTo", "email", "name"} & entry.keys()


@pytest.mark.parametrize("path,field", [("native", "code"), ("upsert", "code"),
    ("registry", "code"), ("native", "number"), ("upsert", "number")])
async def test_old_number_cannot_be_claimed_after_allowed_rename(world, path, field):
    w = world
    changes = {"metadata": {"number": "new-number"}} if field == "number" else {"code": "new-code"}
    old = "number-0" if field == "number" else "code-0"
    response = await mutate(w, path, changes)
    assert response.status_code == 200, response.text
    response = await w.client.post("/api/locations", json=native_payload(
        w, id=uuid.uuid4().hex, code="claim-old", metadata={"number": old}))
    assert response.status_code == 409, response.text
    response = await mutate(w, "native", {"metadata": {"number": old}})
    assert response.status_code == 409, response.text


async def test_registry_metadata_remains_outside_http_patch_contract(world):
    response = await mutate(world, "registry", {"metadata": {"number": "ignored"}})
    assert response.status_code == 200, response.text
    row = await persisted(world)
    assert row.station_number == "number-0" and row.extra_metadata == world.locations[0].extra_metadata


async def test_actual_legacy_readers_find_old_number_after_rename(world):
    w = world
    response = await mutate(w, "native", {"type": "ev_charging"})
    assert response.status_code == 200, response.text
    async with w.factory() as session:
        assert (await build_station_index(session, w.cid))["number-0"] == w.locations[0].id
        assert await session.scalar(text("SELECT " + station_locations_sql()),
            {"stations": ["number-0"], "company_id": str(w.cid)}) == [w.locations[0].id]
    response = await mutate(w, "native", {"metadata": {"number": "new-number"}})
    assert response.status_code == 200, response.text
    async with w.factory() as session:
        index = await build_station_index(session, w.cid)
        sql = "SELECT " + station_locations_sql()
        matched = await session.scalar(text(sql), {"stations": ["number-0"], "company_id": str(w.cid)})
    assert (index.get("number-0"), matched) == (w.locations[0].id, [w.locations[0].id])


@pytest.mark.parametrize("legacy_value,canonical", [(0, "0"), (" old ", "old")])
async def test_legacy_noncanonical_alias_gets_additive_searchable_string_only_on_departure(world, legacy_value, canonical):
    w = world
    legacy = [{"было": legacy_value, "unknown": {"keep": [None, 1]}}]
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[0].id)
        loc.type, loc.station_number = "ev_charging", canonical
        loc.extra_metadata = {"number": canonical, "numberHistory": legacy}
        await session.commit()
    response = await mutate(w, "native", {"name": "No history repair"})
    assert response.status_code == 200, response.text
    assert (await persisted(w)).extra_metadata["numberHistory"] == legacy
    async with w.factory() as session:
        assert (await build_station_index(session, w.cid))[canonical] == w.locations[0].id
        assert await session.scalar(text("SELECT " + station_locations_sql()),
            {"stations": [canonical], "company_id": str(w.cid)}) == [w.locations[0].id]
        result = await location_commands.update(session, w.cid, w.locations[0].id,
            {"metadata": {"number": "replacement"}})
        assert result.location.extra_metadata["numberHistory"][0] == legacy[0]
        assert aliases(result.location.extra_metadata) == [legacy_value, canonical]
        await session.flush()
        await session.rollback()
    row = await persisted(w)
    assert row.station_number == canonical and row.extra_metadata["numberHistory"] == legacy
    for _ in range(2):
        response = await mutate(w, "native", {"metadata": {"number": "replacement"}})
        assert response.status_code == 200, response.text
    row = await persisted(w)
    assert row.extra_metadata["numberHistory"][0] == legacy[0]
    assert aliases(row.extra_metadata) == [legacy_value, canonical]
    async with w.factory() as session:
        assert (await build_station_index(session, w.cid))[canonical] == w.locations[0].id
        assert await session.scalar(text("SELECT " + station_locations_sql()),
            {"stations": [canonical], "company_id": str(w.cid)}) == [w.locations[0].id]


@pytest.mark.parametrize("column,snapshot,expected", [
    ("column-old", "snapshot-old", ["column-old", "snapshot-old"]),
    ("0", 0, ["0"]), (None, 0, ["0"]), ("same", "same", ["same"]),
    ("column-old", None, ["column-old"]),
])
async def test_divergent_numbers_and_zero_are_preserved_without_duplicates(world, column, snapshot, expected):
    w = world
    legacy = [{"было": "legacy", "source": "old-import", "unknown": {"nested": [1, None]}},
              {"other": "dict without alias remains untouched"}]
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[0].id)
        loc.station_number = column
        loc.extra_metadata = {"number": snapshot, "numberHistory": legacy,
            "asuimRaw": {"number": "immutable-raw"}, "nameHistory": [{"было": "Old name"}],
            "hubexAssetId": "manual-link", "source": {"external": "raw-source"}}
        await session.commit()
    response = await mutate(w, "native", {"metadata": {"number": "replacement",
        "numberHistory": [{"было": "forged"}], "asuimRaw": {"number": "forged"}}})
    assert response.status_code == 200, response.text
    row = await persisted(w)
    md = row.extra_metadata
    assert md["numberHistory"][:2] == legacy
    assert aliases({"numberHistory": md["numberHistory"][2:]}) == expected
    assert row.station_number == md["number"] == "replacement"
    assert md["asuimRaw"] == {"number": "immutable-raw"}
    assert md["source"] == {"external": "raw-source"}
    assert md["nameHistory"] == [{"было": "Old name"}]
    assert md["hubexAssetId"] == "manual-link"
    assert row.source_bindings == [{"sourceId": "raw-source"}]


@pytest.mark.parametrize("incoming", [None, {"number": None}, {"number": ""}])
async def test_explicit_number_clear_records_both_outgoing_values(world, incoming):
    w = world
    response = await mutate(w, "native", {"metadata": incoming})
    assert response.status_code == 200, response.text
    row = await persisted(w)
    assert row.station_number is None
    assert aliases(row.extra_metadata) == ["old-0", "number-0"]


@pytest.mark.parametrize("changes", [{}, {"name": "Human display name"},
    {"code": "code-0"}, {"metadata": {"number": "number-0"}},
    {"metadata": {"comment": "partial edit"}}, {"address": None}])
async def test_noop_name_only_and_omitted_number_never_append(world, changes):
    response = await mutate(world, "native", changes)
    assert response.status_code == 200, response.text
    row = await persisted(world)
    assert aliases(row.extra_metadata) == ["old-0"]
    assert row.station_number == "number-0"
    assert row.extra_metadata["number"] == "number-0"


@pytest.mark.parametrize("path", ["native", "registry"])
async def test_repeat_does_not_duplicate_history_audit_or_projection(world, path):
    w = world
    changes = {"code": "new-code"}
    for _ in range(2):
        response = await mutate(w, path, changes)
        assert response.status_code == 200, response.text
    row = await persisted(w)
    assert aliases(row.extra_metadata) == ["old-0"]
    assert code_aliases(row.extra_metadata) == ["code-0"]
    if path == "registry":
        assert w.projections == []
        async with w.factory() as session:
            audits = (await session.scalars(select(AuditEvent).where(AuditEvent.company_id == w.cid))).all()
        assert len(audits) == 1
        details = json.loads(audits[0].details)
        assert details["code"] == {"from": "code-0", "to": "new-code"}
        assert details["extra_metadata"]["from"] == w.locations[0].extra_metadata
        assert aliases(details["extra_metadata"]["to"]) == ["old-0"]
        assert code_aliases(details["extra_metadata"]["to"]) == ["code-0"]
    else:
        assert w.projections == [(w.cid, w.locations[0].id, "new-code")] * 2


@pytest.mark.parametrize("history", [None, [], "absent"])
async def test_code_change_preserves_absent_or_empty_number_history(world, history):
    w = world
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[0].id)
        loc.extra_metadata = {"number": "number-0"}
        if history != "absent":
            loc.extra_metadata = {**loc.extra_metadata, "numberHistory": history}
        await session.commit()
    response = await mutate(w, "native", {"code": "new-code"})
    assert response.status_code == 200, response.text
    md = (await persisted(w)).extra_metadata
    assert code_aliases(md) == ["code-0"]
    if history == "absent":
        assert "numberHistory" not in md
    else:
        assert md["numberHistory"] == history


@pytest.mark.parametrize("history", [{"было": "old"}, "old", 7, False, [None], ["old"], [7]])
async def test_malformed_legacy_history_requires_reconciliation_only_on_rename(world, history):
    w = world
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[0].id)
        loc.extra_metadata = {"number": "number-0", "numberHistory": history}
        await session.commit()
    response = await mutate(w, "native", {"name": "Safe display edit"})
    assert response.status_code == 200, response.text
    assert (await persisted(w)).extra_metadata["numberHistory"] == history
    for changes in ({}, {"address": None}, {"code": "code-0"}):
        response = await mutate(w, "native", changes)
        assert response.status_code == 200, response.text
        assert (await persisted(w)).extra_metadata["numberHistory"] == history
    response = await mutate(w, "native", {"code": "requires-reconciliation"})
    assert response.status_code == 409, response.text
    row = await persisted(w)
    assert row.code == "code-0" and row.station_number == "number-0"
    assert row.extra_metadata["numberHistory"] == history


async def test_direct_command_rollback_is_atomic_and_snapshots_are_not_mutated(world):
    w = world
    async with w.factory() as session:
        before = await session.get(ServiceLocation, w.locations[0].id)
        original_md, original_history = before.extra_metadata, before.extra_metadata["numberHistory"]
        mutation = await location_commands.update(session, w.cid, before.id,
            {"code": "temporary", "metadata": {"number": "temporary-number"}})
        assert original_md == w.locations[0].extra_metadata
        assert original_history == [{"было": "old-0"}]
        assert set(mutation.changes) == {"code", "station_number", "extra_metadata"}
        assert mutation.changes["extra_metadata"]["from"] == original_md
        assert aliases(mutation.changes["extra_metadata"]["to"]) == ["old-0", "number-0"]
        assert code_aliases(mutation.changes["extra_metadata"]["to"]) == ["code-0"]
        entry = mutation.location.extra_metadata["numberHistory"][-1]
        assert entry["actor"] is None and entry["source"] == "unknown"
        await session.flush()
        observer = await persisted(w)
        assert observer.code == "code-0" and observer.extra_metadata == original_md
        await session.rollback()
    row = await persisted(w)
    assert row.code == "code-0" and row.station_number == "number-0" and row.extra_metadata == original_md


async def test_projection_failure_rolls_back_fields_and_alias(world, monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic projection failure after flush")
    monkeypatch.setattr(space_projection, "project_object", fail)
    response = await mutate(world, "native", {"code": "temporary", "metadata": {"number": "temporary"}})
    assert response.status_code == 500
    row = await persisted(world)
    assert row.code == "code-0" and row.station_number == "number-0"
    assert row.extra_metadata == world.locations[0].extra_metadata


async def test_concurrent_edits_reload_stale_row_and_keep_every_alias(world):
    w = world
    async with w.factory() as first, w.factory() as second:
        stale = await second.get(ServiceLocation, w.locations[0].id)
        await location_commands.update(first, w.cid, stale.id, {"metadata": {"number": "intermediate"}})
        await first.flush()
        pending = asyncio.create_task(location_commands.update(second, w.cid, stale.id,
            {"metadata": {"number": "final"}}))
        try:
            await asyncio.sleep(0.05)
            assert not pending.done()
            await first.commit()
            await asyncio.wait_for(pending, timeout=5)
            await second.commit()
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    row = await persisted(w)
    assert row.station_number == "final"
    assert aliases(row.extra_metadata) == ["old-0", "number-0", "intermediate"]


async def test_initial_create_does_not_invent_history_and_existing_ids_stay_opaque(world):
    w = world
    identifier = "deterministic-id-unchanged"
    response = await w.client.post("/api/locations", json=native_payload(
        w, id=identifier, code="initial-code", metadata={"number": 0}))
    assert response.status_code == 200, response.text
    assert response.json()["metadata"] == {"number": 0}
    assert response.json()["passport"]["stationNumber"] == "0"
    response = await w.client.patch("/api/locations/" + identifier, json={"code": "next-code"})
    assert response.status_code == 200, response.text
    assert response.json()["id"] == identifier
    assert "numberHistory" not in response.json()["metadata"]
    assert code_aliases(response.json()["metadata"]) == ["initial-code"]


async def test_preexisting_double_station_number_is_not_reconciled_or_renumbered(world):
    from datetime import datetime, timedelta, timezone

    w = world
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[1].id)
        loc.station_number = "number-0"
        await session.commit()
    started = datetime.now(timezone.utc)
    response = await mutate(w, "native", {"name": "Display name"})
    finished = datetime.now(timezone.utc)
    assert response.status_code == 200, response.text
    async with w.factory() as session:
        rows = (await session.scalars(select(ServiceLocation).where(ServiceLocation.company_id == w.cid))).all()
    assert {r.id for r in rows if r.station_number == "number-0"} == {r.id for r in w.locations}
    metadata = (await persisted(w)).extra_metadata
    assert {k: v for k, v in metadata.items() if k != "fieldProvenance"} == w.locations[0].extra_metadata
    provenance = metadata["fieldProvenance"]
    assert set(provenance) == {"name"}
    marker = provenance["name"]
    assert set(marker) == {"authority", "actor", "source", "recordedAt"}
    assert marker["authority"] == "manual"
    assert marker["actor"] == str(w.user.id) and marker["source"] == "native.locations"
    recorded = datetime.fromisoformat(marker["recordedAt"])
    assert recorded.utcoffset() == timedelta(0) and started <= recorded <= finished
