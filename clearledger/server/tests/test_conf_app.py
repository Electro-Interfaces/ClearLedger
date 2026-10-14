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
    MeetingIn, _сессия_записи, conf_stats, meeting_create, meeting_join,
    meetings_list, meetings_live, room_join, rooms_list, session_end,
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


async def test_серия_одна_комната_и_ссылка_у_повторений(db, jitsi_key):
    """Повторение серии входит в комнату головы, а не в свою.

    Ссылку повторения берут у головы; вход считал комнату от своего номера, и
    ведущий с гостями оказывались в разных комнатах. Повторения, созданные до
    первого входа, ссылки не имели и в «Конференциях» не показывались.
    """
    from app.models import CalendarAttendee, CalendarEvent
    from app.services import jitsi

    company, хозяин, _, _ = await люди(db)
    завтра = datetime.now(timezone.utc) + timedelta(days=1)
    голова = CalendarEvent(company_id=company.id, organizer_id=хозяин.id,
                           title='Планёрка', starts_at=завтра,
                           ends_at=завтра + timedelta(hours=1), tz='Europe/Moscow',
                           visibility='private', recurrence={'mode': 'weekly'})
    db.add(голова)
    await db.flush()
    повтор = CalendarEvent(company_id=company.id, organizer_id=хозяин.id,
                           title='Планёрка', starts_at=завтра + timedelta(days=42),
                           ends_at=завтра + timedelta(days=42, hours=1),
                           tz='Europe/Moscow', visibility='private',
                           series_id=голова.id)
    db.add(повтор)
    await db.flush()
    db.add(CalendarAttendee(event_id=повтор.id, user_id=хозяин.id,
                            role='required', response='accepted'))
    await db.flush()

    вход = await meeting_join(str(повтор.id), company_id=str(company.id),
                              db=db, current_user=хозяин)
    assert вход['room'] == jitsi.room_for(f'event:{голова.id}')
    await db.refresh(голова)
    assert голова.conference_url == вход['guest_url']

    # Вошли за шесть недель до даты: конференция не висит до конца встречи.
    сессия = await db.get(ConfSession, uuid.UUID(вход['session_id']))
    сессия.started_at = datetime.now(timezone.utc) - timedelta(hours=5)
    await db.flush()
    идут = await meetings_live(company_id=str(company.id), db=db, current_user=хозяин)
    assert вход['session_id'] not in [с['id'] for с in идут['live']]


async def test_запись_ложится_на_свой_созыв(db):
    """Опоздавшая запись постоянной комнаты — созыву, в который писалась."""
    from zoneinfo import ZoneInfo

    company, хозяин, _, _ = await люди(db)
    room = f'ledger-{uuid.uuid4().hex[:16]}'
    мск = ZoneInfo('Europe/Moscow')
    старый = ConfSession(company_id=company.id, room=room, title='Оперативка',
                         started_by=хозяин.id,
                         started_at=datetime(2026, 10, 6, 17, 9, tzinfo=мск))
    новый = ConfSession(company_id=company.id, room=room, title='Оперативка',
                        started_by=хозяин.id,
                        started_at=datetime(2026, 10, 13, 10, 7, tzinfo=мск))
    db.add_all([старый, новый])
    await db.flush()

    своя = await _сессия_записи(db, room, f'{room}_2026-10-06-17-48-38.mp4')
    assert своя.id == старый.id
    # Имя без времени — как раньше, последний созыв.
    assert (await _сессия_записи(db, room, 'запись.mp4')).id == новый.id
    assert await _сессия_записи(db, 'ledger-чужая', None) is None


async def _списки(db, company, кто):
    """Номера встреч в «Назначены» и в «Истории»."""
    def ids(ответ):
        return {в['id'] for в in ответ['meetings']}
    return (ids(await meetings_list(company_id=str(company.id), scope='upcoming',
                                    q='', limit=200, db=db, current_user=кто)),
            ids(await meetings_list(company_id=str(company.id), scope='past',
                                    q='', limit=200, db=db, current_user=кто)))


async def test_отменённая_не_висит_в_назначенных(db, jitsi_key):
    from app.models import CalendarEvent

    company, хозяин, _, _ = await люди(db)
    завтра = datetime.now(timezone.utc) + timedelta(days=1)
    встреча = await созвать(db, company, хозяин, starts_at=завтра)
    assert встреча['id'] in (await _списки(db, company, хозяин))[0]

    (await db.get(CalendarEvent, uuid.UUID(встреча['id']))).status = 'cancelled'
    await db.flush()
    assert встреча['id'] not in (await _списки(db, company, хозяин))[0]


