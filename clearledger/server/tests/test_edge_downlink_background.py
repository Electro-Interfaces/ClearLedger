"""Выдача очереди независима от тяжёлой сверки; SQL проверяем на тестовом PostgreSQL."""
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.requests import Request

from app.auth import get_company_by_api_key
from app.database import Base, get_db
from app.main import app
from app.models import (
    Company, EdgeAgent, EdgeDownlink, EdgePacket, EdgePacketRevision,
    StoreDocumentProjection, StoreDocumentProjectionState,
)
from app.routers import edge_router
from app.services import store_document_sync as sync, store_documents
from app.services.document_status_downlink import queue_document_status


@asynccontextmanager
async def savepoint():
    yield


@pytest.fixture
async def projection_company(db):
    company = Company(id=uuid.uuid4(), name="Тест сверки", slug=uuid.uuid4().hex,
                      profile_id="fuel")
    db.add(company)
    await db.commit()
    return company.id


def stub_adapter(monkeypatch, cid, *, empty=False):
    candidate = store_documents.ProjectionCandidate(
        company_id=cid, projection_source="edge", source_kind="edge_document",
        source_record_id=str(uuid.uuid4()), document_id=uuid.uuid4(),
        document_kind="writeoff", priority=50, station_id=208,
        accounting_status="ready",
    )
    adapter = AsyncMock(return_value=[] if empty else [candidate])
    monkeypatch.setattr(store_documents, "ADAPTER_REGISTRY", (("test", adapter),))
    return adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_noop_rebuild_advances_durable_watermark_without_touching_rows(
    db, monkeypatch, projection_company, empty,
):
    cid = projection_company
    adapter = stub_adapter(monkeypatch, cid, empty=empty)
    await store_documents.rebuild_store_document_projection(db, cid)
    await db.commit()
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.execute(text("UPDATE store_document_projection_states "
                          "SET last_successful_rebuild_at = :old WHERE company_id = :cid"),
                     {"old": old, "cid": cid})
    await db.commit()
    before = (await db.execute(select(StoreDocumentProjection.id,
        StoreDocumentProjection.rebuilt_at).where(StoreDocumentProjection.company_id == cid))).all()
    result = await store_documents.rebuild_store_document_projection(db, cid)
    await db.commit()
    after = (await db.execute(select(StoreDocumentProjection.id,
        StoreDocumentProjection.rebuilt_at).where(StoreDocumentProjection.company_id == cid))).all()
    assert result["created"] == result["updated"] == result["removed"] == 0
    assert result["unchanged"] == int(not empty)
    assert before == after
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    async with factory() as restarted:
        watermark = (await restarted.execute(select(
            StoreDocumentProjectionState.last_successful_rebuild_at,
        ).where(StoreDocumentProjectionState.company_id == cid))).scalar_one()
        assert watermark > old
        adapter.reset_mock()
        monkeypatch.setattr(sync, "queue_onec_document_snapshot", AsyncMock(
            return_value=(SimpleNamespace(payload={}), False)))
        monkeypatch.setattr(sync, "queue_document_status", AsyncMock(return_value=0))
        result = await sync.сверить_документы(restarted, cid, 208)
        assert result["rebuilt"] is False
        adapter.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("had_success", [False, True])
