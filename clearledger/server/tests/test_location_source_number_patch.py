"""Opt-in existing-only source-number contract; no producer/API activation.

Pinned characterization exercises a FUTURE independent caller of _apply. The
public DTO couples its numbers and has a separate successful collision control.
"""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
import json
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_LOCATION_SOURCE_NUMBER_PATCH_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Opt in with {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)

from tests.test_location_commands import world as native_world, seed_freeze
from tests.test_location_lock_sets import Trace, observed_block, pid, stop_tasks
from app.models import (AuditEvent, ChargeSession, Contract, ContractLocation, Counterparty,
                        EzsEquipmentUnit, ObjectExportLog, ObjectLink, Organization, Region, ServiceLocation, UserCompany)
from app.scope import (current_object_scope, install_orm_scope, set_request_organization,
                       set_request_scope)
from app.services import location_commands as commands

COLUMN, META = "col-initial", "md-initial"
RESERVED = "technical-retired"
CONFLICT = "Номер уже занят текущим или историческим объектом компании"


@pytest.fixture(scope="module", autouse=True)
def production_scope_listener():
    install_orm_scope()


@pytest_asyncio.fixture
async def world(native_world):
    w = native_world
    set_request_scope(None)
    set_request_organization(None)
    async with w.factory() as db:
        p = await db.get(ServiceLocation, w.locations[0].id)
        p.station_number = COLUMN
        p.extra_metadata = {"number": META, "numberHistory": [{"было": "p-old"}],
            "identifierHistory": [{"domain": "future-opaque", "opaque": [1, {"keep": True}]}],
            "fieldProvenance": {"name": {"authority": "manual", "actor": "synthetic-actor",
                "source": "synthetic.prior", "recordedAt": "2026-01-01T00:00:00+00:00"}},
            "nameHistory": ["Synthetic prior name"], "sourceRaw": {"opaque": ["preserved"]},
            "opaqueSibling": [1, {"keep": "verbatim"}]}
        q = await db.get(ServiceLocation, w.locations[1].id)
        q.status = "closed"
        q.extra_metadata = {**q.extra_metadata, "identifierHistory": [{"domain": "code", "old": RESERVED,
            "new": q.code, "field": "code", "actor": None, "source": "synthetic",
            "recordedAt": "2026-01-01T00:00:00+00:00"},
            {"domain": "station_number", "old": "typed-station-retired", "new": q.station_number}]}
        db.add(ObjectLink(company_id=w.cid, parent_type="point_of_service", parent_id=q.id,
            child_type="number", child_id="dated-retired", relation="number",
            valid_from=date(2020, 1, 1), valid_to=date(2021, 1, 1)))
        await db.commit()
    yield w
    set_request_scope(None)
    set_request_organization(None)


async def snapshot(w, identifier=None):
    c = ServiceLocation.__table__.c
    async with w.factory() as db:
        row = (await db.execute(select(c.id, c.company_id, c.code, c.name, c.type, c.status,
            c.station_number, c.extra_metadata, c.source_bindings).where(
            c.id == (identifier or w.locations[0].id)))).mappings().one()
        return deepcopy(dict(row))


async def conflict(awaitable, status=409):
    with pytest.raises(commands.LocationConflict) as error:
        await awaitable
    assert error.value.status == status
    return error.value


async def patch(w, db, changes, cap, *, identifier=None, company=None):
    return await commands.apply_existing_source_number_patch(db, company or w.cid,
        identifier or w.locations[0].id, changes, cap, actor_id=w.user.id, source="synthetic.source-number")


