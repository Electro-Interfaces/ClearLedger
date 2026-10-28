"""Условные запросы: ETag и ответ 304 на неизменившееся чтение.

ЗАЧЕМ. Ни один ответ API не имел ни `ETag`, ни `Cache-Control` (замер 25.10.2026).
Фронт из-за этого перезапрашивает справочники целиком при каждом переходе: за сутки
на rushydro `registry/company-apps` 252 раза, `references/organizations` 252,
`sso/apps` 245, `location-types` 227 — и всё это полными телами. Для карты рынка одно
тело весит 601 КБ уже в сжатом виде.

ЧТО ЭТО ДАЁТ И ЧЕГО НЕ ДАЁТ. Экономится передача и разбор на стороне браузера: при
совпадении `If-None-Match` уходит 304 без тела. Серверное время НЕ экономится — ответ
к этому моменту уже собран; чтобы не собирать, нужен кэш результата на сервере, а это
отдельная работа с инвалидацией. Так что это дешёвый шаг, а не серебряная пуля.

ПОЧЕМУ `private` И `Vary: Authorization`. Ответы API зависят от того, кто спросил, а
браузер кэширует по URL. Без `private` ответ мог бы попасть в общий кэш (прокси), без
`Vary: Authorization` — быть отданным другому пользователю того же браузера. `no-cache`
здесь не значит «не хранить»: он значит «храни, но каждый раз перепроверяй», то есть
ровно то, что нужно для условных запросов.
"""
from __future__ import annotations

import hashlib

from starlette.requests import Request
from starlette.responses import Response

# Тело больше этого не хэшируем: смысл условного запроса — сэкономить передачу, а на
# многомегабайтных выгрузках вычисление хэша само становится заметным. Выгрузки
# (Excel, PDF, файлы) сюда и так не попадают — они не `application/json`.
MAX_BODY_FOR_ETAG = 8 * 1024 * 1024

_CACHE_CONTROL = "private, no-cache"


def _etag(body: bytes) -> str:
    # sha256 усечённый: коллизия здесь означала бы отданный 304 на изменившийся ответ,
    # поэтому берём не crc32 и не md5, но и не весь хэш — 16 байт хватает с запасом.
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def _matches(header: str | None, etag: str) -> bool:
    """`If-None-Match` по RFC 9110: список значений или `*`, слабые метки тоже."""
    if not header:
        return False
    if header.strip() == "*":
        return True
    for raw in header.split(","):
        candidate = raw.strip()
        if candidate.startswith("W/"):
            candidate = candidate[2:]
        if candidate == etag:
            return True
    return False


async def conditional_get(request: Request, call_next):
    """Повесить ETag на чтения и отвечать 304, когда у клиента то же самое."""
    response = await call_next(request)

    if request.method != "GET" or response.status_code != 200:
        return response
    if not response.headers.get("content-type", "").startswith("application/json"):
        return response
    # Чужой ETag не перебиваем: ручка могла выставить его осознанно и дешевле нас.
    if response.headers.get("etag"):
        return response
    # Чужой `Cache-Control` — тем более. Десяток ручек ставит `no-store` намеренно:
    # токены телефонии, ссылки на документы, ответы управляющего пространства, чаты.
    # `no-store` значит «не храни вообще», наш `no-cache` — «храни, но перепроверяй»;
    # подменять первое вторым нельзя, а дописывать второе к первому — мусор в заголовке
    # (85 падений в полном наборе 25.10.2026 были ровно про это). Условный запрос такому
    # ответу и не нужен: клиент, уважающий `no-store`, ничего не хранит и `If-None-Match`
    # не пришлёт.
    if response.headers.get("cache-control"):
        return response

    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is None:
        body = getattr(response, "body", b"") or b""
    else:
        chunks: list[bytes] = []
        size = 0
        async for chunk in body_iterator:
            piece = chunk if isinstance(chunk, bytes) else str(chunk).encode()
            chunks.append(piece)
            size += len(piece)
        body = b"".join(chunks)
        if size > MAX_BODY_FOR_ETAG:
            # Тело уже прочитано — возвращаем как обычный ответ, без метки.
            return Response(content=body, status_code=response.status_code,
                            headers=dict(response.headers),
                            media_type=response.media_type)

    etag = _etag(body)
    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers["ETag"] = etag
    headers["Cache-Control"] = _CACHE_CONTROL
    # Vary дописываем, а не перезаписываем: CORS уже положил туда Origin.
    vary = {v.strip() for v in headers.get("vary", "").split(",") if v.strip()}
    vary.add("Authorization")
    headers["Vary"] = ", ".join(sorted(vary))

    if _matches(request.headers.get("if-none-match"), etag):
        # 304 идёт без тела и без Content-Type: у клиента уже есть то же самое.
        for drop in ("content-type", "Content-Type"):
            headers.pop(drop, None)
        return Response(status_code=304, headers=headers)

    return Response(content=body, status_code=200, headers=headers,
                    media_type=response.media_type)
