"""Физический разъём из листа коннекторов: составной ключ и безопасное восстановление."""
import io
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import openpyxl
import pytest

from app.models import Company, ServiceLocation
from app.services.asuim_normalize import ingest_asuim_book, map_sessions
from app.services.asuim_session_connectors import (
    build_session_connector_index, load_session_connector_index, resolve_session_connector,
)
from scripts.repair_session_connectors import connector_repair_plan


def connector(station="s1", external=1, number=2, kind="CCS2"):
    return {"id_станции": station, "id_коннектора": external,
            "номер_коннектора": number, "тип": kind}


def source(station="s1", external=1, **extra):
    return {"id_сессии": "session-1", "id_станции": station, "id_коннектора": external,
            "дата_начала": datetime(2026, 10, 1, 10),
            "дата_окончания": datetime(2026, 10, 1, 11), "тип_коннектора": "CCS2",
            "энергия_квтч": 10, **extra}


def test_repeated_connector_id_is_scoped_by_station_and_preserves_equal_types():
    index = build_session_connector_index([connector(), connector("s2", 1, 3), connector("s1", 2, 4)])
    assert map_sessions([source()], connector_index=index)[0]["connector_no"] == "2"
    assert resolve_session_connector(source("s2"), index) == "3"
    assert resolve_session_connector(source("s1", 2), index) == "4"
    assert resolve_session_connector(source("unknown"), index) is None


def test_ambiguous_mapping_type_conflict_and_missing_reference_are_not_guessed():
    index = build_session_connector_index([connector(), connector(number=3)])
    assert resolve_session_connector(source(), index) is None
    index = build_session_connector_index([connector(kind="Type 2")])
    assert resolve_session_connector(source(), index) is None
    assert resolve_session_connector(source(), {}) is None
    assert resolve_session_connector(source(номер_коннектора=7), index) == "7"


def test_excel_numeric_ids_and_duplicate_reference_rows():
    row = connector(external=1.0, number=2.0)
    index = build_session_connector_index([row, row])
    assert resolve_session_connector(source(external=1), index) == "2"
    assert resolve_session_connector(source(external=1.0), index) == "2"


@pytest.mark.asyncio
async def test_book_passes_real_connector_number_before_session_ingestion():
    wb = openpyxl.Workbook()
    ws = wb.active
    raw = source()
    ws.append(list(raw)); ws.append(list(raw.values()))
    ws = wb.create_sheet("ports")
    port = connector()
    ws.append(list(port)); ws.append(list(port.values()))
    stream = io.BytesIO(); wb.save(stream)
    captured = []
    async def ingest(db, company, view, rows, **kwargs):
        if view == "sessions":
            captured.extend(rows)
        return {"status": "success"}
    with patch("app.services.asuim_normalize._ingest_view", ingest), patch(
        "app.services.asuim_normalize._last_loaded_day", AsyncMock(return_value=None)
    ):
        await ingest_asuim_book(AsyncMock(), uuid4(), stream.getvalue())
    assert captured[0]["номер_коннектора"] == "2"


def stored(**extra):
    return SimpleNamespace(id=uuid4(), session_ext_id="session-1", connector_no=None,
                           source_station_id="s1", location_id="loc-1", connector_type="CCS2",
                           started_at=datetime(2026, 10, 1, 10), **extra)


def test_repair_restores_only_missing_number_with_matching_station_time_and_type():
    rows = map_sessions([source()], connector_index=build_session_connector_index([connector()]))
    session = stored()
    changes, counts = connector_repair_plan([session], rows, {"s1": "loc-1"})
    assert changes[0]["new"] == "2" and counts["restore"] == 1
    session.connector_no = "9"
    assert connector_repair_plan([session], rows, {"s1": "loc-1"})[0] == []
    session.connector_no = None
    assert connector_repair_plan([session], rows, {"s1": "foreign"})[0] == []
    session.started_at = datetime(2026, 9, 1)
    assert connector_repair_plan([session], rows, {"s1": "loc-1"})[0] == []


def test_repair_does_not_choose_between_conflicting_source_rows():
    rows = map_sessions([source(номер_коннектора=1), source(номер_коннектора=2)])
    changes, counts = connector_repair_plan([stored()], rows, {"s1": "loc-1"})
    assert not changes and counts["ambiguous_source"] == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_saved_connector_reference_never_crosses_company(db):
    own, other = [Company(id=uuid4(), name="Тест портов", slug=uuid4().hex, profile_id="energy") for _ in range(2)]
    db.add_all([own, other]); await db.flush()
    for company, number in [(own, 2), (other, 9)]:
        db.add(ServiceLocation(id=uuid4().hex, company_id=company.id, code=uuid4().hex,
            name="Тестовая ЭЗС", type="ev_charging", extra_metadata={
                "asuimStationId": "s1", "connectors": [{"sourceId": "1", "no": number, "type": "CCS2"}]}))
    await db.flush()
    index = await load_session_connector_index(db, own.id)
    assert resolve_session_connector(source(), index) == "2"