async def test_characterization_future_independent_metadata_assignment_needs_occupancy(world, record_property):
    w = world
    p = w.locations[0].id
    before = await snapshot(w)
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        loc = await commands.locked_visible_in_set(db, w.cid, p, cap)
        changes = {"extra_metadata": {**deepcopy(loc.extra_metadata), "number": RESERVED}}
        status = None
        try:
            await commands._apply(db, w.cid, loc, changes, actor_id=w.user.id, source="synthetic.future-independent")
        except commands.LocationConflict as error:
            status = error.status
        actual = (status, loc.station_number, loc.extra_metadata["number"])
        record_property("future_independent_contract", json.dumps(actual))
        assert actual == (409, COLUMN, META)
        await db.rollback()
    assert await snapshot(w) == before


async def test_public_coupled_metadata_number_collision_control(world):
    w = world
    before = await snapshot(w)
    response = await w.client.patch("/api/locations/" + w.locations[0].id,
                                    json={"metadata": {"number": RESERVED}})
    assert response.status_code == 409 and response.json() == {"detail": CONFLICT}
    assert await snapshot(w) == before
    assert not w.projections


@pytest.mark.parametrize("changes,column,metadata", [
    ({}, COLUMN, META), ({"station_number": "column-new"}, "column-new", META),
    ({"metadata.number": "metadata-new"}, COLUMN, "metadata-new"),
    ({"station_number": None}, None, META), ({"station_number": ""}, "", META),
    ({"metadata.number": None}, COLUMN, None), ({"metadata.number": ""}, COLUMN, ""),
    ({"station_number": None, "metadata.number": "metadata-new"}, None, "metadata-new"),
    ({"station_number": "column-new", "metadata.number": "metadata-new"}, "column-new", "metadata-new"),
    ({"metadata.number": 0}, COLUMN, 0), ({"metadata.number": 1.25}, COLUMN, 1.25),
    ({"station_number": "  raw number  "}, "  raw number  ", META),
    ({"metadata.number": "  raw number  "}, COLUMN, "  raw number  "),
    ({"station_number": "x" * 60}, "x" * 60, META),
])
async def test_presence_aware_independent_values_preserve_protected_siblings_and_caller_commit(world, changes, column, metadata):
    w = world
    before = await snapshot(w)
    p = w.locations[0].id
    async with w.factory() as db, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        locks = list(trace.locks)
        result = await patch(w, db, changes, cap)
        assert isinstance(result, commands.Mutation)
        assert (result.location.station_number, result.location.extra_metadata["number"]) == (column, metadata)
        assert trace.locks == locks and not db.new
        assert await snapshot(w) == before  # No hidden flush/commit.
        await db.commit()
    after = await snapshot(w)
    assert (after["station_number"], after["extra_metadata"]["number"]) == (column, metadata)
    assert {k: v for k, v in after.items() if k not in ("station_number", "extra_metadata")} == {
        k: v for k, v in before.items() if k not in ("station_number", "extra_metadata")}
    untouched = {"number", "identifierHistory", "numberHistory"}
    assert {k: v for k, v in after["extra_metadata"].items() if k not in untouched} == {
        k: v for k, v in before["extra_metadata"].items() if k not in untouched}
    assert not w.projections
    async with w.factory() as audit:
        assert await audit.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.company_id == w.cid)) == 0


@pytest.mark.parametrize("field", ["station_number", "metadata.number"])
async def test_typed_station_history_records_only_requested_outgoing_value(world, field):
    w = world
    p = w.locations[0].id
    before = await snapshot(w)
    old = COLUMN if field == "station_number" else META
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        result = await patch(w, db, {field: "source-next"}, cap)
        md = result.location.extra_metadata
        assert md["identifierHistory"][:-1] == before["extra_metadata"]["identifierHistory"]
        entry = md["identifierHistory"][-1]
        assert (entry["domain"], entry["field"], entry["old"], entry["new"]) == (
            "station_number", field, old, "source-next")
        assert entry["actor"] == str(w.user.id) and entry["source"] == "synthetic.source-number"
        assert datetime.fromisoformat(entry["recordedAt"]).utcoffset() == timedelta(0)
        assert [h["было"] for h in md["numberHistory"]] == ["p-old", old]
        assert "code-0" not in [h["было"] for h in md["numberHistory"]]
        await db.rollback()
    assert await snapshot(w) == before


