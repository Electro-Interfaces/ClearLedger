"""Паспорт объекта: у кого спрашивать каждую графу.

После разделения уровней (СТО, docs/OBJECTS.md) графы железа принадлежат станции,
но семь из них до сих пор наполняют конвейеры загрузки прямо в колонки точки.
Спросить не того владельца — значит показать застывшее значение вместо свежего,
причём молча. Правило легко сломать невнимательной правкой словаря, поэтому оно
закреплено тестом.
"""
from types import SimpleNamespace

from app.services.station_passport import FEED_OWNED, PASSPORT_SOURCES, passport_value


def _loc(**kw):
    base = dict(serial_number=None, power_kwt=None, connectors_count=None,
                connector_types=None, brand=None, model=None, owner=None,
                ocpp_protocol=None, firmware=None, speed_class=None,
                installed_on=None, decommissioned_on=None, inventory_number=None,
                hubex_asset_id=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _unit(**kw):
    base = dict(serial_number=None, power_kwt=None, connectors_count=None,
                connector_types=None, brand=None, model=None, owner_name=None,
                ocpp_protocol=None, firmware=None, speed_class=None,
                commissioned_on=None, decommissioned_on=None, inventory_number=None,
                hubex_asset_id=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_station_owns_its_own_passport():
    """Заводской номер, модель, прошивка — графы станции: спрашиваем станцию."""
    loc = _loc(serial_number="SN-OLD", model="M-OLD")
    unit = _unit(serial_number="SN-NEW", model="M-NEW", firmware="1.2.3")
    assert passport_value("serialNumber", loc, unit) == "SN-NEW"
    assert passport_value("model", loc, unit) == "M-NEW"
    assert passport_value("firmware", loc, unit) == "1.2.3"


def test_feed_owned_graphs_stay_with_the_point():
    """Мощность, коннекторы, владелец, инвентарный, бренд, дата ввода — их пишет
    загрузка в точку, и станция не должна перекрывать свежую выгрузку."""
    loc = _loc(power_kwt=120.0, connectors_count=4, owner="РусГидро",
               inventory_number="INV-NEW", brand="B-NEW", installed_on="2024-01-01")
    unit = _unit(power_kwt=50.0, connectors_count=1, owner_name="Старый",
                 inventory_number="INV-OLD", brand="B-OLD", commissioned_on="2019-01-01")
    assert passport_value("powerKwt", loc, unit) == 120.0
    assert passport_value("connectorsCount", loc, unit) == 4
    assert passport_value("owner", loc, unit) == "РусГидро"
    assert passport_value("inventoryNumber", loc, unit) == "INV-NEW"
    assert passport_value("brand", loc, unit) == "B-NEW"
    assert passport_value("installedOn", loc, unit) == "2024-01-01"


def test_fallback_works_in_both_directions():
    """Пусто у владельца — берём у второго, чтобы графа не пропала с экрана."""
    assert passport_value("serialNumber", _loc(serial_number="SN"), _unit()) == "SN"
    assert passport_value("powerKwt", _loc(), _unit(power_kwt=50.0)) == 50.0


def test_without_station_behaviour_is_unchanged():
    """Пока связь не заведена, паспорт читается ровно как до разделения."""
    loc = _loc(serial_number="SN", power_kwt=60.0, inventory_number="INV")
    assert passport_value("serialNumber", loc, None) == "SN"
    assert passport_value("powerKwt", loc, None) == 60.0
    assert passport_value("inventoryNumber", loc, None) == "INV"


def test_every_feed_owned_graph_exists_in_sources():
    """Опечатка в FEED_OWNED не должна тихо превратиться в «графы нет»."""
    known = {out_key for out_key, _, _ in PASSPORT_SOURCES}
    assert FEED_OWNED <= known, FEED_OWNED - known
