"""CORE-B02 synthetic PostgreSQL contract tests. Written, NOT RUN.

ROOT must review the adjacent JSON/Markdown fixture contract and provision the
disposable schema first. Use --noconftest; this module does not use app.main,
global db/world fixtures, startup, create_all, migrations or schema cleanup.
These are direct-router/service tests, not HTTP authentication/DTO acceptance.
"""
from __future__ import annotations

import hashlib
from datetime import date
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import SkipTest
import uuid

FLAG = "RUN_SERVICE_LOCATION_WRITER_CONVERGENCE_TESTS"
if os.environ.get(FLAG) != "1":
    raise SkipTest(FLAG + "=1 required; CORE-B02 tests are opt-in")

# This helper is stdlib-only. No app/framework imports precede these guards.
from tests.partner_test_safety import partner_test_safety_error

if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)
if "app.main" in sys.modules or "app.config" in sys.modules:
    raise RuntimeError("Use a fresh ROOT process with --noconftest")
if Path(".env").exists():
    raise RuntimeError("Run from a ROOT synthetic directory without .env")
if os.environ.get("SERVICE_LOCATION_WRITER_SCHEMA_READY") != "1":
    raise RuntimeError("ROOT-provisioned disposable schema acknowledgement required")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    AuditEvent, Company, EzsEquipmentDocument, EzsEquipmentMovement,
    EzsEquipmentUnit, EzsSpareDocument, EzsSparePart, EzsSparePartMovement,
    EzsSparePartStock, EzsSupplyDocument, ObjectLink, ServiceLocation, User, UserCompany,
)
from app.routers import equipment_router as ER, locations_router as LR
from app.scope import (
    current_object_scope, current_organization, install_orm_scope,
    set_request_organization, set_request_scope,
)
from app.services import ezs_equipment as E, ezs_equipment_docs as D
from app.services import location_commands as LC

pytestmark = pytest.mark.asyncio

# Production installs this in main. Here it is installed explicitly once, in
# this fresh process; tests exercise the actual ORM listener, including db.get.
install_orm_scope()


class InjectedFailure(Exception):
    pass


@pytest_asyncio.fixture
async def world(monkeypatch):
    """Bounded synthetic inserts only; ROOT owns disposal of the entire DB.

    Each case gets fresh tenants. There is deliberately no DROP/TRUNCATE or
    cleanup cascade. Independent sessions see committed seed and rollback state.
    """
    set_request_scope(None)
    set_request_organization(None)
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"], pool_size=3, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:12]
    async with factory() as db:
        # Read-only preflight. ROOT supplies all columns, FKs and constraints;
        # merely having these table names is not a schema-equivalence proof.
        for table in (
            "companies", "users", "user_companies", "service_locations", "audit_events",
            "ezs_equipment_units", "ezs_equipment_movements", "ezs_equipment_documents",
            "ezs_spare_parts", "ezs_spare_part_stock", "ezs_spare_part_movements",
            "ezs_spare_documents", "ezs_supply_documents",
            "object_links",
        ):
            assert await db.scalar(text("SELECT to_regclass(:table)"), {"table": table}), table
        companies = [Company(name="Synthetic B02 " + suffix + str(i), slug="b02-" + suffix + str(i),
                             profile_id="energy") for i in range(2)]
        actor = User(name="Synthetic member", email=suffix + "@example.invalid", password_hash="unused")
        db.add_all([*companies, actor])
        await db.flush()
        db.add(UserCompany(user_id=actor.id, company_id=companies[0].id, role="admin"))
        locations = [ServiceLocation(
            id="b02-" + suffix + str(i), company_id=companies[0].id if i < 2 else companies[1].id,
            code="synthetic-code-" + str(i), name="Synthetic warehouse " + str(i),
            type="warehouse" if i != 1 else "ev_charging", status="active", operational_status="unknown",
            address="Synthetic address", station_number="legacy-number",
            source_bindings=[{"sourceId": "synthetic-source"}],
            extra_metadata={"warehouse": {"ownership": "own", "phone": "old-phone", "note": "old-note"},
                            "opaque": {"nested": [1, {"legacy": True}]},
                            "numberHistory": [{"number": "historical"}], "number": "legacy-number"},
        ) for i in range(3)]
        db.add_all(locations)
        await db.commit()
    w = SimpleNamespace(factory=factory, cid=companies[0].id, foreign=companies[1].id,
                        actor=actor, locations=locations, effects=[], projection_result={"sent": 1},
                        projection_error=False, suffix=suffix)

    async def stations(db, cid, ids):
        w.effects.append(("stations", cid, tuple(ids)))
        return {}

    async def projection(db, cid, identifier):
        row = await db.get(ServiceLocation, identifier)
        audits = (await db.scalars(select(AuditEvent).where(AuditEvent.company_id == cid))).all()
        # Effects observe the flushed new status and the outer audit. This
        # observer performs no network calls and does not commit.
        w.effects.append(("projection", cid, identifier, row.operational_status,
                          [a.action for a in audits]))
        if w.projection_error:
            raise InjectedFailure("unexpected downstream exception")
        return w.projection_result

    monkeypatch.setattr(LR, "stations_by_location", stations)
    monkeypatch.setattr(LR.space_projection, "project_object", projection)
    try:
        yield w
    finally:
        set_request_scope(None)
        set_request_organization(None)
        await engine.dispose()


