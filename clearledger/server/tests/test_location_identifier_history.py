"""Opt-in PG: technical code history must never become station-number aliases."""
import asyncio
from copy import deepcopy
from datetime import datetime
import json
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_LOCATION_IDENTIFIER_HISTORY_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Opt in with {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)

from tests.test_location_commands import world, mutate, native_payload
from app.models import AuditEvent, ServiceLocation
from app.scope import current_object_scope, install_orm_scope, set_request_scope
from app.services import location_commands, space_projection
from app.services.session_scope import station_locations_sql
from app.services.stations_normalize import build_station_index

CONFLICT = "Номер уже занят текущим или историческим объектом компании"


@pytest.fixture(scope="module", autouse=True)
def real_orm_listener():
    install_orm_scope()


@pytest_asyncio.fixture
async def ev_world(world):
    async with world.factory() as session:
        loc = await session.get(ServiceLocation, world.locations[0].id)
        loc.type = "ev_charging"
        await session.commit()
    return world


async def persisted(w):
    c = ServiceLocation.__table__.c
    async with w.factory() as session:
        return dict((await session.execute(select(c.id, c.type, c.code, c.station_number,
            c.extra_metadata, c.source_bindings).where(c.company_id == w.cid,
            c.id == w.locations[0].id))).mappings().one())


async def readers(w, value):
    async with w.factory() as session:
        index = await build_station_index(session, w.cid)
        ids = await session.scalar(text("SELECT " + station_locations_sql()),
            {"company_id": str(w.cid), "stations": [value]})
        return index.get(value), sorted(ids)


async def ev_mutate(w, path, changes):
    # Native POST is a complete form. Its default type='other' would make a
    # negative index assertion vacuous; preserve the EV positive-control row.
    if path == "upsert":
        changes = {"type": "ev_charging", "sourceBindings": w.locations[0].source_bindings, **changes}
    return await mutate(w, path, changes)


def typed(md, domain="code"):
    return [entry for entry in md.get("identifierHistory", []) if entry.get("domain") == domain]


@pytest.mark.parametrize("path", ["native", "upsert", "registry"])
async def test_code_only_rename_does_not_create_station_alias_with_actual_readers(ev_world, path):
    w = ev_world
    original = await persisted(w)
    assert original["code"] != original["station_number"]
    expected = (w.locations[0].id, [w.locations[0].id])
    assert await readers(w, "number-0") == expected
    assert await readers(w, "code-0") == (None, [])
    response = await ev_mutate(w, path, {"code": "technical-next"})
    assert response.status_code == 200, response.text
    row = await persisted(w)
    assert row["type"] == "ev_charging" and row["code"] == "technical-next"
    assert row["station_number"] == "number-0"
    assert await readers(w, "number-0") == expected
    assert await readers(w, "technical-next") == (None, [])
    # On pinned old runtime BOTH actual readers falsely match this old code.
    assert await readers(w, "code-0") == (None, [])
    assert row["extra_metadata"]["numberHistory"] == original["extra_metadata"]["numberHistory"]
    [entry] = typed(row["extra_metadata"])
    assert (entry["old"], entry["new"], entry["actor"], entry["source"]) == (
        "code-0", "technical-next", str(w.user.id),
        "registry.objects" if path == "registry" else "native.locations")
    assert datetime.fromisoformat(entry["recordedAt"]).utcoffset().total_seconds() == 0
    assert not {"validFrom", "validTo", "email", "name", "было"} & entry.keys()


@pytest.mark.parametrize("path", ["native", "upsert"])
async def test_actual_old_station_number_remains_readable_after_number_rename(ev_world, path):
    w = ev_world
    expected = (w.locations[0].id, [w.locations[0].id])
    assert await readers(w, "number-0") == expected
    assert await readers(w, "code-0") == (None, [])
    response = await ev_mutate(w, path, {"metadata": {"number": "number-next"}})
    assert response.status_code == 200, response.text
    row = await persisted(w)
    assert row["type"] == "ev_charging" and row["code"] == "code-0"
    assert row["station_number"] == "number-next"
    assert await readers(w, "number-next") == expected
    assert await readers(w, "number-0") == expected
    assert await readers(w, "code-0") == (None, [])
    assert [h["было"] for h in row["extra_metadata"]["numberHistory"]] == ["old-0", "number-0"]


async def test_number_rename_records_typed_station_domain(ev_world):
    response = await ev_mutate(ev_world, "native", {"metadata": {"number": "number-next"}})
    assert response.status_code == 200, response.text
    md = (await persisted(ev_world))["extra_metadata"]
    [entry] = typed(md, "station_number")
    assert (entry["old"], entry["new"], entry["actor"], entry["source"]) == (
        "number-0", "number-next", str(ev_world.user.id), "native.locations")
    assert not typed(md)


