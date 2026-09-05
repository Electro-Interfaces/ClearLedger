import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.models import Company, User, UserCompany
from app.routers.work_router import (
    EventAction, EventIn, calendar_action, calendar_busy, calendar_card, calendar_create,
    ReminderIn, reminder_create, reminders_list,
)

pytestmark = pytest.mark.asyncio(loop_scope='session')


async def people(db):
    company = await db.scalar(select(Company).limit(1))
    owner = await db.scalar(select(User).where(User.email == 'admin@clearledger.ru'))
    await db.merge(UserCompany(company_id=company.id, user_id=owner.id, role='admin'))
    guest = User(email=f'calendar-{uuid.uuid4()}@example.test', name='Участник', password_hash='!test', company_id=company.id)
    db.add(guest)
    await db.flush()
    db.add(UserCompany(company_id=company.id, user_id=guest.id, role='user'))
    await db.flush()
    return company, owner, guest


async def meeting(db, company, owner, guest=None, **fields):
    start = datetime.now(timezone.utc) + timedelta(days=3)
    data = dict(company_id=str(company.id), title='Рабочая встреча', starts_at=start,
                ends_at=start + timedelta(hours=1), attendee_ids=[str(guest.id)] if guest else [])
    data.update(fields)
    return await calendar_create(EventIn(**data), db=db, current_user=owner)


async def test_изменение_круга_роли_и_всего_дня_сохраняется(db):
    company, owner, guest = await people(db)
    event = await meeting(db, company, owner, guest)
    await calendar_action(event['id'], EventAction(company_id=str(company.id), visibility='private',
        all_day=True, attendee_ids=[str(guest.id)], optional_ids=[str(guest.id), str(owner.id)]), db=db, current_user=owner)
    saved = await calendar_card(event['id'], company_id=str(company.id), db=db, current_user=owner)
    assert saved['visibility'] == 'private' and saved['all_day']
    roles = {a['user_id']: a['role'] for a in saved['attendees']}
    assert roles == {str(owner.id): 'required', str(guest.id): 'optional'}


async def test_личная_встреча_не_оставляет_приглашённых(db):
    company, owner, guest = await people(db)
    event = await meeting(db, company, owner, guest)
    saved = await calendar_action(event['id'], EventAction(company_id=str(company.id), visibility='personal'), db=db, current_user=owner)
    assert [a['user_id'] for a in saved['attendees']] == [str(owner.id)]
    with pytest.raises(HTTPException) as error:
        await calendar_card(event['id'], company_id=str(company.id), db=db, current_user=guest)
    assert error.value.status_code == 403
    personal = await meeting(db, company, owner, guest, visibility='personal')
    assert [a['user_id'] for a in personal['attendees']] == [str(owner.id)]


async def test_прямая_ссылка_следует_кругу_встречи(db):
    company, owner, guest = await people(db)
    event = await meeting(db, company, owner)
    visible = await calendar_card(event['id'], company_id=str(company.id), db=db, current_user=guest)
    assert visible['my_response'] is None
    assert not visible['is_organizer']
    with pytest.raises(HTTPException) as error:
        await calendar_action(event['id'], EventAction(company_id=str(company.id), response='accepted'), db=db, current_user=guest)
    assert error.value.status_code == 403
    await calendar_action(event['id'], EventAction(company_id=str(company.id), visibility='private'), db=db, current_user=owner)
    with pytest.raises(HTTPException) as error:
        await calendar_card(event['id'], company_id=str(company.id), db=db, current_user=guest)
    assert error.value.status_code == 403


async def test_отменённая_встреча_не_принимает_ответы_и_правки(db):
    company, owner, guest = await people(db)
    event = await meeting(db, company, owner, guest)
    await calendar_action(event['id'], EventAction(company_id=str(company.id), cancel=True, cancel_reason='Согласовали другой день'), db=db, current_user=owner)
    for actor, data in [(guest, {'response': 'accepted'}), (owner, {'title': 'Новая тема'}),
                        (guest, {'propose_starts_at': event['starts_at'], 'propose_ends_at': event['ends_at']})]:
        with pytest.raises(HTTPException) as error:
            await calendar_action(event['id'], EventAction(company_id=str(company.id), **data), db=db, current_user=actor)
        assert error.value.status_code == 409