async def test_вход_до_срока_не_уводит_встречу_в_историю(db, jitsi_key):
    """Зашли проверить комнату за день до встречи и нажали «Завершить» —
    встреча остаётся назначенной."""
    company, хозяин, _, _ = await люди(db)
    завтра = datetime.now(timezone.utc) + timedelta(days=1)
    встреча = await созвать(db, company, хозяин, starts_at=завтра)
    вход = await meeting_join(встреча['id'], company_id=str(company.id),
                              db=db, current_user=хозяин)
    await session_end(вход['session_id'], company_id=str(company.id),
                      db=db, current_user=хозяин)

    назначены, история = await _списки(db, company, хозяин)
    assert встреча['id'] in назначены
    assert встреча['id'] not in история


async def test_тема_едет_в_ссылке_входа(db, jitsi_key):
    company, хозяин, _, _ = await люди(db)
    встреча = await созвать(db, company, хозяин, title='Разбор «смены» №5')
    вход = await meeting_join(встреча['id'], company_id=str(company.id),
                              db=db, current_user=хозяин)
    from urllib.parse import unquote
    assert unquote(вход['moderator_url']).endswith(
        '#config.subject="Разбор «смены» №5"')
    # Гостевая — голый адрес комнаты: по нему её узнают календарь и журнал.
    assert '#' not in вход['guest_url'] and вход['guest_url'] == встреча['guest_url']


async def test_пустая_постоянная_комната_закрывается(db, jitsi_key):
    """Все вышли — разговор окончен без кнопки и без четырёхчасового срока."""
    from app.models import ConfPresence, ConfRoom

    company, хозяин, зван, _ = await люди(db)
    комната = ConfRoom(company_id=company.id, name='Переговорная', created_by=хозяин.id)
    db.add(комната)
    await db.flush()

    async def карточка():
        ответ = await rooms_list(company_id=str(company.id), db=db, current_user=хозяин)
        return next(к for к in ответ['rooms'] if к['id'] == str(комната.id))

    вход = await room_join(str(комната.id), company_id=str(company.id),
                           db=db, current_user=хозяин)
    await room_join(str(комната.id), company_id=str(company.id), db=db, current_user=зван)
    assert '#config.subject=' in вход['moderator_url']
    к = await карточка()
    assert к['live'] and len(к['inside']) == 2, 'вошедший виден сразу, до первого сигнала'

    сессия = await db.get(ConfSession, uuid.UUID(вход['session_id']))
    отметки = (await db.execute(select(ConfPresence).where(
        ConfPresence.session_id == сессия.id))).scalars().all()
    сейчас = datetime.now(timezone.utc)
    сессия.started_at = сейчас - timedelta(minutes=20)
    # Один вышел давно, второй только что: комната ещё живая.
    отметки[0].left_at = сейчас - timedelta(minutes=10)
    отметки[1].left_at = сейчас - timedelta(seconds=20)
    await db.flush()
    assert (await карточка())['live']

    # Вернулся за забытым вопросом — тот же разговор, отметка о выходе снята.
    await room_join(str(комната.id), company_id=str(company.id), db=db, current_user=зван)
    await db.refresh(отметки[1])
    к = await карточка()
    assert к['live'] and len(к['inside']) == 1

    ушёл = сейчас - timedelta(minutes=3)
    for p in отметки:
        await db.refresh(p)
        p.left_at = ушёл
    await db.flush()
    к = await карточка()
    assert not к['live'] and not к['inside']
    await db.refresh(сессия)
    assert сессия.close_reason == 'empty' and сессия.ended_at == ушёл

    # Вкладки замолчали, никто не вышел: ждём дольше, но тоже закрываем.
    вход = await room_join(str(комната.id), company_id=str(company.id),
                           db=db, current_user=хозяин)
    новая = await db.get(ConfSession, uuid.UUID(вход['session_id']))
    assert новая.id != сессия.id
    p = (await db.execute(select(ConfPresence).where(
        ConfPresence.session_id == новая.id))).scalar_one()
    p.last_seen_at = сейчас - timedelta(minutes=3)
    await db.flush()
    assert (await карточка())['live']
    p.last_seen_at = сейчас - timedelta(minutes=6)
    await db.flush()
    assert not (await карточка())['live']