@pytest.mark.parametrize("error", [RuntimeError, store_documents.ProjectionRevisionConflict])
async def test_failed_rebuild_keeps_watermark_and_retries(
    db, monkeypatch, projection_company, had_success, error,
):
    cid = projection_company
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    if had_success:
        db.add(StoreDocumentProjectionState(company_id=cid, last_successful_rebuild_at=old))
        await db.commit()
    adapter = stub_adapter(monkeypatch, cid)
    adapter.side_effect = error("rebuild failed")
    snapshot = AsyncMock(return_value=(SimpleNamespace(payload={}), False))
    monkeypatch.setattr(sync, "queue_onec_document_snapshot", snapshot)
    monkeypatch.setattr(sync, "queue_document_status", AsyncMock(return_value=0))
    result = await sync.сверить_документы(db, cid, 208)
    assert result["rebuilt"] is False
    snapshot.assert_not_awaited()
    watermark = (await db.execute(select(StoreDocumentProjectionState.last_successful_rebuild_at)
                                 .where(StoreDocumentProjectionState.company_id == cid))).scalar()
    assert watermark == (old if had_success else None)
    adapter.side_effect = None
    result = await sync.сверить_документы(db, cid, 208)
    await db.commit()
    assert result["rebuilt"] is True
    assert adapter.await_count == 2
    assert (await db.execute(select(StoreDocumentProjectionState.last_successful_rebuild_at)
                            .where(StoreDocumentProjectionState.company_id == cid))).scalar_one() > old


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_delivery", ["snapshot", "status"])
async def test_delivery_sql_failure_preserves_rebuild_and_other_deliveries(
    db, monkeypatch, projection_company, failed_delivery,
):
    cid = projection_company
    adapter = stub_adapter(monkeypatch, cid)

    async def enqueue(session, company_id, station, delivery):
        task = EdgeDownlink(company_id=company_id, station_id=station,
                            kind=delivery, payload={"headers": [station]})
        session.add(task)
        await session.flush()
        if station == 208 and delivery == failed_delivery:
            await session.execute(text("SELECT 1 / 0"))
        return task

    async def snapshot(session, company_id, station):
        return await enqueue(session, company_id, station, "snapshot"), True

    async def status(session, company_id, station):
        await enqueue(session, company_id, station, "status")
        return 1

    snapshots = AsyncMock(side_effect=snapshot)
    statuses = AsyncMock(side_effect=status)
    monkeypatch.setattr(sync, "queue_onec_document_snapshot", snapshots)
    monkeypatch.setattr(sync, "queue_document_status", statuses)
    result = await sync.сверить_документы(db, cid, [208, 8])
    await db.commit()
    assert result["rebuilt"] is True and "208" in result["detail"]
    assert [call.args[2] for call in snapshots.await_args_list] == [208, 8]
    assert [call.args[2] for call in statuses.await_args_list] == [208, 8]
    assert result["snapshot"] is True
    assert result["headers"] == (1 if failed_delivery == "snapshot" else 2)
    assert result["statuses"] == (1 if failed_delivery == "status" else 2)
    deliveries = (await db.execute(select(EdgeDownlink.station_id, EdgeDownlink.kind)
                                  .where(EdgeDownlink.company_id == cid))).all()
    assert set(deliveries) == {(208, "snapshot"), (208, "status"),
                               (8, "snapshot"), (8, "status")} - {(208, failed_delivery)}
    assert (await db.execute(select(func.count()).select_from(StoreDocumentProjection)
                            .where(StoreDocumentProjection.company_id == cid))).scalar_one() == 1
    assert (await db.execute(select(StoreDocumentProjectionState.last_successful_rebuild_at)
                            .where(StoreDocumentProjectionState.company_id == cid))).scalar_one()
    monkeypatch.setattr(sync, "queue_onec_document_snapshot", AsyncMock(
        return_value=(SimpleNamespace(payload={}), False)))
    statuses.reset_mock()
    statuses.side_effect = None
    statuses.return_value = 0
    adapter.reset_mock()
    assert (await sync.сверить_документы(db, cid, 208))["rebuilt"] is False
    adapter.assert_not_awaited()
    statuses.assert_awaited_once()


@pytest.mark.asyncio
async def test_rebuild_rollback_rolls_back_watermark_too(db, monkeypatch, projection_company):
    cid = projection_company
    stub_adapter(monkeypatch, cid)
    await store_documents.rebuild_store_document_projection(db, cid)
    await db.rollback()
    assert (await db.execute(select(StoreDocumentProjectionState.company_id)
                            .where(StoreDocumentProjectionState.company_id == cid))).scalar() is None
    assert (await db.execute(select(StoreDocumentProjection.id)
                            .where(StoreDocumentProjection.company_id == cid))).scalar() is None


