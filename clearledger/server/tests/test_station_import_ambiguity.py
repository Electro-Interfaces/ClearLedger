"""Opt-in actual W07/W08 PG evidence; synthetic files, real resolver and ORM.

Before-fix assertions check persisted identity/effects first, never a new symbol.
Run only after an explicit exclusive SQL grant; see the companion evidence note.
"""
from copy import deepcopy
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import uuid

import openpyxl
import pytest
import pytest_asyncio
from sqlalchemy import select

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_STATION_IMPORT_AMBIGUITY_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Opt in with {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)
target = urlsplit(os.environ["TEST_DATABASE_URL"])
if (os.environ.get("APP_ENV") != "test"
        or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]
        or target.hostname != "127.0.0.1" or target.port != 33546
        or target.path != "/api_station_import_ambiguity_test"):
    raise RuntimeError("Requires APP_ENV=test, equal DB URLs and assigned own loopback test database")

from tests.test_location_commands import world as native_world
from app.models import AuditEvent, EzsEquipmentUnit, ObjectLink, Region, ServiceLocation, SourceFile
from app.scope import install_orm_scope, set_request_organization, set_request_scope
from app.services.stations_normalize import _loc_id, ingest_stations, parse_stations_xlsx


@pytest.fixture(scope="module", autouse=True)
def actual_orm_scope():
    install_orm_scope()


@pytest_asyncio.fixture
async def world(native_world):
    w = native_world
    set_request_scope(None)
    set_request_organization(None)
    async with w.factory() as db:
        for index, loc in enumerate(w.locations):
            row = await db.get(ServiceLocation, loc.id)
            row.type = "ev_charging"
            row.station_number = "700001"
            row.serial_number = "synthetic-serial-" + str(index)
            row.operational_status = "working"
            row.power_kwt = 50 + index
            row.owner = "Synthetic contractual owner"
            row.extra_metadata = {"number": "700001", "stationId": "source-" + str(index),
                                  "ocppId": "ocpp-" + str(index), "nameHistory": ["Synthetic old name"],
                                  "numberHistory": [{"было": "synthetic-old-" + str(index)}]}
            unit = EzsEquipmentUnit(company_id=w.cid, inventory_number="inventory-" + str(index),
                                    brand="Synthetic original brand", power_kwt=80 + index,
                                    owner_name="Synthetic unit owner")
            db.add(unit)
            await db.flush()
            db.add(ObjectLink(company_id=w.cid, parent_type="point_of_service", parent_id=row.id,
                              child_type="station", child_id=str(unit.id), relation="placed_at",
                              valid_from=date(2020, 1, 1)))
        await db.commit()
    yield w
    set_request_scope(None)
    set_request_organization(None)


async def snapshot(w):
    """Fresh committed Core reads include every column, units, links, raw and audit."""
    async with w.factory() as db:
        result = {}
        for model in (ServiceLocation, EzsEquipmentUnit, ObjectLink, Region, SourceFile, AuditEvent):
            table = model.__table__
            rows = (await db.execute(select(table).where(table.c.company_id == w.cid))).mappings().all()
            result[model.__name__] = sorted((deepcopy(dict(row)) for row in rows), key=lambda r: str(r["id"]))
        return result


def source_row(family, **changes):
    row = {"number": "700001", "name": "Synthetic incoming label", "status_dev": "Нет связи",
           "region": "Synthetic import region", "brand": "Synthetic incoming brand"}
    if family == "compact":
        row.update(compact=True, ocpp_id=None, num_class="rushydro")
    else:
        row.update(ext_id="source-unknown", partial=family == "partial")
    return {**row, **changes}


