"""In-process TTL-кеш агрегатных ответов раздела «Продажи» ЭЗС с версионной
инвалидацией.

Дашборды (Обзор/Карта/Тарифы/Корпоратив/Частные лица) — чистые чтения тяжёлых
агрегатов по `charge_sessions` (≈105k строк). Данные меняются ТОЛЬКО батч-
ingest'ом/обогащением, поэтому кеш инвалидируется не по TTL-угадыванию, а по
событию: при загрузке новых сессий версия компании инкрементируется
(`bump_version`), и все её кеш-ключи (которые содержат версию) устаревают.

Кеш — per-process (у каждого gunicorn-воркера свой словарь); корректность
держит версия, читаемая из БД (общая для всех воркеров). TTL — страховка на
случай, если версию по какой-то ветке не бампнули.
"""
from __future__ import annotations

import functools
import time
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalyticsCacheVersion

# key = (tag, company_id, params, version) → (expires_at, value)
_STORE: dict[tuple, tuple[float, Any]] = {}
_MAX_ENTRIES = 4000
_DEFAULT_TTL = 900  # 15 мин — fallback поверх версионной инвалидации


async def _version(db: AsyncSession, company_id) -> int:
    """Текущая версия данных компании (0 — если ни одной загрузки ещё не было)."""
    v = await db.scalar(
        select(AnalyticsCacheVersion.version).where(AnalyticsCacheVersion.company_id == company_id)
    )
    return int(v or 0)


async def cached(db: AsyncSession, company_id, tag: str, params: tuple,
                 factory: Callable[[], Awaitable[Any]], ttl: int = _DEFAULT_TTL) -> Any:
    """Вернуть закешированный результат или посчитать через factory и закешировать.

    Ключ включает версию данных компании → загрузка новых сессий автоматически
    делает все прежние ключи недостижимыми (bump_version)."""
    ver = await _version(db, company_id)
    key = (tag, str(company_id), params, ver)
    now = time.time()
    hit = _STORE.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]
    value = await factory()
    if len(_STORE) >= _MAX_ENTRIES:
        _STORE.clear()  # простой bound; версия и так инвалидирует старьё
    _STORE[key] = (now + ttl, value)
    return value


def cached_report(tag: str, ttl: int = _DEFAULT_TTL, copy_rows: bool = False):
    """Декоратор на публичный метод сервиса `async def m(self, company_id, *a, **kw)`.

    Кеширует результат по (tag, company_id, позиционные+именованные аргументы,
    версия данных). Авторизация выполняется в роутере ДО вызова метода —
    кеш её не обходит.

    copy_rows=True — метод возвращает список строк-словарей, которые вызывающий
    может МУТИРОВАТЬ (напр. `_accounts` → `_tag_segments` проставляет segment).
    Тогда на каждый hit отдаём поверхностные копии строк, чтобы мутация не
    портила закешированный оригинал (копия дешевле, чем повторный SQL-скан)."""
    def deco(fn: Callable[..., Awaitable[Any]]):
        @functools.wraps(fn)
        async def wrapper(self, company_id, *args, **kwargs):
            params = (args, tuple(sorted(kwargs.items())))
            value = await cached(self.db, company_id, tag, params,
                                 lambda: fn(self, company_id, *args, **kwargs), ttl)
            if copy_rows and isinstance(value, list):
                return [dict(x) if isinstance(x, dict) else x for x in value]
            return value
        return wrapper
    return deco


async def bump_version(db: AsyncSession, company_id) -> None:
    """Инвалидировать все кеши компании. Вызывать в конце ingest/обогащения
    сессий (после того как данные записаны) — делает собственный commit, чтобы
    новая версия была видна всем воркерам."""
    await db.execute(
        pg_insert(AnalyticsCacheVersion)
        .values(company_id=company_id, version=1)
        .on_conflict_do_update(
            index_elements=["company_id"],
            set_={"version": AnalyticsCacheVersion.version + 1},
        )
    )
    await db.commit()
