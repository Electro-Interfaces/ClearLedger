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
    yield
    rl._hits.clear()


def _req(path: str, ip: str = "10.0.0.5"):
    r = MagicMock()
    r.url.path = path
    r.headers = {"x-forwarded-for": ip}
    r.client.host = ip
    return r


def test_login_is_limited():
    limit, _ = LIMITS["auth"]
    for _ in range(limit):
        assert check(_req("/api/auth/login")) is None
    blocked = check(_req("/api/auth/login"))
    assert blocked is not None and blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_groups_have_separate_windows():
    """Исчерпанный вход не должен закрывать документ, присланный по ссылке."""
    limit, _ = LIMITS["auth"]
    for _ in range(limit + 1):
        check(_req("/api/auth/login"))
    assert check(_req("/api/doc-share/abc")) is None


def test_different_addresses_do_not_share_a_window():
    limit, _ = LIMITS["auth"]
    for _ in range(limit + 1):
        check(_req("/api/auth/login", ip="10.0.0.5"))
    assert check(_req("/api/auth/login", ip="10.0.0.6")) is None


def test_ordinary_endpoints_are_untouched():
    """Ограничивать всё подряд нельзя: витрины делают десятки запросов на экран."""
    for _ in range(200):
        assert check(_req("/api/locations")) is None


def test_forgot_and_reset_share_the_auth_window():
    """Восстановление пароля — тот же подбор, только с другой стороны."""
    limit, _ = LIMITS["auth"]
    for _ in range(limit):
        check(_req("/api/auth/forgot-password"))
    blocked = check(_req("/api/auth/reset-password"))
    assert blocked is not None and blocked.status_code == 429
