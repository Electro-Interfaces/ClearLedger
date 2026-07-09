"""HTTP-клиент Яндекс.Метрики.

Reporting (Stat) API — агрегаты по метрикам/разрезам:
    GET https://api-metrika.yandex.net/stat/v1/data
Management API — список счётчиков (для валидации подключения):
    GET https://api-metrika.yandex.net/management/v1/counters
Авторизация: заголовок `Authorization: OAuth <token>`.
"""
from __future__ import annotations

from typing import Any

import httpx

STAT_URL = "https://api-metrika.yandex.net/stat/v1/data"
COUNTERS_URL = "https://api-metrika.yandex.net/management/v1/counters"


class MetrikaError(Exception):
    """Ошибка обращения к API Метрики (с http-статусом, если есть)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"OAuth {token}"}


def _raise(r: httpx.Response) -> None:
    if r.status_code == 200:
        return
    try:
        msg = r.json().get("message") or r.text[:200]
    except Exception:  # noqa: BLE001
        msg = r.text[:200]
    if r.status_code in (401, 403):
        raise MetrikaError(f"Неверный OAuth-токен или нет доступа к счётчику: {msg}", r.status_code)
    if r.status_code == 429:
        raise MetrikaError("Превышен лимит запросов Метрики (429) — повторите позже", 429)
    raise MetrikaError(f"Метрика вернула {r.status_code}: {msg}", r.status_code)


async def list_counters(token: str) -> list[dict[str, Any]]:
    """Доступные счётчики токена (для проверки подключения)."""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(COUNTERS_URL, headers=_headers(token))
    _raise(r)
    return r.json().get("counters", [])


async def stat_data(
    token: str, *, counter_id: str, metrics: list[str], dimensions: list[str] | None = None,
    date1: str = "7daysAgo", date2: str = "today", sort: str | None = None,
    filters: str | None = None, limit: int = 100, accuracy: str = "full",
) -> dict[str, Any]:
    """Отчёт Reporting API (метод «Таблица»). Возвращает {data, totals, sampled, …}."""
    params: dict[str, Any] = {
        "ids": counter_id, "metrics": ",".join(metrics),
        "date1": date1, "date2": date2, "accuracy": accuracy, "limit": limit,
    }
    if dimensions:
        params["dimensions"] = ",".join(dimensions)
    if sort:
        params["sort"] = sort
    if filters:
        params["filters"] = filters
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(STAT_URL, headers=_headers(token), params=params)
    _raise(r)
    return r.json()
