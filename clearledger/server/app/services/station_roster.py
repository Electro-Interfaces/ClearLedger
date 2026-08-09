"""Снимок профилей и бизнес-политики станции для офлайн-работы Edge.

Экосистемный SSO (RS256 handoff, JWKS) требует связи, а рабочее место станции
обязано пускать человека и при мёртвом канале. Поэтому центр заранее спускает
вниз список профилей, привязанных к станции, с хешами PIN и пароля; агент
кэширует их и проверяет вход локально. Здесь — сборка этого списка и укладка в
очередь edge_downlink (kind="user_roster").

Кого включаем в ростер станции:
  * членов с явным grant station_administrator на эту АЗС;
  * суперадминов платформы — с синтетическим grant этой станции.

Технический admin и объектный скоуп сами по себе права работать с товаром на
станции не дают. Товаровед сети попадает в ростер только если у него
одновременно есть grant администратора этой станции.
Исключаем mail_only (вход невозможен) и тех, у кого нет ни PIN, ни пароля.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..business_access import (
    ROLE_STATION_ADMINISTRATOR,
    SCOPE_STATION,
    has_station_administrator,
    store_policy,
)
from ..models import Company, EdgeAgent, EdgeDownlink, User, UserCompany

ROSTER_KIND = "user_roster"


def _covers(grants: list[dict] | None, station_id: int) -> bool:
    """Есть ли явное бизнес-полномочие администратора этой станции."""
    return has_station_administrator(grants, station_id)


def _effective_grants(
    grants: list[dict] | None, station_id: int, *, is_superadmin: bool
) -> list[dict]:
    result = [dict(grant) for grant in grants or []]
    if is_superadmin and not _covers(result, station_id):
        result.append({
            "role": ROLE_STATION_ADMINISTRATOR,
            "scope_type": SCOPE_STATION,
            "scope_id": str(station_id),
            "synthetic": True,
        })
    return result


async def build_station_roster(
    db: AsyncSession, company_id, station_id: int
) -> list[dict]:
    """Профили администраторов станции и суперадминов платформы."""
    out: list[dict] = []
    seen: set = set()

    def add(user: User, grants: list[dict]) -> None:
        if user.id in seen or user.mail_only:
            return
        if not (user.station_pin_hash or user.password_hash):
            return  # войти нечем — в ростер не берём
        seen.add(user.id)
        out.append(
            {
                "id": str(user.id),
                "login": user.email,
                "name": user.name,
                "role": "station_administrator",
                "grants": grants,
                "pin_hash": user.station_pin_hash or "",
                "pwd_hash": user.password_hash or "",
            }
        )

    rows = (
        await db.execute(
            select(User, UserCompany)
            .outerjoin(
                UserCompany,
                and_(UserCompany.user_id == User.id, UserCompany.company_id == company_id),
            )
            .where(or_(User.is_superadmin.is_(True), UserCompany.company_id == company_id))
        )
    ).all()
    for user, member in rows:
        grants = _effective_grants(
            getattr(member, "business_grants", None), station_id,
            is_superadmin=bool(user.is_superadmin),
        )
        if _covers(grants, station_id):
            # Станционный grant обязателен; сетевой сохраняем, если он есть у
            # того же человека, чтобы профиль отражал объединение его ролей.
            add(user, grants)

    return out


async def enqueue_station_roster(
    db: AsyncSession, company_id, station_id: int
) -> int:
    """Сложить актуальный ростер станции в edge_downlink, сняв прежний ещё не
    доставленный (шлём только свежий список). Коммит — на вызывающей стороне."""
    users = await build_station_roster(db, company_id, station_id)
    stale = (
        await db.execute(
            select(EdgeDownlink).where(
                EdgeDownlink.company_id == company_id,
                EdgeDownlink.station_id == station_id,
                EdgeDownlink.kind == ROSTER_KIND,
                EdgeDownlink.delivered_at.is_(None),
            )
        )
    ).scalars().all()
    for t in stale:
        await db.delete(t)
    company = await db.get(Company, company_id)
    policy = store_policy(company.customization if company else None)
    generated_at = datetime.now(timezone.utc).isoformat()
    db.add(
        EdgeDownlink(
            company_id=company_id,
            station_id=station_id,
            kind=ROSTER_KIND,
            payload={
                "schema_version": 1,
                "revision": generated_at,
                "generated_at": generated_at,
                "policy": policy,
                "users": users,
            },
            note=f"roster:{station_id}",
        )
    )
    return len(users)


async def refresh_company_rosters(db: AsyncSession, company_id) -> int:
    """Освежить ростеры ВСЕХ станций компании (после смены состава или PIN).
    Возвращает число станций, для которых поставлено задание."""
    station_ids = (
        await db.execute(
            select(EdgeAgent.station_id).where(EdgeAgent.company_id == company_id)
        )
    ).scalars().all()
    for sid in station_ids:
        await enqueue_station_roster(db, company_id, sid)
    return len(station_ids)
