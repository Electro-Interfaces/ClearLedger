"""Проекция режет отправку на пачки.

Пространство компании перерастает предел размера тела у приёмника (Express — 100 КБ
по умолчанию): 618 объектов пилота давали HTTP 413. Приём идемпотентен, поэтому
дробление ничего не меняет по смыслу — но обязано складывать счётчики и не терять
последнюю неполную пачку.
"""

import math

from app.services.space_projection import BATCH_SIZE


def chunks(items: list, size: int = BATCH_SIZE) -> list[list]:
    """Ровно то разбиение, которым пользуется project() — вынесено, чтобы проверить края."""
    return [items[i:i + size] for i in range(0, len(items) or 1, size)]


def test_batch_covers_everything_without_loss():
    items = list(range(618))                       # столько объектов у пилота
    parts = chunks(items)
    assert len(parts) == math.ceil(618 / BATCH_SIZE)
    assert sum(len(p) for p in parts) == 618       # ничего не потеряно
    assert [x for p in parts for x in p] == items  # и порядок сохранён


def test_batch_boundaries():
    assert len(chunks(list(range(BATCH_SIZE)))) == 1          # ровно одна полная пачка
    assert len(chunks(list(range(BATCH_SIZE + 1)))) == 2      # хвост едет отдельно
    assert len(chunks([1])) == 1


def test_empty_payload_still_sends_once():
    """Пустая проекция — это осмысленный запрос (приложение отвечает нулями), а не
    молчание: иначе кнопка «В приложения» на пустом реестре ничего бы не сообщила."""
    assert chunks([]) == [[]]
