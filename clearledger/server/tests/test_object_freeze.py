"""Что считается номером объекта и когда его нельзя менять (СТО п. 7.5, 7.6).

Граница здесь юридическая, а не техническая: заводской, инвентарный и внешний
идентификаторы номерами объекта не являются (п. 2.9), и запрет на них не
распространяется. Спутать легко — все они «номера» в обиходе, — а цена ошибки
разная: лишний запрет мешает работе, недостающий рвёт ссылки снаружи.
"""
from types import SimpleNamespace

from app.services.object_freeze import (
    REASON_ACCOUNTED, REASON_CONTRACT, REASON_EXPORTED, REASON_SESSION, number_changed,
)


def _loc(code="612", station_number="276"):
    return SimpleNamespace(code=code, station_number=station_number)


def test_code_change_is_a_number_change():
    assert number_changed(_loc(), "613", None) is True
    assert number_changed(_loc(), "612", None) is False


def test_station_number_is_also_the_object_number():
    """«Номер станции» правится через снимок, но это тот же номер объекта."""
    assert number_changed(_loc(), None, "277") is True
    assert number_changed(_loc(), None, "276") is False


def test_untouched_fields_do_not_trigger_the_ban():
    """Правка адреса или названия номер не меняет — запрет не должен срабатывать."""
    assert number_changed(_loc(), None, None) is False


def test_whitespace_is_not_a_change():
    """Пробелы по краям не считаются правкой: иначе форма ловила бы запрет на
    ровном месте, просто отправив то же значение."""
    assert number_changed(_loc(), " 612 ", None) is False
    assert number_changed(_loc(), None, " 276 ") is False


def test_empty_current_values_are_comparable():
    """У объекта без номера правка — это появление номера, а не его смена."""
    assert number_changed(_loc(code="", station_number=None), "700", None) is True


def test_reasons_are_human_readable():
    """Причину читает человек, которому отказали: она должна называть событие."""
    for reason in (REASON_CONTRACT, REASON_ACCOUNTED, REASON_SESSION, REASON_EXPORTED):
        assert isinstance(reason, str) and len(reason) > 10
        assert reason == reason.strip()
