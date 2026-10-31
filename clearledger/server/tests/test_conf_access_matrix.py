"""Закрытая и открытая конференция: кто видит и кто входит (QA 27.10.2026).

Вход есть в двух местах — «Конференции» (`meeting_join`) и карточка календаря
(`calendar_meeting`), — и правило у них должно быть одно: закрытую открывают
организатор и позванные, открытую пространству — любой сотрудник. Карточка
открытой встречи тоже должна открываться: календарь компании показывает её
всем, и кнопка «Войти» без карточки была бы недостижима.
"""
import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.models import Company, User, UserCompany

pytestmark = pytest.mark.asyncio(loop_scope='session')


@pytest.fixture
def jitsi_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    s = get_settings()
    было = s.jitsi_signing_key
    s.jitsi_signing_key = base64.b64encode(pem).decode()
    yield
    s.jitsi_signing_key = было


async def _call(fn, *a, **kw):
    try:
        return 'ok', await fn(*a, **kw)
    except HTTPException as e:
        return e.status_code, e.detail


async def test_матрица_доступа(db, jitsi_key):
    from app.routers import conf_router as C, work_router as W

    company = await db.scalar(select(Company).limit(1))
    org = await db.scalar(select(User).where(User.email == 'admin@clearledger.ru'))
    await db.merge(UserCompany(company_id=company.id, user_id=org.id, role='admin'))
    inv = User(email=f'acc-{uuid.uuid4()}@example.test', name='Позванный', password_hash='!t', company_id=company.id)
    out = User(email=f'acc-{uuid.uuid4()}@example.test', name='Чужой', password_hash='!t', company_id=company.id)
    db.add_all([inv, out]); await db.flush()
    db.add_all([UserCompany(company_id=company.id, user_id=inv.id, role='user'),
                UserCompany(company_id=company.id, user_id=out.id, role='user')]); await db.flush()
    cid = str(company.id)
    t0 = datetime.now(timezone.utc) - timedelta(minutes=10)
    made = {
        'конф-закрытая': (await C.meeting_create(C.MeetingIn(company_id=cid, title='Закрытая', starts_at=t0,
                          attendee_ids=[str(inv.id)], notify=False), db=db, current_user=org))['id'],
        'конф-открытая': (await C.meeting_create(C.MeetingIn(company_id=cid, title='Открытая', starts_at=t0,
                          open_to_space=True, notify=False), db=db, current_user=org))['id'],
        'кал-закрытая': (await W.calendar_create(W.EventIn(company_id=cid, title='Кал закрытая', starts_at=t0,
                         ends_at=t0 + timedelta(hours=1), visibility='private', video=True,
                         attendee_ids=[str(inv.id)]), db=db, current_user=org))['id'],
        'кал-открытая': (await W.calendar_create(W.EventIn(company_id=cid, title='Кал открытая', starts_at=t0,
                         ends_at=t0 + timedelta(hours=1), visibility='company', video=True),
                         db=db, current_user=org))['id'],
    }
    rng = dict(date_from=t0 - timedelta(hours=1), date_to=t0 + timedelta(hours=3), q=None, subject_ref=None)
    итог = {}
    for who, u in (('позванный', inv), ('чужой', out)):
        comp = {e['id']: e for e in (await W.calendar_list(company_id=cid, scope='company', db=db,
                                                           current_user=u, **rng))['events']}
        идут = {x.get('event_id') for x in (await C.meetings_live(company_id=cid, db=db, current_user=u))['live']}
        for k, i in made.items():
            j = await _call(C.meeting_join, i, company_id=cid, db=db, current_user=u)
            m = await _call(W.calendar_meeting, i, company_id=cid, db=db, current_user=u)
            c = await _call(W.calendar_card, i, company_id=cid, db=db, current_user=u)
            итог[(who, k)] = (j[0], m[0], c[0], i in comp, i in идут)
            print(who, k, 'вход_конф', j[0], 'вход_календарь', m[0], 'карточка', c[0],
                  'в_календаре_компании', i in comp, 'тема видна' if comp.get(i, {}).get('title') not in (None, '', 'Занято') else '')
    for k in ('конф-закрытая', 'кал-закрытая'):
        assert итог[('позванный', k)][:3] == ('ok', 'ok', 'ok'), k
        assert итог[('чужой', k)][0] == 403 and итог[('чужой', k)][1] in (403, 404), k
        assert not итог[('чужой', k)][3] and not итог[('чужой', k)][4], f'{k}: чужой видит закрытую в календаре компании или в «Идут сейчас»'
    for k in ('конф-открытая', 'кал-открытая'):
        assert итог[('чужой', k)][:2] == ('ok', 'ok'), f'{k}: открытая не пускает чужого'
        assert итог[('чужой', k)][2] == 'ok', f'{k}: карточка открытой встречи не открывается сотруднику'
        assert итог[('чужой', k)][4], f'{k}: идущая открытая не видна в «Идут сейчас»'