async def test_same_code_and_number_keeps_real_alias_without_merging_domains(ev_world):
    w = ev_world
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[0].id)
        loc.code = "number-0"
        await session.commit()
    response = await ev_mutate(w, "native", {"code": "technical-next", "metadata": {"number": "number-next"}})
    assert response.status_code == 200, response.text
    row = await persisted(w)
    assert await readers(w, "number-0") == (w.locations[0].id, [w.locations[0].id])
    assert [h["было"] for h in row["extra_metadata"]["numberHistory"]] == ["old-0", "number-0"]
    assert typed(row["extra_metadata"])[0]["old"] == "number-0"
    [entry] = typed(row["extra_metadata"], "station_number")
    assert (entry["old"], entry["new"]) == ("number-0", "number-next")


@pytest.mark.parametrize("path", ["native", "upsert", "registry"])
@pytest.mark.parametrize("target", ["create-code", "create-number", "same-code", "same-number", "other-code"])
async def test_old_technical_code_stays_reserved_after_rename(ev_world, path, target):
    w = ev_world
    response = await ev_mutate(w, path, {"code": "technical-next"})
    assert response.status_code == 200, response.text
    before = await persisted(w)
    if target.startswith("create"):
        changes = {"code": "code-0"} if target == "create-code" else {"code": "claim", "metadata": {"number": "code-0"}}
        response = await w.client.post("/api/locations", json=native_payload(w, id=uuid.uuid4().hex, **changes))
    elif target == "other-code":
        response = await w.client.patch("/api/locations/" + w.locations[1].id, json={"code": "code-0"})
    else:
        changes = {"code": "code-0"} if target == "same-code" else {"metadata": {"number": "code-0"}}
        response = await ev_mutate(w, "native", changes)
    assert response.status_code == 409 and response.json() == {"detail": CONFLICT}
    assert await persisted(w) == before


@pytest.mark.parametrize("value", [None, 0, "forged-scalar", [{"domain": "code", "old": "forged", "new": "fake"}]])
@pytest.mark.parametrize("create", [False, True])
async def test_identifier_history_is_server_owned_for_every_payload_shape(ev_world, value, create):
    w = ev_world
    if create:
        identifier = uuid.uuid4().hex
        response = await w.client.post("/api/locations", json=native_payload(w,
            id=identifier, code="new-code", metadata={"number": "new-number", "identifierHistory": value}))
        assert response.status_code == 422, response.text
        async with w.factory() as session:
            assert await session.get(ServiceLocation, identifier) is None
    else:
        response = await ev_mutate(w, "native", {"metadata": {"comment": "allowed", "identifierHistory": value}})
        assert response.status_code == 200, response.text
        md = (await persisted(w))["extra_metadata"]
        assert "identifierHistory" not in md and md["comment"] == "allowed"
        assert md["number"] == "number-0"


@pytest.mark.parametrize("history_key", ["numberHistory", "identifierHistory"])
@pytest.mark.parametrize("bad", [{"old": "malformed"}, "malformed", 7, False, [None], ["old"], [7]])
@pytest.mark.parametrize("change", [{"code": "technical-next"}, {"metadata": {"number": "number-next"}}])
async def test_malformed_history_blocks_identity_changes_without_implicit_repair(ev_world, history_key, bad, change):
    w = ev_world
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[0].id)
        loc.extra_metadata = {**loc.extra_metadata, history_key: bad}
        await session.commit()
    before = await persisted(w)
    for safe in ({}, {"name": "Display only"}, {"code": "code-0"}, {"metadata": {"comment": "partial"}}):
        response = await ev_mutate(w, "native", safe)
        assert response.status_code == 200, response.text
        row = await persisted(w)
        assert row["extra_metadata"][history_key] == bad
    before_change = await persisted(w)
    response = await ev_mutate(w, "native", change)
    assert response.status_code == 409, response.text
    assert await persisted(w) == before_change
    assert before_change["code"] == before["code"] and before_change["station_number"] == before["station_number"]


async def test_legacy_histories_raw_snapshots_and_bindings_are_preserved(ev_world):
    w = ev_world
    legacy_numbers = [{"было": 0, "unknown": [None, 1]}, {"было": " old "}, {"unknown": {"raw": True}}]
    legacy_ids = [{"domain": "future-domain", "old": 0, "unknown": {"nested": [None, 1]}}, {"opaque": "sentinel"}]
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[0].id)
        loc.extra_metadata = {"number": "number-0", "numberHistory": legacy_numbers,
            "identifierHistory": legacy_ids, "asuimRaw": {"number": "raw-immutable"},
            "nameHistory": [{"было": "Old name"}], "hubexAssetId": "manual-link"}
        await session.commit()
    response = await ev_mutate(w, "native", {"code": "technical-next", "metadata": {"comment": "allowed",
        "identifierHistory": [{"domain": "code", "old": "forged", "new": "fake"}], "asuimRaw": {"number": "forged"}}})
    assert response.status_code == 200, response.text
    row = await persisted(w)
    md = row["extra_metadata"]
    assert md["numberHistory"] == legacy_numbers
    assert md["identifierHistory"][:2] == legacy_ids
    assert [e["old"] for e in typed(md)] == ["code-0"]
    assert md["number"] == "number-0" and md["asuimRaw"] == {"number": "raw-immutable"}
    assert md["nameHistory"] == [{"было": "Old name"}] and md["hubexAssetId"] == "manual-link"
    assert row["source_bindings"] == [{"sourceId": "raw-source"}]


