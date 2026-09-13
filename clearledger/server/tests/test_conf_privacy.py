"""Приватность конференций: чего посторонний не должен видеть.

Проверка написана по находке приёмки CONF-01 (10.09.2026): «Идут сейчас»
отдавали любую конференцию пространства вместе с гостевой ссылкой, и человек,
которого не звали, видел тему закрытого разговора и мог унести ссылку наружу.
"""
import base64
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from app.config import get_settings
from app.models import CalendarEvent, Company, User, UserCompany
from app.routers.conf_router import (
    MeetingIn, meeting_create, meeting_join, meetings_live,
)

pytestmark = pytest.mark.asyncio(loop_scope='session')


@pytest.fixture
def jitsi_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    s = get_settings()
    было = s.jitsi_signing_key
    s.jitsi_signing_key = base64.b64encode(pem).decode()
    yield
    s.jitsi_signing_key = было


async def трое(db):
    company = await db.scalar(select(Company).limit(1))
    хозяин = await db.scalar(select(User).where(User.email == 'admin@clearledger.ru'))
    await db.merge(UserCompany(company_id=company.id, user_id=хозяин.id, role='admin'))
    зван = User(email=f'p-{uuid.uuid4()}@example.test', name='Приглашённый',
                password_hash='!test', company_id=company.id)
    чужой = User(email=f'p-{uuid.uuid4()}@example.test', name='Посторонний',
                 password_hash='!test', company_id=company.id)
    db.add_all([зван, чужой])
    await db.flush()
    db.add(UserCompany(company_id=company.id, user_id=зван.id, role='user'))
    db.add(UserCompany(company_id=company.id, user_id=чужой.id, role='user'))
    await db.flush()
    return company, хозяин, зван, чужой


async def test_идущая_закрытая_конференция_не_видна_постороннему(db, jitsi_key):
    company, хозяин, зван, чужой = await трое(db)
    встреча = await meeting_create(MeetingIn(
        company_id=str(company.id), title='Закрытый разбор',
        attendee_ids=[str(зван.id)], notify=False), db=db, current_user=хозяин)
    await meeting_join(встреча['id'], company_id=str(company.id),
                       db=db, current_user=хозяин)

    свои = await meetings_live(company_id=str(company.id), db=db, current_user=зван)
    assert [с['title'] for с in свои['live']] == ['Закрытый разбор'], \
        'приглашённый должен видеть конференцию, куда его позвали'

    чужие = await meetings_live(company_id=str(company.id), db=db, current_user=чужой)
    названия = [с['title'] for с in чужие['live']]
    assert 'Закрытый разбор' not in названия, \
        'посторонний видит тему закрытого разговора'
    assert all('guest_url' not in с or 'Закрытый' not in с['title']
               for с in чужие['live']), 'посторонний получил гостевую ссылку'


async def test_открытую_пространству_видно_всем(db, jitsi_key):
    company, хозяин, _, чужой = await трое(db)
    встреча = await meeting_create(MeetingIn(
        company_id=str(company.id), title='Открытая планёрка',
        open_to_space=True, notify=False), db=db, current_user=хозяин)
    await meeting_join(встреча['id'], company_id=str(company.id),
                       db=db, current_user=хозяин)

    чужие = await meetings_live(company_id=str(company.id), db=db, current_user=чужой)
    открытая = next((с for с in чужие['live'] if с['title'] == 'Открытая планёрка'), None)
    assert открытая is not None, 'открытую пространству конференцию должно быть видно'
    assert открытая['guest_url'], 'войти в открытую конференцию должно быть чем'


async def test_закрытая_остаётся_закрытой_и_в_списках(db, jitsi_key):
    company, хозяин, _, чужой = await трое(db)
    встреча = await meeting_create(MeetingIn(
        company_id=str(company.id), title='Только свои', notify=False),
        db=db, current_user=хозяин)
    ev = await db.get(CalendarEvent, uuid.UUID(встреча['id']))
    assert ev.visibility == 'private', 'конференция по умолчанию обязана быть закрытой'

    from app.routers.conf_router import meetings_list
    видит = await meetings_list(company_id=str(company.id), scope='upcoming',
                                q='', limit=50, db=db, current_user=чужой)
    assert встреча['id'] not in {в['id'] for в in видит['meetings']}
