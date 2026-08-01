"""Привязки объекта к источникам приводятся к списку на чтении.

Регрессия 01.08.2026: сведение справочника положило 142 объектам пилота
одиночную привязку объектом вместо списка — `GET /api/locations` отвечал 500,
и вместе с ним пустели селектор станций, карта, парк оборудования и все
экраны, перечисляющие сеть.
"""

from types import SimpleNamespace

from app.models import location_bindings


def _loc(value):
    return SimpleNamespace(source_bindings=value)


def test_список_проходит_как_есть():
    binds = [{"sourceId": "s1", "config": {"station": 12}}]
    assert location_bindings(_loc(binds)) == binds


def test_одиночная_привязка_объектом_оборачивается_в_список():
    single = {"origin": "hubex_mirror", "support": "f2c17c8e-7788-462a-aeae-cee6f2e728bb"}
    assert location_bindings(_loc(single)) == [single]


def test_пусто_и_мусор_дают_пустой_список():
    assert location_bindings(_loc(None)) == []
    assert location_bindings(_loc([])) == []
    assert location_bindings(_loc("hubex")) == []
    assert location_bindings(_loc(42)) == []


def test_нечитаемые_элементы_отбрасываются_а_словари_остаются():
    good = {"sourceId": "s1"}
    assert location_bindings(_loc([good, "мусор", None, 7])) == [good]


def test_потребитель_может_звать_get_на_каждом_элементе():
    """Ровно то, на чём падал online_orders: итерация по dict давала строки."""
    single = {"origin": "hubex_mirror", "support": "uuid"}
    for b in location_bindings(_loc(single)):
        assert b.get("config") is None  # не AttributeError на str
