import uuid

import pytest
from sqlalchemy import select

from app.auth import create_access_token
from app.models import Company, User, UserCompany, CompanyRole

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_personal_default_and_concurrent_edit(auth_client):
    url = '/api/pulse/home-settings?company_id=rushydro'
    initial = (await auth_client.get(url)).json()
    config = {"sections": ["chats", "work"], "favorite_apps": ["projects"], "metric_keys": []}
    saved = await auth_client.put(url, json={"scope": "personal", "revision": initial['personal_revision'], "config": config})
    assert saved.status_code == 200, saved.text
    assert saved.json()['effective'] == config
    assert (await auth_client.get(url)).json()['effective'] == config
    conflict = await auth_client.put(url, json={"revision": initial['personal_revision'], "config": config})
    assert conflict.status_code == 409
    reset = await auth_client.put(url, json={"revision": saved.json()['personal_revision'], "config": None})
    assert reset.status_code == 200
    assert reset.json()['personal'] is None
    assert reset.json()['effective'] == reset.json()['default']


async def test_defaults_isolation_and_permissions(auth_client, db):
    company = await db.scalar(select(Company).where(Company.slug == 'rushydro'))
    role = CompanyRole(id=uuid.uuid4(), company_id=company.id, name='Только витрина', modules=['pulse:showcase'])
    db.add(role)
    members = []
    for i in range(2):
        user = User(email=f'pulse-home-{uuid.uuid4()}@example.test', name=f'Учебный сотрудник {i}', password_hash='unused', company_id=company.id)
        db.add(user)
        await db.flush()
        db.add(UserCompany(user_id=user.id, company_id=company.id, role='user', role_id=role.id))
        members.append(user)
    await db.commit()
    url = f'/api/pulse/home-settings?company_id={company.id}'
    headers = [{'Authorization': f'Bearer {create_access_token(str(user.id), user.email)}'} for user in members]
    initial = (await auth_client.get(url)).json()
    shared = {"sections": ["apps"], "favorite_apps": [], "metric_keys": None}
    result = await auth_client.put(url, json={"scope": "space", "revision": initial['space_revision'], "config": shared})
    assert result.status_code == 200, result.text
    one = await auth_client.get(url, headers=headers[0])
    assert one.status_code == 200, one.text
    assert one.json()['effective'] == shared
    assert not one.json()['can_set_default']
    denied = await auth_client.put(url, headers=headers[0], json={"scope": "space", "revision": result.json()['space_revision'], "config": shared})
    assert denied.status_code == 403
    personal = {**shared, 'sections': ['chats']}
    saved = await auth_client.put(url, headers=headers[0], json={"revision": 0, "config": personal})
    assert saved.status_code == 200, saved.text
    assert (await auth_client.get(url, headers=headers[1])).json()['effective'] == shared
    foreign = await auth_client.get('/api/pulse/home-settings?company_id=gig', headers=headers[0])
    assert foreign.status_code == 403
    role.modules = ['projects']
    await db.commit()
    denied = await auth_client.get(url, headers=headers[0])
    assert denied.status_code == 403


@pytest.mark.parametrize('config', [
    {'sections': ['work', 'work']}, {'sections': ['unknown']},
    {'favorite_apps': ['x'] * 13}, {'metric_keys': ['']}, {'unexpected': True},
])
async def test_invalid_config(auth_client, config):
    response = await auth_client.put('/api/pulse/home-settings?company_id=rushydro', json={'revision': 0, 'config': config})
    assert response.status_code == 422


async def test_anonymous_denied(client):
    assert (await client.get('/api/pulse/home-settings?company_id=rushydro')).status_code == 401
