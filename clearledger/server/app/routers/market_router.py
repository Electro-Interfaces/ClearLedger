"""Рынок вокруг сети — API продукта «Маркетинг» (docs/MARKET.md).

Здесь живёт ВНЕШНИЙ мир: чужие станции, торговые центры, парковки, АЗС и наблюдения
по ним (цена, доступность, состояние). Наши объекты сюда не копируются — карта
складывается из двух реестров: `/api/registry/objects` (наше) и этого (чужое).

Волна 0: ручной ввод и наблюдения с мест. Импорт и парсинг придут следующей волной и
лягут в те же таблицы — у каждой записи уже есть происхождение, ранг и срок годности.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import MarketObservation, MarketOperator, MarketSite, User

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
