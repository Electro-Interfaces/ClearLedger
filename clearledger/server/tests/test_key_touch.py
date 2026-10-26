"""Отметка «ключом пользовались»: не чаще раза в минуту и ВНЕ транзакции запроса.

Две вещи, каждая из которых уже стоила работающего обмена на gig:

Частота. Раньше запись шла на каждый входящий запрос в одну и ту же строку —
204 971 обновление на восемь ключей. При любой зависшей транзакции все обращения по
этому ключу встают в очередь на блокировке строки.

Транзакция. Одной частоты не хватило: отметка стояла атрибутом ORM, то есть UPDATE
уходил в транзакции запроса и держал строку до её конца. Вечером 25.10.2026 рядом
жило 29-секундное чтение пакетов станции, и записей стало 2.4 в минуту при СРЕДНЕМ
ожидании 167 секунд: станции получали 499, в базе стояло 14 запросов в очереди.
Теперь запись идёт своей короткой транзакцией.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import app.database as db_module
from app.auth import KEY_TOUCH_INTERVAL, _last_touch, touch_key_used


class _Key:
    def __init__(self, last_used_at=None):
        self.id = "key-1"
        self.last_used_at = last_used_at


class _FakeSession:
    """Сессия, которая только запоминает, что в неё написали."""

    def __init__(self, journal):
        self.journal = journal

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.journal.append(stmt)

    async def commit(self):
        self.journal.append("commit")


@pytest.fixture(autouse=True)
def _chistaya_pamyat():
    """Счёт «когда писали» живёт в памяти процесса — между тестами его обнуляем."""
    _last_touch.clear()
    yield
    _last_touch.clear()


@pytest.fixture
def zapisi(monkeypatch):
    journal: list = []
    monkeypatch.setattr(db_module, "async_session_factory", lambda: _FakeSession(journal))
    return journal


async def _dozhdatsya_zapisi():
    """Дать фоновой задаче отработать: она создаётся, но не ожидается вызывающим."""
    from app.auth import _touch_tasks

    for _ in range(50):
        if _touch_tasks:
            await asyncio.gather(*list(_touch_tasks), return_exceptions=True)
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_pervoe_obrashchenie_pishetsya_otdelnoy_tranzakciey(zapisi):
    k = _Key()
    touch_key_used(k)
    await _dozhdatsya_zapisi()
    assert "commit" in zapisi, "запись обязана уйти своей транзакцией, а не транзакцией запроса"


@pytest.mark.asyncio
async def test_orm_obekt_ne_menyaetsya(zapisi):
    """Главное условие правки: объект сессии ЗАПРОСА не трогаем.

    Присваивание `key.last_used_at` пометило бы объект грязным, и SQLAlchemy отправил
    бы UPDATE при автофлаше — в транзакции запроса. Именно это свело на нет первую
    версию правки: на gig головной запрос держал RowExclusiveLock на space_inbound_keys,
    в очереди стояли шесть запросов, станции отдавали 499.
    """
    k = _Key()
    touch_key_used(k)
    await _dozhdatsya_zapisi()
    assert k.last_used_at is None, "ORM-объект обязан остаться чистым"


@pytest.mark.asyncio
async def test_vtoroy_vyzov_podryad_ne_pishet(zapisi):
    """Счёт ведётся в памяти процесса: второй вызов в том же запросе не пишет."""
    k = _Key()
    touch_key_used(k)
    await _dozhdatsya_zapisi()
    bylo = len(zapisi)
    touch_key_used(k)
    await _dozhdatsya_zapisi()
    assert len(zapisi) == bylo, "повтор по тому же ключу не должен идти в базу"


@pytest.mark.asyncio
async def test_povtor_v_predelah_minuty_ne_pishet(zapisi):
    byla = datetime.now(timezone.utc) - timedelta(seconds=5)
    k = _Key(byla)
    touch_key_used(k)
    await _dozhdatsya_zapisi()
    assert zapisi == [], "запись в пределах интервала означала бы прежнюю очередь"


@pytest.mark.asyncio
async def test_posle_intervala_pishet(zapisi):
    byla = datetime.now(timezone.utc) - KEY_TOUCH_INTERVAL - timedelta(seconds=1)
    k = _Key(byla)
    touch_key_used(k)
    await _dozhdatsya_zapisi()
    assert "commit" in zapisi


@pytest.mark.asyncio
async def test_oshibka_zapisi_ne_lomaet_zapros(monkeypatch):
    """Отметка — для экрана подключений: её потеря не должна отказывать в обслуживании."""
    def _broken():
        raise RuntimeError("база недоступна")

    monkeypatch.setattr(db_module, "async_session_factory", _broken)
    k = _Key()
    touch_key_used(k)  # не должно бросить
    await _dozhdatsya_zapisi()
