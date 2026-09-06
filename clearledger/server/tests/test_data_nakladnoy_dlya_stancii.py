"""Дата бумажной накладной уезжает на станцию календарной датой по Москве.

Станция принимает только «ГГГГ-ММ-ДД»: `ValidateReceipt` на полном ISO
отказывает — «дата входящего документа должна быть в формате ГГГГ-ММ-ДД».
Первая накладная АЗС 8 (П-8-260905-1131, 05.09.2026) с этой красной строкой и
легла оператору на стол.

Второй капкан — часовой пояс: центр хранит моменты в UTC, и накладная от 31.08
лежит как 2026-08-30T21:00Z. Наивный `.date()` сделал бы её тридцатым августа.
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


def дата_накладной(value):
    """Повторяет _дата_накладной из store_router."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Europe/Moscow")).date().isoformat()


def test_вечер_по_utc_это_следующий_день_станции():
    assert дата_накладной(datetime(2026, 8, 30, 21, 0, tzinfo=timezone.utc)) == "2026-08-31"


def test_наивное_время_считается_utc():
    assert дата_накладной(datetime(2026, 8, 30, 21, 0)) == "2026-08-31"


def test_московское_время_остаётся_своей_датой():
    мск = timezone(timedelta(hours=3))
    assert дата_накладной(datetime(2026, 8, 31, 0, 0, tzinfo=мск)) == "2026-08-31"


def test_пустая_дата_остаётся_пустой():
    assert дата_накладной(None) is None