@pytest.mark.parametrize("invalid", [None, [], {"code": "x"}, {"id": "x"}, {"name": "x"},
    {"sourceBindings": []}, {"metadata": {"number": "x"}}, {"identifierHistory": []},
    {"fieldProvenance": {}}, {"authority": "manual"}, {"numberHistory": []},
    {"station_number": True}, {"station_number": 2}, {"station_number": []},
    {"station_number": "x" * 61}, {"metadata.number": "x" * 61},
    {"metadata.number": False}, {"metadata.number": {}}, {"metadata.number": []},
    {"metadata.number": b"bytes"}, {"metadata.number": float("nan")},
    {"metadata.number": float("inf")}, {"metadata.number": 10 ** 61},
    {"station_number": "\x00"}, {"metadata.number": "\x00"},
    {"station_number": "valid", "metadata.name": "forbidden"},
])
async def test_closed_patch_validation_rejects_without_sql_or_mutation(world, invalid):
    w = world
    before = await snapshot(w)
    async with w.factory() as db, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(db, w.cid, [w.locations[0].id])
        count = len(trace.sql)
        await conflict(patch(w, db, invalid, cap), 422)
        assert len(trace.sql) == count and not db.dirty and not db.new
        await db.rollback()
    assert await snapshot(w) == before


@pytest.mark.parametrize("kind", ["none", "forged", "session", "company", "commit", "rollback", "late_id"])
async def test_real_root_capability_required_without_fallback_or_late_locks(world, kind):
    w = world
    p = w.locations[0].id
    async with w.factory() as db, w.factory() as other, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        target, company, identifier = db, w.cid, p
        if kind == "none": cap = None
        elif kind == "forged": cap = replace(cap)
        elif kind == "session": target = other
        elif kind == "company": company = w.foreign
        elif kind in ("commit", "rollback"): await getattr(db, kind)()
        elif kind == "late_id": identifier = w.locations[1].id
        before = len(trace.sql)
        await conflict(patch(w, target, {"metadata.number": "source-next"}, cap, identifier=identifier, company=company))
        assert len(trace.sql) == before and not target.dirty and not target.new
        await db.rollback()


async def test_planned_missing_id_is_404_without_creation_or_audit(world):
    w = world
    missing = "missing-" + uuid.uuid4().hex[:15]
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [missing])
        await conflict(patch(w, db, {"station_number": "source-next"}, cap, identifier=missing), 404)
        assert not db.new and not db.dirty
        await db.rollback()


@pytest.mark.parametrize("field", ["station_number", "metadata.number"])
@pytest.mark.parametrize("value", ["code-1", "number-1", "old-1", RESERVED, "typed-station-retired", "dated-retired"])
async def test_hidden_company_wide_current_and_history_reservations_are_generic(world, field, value):
    w = world
    p, q = [row.id for row in w.locations]
    before = await snapshot(w)
    set_request_scope([p])
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        error = await conflict(patch(w, db, {field: value}, cap))
        assert value not in error.detail and q not in error.detail
        assert not any(isinstance(row, ServiceLocation) and row.id != p for row in db.identity_map.values())
        assert not db.dirty and not db.new and current_object_scope() == [p]
        await db.rollback()
    assert await snapshot(w) == before


@pytest.mark.parametrize("field", ["station_number", "metadata.number"])
@pytest.mark.parametrize("reason", ["session", "contract", "accounted", "external"])
@pytest.mark.parametrize("value", [None, "source-next"])
async def test_freeze_covers_each_independent_assignment_and_clear_before_mutation(world, field, reason, value):
    w = world
    await seed_freeze(w, reason)
    before = await snapshot(w)
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [w.locations[0].id])
        await conflict(patch(w, db, {field: value}, cap))
        assert not db.dirty and not db.new
        await db.rollback()
    assert await snapshot(w) == before


