"""Рынок вокруг сети — API продукта «Маркетинг» (docs/MARKET.md).

Здесь живёт ВНЕШНИЙ мир: чужие станции, торговые центры, парковки, АЗС и наблюдения
по ним (цена, доступность, состояние). Наши объекты сюда не копируются — карта
складывается из двух реестров: `/api/registry/objects` (наше) и этого (чужое).

Волна 0: ручной ввод и наблюдения с мест. Импорт и парсинг придут следующей волной и
лягут в те же таблицы — у каждой записи уже есть происхождение, ранг и срок годности.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import (ChargeSession, MarketObservation, MarketOperator, MarketSite,
                        ServiceLocation, User)
from app.services import market_ocm

router = APIRouter(prefix="/market", tags=["Маркетинг — рынок"])

# Вид точки рынка. Не только ЭЗС (решение МАГа 28.07.2026): торговый центр не конкурент,
# но объясняет спрос и служит кандидатом под размещение.
SITE_KINDS = {"ezs", "mall", "parking", "fuel", "hotel", "office", "other"}
# Ранг источника: чем ближе к первоисточнику, тем выше доверие при конфликте.
SOURCE_RANK = {"partner": 100, "api": 90, "registry": 70, "service_visit": 65,
               "manual": 60, "import": 40, "parser": 20}


class OperatorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    short_name: str | None = Field(default=None, max_length=80)
    relation: str = "competitor"
    site_url: str | None = None
    inn: str | None = None
    notes: str | None = None


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    kind: str = "ezs"
    operator_id: uuid.UUID | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    ports: int | None = None
    max_power_kw: float | None = None
    connectors: str | None = None
    opened_on: str | None = None
    status: str = "active"
    source: str = "manual"
    source_ref: str | None = None
    notes: str | None = None


class ObservationIn(BaseModel):
    site_id: uuid.UUID
    kind: str = "price"
    observed_on: str = Field(min_length=10, max_length=10, description="ISO-дата наблюдения")
    price_value: float | None = None
    price_unit: str | None = None
    price_per_kwh: float | None = None
    basis: str | None = None
    connector_type: str | None = None
    power_kw: float | None = None
    channel: str = "manual"
    source_ref: str | None = None
    snapshot_url: str | None = None
    note: str | None = None


async def _member(company_id: str, user: User, db: AsyncSession) -> uuid.UUID:
    return await assert_company_member(company_id, user, db)


def _dedup_key(kind: str, lat: float | None, lon: float | None, name: str) -> str:
    """Ключ совпадения точек: координата с округлением ~50 м + вид.

    Две карты приносят одну и ту же станцию с разными названиями и в паре десятков
    метров друг от друга. Без ключа рынок за месяц зарастает дублями, и доля считается
    по выдуманному числу чужих портов.
    """
    if lat is not None and lon is not None:
        return f"{kind}:{round(float(lat), 3)}:{round(float(lon), 3)}"
    return f"{kind}:{name.strip().lower()[:80]}"


@router.get("/operators")
async def list_operators(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Операторы рынка со счётчиком точек — «что делает конкурент» начинается отсюда."""
    cid = await _member(company_id, user, db)
    counts = dict((str(oid), int(cnt)) for oid, cnt in (await db.execute(
        select(MarketSite.operator_id, func.count())
        .where(MarketSite.company_id == cid, MarketSite.operator_id.is_not(None))
        .group_by(MarketSite.operator_id)
    )).all())
    rows = (await db.execute(
        select(MarketOperator).where(MarketOperator.company_id == cid)
        .order_by(MarketOperator.name)
    )).scalars().all()
    return {"operators": [{
        "id": str(o.id), "name": o.name, "shortName": o.short_name,
        "relation": o.relation, "siteUrl": o.site_url, "inn": o.inn, "notes": o.notes,
        "sites": counts.get(str(o.id), 0),
    } for o in rows]}


