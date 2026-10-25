"""Точные API-приманки из приватной конфигурации пространства.

Список рабочих адресов не попадает в код, OpenAPI или ответы API. Нормальный
маршрутизатор отдаёт 404; журналирование не входит во время ожидания ответа.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from functools import lru_cache

from fastapi import Request

logger = logging.getLogger("clearledger.security")
KINDS = frozenset({"canary_config", "canary_backup", "canary_identity", "canary_privilege"})
_pending: dict[tuple[str, str], asyncio.Task] = {}
MAX_PENDING = 128
_overflow_logged_at = -1e9


@lru_cache(maxsize=1)
def routes() -> dict[str, str]:
    raw = os.environ.get("SECURITY_CANARY_ROUTES_JSON", "").strip()
    if not raw:
        return {}
    if len(raw) > 16384:
        raise ValueError("Слишком большая конфигурация API-приманок")
    try:
        pairs = json.loads(raw, object_pairs_hook=list)
    except (ValueError, TypeError):
        raise ValueError("Неверный JSON конфигурации API-приманок") from None
    if not raw.startswith("{") or not isinstance(pairs, list) or len(pairs) > 32:
        raise ValueError("API-приманки: нужен объект не более чем с 32 адресами")
    result = {}
    for path, kind in pairs:
        if (not isinstance(path, str) or not re.fullmatch(r"/api/[a-z0-9._/-]{1,180}", path)
                or "//" in path or any(p in (".", "..") for p in path.split("/"))
                or path.endswith("/") or not isinstance(kind, str) or kind not in KINDS
                or path in result):
            raise ValueError("Недопустимая или повторная API-приманка")
        result[path] = kind
    return result


def kind_for(path: str) -> str | None:
    # ASGI path уже декодирован сервером. Не декодировать повторно: это меняет
    # семантику маршрутизации. Только безвредные варианты регистра/конечного слеша.
    return routes().get(path.lower().rstrip("/"))


def validate_routes(app_routes) -> None:
    for path in routes():
        for route in app_routes:
            pattern = getattr(route, "path_regex", None)
            if pattern and (pattern.fullmatch(path) or pattern.fullmatch(path + "/")):
                # Не печатать адрес: настройка не должна утечь в открытый startup log.
                raise ValueError("API-приманка пересекается с рабочим маршрутом")


def observe(request: Request, kind: str) -> None:
    """Сразу поставить событие в обработку, не ждать БД/уведомлений в HTTP.

    Один ожидающий эпизод на вид/адрес. Ограничение защищает память при потоке
    уникальных адресов; обычные probe/rate-limit продолжают работать независимо.
    """
    global _overflow_logged_at
    from app import guard
    key = (kind, guard.client_ip(request))
    if key in _pending:
        return
    if len(_pending) >= MAX_PENDING:
        # Не превращать переполнение очереди в поток собственных логов.
        now = time.monotonic()
        if now - _overflow_logged_at >= 60:
            logger.warning("Очередь событий API-приманок заполнена; общий лимит API остаётся активным")
            _overflow_logged_at = now
        return
    task = asyncio.create_task(guard.record(
        kind, request, block=False,
        detail=f"method={request.method}; запрос к неиспользуемому служебному API; "
               "снаружи обычный 404; успешного доступа этот эпизод не подтверждает",
    ))
    _pending[key] = task

    def done(completed):
        _pending.pop(key, None)
        if not completed.cancelled():
            error = completed.exception()
            if error is not None:
                logger.error("Не удалось обработать эпизод API-приманки",
                             exc_info=(type(error), error, error.__traceback__))

    task.add_done_callback(done)