async def test_unchanged_shared_column_is_not_a_new_conflict_for_independent_metadata_change(world):
    w = world
    p, q = [row.id for row in w.locations]
    async with w.factory() as seed:
        for identifier in (p, q):
            loc = await seed.get(ServiceLocation, identifier)
            loc.station_number = "legacy-shared"
        await seed.commit()
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        result = await patch(w, db, {"station_number": "legacy-shared", "metadata.number": "unique-next"}, cap)
        assert result.location.station_number == "legacy-shared"
        assert result.location.extra_metadata["number"] == "unique-next"
        assert all(h.get("old") != "legacy-shared" for h in result.location.extra_metadata["identifierHistory"])
        await db.commit()
    assert (await snapshot(w, q))["station_number"] == "legacy-shared"


async def test_noop_divergent_shared_and_malformed_history_do_not_trigger_repair_or_freeze(world):
    w = world
    p, q = [row.id for row in w.locations]
    async with w.factory() as seed:
        loc = await seed.get(ServiceLocation, p)
        loc.station_number = "legacy-shared"
        loc.extra_metadata = {**loc.extra_metadata, "identifierHistory": "malformed-keep"}
        (await seed.get(ServiceLocation, q)).station_number = "legacy-shared"
        await seed.commit()
    await seed_freeze(w, "session")
    before = await snapshot(w)
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        result = await patch(w, db, {"station_number": "legacy-shared", "metadata.number": META}, cap)
        assert result.changes == {}
        assert result.location.extra_metadata == before["extra_metadata"]
        await db.commit()
    assert await snapshot(w) == before


@pytest.mark.parametrize("key,bad", [("numberHistory", "bad"), ("numberHistory", [7]),
    ("identifierHistory", "bad"), ("identifierHistory", [{"domain": "station_number", "old": "x"}])])
async def test_known_malformed_history_blocks_actual_identity_change_without_mutation(world, key, bad):
    w = world
    async with w.factory() as seed:
        loc = await seed.get(ServiceLocation, w.locations[0].id)
        loc.extra_metadata = {**loc.extra_metadata, key: bad}
        await seed.commit()
    before = await snapshot(w)
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [w.locations[0].id])
        await conflict(patch(w, db, {"metadata.number": "source-next"}, cap))
        assert not db.dirty
        await db.rollback()
    assert await snapshot(w) == before


@pytest.mark.parametrize("root", [False, [], "legacy-opaque", 7])
async def test_opaque_metadata_root_not_repaired_by_metadata_request_or_column_identity_change(world, root):
    w = world
    async with w.factory() as seed:
        (await seed.get(ServiceLocation, w.locations[0].id)).extra_metadata = root
        await seed.commit()
    before = await snapshot(w)
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [w.locations[0].id])
        for changes in ({"metadata.number": None}, {"metadata.number": "source-next"}, {"station_number": "source-next"}):
            await conflict(patch(w, db, changes, cap))
            assert not db.dirty and not db.new
        result = await patch(w, db, {"station_number": COLUMN}, cap)
        assert result.changes == {} and result.location.extra_metadata == root
        await db.rollback()
    assert await snapshot(w) == before


@pytest.mark.parametrize("changes", [{"station_number": "source-next"}, {"metadata.number": None}])
async def test_sql_null_metadata_is_supported_without_inventing_omitted_number(world, changes):
    w = world
    async with w.factory() as seed:
        (await seed.get(ServiceLocation, w.locations[0].id)).extra_metadata = None
        await seed.commit()
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [w.locations[0].id])
        result = await patch(w, db, changes, cap)
        if "station_number" in changes:
            assert "number" not in result.location.extra_metadata
        else:
            assert result.location.station_number == COLUMN and result.location.extra_metadata["number"] is None
        await db.commit()


