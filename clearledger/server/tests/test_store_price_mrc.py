"""Цены по марке: что считается расхождением и что можно принять вслепую."""
import uuid
from datetime import datetime, timezone

import pytest

from app.services import store_mrc_prices


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Session:
    """Сессия-заглушка: чеки, карточки и цены отдаются по тексту запроса."""

    def __init__(self, факты, карточки, цены):
        self.факты, self.карточки, self.цены = факты, карточки, цены
        self.committed = False

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "store_cheques" in sql:
            return _Rows(self.факты)
        if "edge.price" in sql:
            return _Rows(self.цены)
        return _Rows(self.карточки)

    async def commit(self):
        self.committed = True


def _сессия():
    факты = [
        # Марка подорожала: касса пробила по 220, у нас 210, МРЦ карточки 220.
        {"station_id": 208, "item_uuid": "u-1", "name": "Winston", "cash_price": 220,
         "qty": 30, "amount": 6600, "last_at": datetime(2026, 8, 20, tzinfo=timezone.utc)},
        # Пробили дороже, но МРЦ этого не объясняет — принимать нельзя.
        {"station_id": 208, "item_uuid": "u-2", "name": "Camel", "cash_price": 250,
         "qty": 4, "amount": 1000, "last_at": datetime(2026, 8, 20, tzinfo=timezone.utc)},
        # Наша цена не отстала — строки быть не должно.
        {"station_id": 5, "item_uuid": "u-3", "name": "Parliament", "cash_price": 300,
         "qty": 2, "amount": 600, "last_at": datetime(2026, 8, 20, tzinfo=timezone.utc)},
    ]
    карточки = [
        {"uuid": "u-1", "name": "Winston", "mrc": 220, "marked": True,
         "price_owner": "station", "barcode": "460001"},
        {"uuid": "u-2", "name": "Camel", "mrc": 230, "marked": True,
         "price_owner": "station", "barcode": "460002"},
        {"uuid": "u-3", "name": "Parliament", "mrc": 300, "marked": True,
         "price_owner": "station", "barcode": "460003"},
    ]
    цены = [
        {"station_id": 208, "price": 210, "uuid": "u-1"},
        {"station_id": 208, "price": 240, "uuid": "u-2"},
        {"station_id": 5, "price": 300, "uuid": "u-3"},
    ]
    return _Session(факты, карточки, цены)


async def test_маркой_объясняется_только_совпадение_с_мрц():
    итог = await store_mrc_prices.rows(_сессия(), uuid.uuid4(), "2026-08-01", "2026-08-31")

    имена = {r["name"]: r for r in итог["rows"]}
    assert set(имена) == {"Winston", "Camel"}      # цена, которая не отстала, не строка
    assert имена["Winston"]["by_mark"] is True
    assert имена["Winston"]["loss"] == (220 - 210) * 30
    assert имена["Camel"]["by_mark"] is False      # пробили выше своей же МРЦ
    assert итог["by_mark"] == 1 and итог["other"] == 1
    assert итог["loss_mark"] == 300 and итог["loss_other"] == 40
    assert итог["by_station"][0]["station_id"] == 208


async def test_принимаем_только_объяснённое_маркой(monkeypatch):
    записано: list[tuple] = []

    async def подмена(db, cid, station_id, item_uuid, цена, автор, note):
        записано.append((station_id, item_uuid, цена, автор))
        return True

    monkeypatch.setattr(store_mrc_prices, "записать_цену", подмена)
    сессия = _сессия()
    итог = await store_mrc_prices.accept(сессия, uuid.uuid4(), "товаровед",
                                         "2026-08-01", "2026-08-31")

    assert записано == [(208, "u-1", 220.0, "товаровед")]   # Camel не поехал
    assert итог["accepted"] == 1 and итог["stations"] == 1
    assert итог["recovered"] == 300
    assert сессия.committed is True


@pytest.mark.parametrize("выбор", [["208:u-2"], ["5:u-3"]])
async def test_чужой_выбор_ничего_не_меняет(monkeypatch, выбор):
    async def подмена(*args, **kwargs):
        raise AssertionError("не должно вызываться")

    monkeypatch.setattr(store_mrc_prices, "записать_цену", подмена)
    итог = await store_mrc_prices.accept(_сессия(), uuid.uuid4(), "товаровед",
                                         "2026-08-01", "2026-08-31", только=выбор)
    assert итог["accepted"] == 0
