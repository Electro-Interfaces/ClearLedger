"""Политика тревог и корреляция: без БД и без внешней доставки уведомлений."""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from app import guard
from app.security_context import SecurityContextMiddleware, current
from app.services.export_audit import log_export


def request(path="/api/openapi.json", ua="curl/7.88.1"):
    return Request({"type": "http", "method": "GET", "path": path,
                    "headers": [(b"user-agent", ua.encode())],
                    "client": ("8.8.4.4", 1000), "query_string": b""})


@pytest.mark.asyncio
async def test_schema_single_observed_series_alerted(monkeypatch):
    guard._schema_probes.clear()
    record = AsyncMock()
    monkeypatch.setattr(guard, "record", record)
    for _ in range(4):
        await guard.record_trap(request())
    assert all(c.args[0] == "api_schema_probe" and c.kwargs["alert"] is False
               for c in record.call_args_list)
    await guard.record_trap(request())
    assert record.call_args.args[0] == "trap"
    assert record.call_args.kwargs["block"] is True
    assert record.call_args.kwargs["hits"] == 5


@pytest.mark.asyncio
async def test_schema_window_expires_and_other_traps_still_alert(monkeypatch):
    guard._schema_probes.clear()
    record = AsyncMock()
    monkeypatch.setattr(guard, "record", record)
    monkeypatch.setattr(guard.time, "monotonic", lambda: 100)
    for _ in range(4):
        await guard.record_trap(request())
    monkeypatch.setattr(guard.time, "monotonic", lambda: 161)
    await guard.record_trap(request())
    assert record.call_args.kwargs["alert"] is False
    for r in (request("/.env"), request(ua="sqlmap"), request("/api/config")):
        await guard.record_trap(r)
        assert record.call_args.args[0] == "trap"
        assert record.call_args.kwargs["block"] is True


@pytest.mark.asyncio
async def test_export_volume_frequency_tenant_and_zero(monkeypatch):
    guard._exports.clear()
    record = AsyncMock()
    monkeypatch.setattr(guard, "record", record)
    user = SimpleNamespace(id=uuid.uuid4(), name="Test", email="test@example.invalid")
    db = MagicMock()
    company = uuid.uuid4()
    for rows in (0, 0, 0, 0, 10, 10):
        log_export(db, company, user, f"Реестр: {rows} строк", rows=rows)
    await asyncio.sleep(0)
    record.assert_awaited_once()
    assert record.call_args.args[0] == "export_frequency"
    assert record.call_args.kwargs["alert"] is False
    assert "20 строк" in record.call_args.kwargs["detail"]
    log_export(db, uuid.uuid4(), user, "Другая компания", rows=50000)
    await asyncio.sleep(0)
    assert record.await_count == 1
    log_export(db, company, user, "Большая выгрузка", rows=50000)
    await asyncio.sleep(0)
    assert record.call_args.args[0] == "mass_export"
    assert record.call_args.kwargs["alert"] is True
    guard._exports.clear()
    record.reset_mock()
    log_export(db, company, user, "60000 строк", rows=0)
    await asyncio.sleep(0)
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_context_parallel_export_and_error(monkeypatch):
    record = AsyncMock()
    monkeypatch.setattr(guard, "record", record)
    guard._exports.clear()
    db = MagicMock()
    user = SimpleNamespace(id=uuid.uuid4(), name="Test", email="test@example.invalid")
    app = FastAPI()
    seen = []
    @app.get("/export")
    async def export():
        context = current.get()
        await asyncio.sleep(0.01)
        log_export(db, uuid.uuid4(), user, "Реестр", rows=50001)
        seen.append(context)
        return {"request_id": context.request_id}
    @app.get("/denied")
    async def denied():
        return JSONResponse(status_code=429, content={"detail": "limited"})
    app.add_middleware(SecurityContextMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        a, b = await asyncio.gather(client.get("/export?token=secret", headers={"X-Request-ID": "forged"}),
                                   client.get("/export"))
        denied = await client.get("/denied")
    await asyncio.sleep(0)
    assert a.headers["x-request-id"] == a.json()["request_id"]
    assert a.headers["x-request-id"] != b.headers["x-request-id"]
    assert a.headers["x-request-id"] != "forged"
    assert len(denied.headers["x-request-id"]) == 32
    assert current.get() is None
    assert all(c.path == "/export" for c in seen)
    assert all("request_id=" in c.args[0].details and "secret" not in c.args[0].details
               for c in db.add.call_args_list)
    assert all(c.kwargs["path"] == "/export" for c in record.call_args_list)


@pytest.mark.asyncio
async def test_record_observation_does_not_suppress_alert_or_block(monkeypatch):
    from app import database
    guard._said.clear(); guard._alerted.clear(); guard._blocks.clear()
    db = MagicMock()
    db.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(database, "async_session_factory", factory)
    alert = AsyncMock()
    monkeypatch.setattr(guard, "_alert", alert)
    await guard.record("probe", request(), who="test@example.invalid", alert=False)
    await asyncio.sleep(0)
    alert.assert_not_awaited()
    await guard.record("probe", request(), who="test@example.invalid")
    await asyncio.sleep(0)
    alert.assert_awaited_once()
    await guard.record("probe", request(), who="test@example.invalid", block=True)
    await asyncio.sleep(0)
    assert "8.8.4.4" in guard._blocks
    assert "user=test@example.invalid" in db.add.call_args_list[0].args[0].detail


@pytest.mark.asyncio
async def test_real_application_guard_and_context(monkeypatch):
    from app.main import app
    guard._schema_probes.clear()
    monkeypatch.setattr(guard, "blocked", AsyncMock(return_value=False))
    record = AsyncMock()
    monkeypatch.setattr(guard, "record", record)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/openapi.json")
        assert response.status_code == 404
        assert len(response.headers["x-request-id"]) == 32
        assert record.call_args.args[0] == "api_schema_probe"
        assert record.call_args.kwargs["alert"] is False
        for _ in range(4):
            response = await client.get("/api/openapi.json")
        assert record.call_args.args[0] == "trap"
        assert record.call_args.kwargs["block"] is True
        response = await client.get("/api/config")
        assert response.status_code == 404
        assert record.call_args.kwargs["block"] is True
