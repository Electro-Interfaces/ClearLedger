"""Календарь через почту: VK, Яндекс, Outlook, Gmail, Apple (QA 27.10.2026).

Стандартный путь — письмо с файлом iCalendar (iMIP): клиент сам кладёт встречу
в свой календарь, переносит и снимает её. Ломается он молча: событие на весь
день ложится встречей «00:00–00:00», а письмо с одним UID и лента подписки с
другим дают у человека две одинаковые встречи. Человек вправе выключить такие
письма в личных настройках — тогда остаётся извещение в чате.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Company, User, UserCompany
from app.services.ics import calendar_ics, event_ics


# 27.10.2026 по Москве: полночь — 21:00 UTC накануне.
ПОЛНОЧЬ = datetime(2026, 10, 26, 21, 0, tzinfo=timezone.utc)


def test_весь_день_уходит_датами():
    текст = event_ics(uid='e@trek', title='Отпуск', starts_at=ПОЛНОЧЬ,
                      ends_at=ПОЛНОЧЬ + timedelta(days=1), all_day=True, tz='Europe/Moscow')
    assert 'DTSTART;VALUE=DATE:20261027' in текст
    assert 'DTEND;VALUE=DATE:20261028' in текст, 'конец — день после последнего'
    assert 'DTSTART:2026' not in текст


def test_несколько_дней_и_конец_не_в_полночь():
    # Три дня: 27–29 октября; конец, сохранённый не полуночью, не теряет день.
    текст = event_ics(uid='e@trek', title='Командировка', starts_at=ПОЛНОЧЬ,
                      ends_at=ПОЛНОЧЬ + timedelta(days=2, hours=12), all_day=True,
                      tz='Europe/Moscow')
    assert 'DTSTART;VALUE=DATE:20261027' in текст and 'DTEND;VALUE=DATE:20261030' in текст


def test_лента_подписки_тоже_датами():
    текст = calendar_ics([{'uid': 'e@trek', 'title': 'Отпуск', 'starts_at': ПОЛНОЧЬ,
                           'ends_at': ПОЛНОЧЬ + timedelta(days=1), 'all_day': True,
                           'tz': 'Europe/Moscow'},
                          {'uid': 'f@trek', 'title': 'Планёрка', 'starts_at': ПОЛНОЧЬ,
                           'ends_at': ПОЛНОЧЬ + timedelta(hours=1)}])
    assert 'DTSTART;VALUE=DATE:20261027' in текст
    assert 'DTSTART:20261026T210000Z' in текст, 'обычная встреча осталась моментом'


async def _люди(db):
    company = await db.scalar(select(Company).limit(1))
    хозяин = await db.scalar(select(User).where(User.email == 'admin@clearledger.ru'))
    await db.merge(UserCompany(company_id=company.id, user_id=хозяин.id, role='admin'))
    зван = User(email=f'mail-{uuid.uuid4()}@example.test', name='Позванный',
                password_hash='!test', company_id=company.id)
    db.add(зван)
    await db.flush()
    db.add(UserCompany(company_id=company.id, user_id=зван.id, role='user'))
    await db.flush()
    return company, хозяин, зван


@pytest.mark.asyncio(loop_scope='session')
async def test_письмо_с_календарём_и_выключатель(db, monkeypatch):
    from app.routers.work_router import EventAction, EventIn, calendar_action, calendar_create
    from app.services import email_service

    письма = []

    async def не_слать(to, **поля):
        письма.append((to, поля))
        return True
    monkeypatch.setattr(email_service, 'send_meeting_invite', не_слать)
    company, хозяин, зван = await _люди(db)
    день = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=21, minute=0, second=0, microsecond=0)
    ev = await calendar_create(EventIn(
        company_id=str(company.id), title='Выездной день', starts_at=день,
        ends_at=день + timedelta(days=1), all_day=True, attendee_ids=[str(зван.id)]),
        db=db, current_user=хозяин)

    кому = [p for to, p in письма if to == зван.email]
    assert кому, 'приглашения письмом нет'
    файл = кому[0]['ics']
    assert 'METHOD:REQUEST' in файл and кому[0]['method'] == 'REQUEST'
    assert 'DTSTART;VALUE=DATE:' in файл, 'событие на весь день ушло моментом'
    assert f'UID:{ev["id"]}@trek' in файл
    assert f'mailto:{зван.email}' in файл, 'получателя нет в составе — VK не покажет кнопок'
    assert 'весь день' in кому[0]['subject'] and '00:00' not in кому[0]['subject']

    # Выключил «Встречи — в мой почтовый календарь»: письма нет, чат остаётся.
    зван.email_notify = ['digest']
    await db.flush()
    письма.clear()
    новый = день + timedelta(days=1)
    await calendar_action(ev['id'], EventAction(company_id=str(company.id), starts_at=новый,
                                                ends_at=новый + timedelta(days=1)),
                          db=db, current_user=хозяин)
    assert not [1 for to, _ in письма if to == зван.email], 'письмо ушло вопреки настройке'


@pytest.mark.asyncio(loop_scope='session')
async def test_продление_это_изменение_и_отозванному_гостю_не_пишем(db, monkeypatch):
    from app.models import CalendarGuest
    from app.routers.work_router import EventAction, EventIn, calendar_action, calendar_create
    from app.services import email_service

    письма = []

    async def не_слать(to, **поля):
        письма.append((to, поля))
        return True
    monkeypatch.setattr(email_service, 'send_meeting_invite', не_слать)
    company, хозяин, зван = await _люди(db)
    день = (datetime.now(timezone.utc) + timedelta(days=5)).replace(hour=21, minute=0, second=0, microsecond=0)
    ev = await calendar_create(EventIn(
        company_id=str(company.id), title='Выставка', starts_at=день,
        ends_at=день + timedelta(days=1), all_day=True, attendee_ids=[str(зван.id)]),
        db=db, current_user=хозяин)
    db.add(CalendarGuest(event_id=uuid.UUID(ev['id']), email='otozvan@example.test', token_hash='x' * 64,
                         token_prefix='x' * 8, expires_at=день, revoked_at=datetime.now(timezone.utc)))
    await db.flush()
    письма.clear()
    await calendar_action(ev['id'], EventAction(company_id=str(company.id), starts_at=день,
                                                ends_at=день + timedelta(days=3)),
                          db=db, current_user=хозяин)
    тема = next(p['subject'] for to, p in письма if to == зван.email)
    assert тема.startswith('Изменено:') and ' – ' in тема and 'весь день' in тема, тема
    assert not [1 for to, _ in письма if to == 'otozvan@example.test'], 'отозванному гостю ушло письмо'
