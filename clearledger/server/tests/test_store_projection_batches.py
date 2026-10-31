"""Реальный PostgreSQL: редакции, порции и восстановление фоновой сборки."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Company, EdgePacket, EdgePacketRevision, StoreDocumentProjectionState
from app.services import store_documents as docs, store_document_sync as sync


@pytest.fixture
async def company(db):
    row = Company(id=uuid.uuid4(), name="Проверка центра", slug=uuid.uuid4().hex, profile_id="fuel")
    db.add(row)
    await db.commit()
    return row.id


def packet(cid, *, payload=None, kind="future-envelope", number=None):
    return EdgePacket(id=uuid.uuid4(), company_id=cid,
        packet_uuid=number or str(uuid.uuid4()), station_id=8, kind=kind,
        payload=payload if payload is not None else {"source": "original"},
        received_at=datetime(2026, 10, 31, tzinfo=timezone.utc))


def revision(parent, index, payload):
    return EdgePacketRevision(id=uuid.uuid4(), company_id=parent.company_id,
        edge_packet_id=parent.id, packet_uuid=parent.packet_uuid,
        content_hash=f"{index:064x}", payload=payload,
        received_at=parent.received_at + timedelta(seconds=index))


@pytest.mark.asyncio
@pytest.mark.parametrize("auto", [False, True])
async def test_latest_body_and_original_are_not_modified(db, company, monkeypatch, auto):
    monkeypatch.setattr(docs, "_АВТО_РЕВИЗИИ", auto)
    row = packet(company)
    db.add(row)
    await db.flush()
    db.add_all([revision(row, 1, {"source": "old"}), revision(row, 2, {"source": "latest"})])
    await db.commit()
    row_id, received = row.id, row.received_at
    result = [p async for p in docs._iter_edge_packets(db, company)]
    assert len(result) == 1
    assert result[0].payload == {"source": "latest" if auto else "original"}
    assert result[0].received_at == received + timedelta(seconds=2 if auto else 0)
    db.expire_all()
    assert (await db.get(EdgePacket, row_id)).payload == {"source": "original"}


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [None, {"kept": "older-nonempty"}])
async def test_empty_revisions_do_not_erase_older_body(db, company, monkeypatch, previous):
    monkeypatch.setattr(docs, "_АВТО_РЕВИЗИИ", True)
    row = packet(company)
    db.add(row)
    await db.flush()
    if previous is not None:
        db.add(revision(row, 1, previous))
    db.add_all([revision(row, 2, {}), revision(row, 3, {})])
    await db.commit()
    result = [p async for p in docs._iter_edge_packets(db, company)]
    assert result[0].payload == (previous or row.payload)
    assert result[0].received_at == row.received_at + timedelta(seconds=1 if previous else 0)


@pytest.mark.asyncio
async def test_portions_preserve_unknown_envelopes_and_isolate_company(db, company, monkeypatch):
    monkeypatch.setattr(docs, "_EDGE_PACKET_BATCH_SIZE", 3)
    monkeypatch.setattr(docs, "_АВТО_РЕВИЗИИ", True)
    foreign = Company(id=uuid.uuid4(), name="Другой контур", slug=uuid.uuid4().hex, profile_id="fuel")
    db.add(foreign)
    await db.flush()
    rows = [packet(company, payload={"index": n}, kind="new-envelope") for n in range(11)]
    db.add_all([*rows, packet(foreign.id, number=rows[0].packet_uuid, payload={"foreign": True})])
    await db.commit()
    queries = []
    def capture(conn, cursor, statement, params, context, executemany):
        queries.append(statement)
    event.listen(db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        result = [p async for p in docs._iter_edge_packets(db, company)]
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", capture)
    assert {p.packet_uuid: p.payload for p in result} == {p.packet_uuid: p.payload for p in rows}
    assert len([s for s in queries if "edge_packets.payload" in s.split("FROM")[0]]) == 4


@pytest.mark.asyncio
async def test_revised_packet_never_reads_original_payload(db, company, monkeypatch):
    monkeypatch.setattr(docs, "_АВТО_РЕВИЗИИ", True)
    row = packet(company, payload={"original": "x" * 100_000})
    db.add(row)
    await db.flush()
    db.add_all([revision(row, n, {"revision": n, "padding": "y" * 100_000}) for n in range(1, 21)])
    await db.commit()
    statements = []
    def capture(conn, cursor, statement, params, context, executemany):
        statements.append(statement)
    event.listen(db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        result = [p async for p in docs._iter_edge_packets(db, company)]
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", capture)
    assert result[0].payload["revision"] == 20
    assert not any("edge_packets.payload" in s.split("FROM")[0] for s in statements)
    reads = [s for s in statements if "edge_packet_revisions.payload" in s.split("FROM")[0]]
    assert len(reads) == 1 and "DISTINCT ON" in reads[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError, docs.ProjectionRevisionConflict, asyncio.CancelledError])
async def test_worker_releases_lock_and_retry_succeeds(db, company, monkeypatch, failure):
    engine = create_async_engine(db.bind.url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.database.async_session_factory", factory)
    rebuild = AsyncMock(side_effect=failure("failure") if failure else None, return_value={"records": 0})
    monkeypatch.setattr(sync, "rebuild_store_document_projection", rebuild)
    try:
        if failure is asyncio.CancelledError:
            with pytest.raises(asyncio.CancelledError):
                await sync._пересобрать(company, 8)
        else:
            await sync._пересобрать(company, 8)
        key = {"scope_key": f"store-documents:{company}"}
        async with factory() as session:
            assert (await session.execute(text(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(:scope_key, 0))"), key)).scalar()
            await session.rollback()
        assert (await db.execute(text(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(:scope_key, 0))"), key)).scalar()
        await db.rollback()
        rebuild.side_effect = None
        await sync._пересобрать(company, 8)
        assert rebuild.await_count == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_worker_skips_busy_manual_rebuild(db, company, monkeypatch):
    monkeypatch.setattr("app.database.async_session_factory", async_sessionmaker(db.bind, expire_on_commit=False))
    rebuild = AsyncMock(return_value={"records": 0})
    monkeypatch.setattr(sync, "rebuild_store_document_projection", rebuild)
    await db.execute(docs.ADVISORY_LOCK, {"scope_key": f"store-documents:{company}"})
    await asyncio.wait_for(sync._пересобрать(company, 8), timeout=2)
    rebuild.assert_not_awaited()
    await db.rollback()
    await sync._пересобрать(company, 8)
    rebuild.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_empty_rebuild_persists_freshness(db, company, monkeypatch):
    monkeypatch.setattr(docs, "ADAPTER_REGISTRY", ())
    first = await docs.rebuild_store_document_projection(db, company)
    await db.commit()
    state = await db.get(StoreDocumentProjectionState, company)
    assert first["records"] == 0 and state.last_successful_rebuild_at is not None
    launch = Mock()
    monkeypatch.setattr(sync, "запустить_пересборку", launch)
    monkeypatch.setattr(sync, "queue_onec_document_snapshot", AsyncMock(side_effect=ValueError("empty")))
    monkeypatch.setattr(sync, "queue_document_status", AsyncMock(return_value=0))
    await sync.сверить_документы(db, company, 8)
    launch.assert_not_called()
