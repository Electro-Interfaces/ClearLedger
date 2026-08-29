"""Ограничение частоты обращений к публичным ручкам.

В Ядре его не было вовсе: ни в приложении, ни в nginx стека, ни на кромке. При
этом снаружи без авторизации доступны вход, восстановление пароля, приём
приглашения и публичные ссылки на документ — то есть подбор пароля и перебор
токенов ничем не ограничивались.

Счётчик в памяти процесса, без внешних зависимостей. Это осознанный потолок:
при нескольких воркерах лимит умножается на их число, а после рестарта окно
обнуляется. Для защиты от перебора этого достаточно — она меняет порядок величин
(миллионы попыток превращаются в сотни), — а точный распределённый счётчик
потребовал бы Redis, которого в стеке нет. Так же сделано в Поддержке
(`scripts/lib/rate-limiter.js`).

Ключ — «IP + группа ручек», а не IP целиком: вход и публичная ссылка на документ
живут своими окнами, и подбор пароля не должен закрывать человеку доступ к
документу, который ему прислали.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

# Группа → (сколько запросов, за сколько секунд). Пороги выбраны так, чтобы
# человек их не заметил, а перебор упёрся: вход руками — это единицы попыток в
# минуту, а не десятки.
LIMITS: dict[str, tuple[int, int]] = {
    "auth": (10, 60),        # вход, восстановление и сброс пароля
    "invite": (20, 60),      # просмотр и приём приглашения
    "public_doc": (60, 60),  # публичная ссылка на документ и проверка записи
}

# Путь (префикс после /api) → группа. Пусто — ручка не ограничивается.
ROUTES: tuple[tuple[str, str], ...] = (
    ("/api/auth/login", "auth"),
    ("/api/auth/forgot-password", "auth"),
    ("/api/auth/reset-password", "auth"),
    ("/api/auth/register", "auth"),
    ("/api/invitations/accept", "invite"),
    ("/api/doc-share", "public_doc"),
    # Приглашение на встречу: публичная ссылка без учётной записи, и
    # перебор токенов по ней ограничивается так же, как по документу.
    ("/api/invite/", "public_doc"),
    ("/api/showcase", "public_doc"),
)

_hits: dict[str, deque[float]] = defaultdict(deque)
# Когда по этому ключу последний раз писали в журнал безопасности. Отбитых
# запросов в переборе тысячи, а запись нужна одна: она называет факт «по этому
# адресу шёл перебор», а не считает его попытки.
_reported: dict[str, float] = {}
# Потолок словаря: без него длинная атака с меняющихся адресов съедала бы память
# процесса. При переполнении чистим самые старые окна — они всё равно истекли.
_MAX_KEYS = 20_000


def _group(path: str) -> str | None:
    for prefix, group in ROUTES:
        if path.startswith(prefix):
            return group
    return None


def _client_ip(request: Request) -> str:
    # За кромкой стека реальный адрес приходит заголовком; первый в списке —
    # клиент, остальные прокси.
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded.strip():
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "-"


def _prune(now: float) -> None:
    if len(_hits) <= _MAX_KEYS:
        return
    dead = [k for k, v in _hits.items() if not v or now - v[-1] > 3600]
    for k in dead[: len(_hits) - _MAX_KEYS + 1]:
        _hits.pop(k, None)


def check(request: Request) -> tuple[JSONResponse | None, dict[str, object] | None]:
    """Ответ 429, если лимит исчерпан; иначе None и запрос идёт дальше.

    Второй элемент — событие для журнала безопасности: он не пустой только на
    первом отказе в окне. Отбить перебор мало: если его никто не увидел, разбирать
    инцидент будет не по чему.
    """
    group = _group(request.url.path)
    if group is None:
        return None, None

    limit, window = LIMITS[group]
    now = time.monotonic()
    key = f"{_client_ip(request)}|{group}"
    hits = _hits[key]
    while hits and now - hits[0] > window:
        hits.popleft()

    if len(hits) >= limit:
        retry_after = max(1, int(window - (now - hits[0])))
        event = None
        if now - _reported.get(key, 0.0) > window:
            _reported[key] = now
            event = {
                "kind": "rate_limited",
                "scope": group,
                "ip": _client_ip(request)[:64],
                "path": request.url.path[:200],
                "user_agent": (request.headers.get("user-agent") or "")[:300] or None,
                "hits": len(hits),
            }
        return JSONResponse(
            status_code=429,
            content={"detail": "Слишком много попыток. Повторите позже."},
            headers={"Retry-After": str(retry_after)},
        ), event

    hits.append(now)
    _prune(now)
    return None, None
