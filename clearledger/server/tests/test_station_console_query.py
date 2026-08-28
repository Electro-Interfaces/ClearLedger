"""Повторяющиеся параметры обязаны доезжать до станции целиком.

Ломалось так: печать ценников шлёт «item=A&item=B&item=C», прокси центра
собирал их через dict(request.query_params) — а dict оставляет по одному
значению на ключ. До станции доезжал один item, и вместо четырнадцати ценников
печатался один. Локально на станции всё работало: там прокси нет.
"""
from starlette.datastructures import QueryParams


def test_повторяющиеся_ключи_переживают_прокси():
    пришло = QueryParams("item=A&item=B&item=C&receipt=r-1")

    # Так было — и так терялось.
    assert dict(пришло) == {"item": "C", "receipt": "r-1"}

    # Так теперь: httpx получает список пар и шлёт все три.
    assert пришло.multi_items() == [
        ("item", "A"), ("item", "B"), ("item", "C"), ("receipt", "r-1"),
    ]


def test_прокси_станции_передаёт_параметры_списком_пар():
    """Страховка от возврата dict(): проверяем сам исходник роутера."""
    from pathlib import Path

    код = Path(__file__).resolve().parents[1].joinpath(
        "app", "routers", "station_console_router.py").read_text(encoding="utf-8")
    assert "params=request.query_params.multi_items()" in код
    assert "params=dict(request.query_params)" not in код