@router.post("/operators", status_code=status.HTTP_201_CREATED)
async def create_operator(
    company_id: str = Query(...), body: OperatorIn = Body(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cid = await _member(company_id, user, db)
    op = MarketOperator(company_id=cid, **body.model_dump())
    db.add(op)
    await db.commit()
    return {"id": str(op.id), "name": op.name}


@router.get("/sites")
async def list_sites(
    company_id: str = Query(...),
    kind: str | None = Query(None, description="ezs|mall|parking|fuel|…"),
    city: str | None = Query(None),
    limit: int = Query(2000, le=5000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Точки рынка для карты и списка — с последней ценой и её возрастом.

    Возраст показываем всегда: цена конкурента без даты выглядит достоверной, а решение
    по ней ошибочно (принцип 2 docs/MARKET.md).
    """
    cid = await _member(company_id, user, db)
    q = select(MarketSite).where(MarketSite.company_id == cid)
    if kind:
        q = q.where(MarketSite.kind == kind)
    if city:
        q = q.where(MarketSite.city == city)
    sites = (await db.execute(q.order_by(MarketSite.name).limit(limit))).scalars().all()

    # Последнее ценовое наблюдение на точку — одним запросом, а не N+1.
    last_price: dict[str, dict[str, Any]] = {}
    if sites:
        ids = [s.id for s in sites]
        rows = (await db.execute(
            select(MarketObservation)
            .where(MarketObservation.site_id.in_(ids), MarketObservation.kind == "price")
            .order_by(MarketObservation.site_id, MarketObservation.observed_on.desc())
        )).scalars().all()
        for o in rows:
            key = str(o.site_id)
            if key not in last_price:
                last_price[key] = {
                    "value": float(o.price_per_kwh or o.price_value or 0) or None,
                    "unit": o.price_unit, "basis": o.basis,
                    "observedOn": o.observed_on, "channel": o.channel,
                    "confidence": o.confidence,
                }

    operators = dict((str(o.id), o.name) for o in (await db.execute(
        select(MarketOperator).where(MarketOperator.company_id == cid))).scalars().all())

    return {"sites": [{
        "id": str(s.id), "kind": s.kind, "name": s.name,
        "operatorId": str(s.operator_id) if s.operator_id else None,
        "operatorName": operators.get(str(s.operator_id)) if s.operator_id else None,
        "address": s.address, "city": s.city, "region": s.region,
        "lat": float(s.latitude) if s.latitude is not None else None,
        "lon": float(s.longitude) if s.longitude is not None else None,
        "ports": s.ports,
        "maxPowerKw": float(s.max_power_kw) if s.max_power_kw is not None else None,
        "connectors": s.connectors, "status": s.status, "openedOn": s.opened_on,
        "isOurs": bool(s.location_id), "locationId": s.location_id,
        "source": s.source, "sourceRank": s.source_rank,
        "lastSeenAt": s.last_seen_at.isoformat() if s.last_seen_at else None,
        "verifiedAt": s.verified_at.isoformat() if s.verified_at else None,
        "price": last_price.get(str(s.id)),
        "notes": s.notes,
    } for s in sites], "total": len(sites)}


@router.post("/sites", status_code=status.HTTP_201_CREATED)
async def create_site(
    company_id: str = Query(...), body: SiteIn = Body(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Завести точку рынка вручную. Дубль по координате не создаём — возвращаем найденную."""
    cid = await _member(company_id, user, db)
    if body.kind not in SITE_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Неизвестный вид точки: {body.kind}")
    key = _dedup_key(body.kind, body.latitude, body.longitude, body.name)
    exists = (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid, MarketSite.dedup_key == key))).scalar_one_or_none()
    if exists is not None:
        return {"id": str(exists.id), "name": exists.name, "duplicate": True}

    now = datetime.now(timezone.utc)
    site = MarketSite(
        company_id=cid, dedup_key=key,
        source_rank=SOURCE_RANK.get(body.source, 50),
        first_seen_at=now, last_seen_at=now,
        **body.model_dump(),
    )
    db.add(site)
    await db.commit()
    return {"id": str(site.id), "name": site.name, "duplicate": False}


@router.patch("/sites/{site_id}")
async def patch_site(
    site_id: uuid.UUID, company_id: str = Query(...), body: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Правка карточки человеком. Помечаем `verified_*`: ручная правка сильнее машинной,
    и следующий импорт её не затирает, а показывает расхождение."""
    cid = await _member(company_id, user, db)
    site = (await db.execute(select(MarketSite).where(
        MarketSite.id == site_id, MarketSite.company_id == cid))).scalar_one_or_none()
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Точка не найдена")
    allowed = {"name", "kind", "operator_id", "address", "city", "region", "latitude",
               "longitude", "ports", "max_power_kw", "connectors", "opened_on",
               "closed_on", "status", "notes", "location_id"}
    for field, value in body.items():
        if field in allowed:
            setattr(site, field, value)
    site.verified_at = datetime.now(timezone.utc)
    site.verified_by = user.id
    site.updated_at = datetime.now(timezone.utc)
    site.dedup_key = _dedup_key(site.kind, site.latitude, site.longitude, site.name)
    await db.commit()
    return {"id": str(site.id), "verifiedAt": site.verified_at.isoformat()}


@router.get("/observations")
async def list_observations(
    company_id: str = Query(...),
    site_id: uuid.UUID | None = Query(None),
    limit: int = Query(200, le=1000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Лента наблюдений — «откуда мы это знаем». По точке или по всей компании."""
    cid = await _member(company_id, user, db)
    q = select(MarketObservation).where(MarketObservation.company_id == cid)
    if site_id:
        q = q.where(MarketObservation.site_id == site_id)
    rows = (await db.execute(
        q.order_by(MarketObservation.observed_on.desc(),
                   MarketObservation.created_at.desc()).limit(limit)
    )).scalars().all()
    names = dict((str(s.id), s.name) for s in (await db.execute(
        select(MarketSite).where(MarketSite.company_id == cid))).scalars().all())
    return {"observations": [{
        "id": str(o.id), "siteId": str(o.site_id), "siteName": names.get(str(o.site_id)),
        "kind": o.kind, "observedOn": o.observed_on,
        "price": float(o.price_value) if o.price_value is not None else None,
        "priceUnit": o.price_unit,
        "pricePerKwh": float(o.price_per_kwh) if o.price_per_kwh is not None else None,
        "basis": o.basis, "connectorType": o.connector_type,
        "powerKw": float(o.power_kw) if o.power_kw is not None else None,
        "channel": o.channel, "confidence": o.confidence, "sourceRef": o.source_ref,
        "snapshotUrl": o.snapshot_url, "author": o.author_name, "note": o.note,
    } for o in rows], "total": len(rows)}


@router.post("/observations", status_code=status.HTTP_201_CREATED)
async def create_observation(
    company_id: str = Query(...), body: ObservationIn = Body(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Записать наблюдение (заезд сервиса, звонок, снимок сайта).

    Автор и канал проставляются здесь, а не приходят из формы: наблюдение ценно тем,
    что известно, чьими глазами оно сделано.
    """
    cid = await _member(company_id, user, db)
    site = (await db.execute(select(MarketSite).where(
        MarketSite.id == body.site_id, MarketSite.company_id == cid))).scalar_one_or_none()
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Точка не найдена")

    obs = MarketObservation(
        company_id=cid, author_id=user.id, author_name=user.name,
        **body.model_dump(),
    )
    db.add(obs)
    # Наблюдение = подтверждение, что точка ещё жива: возраст карточки обновляем здесь,
    # иначе «последний раз видели» показывало бы дату импорта, а не факта.
    site.last_seen_at = datetime.now(timezone.utc)
    if body.kind == "closed":
        site.status = "closed"
        site.closed_on = body.observed_on
    await db.commit()
    return {"id": str(obs.id)}


@router.get("/summary")
async def market_summary(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Сводка рынка для карточки продукта на столе и шапки раздела."""
    cid = await _member(company_id, user, db)
    by_kind = dict((k, int(c)) for k, c in (await db.execute(
        select(MarketSite.kind, func.count())
        .where(MarketSite.company_id == cid, MarketSite.status != "closed")
        .group_by(MarketSite.kind))).all())
    operators = int((await db.execute(
        select(func.count()).select_from(MarketOperator)
        .where(MarketOperator.company_id == cid, MarketOperator.relation == "competitor")
    )).scalar() or 0)
    observations = int((await db.execute(
        select(func.count()).select_from(MarketObservation)
        .where(MarketObservation.company_id == cid))).scalar() or 0)
    last_obs = (await db.execute(
        select(func.max(MarketObservation.observed_on))
        .where(MarketObservation.company_id == cid))).scalar()
    return {
        "byKind": by_kind,
        "competitors": operators,
        "observations": observations,
        "lastObservedOn": last_obs,
    }


# ── Позиция: наш объект в своём окружении ───────────────────────────────────
# Главный экран пилота (docs/MARKET.md §5). Здесь внешние данные встречаются с
# нашими: слева наша выручка и цена, справа — кто стоит рядом и почём заряжает.

# Радиус окружения по умолчанию. Изохрона (10 мин) точнее, но требует внешнего
# маршрутизатора; 5 км по прямой — её рабочее приближение в городе, и оно не врёт
# в ту сторону, где принимается решение (сосед в 5 км конкурент почти всегда).
DEFAULT_RADIUS_KM = 5.0
EARTH_KM = 6371.0


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние по прямой (гаверсинус). PostGIS ради одного радиуса не нужен."""
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_KM * asin(sqrt(a))


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


@router.get("/position")
async def market_position(
    company_id: str = Query(...),
    days: int = Query(30, ge=1, le=365, description="окно наших продаж"),
    radius_km: float = Query(DEFAULT_RADIUS_KM, ge=0.5, le=50),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Наши объекты в окружении рынка: продажи, наша цена, соседи и их цена.

    Одна строка = один наш объект, и в ней сразу оба мира. Смотреть их порознь
    бесполезно: «выручка упала» без соседей не объясняет ничего, а «рядом открылся
    конкурент» без нашей выручки не говорит, важно ли это.
    """
    cid = await _member(company_id, user, db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)

    # ── наши объекты ──
    ours = (await db.execute(
        select(ServiceLocation.id, ServiceLocation.name, ServiceLocation.code,
               ServiceLocation.city, ServiceLocation.latitude, ServiceLocation.longitude)
        .where(ServiceLocation.company_id == cid)
    )).all()

    # ── наши продажи за окно: сессии, энергия, выручка ──
    # Цену считаем только по сессиям с оплатой: у ЮЛ `amount` = 0 (постоплата), и
    # включение их в делимое занижало бы наш тариф вдвое.
    sales_rows = (await db.execute(
        select(ChargeSession.location_id,
               func.count(), func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
               func.coalesce(func.sum(ChargeSession.amount), 0),
               func.coalesce(func.sum(
                   case((ChargeSession.amount > 0, ChargeSession.energy_kwh), else_=0)), 0))
        .where(ChargeSession.company_id == cid, ChargeSession.started_at >= since,
               ChargeSession.location_id.is_not(None))
        .group_by(ChargeSession.location_id)
    )).all()
    sales = {
        str(loc): {
            "sessions": int(cnt), "energyKwh": float(energy or 0),
            "revenue": float(amount or 0),
            "ourPricePerKwh": round(float(amount) / float(paid_energy), 2)
            if paid_energy and float(paid_energy) > 0 else None,
        }
        for loc, cnt, energy, amount, paid_energy in sales_rows
    }

    # ── точки рынка с их последней ценой ──
    market = (await db.execute(
        select(MarketSite).where(
            MarketSite.company_id == cid, MarketSite.status != "closed",
            MarketSite.latitude.is_not(None), MarketSite.longitude.is_not(None))
    )).scalars().all()
    price_rows = (await db.execute(
        select(MarketObservation)
        .where(MarketObservation.company_id == cid, MarketObservation.kind == "price")
        .order_by(MarketObservation.site_id, MarketObservation.observed_on.desc())
    )).scalars().all()
    last_price: dict[str, MarketObservation] = {}
    for o in price_rows:
        last_price.setdefault(str(o.site_id), o)

    rows: list[dict[str, Any]] = []
    for loc_id, name, code, city, lat, lon in ours:
        s = sales.get(str(loc_id), {"sessions": 0, "energyKwh": 0.0, "revenue": 0.0,
                                    "ourPricePerKwh": None})
        neighbours: list[dict[str, Any]] = []
        if lat is not None and lon is not None:
            for m in market:
                # Свои же точки в окружение не считаем: конкурент — это чужой.
                if m.location_id == loc_id:
                    continue
                d = _distance_km(float(lat), float(lon), float(m.latitude), float(m.longitude))
                if d > radius_km:
                    continue
                obs = last_price.get(str(m.id))
                neighbours.append({
                    "id": str(m.id), "name": m.name, "kind": m.kind,
                    "operatorName": None, "distanceKm": round(d, 1),
                    "ports": m.ports,
                    "pricePerKwh": float(obs.price_per_kwh) if obs and obs.price_per_kwh else None,
                    "observedOn": obs.observed_on if obs else None,
                })
        neighbours.sort(key=lambda n: n["distanceKm"])
        rivals = [n for n in neighbours if n["kind"] == "ezs"]
        rival_prices = [n["pricePerKwh"] for n in rivals if n["pricePerKwh"]]
        market_price = _median(rival_prices)
        our_price = s["ourPricePerKwh"]
        rows.append({
            "locationId": str(loc_id), "name": name, "code": code, "city": city,
            "lat": float(lat) if lat is not None else None,
            "lon": float(lon) if lon is not None else None,
            "hasGeo": lat is not None and lon is not None,
            **s,
            "rivals": len(rivals),
            "rivalPorts": sum(n["ports"] or 0 for n in rivals),
            "attractors": len(neighbours) - len(rivals),
            "marketPricePerKwh": market_price,
            # Ценовой индекс: >0 — мы дороже рынка, <0 — дешевле. Пусто, если сравнивать
            # не с чем: выдуманный ноль здесь опаснее пропуска.
            "priceGapPct": round((our_price - market_price) / market_price * 100, 1)
            if our_price and market_price else None,
            "neighbours": neighbours[:8],
        })

    # Наверх — там, где есть с чем сравнивать и где больше денег.
    rows.sort(key=lambda r: (r["marketPricePerKwh"] is None, -r["revenue"]))
    return {"days": days, "radiusKm": radius_km, "objects": rows, "total": len(rows)}


class BulkSiteIn(BaseModel):
    """Строка списка при массовом заведении точек (вставка из таблицы)."""
    name: str
    kind: str = "ezs"
    operator: str | None = None
    address: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    ports: int | None = None
    max_power_kw: float | None = None
    price_per_kwh: float | None = None
    observed_on: str | None = None


@router.post("/sites/bulk")
async def bulk_sites(
    company_id: str = Query(...),
    items: list[BulkSiteIn] = Body(..., embed=True),
    source: str = Query("import"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Завести список точек разом — вставкой из таблицы или выгрузки.

    Волна 0 живёт на ручном вводе, но «одна точка за раз» останавливает работу на
    десятой строке. Дедуп тот же, что при ручном заведении: повторный импорт того же
    списка ничего не портит, а обновляет `last_seen_at`.

    Цена в строке — это сразу наблюдение: без даты и канала она была бы фактом без
    происхождения, а такие в рынок не попадают (принцип 2 docs/MARKET.md).
    """
    cid = await _member(company_id, user, db)
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    # Операторы заводим по имени: в выгрузке они строкой, а не идентификатором.
    known_ops = {(o.name or "").strip().lower(): o.id for o in (await db.execute(
        select(MarketOperator).where(MarketOperator.company_id == cid))).scalars().all()}

    created = updated = observations = 0
    for it in items:
        if it.kind not in SITE_KINDS or not it.name.strip():
            continue
        op_id = None
        if it.operator and it.operator.strip():
            key = it.operator.strip().lower()
            if key not in known_ops:
                op = MarketOperator(company_id=cid, name=it.operator.strip(),
                                    relation="competitor")
                db.add(op)
                await db.flush()
                known_ops[key] = op.id
            op_id = known_ops[key]

        key = _dedup_key(it.kind, it.latitude, it.longitude, it.name)
        site = (await db.execute(select(MarketSite).where(
            MarketSite.company_id == cid, MarketSite.dedup_key == key))).scalar_one_or_none()
        if site is None:
            site = MarketSite(
                company_id=cid, dedup_key=key, kind=it.kind, name=it.name.strip(),
                operator_id=op_id, address=it.address, city=it.city,
                latitude=it.latitude, longitude=it.longitude,
                ports=it.ports, max_power_kw=it.max_power_kw,
                source=source, source_rank=SOURCE_RANK.get(source, 40),
                first_seen_at=now, last_seen_at=now,
            )
            db.add(site)
            await db.flush()
            created += 1
        else:
            # Ручную правку импорт не перетирает — только отмечает, что точка жива.
            site.last_seen_at = now
            if op_id and not site.operator_id:
                site.operator_id = op_id
            updated += 1

        if it.price_per_kwh:
            db.add(MarketObservation(
                company_id=cid, site_id=site.id, kind="price",
                observed_on=it.observed_on or today,
                price_value=it.price_per_kwh, price_unit="kwh",
                price_per_kwh=it.price_per_kwh,
                channel=source, author_id=user.id, author_name=user.name,
            ))
            observations += 1

    await db.commit()
    return {"created": created, "updated": updated, "observations": observations}


# ── Импорт из Open Charge Map ───────────────────────────────────────────────
# Открытый реестр ЭЗС с официальным API (docs/MARKET.md, принцип 6): выше парсинга по
# доверию и единственный источник, где чужие сети отдают себя сами.


@router.get("/ocm/status")
async def ocm_status(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Настроен ли ключ. Интерфейс должен объяснять отсутствие ключа, а не молчать."""
    await _member(company_id, user, db)
    return {"configured": bool(market_ocm.api_key())}


@router.post("/ocm/import")
async def ocm_import(
    company_id: str = Query(...),
    south: float = Query(..., ge=-90, le=90),
    west: float = Query(..., ge=-180, le=180),
    north: float = Query(..., ge=-90, le=90),
    east: float = Query(..., ge=-180, le=180),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Загрузить точки прямоугольника в рынок компании.

    Область задаёт человек (город сети или видимая часть карты), а не «вся страна»:
    рынок нужен там, где у нас есть объекты, а лишние тысячи точек только замедлят
    расчёт окружения и размоют картину.
    """
    cid = await _member(company_id, user, db)
    try:
        return await market_ocm.import_area(
            db, cid, (south, west, north, east), user.id, user.name)
    except RuntimeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/ocm/import-network")
async def ocm_import_network(
    company_id: str = Query(...),
    padding: float = Query(0.15, ge=0.02, le=1.0, description="буфер вокруг наших объектов, °"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Загрузить рынок вокруг ВСЕЙ нашей сети — по кластерам наших объектов.

    Кластеры считаем по городам: у сети ЭЗС объекты стоят гнёздами (Южно-Сахалинск,
    Владивосток, Омск), и один общий прямоугольник на страну притащил бы весь рынок
    России, включая места, где нас нет.
    """
    cid = await _member(company_id, user, db)
    if not market_ocm.api_key():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Не задан OCM_API_KEY — ключ Open Charge Map не настроен в стеке")

    rows = (await db.execute(
        select(ServiceLocation.city,
               func.min(ServiceLocation.latitude), func.max(ServiceLocation.latitude),
               func.min(ServiceLocation.longitude), func.max(ServiceLocation.longitude),
               func.count())
        .where(ServiceLocation.company_id == cid,
               ServiceLocation.latitude.is_not(None), ServiceLocation.city.is_not(None))
        .group_by(ServiceLocation.city)
    )).all()

    total = {"areas": 0, "found": 0, "created": 0, "updated": 0, "prices": 0, "skippedOurs": 0}
    problems: list[str] = []
    for city, min_lat, max_lat, min_lon, max_lon, cnt in rows:
        bbox = (float(min_lat) - padding, float(min_lon) - padding,
                float(max_lat) + padding, float(max_lon) + padding)
        try:
            res = await market_ocm.import_area(db, cid, bbox, user.id, user.name)
        except RuntimeError as e:
            problems.append(f"{city}: {e}")
            continue
        total["areas"] += 1
        for k in ("found", "created", "updated", "prices", "skippedOurs"):
            total[k] += res[k]
    return {**total, "cities": len(rows), "problems": problems}
