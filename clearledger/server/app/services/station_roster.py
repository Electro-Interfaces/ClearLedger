"""Ростер профилей станции — офлайн-вход на edge-агенте АЗС.

Экосистемный SSO (RS256 handoff, JWKS) требует связи, а рабочее место станции
обязано пускать человека и при мёртвом канале. Поэтому центр заранее спускает
вниз список профилей, привязанных к станции, с хешами PIN и пароля; агент
кэширует их и проверяет вход локально. Здесь — сборка этого списка и укладка в
очередь edge_downlink (kind="user_roster").

Кого включаем в ростер станции:
  * суперадминов (видят всю сеть);
  * членов компании со скоупом «вся сеть» (object_scope = NULL);
  * членов, у кого станция есть в object_scope.
Исключаем mail_only (вход невозможен) и тех, у кого нет ни PIN, ни пароля.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EdgeAgent, EdgeDownlink, ServiceLocation, User, UserCompany

ROSTER_KIND = "user_roster"


def _covers(object_scope: list | None, loc_id: str | None, is_superadmin: bool) -> bool:
    """Виден ли пользователю объект станции. NULL-скоуп — вся сеть; суперадмин —
    везде. Чистая функция: её и проверяем тестом, мост и запрос тривиальны."""
    if is_superadmin or object_scope is None:
        return True
    return loc_id is not None and loc_id in object_scope


async def _station_location_id(
    db: AsyncSession, company_id, station_id: int
) -> str | None:
    """service_locations.id для int-кода станции. Мост — code == str(station_id)
    или source_bindings[].config.station == station_id. None, если не размечено:
    тогда скоуп по станции не сработает, но «вся сеть» и суперадмины пройдут."""
    target = str(station_id)
    rows = (
        await db.execute(
            select(
                ServiceLocation.id,
                ServiceLocation.code,
                ServiceLocation.source_bindings,
            ).where(ServiceLocation.company_id == company_id)
        )
    ).all()
    for sid, code, bindings in rows:
        if str(code) == target:
            return sid
        for b in bindings or []:
            cfg = (b or {}).get("config") or {}
            if str(cfg.get("station") or "") == target:
                return sid
    return None


async def build_station_roster(
    db: AsyncSession, company_id, station_id: int
) -> list[dict]:
    """Список профилей станции: {id, login, name, role, pin_hash, pwd_hash}."""
    loc_id = await _station_location_id(db, company_id, station_id)
    out: list[dict] = []
    seen: set = set()

    def add(user: User, role: str) -> None:
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
                "role": role,
                "pin_hash": user.station_pin_hash or "",
                "pwd_hash": user.password_hash or "",
            }
        )

    rows = (
        await db.execute(
            select(User, UserCompany)
            .join(UserCompany, UserCompany.user_id == User.id)
            .where(UserCompany.company_id == company_id)
        )
    ).all()
    for user, member in rows:
        if _covers(member.object_scope, loc_id, user.is_superadmin):
            add(user, member.role or user.role or "user")

    # Суперадмины без членства в этой компании тоже входят на любую станцию.
    supers = (
        await db.execute(
            select(User).where(User.is_superadmin.is_(True), User.mail_only.is_(False))
        )
    ).scalars().all()
    for user in supers:
        add(user, "admin")

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
    db.add(
        EdgeDownlink(
            company_id=company_id,
            station_id=station_id,
            kind=ROSTER_KIND,
            payload={"users": users},
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