@pytest.mark.parametrize("kind", ["session", "external_link", "external_log", "inventory", "unrelated"])
async def test_pending_fact_rejected_without_flush_then_explicit_flush_preserves_visibility(world, kind):
    w = world
    p = w.locations[0].id
    unit_id = None
    if kind == "inventory":
        async with w.factory() as seed:
            unit = EzsEquipmentUnit(company_id=w.cid)
            seed.add(unit)
            await seed.flush()
            unit_id = unit.id
            seed.add(ObjectLink(company_id=w.cid, parent_type="point_of_service", parent_id=p,
                child_type="station", child_id=str(unit.id), relation="placed_at", valid_from=date(2020, 1, 1)))
            await seed.commit()
    before = await snapshot(w)
    async with w.factory() as db, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        await commands.locked_visible_in_set(db, w.cid, p, cap)  # Admit before fixture's explicit flush.
        if kind == "session":
            pending = ChargeSession(company_id=w.cid, location_id=p, session_ext_id=uuid.uuid4().hex)
            db.add(pending)
        elif kind == "external_link":
            pending = ObjectLink(company_id=w.cid, parent_type="point_of_service", parent_id=p,
                child_type="synthetic:external", child_id="pending", relation="external_id", valid_from=date(2020, 1, 1))
            db.add(pending)
        elif kind == "external_log":
            pending = ObjectExportLog(company_id=w.cid, actor_kind="integration", destination="synthetic",
                                      is_external=True, objects_count=1)
            db.add(pending)
        elif kind == "inventory":
            pending = await db.get(EzsEquipmentUnit, unit_id)
            pending.inventory_number = "synthetic-pending-inventory"
        else:
            pending = Region(company_id=w.cid, name="Synthetic pending unrelated")
            db.add(pending)
        count = len(trace.sql)
        await conflict(patch(w, db, {"metadata.number": "source-next"}, cap))
        assert len(trace.sql) == count
        assert pending in db.new or pending in db.dirty
        assert await snapshot(w) == before
        await db.flush()  # Caller owns this admitted write; helper never does it.
        if kind == "unrelated":
            result = await patch(w, db, {"metadata.number": "source-next"}, cap)
            assert result.location.extra_metadata["number"] == "source-next"
        else:
            await conflict(patch(w, db, {"metadata.number": "source-next"}, cap))
        await db.rollback()
    assert await snapshot(w) == before


@pytest.mark.parametrize("state", ["target", "unrelated", "deleted"])
async def test_clean_entry_rejects_other_pending_state_without_hidden_flush_or_loss(world, state):
    w = world
    p, q = [row.id for row in w.locations]
    async with w.factory() as db, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        row = await db.get(ServiceLocation, p if state == "target" else q)
        if state == "deleted": await db.delete(row)
        else: row.name = "Synthetic pending caller name"
        count = len(trace.sql)
        await conflict(patch(w, db, {"metadata.number": "source-next"}, cap))
        assert len(trace.sql) == count
        assert row in db.deleted or row in db.dirty
        if state != "deleted": assert row.name == "Synthetic pending caller name"
        await db.rollback()


async def test_sequential_patches_require_caller_flush_same_root_set_and_do_not_commit(world):
    w = world
    p = w.locations[0].id
    before = await snapshot(w)
    async with w.factory() as db, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        locks = list(trace.locks)
        await patch(w, db, {"metadata.number": "first-next"}, cap)
        count = len(trace.sql)
        await conflict(patch(w, db, {"metadata.number": "second-next"}, cap))
        assert len(trace.sql) == count
        await db.flush()
        await patch(w, db, {"metadata.number": "second-next"}, cap)
        assert trace.locks == locks and await snapshot(w) == before
        await db.flush()
        await conflict(patch(w, db, {"metadata.number": META}, cap))  # Own outgoing alias is reserved.
        await db.rollback()
    assert await snapshot(w) == before