async def snapshot(w):
    """Independent committed oracle; never reuses a warm identity map."""
    async with w.factory() as db:
        rows = (await db.scalars(select(ServiceLocation).where(
            ServiceLocation.company_id.in_([w.cid, w.foreign])).order_by(ServiceLocation.id))).all()
        audits = (await db.scalars(select(AuditEvent).where(
            AuditEvent.company_id.in_([w.cid, w.foreign])).order_by(AuditEvent.id))).all()
        stocks = (await db.scalars(select(EzsSparePartStock).where(
            EzsSparePartStock.company_id.in_([w.cid, w.foreign])).order_by(EzsSparePartStock.id))).all()
        links = (await db.scalars(select(ObjectLink).where(
            ObjectLink.company_id.in_([w.cid, w.foreign])).order_by(ObjectLink.id))).all()
        history = {}
        for cls in (EzsEquipmentUnit, EzsEquipmentMovement, EzsEquipmentDocument,
                    EzsSparePartMovement, EzsSpareDocument, EzsSupplyDocument):
            records = (await db.scalars(select(cls).where(cls.company_id.in_(
                [w.cid, w.foreign])).order_by(cls.id))).all()
            history[cls.__tablename__] = [
                {column.name: getattr(record, column.name) for column in cls.__table__.columns}
                for record in records]
        return {"rows": {r.id: {k: getattr(r, k) for k in (
                    "company_id", "code", "name", "type", "status", "operational_status", "address",
                    "station_number", "source_bindings", "extra_metadata")} for r in rows},
                "audits": [(str(a.id), a.action, json.loads(a.details)) for a in audits],
                "audit_actors": [(a.company_id, a.user_id, a.user_name) for a in audits],
                "stocks": [(str(s.id), s.location_id, str(s.qty)) for s in stocks], "history": history,
                "links": [{column.name: getattr(link, column.name) for column in ObjectLink.__table__.columns}
                          for link in links]}


async def scoped_member(w):
    async with w.factory() as db:
        member = await db.get(UserCompany, (w.actor.id, w.cid))
        member.role, member.object_scope = "user", [w.locations[1].id]
        await db.commit()


async def op(db, w, status, identifier=None):
    return await LR.set_operational_status(identifier or w.locations[1].id,
        LR.OpStatusBody(status=status, reason="Synthetic reason"), db=db, current_user=w.actor)


@pytest.mark.parametrize("status", ["working", "no_link", "disabled", "not_working",
                                    "on_repair", "maintenance", "unknown", "decommissioned"])
async def test_op_status_and_noop_preserve_audit_projection_and_outer_commit(world, status):
    w = world
    before = await snapshot(w)
    async with w.factory() as db:
        await db.begin()
        root = db.sync_session.get_transaction()
        out = await op(db, w, status)
        assert out.operationalStatus == status
        assert db.sync_session.get_transaction() is root and root.is_active
        assert await snapshot(w) == before  # includes same-status no-op audit
        await db.commit()
    after = await snapshot(w)
    expected = dict(before["rows"][w.locations[1].id], operational_status=status)
    assert after["rows"][w.locations[1].id] == expected
    assert after["rows"][w.locations[0].id] == before["rows"][w.locations[0].id]
    assert after["rows"][w.locations[2].id] == before["rows"][w.locations[2].id]
    assert len(after["audits"]) == 1
    assert after["audits"][0][1:] == ("location_op_status", {
        "location_id": w.locations[1].id, "from": "unknown", "to": status, "reason": "Synthetic reason"})
    assert after["audit_actors"] == [(w.cid, str(w.actor.id), w.actor.name)]
    assert [e[0] for e in w.effects] == ["stations", "projection"]
    assert w.effects[1][3:] == (status, ["location_op_status"])