@pytest.mark.asyncio
async def test_metadata_creates_new_state_table_on_existing_installation(db, projection_company):
    # Проверяем ровно первый этап database.create_all на уже существующей схеме.
    async with db.bind.begin() as conn:
        await conn.run_sync(StoreDocumentProjectionState.__table__.drop)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(Base.metadata.create_all)
    assert (await db.execute(select(Company.id).where(Company.id == projection_company))).scalar_one()
    db.add(StoreDocumentProjectionState(company_id=projection_company,
        last_successful_rebuild_at=datetime.now(timezone.utc)))
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["pending", "delivered", "acked"])
async def test_document_status_noop_preserves_task_and_unfinished_redelivery(
    db, monkeypatch, projection_company, delivery,
):
    cid = projection_company
    stub_adapter(monkeypatch, cid)
    await store_documents.rebuild_store_document_projection(db, cid)
    await queue_document_status(db, cid, 208)
    await db.commit()

    async def tasks():
        return (await db.execute(select(EdgeDownlink).where(
            EdgeDownlink.company_id == cid, EdgeDownlink.station_id == 208,
            EdgeDownlink.kind == "document_status").order_by(EdgeDownlink.created_at, EdgeDownlink.id))).scalars().all()

    first, = await tasks()
    if delivery != "pending":
        first.delivered_at = datetime.now(timezone.utc)
    if delivery == "acked":
        first.acked_at = datetime.now(timezone.utc)
    await db.commit()
    for _ in range(2):
        assert await queue_document_status(db, cid, 208) == 1
        await db.commit()
    unchanged, = await tasks()
    assert unchanged.id == first.id
    assert (unchanged.acked_at is None) == (delivery != "acked")
    # Новый rebuild timestamp без изменения бухгалтерских данных тоже no-op.
    row = (await db.execute(select(StoreDocumentProjection).where(
        StoreDocumentProjection.company_id == cid))).scalar_one()
    row.rebuilt_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    await queue_document_status(db, cid, 208)
    await db.commit()
    assert len(await tasks()) == 1
    row.accounting_status = "needs_review"
    await queue_document_status(db, cid, 208)
    await db.commit()
    changed = await tasks()
    assert changed[-1].payload["items"][0]["accounting_status"] == "needs_review"
    assert changed[-1].id != first.id
    assert len(changed) == (1 if delivery == "pending" else 2)


@pytest.mark.asyncio
async def test_background_reconcile_noop_preserves_status_redelivery_until_ack(
    db, monkeypatch, projection_company,
):
    cid = projection_company
    adapter = stub_adapter(monkeypatch, cid)
    monkeypatch.setattr(sync, "queue_onec_document_snapshot", AsyncMock(
        return_value=(SimpleNamespace(payload={}), False)))
    request = Request({"type": "http", "headers": [(b"x-station-id", b"208")]})
    company = SimpleNamespace(id=cid)

    async def poll():
        return await edge_router.downlink(request, company, 208, db)

    assert (await sync.сверить_документы(db, cid, 208))["rebuilt"] is True
    await db.commit()
    first = (await poll())["tasks"]
    assert len(first) == 1 and first[0]["kind"] == "document_status"
    # Свежий реестр: повторяем такт, а затем no-op полную сборку после порога.
    assert (await sync.сверить_документы(db, cid, 208))["rebuilt"] is False
    await db.execute(text("UPDATE store_document_projection_states "
                          "SET last_successful_rebuild_at = :old WHERE company_id = :cid"),
                     {"old": datetime.now(timezone.utc) - timedelta(hours=1), "cid": cid})
    await db.commit()
    assert (await sync.сверить_документы(db, cid, 208))["rebuilt"] is True
    await db.commit()
    assert adapter.await_count == 2
    assert (await poll())["tasks"] == first
    task_id = uuid.UUID(first[0]["id"])
    await edge_router.downlink_ack(task_id, company, 208, db)
    await sync.сверить_документы(db, cid, 208)
    await db.commit()
    assert (await poll())["tasks"] == []
    assert (await db.execute(select(func.count()).select_from(EdgeDownlink)
                            .where(EdgeDownlink.company_id == cid))).scalar_one() == 1


@pytest.mark.asyncio
async def test_concurrent_status_queues_do_not_duplicate_tasks(db, monkeypatch, projection_company):
    cid = projection_company
    stub_adapter(monkeypatch, cid)
    await store_documents.rebuild_store_document_projection(db, cid)
    await db.commit()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    async def queue():
        async with factory() as session:
            assert await queue_document_status(session, cid, 208) == 1
            await session.commit()

    await asyncio.wait_for(asyncio.gather(queue(), queue()), 3)
    assert (await db.execute(select(func.count()).select_from(EdgeDownlink)
                            .where(EdgeDownlink.company_id == cid))).scalar_one() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["sql", "sleep"])
async def test_cancel_background_cycle_is_normal_shutdown(monkeypatch, phase):
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def block():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def tick():
        if phase == "sql":
            await block()

    async def sleep(_seconds):
        await block()

    monkeypatch.setattr(sync, "tick", tick)
    monkeypatch.setattr(sync.asyncio, "sleep", sleep)
    task = asyncio.create_task(sync.run_forever())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    assert await asyncio.wait_for(task, 1) is None
    assert cleaned.is_set()