async def test_запись_удаляет_организатор_но_не_приглашённый(db, tmp_path, monkeypatch):
    """Запись убирает тот, кто собрал, — файл уходит с диска, созыв остаётся."""
    from pathlib import Path

    from app.models import SourceFile
    from app.routers.conf_router import recording_remove, recordings_list
    from app.services import file_store

    monkeypatch.setenv('UPLOAD_DIR', str(tmp_path))
    company, хозяин, зван, _ = await люди(db)
    файл = file_store.put(db, company.id, b'mp4', file_name='r.mp4', mime='video/mp4')
    await db.flush()
    s = ConfSession(company_id=company.id, room='ledger-rm', title='Разбор',
                    started_by=хозяин.id, recording_file_id=файл.id)
    db.add(s)
    await db.flush()
    cid = str(company.id)

    своё = [з for з in (await recordings_list(company_id=cid, limit=50, db=db,
                                              current_user=хозяин))['recordings']
            if з['session_id'] == str(s.id)]
    assert своё and своё[0]['can_remove']

    # Не участник и не организатор — запись ему даже не видна, удалить нельзя.
    with pytest.raises(HTTPException) as отказ:
        await recording_remove(str(s.id), company_id=cid, db=db, current_user=зван)
    assert отказ.value.status_code == 403

    путь = Path(файл.storage_path)
    assert путь.exists()
    await recording_remove(str(s.id), company_id=cid, db=db, current_user=хозяин)
    assert not путь.exists()
    assert s.recording_file_id is None
    assert await db.get(SourceFile, файл.id) is None
    assert await db.get(ConfSession, s.id) is not None


async def _сообщения(db, кому):
    """Строки чата, пришедшие человеку от других (личные комнаты)."""
    from app.models import ChatMessage, ChatParticipant
    комнаты = select(ChatParticipant.room_id).where(ChatParticipant.user_id == кому.id)
    return list((await db.execute(select(ChatMessage.content).where(
        ChatMessage.room_id.in_(комнаты), ChatMessage.user_id != кому.id))).scalars())


async def test_отмена_и_перенос_доходят_до_участников(db, jitsi_key, monkeypatch):
    """РусГидро, «ТЗ по СРМ» пп. 2–3: отмена и перенос не должны быть молчаливыми."""
    from app.models import PersonalReminder
    from app.routers.work_router import EventAction, calendar_action
    from app.services import reminders

    from app.services import email_service

    письма = []

    async def не_слать(to, **поля):
        письма.append((to, поля['method']))
        return True
    # Тестовый контейнер видит почтовый сервер стека: письма не отправляем, а считаем.
    monkeypatch.setattr(email_service, 'send_meeting_invite', не_слать)
    company, хозяин, зван, _ = await люди(db)
    начало = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    встреча = await созвать(db, company, хозяин, attendee_ids=[str(зван.id)], starts_at=начало)
    ev_id = встреча['id']
    напоминание = await reminders.put(db, company.id, зван.id, f'event:{ev_id}',
                                      начало - timedelta(minutes=15))
    await db.commit()

    новое = начало + timedelta(days=1)
    await calendar_action(ev_id, EventAction(company_id=str(company.id), starts_at=новое,
                                             ends_at=новое + timedelta(hours=1)),
                          db=db, current_user=хозяин)
    assert any('перенесена' in m for m in await _сообщения(db, зван)), 'о переносе не сказали'
    assert (зван.email, 'REQUEST') in письма, 'письма о переносе нет'
    await db.refresh(напоминание)
    assert напоминание.remind_at == новое - timedelta(minutes=15), 'напоминание осталось на старом времени'

    await calendar_action(ev_id, EventAction(company_id=str(company.id), cancel=True,
                                             cancel_reason='заболел докладчик'),
                          db=db, current_user=хозяин)
    assert any('отменена: заболел докладчик' in m for m in await _сообщения(db, зван))
    assert (зван.email, 'CANCEL') in письма, 'письма об отмене нет'
    assert await db.get(PersonalReminder, напоминание.id) is None


