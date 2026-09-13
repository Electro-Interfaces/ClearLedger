"""Приложение «Конференции»: созыв, вход, журнал и статистика."""
import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.models import Company, ConfSession, User, UserCompany
from app.routers.conf_router import (
    MeetingIn, conf_stats, meeting_create, meeting_join, meetings_list,
    meetings_live, session_end,
)

pytestmark = pytest.mark.asyncio(loop_scope='session')


@pytest.fixture
def jitsi_key():
    """Ключ подписи на время теста: без него конференции выключены (503)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    s = get_settings()
    было = s.jitsi_signing_key
    s.jitsi_signing_key = base64.b64encode(pem).decode()
    yield
    s.jitsi_signing_key = было


async def люди(db):
    company = await db.scalar(select(Company).limit(1))
    хозяин = await db.scalar(select(User).where(User.email == 'admin@clearledger.ru'))
    await db.merge(UserCompany(company_id=company.id, user_id=хозяин.id, role='admin'))
    зван = User(email=f'conf-{uuid.uuid4()}@example.test', name='Приглашённый',
                password_hash='!test', company_id=company.id)
    чужой = User(email=f'conf-{uuid.uuid4()}@example.test', name='Посторонний',
                 password_hash='!test', company_id=company.id)
    db.add_all([зван, чужой])
    await db.flush()
    db.add(UserCompany(company_id=company.id, user_id=зван.id, role='user'))
    db.add(UserCompany(company_id=company.id, user_id=чужой.id, role='user'))
    await db.flush()
    return company, хозяин, зван, чужой


async def созвать(db, company, кто, **поля):
    данные = dict(company_id=str(company.id), title='Разбор смены', notify=False)
    данные.update(поля)
    return await meeting_create(MeetingIn(**данные), db=db, current_user=кто)


async def test_созвон_попадает_в_журнал_и_календарь(db, jitsi_key):
    company, хозяин, зван, _ = await люди(db)
    встреча = await созвать(db, company, хозяин, attendee_ids=[str(зван.id)])
    assert встреча['guest_url'] and '/ledger-' in встреча['guest_url'], \
        'ссылка для участников не ведёт в нашу комнату'
    assert {a['user_id'] for a in встреча['attendees']} == {str(хозяин.id), str(зван.id)}

    # Пока никто не вошёл — разговор не идёт: назначить можно что угодно.
    assert (await meetings_live(company_id=str(company.id), db=db,
                                current_user=хозяин))['live'] == []

    вход = await meeting_join(встреча['id'], company_id=str(company.id),
                              db=db, current_user=хозяин)
    assert вход['moderator_url'] != вход['guest_url'], 'гостю ушёл токен ведущего'
    идут = (await meetings_live(company_id=str(company.id), db=db,
                                current_user=хозяин))['live']
    assert len(идут) == 1 and идут[0]['title'] == 'Разбор смены'
    assert [ч['name'] for ч in идут[0]['came']] == [хозяин.name]

    # Второй участник входит в ТОТ ЖЕ разговор, а не заводит свой.
    await meeting_join(встреча['id'], company_id=str(company.id), db=db, current_user=зван)
    идут = (await meetings_live(company_id=str(company.id), db=db,
                                current_user=хозяин))['live']
    assert len(идут) == 1 and len(идут[0]['came']) == 2

    await session_end(вход['session_id'], company_id=str(company.id),
                      db=db, current_user=хозяин)
    assert (await meetings_live(company_id=str(company.id), db=db,
                                current_user=хозяин))['live'] == []


async def test_статистика_считает_состоявшиеся_разговоры(db, jitsi_key):
    company, хозяин, зван, _ = await люди(db)
    встреча = await созвать(db, company, хозяин, attendee_ids=[str(зван.id)],
                            subject_ref='doc:00000000-0000-0000-0000-000000000001')
    вход = await meeting_join(встреча['id'], company_id=str(company.id),
                              db=db, current_user=хозяин)
    # Разговор длиной в полчаса: сессию закрываем задним числом.
    сессия = await db.get(ConfSession, uuid.UUID(вход['session_id']))
    сессия.started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    сессия.ended_at = datetime.now(timezone.utc)
    await db.commit()

    д = await conf_stats(company_id=str(company.id), days=7, db=db, current_user=хозяин)
    assert д['total'] >= 1
    мой = next(ч for ч in д['people'] if ч['user_id'] == str(хозяин.id))
    assert 25 * 60 <= мой['seconds'] <= 35 * 60, 'время разговора посчитано неверно'
    предметы = {п['subject_ref'] for п in д['subjects']}
    assert 'doc:00000000-0000-0000-0000-000000000001' in предметы


async def test_закрытую_встречу_чужому_не_открыть(db, jitsi_key):
    company, хозяин, зван, чужой = await люди(db)
    встреча = await созвать(db, company, хозяин, attendee_ids=[str(зван.id)])
    # Круг «company» — по умолчанию: созвон виден пространству. Закрываем его.
    from app.models import CalendarEvent
    ev = await db.get(CalendarEvent, uuid.UUID(встреча['id']))
    ev.visibility = 'private'
    await db.commit()

    with pytest.raises(HTTPException) as отказ:
        await meeting_join(встреча['id'], company_id=str(company.id),
                           db=db, current_user=чужой)
    assert отказ.value.status_code == 403
    видит = await meetings_list(company_id=str(company.id), scope='upcoming',
                                q='', limit=50, db=db, current_user=чужой)
    assert встреча['id'] not in {в['id'] for в in видит['meetings']}


async def test_завершённая_уходит_из_назначенных_в_историю(db, jitsi_key):
    """Раздел делится по факту, а не по часам: закрытая конференция — прошедшая,
    даже если по расписанию её час ещё не кончился."""
    company, хозяин, зван, _ = await люди(db)
    встреча = await созвать(db, company, хозяин, attendee_ids=[str(зван.id)], minutes=120)
    вход = await meeting_join(встреча['id'], company_id=str(company.id),
                              db=db, current_user=хозяин)

    назначены = await meetings_list(company_id=str(company.id), scope='upcoming',
                                    q='', limit=50, db=db, current_user=хозяин)
    assert встреча['id'] in {в['id'] for в in назначены['meetings']}

    await session_end(вход['session_id'], company_id=str(company.id),
                      db=db, current_user=хозяин)

    назначены = await meetings_list(company_id=str(company.id), scope='upcoming',
                                    q='', limit=50, db=db, current_user=хозяин)
    assert встреча['id'] not in {в['id'] for в in назначены['meetings']},         'завершённая конференция осталась в «назначены»'
    история = await meetings_list(company_id=str(company.id), scope='past',
                                  q='', limit=50, db=db, current_user=хозяин)
    assert встреча['id'] in {в['id'] for в in история['meetings']}
