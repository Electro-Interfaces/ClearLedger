"""Разбор корзины сети: метрики, связки и топливо как измерение покупателя."""
import uuid
from datetime import datetime, timezone

from app.services import store_baskets
from app.services.store_baskets import analyze


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Session:
    """Сессия-заглушка: чеки и заправки отдаёт, справочник карточек — пустой."""

    def __init__(self, cheques, fuel=()):
        self.cheques, self.fuel = cheques, list(fuel)

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "fuel_transactions" in sql:
            return _Rows(self.fuel)
        if "store_cheques" in sql:
            return _Rows(self.cheques)
        return _Rows([])  # edge.item — обогащения контуром в тесте нет


def _чек(station, hour, lines, *, fuel=False, ret=False, pay="Наличные",
         shift=7100, number=1):
    return {
        "station_id": station,
        "shift_number": shift,
        "number": number,
        "at": datetime(2026, 8, 10, hour, tzinfo=timezone.utc),
        "is_return": ret,
        "had_fuel": fuel,
        "pay_name": pay,
        "lines": [{"name": имя, "qty": 1, "amount": сумма, "scope": "store"}
                  for имя, сумма in lines],
    }


def _заправка(station, receipt, fuel_name, liters, amount, shift=7100):
    return {"station_code": station, "shift_number": shift, "receipt": receipt,
            "fuel_name": fuel_name, "liters": liters, "amount": amount}


async def test_корзина_считает_глубину_связки_и_не_мешает_возвраты():
    # Пять чеков «кофе + хот-дог» дают связку (порог — пять), одиночные кофе
    # разбавляют её и опускают уверенность.
    чеки = [_чек(208, 8, [("Кофе", 100), ("Хот-дог", 150)], number=n)
            for n in range(1, 6)]
    чеки += [_чек(208, 9, [("Кофе", 100)], number=n) for n in range(6, 11)]
    чеки += [_чек(5, 20, [("Вода", 60)], fuel=True, number=11)]
    чеки += [_чек(208, 21, [("Кофе", 100)], ret=True, number=12)]

    итог = await analyze(_Session(чеки), uuid.uuid4(), "2026-08-01", "2026-08-31")

    т = итог["totals"]
    assert т["cheques"] == 11              # возврат в корзину не попал
    assert т["returns"] == 1 and т["returns_amount"] == 100.0
    assert т["revenue"] == 5 * 250 + 5 * 100 + 60
    assert т["positions"] == 16
    assert т["depth"] == round(16 / 11, 2)
    assert т["single_pct"] == round(6 / 11 * 100, 1)

    пары = итог["pairs"]
    assert len(пары) == 1
    пара = пары[0]
    assert (пара["a"], пара["b"]) == ("Кофе", "Хот-дог")
    assert пара["together"] == 5
    # Кофе в 10 чеках, хот-дог в 5, вместе 5 из 11 → уверенность 50 %,
    # подъём = 0.4545 / (0.9091 × 0.4545) = 1.1
    assert пара["confidence"] == 50.0
    assert пара["lift"] == 1.1

    станции = {с["station_id"]: с for с in итог["stations"]}
    assert станции[5]["cheques"] == 1
    assert станции[208]["cheques"] == 10

    размеры = {р["positions"]: р["cheques"] for р in итог["sizes"]}
    assert размеры == {1: 6, 2: 5}
    assert [ч["hour"] for ч in итог["hours"]] == [11, 12, 23]  # МСК = UTC+3