async def test_протокол_черновик_сохранение_и_рассылка(db, tmp_path, monkeypatch):
    """«Дешифратор + протокол»: черновик по расшифровке, исполнитель — из участников."""
    from app.routers.conf_router import (ProtocolIn, ProtocolItemIn, recording_protocol,
                                         recording_transcript)
    from app.services import file_store

    monkeypatch.setenv('UPLOAD_DIR', str(tmp_path))
    company, хозяин, зван, чужой = await люди(db)
    зван.name = 'Марков Антон Александрович'
    файл = file_store.put(db, company.id, b'mp4', file_name='p.mp4', mime='video/mp4')
    await db.flush()
    s = ConfSession(company_id=company.id, room='ledger-pr', title='Планёрка',
                    started_by=хозяин.id, recording_file_id=файл.id, transcript_status='done',
                    transcript=[{'start': 3, 'end': 8, 'text': 'Решили начать монтаж в ноябре.'},
                                {'start': 9, 'end': 15, 'text': 'Антону подготовить смету до пятницы.'}])
    db.add(s)
    from app.models import ConfPresence
    await db.flush()
    db.add(ConfPresence(session_id=s.id, user_id=зван.id))
    await db.commit()
    cid = str(company.id)

    t = await recording_transcript(str(s.id), company_id=cid, db=db, current_user=хозяин)
    assert t['draft'] and [п['kind'] for п in t['protocol']] == ['decision', 'task']
    assert t['protocol'][1]['assignee_id'] == str(зван.id)

    # Посторонний записи не видит — и протокол ему не открыть.
    with pytest.raises(HTTPException) as отказ:
        await recording_transcript(str(s.id), company_id=cid, db=db, current_user=чужой)
    assert отказ.value.status_code == 404

    # Исполнитель — только участник встречи.
    with pytest.raises(HTTPException):
        await recording_protocol(str(s.id), ProtocolIn(company_id=cid, items=[
            ProtocolItemIn(kind='task', text='x', assignee_id=str(чужой.id))]),
            db=db, current_user=хозяин)

    пункты = [ProtocolItemIn(**п) for п in t['protocol']]
    итог = await recording_protocol(str(s.id), ProtocolIn(company_id=cid, items=пункты, send=True),
                                    db=db, current_user=хозяин)
    assert итог == {'saved': 2, 'sent': 1}
    assert any(m.startswith('📝 Протокол: Планёрка') for m in await _сообщения(db, зван))
    await db.refresh(s)
    assert s.protocol and 'Поручения:' in (s.note or '')
    t = await recording_transcript(str(s.id), company_id=cid, db=db, current_user=хозяин)
    assert not t['draft']


async def test_встреча_из_календаря_с_видео_и_приглашением(db, jitsi_key, monkeypatch):
    """РусГидро 15.10: в «Новой встрече» ссылка на видео не создавалась, а
    позванные из календаря не получали ничего."""
    from app.routers.work_router import EventAction, EventIn, calendar_action, calendar_create
    from app.services import email_service

    письма = []

    async def не_слать(to, **поля):
        письма.append((to, поля['method']))
        return True
    monkeypatch.setattr(email_service, 'send_meeting_invite', не_слать)
    company, хозяин, зван, чужой = await люди(db)
    начало = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
    ev = await calendar_create(EventIn(company_id=str(company.id), title='Видео из календаря',
                                       starts_at=начало, ends_at=начало + timedelta(hours=1),
                                       attendee_ids=[str(зван.id)], video=True),
                               db=db, current_user=хозяин)
    assert ev['conference_url'] and '/ledger-' in ev['conference_url'], 'ссылка на комнату не создана'
    assert any(m.startswith('📅') and 'Видео из календаря' in m and '/ledger-' in m
               for m in await _сообщения(db, зван)), 'приглашения в чат нет'
    assert (зван.email, 'REQUEST') in письма

    # Добавили человека — приглашение уходит ему, а не всем повторно.
    до = len(await _сообщения(db, зван))
    await calendar_action(ev['id'], EventAction(company_id=str(company.id),
                                                attendee_ids=[str(зван.id), str(чужой.id)]),
                          db=db, current_user=хозяин)
    assert any(m.startswith('📅') for m in await _сообщения(db, чужой))
    assert len(await _сообщения(db, зван)) == до, 'старому участнику пришло повторное приглашение'

    # Без флажка ссылки нет: чужую не подставляем.
    без = await calendar_create(EventIn(company_id=str(company.id), title='Без видео',
                                        starts_at=начало, ends_at=начало + timedelta(hours=1)),
                                db=db, current_user=хозяин)
    assert not без['conference_url']


