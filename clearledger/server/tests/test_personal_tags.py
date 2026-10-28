"""Личные теги (28.10.2026): видит только хозяин, предмет у других не меняется."""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Company, PersonalTagLink, User, UserCompany
from app.routers.personal_tags_router import (
    AssignIn, TagAction, TagIn, tag_action, tag_create, tags_assign, tags_mine)

pytestmark = pytest.mark.asyncio(loop_scope='session')


async def _человек(db, cid):
    u = User(email=f'tags-{uuid.uuid4()}@example.test', name='Тест тегов', password_hash='!test',
             company_id=uuid.UUID(cid))
    db.add(u)
    await db.flush()
    db.add(UserCompany(company_id=uuid.UUID(cid), user_id=u.id, role='admin'))
    await db.flush()
    return u


async def test_тег_вешается_и_виден_только_хозяину(db):
    cid = str((await db.scalar(select(Company).limit(1))).id)
    я, сосед = await _человек(db, cid), await _человек(db, cid)
    тег = await tag_create(TagIn(company_id=cid, name='Клиент Х', color='teal'), db=db, current_user=я)
    with pytest.raises(HTTPException) as e:
        await tag_create(TagIn(company_id=cid, name='клиент х'), db=db, current_user=я)
    assert e.value.status_code == 409, 'имя без учёта регистра — то же самое'

    ref = f'event:{uuid.uuid4()}'
    await tags_assign(AssignIn(company_id=cid, target_ref=ref, tag_ids=[тег['id']]), db=db, current_user=я)
    моё = await tags_mine(company_id=cid, db=db, current_user=я)
    assert моё['links'][ref] == [тег['id']] and моё['tags'][0]['color'] == 'teal'

    чужое = await tags_mine(company_id=cid, db=db, current_user=сосед)
    assert чужое == {'tags': [], 'links': {}}, 'сосед не видит ни тегов, ни привязок'
    with pytest.raises(HTTPException) as e:
        await tags_assign(AssignIn(company_id=cid, target_ref=ref, tag_ids=[тег['id']]), db=db, current_user=сосед)
    assert e.value.status_code == 404, 'чужой тег не повесить'
    with pytest.raises(HTTPException) as e:
        await tag_action(тег['id'], TagAction(company_id=cid, delete=True), db=db, current_user=сосед)
    assert e.value.status_code == 404


async def test_неверный_предмет_и_цвет_и_удаление_снимает(db):
    cid = str((await db.scalar(select(Company).limit(1))).id)
    я = await _человек(db, cid)
    with pytest.raises(HTTPException) as e:
        await tag_create(TagIn(company_id=cid, name='Неон', color='#00ff00'), db=db, current_user=я)
    assert e.value.status_code == 400
    тег = await tag_create(TagIn(company_id=cid, name='Бюджет', color='amber'), db=db, current_user=я)
    for плохой in ('user:' + str(uuid.uuid4()), 'event:not-a-uuid', 'http://evil'):
        with pytest.raises(HTTPException) as e:
            await tags_assign(AssignIn(company_id=cid, target_ref=плохой, tag_ids=[тег['id']]), db=db, current_user=я)
        assert e.value.status_code == 400, плохой

    ref = f'task:{uuid.uuid4()}'
    второй = await tag_create(TagIn(company_id=cid, name='Срочно мне', color='red'), db=db, current_user=я)
    await tags_assign(AssignIn(company_id=cid, target_ref=ref, tag_ids=[тег['id'], второй['id']]), db=db, current_user=я)
    # Набор целиком: прислали один — второй снялся.
    await tags_assign(AssignIn(company_id=cid, target_ref=ref, tag_ids=[второй['id']]), db=db, current_user=я)
    assert (await tags_mine(company_id=cid, db=db, current_user=я))['links'][ref] == [второй['id']]

    переименован = await tag_action(второй['id'], TagAction(company_id=cid, name='Горит', color='orange'),
                                    db=db, current_user=я)
    assert переименован['name'] == 'Горит' and переименован['color'] == 'orange'
    await tag_action(второй['id'], TagAction(company_id=cid, delete=True), db=db, current_user=я)
    assert (await db.execute(select(PersonalTagLink).where(PersonalTagLink.target_ref == ref))).first() is None


async def test_трек_отбирает_по_моему_тегу(auth_client):
    from tests.helpers import seed_company_id
    me = (await auth_client.get('/api/auth/me')).json()
    cid = seed_company_id(me)
    задачи = []
    for имя in ('Поручение с моим тегом', 'Поручение без тега'):
        r = await auth_client.post('/api/tasks', json={'company_id': cid, 'title': имя, 'assignee_id': me['id']})
        assert r.status_code == 201, r.text
        задачи.append(r.json())
    r = await auth_client.post('/api/work/tags', json={'company_id': cid, 'name': f'Отбор {uuid.uuid4().hex[:6]}', 'color': 'violet'})
    assert r.status_code == 201, r.text
    тег = r.json()
    r = await auth_client.post('/api/work/tags-assign', json={
        'company_id': cid, 'target_ref': f"task:{задачи[0]['id']}", 'tag_ids': [тег['id']]})
    assert r.status_code == 200, r.text
    body = (await auth_client.get('/api/work', params={'company_id': cid, 'scope': 'all', 'my_tag': тег['id'], 'limit': 200})).json()
    ids = {w['id'] for w in body['work']}
    assert задачи[0]['id'] in ids and задачи[1]['id'] not in ids, ids
    чужой = (await auth_client.get('/api/work', params={'company_id': cid, 'scope': 'all', 'my_tag': str(uuid.uuid4())})).json()
    assert чужой['work'] == [], 'неизвестный тег ничего не отбирает'