@pytest.mark.parametrize("identifier_index", [0, 2, None])
async def test_op_invalid_status_precedes_target_admission(world, identifier_index):
    w = world
    before = await snapshot(w)
    identifier = "missing-synthetic" if identifier_index is None else w.locations[identifier_index].id
    async with w.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await op(db, w, "invalid-synthetic", identifier)
        assert exc.value.status_code == 400
        await db.rollback()
    assert await snapshot(w) == before and w.effects == []


@pytest.mark.parametrize("raised", [False, True])
async def test_op_projection_returned_failure_vs_exception_rollback(world, raised):
    w = world
    before = await snapshot(w)
    w.projection_result, w.projection_error = {"failed": 1, "sent": 0}, raised
    async with w.factory() as db:
        if raised:
            with pytest.raises(InjectedFailure):
                await op(db, w, "working")
            await db.rollback()
        else:
            assert (await op(db, w, "working")).operationalStatus == "working"
            await db.commit()
    after = await snapshot(w)
    if raised:
        assert after == before
    else:
        assert after["rows"][w.locations[1].id]["operational_status"] == "working"
        assert len(after["audits"]) == 1
    assert [e[0] for e in w.effects] == ["stations", "projection"]


async def test_op_foreign_company_no_audit_or_effect(world):
    w = world
    before = await snapshot(w)
    async with w.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await op(db, w, "working", w.locations[2].id)
        assert exc.value.status_code == 404
        await db.rollback()
    assert await snapshot(w) == before and not w.effects


@pytest.mark.parametrize("flow", ["operational", "rename", "close", "delete"])
@pytest.mark.parametrize("warm", [False, True])
async def test_existing_object_ceiling_before_mutation_even_warm(world, flow, warm):
    w = world
    await scoped_member(w)
    before = await snapshot(w)
    async with w.factory() as db:
        held = await db.get(ServiceLocation, w.locations[0].id) if warm else None
        set_request_scope([w.locations[1].id])
        with pytest.raises(HTTPException) as exc:
            if flow == "operational":
                await op(db, w, "working", w.locations[0].id)
            elif flow == "rename":
                await ER.warehouse_update(w.locations[0].id, ER.WarehouseIn(name="Denied"),
                                          company_id=str(w.cid), user=w.actor, db=db)
            elif flow == "close":
                await ER.warehouse_status(w.locations[0].id, ER.WarehouseStatusIn(closed=True),
                                          company_id=str(w.cid), user=w.actor, db=db)
            else:
                await ER.warehouse_delete(w.locations[0].id, company_id=str(w.cid), user=w.actor, db=db)
        assert exc.value.status_code == 404
        if held is not None:
            assert held.name == before["rows"][held.id]["name"] and held.status == "active"
        await db.rollback()
    set_request_scope(None)
    assert await snapshot(w) == before and not w.effects


@pytest.mark.parametrize("warm", [False, True])
async def test_op_effective_context_ceiling_is_checked_even_with_unrestricted_membership(world, warm):
    w = world  # Membership remains admin/full; current context is narrower.
    before = await snapshot(w)
    async with w.factory() as db:
        held = await db.get(ServiceLocation, w.locations[0].id) if warm else None
        set_request_scope([w.locations[1].id])
        with pytest.raises(HTTPException) as exc:
            await op(db, w, "working", w.locations[0].id)
        assert exc.value.status_code == 404
        if held is not None:
            assert held.operational_status == "unknown"
        await db.rollback()
    set_request_scope(None)
    assert await snapshot(w) == before and not w.effects


@pytest.mark.parametrize("flow", ["rename", "close", "delete"])
@pytest.mark.parametrize("target", ["foreign", "wrong_type", "no_membership"])
async def test_warehouse_tenant_type_and_member_denial(world, flow, target):
    w = world
    before = await snapshot(w)
    identifier = w.locations[1 if target == "wrong_type" else 2].id
    cid = w.foreign if target == "no_membership" else w.cid
    async with w.factory() as db:
        with pytest.raises(HTTPException) as exc:
            if flow == "rename":
                await ER.warehouse_update(identifier, ER.WarehouseIn(name="Denied"),
                                          company_id=str(cid), user=w.actor, db=db)
            elif flow == "close":
                await ER.warehouse_status(identifier, ER.WarehouseStatusIn(closed=True),
                                          company_id=str(cid), user=w.actor, db=db)
            else:
                await ER.warehouse_delete(identifier, company_id=str(cid), user=w.actor, db=db)
        assert exc.value.status_code == (403 if target == "no_membership" else 404)
        await db.rollback()
    assert await snapshot(w) == before