@pytest.mark.parametrize("entry", [
    {"domain": "code", "old": "", "new": "next"},
    {"domain": "code", "old": "old", "new": None},
    {"domain": "code", "old": 7, "new": "next"},
    {"domain": "code", "old": "old", "new": []},
    {"domain": "station_number", "old": "old", "new": {}},
    {"domain": "station_number", "old": None, "new": "next"},
])
async def test_malformed_known_typed_domain_is_not_repaired(ev_world, entry):
    w = ev_world
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[0].id)
        loc.extra_metadata = {**loc.extra_metadata, "identifierHistory": [entry]}
        await session.commit()
    response = await ev_mutate(w, "native", {"name": "Safe display name"})
    assert response.status_code == 200, response.text
    before = await persisted(w)
    response = await ev_mutate(w, "native", {"code": "technical-next"})
    assert response.status_code == 409, response.text
    assert await persisted(w) == before


@pytest.mark.parametrize("incoming", [None, {"number": None}, {"number": ""}])
async def test_number_clear_records_typed_null_and_searchable_actual_alias(ev_world, incoming):
    w = ev_world
    response = await ev_mutate(w, "native", {"metadata": incoming})
    assert response.status_code == 200, response.text
    row = await persisted(w)
    [entry] = typed(row["extra_metadata"], "station_number")
    assert (entry["old"], entry["new"]) == ("number-0", None)
    assert await readers(w, "number-0") == (w.locations[0].id, [w.locations[0].id])
    assert await readers(w, "code-0") == (None, [])


@pytest.mark.parametrize("key", ["identifierHistory", "numberHistory"])
async def test_malformed_hidden_history_fails_closed_without_disclosing_payload(ev_world, key):
    w = ev_world
    async with w.factory() as session:
        hidden = await session.get(ServiceLocation, w.locations[1].id)
        hidden.extra_metadata = {key: "hidden-malformed-sentinel"}
        await session.commit()
    set_request_scope([w.locations[0].id])
    before = await persisted(w)
    async with w.factory() as session:
        with pytest.raises(location_commands.LocationConflict) as error:
            await location_commands.update(session, w.cid, w.locations[0].id, {"code": "technical-next"})
        assert error.value.status == 409 and error.value.detail == CONFLICT
        assert not any(isinstance(row, ServiceLocation) and row.id == w.locations[1].id
                       for row in session.identity_map.values())
        await session.rollback()
    assert await persisted(w) == before


async def test_foreign_typed_reservation_does_not_block_own_company(ev_world):
    w = ev_world
    async with w.factory() as session:
        session.add(ServiceLocation(id=uuid.uuid4().hex, company_id=w.foreign, code="foreign-code",
            name="Synthetic foreign point", extra_metadata={"identifierHistory": [{
                "domain": "code", "old": "foreign-old", "new": "foreign-code"}]}))
        await session.commit()
    response = await ev_mutate(w, "native", {"code": "foreign-old"})
    assert response.status_code == 200, response.text
    assert (await persisted(w))["code"] == "foreign-old"


@pytest.mark.parametrize("domain", ["code", "station_number", "legacy-number"])
async def test_hidden_company_reservation_reads_both_histories_without_entities(ev_world, domain):
    w = ev_world
    async with w.factory() as session:
        hidden = await session.get(ServiceLocation, w.locations[1].id)
        entry = {"domain": domain, "old": "hidden-retired", "new": None if domain == "station_number" else "code-1", "actor": None,
                 "source": "synthetic", "recordedAt": "2026-10-30T00:00:00+00:00"}
        hidden.extra_metadata = ({"numberHistory": [{"было": "hidden-retired"}]} if domain == "legacy-number"
                                 else {"identifierHistory": [entry]})
        await session.commit()
    before = await persisted(w)
    set_request_scope([w.locations[0].id])
    async with w.factory() as session:
        assert await session.get(ServiceLocation, w.locations[1].id) is None
        with pytest.raises(location_commands.LocationConflict) as error:
            await location_commands.update(session, w.cid, w.locations[0].id, {"code": "hidden-retired"})
        assert error.value.status == 409 and error.value.detail == CONFLICT
        assert not any(isinstance(row, ServiceLocation) and row.id == w.locations[1].id
                       for row in session.identity_map.values())
        assert current_object_scope() == [w.locations[0].id]
        await session.rollback()
    assert await persisted(w) == before


