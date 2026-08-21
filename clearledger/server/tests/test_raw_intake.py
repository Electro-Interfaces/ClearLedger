"""Слой сырых пакетов: усечение по бюджету и горизонт хранения.

Без БД: проверяется ровно то, что решает судьбу пакета ещё до вставки.
"""
import uuid
import json

import pytest

from app.services import raw_intake


def _item(size: int) -> dict:
    """Элемент, чьё JSON-представление заведомо больше `size` байт."""
    return {"payload": "x" * size}


def test_пакет_в_бюджете_кладётся_целиком():
    items = [_item(10), _item(10)]
    kept, note = raw_intake.fit(items, budget=10_000)
    assert kept == items
    assert note.get("truncated") is None
    assert note["bytes"] > 0


def test_усечение_режет_префиксом_и_считает_отброшенное():
    items = [_item(100), _item(100), _item(100)]
    one = len(json.dumps(items[0], ensure_ascii=False).encode("utf-8"))
    kept, note = raw_intake.fit(items, budget=one * 2)
    # Именно первые два, а не «любые поместившиеся»: дырка в середине читалась бы
    # как потеря данных источником.
    assert kept == items[:2]
    assert note == {"bytes": one * 2, "truncated": True, "kept": 2, "total": 3}


def test_первый_элемент_больше_бюджета_даёт_пустой_пакет_с_отметкой():
    kept, note = raw_intake.fit([_item(5000)], budget=100)
    assert kept == []
    assert note["truncated"] is True and note["kept"] == 0 and note["total"] == 1


def test_несериализуемый_элемент_падает_здесь_а_не_во_вставке():
    with pytest.raises(TypeError):
        raw_intake.fit([{"x": object()}], budget=10_000)


def test_кириллица_меряется_в_байтах_а_не_в_символах():
    # «Смена» в UTF-8 — два байта на букву; бюджет в символах пропустил бы вдвое
    # больше, чем влезает, и усечение перестало бы быть защитой.
    item = {"Смена": "документ"}
    size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
    assert size > len(json.dumps(item, ensure_ascii=False))
    kept, _ = raw_intake.fit([item, item], budget=size)
    assert kept == [item]


def test_горизонт_по_умолчанию_и_настройка(monkeypatch):
    monkeypatch.delenv("RAW_BATCH_KEEP_DAYS", raising=False)
    assert raw_intake.keep_days() == raw_intake.KEEP_DAYS_DEFAULT
    monkeypatch.setenv("RAW_BATCH_KEEP_DAYS", "7")
    assert raw_intake.keep_days() == 7


@pytest.mark.parametrize("value,expected", [
    ("0", 1),        # опечатка в окружении не должна чистить слой в момент записи
    ("-5", 1),
    ("100000", 365),  # рабочий буфер не превращается в архив
    ("тридцать", raw_intake.KEEP_DAYS_DEFAULT),
    ("", raw_intake.KEEP_DAYS_DEFAULT),
])
def test_горизонт_зажат_с_обеих_сторон(monkeypatch, value, expected):
    monkeypatch.setenv("RAW_BATCH_KEEP_DAYS", value)
    assert raw_intake.keep_days() == expected


def test_период_прогона_строкой_становится_датой():
    assert raw_intake._as_dt("2026-08-01").isoformat() == "2026-08-01T00:00:00"
    assert raw_intake._as_dt(None) is None
    assert raw_intake._as_dt("вся история") is None


def test_повтор_объявлен_только_там_где_источник_не_нужен():
    # Ветки STS сохраняют перечень смен, а отчёт смены тянут отдельным запросом:
    # «повтор» по такому пакету всё равно пошёл бы к источнику.
    assert set(raw_intake._REPLAY) == {"cb_shifts"}


# ── Владелец пакета: канал Ядра или подключение приложения ───────────────────


async def test_пакет_без_владельца_не_сохраняется():
    """Ни источника, ни подключения — неизвестно, кто привёз и кому повторять."""
    from app.services import raw_intake

    got = await raw_intake.save_raw_batch(
        None, company_id=uuid.uuid4(), doc_type="cb_shifts", items=[{"a": 1}])
    assert got is None


async def test_пакет_с_двумя_владельцами_не_сохраняется():
    # «Оба сразу» — это не избыточность, а потеря ответа на вопрос «чей пакет».
    from app.services import raw_intake

    got = await raw_intake.save_raw_batch(
        None, company_id=uuid.uuid4(), doc_type="cb_shifts", items=[{"a": 1}],
        source_id=uuid.uuid4(), connection_id=uuid.uuid4())
    assert got is None
