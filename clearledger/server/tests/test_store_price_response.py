"""Отклик спроса на цену: наблюдение, а не закон — и оно должно быть честным."""
import uuid
from datetime import datetime, timedelta, timezone

from app.services import store_dynamics


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Session:
    """Сессия-заглушка: журнал цен отдаёт, документы и себестоимость — через подмену."""

    def __init__(self, changes):
        self.changes = changes

    async def execute(self, statement, params=None):
        return _Rows(self.changes)


def _изменение(*, было, стало, когда=None, дней_назад=10, uuid_="u-1", station=208):
    # Момент передаётся явно: два разных now() разъезжаются на микросекунды, и
    # крайний день окна наблюдения то попадает в выборку, то нет.
    return {"station_id": station, "price": стало, "price_prev": было,
            "valid_from": когда or datetime.now(timezone.utc) - timedelta(days=дней_назад),
            "author": "товаровед", "name": "Кофе", "item_uuid": uuid_}


def _док(станция, день, uuid_, qty, amount):
    return {"station_id": станция, "doc_date": день,
            "lines": [{"Номенклатура": uuid_, "Количество": qty, "Сумма": amount}]}


async def test_подъём_цены_срезал_спрос_но_поднял_маржу(monkeypatch):
    когда = datetime.now(timezone.utc) - timedelta(days=10)
    доки = []
    # До подъёма: всё окно (14 дней) по 10 штук за 1000 ₽; после — по 8 за 960 ₽.
    # Окно «после» короче: изменение случилось десять дней назад, дальше «сейчас».
    for d in range(1, 15):
        доки.append(_док(208, когда - timedelta(days=d), "u-1", 10, 1000))
    for d in range(0, 10):
        доки.append(_док(208, когда + timedelta(days=d), "u-1", 8, 960))

    async def документы(db, cid, d1, d2, виды, stations, строки_поле="Товары"):
        return [d for d in доки if d1 <= d["doc_date"] <= d2]

    async def себестоимости(db, cid, stations, на_дату):
        return {"u-1": 60.0}

    monkeypatch.setattr(store_dynamics, "_документы", документы)
    monkeypatch.setattr(store_dynamics, "_себестоимости", себестоимости)

    итог = await store_dynamics.отклики(
        _Session([_изменение(было=100, стало=120, когда=когда)]), uuid.uuid4())

    assert итог["total"] == 1
    r = итог["rows"][0]
    assert r["price_prev"] == 100.0 and r["price"] == 120.0
    assert r["price_pct"] == 20.0
    assert r["qty_day_prev"] == 10.0 and r["qty_day"] == 8.0
    assert r["qty_pct"] == -20.0
    # Эластичность −1: каждый процент цены съел процент спроса.
    assert r["elasticity"] == -1.0
    # Маржа: было (1000 − 10×60) = 400 в день, стало (960 − 8×60) = 480.
    assert r["margin_day_prev"] == 400.0 and r["margin_day"] == 480.0
    assert r["verdict"] == "маржа выросла — решение сработало"


async def test_копеечный_сдвиг_не_даёт_эластичности(monkeypatch):
    async def документы(*args, **kwargs):
        return []

    async def себестоимости(*args, **kwargs):
        return {}

    monkeypatch.setattr(store_dynamics, "_документы", документы)
    monkeypatch.setattr(store_dynamics, "_себестоимости", себестоимости)

    итог = await store_dynamics.отклики(
        _Session([_изменение(было=100, стало=100.2, дней_назад=10)]), uuid.uuid4())

    r = итог["rows"][0]
    # На сдвиге в две десятых процента знаменатель обнуляет смысл — числа нет.
    assert r["elasticity"] is None
    # Продаж нет вовсе — судить не о чем, и экран обязан это сказать.
    assert r["verdict"] == "наблюдений мало — рано судить"


async def test_без_изменений_цен_возвращается_пусто():
    итог = await store_dynamics.отклики(_Session([]), uuid.uuid4())
    assert итог == {"window": 14, "rows": [], "total": 0}
