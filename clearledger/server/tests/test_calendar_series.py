"""Сохранение серии видно сразу; регламент и запрос делят одну транзакционную блокировку."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import CalendarAttendee, CalendarEvent, Company, User, UserCompany
from app.routers.work_router import (
    EventAction, EventIn, calendar_action, calendar_card, calendar_create,
)
from app.services import calendar_series, meeting_notice, task_scheduler

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def series(db, monkeypatch):
    company = Company(name="Тест календаря", slug=f"calendar-{uuid.uuid4().hex[:16]}",
                      profile_id="energy")
    owner = await db.scalar(select(User).where(User.email == "admin@clearledger.ru"))
    guest = User(email=f"calendar-{uuid.uuid4()}@example.test", name="Участник",
                 password_hash="!test")
    observer = User(email=f"calendar-{uuid.uuid4()}@example.test", name="Наблюдатель",
                    password_hash="!test")
    outsider = User(email=f"calendar-{uuid.uuid4()}@example.test", name="Другая компания",
                    password_hash="!test")
    db.add_all([company, guest, observer, outsider])
    await db.flush()
    for person in [owner, guest, observer]:
        db.add(UserCompany(company_id=company.id, user_id=person.id, role="user"))
    await db.commit()
    notice = AsyncMock(return_value={})
    monkeypatch.setattr(meeting_notice, "известить", notice)
    return SimpleNamespace(
        company=company, owner=owner, guest=guest, observer=observer, outsider=outsider,
        start=(datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0),
        sessions=async_sessionmaker(db.bind, expire_on_commit=False), notice=notice)


def event_input(series, **fields):
    values = dict(company_id=str(series.company.id), title="Тестовая планёрка",
                  starts_at=series.start, ends_at=series.start + timedelta(hours=1),
                  visibility="private", attendee_ids=[str(series.guest.id)])
    values.update(fields)
    return EventIn(**values)


async def create(db, series, **fields):
    return await calendar_create(event_input(series, **fields), db=db, current_user=series.owner)


async def action(db, series, event_id, **fields):
    return await calendar_action(str(event_id), EventAction(
        company_id=str(series.company.id), **fields), db=db, current_user=series.owner)


async def copies(db, event_id):
    return (await db.scalars(select(CalendarEvent).where(
        CalendarEvent.series_id == uuid.UUID(str(event_id)))
        .order_by(CalendarEvent.starts_at))).all()


@pytest.mark.parametrize("mode,interval,count", [("daily", 1, 59), ("weekly", 1, 8),
                                                 ("weekly", 2, 4), ("monthly", 1, 1)])
async def test_api_сразу_возвращает_весь_горизонт_без_tick(auth_client, db, series,
                                                         monkeypatch, mode, interval, count):
    monkeypatch.setattr(task_scheduler, "tick", AsyncMock(side_effect=AssertionError("Глобальный tick")))
    monkeypatch.setattr(task_scheduler, "run_meeting_series", AsyncMock(
        side_effect=AssertionError("Массовый проход из запроса")))
    # Ровно 60 суток: конец окна не зависит от времени выполнения теста.
    series.start = datetime.now(timezone.utc) + timedelta(days=1)
    payload = event_input(series, recurrence={"mode": mode, "interval": interval})
    response = await auth_client.post("/api/work/calendar", json=payload.model_dump(mode="json"))
    assert response.status_code == 201, response.text
    event_id = response.json()["id"]
    result = await auth_client.get("/api/work/calendar", params={
        "company_id": str(series.company.id), "from": series.start.isoformat(),
        "to": (series.start + timedelta(days=61)).isoformat(), "scope": "mine"})
    assert result.status_code == 200, result.text
    events = result.json()["events"]
    # Число месячных повторов зависит от длины месяцев, проверяем точные даты ниже.
    expected = []
    cursor = series.start
    horizon = datetime.now(timezone.utc) + timedelta(days=60)
    from zoneinfo import ZoneInfo
    while (cursor := calendar_series.next_occurrence(cursor, payload.recurrence,
                                                      ZoneInfo(payload.tz))) <= horizon:
        expected.append(cursor)
    actual = [datetime.fromisoformat(e["starts_at"]) for e in events if e["series_id"] == event_id]
    assert actual == expected
    assert len(actual) >= count
    if mode == "daily":
        assert len(actual) == 59 > task_scheduler.SERIES_MAX_PER_TICK
    assert all(e["recurrence"] is None for e in events if e["series_id"] == event_id)
    # Строки уже зафиксированы, новый сеанс видит их до фонового прохода.
    async with series.sessions() as fresh:
        assert len(await copies(fresh, event_id)) == len(expected)


async def test_граница_включительна_в_поясе_встречи_и_снимается_сразу(db, series):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Asia/Vladivostok")
    series.start = series.start.astimezone(zone).replace(hour=23, minute=59, second=30, microsecond=999)
    until = (series.start + timedelta(days=2)).date()
    event = await create(db, series, tz=zone.key, recurrence={"mode": "daily"},
                         recurrence_until=until)
    assert len(await copies(db, event["id"])) == 2
    await action(db, series, event["id"], recurrence_until=None)
    assert len(await copies(db, event["id"])) > 40


async def test_включение_и_повторное_сохранение_не_трогает_другую_голову(db, series):
    first = await create(db, series)
    other = CalendarEvent(company_id=series.company.id, organizer_id=series.owner.id,
        title="Не сохраняемая серия", starts_at=series.start, ends_at=series.start + timedelta(hours=1),
        recurrence={"mode": "daily"})
    db.add(other)
    await db.commit()
    for _ in range(2):
        await action(db, series, first["id"], recurrence={"mode": "weekly"})
    before = [(e.id, e.starts_at) for e in await copies(db, first["id"])]
    assert len(before) == 8
    await action(db, series, first["id"], title="Новая тема")
    assert [(e.id, e.starts_at) for e in await copies(db, first["id"])] == before
    assert await copies(db, other.id) == []
    # Не оставляем незаполненную постороннюю серию следующим тестам регламента.
    other.recurrence = None
    await db.commit()


async def test_смена_правила_и_выключение_не_перестраивают_назначенное(db, series):
    event = await create(db, series, recurrence={"mode": "weekly"},
                         recurrence_until=(series.start + timedelta(days=14)).date())
    existing = await copies(db, event["id"])
    # Один экземпляр переносили отдельно, другой отменяли.
    moved = existing[-1]
    moved.starts_at -= timedelta(hours=2)
    moved.ends_at -= timedelta(hours=2)
    existing[0].status = "cancelled"
    await db.commit()
    before = [(e.id, e.starts_at, e.ends_at, e.status) for e in existing]
    await action(db, series, event["id"], recurrence={})
    await action(db, series, event["id"], starts_at=series.start - timedelta(days=100),
                 ends_at=series.start - timedelta(days=100) + timedelta(hours=2))
    await action(db, series, event["id"], recurrence={"mode": "daily"}, recurrence_until=None)
    after = await copies(db, event["id"])
    assert [(e.id, e.starts_at, e.ends_at, e.status) for e in after[:len(before)]] == before
    assert all(e.starts_at > moved.starts_at for e in after[len(before):])
    assert len({e.starts_at for e in after}) == len(after)
    ids = {e.id for e in after}
    await action(db, series, event["id"], recurrence={"mode": "daily"})
    assert {e.id for e in await copies(db, event["id"])} == ids


async def test_участники_ведущие_ответы_и_поля_копируются_после_правок(db, series):
    subject = f"task:{uuid.uuid4()}"
    event = await create(db, series, subject_ref=subject)
    await calendar_action(event["id"], EventAction(company_id=str(series.company.id),
        response="tentative", comment="Только для головы"), db=db, current_user=series.guest)
    await action(db, series, event["id"], recurrence={"mode": "weekly"},
                 optional_ids=[str(series.guest.id)], host_ids=[str(series.guest.id)],
                 all_day=True, description="Описание", location="Переговорная",
                 conference_url="https://video.example.test/series")
    for row in await copies(db, event["id"]):
        assert (row.company_id, row.organizer_id, row.visibility) == (
            series.company.id, series.owner.id, "private")
        assert (row.all_day, row.description, row.location, row.conference_url) == (
            True, "Описание", "Переговорная", "https://video.example.test/series")
        assert row.subject_ref == subject
        attendees = (await db.scalars(select(CalendarAttendee).where(
            CalendarAttendee.event_id == row.id))).all()
        assert {(a.user_id, a.role, a.response, a.is_host) for a in attendees} == {
            (series.owner.id, "required", "accepted", False),
            (series.guest.id, "optional", "tentative", True)}
        assert all(a.comment is None and a.proposed_starts_at is None for a in attendees)


@pytest.mark.parametrize("visibility", ["private", "personal", "company"])
async def test_права_круг_и_компания_повторений_сохраняются(db, series, visibility):
    event = await create(db, series, visibility=visibility, recurrence={"mode": "weekly"},
                         attendee_ids=[str(series.guest.id), str(series.outsider.id)])
    row = (await copies(db, event["id"]))[0]
    participants = set((await db.scalars(select(CalendarAttendee.user_id).where(
        CalendarAttendee.event_id == row.id))).all())
    assert participants == ({series.owner.id} if visibility == "personal"
                             else {series.owner.id, series.guest.id})
    if visibility == "company":
        await calendar_card(str(row.id), company_id=str(series.company.id), db=db,
                            current_user=series.observer)
    else:
        with pytest.raises(HTTPException) as error:
            await calendar_card(str(row.id), company_id=str(series.company.id), db=db,
                                current_user=series.observer)
        assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        await calendar_action(str(row.id), EventAction(company_id=str(series.company.id),
            recurrence={"mode": "daily"}), db=db, current_user=series.owner)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        await calendar_action(event["id"], EventAction(company_id=str(series.company.id),
            recurrence={"mode": "daily"}), db=db, current_user=series.guest)
    assert error.value.status_code == 403
    other_company = await db.scalar(select(Company).where(Company.id != series.company.id).limit(1))
    assert await calendar_series.materialize_series(
        db, other_company.id, uuid.UUID(event["id"]), datetime.now(timezone.utc)) == 0
    assert await copies(db, row.id) == []


@pytest.mark.parametrize("update", [False, True])
async def test_ошибка_построения_откатывает_голову_правило_и_участников(db, series, monkeypatch, update):
    initial = await create(db, series) if update else None
    event_id = uuid.UUID(initial["id"]) if initial else uuid.uuid4()
    original = calendar_series.next_occurrence
    calls = 0

    def fail_after_first(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Ошибка после записи первого экземпляра и его участников")
        return original(*args)

    monkeypatch.setattr(calendar_series, "next_occurrence", fail_after_first)
    series.notice.reset_mock()
    async with series.sessions() as transaction:
        owner = await transaction.get(User, series.owner.id)
        with pytest.raises(RuntimeError, match="после записи"):
            if update:
                await calendar_action(str(event_id), EventAction(company_id=str(series.company.id),
                    recurrence={"mode": "daily"}, optional_ids=[str(series.guest.id)]),
                    db=transaction, current_user=owner)
            else:
                await calendar_create(event_input(series, id=str(event_id),
                    recurrence={"mode": "daily"}), db=transaction, current_user=owner)
        await transaction.rollback()
    async with series.sessions() as fresh:
        assert await copies(fresh, event_id) == []
        head = await fresh.get(CalendarEvent, event_id)
        if update:
            assert head.recurrence is None
            guest = await fresh.scalar(select(CalendarAttendee).where(
                CalendarAttendee.event_id == event_id, CalendarAttendee.user_id == series.guest.id))
            assert guest.role == "required"
        else:
            assert head is None
        count = await fresh.scalar(select(func.count()).select_from(CalendarAttendee).where(
            CalendarAttendee.event_id.not_in(select(CalendarEvent.id))))
        assert count == 0
    series.notice.assert_not_called()


async def test_запрос_и_scheduler_не_дублируют_серию_под_блокировкой(db, series, monkeypatch):
    event = await create(db, series, recurrence={"mode": "weekly"},
                         recurrence_until=series.start.date())
    generated = asyncio.Event()
    release = asyncio.Event()
    original = calendar_series.materialize_series

    async def paused_materialize(*args, **kwargs):
        count = await original(*args, **kwargs)
        if not kwargs.get("skip_locked"):
            generated.set()
            await release.wait()
        return count

    monkeypatch.setattr(calendar_series, "materialize_series", paused_materialize)

    async def save():
        async with series.sessions() as transaction:
            owner = await transaction.get(User, series.owner.id)
            return await calendar_action(event["id"], EventAction(
                company_id=str(series.company.id), recurrence_until=None),
                db=transaction, current_user=owner)

    request = asyncio.create_task(save())
    try:
        await asyncio.wait_for(generated.wait(), timeout=5)
        async with series.sessions() as background:
            assert await copies(background, event["id"]) == []  # ещё не commit
            assert await asyncio.wait_for(task_scheduler.run_meeting_series(
                background, datetime.now(timezone.utc)), timeout=5) == 0
            await background.commit()
    finally:
        release.set()
        await asyncio.wait_for(request, timeout=5)
    async with series.sessions() as fresh:
        assert len(await copies(fresh, event["id"])) == 8
        assert await task_scheduler.run_meeting_series(fresh, datetime.now(timezone.utc)) == 0


async def test_запрос_ждёт_scheduler_и_перечитывает_голову_после_ожидания(db, series, monkeypatch):
    # Проверяем ожидание блокировки, а не переход местных суток. После 17 UTC
    # исходное «сейчас + день» сдвигалось на 4 часа уже в следующие сутки МСК,
    # и recurrence_until закономерно отсекал второй повтор. Полдень МСК
    # сохраняет один календарный день до и после сдвига независимо от запуска.
    series.start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0)
    event = await create(db, series, recurrence={"mode": "weekly"},
                         recurrence_until=series.start.date())
    entered = asyncio.Event()
    original_lock = calendar_series.lock_event

    async def observed_lock(*args, **kwargs):
        entered.set()
        return await original_lock(*args, **kwargs)

    async with series.sessions() as request_db, series.sessions() as background:
        # И голова, и участник уже находятся в identity map запроса.
        stale = await request_db.get(CalendarEvent, uuid.UUID(event["id"]))
        await request_db.scalars(select(CalendarAttendee).where(CalendarAttendee.event_id == stale.id))
        head = await original_lock(background, series.company.id, stale.id)
        head.starts_at += timedelta(hours=4)
        head.ends_at += timedelta(hours=4)
        head.recurrence_until = (series.start + timedelta(days=14)).date()
        assert await task_scheduler.run_meeting_series(background, datetime.now(timezone.utc)) == 2
        monkeypatch.setattr(calendar_series, "lock_event", observed_lock)
        # Со старым ends_at эта правка была бы ошибочной; после ожидания должна
        # использовать конец и правило, сохранённые конкурентной транзакцией.
        request = asyncio.create_task(action(request_db, series, event["id"],
            title="После ожидания", starts_at=series.start + timedelta(hours=2)))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            assert not request.done()
            await background.commit()
            result = await asyncio.wait_for(request, timeout=5)
        finally:
            if not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
        assert result["recurrence_until"] == head.recurrence_until.isoformat()
        assert result["ends_at"] == series.start + timedelta(hours=5)
        assert len(await copies(request_db, event["id"])) == 2


async def test_два_сохранения_одной_головы_создают_один_набор(db, series):
    event = await create(db, series)

    async def save():
        async with series.sessions() as transaction:
            owner = await transaction.get(User, series.owner.id)
            return await calendar_action(event["id"], EventAction(company_id=str(series.company.id),
                recurrence={"mode": "daily"}), db=transaction, current_user=owner)

    await asyncio.wait_for(asyncio.gather(save(), save()), timeout=10)
    rows = await copies(db, event["id"])
    assert len(rows) == 59
    assert len({e.starts_at for e in rows}) == 59


async def test_api_включение_и_снятие_границы_видно_до_следующего_tick(auth_client, db, series):
    response = await auth_client.post("/api/work/calendar", json=event_input(series).model_dump(mode="json"))
    assert response.status_code == 201, response.text
    event_id = response.json()["id"]
    for changes, expected in [
        ({"recurrence": {"mode": "weekly"},
          "recurrence_until": (series.start + timedelta(days=14)).date().isoformat()}, 2),
        ({"recurrence_until": None}, 8),
        ({"recurrence": {"mode": "weekly"}}, 8),
    ]:
        response = await auth_client.post(f"/api/work/calendar/{event_id}", json={
            "company_id": str(series.company.id), **changes})
        assert response.status_code == 200, response.text
        result = await auth_client.get("/api/work/calendar", params={
            "company_id": str(series.company.id), "from": series.start.isoformat(),
            "to": (series.start + timedelta(days=61)).isoformat()})
        assert result.status_code == 200, result.text
        assert len([e for e in result.json()["events"] if e["series_id"] == event_id]) == expected


@pytest.mark.parametrize("mode,interval", [("daily", 1), ("weekly", 3), ("monthly", 1)])
@pytest.mark.parametrize("enable", [False, True])
async def test_голова_2000_года_строит_только_будущее_сохраняя_ритм(db, series, mode, interval, enable):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Europe/Berlin")
    series.start = datetime(2000, 1, 31, 10, 15, tzinfo=zone)
    before = datetime.now(timezone.utc)
    rule = {"mode": mode, "interval": interval}
    event = await create(db, series, tz=zone.key, recurrence=None if enable else rule)
    if enable:
        await action(db, series, event["id"], recurrence=rule)
    after = datetime.now(timezone.utc)
    rows = await copies(db, event["id"])
    assert 0 < len(rows) <= 60
    assert all(before <= e.starts_at <= after + timedelta(days=60) for e in rows)
    local = [e.starts_at.astimezone(zone) for e in rows]
    assert all((t.hour, t.minute) == (10, 15) for t in local)
    if mode == "weekly":
        assert all((t.date() - series.start.date()).days % (7 * interval) == 0 for t in local)
    if mode == "monthly":
        assert all(t.day == 28 for t in local)  # февраль давно прижал 31-е число
    before_ids = {e.id for e in rows}
    await action(db, series, event["id"], recurrence=rule)
    assert {e.id for e in await copies(db, event["id"])} == before_ids


async def test_только_scheduler_ограничивает_проход_сорока_строками(db, series):
    head = CalendarEvent(company_id=series.company.id, organizer_id=series.owner.id,
        title="Серия для регламента", starts_at=series.start, ends_at=series.start + timedelta(hours=1),
        recurrence={"mode": "daily"})
    db.add(head)
    await db.flush()
    db.add(CalendarAttendee(event_id=head.id, user_id=series.owner.id, response="accepted", is_host=True))
    await db.commit()
    now = datetime.now(timezone.utc)
    assert await task_scheduler.run_meeting_series(db, now) == 40
    assert len(await copies(db, head.id)) == 40
    # Общий сервис не фиксирует свою транзакцию даже в регламенте.
    async with series.sessions() as fresh:
        assert await copies(fresh, head.id) == []
    assert await task_scheduler.run_meeting_series(db, now) == 19
    assert len(await copies(db, head.id)) == 59
    assert await task_scheduler.run_meeting_series(db, now) == 0
    await db.commit()


async def test_api_ошибка_построения_откатывается_dependency(auth_client, db, series, monkeypatch):
    original = calendar_series.next_occurrence
    calls = 0
    event_id = uuid.uuid4()

    def fail_after_first(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Ошибка API после первой вставки")
        return original(*args)

    monkeypatch.setattr(calendar_series, "next_occurrence", fail_after_first)
    with pytest.raises(RuntimeError, match="Ошибка API"):
        await auth_client.post("/api/work/calendar", json=event_input(
            series, id=str(event_id), recurrence={"mode": "daily"}).model_dump(mode="json"))
    async with series.sessions() as fresh:
        assert await fresh.get(CalendarEvent, event_id) is None
        assert await copies(fresh, event_id) == []
    series.notice.assert_not_called()


async def test_перенос_экземпляра_синхронизирован_с_продлением_серии(db, series, monkeypatch):
    event = await create(db, series, recurrence={"mode": "weekly"},
                         recurrence_until=(series.start + timedelta(days=14)).date())
    last = (await copies(db, event["id"]))[-1]
    head = await db.get(CalendarEvent, uuid.UUID(event["id"]))
    head.recurrence_until = None
    await db.commit()
    paused = asyncio.Event()
    release = asyncio.Event()
    original = calendar_series.materialize_series

    async def paused_save(*args, **kwargs):
        made = await original(*args, **kwargs)
        if not kwargs.get("skip_locked"):
            paused.set()
            await release.wait()
        return made

    monkeypatch.setattr(calendar_series, "materialize_series", paused_save)

    async def move():
        async with series.sessions() as transaction:
            return await action(transaction, series, last.id,
                starts_at=last.starts_at + timedelta(days=7), ends_at=last.ends_at + timedelta(days=7))

    request = asyncio.create_task(move())
    try:
        await asyncio.wait_for(paused.wait(), timeout=5)
        async with series.sessions() as background:
            assert await asyncio.wait_for(task_scheduler.run_meeting_series(
                background, datetime.now(timezone.utc)), timeout=5) == 0
    finally:
        release.set()
        await asyncio.wait_for(request, timeout=5)
    async with series.sessions() as fresh:
        assert await task_scheduler.run_meeting_series(fresh, datetime.now(timezone.utc)) == 5
        rows = await copies(fresh, event["id"])
        assert len(rows) == len({e.starts_at for e in rows}) == 7
        await fresh.commit()


async def test_поздний_ответ_и_смена_состава_не_правят_уже_назначенные_экземпляры(db, series):
    event = await create(db, series, recurrence={"mode": "weekly"},
                         recurrence_until=(series.start + timedelta(days=14)).date())
    initial_ids = {e.id for e in await copies(db, event["id"])}
    await calendar_action(event["id"], EventAction(company_id=str(series.company.id),
        response="accepted"), db=db, current_user=series.guest)
    await action(db, series, event["id"], attendee_ids=[], recurrence_until=None)
    for row in await copies(db, event["id"]):
        attendees = (await db.scalars(select(CalendarAttendee).where(
            CalendarAttendee.event_id == row.id))).all()
        by_user = {a.user_id: a for a in attendees}
        if row.id in initial_ids:
            assert by_user[series.guest.id].response == "pending"
        else:
            assert set(by_user) == {series.owner.id}