async def test_граница_серии_может_быть_снята(db):
    company, owner, guest = await people(db)
    event = await meeting(db, company, owner, recurrence={'mode': 'weekly'},
                          recurrence_until=(datetime.now(timezone.utc) + timedelta(days=30)).date())
    saved = await calendar_action(event['id'], EventAction(company_id=str(company.id), recurrence_until=None), db=db, current_user=owner)
    assert saved['recurrence_until'] is None
    assert saved['recurrence'] == {'mode': 'weekly'}


async def test_предложение_сохраняется_а_новый_ответ_его_снимает(db):
    company, owner, guest = await people(db)
    event = await meeting(db, company, owner, guest)
    start = event['starts_at'] + timedelta(hours=2)
    proposed = await calendar_action(event['id'], EventAction(company_id=str(company.id), propose_starts_at=start,
        propose_ends_at=start + timedelta(hours=1)), db=db, current_user=guest)
    attendee = next(a for a in proposed['attendees'] if a['user_id'] == str(guest.id))
    assert attendee['proposed_starts_at'] == start and attendee['response'] == 'declined'
    saved = await calendar_action(event['id'], EventAction(company_id=str(company.id), response='accepted'), db=db, current_user=guest)
    attendee = next(a for a in saved['attendees'] if a['user_id'] == str(guest.id))
    assert attendee['proposed_starts_at'] is None and attendee['proposed_ends_at'] is None


async def test_подбор_исключает_редактируемую_встречу_но_не_чужую(db):
    company, owner, guest = await people(db)
    event = await meeting(db, company, owner, guest)
    args = dict(company_id=str(company.id), date_from=event['starts_at'], date_to=event['ends_at'],
                user_ids=str(guest.id), db=db, current_user=owner)
    busy = await calendar_busy(**args)
    assert all(p['busy'] for p in busy['people'])
    free = await calendar_busy(**args, exclude_event_id=event['id'])
    before = {p['user_id']: len(p['busy']) for p in busy['people']}
    assert all(len(p['busy']) == before[p['user_id']] - 1 for p in free['people'])
    args['current_user'] = guest
    with pytest.raises(HTTPException) as error:
        await calendar_busy(**args, exclude_event_id=event['id'])
    assert error.value.status_code == 403


@pytest.mark.parametrize('fields', [
    {'recurrence': {'mode': 'weekly', 'interval': 0}},
    {'recurrence': {'mode': 'unknown'}},
    {'recurrence': {'mode': 'daily'}, 'recurrence_until': datetime(2000, 1, 1).date()},
    {'tz': 'Nowhere/Invalid'}, {'conference_url': 'javascript:alert(1)'},
])
async def test_ошибочные_настройки_не_сохраняются(db, fields):
    company, owner, guest = await people(db)
    with pytest.raises(HTTPException) as error:
        await meeting(db, company, owner, **fields)
    assert error.value.status_code == 400


async def test_пустое_и_слишком_длинное_название_отклоняется():
    for title in ['   ', 'т' * 301]:
        with pytest.raises(ValidationError):
            EventAction(company_id=str(uuid.uuid4()), title=title)


async def test_напоминания_встречи_отбираются_только_для_себя(db):
    company, owner, guest = await people(db)
    event = await meeting(db, company, owner, guest)
    target = 'event:' + event['id']
    for actor in [owner, guest]:
        await reminder_create(ReminderIn(company_id=str(company.id), target_ref=target,
            remind_at=event['starts_at'] - timedelta(minutes=15)), db=db, current_user=actor)
    result = await reminders_list(company_id=str(company.id), pending=False, target_ref=target, db=db, current_user=owner)
    assert len(result['items']) == 1 and result['items'][0]['target_ref'] == target
    await calendar_action(event['id'], EventAction(company_id=str(company.id), cancel=True), db=db, current_user=owner)
    result = await reminders_list(company_id=str(company.id), pending=False, target_ref=target, db=db, current_user=guest)
    assert not result['items']
