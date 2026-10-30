"""Opt-in actual manual name -> session W10 checks in isolated synthetic PG.

Baseline primary tests assert the final name/history before checking new metadata;
missing provenance symbols/keys are not used as evidence of the old W10 defect.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_LOCATION_MANUAL_NAME_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Opt in with {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)

from tests.test_location_commands import world as native_world
from tests.test_location_lock_sets import observed_block, pid, stop_tasks
from app.auth import get_current_user
from app.models import (AuditEvent, ChargeSession, Organization, ServiceLocation, User, UserCompany)
from app.routers import locations_router
from app.scope import install_orm_scope, set_request_organization, set_request_scope
from app.services import location_commands as commands, space_projection, space_registry
from app.services.stations_normalize import refresh_location_names

MANUAL = "Synthetic manual label"
SOURCE = "Synthetic session label"
VALID_STORED = {"name": {"authority": "manual", "actor": "synthetic-prior-actor",
                         "source": "synthetic.prior", "recordedAt": "2026-01-01T00:00:00+00:00"}}


@pytest.fixture(scope="module", autouse=True)
def real_scope_listener():
    install_orm_scope()


@pytest_asyncio.fixture
async def world(native_world):
    w = native_world
    set_request_scope(None)
    set_request_organization(None)
    async with w.factory() as db:
        row = await db.get(ServiceLocation, w.locations[0].id)
        row.type = "ev_charging"
        row.extra_metadata = {**row.extra_metadata, "nameHistory": ["Synthetic older label"],
                              "rawSnapshot": {"source": "synthetic", "value": "preserved"}}
        await db.commit()
    yield w
    set_request_scope(None)
    set_request_organization(None)


async def snapshot(w, identifier=None):
    c = ServiceLocation.__table__.c
    async with w.factory() as db:
        row = (await db.execute(select(c.id, c.company_id, c.name, c.code, c.type,
            c.station_number, c.extra_metadata, c.source_bindings).where(c.id == (identifier or w.locations[0].id)))).mappings().one()
        return deepcopy(dict(row))


async def seed_sessions(w):
    p = w.locations[0].id
    async with w.factory() as db:
        for index, (name, day) in enumerate((("Synthetic older source", 1), ("  " + SOURCE + "  ", 3),
                                            (None, 5), ("   ", 6))):
            db.add(ChargeSession(company_id=w.cid, location_id=p,
                session_ext_id=uuid.uuid4().hex, source_station_id="synthetic-source-id",
                station_code="synthetic-source-number", station_name=name,
                started_at=datetime(2026, 1, day, 12)))
        foreign = ServiceLocation(id="foreign-name-" + uuid.uuid4().hex[:16], company_id=w.foreign,
                                   code="synthetic-foreign", name="Synthetic foreign label", type="ev_charging",
                                   extra_metadata={"rawSnapshot": "foreign-preserved"}, source_bindings=[])
        db.add(foreign)
        await db.flush()
        db.add(ChargeSession(company_id=w.foreign, location_id=foreign.id, session_ext_id=uuid.uuid4().hex,
                             station_name="Synthetic foreign source", started_at=datetime(2026, 1, 9, 12)))
        await db.commit()
    return foreign.id


async def refresh(w, *, commit=True):
    async with w.factory() as db:
        count = await refresh_location_names(db, w.cid)
        assert isinstance(count, int)
        if commit:
            await db.commit()
        else:
            await db.rollback()
        return count


async def request(w, path, changes, *, company=None):
    p = w.locations[0].id
    if path == "native":
        return await w.client.patch("/api/locations/" + p, json=changes)
    if path == "registry":
        return await w.client.patch("/api/registry/objects/" + p,
                                    params={"company_id": str(company or w.cid)}, json=changes)
    current = await snapshot(w)
    body = {"id": p, "company_id": str(company or w.cid), "code": current["code"],
            "name": current["name"], "type": current["type"],
            "sourceBindings": current["source_bindings"], **changes}
    return await w.client.post("/api/locations", json=body)


def assert_marker(row, w, source):
    fp = row["extra_metadata"]["fieldProvenance"]
    marker = fp["name"]
    assert marker["authority"] == "manual"
    assert marker["actor"] == str(w.user.id) and marker["source"] == source
    recorded = datetime.fromisoformat(marker["recordedAt"])
    assert recorded.utcoffset() == timedelta(0)
    assert set(marker) == {"authority", "actor", "source", "recordedAt"}
    return marker


@pytest.mark.parametrize("path", ["native", "upsert", "registry"])
async def test_manual_edit_survives_actual_w10(world, path, record_property):
    w = world
    foreign = await seed_sessions(w)
    original = await snapshot(w)
    foreign_before = await snapshot(w, foreign)
    response = await request(w, path, {"name": MANUAL})
    assert response.status_code == 200, response.text
    manual = await snapshot(w)
    count = await refresh(w)
    after = await snapshot(w)
    actual = (count, after["name"], after["extra_metadata"]["nameHistory"])
    record_property("manual_w10_actual", json.dumps(actual))
    # Baseline must show actual manual-name loss, not just a missing new key.
    assert actual == (0, MANUAL, original["extra_metadata"]["nameHistory"])
    assert after == manual
    assert await snapshot(w, foreign) == foreign_before
    assert_marker(after, w, "registry.objects" if path == "registry" else "native.locations")
    old_md = {k: v for k, v in after["extra_metadata"].items() if k != "fieldProvenance"}
    assert old_md == original["extra_metadata"]
    assert {k: v for k, v in after.items() if k not in ("name", "extra_metadata")} == {
        k: v for k, v in original.items() if k not in ("name", "extra_metadata")}


@pytest.mark.parametrize("kind", ["cpo", "unmarked"])
async def test_cpo_and_unmarked_w10_controls_are_independent(world, kind):
    w = world
    foreign = await seed_sessions(w)
    if kind == "cpo":
        async with w.factory() as db:
            row = await db.get(ServiceLocation, w.locations[0].id)
            row.extra_metadata = {**row.extra_metadata, "nameSource": "cpo_registry"}
            await db.commit()
    before, foreign_before = await snapshot(w), await snapshot(w, foreign)
    count = await refresh(w)
    after = await snapshot(w)
    if kind == "cpo":
        assert count == 0 and after == before
    else:
        assert count == 1 and after["name"] == SOURCE
        assert after["extra_metadata"]["nameHistory"] == before["extra_metadata"]["nameHistory"] + [before["name"]]
        assert {k: v for k, v in after["extra_metadata"].items() if k != "nameHistory"} == {
            k: v for k, v in before["extra_metadata"].items() if k != "nameHistory"}
    assert await refresh(w) == 0
    assert await snapshot(w) == after and await snapshot(w, foreign) == foreign_before


@pytest.mark.parametrize("bad", [None, False, 7, "forged", [], {"name": {"authority": "manual"}}])
async def test_supplied_provenance_on_new_native_create_is_rejected(world, bad):
    w = world
    identifier = "manual-create-" + uuid.uuid4().hex[:15]
    response = await w.client.post("/api/locations", json={"id": identifier, "company_id": str(w.cid),
        "code": identifier, "name": "Synthetic initial name", "metadata": {"fieldProvenance": bad}})
    assert response.status_code == 422, response.text
    async with w.factory() as db:
        assert await db.get(ServiceLocation, identifier) is None
    assert not w.projections


@pytest.mark.parametrize("path", ["native", "upsert"])
@pytest.mark.parametrize("bad", [None, False, 7, "forged", [], {"name": {"authority": "sessions"}}])
async def test_payload_provenance_cannot_overwrite_stored_marker(world, path, bad):
    w = world
    assert (await request(w, "native", {"name": MANUAL})).status_code == 200
    before = await snapshot(w)
    response = await request(w, path, {"metadata": {"fieldProvenance": bad, "comment": "Synthetic echo"}})
    assert response.status_code == 200, response.text
    after = await snapshot(w)
    assert after["extra_metadata"]["fieldProvenance"] == before["extra_metadata"]["fieldProvenance"]
    assert after["extra_metadata"]["comment"] == "Synthetic echo"


@pytest.mark.parametrize("stored", [None, False, "legacy-opaque", [], {"name": None},
                                    {"name": []}, {"name": {"authority": "future"}},
                                    {"name": {"authority": "manual"}},
                                    {"name": {**VALID_STORED["name"], "recordedAt": "invalid"}}])
async def test_malformed_or_unknown_stored_provenance_is_not_silently_repaired(world, stored):
    w = world
    async with w.factory() as db:
        row = await db.get(ServiceLocation, w.locations[0].id)
        row.extra_metadata = {**row.extra_metadata, "fieldProvenance": stored}
        await db.commit()
    before = await snapshot(w)
    # Malformed incoming key and a name no-op cannot erase/repair stored JSON.
    response = await request(w, "native", {"name": before["name"], "metadata": {"fieldProvenance": "payload-forgery"}})
    assert response.status_code == 200, response.text
    assert await snapshot(w) == before
    response = await request(w, "native", {"name": MANUAL})
    assert response.status_code == 409, response.text
    assert await snapshot(w) == before


async def test_name_provenance_preserves_unknown_siblings_and_extra_known_marker_fields(world):
    w = world
    stored = {**deepcopy(VALID_STORED), "futureField": {"opaque": [1, "keep"]}}
    stored["name"]["futureExtra"] = {"opaque": "keep"}
    async with w.factory() as db:
        row = await db.get(ServiceLocation, w.locations[0].id)
        row.extra_metadata = {**row.extra_metadata, "fieldProvenance": stored}
        await db.commit()
    response = await request(w, "native", {"name": MANUAL})
    assert response.status_code == 200, response.text
    fp = (await snapshot(w))["extra_metadata"]["fieldProvenance"]
    assert fp["futureField"] == stored["futureField"]
    assert fp["name"]["futureExtra"] == stored["name"]["futureExtra"]
    assert fp["name"]["actor"] == str(w.user.id) and fp["name"]["authority"] == "manual"


@pytest.mark.parametrize("path", ["native", "upsert", "registry"])
async def test_noop_replay_with_different_actor_keeps_marker_time_source_and_audit(world, path):
    w = world
    assert (await request(w, "native", {"name": MANUAL})).status_code == 200
    before = await snapshot(w)
    async with w.factory() as db:
        actor = User(name="Synthetic second actor", email=uuid.uuid4().hex + "@example.invalid", password_hash="unused")
        db.add(actor)
        await db.flush()
        db.add(UserCompany(user_id=actor.id, company_id=w.cid, role="admin"))
        await db.commit()
    async def second_actor():
        set_request_scope(None)
        set_request_organization(None)
        return actor
    w.app.dependency_overrides[get_current_user] = second_actor
    for _ in range(2):
        response = await request(w, path, {"name": "  " + MANUAL + "  "})
        assert response.status_code == 200, response.text
    assert await snapshot(w) == before
    async with w.factory() as db:
        assert await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.company_id == w.cid)) == 0


@pytest.mark.parametrize("source", ["native.locations", "registry.objects"])
async def test_source_and_actor_without_internal_intent_do_not_infer_manual_authority(world, source):
    w = world
    await seed_sessions(w)
    async with w.factory() as db:
        await commands.update(db, w.cid, w.locations[0].id, {"name": "Synthetic legacy direct name"},
                              actor_id=w.user.id, source=source)
        await db.commit()
    assert "fieldProvenance" not in (await snapshot(w))["extra_metadata"]
    assert await refresh(w) == 1
    assert (await snapshot(w))["name"] == SOURCE


async def test_initial_create_is_explicitly_outside_edit_marker_slice(world):
    w = world
    identifier = "initial-" + uuid.uuid4().hex[:15]
    response = await w.client.post("/api/locations", json={"id": identifier, "company_id": str(w.cid),
        "code": identifier, "name": "Synthetic initial name"})
    assert response.status_code == 200, response.text
    assert "fieldProvenance" not in (response.json()["metadata"] or {})


@pytest.mark.parametrize("path", ["native", "upsert", "registry"])
async def test_changed_manual_name_then_replay_produces_single_registry_audit(world, path):
    w = world
    response = await request(w, path, {"name": MANUAL})
    assert response.status_code == 200, response.text
    before = await snapshot(w)
    assert (await request(w, path, {"name": MANUAL})).status_code == 200
    assert await snapshot(w) == before
    async with w.factory() as db:
        events = (await db.scalars(select(AuditEvent).where(AuditEvent.company_id == w.cid))).all()
    assert len(events) == (1 if path == "registry" else 0)
    if events:
        details = json.loads(events[0].details)
        assert details["name"]["to"] == MANUAL
        assert details["extra_metadata"]["to"]["fieldProvenance"] == before["extra_metadata"]["fieldProvenance"]


@pytest.mark.parametrize("path", ["native", "upsert", "registry"])
async def test_projection_or_registry_audit_failure_rolls_back_name_and_provenance(world, path, monkeypatch):
    w = world
    before = await snapshot(w)
    async def failure(*args, **kwargs):
        raise RuntimeError("synthetic failure after real mutation")
    if path == "registry":
        monkeypatch.setattr(space_registry, "_audit", failure)
    else:
        monkeypatch.setattr(space_projection, "project_object", failure)
    response = await request(w, path, {"name": MANUAL})
    assert response.status_code == 500
    assert await snapshot(w) == before


@pytest.mark.parametrize("scope", [[], ["not-this-synthetic-point"]])
async def test_current_object_context_denies_internal_manual_intent(world, scope):
    w = world
    before = await snapshot(w)
    set_request_scope(scope)
    async with w.factory() as db:
        if scope == []:
            with pytest.raises(commands.LocationConflict) as error:
                await commands.update(db, w.cid, w.locations[0].id, {"name": MANUAL},
                    actor_id=w.user.id, source="native.locations", name_intent="manual")
            assert error.value.status == 404
        else:
            assert await commands.update(db, w.cid, w.locations[0].id, {"name": MANUAL},
                actor_id=w.user.id, source="native.locations", name_intent="manual") is None
        await db.rollback()
    assert await snapshot(w) == before


async def test_foreign_upsert_cannot_stamp_an_owned_point_in_another_company(world):
    w = world
    before = await snapshot(w)
    response = await request(w, "upsert", {"name": MANUAL}, company=w.foreign)
    assert response.status_code == 404, response.text
    assert await snapshot(w) == before


@pytest.mark.parametrize("case", ["objects", "organization"])
@pytest.mark.parametrize("path", ["native", "upsert", "registry"])
async def test_actual_wrapper_admission_is_not_expanded_by_manual_intent(world, case, path):
    w = world
    async with w.factory() as db:
        member = await db.get(UserCompany, (w.user.id, w.cid))
        member.role = "user"
        if case == "objects":
            member.object_scope = [w.locations[1].id]
        else:
            org = Organization(company_id=w.cid, name="Synthetic unmatched organization", inn="000000000099")
            db.add(org)
            await db.flush()
            member.own_organization_id = org.id
        await db.commit()
    before = await snapshot(w)
    response = await request(w, path, {"name": MANUAL})
    assert response.status_code == (403 if path == "registry" else 404), response.text
    assert await snapshot(w) == before


async def native_in_transaction(w, db, name):
    return await locations_router.update_location(w.locations[0].id,
        locations_router.LocationUpdate(name=name), db=db, current_user=w.user)


async def test_manual_lock_first_w10_rechecks_current_row_guard_after_wait(world, record_property):
    w = world
    await seed_sessions(w)
    before = await snapshot(w)
    async with w.factory() as manual, w.factory() as session_writer, w.factory() as observer:
        a, b = await pid(manual), await pid(session_writer)
        await native_in_transaction(w, manual, MANUAL)
        pending = asyncio.create_task(refresh_location_names(session_writer, w.cid))
        try:
            edge = await observed_block(observer, b, a)
            record_property("manual_first_w10_wait", json.dumps(edge))
            await manual.commit()
            assert await asyncio.wait_for(pending, 7) == 0
            await session_writer.commit()
        finally:
            await stop_tasks(pending)
            await session_writer.rollback()
    after = await snapshot(w)
    assert after["name"] == MANUAL and after["extra_metadata"]["nameHistory"] == before["extra_metadata"]["nameHistory"]
    assert_marker(after, w, "native.locations")


@pytest.mark.parametrize("source_end", ["commit", "rollback"])
async def test_w10_first_manual_reload_preserves_actual_history_and_final_intent(world, source_end, record_property):
    w = world
    await seed_sessions(w)
    before = await snapshot(w)
    async with w.factory() as source, w.factory() as manual, w.factory() as observer:
        a, b = await pid(source), await pid(manual)
        assert await refresh_location_names(source, w.cid) == 1
        pending = asyncio.create_task(native_in_transaction(w, manual, MANUAL))
        try:
            edge = await observed_block(observer, b, a)
            record_property("w10_first_manual_wait", json.dumps(edge))
            await getattr(source, source_end)()
            await asyncio.wait_for(pending, 7)
            await manual.commit()
        finally:
            await stop_tasks(pending)
            await manual.rollback()
    after = await snapshot(w)
    assert after["name"] == MANUAL
    assert after["extra_metadata"]["nameHistory"] == before["extra_metadata"]["nameHistory"] + (
        [before["name"]] if source_end == "commit" else [])
    assert_marker(after, w, "native.locations")
    assert await refresh(w) == 0


@pytest.mark.parametrize("incoming", [None, "client-scalar", {"name": {"authority": "manual"}}])
async def test_unmarked_point_cannot_get_client_supplied_provenance(world, incoming):
    w = world
    await seed_sessions(w)
    response = await request(w, "native", {"metadata": {"fieldProvenance": incoming}})
    assert response.status_code == 200, response.text
    assert "fieldProvenance" not in (await snapshot(w))["extra_metadata"]
    assert await refresh(w) == 1


@pytest.mark.parametrize("path", ["native", "upsert", "registry"])
async def test_explicit_unmarked_name_noop_is_not_retroactively_marked(world, path):
    w = world
    await seed_sessions(w)
    before = await snapshot(w)
    response = await request(w, path, {"name": before["name"]})
    assert response.status_code == 200, response.text
    assert await snapshot(w) == before
    assert await refresh(w) == 1


@pytest.mark.parametrize("path,body", [("native", {"description": "Synthetic description"}),
                                      ("registry", {"description": "Synthetic description"}),
                                      ("registry", {"name": None})])
async def test_omitted_or_registry_excluded_null_name_does_not_claim_manual_intent(world, path, body):
    w = world
    await seed_sessions(w)
    response = await request(w, path, body)
    assert response.status_code == 200, response.text
    assert "fieldProvenance" not in (await snapshot(w))["extra_metadata"]
    assert await refresh(w) == 1


@pytest.mark.parametrize("name_marker", [VALID_STORED["name"], {"authority": "manual"}])
async def test_w10_preserves_current_manual_marker_without_repairing_its_shape(world, name_marker):
    w = world
    await seed_sessions(w)
    async with w.factory() as db:
        row = await db.get(ServiceLocation, w.locations[0].id)
        row.extra_metadata = {**row.extra_metadata, "fieldProvenance": {"name": name_marker}}
        await db.commit()
    before = await snapshot(w)
    assert await refresh(w) == 0
    assert await snapshot(w) == before
