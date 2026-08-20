"""Ограничение частоты на публичных ручках.

Логика простая, но ошибиться в ней дорого в обе стороны: слишком широкий охват
закроет работу людям, слишком узкий оставит подбор пароля без препятствий.
Отдельно проверяется, что группы не мешают друг другу — иначе перебор токенов
на одном адресе закрыл бы вход всем за той же кромкой.
"""
from unittest.mock import MagicMock

import pytest

from app.rate_limit import LIMITS, check


@pytest.fixture(autouse=True)
def _clean_counters():
    import app.rate_limit as rl
    rl._hits.clear()
    rl._reported.clear()
    yield
    rl._hits.clear()
    rl._reported.clear()


def _req(path: str, ip: str = "10.0.0.5"):
    r = MagicMock()
    r.url.path = path
    r.headers = {"x-forwarded-for": ip}
    r.client.host = ip
    return r


def _verdict(path: str, ip: str = "10.0.0.5"):
    """Только ответ: событие журнала проверяется отдельным тестом."""
    return check(_req(path, ip))[0]


def test_login_is_limited():
    limit, _ = LIMITS["auth"]
    for _ in range(limit):
        assert _verdict("/api/auth/login") is None
    blocked = _verdict("/api/auth/login")
    assert blocked is not None and blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_groups_have_separate_windows():
    """Исчерпанный вход не должен закрывать документ, присланный по ссылке."""
    limit, _ = LIMITS["auth"]
    for _ in range(limit + 1):
        _verdict("/api/auth/login")
    assert _verdict("/api/doc-share/abc") is None


def test_different_addresses_do_not_share_a_window():
    limit, _ = LIMITS["auth"]
    for _ in range(limit + 1):
        _verdict("/api/auth/login", ip="10.0.0.5")
    assert _verdict("/api/auth/login", ip="10.0.0.6") is None


def test_ordinary_endpoints_are_untouched():
    """Ограничивать всё подряд нельзя: витрины делают десятки запросов на экран."""
    for _ in range(200):
        assert _verdict("/api/locations") is None


def test_forgot_and_reset_share_the_auth_window():
    """Восстановление пароля — тот же подбор, только с другой стороны."""
    limit, _ = LIMITS["auth"]
    for _ in range(limit):
        _verdict("/api/auth/forgot-password")
    blocked = _verdict("/api/auth/reset-password")
    assert blocked is not None and blocked.status_code == 429


def test_blocked_attempt_is_reported_once_per_window():
    """Отбить перебор мало: его должно быть видно потом. Но запись — одна на окно,
    иначе тысяча отбитых запросов превращается в тысячу вставок."""
    limit, _ = LIMITS["public_doc"]
    for _ in range(limit):
        check(_req("/api/doc-share/xxx"))
    blocked, event = check(_req("/api/doc-share/xxx"))
    assert blocked is not None and event is not None
    assert event["kind"] == "rate_limited" and event["scope"] == "public_doc"
    assert event["ip"] == "10.0.0.5" and event["path"] == "/api/doc-share/xxx"
    _, again = check(_req("/api/doc-share/yyy"))
    assert again is None
