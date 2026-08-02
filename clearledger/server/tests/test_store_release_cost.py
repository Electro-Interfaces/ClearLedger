"""Себестоимость блюда общепита — из выпуска 1С, а не из закупок.

У ГИГ общепит продаётся как сопутствующий товар, а себестоимость 1С формирует по
рецептуре в момент продажи (документ «Выпуск продукции»). Блюдо при этом никогда не
закупается, поэтому база из ПТУ для него пуста — и товарные экраны показывали блюда
без маржи вовсе.
"""
import uuid

from app.services.goods_dashboard import GoodsDashboardService

DISH = "guid-дыуы-капучино"
GOODS = "guid-товар-вода"


def _svc(purchases, releases):
    s = GoodsDashboardService(session=None, company_id=uuid.uuid4())

    async def _p(df, dt, stations):
        return purchases

    async def _r():
        return []

    async def _rel(df, dt, stations):
        return releases

    s._load_purchases, s._load_returns, s._release_agg = _p, _r, _rel
    return s


def _ptu(ref, amount, qty):
    return [{"Документ": {"СуммаВключаетНДС": False,
                          "Товары": [{"Номенклатура": ref, "Сумма": amount, "Количество": qty}]}}]


async def test_dish_costed_from_release_goods_from_purchase():
    svc = _svc(_ptu(GOODS, 500.0, 10), {DISH: [829.2, 10.0]})
    cm = await svc._cost_unit_map()

    assert cm[DISH] == (82.92, "release", 10.0)     # порция по выпуску
    assert cm[GOODS] == (50.0, "purchase", 10.0)    # товар по закупке


async def test_release_wins_over_purchase_for_same_sku():
    svc = _svc(_ptu(DISH, 300.0, 10), {DISH: [829.2, 10.0]})
    cm = await svc._cost_unit_map()

    assert cm[DISH][1] == "release"
    assert cm[DISH][0] == 82.92


async def test_no_release_keeps_purchase_base():
    svc = _svc(_ptu(GOODS, 500.0, 10), {})
    cm = await svc._cost_unit_map()

    assert cm[GOODS][1] == "purchase"
    assert DISH not in cm
