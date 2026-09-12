"""Разбор выгрузки реестра ЭЗС страны (app/services/market_registry.py).

Проверяем то, на чём приём ломается молча и выводы становятся неверными:
разбор коннекторов и тарифов с окнами, класс точки, площадка-агрегатор вместо
оператора, валюта, BOM в первой колонке. База здесь не нужна — это чистый разбор.

Прогон:  py -m pytest server/tests/test_market_registry.py -q
"""
from __future__ import annotations

from app.services.market_registry import (CURRENCY_BY_ID, comparable_price,
                                          parse_connectors, parse_registry_csv,
                                          parse_tariffs, site_class)


def test_connectors_keep_own_power():
    """Мощность у коннектора своя: один CCS 150 кВт и четыре Type 2 по 22 — разные
    конкуренты, хотя суммарная мощность сопоставима."""
    out = parse_connectors("CHAdeMO:50|CCS Combo 2:60")
    assert out == [{"type": "CHAdeMO", "power_kw": 50.0},
                   {"type": "CCS Combo 2", "power_kw": 60.0}]
    # Имя с двоеточием внутри и без мощности не должно рвать разбор.
    assert parse_connectors("Type 1:3|Красная (на три фазы):10")[1]["power_kw"] == 10.0
    assert parse_connectors("") == []
    assert parse_connectors(None) == []


def test_tariffs_windows_and_units():
    """Окно действия сохраняется: «20 ₽ днём и 17 ночью» — это два факта, а не один."""
    out = parse_tariffs("per_kwt:20@08:00-23:00|per_kwt:17@23:00-08:00")
    assert out == [{"unit": "kwh", "price": 20.0, "window": "08:00-23:00"},
                   {"unit": "kwh", "price": 17.0, "window": "23:00-08:00"}]
    # За минуту и за сессию единица сохраняется как есть — в сравнение с ₽/кВт·ч
    # такие тарифы не идут (принцип 3 MARKET.md).
    assert parse_tariffs("per_minute:7")[0]["unit"] == "minute"
    assert parse_tariffs("") == []


def test_site_class_separates_home_sockets():
    """Домашняя розетка не сеть: в сравнении операторов она мусор."""
    assert site_class("home_station", None) == "home"
    assert site_class("public_station_paid_fast", "PUNKT E") == "network"
    assert site_class("public_station", None) == "network"
    assert site_class(None, None) == "unknown"


def test_currency_guard():
    """Рубль — единственная сравнимая валюта: тариф 0.54 в Беларуси при смешении
    превратит медиану рынка в выдумку."""
    assert CURRENCY_BY_ID["1"] == "RUB"
    assert CURRENCY_BY_ID.get("9") is None


def test_comparable_price_filters_what_breaks_the_median():
    """Четыре случая из настоящей выгрузки, каждый из которых сдвигает медиану рынка."""
    # Обычный рублёвый тариф — сравним.
    assert comparable_price("kwh", 19.0, paid=True, currency="RUB") == 19.0
    # Ноль на БЕСПЛАТНОЙ станции — настоящий факт (вся наша сеть такая).
    assert comparable_price("kwh", 0.0, paid=False, currency="RUB") == 0.0
    # Ноль на ПЛАТНОЙ — «цена не указана»: в выгрузке есть `per_kwt:0` при `paid=1`.
    assert comparable_price("kwh", 0.0, paid=True, currency="RUB") is None
    # 600 ₽/кВт·ч — цена за сессию, попавшая в поле киловатт-часа.
    assert comparable_price("kwh", 600.0, paid=True, currency="RUB") is None
    # Не рубли (Беларусь, Казахстан) и не за киловатт-час.
    assert comparable_price("kwh", 0.54, paid=True, currency="BYN") is None
    assert comparable_price("minute", 7.0, paid=True, currency="RUB") is None


def test_csv_bom_does_not_hide_the_key():
    """BOM в первой колонке делает ключ точки невидимым, и весь файл заезжает как
    новые записи при каждом прогоне."""
    content = ("﻿id;uuid;name;lat;lon;operator;icon_type;connectors;tariffs;currency_id\r\n"
               "53512;abc-1;Акварель ТЦ;56.00018;37.87966;PUNKT E;public_station_paid_fast;"
               "CHAdeMO:50;per_kwt:20@08:00-23:00;1\r\n").encode("utf-8")
    rows = parse_registry_csv(content)
    assert len(rows) == 1
    assert rows[0]["id"] == "53512"          # не "﻿id"
    assert rows[0]["uuid"] == "abc-1"
    assert parse_tariffs(rows[0]["tariffs"])[0]["price"] == 20.0


if __name__ == "__main__":  # прогон без pytest
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