async def test_warehouse_partial_patch_preserves_subtrees_identity_and_null_rules(world):
    w = world
    before = await snapshot(w)
    async with w.factory() as db:
        card = await ER.warehouse_update(w.locations[0].id, ER.WarehouseIn(
            name="  Renamed synthetic  ", phone=None, address="   "),
            company_id=str(w.cid), user=w.actor, db=db)
        assert card["name"] == "Renamed synthetic" and card["phone"] is None
        assert card["note"] == "old-note" and card["address"] is None
        assert await snapshot(w) == before
        await db.commit()
    after = await snapshot(w)
    old, new = before["rows"][w.locations[0].id], after["rows"][w.locations[0].id]
    assert after["rows"].keys() == before["rows"].keys()
    for key in ("company_id", "code", "station_number", "source_bindings", "status", "operational_status"):
        assert new[key] == old[key]
    assert new["extra_metadata"]["opaque"] == old["extra_metadata"]["opaque"]
    assert new["extra_metadata"]["numberHistory"] == old["extra_metadata"]["numberHistory"]
    assert new["extra_metadata"]["number"] == old["extra_metadata"]["number"]
    assert new["extra_metadata"]["warehouse"]["updatedAt"]
    assert after["audits"] == [] and w.effects == []


async def test_warehouse_details_autoflush_before_real_mol_lookup_preserves_old_phase(world, monkeypatch):
    w = world
    before = await snapshot(w)
    observed = []
    async with w.factory() as db:
        original_get = db.get

        async def observe_get(model, identifier, *args, **kwargs):
            result = await original_get(model, identifier, *args, **kwargs)
            if model is User and identifier == w.actor.id:
                # The actual User SELECT above must have autoflushed details,
                # before the old warehouse metadata assignment point.
                columns = ServiceLocation.__table__.c
                row = (await db.execute(select(columns.name, columns.address, columns.extra_metadata).where(
                    columns.id == w.locations[0].id))).one()
                assert row.name == "Synthetic phase rename" and row.address == "Synthetic phase address"
                assert row.extra_metadata == before["rows"][w.locations[0].id]["extra_metadata"]
                assert await snapshot(w) == before
                observed.append(identifier)
            return result

        monkeypatch.setattr(db, "get", observe_get)
        card = await D.save_warehouse(db, w.cid, w.locations[0].id, {
            "name": "Synthetic phase rename", "address": "Synthetic phase address",
            "responsibleUserId": str(w.actor.id), "note": "Synthetic phase note"})
        assert card["responsible"] == w.actor.name and card["note"] == "Synthetic phase note"
        assert observed == [w.actor.id]
        await db.rollback()
    assert await snapshot(w) == before


async def test_warehouse_helper_lookup_is_not_form_create_or_metadata_update(world):
    w = world
    before = await snapshot(w)
    async with w.factory() as db:
        loc = await E.get_or_create_warehouse(db, w.cid, "  SYNTHETIC WAREHOUSE 0  ")
        assert loc.id == w.locations[0].id
        await db.commit()
    assert await snapshot(w) == before
    async with w.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await ER.warehouse_create(ER.WarehouseIn(name=" synthetic warehouse 0 "),
                                      company_id=str(w.cid), user=w.actor, db=db)
        assert exc.value.status_code == 409
        await db.rollback()
    assert await snapshot(w) == before


async def test_warehouse_create_exact_trimmed_identity_and_outer_rollback(world):
    w = world
    before = await snapshot(w)
    name = "Synthetic new " + w.suffix
    expected_id = "wh-" + hashlib.md5(f"{w.cid}|{name.lower()}".encode()).hexdigest()[:20]
    async with w.factory() as db:
        await db.begin()
        root = db.sync_session.get_transaction()
        card = await ER.warehouse_create(ER.WarehouseIn(name="  " + name + " ", note="fresh"),
                                         company_id=str(w.cid), user=w.actor, db=db)
        assert card["id"] == expected_id and card["name"] == name and card["note"] == "fresh"
        loc = await db.get(ServiceLocation, expected_id)
        assert loc.code == name and loc.type == "warehouse" and loc.status == "active"
        assert db.sync_session.get_transaction() is root and root.is_active
        assert await snapshot(w) == before
        await db.rollback()
    assert await snapshot(w) == before


