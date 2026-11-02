"""Маршрут поручения и типизированной задачи, без запросов и side effects."""
from __future__ import annotations

from app.models import TaskType


DEFAULT_ROUTE: list[dict] = [
    {"code": "new", "name": "Постановка"},
    {"code": "in_progress", "name": "В работе"},
    {"code": "review", "name": "Проверка"},
]

_USE_DEFAULT_ROUTE = object()


def route_of(t: TaskType | None, *, default_route=_USE_DEFAULT_ROUTE) -> list[dict]:
    """Маршрут типа; у задачи без типа — маршрут поручения."""
    if default_route is _USE_DEFAULT_ROUTE:
        default_route = DEFAULT_ROUTE
    if t is None or not t.route:
        return default_route
    stages = [s for s in t.route if isinstance(s, dict) and s.get("code")]
    return stages or default_route