async def test_кто_ведущий(db, jitsi_key):
    """Организатор — ведущий всегда; до начала позванный ждёт; через 5 минут без
    ведущего пропуск получает первый вошедший, следующий — уже нет."""
    from app.routers import conf_router as C, work_router as W

    company = await db.scalar(select(Company).limit(1))
    org = await db.scalar(select(User).where(User.email == 'admin@clearledger.ru'))
    await db.merge(UserCompany(company_id=company.id, user_id=org.id, role='admin'))
    a = User(email=f'host-{uuid.uuid4()}@example.test', name='Первый', password_hash='!t', company_id=company.id)
    b = User(email=f'host-{uuid.uuid4()}@example.test', name='Второй', password_hash='!t', company_id=company.id)
    db.add_all([a, b]); await db.flush()
    db.add_all([UserCompany(company_id=company.id, user_id=a.id, role='user'),
                UserCompany(company_id=company.id, user_id=b.id, role='user')]); await db.flush()
    cid = str(company.id)
    позже = datetime.now(timezone.utc) + timedelta(hours=1)
    рано = await W.calendar_create(W.EventIn(company_id=cid, title='Позже', starts_at=позже, ends_at=позже + timedelta(hours=1),
                                             visibility='private', video=True, attendee_ids=[str(a.id)]), db=db, current_user=org)
    assert (await C.meeting_join(рано['id'], company_id=cid, db=db, current_user=a))['moderator'] is False, 'до начала позванный стал ведущим'
    assert (await W.calendar_meeting(рано['id'], company_id=cid, db=db, current_user=org))['moderator'] is True
    шло = datetime.now(timezone.utc) - timedelta(minutes=10)
    идёт = await W.calendar_create(W.EventIn(company_id=cid, title='Идёт', starts_at=шло, ends_at=шло + timedelta(hours=1),
                                             visibility='private', video=True, attendee_ids=[str(a.id), str(b.id)]), db=db, current_user=org)
    первый = await W.calendar_meeting(идёт['id'], company_id=cid, db=db, current_user=a)
    второй = await C.meeting_join(идёт['id'], company_id=cid, db=db, current_user=b)
    assert первый['moderator'] is True, 'через 5 минут без ведущего первый вошедший не получил пропуск'
    assert второй['moderator'] is False, 'второй вошедший тоже стал ведущим'
    assert первый['session_id'] == второй['session_id'], 'вход из календаря и из «Конференций» завели разные сессии'


async def test_завершить_только_хозяин_и_встреча_сокращается(db, jitsi_key):
    """«Завершить» — организатору; чужой из компании прямым запросом не гасит.
    После завершения конец встречи в календаре — фактический."""
    from app.models import CalendarEvent
    from app.routers import conf_router as C, work_router as W

    company = await db.scalar(select(Company).limit(1))
    org = await db.scalar(select(User).where(User.email == 'admin@clearledger.ru'))
    await db.merge(UserCompany(company_id=company.id, user_id=org.id, role='admin'))
    out = User(email=f'end-{uuid.uuid4()}@example.test', name='Чужой', password_hash='!t', company_id=company.id)
    db.add(out); await db.flush()
    db.add(UserCompany(company_id=company.id, user_id=out.id, role='user')); await db.flush()
    cid = str(company.id)
    шло = datetime.now(timezone.utc) - timedelta(minutes=10)
    ev = await W.calendar_create(W.EventIn(company_id=cid, title='Открытая', starts_at=шло, ends_at=шло + timedelta(hours=1),
                                           visibility='company', video=True), db=db, current_user=org)
    вход = await C.meeting_join(ev['id'], company_id=cid, db=db, current_user=out)
    чужой = await _call(C.session_end, вход['session_id'], company_id=cid, db=db, current_user=out)
    assert чужой[0] == 403, 'чужой сотрудник закрыл открытую конференцию'
    итог = await C.session_end(вход['session_id'], company_id=cid, db=db, current_user=org)
    строка = await db.get(CalendarEvent, uuid.UUID(ev['id']))
    await db.refresh(строка)
    assert abs((строка.ends_at - итог['ended_at']).total_seconds()) < 1, 'конец встречи не сократился до фактического'