@pytest.mark.parametrize("incoming", [None, {"identifierHistory": None},
                                     {"identifierHistory": []}, {"identifierHistory": "forged"}])
async def test_existing_typed_code_history_cannot_be_cleared_through_metadata(ev_world, incoming):
    w = ev_world
    response = await ev_mutate(w, "native", {"code": "technical-next"})
    assert response.status_code == 200, response.text
    original = typed((await persisted(w))["extra_metadata"])
    assert original
    response = await ev_mutate(w, "native", {"metadata": incoming})
    assert response.status_code == 200, response.text
    assert typed((await persisted(w))["extra_metadata"]) == original


@pytest.mark.parametrize("history", [None, [], "absent"])
@pytest.mark.parametrize("field", ["code", "number"])
async def test_absent_empty_typed_history_starts_only_on_real_identity_change(ev_world, history, field):
    w = ev_world
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[0].id)
        if history != "absent":
            loc.extra_metadata = {**loc.extra_metadata, "identifierHistory": history}
        await session.commit()
    before = await persisted(w)
    response = await ev_mutate(w, "native", {"name": "Only display name"})
    assert response.status_code == 200, response.text
    md = (await persisted(w))["extra_metadata"]
    assert ("identifierHistory" in md) == ("identifierHistory" in before["extra_metadata"])
    assert md.get("identifierHistory") == before["extra_metadata"].get("identifierHistory")
    changes = {"code": "technical-next"} if field == "code" else {"metadata": {"number": "number-next"}}
    response = await ev_mutate(w, "native", changes)
    assert response.status_code == 200, response.text
    domain = "code" if field == "code" else "station_number"
    assert len(typed((await persisted(w))["extra_metadata"], domain)) == 1


async def test_both_histories_rollback_without_mutating_original_snapshots(ev_world):
    w = ev_world
    before = await persisted(w)
    async with w.factory() as session:
        loc = await session.get(ServiceLocation, w.locations[0].id)
        original_md = loc.extra_metadata
        copied = deepcopy(original_md)
        result = await location_commands.update(session, w.cid, loc.id,
            {"code": "technical-next", "metadata": {"number": "number-next"}})
        assert original_md == copied
        assert typed(result.location.extra_metadata)[0]["old"] == "code-0"
        assert [e["было"] for e in result.location.extra_metadata["numberHistory"]] == ["old-0", "number-0"]
        await session.flush()
        assert await persisted(w) == before
        await session.rollback()
    assert await persisted(w) == before


@pytest.mark.parametrize("path", ["native", "registry"])
async def test_replay_keeps_one_history_and_one_registry_audit(ev_world, path):
    w = ev_world
    for _ in range(2):
        response = await ev_mutate(w, path, {"code": "technical-next"})
        assert response.status_code == 200, response.text
    row = await persisted(w)
    assert len(typed(row["extra_metadata"])) == 1
    assert row["extra_metadata"]["numberHistory"] == [{"было": "old-0"}]
    if path == "registry":
        async with w.factory() as session:
            events = (await session.scalars(select(AuditEvent).where(AuditEvent.company_id == w.cid))).all()
        assert len(events) == 1
        details = json.loads(events[0].details)
        assert typed(details["extra_metadata"]["to"]) == typed(row["extra_metadata"])
        assert not w.projections
    else:
        assert w.projections == [(w.cid, w.locations[0].id, "technical-next")] * 2


async def test_concurrent_technical_renames_reload_stale_row_and_keep_chain(ev_world):
    w = ev_world
    async with w.factory() as first, w.factory() as second:
        stale = await second.get(ServiceLocation, w.locations[0].id)
        await location_commands.update(first, w.cid, stale.id, {"code": "technical-middle"})
        await first.flush()
        pending = asyncio.create_task(location_commands.update(second, w.cid, stale.id, {"code": "technical-final"}))
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
    assert [(e["old"], e["new"]) for e in typed(row["extra_metadata"])] == [
        ("code-0", "technical-middle"), ("technical-middle", "technical-final")]
    assert row["extra_metadata"]["numberHistory"] == [{"было": "old-0"}]


async def test_projection_failure_rolls_back_both_history_domains(ev_world, monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic projection failure")
    monkeypatch.setattr(space_projection, "project_object", fail)
    before = await persisted(ev_world)
    response = await ev_mutate(ev_world, "native", {"code": "technical-next", "metadata": {"number": "number-next"}})
    assert response.status_code == 500
    assert await persisted(ev_world) == before
