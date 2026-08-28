"""Корзина цен: когда применять и что происходит при применении."""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models import StorePricePlan
from app.services import store_price_plans


def test_сейчас_не_назначает_времени():
    assert store_price_plans._когда("now", None, None) is None


def test_через_минуты_считается_от_текущего_момента():
    когда = store_price_plans._когда("delay", 30, None)
    разница = когда - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < разница <= timedelta(minutes=30)


@pytest.mark.parametrize("минут", [0, -5, 24 * 60 + 1])
def test_интервал_вне_суток_отвергается(минут):
    with pytest.raises(ValueError):
        store_price_plans._когда("delay", минут, None)


def test_время_без_пояса_читается_как_московское():
    завтра = (datetime.now(ZoneInfo("Europe/Moscow")) + timedelta(days=1)
              ).replace(hour=6, minute=0, second=0, microsecond=0)
    когда = store_price_plans._когда("scheduled", None,
                                     завтра.strftime("%Y-%m-%dT%H:%M"))
    # Товаровед пишет «завтра в шесть утра» по своему календарю, а не по UTC.
    assert когда.astimezone(ZoneInfo("Europe/Moscow")).hour == 6


def test_прошедшее_время_отвергается():
    вчера = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    with pytest.raises(ValueError):
        store_price_plans._когда("scheduled", None, вчера)
    with pytest.raises(ValueError):
        store_price_plans._когда("scheduled", None, None)


class _Session:
    def __init__(self):
        self.committed = 0

    async def commit(self):
        self.committed += 1


async def test_исполнение_закрывает_строки_и_переживает_потерянную_карточку(monkeypatch):
    записано = []

    async def подмена(db, cid, station_id, item_uuid, цена, автор, note):
        записано.append((station_id, item_uuid, цена, автор))
        return item_uuid != "нет-такой"     # карточка уехала из справочника

    monkeypatch.setattr(store_price_plans, "записать_цену", подмена)
    cid = uuid.uuid4()
    строки = [
        StorePricePlan(company_id=cid, station_id=208, item_uuid="u-1",
                       name="Кофе", old_price=90, new_price=99, author="товаровед",
                       reason="+10 % к цене", status="scheduled"),
        StorePricePlan(company_id=cid, station_id=208, item_uuid="нет-такой",
                       name="Пропавший", old_price=50, new_price=55, author="товаровед",
                       reason="+10 % к цене", status="scheduled"),
    ]

    итог = await store_price_plans.исполнить(_Session(), строки, cid, автор="")

    assert итог == {"ok": 1, "failed": 1, "stations": 1}
    assert записано[0] == (208, "u-1", 99.0, "товаровед")   # подпись из строки плана
    assert строки[0].status == "applied" and строки[0].applied_at is not None
    # Сбойная строка остаётся в корзине с причиной: одна потерянная карточка не
    # отменяет остальную переоценку, но и молча не исчезает.
    assert строки[1].status == "scheduled"
    assert "справочник" in строки[1].error
