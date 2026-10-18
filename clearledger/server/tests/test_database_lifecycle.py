"""Отложенная доставка API обязана освободить БД до удаления схем."""
import asyncio
import uuid

import pytest
from sqlalchemy import text

from app import database
from app.services import notify
from tests.helpers import drain_application_tasks


@pytest.mark.asyncio(loop_scope="session")
async def test_drain_finishes_notification_transaction(setup_database, monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def dispatch(session, *_args):
        # Реальная транзакция удерживает блокировку, конфликтующую с DROP.
        await session.execute(text("SELECT id FROM companies LIMIT 1"))
        entered.set()
        await release.wait()
        finished.set()

    monkeypatch.setattr(notify, "dispatch", dispatch)
    notify.dispatch_async(uuid.uuid4(), "doc.create")
    await asyncio.wait_for(entered.wait(), timeout=10)
    assert database.engine.pool.checkedout() == 1

    # Отдаём доставке управление только на следующем обороте event loop:
    # пустой drain вернулся бы до finished и оставил соединение занятым.
    asyncio.get_running_loop().call_soon(release.set)
    await drain_application_tasks()

    assert finished.is_set()
    assert database.engine.pool.checkedout() == 0
