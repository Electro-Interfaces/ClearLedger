"""Обзор без общего хранилища: частичные результаты и доверенные ссылки."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, User
from app.services.management_config import Kind, ManagementConfig, OutboundGrant, RemoteSource
from app.services.management_delegation import sign_access
from app.services.management_local import read_local
from app.services.management_schemas import (
    ManagementItem, ManagementOverview, ManagementRecord, ManagementSource,
    SourceIdentity, SourceOverview,
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def calendar_bounds(kind: Kind, date_from: date | None, date_to: date | None,
                    time_zone: str) -> tuple[datetime | None, datetime | None]:
    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "Неизвестный часовой пояс")
    if kind != "calendar":
        return None, None
    if date_from is None or date_to is None or date_to < date_from:
        raise HTTPException(422, "Для календаря нужен корректный период date_from/date_to")
    if (date_to - date_from).days > 366:
        raise HTTPException(422, "Период календаря не должен превышать 367 дней")
    try:
        return (datetime.combine(date_from, time.min, zone).astimezone(timezone.utc),
                datetime.combine(date_to + timedelta(days=1), time.min, zone).astimezone(timezone.utc))
    except OverflowError:
        # Как следующий день после date.max, так и UTC до datetime.min.
        raise HTTPException(422, "Границы периода календаря выходят за допустимый диапазон дат") from None


def make_item(record: ManagementRecord, source: SourceIdentity, base_url: str = "") -> ManagementItem:
    source_id = str(record.source_id)
    params = {"company": source.company_id}
    if record.kind == "chats":
        path = "/"
        params["chat"] = source_id
    else:
        path = "/docs/work"
        params["view"] = "errands" if record.kind == "tasks" else "calendar"
        params["task" if record.kind == "tasks" else "event"] = source_id
    return ManagementItem(**{**record.model_dump(), "source_id": source_id},
                          id=f"{source.code}:{source.company_id}:{record.kind}:{source_id}",
                          source=source, href=f"{base_url}{path}?{urlencode(params)}")


async def fetch_remote(config: ManagementConfig, source: RemoteSource, grant: OutboundGrant,
                       kind: Kind, params: dict, limit: int) -> tuple[list[ManagementItem], ManagementSource]:
    try:
        # httpx ограничивает отдельные операции, это предел вызова целиком.
        async with asyncio.timeout(8):
            return await _fetch_remote(config, source, grant, kind, params, limit)
    except TimeoutError:
        return [], ManagementSource(code=source.code, name=source.name, state="error",
                                     error="Не удалось прочитать источник")


async def _fetch_remote(config: ManagementConfig, source: RemoteSource, grant: OutboundGrant,
                        kind: Kind, params: dict, limit: int) -> tuple[list[ManagementItem], ManagementSource]:
    status = ManagementSource(code=source.code, name=source.name, state="not_configured",
                              error="Подключение источника не настроено")
    if not config.signing_private_key_b64:
        return [], status
    try:
        token = sign_access(config, source, grant, kind)
    except Exception:
        return [], status
    try:
        # Не передаём browser/OAuth cookies, JWT Ядра, API keys или proxy env.
        async with httpx.AsyncClient(timeout=6.0, trust_env=False, follow_redirects=False) as client:
            async with client.stream("GET", source.base_url + "/api/management/source-overview",
                                     params=params, headers={"Authorization": f"Bearer {token}"}) as response:
                if response.status_code in (401, 403):
                    return [], status.model_copy(update={"state": "forbidden", "error": "Источник отказал в доступе"})
                if response.status_code in (404, 503):
                    return [], status
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise ValueError("response too large")
        result = SourceOverview.model_validate_json(raw)
        if len(result.items) > limit or any(r.kind != kind for r in result.items):
            raise ValueError("source contract mismatch")
        if len({r.source_id for r in result.items}) != len(result.items):
            raise ValueError("duplicate source records")
        if result.fetched_at.tzinfo is None or result.fetched_at > now() + timedelta(seconds=60):
            raise ValueError("invalid source clock")
        identity = SourceIdentity(code=source.code, name=source.name,
                                  company_id=str(source.company_id), company_name=source.company_name)
        items = [make_item(r, identity, source.base_url) for r in result.items]
        return items, status.model_copy(update={"state": "ok", "error": None,
                                               "fetched_at": result.fetched_at,
                                               "truncated": result.truncated})
    except Exception:
        # Ни тело ошибки, ни hostname, ни путь к ключу в публичную выдачу не идут.
        return [], status.model_copy(update={"state": "error", "error": "Не удалось прочитать источник"})


def _sort_key(item: ManagementItem):
    moment = item.starts_at if item.kind == "calendar" else item.updated_at
    if moment and moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    value = moment.timestamp() if moment else float("-inf")
    return (value if item.kind == "calendar" else -value, item.id)


async def overview(config: ManagementConfig, db: AsyncSession, user: User, cid: UUID,
                   kind: Kind, space: str, query: str, date_from: date | None,
                   date_to: date | None, time_zone: str, limit: int, *,
                   allow_remote: bool = True) -> ManagementOverview:
    start, end = calendar_bounds(kind, date_from, date_to, time_zone)
    if not config.enabled or not config.hub_enabled:
        return ManagementOverview(enabled=False, fetched_at=now(), items=[], sources=[], truncated=False)
    actor_id = user.id
    # Каталог выдачи тоже приватный: источник без grant не появляется даже ошибкой.
    targets = [(s, g) for s in config.sources for g in s.grants
               if allow_remote and g.local_user_id == actor_id and g.local_company_id == cid and kind in g.kinds]
    allowed_codes = {config.code, *(s.code for s, _ in targets)}
    if space != "all" and space not in allowed_codes:
        raise HTTPException(404, "Пространство не найдено")
    items: list[ManagementItem] = []
    sources: list[ManagementSource] = []
    if space in ("all", config.code):
        status = ManagementSource(code=config.code, name=config.name, state="ok")
        try:
            company = await db.get(Company, cid)
            if company is None:
                raise HTTPException(403, "Компания недоступна")
            identity = SourceIdentity(code=config.code, name=config.name, company_id=str(cid),
                                      company_name=company.short_name or company.name)
            records, truncated = await read_local(db, user, cid, kind, query=query,
                                                  date_from=start, date_to=end, limit=limit)
            items.extend(make_item(record, identity) for record in records)
            status.fetched_at, status.truncated = now(), truncated
        except HTTPException as exc:
            status.state = "forbidden" if exc.status_code in (401, 403, 404) else "error"
            status.error = "Источник отказал в доступе" if status.state == "forbidden" else "Не удалось прочитать источник"
        except Exception:
            status.state, status.error = "error", "Не удалось прочитать источник"
        sources.append(status)
    params = {"kind": kind, "query": query, "limit": limit, "time_zone": time_zone}
    if kind == "calendar":
        params.update(date_from=date_from.isoformat(), date_to=date_to.isoformat())
    responses = await asyncio.gather(*(fetch_remote(config, s, g, kind, params, limit)
                                       for s, g in targets if space in ("all", s.code)))
    for remote_items, status in responses:
        items.extend(remote_items)
        sources.append(status)
    items.sort(key=_sort_key)
    truncated = len(items) > limit or any(s.truncated for s in sources)
    return ManagementOverview(enabled=True, fetched_at=now(), items=items[:limit],
                              sources=sources, truncated=truncated)