@pytest.mark.parametrize("scope", [[], ["missing-synthetic"]])
async def test_current_object_admission_is_not_granted_by_source_capability(world, scope):
    w = world
    p = w.locations[0].id
    before = await snapshot(w)
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        set_request_scope(scope)
        await conflict(patch(w, db, {"metadata.number": "source-next"}, cap), 404)
        assert current_object_scope() == scope and not db.dirty
        await db.rollback()
    assert await snapshot(w) == before


async def test_current_organization_admission_is_not_bypassed(world):
    w = world
    async with w.factory() as seed:
        org = Organization(company_id=w.cid, name="Synthetic unmatched org", inn="000000000097")
        seed.add(org)
        await seed.commit()
    set_request_organization(org.id)
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [w.locations[0].id])
        await conflict(patch(w, db, {"metadata.number": "source-next"}, cap), 404)
        assert not db.dirty
        await db.rollback()


async def test_foreign_held_row_is_not_loaded_locked_or_used_for_own_occupancy(world):
    w = world
    async with w.factory() as seed:
        foreign = ServiceLocation(id="foreign-" + uuid.uuid4().hex[:16], company_id=w.foreign,
            code="foreign-code", name="Synthetic foreign point", station_number="foreign-number", source_bindings=[])
        seed.add(foreign)
        await seed.commit()
    async with w.factory() as holder, w.factory() as db:
        await holder.execute(select(ServiceLocation).where(ServiceLocation.id == foreign.id,
                            ServiceLocation.company_id == w.foreign).with_for_update())
        cap = await commands.acquire_location_set(db, w.cid, [w.locations[0].id, foreign.id])
        await conflict(asyncio.wait_for(patch(w, db, {"metadata.number": "source-next"}, cap,
                                              identifier=foreign.id), 1), 404)
        assert not any(isinstance(row, ServiceLocation) and row.id == foreign.id for row in db.identity_map.values())
        result = await asyncio.wait_for(patch(w, db, {"metadata.number": "foreign-number"}, cap), 1)
        assert result.location.extra_metadata["number"] == "foreign-number"
        await db.rollback()
        await holder.rollback()


async def test_stale_orm_wait_reload_preserves_manual_column_and_history(world, record_property):
    w = world
    p = w.locations[0].id
    async with w.factory() as source, w.factory() as manual, w.factory() as observer:
        stale = await source.get(ServiceLocation, p)
        a, b = await pid(manual), await pid(source)
        await commands.update(manual, w.cid, p, {"metadata": {"number": "manual-current"}},
                              actor_id=w.user.id, source="synthetic.manual-number")
        await manual.flush()
        waiting = asyncio.create_task(commands.acquire_location_set(source, w.cid, [p]))
        try:
            edge = await observed_block(observer, b, a)
            record_property("source_number_stale_wait", json.dumps(edge))
            await manual.commit()
            cap = await asyncio.wait_for(waiting, 7)
            result = await patch(w, source, {"metadata.number": "source-next"}, cap)
            assert result.location is stale
            assert stale.station_number == "manual-current" and stale.extra_metadata["number"] == "source-next"
            assert [h["old"] for h in stale.extra_metadata["identifierHistory"] if h.get("domain") == "station_number"] == [
                COLUMN, META, "manual-current"]
            assert stale.extra_metadata["identifierHistory"][-1]["field"] == "metadata.number"
            await source.rollback()
        finally:
            await stop_tasks(waiting)
            await manual.rollback()
    after = await snapshot(w)
    assert after["station_number"] == after["extra_metadata"]["number"] == "manual-current"


