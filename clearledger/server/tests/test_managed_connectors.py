import json
import uuid
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from fastapi import FastAPI, HTTPException

from app.auth import get_current_user
from app.database import get_db
from app.routers import space_registry_router
from app.services import managed_connectors, sso

COMPANY = uuid.UUID('11111111-1111-4111-8111-111111111111')
OTHER = uuid.UUID('22222222-2222-4222-8222-222222222222')
REMOTE = '33333333-3333-4333-8333-333333333333'
ACTOR = uuid.UUID('44444444-4444-4444-8444-444444444444')
CONNECTOR = '55555555-5555-4555-8555-555555555555'
RealClient = httpx.AsyncClient


@pytest.fixture
def signing(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    public = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(sso, '_private_key', lambda: private)
    return public


@pytest.fixture
def api(monkeypatch, signing):
    state = {'role': 'admin', 'owner_status': 200, 'body': None, 'calls': [], 'available': True}

    class DB:
        async def execute(self, statement):
            app = SimpleNamespace(code='support', name='Поддержка', base_url='/support', config={'internalUrl': 'http://support.test:3003'})
            link = SimpleNamespace(external_company_id=REMOTE)
            return SimpleNamespace(scalar_one_or_none=lambda: state['role'], first=lambda: (app, link) if state['available'] else None)

    async def member(ref, user, db):
        if str(ref) != str(COMPANY):
            raise HTTPException(403, 'Нет доступа к организации')
        return COMPANY

    monkeypatch.setattr(space_registry_router, 'assert_company_member', member)
    app = FastAPI()
    app.include_router(space_registry_router.router, prefix='/api')
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=ACTOR, is_superadmin=False)
    app.dependency_overrides[get_db] = lambda: DB()

    def owner(request):
        claims = jwt.decode(request.headers['authorization'].split(' ', 1)[1], signing, algorithms=['RS256'], audience='support', issuer=sso.settings.sso_issuer)
        state['calls'].append({'url': str(request.url), 'claims': claims, 'body': json.loads(request.content) if request.content else None, 'method': request.method})
        body = state['body']
        if body is None:
            body = {'id': CONNECTOR, 'provider': 'mango', 'label': 'Mango', 'secrets': {'api_key': True}, 'values': {'lines': []}, 'credentials': {'api_key': 'OWNER-SECRET'}}
        return httpx.Response(state['owner_status'], json=body)

    transport = httpx.MockTransport(owner)
    monkeypatch.setattr(managed_connectors.httpx, 'AsyncClient', lambda **kwargs: RealClient(transport=transport, **kwargs))
    return app, state


@pytest.mark.asyncio
async def test_admin_forwards_to_owner_with_mapped_company_and_scoped_token(api):
    app, state = api
    async with RealClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        response = await client.post(f'/api/registry/connectors/managed/support?company_id={COMPANY}', json={
            'id': CONNECTOR, 'provider': 'mango', 'label': 'Mango', 'credentials': {'api_key': 'INPUT-SECRET'}, 'values': {'lines': []}, 'enabled': False,
        })
    assert response.status_code == 200
    assert 'SECRET' not in response.text
    request = state['calls'][0]
    assert request['claims']['svc'] == 'connections'
    assert request['claims']['cid'] == REMOTE
    assert request['claims']['actor'] == str(ACTOR)
    assert f'companyId={REMOTE}' in request['url']
    assert request['body']['credentials']['api_key'] == 'INPUT-SECRET'
    assert response.json()['owner_base_url'] == '/support'


@pytest.mark.asyncio
@pytest.mark.parametrize('path,method', [('/catalog', 'GET'), (f'/managed/support/{CONNECTOR}', 'GET'), ('/managed/support', 'POST'), (f'/managed/support/{CONNECTOR}', 'PATCH'), (f'/managed/support/{CONNECTOR}/actions/test', 'POST')])
async def test_member_cannot_read_settings_or_manage_connections(api, path, method):
    app, state = api
    state['role'] = 'member'
    async with RealClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        response = await client.request(method, f'/api/registry/connectors{path}?company_id={COMPANY}', json={})
    assert response.status_code == 403
    assert not state['calls']


@pytest.mark.asyncio
async def test_foreign_company_never_reaches_owner(api):
    app, state = api
    async with RealClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        response = await client.get(f'/api/registry/connectors/managed/support/{CONNECTOR}?company_id={OTHER}')
    assert response.status_code == 403
    assert not state['calls']


@pytest.mark.asyncio
async def test_catalog_explains_unavailable_owner(api):
    app, state = api
    state['available'] = False
    async with RealClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        response = await client.get(f'/api/registry/connectors/catalog?company_id={COMPANY}')
    assert response.status_code == 200
    assert response.json()['providers'] == []
    assert 'не связана' in response.json()['problems'][0]['message']
    assert not state['calls']


@pytest.mark.asyncio
async def test_update_and_action_have_fixed_routes_and_unknown_action_is_rejected(api):
    app, state = api
    async with RealClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        updated = await client.patch(f'/api/registry/connectors/managed/support/{CONNECTOR}?company_id={COMPANY}', json={'label': 'Новое имя', 'credentials': {}})
        action = await client.post(f'/api/registry/connectors/managed/support/{CONNECTOR}/actions/test?company_id={COMPANY}')
        forbidden = await client.post(f'/api/registry/connectors/managed/support/{CONNECTOR}/actions/delete?company_id={COMPANY}')
    assert updated.status_code == action.status_code == 200
    assert state['calls'][0]['method'] == 'PATCH'
    assert state['calls'][0]['body']['credentials'] == {}
    assert state['calls'][1]['claims']['cid'] == REMOTE
    assert forbidden.status_code == 404
    assert len(state['calls']) == 2


def test_service_token_remains_compatible_with_existing_scopes(signing):
    token = sso.sign_service_token(aud='support', scope='projection')
    claims = jwt.decode(token, signing, algorithms=['RS256'], audience='support', issuer=sso.settings.sso_issuer)
    assert claims['svc'] == 'projection'
    assert 'cid' not in claims and 'actor' not in claims


@pytest.mark.asyncio
async def test_directory_binding_uses_owner_company_and_checks_admin(api):
    app,state=api
    body={'extension':'101','user_id':str(ACTOR),'can_call':True}
    path=f'/api/registry/connectors/managed/support/{CONNECTOR}/actions/bind-operator?company_id={COMPANY}'
    async with RealClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
        response=await client.post(path,json=body)
        assert response.status_code==200
        assert state['calls'][0]['body']==body
        assert state['calls'][0]['claims']['cid']==REMOTE
        state['role']='member'
        assert (await client.post(path,json=body)).status_code==403
    assert len(state['calls'])==1
