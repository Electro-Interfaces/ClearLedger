"""Синтетические адреса: рабочий набор приманок не хранится в репозитории."""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, Request

from app import guard, security_canaries as canaries

SYNTHETIC = {
    '/api/qa-canary/config': 'canary_config',
    '/api/qa-canary/backup': 'canary_backup',
    '/api/qa-canary/identity': 'canary_identity',
    '/api/qa-canary/privilege': 'canary_privilege',
}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('SECURITY_CANARY_ROUTES_JSON', json.dumps(SYNTHETIC))
    canaries.routes.cache_clear()
    guard._probe.clear(); guard._reads.clear()
    yield
    canaries.routes.cache_clear()
    guard._probe.clear(); guard._reads.clear()


async def settle():
    if canaries._pending:
        await asyncio.gather(*list(canaries._pending.values()))
    await asyncio.sleep(0)


def headers(response):
    return {k: v for k, v in response.headers.items() if k != 'x-request-id'}


@pytest.mark.parametrize('method', ['GET', 'POST', 'HEAD', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
@pytest.mark.asyncio
async def test_response_identical_to_unknown_api(configured, monkeypatch, method):
    from app.main import app
    canaries.validate_routes(app.routes)
    monkeypatch.setattr(guard, 'blocked', AsyncMock(return_value=False))
    record = AsyncMock()
    monkeypatch.setattr(guard, 'record', record)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        ordinary = await client.request(method, '/api/qa-ordinary-missing')
        for path, kind in SYNTHETIC.items():
            response = await client.request(method, path, headers={'Authorization': 'Bearer deliberately-invalid'})
            await settle()
            assert response.status_code == ordinary.status_code == 404
            assert response.content == ordinary.content
            assert headers(response) == headers(ordinary)
            assert len(response.headers['x-request-id']) == 32
            assert record.call_args.args[0] == kind
            assert record.call_args.kwargs['block'] is False
        # Доступ не меняется из-за обращения к приманке.
        assert (await client.get('/api/health')).status_code == 200


@pytest.mark.asyncio
async def test_http_does_not_wait_for_security_database(configured, monkeypatch):
    from app.main import app
    gate = asyncio.Event()
    started = asyncio.Event()
    async def slow_record(*args, **kwargs):
        started.set()
        await gate.wait()
    monkeypatch.setattr(guard, 'record', slow_record)
    monkeypatch.setattr(guard, 'blocked', AsyncMock(return_value=False))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await asyncio.wait_for(client.get(next(iter(SYNTHETIC))), timeout=2)
            assert response.status_code == 404
            assert started.is_set() and not gate.is_set()
            assert len(canaries._pending) == 1
            await client.get(next(iter(SYNTHETIC)))
            assert len(canaries._pending) == 1
    finally:
        gate.set()
        await settle()


@pytest.mark.asyncio
async def test_normal_requests_and_direct_trap_are_not_canaries(configured, monkeypatch):
    from app.main import app
    monkeypatch.setattr(guard, 'blocked', AsyncMock(return_value=False))
    record = AsyncMock()
    monkeypatch.setattr(guard, 'record', record)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for path in ('/api/health?config=1', '/api/qa-canary/config/child', '/api/security/trap', '/api/unknown'):
            response = await client.get(path)
            assert response.status_code in (200, 404)
    await settle()
    record.assert_not_awaited()


def test_exact_matching_only(configured):
    assert canaries.kind_for('/api/qa-canary/config') == 'canary_config'
    assert canaries.kind_for('/API/QA-CANARY/CONFIG/') == 'canary_config'
    for path in ('/api/qa-canary/configX', '/api/qa-canary/config/child',
                 '/api/qa-canary/%2563onfig', '/api/health', '/api/qa-canary/config?token=x'):
        assert canaries.kind_for(path) is None


def test_registered_dynamic_route_cannot_become_canary(configured):
    app = FastAPI()
    @app.get('/api/qa-canary/{resource}')
    def real_api(resource: str):
        return resource
    with pytest.raises(ValueError, match='пересекается'):
        canaries.validate_routes(app.routes)


@pytest.mark.parametrize('raw', [
    'broken', '[]', '{"/api/health":"unknown"}', '{"/api/a/../b":"canary_config"}',
    '{"/api/a?token=x":"canary_config"}', '{"/api/a/":"canary_config"}',
    '{"/api/a":"canary_config","/api/a":"canary_backup"}',
    '{"/api/a":{"value":"canary_config"}}',
])
def test_rejects_invalid_private_configuration(monkeypatch, raw):
    monkeypatch.setenv('SECURITY_CANARY_ROUTES_JSON', raw)
    canaries.routes.cache_clear()
    try:
        with pytest.raises(ValueError):
            canaries.routes()
    finally:
        canaries.routes.cache_clear()


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv('SECURITY_CANARY_ROUTES_JSON', raising=False)
    canaries.routes.cache_clear()
    assert canaries.routes() == {}


@pytest.mark.asyncio
async def test_pending_work_is_bounded(configured, monkeypatch):
    gate = asyncio.Event()
    async def slow_record(*args, **kwargs):
        await gate.wait()
    monkeypatch.setattr(guard, 'record', slow_record)
    monkeypatch.setattr(canaries, 'MAX_PENDING', 2)
    try:
        for i in range(5):
            req = Request({'type': 'http', 'method': 'GET', 'path': '/api/qa-canary/config',
                           'headers': [], 'client': (f'10.0.0.{i+1}', 123), 'query_string': b''})
            canaries.observe(req, 'canary_config')
        assert len(canaries._pending) == 2
    finally:
        gate.set()
        await settle()


@pytest.mark.asyncio
async def test_scan_still_reaches_general_probe_limit(configured, monkeypatch):
    from app.main import app
    monkeypatch.setattr(guard, 'blocked', AsyncMock(return_value=False))
    record = AsyncMock()
    monkeypatch.setattr(guard, 'record', record)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for _ in range(guard.PROBE_BLOCK):
            await client.get(next(iter(SYNTHETIC)))
        await settle()
    assert any(c.args[0] == 'probe' and c.kwargs.get('block') is True for c in record.call_args_list)


@pytest.mark.asyncio
async def test_cors_preflight_has_normal_response_without_alert(configured, monkeypatch):
    from app.main import app
    record = AsyncMock()
    monkeypatch.setattr(guard, 'record', record)
    req_headers = {'Origin': 'http://localhost:3000', 'Access-Control-Request-Method': 'GET'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        ordinary = await client.options('/api/qa-ordinary-missing', headers=req_headers)
        canary = await client.options(next(iter(SYNTHETIC)), headers=req_headers)
    assert ordinary.status_code == canary.status_code
    assert ordinary.content == canary.content
    assert headers(ordinary) == headers(canary)
    record.assert_not_awaited()
