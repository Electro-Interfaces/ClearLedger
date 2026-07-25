"""Карта пространства — сводка контейнера для анализа и управления.

Классические разделы Центра управления отвечают на вопрос «что настроено»: список
сотрудников, список приложений, журнал событий. Карта отвечает на другой вопрос —
«что здесь вообще происходит»: кто эти люди (свои и внешние), куда каждый допущен,
кто давно не заходил, где активность, а где тишина.

Поэтому здесь агрегаты, а не CRUD: матрица «человек × приложение», признаки
принадлежности, последний вход и счётчик событий на человека. Ничего не меняем —
только читаем, поэтому карта безопасна для наблюдения в любой момент.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (AuditEvent, Company, Counterparty, EzsEquipmentUnit, ServiceLocation,
                        User, UserCompany)
from app.services import app_registry

ACTIVITY_WINDOW_DAYS = 30
RECENT_EVENTS_LIMIT = 40
# «Сейчас в системе»: отметка присутствия обновляется при работе не чаще раза в 2 минуты
# (auth.PRESENCE_TOUCH_SECONDS), поэтому окно берём с запасом — иначе активный человек
# мигал бы между «в сети» и «нет» между обновлениями.
ONLINE_WINDOW_MINUTES = 6


async def space_map(
    db: AsyncSession, company_ids: list[uuid.UUID],
) -> dict[str, Any]:
    """Карта по перечисленным компаниям пространства (одна или все — решает роутер)."""
    since = datetime.now(timezone.utc) - timedelta(days=ACTIVITY_WINDOW_DAYS)
    companies = []
    for cid in company_ids:
        company = await db.get(Company, cid)
        if company is None:
            continue
        companies.append(await _company_map(db, company, since))
    return {
        "windowDays": ACTIVITY_WINDOW_DAYS,
        "companies": companies,
        "recentEvents": await _recent_events(db, company_ids),
    }


async def _company_map(db: AsyncSession, company: Company, since: datetime) -> dict[str, Any]:
    online_since = datetime.now(timezone.utc) - timedelta(minutes=ONLINE_WINDOW_MINUTES)
    apps = await app_registry.company_apps(db, company.id)
    enabled_apps = [a for a in apps if a.get("enabled")]

    rows = (await db.execute(
        select(User, UserCompany, Counterparty)
        .join(UserCompany, UserCompany.user_id == User.id)
        .outerjoin(Counterparty, Counterparty.id == UserCompany.organization_id)
        .where(UserCompany.company_id == company.id)
        .order_by(User.name)
    )).all()

    # События за окно активности — на человека, одним запросом вместо N.
    events = dict((str(uid), cnt) for uid, cnt in (await db.execute(
        select(AuditEvent.user_id, func.count())
        .where(AuditEvent.company_id == company.id, AuditEvent.timestamp >= since)
        .group_by(AuditEvent.user_id)
    )).all())

    people = []
    for user, membership, org in rows:
        allowed = await app_registry.effective_apps(db, company.id, membership.modules)
        # Админ компании и суперадмин допущены всюду — гейт по модулям к ним не применяется.
        full = membership.role == "admin" or user.is_superadmin
        people.append({
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "partyType": getattr(membership, "party_type", None) or "internal",
            "orgName": (org.short_name or org.name) if org is not None else None,
            "role": membership.role,
            "position": membership.position,
            "isSuperadmin": user.is_superadmin,
            "apps": sorted({a["code"] for a in enabled_apps}) if full
                    else sorted({a["code"] for a in enabled_apps if a["code"] in allowed}),
            "fullAccess": full,
            "lastSeenAt": user.last_seen_at.isoformat() if user.last_seen_at else None,
            "online": _is_online(user.last_seen_at, online_since),
            "events": events.get(str(user.id), 0),
        })

    internal = sum(1 for p in people if p["partyType"] == "internal")
    online = sum(1 for p in people if p["online"])
    silent = sum(1 for p in people if p["lastSeenAt"] is None)
    no_access = sum(1 for p in people if not p["apps"])

    return {
        "id": str(company.id),
        "name": company.name,
        "slug": company.slug,
        "apps": [{"code": a["code"], "name": a["name"], "enabled": bool(a.get("enabled"))} for a in apps],
        "people": people,
        "counts": {
            "people": len(people),
            "online": online,
            "internal": internal,
            "partners": len(people) - internal,
            "neverSeen": silent,
            "noAccess": no_access,
            "objects": await _count(db, ServiceLocation, company.id),
            "organizations": await _count(db, Counterparty, company.id),
            "equipment": await _count(db, EzsEquipmentUnit, company.id),
            "events": sum(events.values()),
        },
        "topActions": await _top_actions(db, company.id, since),
    }


def _is_online(seen: datetime | None, threshold: datetime) -> bool:
    """Человек в системе, если отметка присутствия свежее порога."""
    if seen is None:
        return False
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return seen >= threshold


async def _count(db: AsyncSession, model, company_id: uuid.UUID) -> int:
    return int((await db.execute(
        select(func.count()).select_from(model).where(model.company_id == company_id)
    )).scalar() or 0)


async def _top_actions(
    db: AsyncSession, company_id: uuid.UUID, since: datetime,
) -> list[dict[str, Any]]:
    """Чем занимались в компании: топ действий за окно. Показывает характер активности."""
    rows = (await db.execute(
        select(AuditEvent.action, func.count().label("cnt"))
        .where(AuditEvent.company_id == company_id, AuditEvent.timestamp >= since)
        .group_by(AuditEvent.action).order_by(func.count().desc()).limit(8)
    )).all()
    return [{"action": action, "count": int(cnt)} for action, cnt in rows]


async def _recent_events(
    db: AsyncSession, company_ids: list[uuid.UUID],
) -> list[dict[str, Any]]:
    """Свежая лента событий пространства — чтобы видеть происходящее, а не только итоги."""
    if not company_ids:
        return []
    rows = (await db.execute(
        select(AuditEvent, Company.name)
        .join(Company, Company.id == AuditEvent.company_id)
        .where(AuditEvent.company_id.in_(company_ids))
        .order_by(AuditEvent.timestamp.desc()).limit(RECENT_EVENTS_LIMIT)
    )).all()
    out = []
    for ev, company_name in rows:
        out.append({
            "at": ev.timestamp.isoformat() if ev.timestamp else None,
            "company": company_name,
            "userName": ev.user_name,
            "action": ev.action,
            "summary": _event_summary(ev.details),
        })
    return out


def _event_summary(details: str | None) -> str | None:
    """Короткая суть события: детали лежат JSON-строкой, в ленте нужен человекочитаемый след."""
    if not details:
        return None
    try:
        data = json.loads(details)
    except (ValueError, TypeError):
        return details[:120]
    for key in ("objectCode", "objectName", "code", "name", "email", "role", "partyType"):
        if data.get(key):
            return f"{key}: {data[key]}"
    return None
