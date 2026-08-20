"""Управление подписками: то, что должно отказать до базы.

Ловим три вещи, каждая из которых доезжает до подписчика молча. Неизвестный тип
события — подписка, которая никогда не сработает. Секрет не того формата —
подпись, которую получатель не сойдёт. Недобранная цель — 500-я из CHECK вместо
внятного отказа.
"""
import base64

import pytest
from fastapi import HTTPException

from app.routers.space_events_router import (
    _check_shape, _check_types, _new_secret,
)
from app.services.space_events import EVENT_TYPES, sign


def test_неизвестный_тип_события_отклоняется_а_не_отсеивается():
    # Тихий отсев оставил бы человека в уверенности, что он подписался.
    with pytest.raises(HTTPException) as e:
        _check_types(["doc.registered", "doc.exploded"])
    assert e.value.status_code == 400
    assert "doc.exploded" in e.value.detail


def test_пустой_список_типов_отклоняется():
    with pytest.raises(HTTPException) as e:
        _check_types([])
    assert e.value.status_code == 400


def test_дубли_типов_схлопываются_с_сохранением_порядка():
    assert _check_types(["doc.archived", "doc.registered", "doc.archived"]) == [
        "doc.archived", "doc.registered"]


def test_каталог_принимается_целиком():
    assert _check_types(list(EVENT_TYPES)) == list(EVENT_TYPES)


@pytest.mark.parametrize("kind,app_code,url,secret", [
    ("app", None, None, False),                       # приложение без кода
    ("app", "support", "https://x.test/hook", False),  # вторая копия адреса
    ("url", None, None, True),                        # внешний без адреса
    ("url", None, "ftp://x.test/hook", True),         # не http(s)
    ("url", None, "не адрес", True),                  # мусор вместо адреса
    ("url", None, "https://x.test/hook", False),      # внешний без секрета
])
def test_недобранная_цель_отклоняется_словами(kind, app_code, url, secret):
    with pytest.raises(HTTPException) as e:
        _check_shape(kind, app_code, url, has_secret=secret)
    assert e.value.status_code == 400
    assert e.value.detail  # человеку должно быть понятно, чего не хватило


@pytest.mark.parametrize("kind,app_code,url,secret", [
    ("app", "support", None, False),
    ("url", None, "https://x.test/hook", True),
])
def test_допустимые_сочетания_проходят(kind, app_code, url, secret):
    _check_shape(kind, app_code, url, has_secret=secret)


def test_секрет_в_формате_standard_webhooks_и_годится_для_подписи(monkeypatch):
    monkeypatch.setenv("EVENTS_SECRET_KEY", "ключ-стенда")
    raw, enc, hint = _new_secret()

    assert raw.startswith("whsec_")
    # 24 байта — ровно то, что ждёт библиотека подписчика на той стороне.
    assert len(base64.b64decode(raw[6:])) == 24
    assert hint == raw[-6:] and len(hint) == 6
    assert raw not in enc  # наружу из хранилища секрет не проступает
    assert sign(raw, "evt", 1767225600, "{}").startswith("v1,")


def test_без_ключа_стека_секрет_не_заводится(monkeypatch):
    # Открытым он не ляжет: лучше отказ, чем секрет подписи в базе как есть.
    monkeypatch.delenv("EVENTS_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        _new_secret()
    assert e.value.status_code == 503
