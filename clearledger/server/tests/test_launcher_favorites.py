"""Избранные приложения каталога (`/api/sso/apps/favorites`).

Проверяется главное обещание: избранное каталога и «Закреплённые приложения»
пульта — ОДИН список человека, а не два. Иначе звёздочка в каталоге и настройка
пульта начнут показывать разное, и человек не поймёт, где правда.
"""
import uuid

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

URL = '/api/sso/apps/favorites?company_id=rushydro'
PULSE_URL = '/api/pulse/home-settings?company_id=rushydro'


async def test_favorites_are_the_same_list_as_pulse_pins(auth_client):
    assert (await auth_client.get(URL)).json()['codes'] == []

    saved = await auth_client.put(URL, json={'codes': ['projects', 'ops']})
    assert saved.status_code == 200, saved.text
    assert saved.json()['codes'] == ['projects', 'ops']
    assert (await auth_client.get(URL)).json()['codes'] == ['projects', 'ops']
    # Тот же список виден пульту — и остальные настройки экрана целы.
    home = (await auth_client.get(PULSE_URL)).json()
    assert home['effective']['favorite_apps'] == ['projects', 'ops']
    assert home['effective']['sections'] == home['default']['sections']

    # Снятие звёздочки — тем же списком без кода, порядок сохраняется.
    await auth_client.put(URL, json={'codes': ['ops']})
    assert (await auth_client.get(URL)).json()['codes'] == ['ops']

    # Настройка пульта остаётся хозяином того же поля: сохранение оттуда меняет избранное.
    home = (await auth_client.get(PULSE_URL)).json()
    config = {**home['effective'], 'favorite_apps': ['sales']}
    from_pulse = await auth_client.put(
        PULSE_URL, json={'revision': home['personal_revision'], 'config': config})
    assert from_pulse.status_code == 200, from_pulse.text
    assert (await auth_client.get(URL)).json()['codes'] == ['sales']

    reset = await auth_client.get(PULSE_URL)
    await auth_client.put(PULSE_URL, json={
        'revision': reset.json()['personal_revision'], 'config': None})


@pytest.mark.parametrize('codes', [['x'] * 13, ['ops', 'ops'], [''], ['x' * 81]])
async def test_invalid_codes(auth_client, codes):
    assert (await auth_client.put(URL, json={'codes': codes})).status_code == 422


async def test_foreign_company_and_anonymous_denied(auth_client, client):
    other = f'/api/sso/apps/favorites?company_id={uuid.uuid4()}'
    assert (await auth_client.get(other)).status_code in (400, 403)
    assert (await client.get(URL)).status_code == 401