async def test_matching_organization_admits_noop_and_retains_contract_freeze(world):
    w = world
    p = w.locations[0].id
    async with w.factory() as seed:
        org = Organization(company_id=w.cid, name="Synthetic matching org", inn="000000000098")
        party = Counterparty(company_id=w.cid, name="Synthetic matching party")
        seed.add_all([org, party])
        await seed.flush()
        contract = Contract(company_id=w.cid, organization_id=org.id, counterparty_id=party.id,
                            type="energy", scope_type="locations", number="synthetic", date="2026-10-30")
        seed.add(contract)
        await seed.flush()
        seed.add(ContractLocation(company_id=w.cid, contract_id=contract.id, location_id=p))
        await seed.commit()
    set_request_organization(org.id)
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        assert (await patch(w, db, {"metadata.number": META}, cap)).changes == {}
        error = await conflict(patch(w, db, {"metadata.number": "source-next"}, cap))
        assert "договор" in error.detail
        await db.rollback()


@pytest.mark.parametrize("provenance", [None, "opaque-provenance", []])
async def test_opaque_protected_provenance_not_repaired_by_number_change(world, provenance):
    w = world
    p = w.locations[0].id
    async with w.factory() as seed:
        loc = await seed.get(ServiceLocation, p)
        loc.extra_metadata = {**loc.extra_metadata, "fieldProvenance": provenance}
        await seed.commit()
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        result = await patch(w, db, {"metadata.number": "source-next"}, cap)
        assert result.location.extra_metadata["fieldProvenance"] == provenance
        await db.rollback()


@pytest.mark.parametrize("root", [False, [], "legacy-opaque", 7])
async def test_native_hidden_malformed_catalog_root_gets_generic_conflict(world, root, record_property):
    w = world
    p, q = [row.id for row in w.locations]
    async with w.factory() as seed:
        member = await seed.get(UserCompany, (w.user.id, w.cid))
        member.role, member.object_scope = "user", [p]
        (await seed.get(ServiceLocation, q)).extra_metadata = root
        await seed.commit()
    before = await snapshot(w)
    response = await w.client.patch("/api/locations/" + p, json={"metadata": {"number": "catalog-new"}})
    record_property("native_malformed_catalog_status", str(response.status_code))
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": CONFLICT}
    assert q not in response.text
    assert await snapshot(w) == before


async def test_native_hidden_nullable_catalog_metadata_control(world):
    w = world
    p, q = [row.id for row in w.locations]
    async with w.factory() as seed:
        member = await seed.get(UserCompany, (w.user.id, w.cid))
        member.role, member.object_scope = "user", [p]
        (await seed.get(ServiceLocation, q)).extra_metadata = None
        await seed.commit()
    response = await w.client.patch("/api/locations/" + p, json={"metadata": {"number": "catalog-new"}})
    assert response.status_code == 200, response.text
    after = await snapshot(w)
    assert after["station_number"] == after["extra_metadata"]["number"] == "catalog-new"
    assert (await snapshot(w, q))["extra_metadata"] is None


@pytest.mark.parametrize("root", [False, [], "legacy-opaque", 7])
async def test_source_occupancy_fails_closed_for_hidden_opaque_catalog_root(world, root):
    w = world
    p, q = [row.id for row in w.locations]
    async with w.factory() as seed:
        (await seed.get(ServiceLocation, q)).extra_metadata = root
        await seed.commit()
    set_request_scope([p])
    before = await snapshot(w)
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        assert (await patch(w, db, {}, cap)).changes == {}  # No new claim, no repair/inspection.
        error = await conflict(patch(w, db, {"metadata.number": "unclaimed-next"}, cap))
        assert error.detail == CONFLICT
        assert not any(isinstance(row, ServiceLocation) and row.id != p for row in db.identity_map.values())
        assert not db.is_modified(next(row for row in db.identity_map.values() if isinstance(row, ServiceLocation)))
        await db.rollback()
    assert await snapshot(w) == before