async def test_warehouse_create_late_validation_failure_rolls_back_new_row_and_pending_work(world):
    w = world
    before = await snapshot(w)
    async with w.factory() as db:
        pending = await db.get(ServiceLocation, w.locations[1].id)
        pending.description = "Synthetic pending caller edit"
        with pytest.raises(HTTPException) as exc:
            await ER.warehouse_create(ER.WarehouseIn(name="Synthetic invalid " + w.suffix, ownership="rent"),
                                      company_id=str(w.cid), user=w.actor, db=db)
        assert exc.value.status_code == 400
        await db.rollback()
    assert await snapshot(w) == before
    async with w.factory() as db:
        assert (await db.get(ServiceLocation, w.locations[1].id)).description is None


async def test_new_form_warehouse_legacy_scope_exception_does_not_admit_later_existing_edit(world):
    w = world
    await scoped_member(w)
    before = await snapshot(w)
    async with w.factory() as db:
        card = await ER.warehouse_create(ER.WarehouseIn(name="Synthetic scoped new " + w.suffix, note="fresh"),
                                         company_id=str(w.cid), user=w.actor, db=db)
        assert card["note"] == "fresh" and current_object_scope() == [w.locations[1].id]
        identifier = card["id"]
        assert identifier not in current_object_scope()
        await db.commit()
    # End the creation request; observer/reset is outside the domain operation.
    set_request_scope(None)
    created = await snapshot(w)
    assert created["rows"][identifier]["type"] == "warehouse"
    assert len(created["rows"]) == len(before["rows"]) + 1
    for key, row in before["rows"].items():
        assert created["rows"][key] == row
    async with w.factory() as db:
        held = await db.get(ServiceLocation, identifier)
        with pytest.raises(HTTPException) as exc:
            await ER.warehouse_update(identifier, ER.WarehouseIn(note="Denied later edit"),
                                      company_id=str(w.cid), user=w.actor, db=db)
        assert exc.value.status_code == 404
        assert held.extra_metadata["warehouse"]["note"] == "fresh"
        await db.rollback()
    set_request_scope(None)
    assert await snapshot(w) == created


@pytest.mark.parametrize("boundary", ["commit_new_root", "rollback_new_root", "cross_session"])
async def test_new_warehouse_initialization_cannot_cross_root_or_session(world, boundary):
    w = world
    before = await snapshot(w)
    name = "Synthetic boundary " + w.suffix
    set_request_scope([w.locations[1].id])
    async with w.factory() as db:
        loc = await E.get_or_create_warehouse(db, w.cid, name)
        identifier = loc.id
        if boundary == "cross_session":
            async with w.factory() as other:
                await other.begin()
                with pytest.raises(LC.LocationConflict) as exc:
                    await LC.update_warehouse_details(other, w.cid, loc, name="Denied cross-session",
                                                       address=None, address_given=False)
                assert exc.value.status == 404
                await other.rollback()
            await db.rollback()
        else:
            if boundary == "commit_new_root":
                await db.commit()
            else:
                await db.rollback()
            await db.begin()
            with pytest.raises(LC.LocationConflict) as exc:
                await LC.update_warehouse_details(db, w.cid, loc, name="Denied new-root",
                                                   address=None, address_given=False)
            assert exc.value.status == 404
            await db.rollback()
    set_request_scope(None)
    after = await snapshot(w)
    if boundary == "commit_new_root":
        assert after["rows"][identifier]["name"] == name
        assert after["rows"][identifier]["extra_metadata"] is None
        assert len(after["rows"]) == len(before["rows"]) + 1
        assert after["audits"] == []
    else:
        assert after == before


