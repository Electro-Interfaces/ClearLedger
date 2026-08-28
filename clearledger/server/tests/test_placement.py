"""Личная раскладка: где отложение упирается в срок компании.

Проверяется одно правило, нарушение которого превращает «не сегодня» в способ
обнулить обязательство: личное сокрытие не двигает срок предмета. Отложить
дальше срока нельзя — дата обрезается днём срока; просроченное не прячется
вовсе.

Без БД: `clamp_defer` — чистая функция, и гонять ради неё контейнер незачем.
"""
from datetime import date, datetime, timezone

import pytest

from app.services.placement import DeferRefused, clamp_defer

TODAY = date(2026, 8, 28)


def _due(day: int, hour: int = 18) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


def test_без_срока_откладывается_куда_угодно():
    assert clamp_defer(date(2026, 12, 31), None, TODAY) == date(2026, 12, 31)


def test_внутри_срока_остаётся_как_просили():
    assert clamp_defer(date(2026, 9, 1), _due(10), TODAY) == date(2026, 9, 1)


def test_дальше_срока_обрезается_днём_срока():
    # Человек просит спрятать до 20-го, а срок 10-го: возвращаем в день срока,
    # а не молча соглашаемся — иначе работа всплывёт уже просроченной.
    assert clamp_defer(date(2026, 9, 20), _due(10), TODAY) == date(2026, 9, 10)


def test_ровно_в_день_срока_допустимо():
    assert clamp_defer(date(2026, 9, 10), _due(10), TODAY) == date(2026, 9, 10)


def test_просроченное_не_прячется():
    # Срок 20 августа, сегодня 28-е: спрятать нельзя — просроченное закрывают,
    # передают или переносят срок, но не убирают с глаз.
    with pytest.raises(DeferRefused):
        clamp_defer(date(2026, 9, 5),
                    datetime(2026, 8, 20, 18, tzinfo=timezone.utc), TODAY)


def test_срок_сегодня_тоже_не_прячется():
    with pytest.raises(DeferRefused):
        clamp_defer(date(2026, 8, 29), datetime(2026, 8, 28, 23, tzinfo=timezone.utc), TODAY)


def test_отложить_в_прошлое_или_на_сегодня_нельзя():
    for day in (date(2026, 8, 27), TODAY):
        with pytest.raises(DeferRefused):
            clamp_defer(day, None, TODAY)


def test_срок_строкой_из_очереди_понимается_так_же():
    # Очередь отдаёт срок в ISO, и отложение идёт из той же строки экрана.
    assert clamp_defer(date(2026, 9, 20), "2026-09-10T18:00:00+00:00", TODAY) == date(2026, 9, 10)


def test_срок_без_пояса_не_роняет_разбор():
    assert clamp_defer(date(2026, 9, 20), "2026-09-10T18:00:00", TODAY) == date(2026, 9, 10)
