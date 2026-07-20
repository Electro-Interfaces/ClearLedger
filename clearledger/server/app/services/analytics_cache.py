"""ОБЩИЙ (в Postgres) TTL-кеш агрегатных ответов раздела «Продажи» ЭЗС с версионной
инвалидацией.

Дашборды (Обзор/Карта/Тарифы/Корпоратив/Частные лица) — чистые чтения тяжёлых
агрегатов по `charge_sessions`. Данные меняются ТОЛЬКО батч-ingest'ом/обогащением,
поэтому кеш инвалидируется не по TTL-угадыванию, а по событию: при загрузке новых
сессий версия компании инкрементируется (`bump_version`), и все её кеш-ключи
(которые содержат версию) устаревают.

⚠ Раньше кеш был per-process (у каждого gunicorn-воркера свой словарь `_STORE`).
Это раздваивало правду: при `-w 2` два воркера могли держать РАЗНЫЕ значения под
одним ключом (если версия не поспевала за данными) и отдавать их по round-robin —
цифры «мигали» при F5 без действий пользователя. Теперь кеш ОБЩИЙ — таблица
`analytics_cache` в Postgres: все воркеры и все заходы видят ОДНО значение для
(компания, версия, запрос). Мигание от рассинхрона воркеров архитектурно невозможно.

Таблица создаётся лениво (`CREATE TABLE IF NOT EXISTS`) — без миграции в models/
database, чтобы не пересекаться с параллельной работой над схемой.
"""
from __future__ import annotations

import functools
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Awaitable, Callable

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import AnalyticsCacheVersion

_DEFAULT_TTL = 900  # 15 мин — fallback поверх версионной инвалидации
_table_ready = False


async def _version(db: AsyncSession, company_id) -> int:
    """Текущая версия данных компании (0 — если ни одной загрузки ещё не было)."""
    v = await db.scalar(
        select(AnalyticsCacheVersion.version).where(AnalyticsCacheVersion.company_id == company_id)
    )
    return int(v or 0)


def _json_default(o: Any) -> Any:
    """Сериализация значений, которые json не умеет: Decimal→float (правило проекта
    NUMERIC→float), даты→ISO."""
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


def _make_key(tag: str, company_id, params: tuple, ver: int, station_stamp: int = 0) -> str:
    """Детерминированный ключ строки-кэша. Версия в ключе → бамп делает прежние
    ключи недостижимыми. station_stamp → переучёт станций (region_id и пр.) тоже
    инвалидирует кэши, зависящие от справочника (регион-разрезы, retail:geo), без
    явного bump в ingest станций. repr стабилен для (args, sorted(kwargs))."""
    raw = f"{tag}|{company_id}|{ver}|{station_stamp}|{params!r}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _station_stamp(db: AsyncSession, company_id) -> int:
    """Отпечаток справочника станций компании: max(updated_at) в секундах.
    Меняется при любом переучёте станций (region_id, статусы) — так кэши, читающие
    станции/регион через join, инвалидируются АВТОМАТИЧЕСКИ, без bump_version в
    stations_normalize. Ошибка/отсутствие таблицы → 0 (кэш всё равно держит версия)."""
    try:
        v = await db.scalar(text(
            "SELECT extract(epoch from max(updated_at))::bigint"
            " FROM service_locations WHERE company_id = :c"
        ), {"c": str(company_id)})
        return int(v or 0)
    except Exception:  # noqa: BLE001
        return 0


async def _ensure_table() -> None:
    """Ленивое создание общей таблицы кэша (раз на процесс)."""
    global _table_ready
    if _table_ready:
        return
    async with async_session_factory() as w:
        await w.execute(text(
            "CREATE TABLE IF NOT EXISTS analytics_cache ("
            " cache_key text PRIMARY KEY,"
            " company_id uuid,"
            " version integer NOT NULL,"
            " payload text NOT NULL,"
            " computed_at timestamptz NOT NULL DEFAULT now())"
        ))
        await w.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_analytics_cache_company_ver"
            " ON analytics_cache (company_id, version)"
        ))
        await w.commit()
    _table_ready = True


async def cached(db: AsyncSession, company_id, tag: str, params: tuple,
                 factory: Callable[[], Awaitable[Any]], ttl: int = _DEFAULT_TTL) -> Any:
    """Вернуть закешированный результат из ОБЩЕГО (в Postgres) кэша или посчитать
    через factory и записать. Ключ включает версию данных компании → загрузка новых
    сессий (bump_version) автоматически делает все прежние ключи недостижимыми."""
    ver = await _version(db, company_id)
    stamp = await _station_stamp(db, company_id)
    key = _make_key(tag, company_id, params, ver, stamp)
    await _ensure_table()
    # Чтение из общего кэша — в сессии запроса (чистый SELECT).
    hit = await db.scalar(
        text("SELECT payload FROM analytics_cache"
             " WHERE cache_key = :k AND computed_at > now() - make_interval(secs => :ttl)"),
        {"k": key, "ttl": ttl},
    )
    if hit is not None:
        try:
            return json.loads(hit)
        except (ValueError, TypeError):
            pass  # битый payload → пересчёт
    value = await factory()
    payload = json.dumps(value, default=_json_default, ensure_ascii=False)
    # Запись — в ОТДЕЛЬНОЙ сессии, чтобы не коммитить транзакцию запроса.
    async with async_session_factory() as w:
        await w.execute(
            text("INSERT INTO analytics_cache (cache_key, company_id, version, payload, computed_at)"
                 " VALUES (:k, :cid, :ver, :p, now())"
                 " ON CONFLICT (cache_key) DO UPDATE SET payload = EXCLUDED.payload,"
                 " computed_at = now(), version = EXCLUDED.version"),
            {"k": key, "cid": str(company_id), "ver": ver, "p": payload},
        )
        await w.commit()
    # Отдаём тот же объект, что положили (без лишнего round-trip через БД).
    return value


def cached_report(tag: str, ttl: int = _DEFAULT_TTL, copy_rows: bool = False):
    """Декоратор на публичный метод сервиса `async def m(self, company_id, *a, **kw)`.

    Кеширует результат по (tag, company_id, позиционные+именованные аргументы,
    версия данных). Авторизация выполняется в роутере ДО вызова метода — кеш её
    не обходит. С общим БД-кэшем каждый hit — свежий json.loads(), поэтому мутация
    не портит кэш; copy_rows оставлен для совместимости интерфейса."""
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
    """Инвалидировать все кеши компании. Вызывать в конце ingest/обогащения сессий
    (после того как данные записаны) — делает собственный commit, чтобы новая версия
    была видна всем воркерам. Ключи со старой версией становятся недостижимы; их
    строки в общем кэше подчищаем, чтобы таблица не пухла."""
    await db.execute(
        pg_insert(AnalyticsCacheVersion)
        .values(company_id=company_id, version=1)
        .on_conflict_do_update(
            index_elements=["company_id"],
            set_={"version": AnalyticsCacheVersion.version + 1},
        )
    )
    await db.commit()
    try:
        await _ensure_table()
        async with async_session_factory() as w:
            await w.execute(
                text("DELETE FROM analytics_cache WHERE company_id = :cid AND version <"
                     " (SELECT version FROM analytics_cache_version WHERE company_id = :cid)"),
                {"cid": str(company_id)},
            )
            await w.commit()
    except Exception:  # noqa: BLE001 — чистка не критична для корректности
        pass
