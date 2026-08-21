"""Реестр подключений пространства: учёт того, что подключено, в одном месте.

Раньше ответа на вопрос «что подключено у этой компании» не было ни на одном
экране. Записи вели двое — Ядро своими источниками, Координатор своей таблицей, —
а сводная витрина собиралась опросом приложений в момент показа. Отсюда три
следствия, каждое из которых видел администратор:

* приложение не ответило — и подключений «нет»;
* интеграция, настроенная переменными окружения, не показывалась вовсе, потому
  что приложение о ней не рассказывало;
* одна и та же внешняя система приходила двумя строками без сопоставления.

Здесь ведётся УЧЁТ, а не транспорт. Владелец подключения не меняется: приложение
как ходило в свою внешнюю систему, так и ходит, — оно лишь сообщает, что у него
есть и как оно себя чувствует. Настройки и секреты остаются у него.

Регистрация идемпотентна по тройке «компания + приложение + идентификатор у
владельца»: повторный доклад — штатный режим, приложение сообщает о себе при
каждом изменении и периодически.

Полнота доклада — ответственность владельца. Мы не удаляем записи, о которых
приложение перестало сообщать: молчание значит «не смог рассказать» так же часто,
как «больше нет», а разница между ними видна по `reported_at`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SpaceConnection

log = logging.getLogger("clearledger.connections")

DIRECTIONS = ("in", "out", "both")
INITIATORS = ("us", "them")
STATUSES = ("active", "disabled", "error", "draft")
ENGAGEMENT_MODES = ("own", "coordinate", "enrich")
# После этого срока молчания запись показывается как устаревшая: приложение о ней
# больше не докладывает, и верить её состоянию нельзя.
STALE_AFTER = timedelta(days=1)


def _pick(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else fallback


async def report(db: AsyncSession, company_id: uuid.UUID, app_code: str,
                 items: list[dict[str, Any]]) -> dict[str, int]:
    """Принять доклад приложения о своих подключениях.

    Возвращает счётчики заведённых и обновлённых записей — приложению полезно
    видеть, что доклад дошёл целиком, а не наполовину.
    """
    now = datetime.now(timezone.utc)
    existing = {
        row.external_id: row
        for row in (await db.execute(select(SpaceConnection).where(
            SpaceConnection.company_id == company_id,
            SpaceConnection.app_code == app_code))).scalars().all()
    }
    created = updated = 0
    for item in items:
        external_id = str(item.get("id") or item.get("external_id") or "").strip()
        provider = str(item.get("provider") or "").strip()
        if not external_id or not provider:
            # Без этих двух полей запись не опознать и не сопоставить с прошлым
            # докладом. Молча пропускаем одну строку, а не рушим весь доклад:
            # остальные подключения компании к ней отношения не имеют.
            continue
        row = existing.get(external_id)
        if row is None:
            row = SpaceConnection(
                company_id=company_id, app_code=app_code, external_id=external_id[:120])
            db.add(row)
            created += 1
        else:
            updated += 1
        row.provider = provider[:40]
        row.kind = str(item.get("kind") or "channel").strip()[:30]
        row.name = str(item.get("name") or "").strip()[:200]
        row.direction = _pick(item.get("direction"), DIRECTIONS, "in")
        row.initiator = _pick(item.get("initiator"), INITIATORS, "us")
        row.engagement_mode = _pick(
            item.get("engagement_mode"), ENGAGEMENT_MODES, "own")
        row.status = _pick(item.get("status"), STATUSES, "draft")
        row.configured = bool(item.get("configured"))
        row.secret_ref = (str(item.get("secret_ref"))[:120]
                          if item.get("secret_ref") else None)
        row.endpoint = (str(item.get("endpoint"))[:500]
                        if item.get("endpoint") else None)
        row.last_error = (str(item.get("last_error"))[:500]
                          if item.get("last_error") else None)
        last_sync = item.get("last_sync_at")
        row.last_sync_at = _as_time(last_sync) if last_sync else row.last_sync_at
        row.reported_at = now
    return {"created": created, "updated": updated}


def _as_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def entry(row: SpaceConnection, now: datetime | None = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    return {
        "id": str(row.id),
        "app": row.app_code,
        "external_id": row.external_id,
        "provider": row.provider,
        "kind": row.kind,
        "name": row.name or row.provider,
        "direction": row.direction,
        "initiator": row.initiator,
        "engagement_mode": row.engagement_mode,
        "status": row.status,
        "configured": row.configured,
        "secret_ref": row.secret_ref,
        "endpoint": row.endpoint,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_error": row.last_error,
        "reported_at": row.reported_at.isoformat() if row.reported_at else None,
        # Устаревшая запись — не то же самое, что сломанное подключение. Состояние
        # у неё может быть каким угодно, просто оно давнее.
        "stale": bool(row.reported_at and row.reported_at < moment - STALE_AFTER),
    }


async def listing(db: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Что подключено у компании — одним запросом, без похода в приложения."""
    rows = (await db.execute(select(SpaceConnection).where(
        SpaceConnection.company_id == company_id).order_by(
            SpaceConnection.app_code, SpaceConnection.provider,
            SpaceConnection.name))).scalars().all()
    now = datetime.now(timezone.utc)
    items = [entry(row, now) for row in rows]
    return {
        "connections": items,
        "count": len(items),
        # Разрез «кто к нам стучится» — это вопрос, на который отдельно не
        # отвечал никто: входящие подключения не были сущностью вовсе.
        "inbound": sum(1 for item in items if item["initiator"] == "them"),
        "stale": sum(1 for item in items if item["stale"]),
    }