async def test_видеоконференция_до_сохранения_та_же_комната(db, jitsi_key):
    """«Создать видеоконференцию» в новой встрече: ссылка до сохранения ведёт в
    ту же комнату, куда потом входят из карточки."""
    from app.routers.work_router import EventIn, calendar_create, calendar_video_link
    from app.services import jitsi

    company, хозяин, _, _ = await люди(db)
    номер = str(uuid.uuid4())
    ссылка = (await calendar_video_link(company_id=str(company.id), event_id=номер,
                                        db=db, current_user=хозяин))['url']
    assert '/ledger-' in ссылка
    начало = (datetime.now(timezone.utc) + timedelta(days=4)).replace(microsecond=0)
    ev = await calendar_create(EventIn(id=номер, company_id=str(company.id), title='Заранее',
                                       starts_at=начало, ends_at=начало + timedelta(hours=1),
                                       conference_url=ссылка), db=db, current_user=хозяин)
    assert ev['id'] == номер and ev['conference_url'] == ссылка
    from app.models import CalendarEvent
    assert ссылка.endswith(jitsi.event_room(await db.get(CalendarEvent, uuid.UUID(номер))))

    # Собранной встрече ссылку здесь не выдаём — и номер повторно не занять.
    with pytest.raises(HTTPException) as отказ:
        await calendar_video_link(company_id=str(company.id), event_id=номер, db=db, current_user=хозяин)
    assert отказ.value.status_code == 409
    with pytest.raises(HTTPException) as отказ:
        await calendar_create(EventIn(id=номер, company_id=str(company.id), title='Повтор',
                                      starts_at=начало, ends_at=начало + timedelta(hours=1)),
                              db=db, current_user=хозяин)
    assert отказ.value.status_code == 409


async def test_ведущие_встречи_и_пять_минут(db, jitsi_key, monkeypatch):
    """Ведущий — отмеченный участник (по умолчанию организатор). Остальные ждут;
    через 5 минут без ведущего комнату открывает первый вошедший — и только он
    (решение МАГа 15.10.2026)."""
    from app.models import CalendarAttendee
    from app.routers.work_router import EventAction, EventIn, calendar_action, calendar_create, calendar_meeting
    from app.services import email_service

    async def не_слать(to, **поля):
        return True
    monkeypatch.setattr(email_service, 'send_meeting_invite', не_слать)
    company, хозяин, зван, чужой = await люди(db)
    cid = str(company.id)
    скоро = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)

    # По умолчанию ведущий — организатор.
    ev = await calendar_create(EventIn(company_id=cid, title='Ведущий по умолчанию', starts_at=скоро,
                                       ends_at=скоро + timedelta(hours=1), attendee_ids=[str(зван.id)],
                                       video=True), db=db, current_user=хозяин)
    отметки = {a['user_id']: a['is_host'] for a in ev['attendees']}
    assert отметки == {str(хозяин.id): True, str(зван.id): False}

    # Секретарь передаёт роль: ведущий — приглашённый, организатор — нет.
    ev = await calendar_action(ev['id'], EventAction(company_id=cid, host_ids=[str(зван.id)]),
                               db=db, current_user=хозяин)
    assert {a['user_id']: a['is_host'] for a in ev['attendees']} == {str(хозяин.id): False, str(зван.id): True}
    вход = await calendar_meeting(ev['id'], company_id=cid, db=db, current_user=зван)
    assert вход['moderator'] is True
    вход = await calendar_meeting(ev['id'], company_id=cid, db=db, current_user=хозяин)
    assert вход['moderator'] is False and вход['host_wait_until'], 'до срока организатор не ведущий'

    # Встреча началась 10 минут назад, ведущего в комнате нет — первый вошедший
    # получает пропуск ведущего, второй застаёт его и входит участником.
    давно = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(microsecond=0)
    ev2 = await calendar_create(EventIn(company_id=cid, title='Ведущий опоздал', starts_at=давно,
                                        ends_at=давно + timedelta(hours=1),
                                        attendee_ids=[str(зван.id), str(чужой.id)], video=True),
                                db=db, current_user=хозяин)
    первый = await calendar_meeting(ev2['id'], company_id=cid, db=db, current_user=зван)
    второй = await calendar_meeting(ev2['id'], company_id=cid, db=db, current_user=чужой)
    assert первый['moderator'] is True and второй['moderator'] is False
    # Сам ведущий входит ведущим всегда.
    assert (await calendar_meeting(ev2['id'], company_id=cid, db=db, current_user=хозяин))['moderator'] is True