@pytest.mark.parametrize("boundary", ["consumed", "card_before_details", "existing_entry", "different_loaded_target"])
async def test_new_warehouse_initialization_is_not_an_existing_object_permission(world, boundary):
    w = world
    before = await snapshot(w)
    async with w.factory() as db:
        hidden = await db.get(ServiceLocation, w.locations[0].id)
        set_request_scope([w.locations[1].id])
        loc = await E.get_or_create_warehouse(db, w.cid, "Synthetic scoped init " + w.suffix)
        target = loc
        if boundary in {"consumed", "card_before_details"}:
            if boundary == "card_before_details":
                with pytest.raises(LC.LocationConflict) as exc:
                    await LC.update_warehouse_card(db, w.cid, loc, warehouse={"ownership": "own"})
                assert exc.value.status == 404
            await LC.update_warehouse_details(db, w.cid, loc, name=None, address=None, address_given=False)
            await LC.update_warehouse_card(db, w.cid, loc, warehouse={"ownership": "own"})
        elif boundary == "existing_entry":
            with pytest.raises(LC.LocationConflict) as exc:
                await LC.warehouse_for_mutation(db, w.cid, loc.id)
            assert exc.value.status == 404
        else:
            target = hidden
        with pytest.raises(LC.LocationConflict) as exc:
            await LC.update_warehouse_details(db, w.cid, target, name="Denied existing permission",
                                               address=None, address_given=False)
        assert exc.value.status == 404
        with pytest.raises(LC.LocationConflict) as exc:
            await LC.update_warehouse_card(db, w.cid, target, warehouse={"ownership": "own", "note": "Denied"})
        assert exc.value.status == 404
        await db.rollback()
    set_request_scope(None)
    assert await snapshot(w) == before


@pytest.mark.parametrize("operation", ["operational", "lifecycle", "delete"])
async def test_new_warehouse_initialization_never_bypasses_other_commands(world, operation):
    w = world
    before = await snapshot(w)
    set_request_scope([w.locations[1].id])
    async with w.factory() as db:
        loc = await E.get_or_create_warehouse(db, w.cid, "Synthetic scoped other " + w.suffix)
        with pytest.raises(LC.LocationConflict) as exc:
            if operation == "operational":
                await LC.set_operational_status(db, w.cid, loc, "working")
            elif operation == "lifecycle":
                await LC.set_warehouse_status(db, w.cid, loc, True)
            else:
                await LC.delete_unused_warehouse(db, w.cid, loc)
        assert exc.value.status == 404
        assert loc.operational_status == "unknown" and loc.status == "active"
        await db.rollback()
    set_request_scope(None)
    assert await snapshot(w) == before


async def test_renamed_warehouse_original_name_keeps_pk_collision_and_outer_rollback(world):
    w = world
    original = "Synthetic collision " + w.suffix
    async with w.factory() as db:
        card = await ER.warehouse_create(ER.WarehouseIn(name=original), company_id=str(w.cid), user=w.actor, db=db)
        identifier = card["id"]
        await db.commit()
    async with w.factory() as db:
        await ER.warehouse_update(identifier, ER.WarehouseIn(name="Synthetic renamed " + w.suffix),
                                  company_id=str(w.cid), user=w.actor, db=db)
        await db.commit()
    before = await snapshot(w)
    async with w.factory() as db:
        with pytest.raises(IntegrityError):
            await ER.warehouse_create(ER.WarehouseIn(name=original), company_id=str(w.cid), user=w.actor, db=db)
        await db.rollback()
    assert await snapshot(w) == before
    assert before["rows"][identifier]["code"] == original


async def seed_link(w, end, closed, *, foreign=False):
    async with w.factory() as db:
        link = ObjectLink(company_id=w.foreign if foreign else w.cid,
            parent_type="point_of_service" if end == "parent" else "external",
            parent_id=w.locations[0].id if end == "parent" else "synthetic-parent-" + w.suffix,
            child_type="point_of_service" if end == "child" else "external",
            child_id=w.locations[0].id if end == "child" else "synthetic-child-" + w.suffix,
            relation="synthetic_history", valid_from=date(2020, 1, 1),
            valid_to=date(2021, 1, 1) if closed else None)
        db.add(link)
        await db.commit()
        return link.id


@pytest.mark.parametrize("end", ["parent", "child"])
@pytest.mark.parametrize("closed", [False, True])
async def test_known_opaque_history_blocks_delete_without_touching_link_or_zero_stock(world, end, closed):
    w = world
    await seed_usage(w, "zero")
    await seed_link(w, end, closed)
    before = await snapshot(w)
    async with w.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await ER.warehouse_delete(w.locations[0].id, company_id=str(w.cid), user=w.actor, db=db)
        assert exc.value.status_code == 409
        # Generic conflict must not reveal soft-reference identifiers/relations.
        assert w.suffix not in str(exc.value.detail) and "synthetic_history" not in str(exc.value.detail)
        await db.rollback()
    assert await snapshot(w) == before


