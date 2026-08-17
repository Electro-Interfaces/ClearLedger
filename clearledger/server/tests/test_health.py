"""Тесты /api/health."""

import asyncio

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import database_startup_lock


async def test_health_returns_ok(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "TradeLedger API"
    assert "version" in data


async def test_ready_checks_database_schema_and_storage(client: AsyncClient):
    resp = await client.get("/api/ready")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ready"
    assert resp.json()["database"] == "ok"
    assert resp.json()["storage"] == "ok"


async def test_database_startup_lock_serializes_workers(db: AsyncSession):
    order = []

    async def worker(name: str):
        async with database_startup_lock():
            order.append(f"{name}:start")
            await asyncio.sleep(0.03)
            order.append(f"{name}:end")

    await asyncio.gather(worker("a"), worker("b"))
    assert order in (
        ["a:start", "a:end", "b:start", "b:end"],
        ["b:start", "b:end", "a:start", "a:end"],
    )