@pytest.mark.asyncio
async def test_loop_survives_failed_tick(monkeypatch):
    calls = 0

    async def tick():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("временная ошибка БД")
        raise asyncio.CancelledError

    monkeypatch.setattr(sync, "tick", tick)
    monkeypatch.setattr(sync, "TICK_SECONDS", 0)
    await asyncio.wait_for(sync.run_forever(), 1)
    assert calls == 2


@pytest.mark.asyncio
async def test_fresh_registry_sends_snapshots_to_every_station(monkeypatch):
    db = SimpleNamespace(begin_nested=savepoint, execute=AsyncMock(return_value=SimpleNamespace(
        scalar=lambda: datetime.now(timezone.utc))))
    rebuild = AsyncMock()
    snapshot = AsyncMock(return_value=(SimpleNamespace(payload={"headers": [1]}), True))
    statuses = AsyncMock(return_value=2)
    monkeypatch.setattr(sync, "rebuild_store_document_projection", rebuild)
    monkeypatch.setattr(sync, "queue_onec_document_snapshot", snapshot)
    monkeypatch.setattr(sync, "queue_document_status", statuses)
    cid = uuid.uuid4()
    result = await sync.сверить_документы(db, cid, [208, 8])
    rebuild.assert_not_awaited()
    assert [call.args[2] for call in snapshot.await_args_list] == [208, 8]
    assert [call.args[2] for call in statuses.await_args_list] == [208, 8]
    assert result["headers"] == 2 and result["statuses"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_delivery", ["snapshot", "status"])
async def test_queue_failure_does_not_rollback_rebuild(monkeypatch, failed_delivery):
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar=lambda: None)),
        rollback=AsyncMock(),
        begin_nested=savepoint,
    )
    rebuild = AsyncMock(return_value={"records": 1})
    snapshot_result = (SimpleNamespace(payload={"headers": [1]}), True)
    snapshot = AsyncMock(side_effect=[
        RuntimeError("очередь недоступна") if failed_delivery == "snapshot" else snapshot_result,
        snapshot_result,
    ])
    statuses = AsyncMock(side_effect=[
        RuntimeError("очередь недоступна") if failed_delivery == "status" else 1, 1,
    ])
    monkeypatch.setattr(sync, "rebuild_store_document_projection", rebuild)
    monkeypatch.setattr(sync, "queue_onec_document_snapshot", snapshot)
    monkeypatch.setattr(sync, "queue_document_status", statuses)
    result = await sync.сверить_документы(db, uuid.uuid4(), [208, 8])
    db.rollback.assert_not_awaited()
    rebuild.assert_awaited_once()
    assert [call.args[2] for call in snapshot.await_args_list] == [208, 8]
    assert [call.args[2] for call in statuses.await_args_list] == [208, 8]
    assert result["rebuilt"] is True and result["snapshot"] is True
    assert result["headers"] == (1 if failed_delivery == "snapshot" else 2)
    assert result["statuses"] == (1 if failed_delivery == "status" else 2)


@pytest.mark.asyncio
async def test_downlink_responds_while_rebuild_waits_in_own_session(db, monkeypatch):
    cid = (await db.execute(select(Company.id).limit(1))).scalar_one()
    station = 98208
    db.add(EdgeAgent(company_id=cid, station_id=station))
    task_id = uuid.uuid4()
    db.add(EdgeDownlink(id=task_id, company_id=cid, station_id=station,
                        kind="nsi_delta", payload={"items": []}))
    await db.commit()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(sync, "async_session_factory", factory)
    entered = asyncio.Event()
    sessions = []

    async def rebuild(background_db, company_id):
        assert company_id == cid
        assert background_db is not db
        sessions.append(background_db)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(sync, "rebuild_store_document_projection", rebuild)
    monkeypatch.setattr(edge_router, "сверить_документы", sync.сверить_документы, raising=False)
    background = asyncio.create_task(sync.tick())

    async def request_db():
        async with factory() as session:
            assert session not in sessions
            yield session

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_company_by_api_key] = lambda: SimpleNamespace(id=cid)
    app.dependency_overrides[get_db] = request_db
    app.dependency_overrides[edge_router.станция_ключа] = lambda: station
    try:
        await asyncio.wait_for(entered.wait(), 2)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await asyncio.wait_for(client.get(
                "/api/edge/downlink", headers={"X-Station-Id": str(station)}), 1)
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()["tasks"]] == [str(task_id)]
        assert not background.done()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        background.cancel()
        with pytest.raises(asyncio.CancelledError):
            await background
    async with factory() as session:
        # Отмена SQL освобождает сессию и транзакционный lock для нового такта.
        assert (await session.execute(sync.TRY_LOCK, {
            "scope_key": f"store-documents:{cid}",
        })).scalar() is True