@pytest.mark.parametrize("end", ["parent", "child"])
async def test_foreign_tenant_opaque_link_is_neither_disclosed_nor_deleted(world, end):
    w = world
    await seed_link(w, end, True, foreign=True)
    before = await snapshot(w)
    async with w.factory() as db:
        out = await ER.warehouse_delete(w.locations[0].id, company_id=str(w.cid), user=w.actor, db=db)
        assert out == {"deleted": w.locations[0].id, "name": w.locations[0].name}
        await db.commit()
    after = await snapshot(w)
    assert after["links"] == before["links"]
    assert w.locations[0].id not in after["rows"]
    assert len(after["audits"]) == 1 and after["audits"][0][1] == "equipment_warehouse_delete"


async def seed_usage(w, kind):
    async with w.factory() as db:
        lid = w.locations[0].id
        part = EzsSparePart(company_id=w.cid, name="Synthetic spare")
        unit = EzsEquipmentUnit(company_id=w.cid, inventory_number="synthetic-" + w.suffix,
                                current_location_id=lid if kind in {"unit", "terminal"} else None,
                                state="written_off" if kind == "terminal" else "in_stock_new")
        db.add_all([part, unit])
        await db.flush()
        row = None
        if kind in {"zero", "spares"}:
            row = EzsSparePartStock(company_id=w.cid, part_id=part.id, location_id=lid,
                                    qty=0 if kind == "zero" else 1)
        elif kind == "equipment_movement":
            row = EzsEquipmentMovement(company_id=w.cid, unit_id=unit.id, op="transfer",
                                        from_location_id=lid, occurred_on="2026-10-31")
        elif kind == "spare_movement":
            row = EzsSparePartMovement(company_id=w.cid, part_id=part.id, op="transfer", qty=1,
                                        from_location_id=lid, occurred_on="2026-10-31")
        elif kind in {"equipment_doc", "spare_doc"}:
            cls = EzsEquipmentDocument if kind == "equipment_doc" else EzsSpareDocument
            row = cls(company_id=w.cid, op="transfer", number="Synthetic-" + w.suffix,
                      doc_date="2026-10-31", from_location_id=lid)
        elif kind == "supply_doc":
            row = EzsSupplyDocument(company_id=w.cid, number="Synthetic-" + w.suffix,
                                    doc_date="2026-10-31", warehouse_id=lid)
        if row is not None:
            db.add(row)
        await db.commit()
        return row.id if row is not None else unit.id


@pytest.mark.parametrize("kind", ["unit", "spares", "equipment_movement", "spare_movement",
                                   "equipment_doc", "spare_doc", "supply_doc"])
async def test_delete_each_usage_guard_preserves_real_rows(world, kind):
    w = world
    await seed_usage(w, kind)
    before = await snapshot(w)
    async with w.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await ER.warehouse_delete(w.locations[0].id, company_id=str(w.cid), user=w.actor, db=db)
        assert exc.value.status_code == 409
        await db.rollback()
    assert await snapshot(w) == before


@pytest.mark.parametrize("kind,denied", [("unit", True), ("spares", True), ("zero", False),
                                         ("terminal", False), ("equipment_doc", False)])
async def test_close_stock_guards_and_reopen_history_contract(world, kind, denied):
    w = world
    await seed_usage(w, kind)
    before = await snapshot(w)
    async with w.factory() as db:
        if denied:
            with pytest.raises(HTTPException) as exc:
                await D.set_warehouse_status(db, w.cid, w.locations[0].id, True)
            assert exc.value.status_code == 409
            await db.rollback()
        else:
            assert (await D.set_warehouse_status(db, w.cid, w.locations[0].id, True))["status"] == "closed"
            assert await snapshot(w) == before
            await db.commit()
    if denied:
        assert await snapshot(w) == before
    else:
        async with w.factory() as db:
            assert (await D.set_warehouse_status(db, w.cid, w.locations[0].id, False))["status"] == "active"
            await db.commit()
        assert await snapshot(w) == before