def excel_bytes(family, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    if family == "compact":
        ws.title = "Stations"
        ws.append(["Номер", "Название", "OCPP ID", "Местоположение", "Протокол",
                   "Производитель", "Коннекторы", "Статус", "Владелец"])
        keys = ["number", "name", "ocpp_id", "address", "ocpp_protocol", "brand",
                "connector_types", "status_dev", "owner"]
    else:
        ws.title = "Станции"
        ws.append(["Synthetic column " + str(i) for i in range(36)])
        keys = ["ext_id", "name", "number", "serial_number", "owner_id", "owner", "region",
                "city", "street", "house", "address", "latitude", "longitude", "model", "brand",
                "connectors_count", "connector_types", "power_kwt", "ocpp_protocol", "firmware",
                "status_dev", "stage", "is_published", "is_hidden", "access_type", "location_type",
                "subsidy", "always_on", "rating", "success_pct", "unused", "is_test",
                "hubex_asset_id", "hubex_name", "hubex_link_status", "hubex_note"]
    for row in rows:
        ws.append([row.get(key) for key in keys])
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()


async def ingest(w, family, rows, mode="replace", *, parsed=False):
    """Real entry point, no resolver/new-branch mocking, caller owns final commit."""
    if parsed:
        assert family in {"compact", "full"}
        content = excel_bytes(family, rows)
        path = Path(os.environ["UPLOAD_DIR"]) / (uuid.uuid4().hex + ".xlsx")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        async with w.factory() as db:
            db.add(SourceFile(company_id=w.cid, file_name="synthetic-stations.xlsx",
                              mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              size=len(content), storage_path=str(path), fingerprint=hashlib.sha256(content).hexdigest()))
            await db.commit()
        rows = parse_stations_xlsx(content)
    async with w.factory() as db:
        result = await ingest_stations(db, w.cid, rows, mode=mode)
        await db.commit()
    return result


def evidence(record_property, result, before, after):
    record_property("actual_import", json.dumps({"result": result,
        "counts_before": {k: len(v) for k, v in before.items()},
        "counts_after": {k: len(v) for k, v in after.items()},
        "points": [{k: r[k] for k in ("id", "code", "name", "station_number", "serial_number",
                                      "operational_status")} for r in after["ServiceLocation"]]}, default=str))


def rejected_without_mutation(result, before, after):
    # Baseline fails here on actual duplicate creation / wrong point+unit+audit mutation.
    assert after == before
    assert (result["status"], result["created"], result["updated"], result["errors"]) == ("partial", 0, 0, 1)
    assert result["ambiguous"] == 1


@pytest.mark.parametrize("family", ["compact", "full", "partial"])
@pytest.mark.parametrize("mode", ["append", "replace"])
async def test_shared_number_unknown_identity_never_becomes_new(world, family, mode, record_property):
    before = await snapshot(world)
    result = await ingest(world, family, [source_row(family)], mode)
    after = await snapshot(world)
    evidence(record_property, result, before, after)
    rejected_without_mutation(result, before, after)


@pytest.mark.parametrize("family,key", [("compact", "ocppId"), ("compact", "stationId"),
                                      ("full", "stationId"), ("partial", "stationId"),
                                      ("full", "serial")])
async def test_multiple_strong_candidates_never_select_first(world, family, key, record_property):
    w = world
    async with w.factory() as db:
        for index, loc in enumerate(w.locations):
            row = await db.get(ServiceLocation, loc.id)
            if key == "serial":
                # lower(serial) index permits this legacy pair, resolver strips it.
                row.serial_number = "same-serial" if index == 0 else " same-serial "
            else:
                row.extra_metadata = {**row.extra_metadata, key: "same-key"}
        await db.commit()
    changes = ({"ocpp_id": "same-key"} if family == "compact" else
               {"serial_number": "same-serial"} if key == "serial" else {"ext_id": "same-key"})
    before = await snapshot(w)
    result = await ingest(w, family, [source_row(family, **changes)])
    after = await snapshot(w)
    evidence(record_property, result, before, after)
    rejected_without_mutation(result, before, after)


@pytest.mark.parametrize("family", ["full", "partial"])
async def test_source_points_to_p_serial_to_q_rejects_whole_row(world, family, record_property):
    before = await snapshot(world)
    result = await ingest(world, family, [source_row(family, ext_id="source-0", serial_number="synthetic-serial-1")])
    after = await snapshot(world)
    evidence(record_property, result, before, after)
    rejected_without_mutation(result, before, after)


async def test_compact_own_ocpp_mismatch_rejects_before_point_unit_and_audit(world, record_property):
    async with world.factory() as db:
        row = await db.get(ServiceLocation, world.locations[1].id)
        row.station_number = "700002"
        await db.commit()
    before = await snapshot(world)
    result = await ingest(world, "compact", [source_row("compact", ocpp_id="unowned-ocpp")])
    after = await snapshot(world)
    evidence(record_property, result, before, after)
    rejected_without_mutation(result, before, after)


async def test_ocpp_and_source_key_point_to_different_cards(world, record_property):
    async with world.factory() as db:
        other = await db.get(ServiceLocation, world.locations[1].id)
        other.extra_metadata = {**other.extra_metadata, "stationId": "ocpp-0"}
        await db.commit()
    before = await snapshot(world)
    result = await ingest(world, "compact", [source_row("compact", ocpp_id="ocpp-0")])
    after = await snapshot(world)
    evidence(record_property, result, before, after)
    rejected_without_mutation(result, before, after)


async def test_ambiguous_number_cannot_escape_through_deterministic_id_fallback(world, record_property):
    async with world.factory() as db:
        db.add(ServiceLocation(id=_loc_id(world.cid, "ocpp:700001"), company_id=world.cid,
                               code="synthetic-unrelated-key", name="Synthetic unrelated point",
                               type="ev_charging", station_number="700009", source_bindings=[],
                               extra_metadata={"ocppId": "unrelated-ocpp"}))
        await db.commit()
    before = await snapshot(world)
    result = await ingest(world, "compact", [source_row("compact")])
    after = await snapshot(world)
    evidence(record_property, result, before, after)
    rejected_without_mutation(result, before, after)


@pytest.mark.parametrize("family", ["compact", "full"])
async def test_actual_xlsx_keeps_raw_bytes_when_row_requires_reconciliation(world, family, record_property):
    content = excel_bytes(family, [source_row(family)])
    rows = parse_stations_xlsx(content)
    path = Path(os.environ["UPLOAD_DIR"]) / (uuid.uuid4().hex + ".xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    async with world.factory() as db:
        db.add(SourceFile(company_id=world.cid, file_name="synthetic.xlsx", storage_path=str(path),
                          size=len(content), fingerprint=hashlib.sha256(content).hexdigest()))
        await db.commit()
    before = await snapshot(world)
    result = await ingest(world, family, rows)
    after = await snapshot(world)
    evidence(record_property, result, before, after)
    assert path.read_bytes() == content
    rejected_without_mutation(result, before, after)


@pytest.mark.parametrize("family", ["compact", "full", "partial"])
@pytest.mark.parametrize("mode", ["append", "replace"])
async def test_unique_stronger_identity_preserves_both_legacy_shared_number_cards(world, family, mode):
    w = world
    before = await snapshot(w)
    rows = [source_row(family, **({"ocpp_id": "ocpp-" + str(i)} if family == "compact" else
                                  {"ext_id": "source-" + str(i), "serial_number": "synthetic-serial-" + str(i)}))
            for i in range(2)]
    result = await ingest(w, family, rows, mode)
    after = await snapshot(w)
    expected = (0, 0, 2) if mode == "append" else (0, 2, 0)
    assert (result["created"], result["updated"], result["skipped"]) == expected
    assert result["status"] == "success" and result["errors"] == result["ambiguous"] == 0
    assert len(after["ServiceLocation"]) == 2
    for old in before["ServiceLocation"]:
        new = next(row for row in after["ServiceLocation"] if row["id"] == old["id"])
        for key in ("code", "station_number", "source_bindings"):
            assert new[key] == old[key]
        assert new["extra_metadata"]["numberHistory"] == old["extra_metadata"]["numberHistory"]
        assert new["operational_status"] == ("working" if mode == "append" else "no_link")
        # Full replace clears omitted nullable passport values; partial/compact preserve them.
        assert new["power_kwt"] == (None if family == "full" and mode == "replace" else old["power_kwt"])
        assert new["owner"] == (None if family == "full" and mode == "replace" else old["owner"])
    assert after["ObjectLink"] == before["ObjectLink"]
    assert [r["inventory_number"] for r in after["EzsEquipmentUnit"]] == [r["inventory_number"] for r in before["EzsEquipmentUnit"]]
    if mode == "append":
        assert after == before


@pytest.mark.parametrize("family", ["full", "partial"])
async def test_serial_enrichment_with_new_source_id_is_still_allowed(world, family):
    # Existing policy: a new source ID plus unique serial is sufficient evidence.
    result = await ingest(world, family, [source_row(family, serial_number="synthetic-serial-0")])
    after = await snapshot(world)
    assert (result["created"], result["updated"], result["errors"]) == (0, 1, 0)
    assert len(after["ServiceLocation"]) == 2
    assert next(r for r in after["ServiceLocation"] if r["id"] == world.locations[0].id)["operational_status"] == "no_link"


async def test_intentional_compact_ac_dc_pair_split_keeps_existing_behavior(world):
    async with world.factory() as db:
        row = await db.get(ServiceLocation, world.locations[1].id)
        row.station_number = "700002"
        await db.commit()
    rows = [source_row("compact", ocpp_id="ocpp-0"), source_row("compact", ocpp_id="new-dc-key")]
    result = await ingest(world, "compact", rows)
    after = await snapshot(world)
    assert (result["created"], result["updated"], result["pair_split"], result["errors"]) == (1, 1, 1, 0)
    assert len(after["ServiceLocation"]) == 3
    assert len([r for r in after["ServiceLocation"] if r["station_number"] == "700001"]) == 2
    replay = await ingest(world, "compact", rows)
    assert (replay["created"], replay["updated"], replay["errors"]) == (0, 2, 0)
    assert len((await snapshot(world))["ServiceLocation"]) == 3


@pytest.mark.parametrize("lookup", ["ocpp", "source"])
async def test_repeated_same_strong_key_is_not_a_new_ac_dc_device(world, lookup, record_property):
    w = world
    key = "ocpp-0" if lookup == "ocpp" else "source-0"
    if lookup == "source":
        async with w.factory() as db:
            row = await db.get(ServiceLocation, w.locations[0].id)
            row.extra_metadata = {k: v for k, v in row.extra_metadata.items() if k != "ocppId"}
            await db.commit()
    # Existing ID comes from native fixture, not _loc_id(company, 'ocpp:...').
    assert w.locations[0].id != _loc_id(w.cid, "ocpp:" + key)
    before = await snapshot(w)
    row = source_row("compact", ocpp_id=key)
    result = await ingest(w, "compact", [row, dict(row)])
    after = await snapshot(w)
    evidence(record_property, result, before, after)
    # First assert catches the actual duplicate, before any new result contract.
    assert len(after["ServiceLocation"]) == len(before["ServiceLocation"])
    assert {r["id"] for r in after["ServiceLocation"]} == {r["id"] for r in before["ServiceLocation"]}
    assert (result["created"], result["updated"], result["skipped"], result["errors"], result["pair_split"]) == (
        0, 1, 1, 0, 0)
    assert result["status"] == "success"
    assert len(after["AuditEvent"]) - len(before["AuditEvent"]) == 1


@pytest.mark.parametrize("family", ["full", "partial"])
async def test_repeated_same_source_id_keeps_actual_w08_update_semantics(world, family):
    row = source_row(family, ext_id="source-0", serial_number="synthetic-serial-0")
    result = await ingest(world, family, [row, dict(row)])
    after = await snapshot(world)
    assert len(after["ServiceLocation"]) == 2
    assert (result["created"], result["updated"], result["skipped"], result["errors"]) == (0, 2, 0, 0)
    assert result["status"] == "success"
    assert len(after["AuditEvent"]) == 1


@pytest.mark.parametrize("family", ["compact", "full"])
async def test_unambiguous_fresh_actual_file_create_and_replay_control(world, family):
    row = source_row(family, number="700099", ocpp_id="fresh-ocpp", ext_id="fresh-source")
    result = await ingest(world, family, [row], parsed=True)
    assert (result["created"], result["updated"], result["errors"]) == (1, 0, 0)
    points = (await snapshot(world))["ServiceLocation"]
    assert len(points) == 3
    result = await ingest(world, family, [row], parsed=True)
    assert (result["created"], result["updated"], result["errors"]) == (0, 1, 0)
    after = (await snapshot(world))["ServiceLocation"]
    assert [(r["id"], r["code"], r["station_number"]) for r in after] == [
        (r["id"], r["code"], r["station_number"]) for r in points]


@pytest.mark.parametrize("family", ["compact", "full", "partial"])
async def test_mixed_accepted_and_ambiguous_rows_preserve_only_accepted_mutation(world, family, record_property):
    changes = {"ocpp_id": "ocpp-0"} if family == "compact" else {"ext_id": "source-0"}
    before = await snapshot(world)
    result = await ingest(world, family, [source_row(family, **changes), source_row(family)])
    after = await snapshot(world)
    evidence(record_property, result, before, after)
    assert len(after["ServiceLocation"]) == 2
    untouched = next(r for r in before["ServiceLocation"] if r["id"] == world.locations[1].id)
    assert next(r for r in after["ServiceLocation"] if r["id"] == untouched["id"]) == untouched
    assert (result["status"], result["created"], result["updated"], result["errors"], result["ambiguous"]) == (
        "partial", 0, 1, 1, 1)
    assert len(after["AuditEvent"]) - len(before["AuditEvent"]) == 1


async def test_reconciliation_count_remains_exact_while_details_are_bounded(world, record_property):
    before = await snapshot(world)
    result = await ingest(world, "compact", [source_row("compact") for _ in range(55)])
    after = await snapshot(world)
    evidence(record_property, result, before, after)
    assert after == before
    assert (result["created"], result["updated"], result["errors"], result["ambiguous"]) == (0, 0, 55, 55)
    assert result["status"] == "partial"
    # Tentative additive result shape, subject to coordinator approval.
    assert result["reconciliation_count"] == 55
    assert len(result["reconciliation"]) == 50
    assert all(set(item) == {"rowOrdinal", "sourceKind", "reasonCode", "retryable"}
               for item in result["reconciliation"])
    assert [item["rowOrdinal"] for item in result["reconciliation"]] == list(range(1, 51))
    assert all(item["reasonCode"] == "ambiguous_identity" and item["retryable"] is False
               for item in result["reconciliation"])