async def test_прицеп_к_топливу_и_разрез_по_марке():
    # Четыре заправки: две с товаром (95-й и ДТ), две — уехали ни с чем.
    чеки = [
        _чек(208, 8, [("Кофе", 100)], fuel=True, number=1),
        _чек(208, 9, [("Вода", 60), ("Шоколад", 90)], fuel=True, number=2),
        _чек(208, 10, [("Жвачка", 40)], number=9),   # без заправки
    ]
    заправки = [
        _заправка(208, 1, "АИ-95", 15, 3000),
        _заправка(208, 2, "ДТ", 45, 4500),
        _заправка(208, 3, "АИ-95", 20, 4000),
        _заправка(208, 4, "АИ-92", 8, 1500),
    ]

    итог = await analyze(_Session(чеки, заправки), uuid.uuid4(),
                         "2026-08-01", "2026-08-31")

    т = итог["totals"]
    assert т["fuel_ops"] == 4
    assert т["mixed"] == 2
    assert т["fuel_only"] == 2
    assert т["attach_pct"] == 50.0
    assert т["avg_fill"] == 22.0                     # (15+45+20+8)/4
    assert т["goods_per_fill"] == round(250 / 4, 2)  # товар смешанных на все заправки

    assert итог["fuel"]["matched"] == 2
    assert итог["fuel"]["matched_pct"] == 100.0
    марки = {м["fuel"]: м for м in итог["fuel"]["by_fuel"]}
    assert марки["АИ-95"]["ops"] == 2 and марки["АИ-95"]["with_goods"] == 1
    assert марки["АИ-95"]["attach_pct"] == 50.0
    assert марки["ДТ"]["attach_pct"] == 100.0
    assert марки["ДТ"]["goods_per_fill"] == 150.0    # вода + шоколад на одну заправку
    assert марки["АИ-92"]["with_goods"] == 0

    объёмы = {д["label"]: д for д in итог["fuel"]["by_volume"]}
    assert объёмы["до 10 л"]["ops"] == 1 and объёмы["до 10 л"]["with_goods"] == 0
    # 15 л с товаром и 20 л без него — обе в диапазоне (10; 20]
    assert объёмы["10–20 л"]["ops"] == 2 and объёмы["10–20 л"]["attach_pct"] == 50.0
    assert объёмы["40 л и больше"]["attach_pct"] == 100.0

    станция = итог["stations"][0]
    assert станция["fuel_ops"] == 4 and станция["attach_pct"] == 50.0


async def test_топливный_контур_отстал_прицеп_не_уходит_за_сто():
    # Реализаций ещё нет, а смешанные чеки уже приехали: заправками считаем их.
    чеки = [_чек(208, 8, [("Кофе", 100)], fuel=True, number=1),
            _чек(208, 9, [("Кофе", 100)], fuel=True, number=2)]
    итог = await analyze(_Session(чеки, []), uuid.uuid4(), "2026-08-01", "2026-08-31")
    assert итог["totals"]["fuel_ops"] == 2
    assert итог["totals"]["attach_pct"] == 100.0
    assert итог["fuel"]["ops"] == 0 and итог["fuel"]["matched"] == 0


async def test_разбор_по_товару_считает_соседей_и_часы():
    # Кофе в семи чеках, из них пять — с хот-догом; вода живёт своей жизнью.
    чеки = [_чек(208, 8, [("Кофе", 100), ("Хот-дог", 150)], number=n)
            for n in range(1, 6)]
    чеки += [_чек(208, 15, [("Кофе", 100)], fuel=True, number=n) for n in range(6, 8)]
    чеки += [_чек(208, 9, [("Вода", 60)], number=n) for n in range(8, 14)]

    итог = await store_baskets.по_товару(_Session(чеки), uuid.uuid4(),
                                         "2026-08-01", "2026-08-31", "Кофе")

    assert итог["item"] == "Кофе"
    assert итог["cheques"] == 7
    assert итог["share"] == round(7 / 13 * 100, 1)
    assert итог["revenue"] == 700 and итог["avg_price"] == 100.0
    assert итог["with_fuel"] == 2
    соседи = {с["name"]: с for с in итог["neighbours"]}
    # Вода ни разу не встретилась с кофе — соседом её называть нечего.
    assert set(соседи) == {"Хот-дог"}
    assert соседи["Хот-дог"]["together"] == 5
    assert соседи["Хот-дог"]["confidence"] == round(5 / 7 * 100, 1)
    часы = {ч["hour"]: ч["cheques"] for ч in итог["hours"] if ч["cheques"]}
    assert часы == {11: 5, 18: 2}          # МСК = UTC+3


async def test_разбор_по_пустому_имени_ничего_не_считает():
    итог = await store_baskets.по_товару(_Session([]), uuid.uuid4(),
                                         "2026-08-01", "2026-08-31", "  ")
    assert итог["cheques"] == 0 and итог["neighbours"] == []


async def test_пустой_период_не_падает_и_говорит_словами():
    итог = await analyze(_Session([]), uuid.uuid4(), "2026-08-01", "2026-08-02")
    assert итог["totals"]["cheques"] == 0
    assert итог["pairs"] == []
    assert "считать нечего" in итог["verdict"]