async def test_source_occupancy_fails_closed_for_hidden_malformed_typed_history(world):
    w = world
    p, q = [row.id for row in w.locations]
    async with w.factory() as seed:
        other = await seed.get(ServiceLocation, q)
        other.extra_metadata = {**other.extra_metadata, "identifierHistory": "hidden-malformed"}
        await seed.commit()
    set_request_scope([p])
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        error = await conflict(patch(w, db, {"metadata.number": "unclaimed-next"}, cap))
        assert error.detail == CONFLICT and q not in error.detail
        assert not db.dirty
        await db.rollback()


async def test_jsonb_numeric_exponent_reservation_matches_hidden_persisted_number(world, record_property):
    w = world
    p, q = [row.id for row in w.locations]
    async with w.factory() as seed:
        other = await seed.get(ServiceLocation, q)
        other.extra_metadata = {**other.extra_metadata, "number": 10 ** 20}
        await seed.commit()
    set_request_scope([p])
    before = await snapshot(w)
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        status = None
        try:
            await patch(w, db, {"metadata.number": 1e20}, cap)
        except commands.LocationConflict as error:
            status = error.status
        loc = await db.get(ServiceLocation, p)
        record_property("numeric_exponent_reservation", json.dumps([status, str(loc.extra_metadata["number"])]))
        assert status == 409 and loc.extra_metadata["number"] == META
        await db.rollback()
    assert await snapshot(w) == before


async def test_jsonb_numeric_exponent_fresh_session_replay_is_noop(world, record_property):
    w = world
    p = w.locations[0].id
    async with w.factory() as first:
        cap = await commands.acquire_location_set(first, w.cid, [p])
        await patch(w, first, {"metadata.number": 1e20}, cap)
        await first.commit()
    before = await snapshot(w)
    assert before["extra_metadata"]["number"] == 10 ** 20
    async with w.factory() as second, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(second, w.cid, [p])
        result = await patch(w, second, {"metadata.number": 1e20}, cap)
        record_property("numeric_exponent_replay", json.dumps(sorted(result.changes)))
        assert result.changes == {} and result.location.extra_metadata == before["extra_metadata"]
        # Canonical stored numeric text, not a short exponent spelling, owns the limit.
        count = len(trace.sql)
        await conflict(patch(w, second, {"metadata.number": 1e100}, cap), 422)
        assert len(trace.sql) == count
        await second.commit()
    assert await snapshot(w) == before


async def test_jsonb_negative_zero_reservation_replay_and_ordinary_float_scale(world, record_property):
    w = world
    p, q = [row.id for row in w.locations]
    async with w.factory() as seed:
        other = await seed.get(ServiceLocation, q)
        other.extra_metadata = {**other.extra_metadata, "number": 0.0}
        await seed.commit()
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        status = None
        try:
            await patch(w, db, {"metadata.number": -0.0}, cap)
        except commands.LocationConflict as error:
            status = error.status
        record_property("negative_zero_reservation", json.dumps(status))
        assert status == 409
        await db.rollback()
    async with w.factory() as seed:
        other = await seed.get(ServiceLocation, q)
        other.extra_metadata = {**other.extra_metadata, "number": "not-zero"}
        await seed.commit()
    async with w.factory() as first:
        cap = await commands.acquire_location_set(first, w.cid, [p])
        await patch(w, first, {"metadata.number": -0.0}, cap)
        await first.commit()
    before = await snapshot(w)
    assert isinstance(before["extra_metadata"]["number"], float)
    assert str(before["extra_metadata"]["number"]) == "0.0"
    async with w.factory() as second:
        cap = await commands.acquire_location_set(second, w.cid, [p])
        assert (await patch(w, second, {"metadata.number": -0.0}, cap)).changes == {}
        for ordinary in (1.0, 1.25):
            result = await patch(w, second, {"metadata.number": ordinary}, cap)
            assert isinstance(result.location.extra_metadata["number"], float)
            assert result.location.extra_metadata["number"] == ordinary
            await second.flush()
        await second.rollback()
    assert await snapshot(w) == before
