"""Отметка «ключом пользовались» пишется не чаще раза в минуту.

Проверяем именно экономию записи: раньше каждое обращение по ключу обновляло одну
и ту же строку, и при зависшей транзакции все обращения по этому ключу вставали в
очередь на блокировке строки (инцидент на gig 25.10.2026 — очередь по четыре минуты
и отказы по statement_timeout).
"""
from datetime import datetime, timedelta, timezone

from app.auth import KEY_TOUCH_INTERVAL, touch_key_used


class _Key:
    """Минимальный двойник: функции нужен только атрибут last_used_at."""

    def __init__(self, last_used_at=None):
        self.last_used_at = last_used_at


def test_pervoe_obrashchenie_pishetsya():
    k = _Key()
    touch_key_used(k)
    assert k.last_used_at is not None


def test_povtor_v_predelah_minuty_ne_pishet():
    byla = datetime.now(timezone.utc) - timedelta(seconds=5)
    k = _Key(byla)
    touch_key_used(k)
    assert k.last_used_at == byla, "запись в пределах интервала означала бы прежнюю очередь"


def test_posle_intervala_pishet():
    byla = datetime.now(timezone.utc) - KEY_TOUCH_INTERVAL - timedelta(seconds=1)
    k = _Key(byla)
    touch_key_used(k)
    assert k.last_used_at > byla