@pytest.mark.asyncio
async def test_busy_projection_lock_skips_tick_then_recovers(db, monkeypatch):
    cid = (await db.execute(select(Company.id).limit(1))).scalar_one()
    station = 98209
    db.add(EdgeAgent(company_id=cid, station_id=station))
    await db.commit()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(sync, "async_session_factory", factory)
    reconcile = AsyncMock(return_value={"detail": "ok"})
    monkeypatch.setattr(sync, "сверить_документы", reconcile)
    async with factory() as holder:
        await holder.execute(store_documents.ADVISORY_LOCK,
                             {"scope_key": f"store-documents:{cid}"})
        assert await asyncio.wait_for(sync.tick(), 1) == 0
        reconcile.assert_not_awaited()
        await holder.rollback()
    assert await asyncio.wait_for(sync.tick(), 1) == 1
    assert reconcile.await_args.args[0] is not db
    assert reconcile.await_args.args[1] == cid
    assert station in reconcile.await_args.args[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_revisions", [False, True])
async def test_production_packet_projects_recipe_and_release(db, monkeypatch, projection_company,
                                                            auto_revisions):
    cid = projection_company
    now = datetime.now(timezone.utc)
    ids = {kind: uuid.uuid4() for kind in ("recipe", "production_release")}

    def payload(version):
        goods = [{"scope": "store", "Номенклатура": str(uuid.uuid4()),
                  "Количество": 2, "Сумма": 240}]
        return {"Документы": [{
            "Тип": kind, "ИдентификаторДокумента": str(document_id),
            "Номер": f"{kind}-{version}", "Дата": now.isoformat(),
            "ВыпускБлюд" if kind == "production_release" else "Товары": goods,
        } for kind, document_id in ids.items()]}

    packet = EdgePacket(company_id=cid, packet_uuid=str(uuid.uuid4()), station_id=208,
                        kind="production", payload=payload("first"), received_at=now)
    db.add(packet)
    await db.flush()
    db.add(EdgePacketRevision(
        company_id=cid, edge_packet_id=packet.id, packet_uuid=packet.packet_uuid,
        content_hash="a" * 64, payload=payload("revision"),
        received_at=now + timedelta(minutes=1)))
    await db.commit()
    monkeypatch.setattr(store_documents, "_АВТО_РЕВИЗИИ", auto_revisions)

    async def edge_adapter(session, company_id):
        class TestSchemaSession:
            async def execute(self, statement, *args):
                # В тестовом контуре канонические таблицы лежат в public.
                if "core.data_entries" in str(statement.compile(dialect=postgresql.dialect())):
                    statement = text(str(statement).replace("core.data_entries", "data_entries"))
                return await session.execute(statement, *args)

        return await store_documents._edge_adapter(TestSchemaSession(), company_id)

    monkeypatch.setattr(store_documents, "ADAPTER_REGISTRY", (("edge", edge_adapter),))
    result = await store_documents.rebuild_store_document_projection(db, cid)
    await db.commit()
    assert result["created"] == result["records"] == 2
    rows = (await db.execute(select(StoreDocumentProjection).where(
        StoreDocumentProjection.company_id == cid))).scalars().all()
    version = "revision" if auto_revisions else "first"
    assert {row.document_kind: row.document_id for row in rows} == ids
    assert {row.number for row in rows} == {f"{kind}-{version}" for kind in ids}
    assert all(row.amount == 240 and row.station_id == 208 and row.is_primary for row in rows)
    assert all(row.header["packet_uuid"] == packet.packet_uuid for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_revisions", [False, True])
async def test_edge_payload_is_scoped_and_only_latest_revision_is_loaded(
    db, monkeypatch, auto_revisions,
):
    cids = (await db.execute(select(Company.id).limit(2))).scalars().all()
    cid, other_cid = cids
    now = datetime.now(timezone.utc)

    def payload(number):
        return {"Документы": [{"Тип": "writeoff", "Номер": number,
            "Товары": [{"Номенклатура": str(uuid.uuid4()), "Количество": 1,
                        "Сумма": 10, "scope": "store"}]}]}

    def packet(company_id, kind, number):
        return EdgePacket(id=uuid.uuid4(), company_id=company_id,
                          packet_uuid=str(uuid.uuid4()), station_id=98210,
                          kind=kind, payload=payload(number), received_at=now)

    wanted = packet(cid, "writeoff", "first")
    stock = packet(cid, "stock", "stock-must-not-project")
    foreign = packet(other_cid, "writeoff", "foreign")
    db.add_all([wanted, stock, foreign])
    await db.flush()
    for parent in [wanted, stock, foreign]:
        for index in [1, 2]:
            db.add(EdgePacketRevision(
                company_id=parent.company_id, edge_packet_id=parent.id,
                packet_uuid=parent.packet_uuid, content_hash=str(index) * 64,
                payload=payload(f"revision-{index}"),
                received_at=now + timedelta(minutes=index)))
    await db.commit()
    monkeypatch.setattr(store_documents, "_АВТО_РЕВИЗИИ", auto_revisions)
    statements = []

    class RecordingSession:
        async def execute(self, statement, *args):
            # Обычный тестовый контур создаёт public, боевой — core.
            sql = str(statement.compile(dialect=postgresql.dialect()))
            if "core.data_entries" in sql:
                statement = text(str(statement).replace("core.data_entries", "data_entries"))
            result = await db.execute(statement, *args)
            if "edge_packet" in sql:
                rows = result.all()
                statements.append((statement, rows))
                return SimpleNamespace(all=lambda: rows)
            return result

    rows = await store_documents._edge_adapter(RecordingSession(), cid)
    # Предыдущий параметр остаётся в общей БД; проверяем только свои пакеты.
    rows = [row for row in rows if row.header["packet_uuid"] == wanted.packet_uuid]
    expected_number = "revision-2" if auto_revisions else "first"
    assert [row.number for row in rows] == [expected_number]
    packet_query, packet_rows = statements[0]
    payload_query, payload_rows = statements[1]
    assert wanted.packet_uuid in {row.packet_uuid for row in packet_rows}
    assert stock.packet_uuid not in {row.packet_uuid for row in packet_rows}
    assert foreign.packet_uuid not in {row.packet_uuid for row in packet_rows}
    own_payloads = [row for row in payload_rows if row.packet_uuid == wanted.packet_uuid]
    assert [row.payload["Документы"][0]["Номер"] for row in own_payloads] == [expected_number]
    assert stock.packet_uuid not in {row.packet_uuid for row in payload_rows}
    assert foreign.packet_uuid not in {row.packet_uuid for row in payload_rows}
    assert set(packet_query.selected_columns.keys()) == {
        "packet_uuid", "station_id", "received_at", "kind"}
    expected_columns = {"packet_uuid", "payload"}
    if auto_revisions:
        expected_columns.add("received_at")
    assert set(payload_query.selected_columns.keys()) == expected_columns


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_cheque_payload_is_only_loaded_for_missing_scope(monkeypatch, legacy):
    from app.models import StoreCheque

    now = datetime.now(timezone.utc)

    def cheque(packet_uuid, scoped):
        line = {"Номенклатура": str(uuid.uuid4()), "Количество": 1, "Сумма": 10}
        if scoped:
            line["scope"] = "store"
        return SimpleNamespace(
            id=uuid.uuid4(), station_id=208, shift_number=7001, number=1,
            at=now, received_at=now, fiscal_number=1001, pay_name="Карта",
            is_return=False, had_fuel=False, version=1,
            packet_uuid=packet_uuid, lines=[line],
        )

    cheques = [cheque("modern-packet", True)]
    if legacy:
        cheques.append(cheque("legacy-packet", False))
    payload_queries = []

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return self

        def all(self):
            return self.rows

    class Session:
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is StoreCheque:
                return Rows(cheques)
            assert entity is EdgePacket
            payload_queries.append(statement)
            return Rows([])

    monkeypatch.setattr(store_documents, "load_item_catalog", AsyncMock(return_value={}))
    await store_documents._cheque_adapter(Session(), uuid.uuid4())
    assert len(payload_queries) == int(legacy)
    if legacy:
        query = payload_queries[0]
        assert set(query.selected_columns.keys()) == {"packet_uuid", "station_id", "payload"}
        sql = str(query.compile(dialect=postgresql.dialect(),
                                compile_kwargs={"literal_binds": True}))
        assert "legacy-packet" in sql and "modern-packet" not in sql
