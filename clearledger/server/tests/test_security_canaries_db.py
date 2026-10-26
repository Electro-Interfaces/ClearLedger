"""Проверка записи и вызова каналов: только отдельная БД из tests/conftest.py."""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app import guard, security_canaries as canaries
from app.models import SecurityEvent, SecurityBlock


@pytest.mark.asyncio(loop_scope='session')
async def test_all_categories_persist_and_alert_without_block(db, monkeypatch):
    from app.main import app
    configured = {f'/api/test-canary/{n}': kind for n, kind in enumerate(sorted(canaries.KINDS))}
    monkeypatch.setenv('SECURITY_CANARY_ROUTES_JSON', json.dumps(configured))
    canaries.routes.cache_clear()
    guard._said.clear(); guard._alerted.clear(); guard._probe.clear()
    alert = AsyncMock()
    monkeypatch.setattr(guard, '_alert', alert)
    client_ip = '93.184.216.34'
    ids = {}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for path, kind in configured.items():
                response = await client.get(path + '?password=do-not-store',
                                            headers={'X-Forwarded-For': client_ip})
                assert response.status_code == 404
                ids[kind] = response.headers['x-request-id']
            if canaries._pending:
                await asyncio.gather(*list(canaries._pending.values()))
            await asyncio.sleep(0)
            assert alert.await_count == 4
            rows = (await db.execute(select(SecurityEvent).where(
                SecurityEvent.ip == client_ip, SecurityEvent.kind.in_(canaries.KINDS)))).scalars().all()
            assert len(rows) == 4
            for row in rows:
                assert row.path in configured
                assert ids[row.kind] in row.detail
                assert 'do-not-store' not in row.detail + row.path
                assert 'method=GET' in row.detail
            blocks = (await db.execute(select(SecurityBlock).where(SecurityBlock.ip == client_ip))).scalars().all()
            assert not blocks
            # Повтор сохраняет обычный HTTP-ответ, не создаёт ещё одно уведомление.
            await client.get(next(iter(configured)), headers={'X-Forwarded-For': client_ip})
            if canaries._pending:
                await asyncio.gather(*list(canaries._pending.values()))
            await asyncio.sleep(0)
            assert alert.await_count == 4
    finally:
        canaries.routes.cache_clear()
        guard._said.clear(); guard._alerted.clear(); guard._probe.clear()
