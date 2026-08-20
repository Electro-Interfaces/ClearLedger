"""Шина событий пространства: конверт, подпись, темп повторов.

Ловим то, из-за чего событие молча не доедет: лишний атрибут в конверте (чужой
разбор его не ждёт), подпись не по той строке (получатель отвергнет всё), шаг
повтора короче тика планировщика (доставка выродится в долбёжку каждый тик).
"""
import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.space_events import (
    BACKOFF_CAP, EVENT_TYPES, _backoff, envelope, sign,
)

_WHEN = datetime(2026, 8, 20, 9, 30, tzinfo=timezone.utc)
_EVENT_ID = uuid.UUID("018f2c9e-7d21-7a53-9a10-0b6f2c4de001")


def test_конверт_несёт_ровно_восемь_атрибутов_cloudevents():
    # Тот же набор, что у шины Поддержки: лишнее поле — это уже другой формат,
    # и разбор на той стороне придётся переписывать.
    out = envelope(_EVENT_ID, "doc.registered", "9c1b", _WHEN, {"a": 1})
    assert set(out) == {"specversion", "id", "source", "type", "subject",
                        "time", "datacontenttype", "data"}
    assert out["specversion"] == "1.0"
    assert out["id"] == str(_EVENT_ID)
    assert out["time"] == "2026-08-20T09:30:00Z"
    assert out["datacontenttype"] == "application/json"


def test_время_события_приводится_к_utc():
    local = datetime(2026, 8, 20, 12, 30,
                     tzinfo=timezone(timedelta(hours=3)))
    assert envelope(_EVENT_ID, "doc.registered", "x", local, {})["time"] == (
        "2026-08-20T09:30:00Z")


def test_подпись_считается_по_строке_id_время_тело():
    secret = "whsec_" + base64.b64encode(b"0123456789abcdef").decode()
    body = json.dumps({"a": 1}, ensure_ascii=False, separators=(",", ":"))
    got = sign(secret, str(_EVENT_ID), 1787227800, body)

    key = base64.b64decode(secret[6:])
    want = base64.b64encode(hmac.new(
        key, f"{_EVENT_ID}.1787227800.{body}".encode(), hashlib.sha256,
    ).digest()).decode()
    assert got == "v1," + want


def test_секрет_без_префикса_берётся_как_есть():
    # Подписчик мог завести свой секрет руками, без нашего префикса.
    assert sign("простой-секрет", "id", 1, "{}").startswith("v1,")


def test_шаг_повтора_растёт_и_упирается_в_потолок():
    # Шаг обязан быть кратен тику планировщика (5 минут), иначе первые попытки
    # придутся на один и тот же тик и повтор выродится в долбёжку.
    assert _backoff(1) == timedelta(minutes=5)
    assert _backoff(2) == timedelta(minutes=10)
    assert _backoff(3) == timedelta(minutes=20)
    assert _backoff(12) == BACKOFF_CAP


def test_каталог_типов_закрыт():
    # Подписка не может ссылаться на событие, которого система не издаёт.
    assert "doc.registered" in EVENT_TYPES
    assert "doc.approval.cancelled" not in EVENT_TYPES


async def test_публикация_неизвестного_типа_запрещена():
    from app.services import space_events

    with pytest.raises(ValueError):
        await space_events.publish(None, uuid.uuid4(), "doc.выдумка", "x", {})
