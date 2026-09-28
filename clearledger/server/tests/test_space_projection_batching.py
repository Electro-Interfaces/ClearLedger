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


def test_only_last_objects_batch_carries_full_list(monkeypatch):
    """Полный состав едет одним списком с последней пачкой: приёмник архивирует
    отсутствующих только по нему. Когда полным считалась каждая пачка, 28.09.2026
    на rushydro ушли в архив 602 объекта и отменились 1722 заявки."""
    import asyncio
    from types import SimpleNamespace
    from app.services import space_projection as sp

    items = [{"id": f"o{i}", "name": f"Станция {i}"} for i in range(250)]
    sent: list[dict] = []

    async def fake_target(db, cid, app):
        return SimpleNamespace(), SimpleNamespace(external_company_id="ext"), "t"

    async def fake_payload(db, cid, app_row, app, entity):
        return items

    class Resp:
        status_code = 200
        def json(self): return {"created": 0, "updated": 0, "skipped": []}

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            sent.append(json)
            return Resp()

    monkeypatch.setattr(sp, "_target", fake_target)
    monkeypatch.setattr(sp, "_payload", fake_payload)
    monkeypatch.setattr(sp, "_internal_base_url", lambda *a: "http://support")
    monkeypatch.setattr(sp.httpx, "AsyncClient", Client)

    asyncio.run(sp.project(None, "cid", "support", "objects"))
    assert len(sent) == 3
    assert [("allIds" in b) for b in sent] == [False, False, True]
    assert sent[-1]["allIds"] == [it["id"] for it in items]