@pytest.mark.parametrize("fault", [None, "after_cleanup", "outer_audit"])
async def test_zero_stock_delete_is_atomic_and_has_exactly_one_outer_audit(world, monkeypatch, fault):
    w = world
    await seed_usage(w, "zero")
    await seed_link(w, "parent", True, foreign=True)
    before = await snapshot(w)
    async with w.factory() as db:
        original_add = db.add

        async def fail_delete(row):
            # Proves this injection is after actual SQL zero-stock cleanup.
            assert await db.scalar(select(func.count()).select_from(EzsSparePartStock).where(
                EzsSparePartStock.location_id == w.locations[0].id)) == 0
            raise InjectedFailure("after real stock cleanup")

        def fail_audit(row, *args, **kwargs):
            if isinstance(row, AuditEvent) and row.action == "equipment_warehouse_delete":
                assert any(isinstance(r, ServiceLocation) and r.id == w.locations[0].id
                           for r in db.deleted)
                raise InjectedFailure("outer audit add")
            return original_add(row, *args, **kwargs)

        if fault == "after_cleanup":
            monkeypatch.setattr(db, "delete", fail_delete)
        elif fault == "outer_audit":
            monkeypatch.setattr(db, "add", fail_audit)
        if fault:
            with pytest.raises(InjectedFailure):
                await ER.warehouse_delete(w.locations[0].id, company_id=str(w.cid), user=w.actor, db=db)
            await db.rollback()
        else:
            out = await ER.warehouse_delete(w.locations[0].id, company_id=str(w.cid), user=w.actor, db=db)
            assert out == {"deleted": w.locations[0].id, "name": w.locations[0].name}
            assert await snapshot(w) == before
            await db.commit()
    after = await snapshot(w)
    if fault:
        assert after == before
    else:
        assert w.locations[0].id not in after["rows"] and after["stocks"] == []
        assert len(after["audits"]) == 1
        assert after["audits"][0][1:] == ("equipment_warehouse_delete", out)
        assert after["audit_actors"] == [(w.cid, str(w.actor.id), w.actor.name)]
        assert after["rows"][w.locations[2].id] == before["rows"][w.locations[2].id]
        assert after["links"] == before["links"]
    assert not w.effects


@pytest.mark.parametrize("flow,command", [
    ("operational", "set_operational_status"), ("rename", "update_warehouse_card"),
    ("rename", "update_warehouse_details"),
    ("close", "set_warehouse_status"), ("delete", "delete_unused_warehouse"),
    ("create", "create_warehouse"),
])
async def test_common_owner_rejection_cannot_be_bypassed(world, monkeypatch, flow, command):
    """Additional architecture oracle; real PG state tests above remain primary."""
    w = world
    before = await snapshot(w)
    calls = []

    async def deny(*args, **kwargs):
        calls.append((args, kwargs))
        raise LC.LocationConflict(409, "Synthetic owner denial")

    monkeypatch.setattr(LC, command, deny)
    async with w.factory() as db:
        expected_error = LC.LocationConflict if flow == "create" else HTTPException
        with pytest.raises(expected_error) as exc:
            if flow == "operational":
                await op(db, w, "working")
            elif flow == "rename":
                await D.save_warehouse(db, w.cid, w.locations[0].id, {"name": "Synthetic changed"})
            elif flow == "close":
                await D.set_warehouse_status(db, w.cid, w.locations[0].id, True)
            elif flow == "delete":
                await D.delete_warehouse(db, w.cid, w.locations[0].id)
            else:
                await E.get_or_create_warehouse(db, w.cid, "Synthetic brand new " + w.suffix)
        status = exc.value.status if flow == "create" else exc.value.status_code
        assert status == 409 and exc.value.detail == "Synthetic owner denial"
        await db.rollback()
    assert len(calls) == 1 and await snapshot(w) == before and not w.effects


async def test_selected_organization_is_preserved_without_new_native_join_policy(world):
    w = world
    org = uuid.uuid4()  # context selection only; no fabricated ContractLocation
    set_request_organization(org)
    async with w.factory() as db:
        await op(db, w, "working")
        assert current_organization() == org and current_object_scope() is None
        await db.rollback()
    async with w.factory() as db:
        await D.save_warehouse(db, w.cid, w.locations[0].id, {"note": "Synthetic org-context edit"})
        assert current_organization() == org and current_object_scope() is None
        await db.rollback()


@pytest.mark.parametrize("flow", ["operational", "warehouse"])
async def test_empty_legacy_context_keeps_existing_unrestricted_semantics(world, flow):
    w = world
    before = await snapshot(w)
    set_request_scope([])  # Existing scope.py treats [] as unrestricted, unlike native explicit checks.
    async with w.factory() as db:
        if flow == "operational":
            await op(db, w, "working")
        else:
            await D.save_warehouse(db, w.cid, w.locations[0].id, {"note": "Synthetic empty context"})
        assert current_object_scope() == []
        await db.rollback()
    set_request_scope(None)
    assert await snapshot(w) == before
