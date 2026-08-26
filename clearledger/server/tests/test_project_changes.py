import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from app.models import EzsSite, EzsSiteEvent
from app.services import ezs_lifecycle
from app.services.ezs_changes import _changes_len, make_change
from app.services.ezs_site_work import log_event, update_site
from app.services.ezs_sites import _apply_update


def test_изменение_хранит_старое_и_новое_значение():
    change = make_change("stage", "lead", "negotiation")

    assert change == {
        "field": "stage",
        "label": "Стадия",
        "category": "stage",
        "old": "lead",
        "new": "negotiation",
        "oldDisplay": "Лид",
        "newDisplay": "Переговоры",
    }


def test_импорт_фиксирует_только_действительно_добавленные_поля():
    site = EzsSite(city="Псков", manual_fields=["owner"], raw={})
    changed, changes = _apply_update(
        site,
        {"city": "Псков", "address": "ул. Советская, 1", "owner": "ООО Владелец"},
        {},
        "Лист 1",
        3,
        "key",
        datetime.now(timezone.utc),
        True,
    )

    assert changed is True
    assert [item["field"] for item in changes] == ["address"]
    assert changes[0]["oldDisplay"] == "не задано"
    assert changes[0]["newDisplay"] == "ул. Советская, 1"


@pytest.mark.asyncio
async def test_ручная_правка_пишет_структурированное_событие(monkeypatch):
    project_id = uuid.uuid4()

    class FakeResult:
        def scalar_one_or_none(self):
            return project_id

    class FakeDb:
        def __init__(self):
            self.added = []

        def add(self, value):
            self.added.append(value)

        async def execute(self, _query):
            return FakeResult()

    async def no_sync(*_args, **_kwargs):
        return None

    monkeypatch.setattr(ezs_lifecycle, "sync_from_site", no_sync)
    db = FakeDb()
    site = EzsSite(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        city="Псков",
        manual_fields=[],
    )

    result = await update_site(db, site, {"city": "Великий Новгород"}, None)

    assert result == {"changed": ["city"]}
    event = next(item for item in db.added if isinstance(item, EzsSiteEvent))
    assert event.source == "user"
    assert event.project_id == project_id
    assert event.changes[0]["field"] == "city"
    assert event.changes[0]["old"] == "Псков"
    assert event.changes[0]["new"] == "Великий Новгород"


def test_длина_изменений_не_падает_на_нестандартном_значении():
    """Заметка и касание пишутся без «было → стало», и в колонке лежит JSON null.

    `jsonb_array_length` на скаляре роняет ВЕСЬ запрос, а не строку: одна такая
    запись гасила экран «Изменения» целиком (HTTP 500).
    """
    sql = str(_changes_len().compile(dialect=postgresql.dialect()))

    assert "jsonb_typeof" in sql
    assert "jsonb_array_length" in sql


@pytest.mark.asyncio
async def test_заметка_пишется_пустым_списком_а_не_json_null(monkeypatch):
    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeDb:
        def __init__(self):
            self.added = []

        def add(self, value):
            self.added.append(value)

        async def execute(self, _query):
            return FakeResult()

    db = FakeDb()
    site = EzsSite(id=uuid.uuid4(), company_id=uuid.uuid4())

    await log_event(db, site, "note", text="созвонились с собственником")

    assert db.added[0].changes == []
