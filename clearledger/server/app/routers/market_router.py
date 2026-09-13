"""Рынок вокруг сети — API продукта «Маркетинг» (docs/MARKET.md).

Здесь живёт ВНЕШНИЙ мир: чужие станции, торговые центры, парковки, АЗС и наблюдения
по ним (цена, доступность, состояние). Наши объекты сюда не копируются — карта
складывается из двух реестров: `/api/registry/objects` (наше) и этого (чужое).

Волна 0: ручной ввод и наблюдения с мест. Импорт и парсинг придут следующей волной и
лягут в те же таблицы — у каждой записи уже есть происхождение, ранг и срок годности.
"""
from __future__ import annotations

import uuid
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_ as sa_or, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.services.mapping import canon_city, canon_region
from app.models import (ChargeSession, CorporateClient, EzsSite, MarketGrowthLead,
                        MarketPlayer, MarketRegionStat, MarketShop,
                        MarketObservation, MarketOperator, MarketScenario,
                        MarketScenarioMeasure, MarketSite, MarketSiteSnapshot, Region,
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
    """Компании рынка: у кого сколько точек, почём и какого качества.

    Реестр отвечает на вопрос «кто здесь вообще есть» — и сразу в той рамке, в
    которой сети сравнивают: развёрнутые точки и порты, живые из них, цена, связь,
    репутация. Одно число «точек» без остального сравнивать не позволяет: сеть из
    сорока мёртвых розеток и сеть из десяти работающих DC — не одно и то же.
    """
    cid = await _member(company_id, user, db)
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)

    # Считаем ТОЛЬКО по сетевым точкам: домашняя розетка частника не часть сети
    # оператора, даже если источник приписал её той же строкой.
    agg = {str(oid): {
        "sites": int(sites), "ports": int(ports or 0),
        "alive": int(alive or 0),
        "maxPowerKw": float(power) if power else None,
        "quality": round(float(quality), 1) if quality is not None else None,
        "success": round(float(success), 1) if success is not None else None,
        "rating": round(float(rating), 2) if rating is not None else None,
        "reviews": int(reviews or 0),
    } for oid, sites, ports, alive, power, quality, success, rating, reviews in (
        await db.execute(
            select(MarketSite.operator_id, func.count(),
                   func.sum(MarketSite.ports),
                   func.sum(case((MarketSite.last_session_at >= alive_since, 1), else_=0)),
                   func.max(MarketSite.max_power_kw),
                   func.avg(MarketSite.connection_quality_24h),
                   func.avg(MarketSite.success_charge_pct),
                   func.avg(MarketSite.rating),
                   func.sum(MarketSite.reviews_count))
            .where(MarketSite.company_id == cid,
                   MarketSite.operator_id.is_not(None),
                   MarketSite.site_class != "home",
                   MarketSite.status != "closed")
            .group_by(MarketSite.operator_id))).all()}

    # Цена по оператору — медиана последних сравнимых наблюдений его точек.
    # Одна точка — одна цена, иначе станция, которую чаще импортировали, весит
    # больше соседней (ревизия 12.09.2026, К4).
    last_price = await _last_prices(db, cid)
    site_operator = dict((str(sid), str(oid)) for sid, oid in (await db.execute(
        select(MarketSite.id, MarketSite.operator_id)
        .where(MarketSite.company_id == cid,
               MarketSite.operator_id.is_not(None)))).all())
    prices: dict[str, list[float]] = {}
    for site_id, obs in last_price.items():
        oid = site_operator.get(site_id)
        if oid:
            prices.setdefault(oid, []).append(obs["price"])

    rows = (await db.execute(
        select(MarketOperator).where(MarketOperator.company_id == cid)
        .order_by(MarketOperator.name))).scalars().all()
    operators = [{
        "id": str(o.id), "name": o.name, "shortName": o.short_name,
        "relation": o.relation, "notes": o.notes,
        **_operator_facts(o),
        "medianPricePerKwh": _median(prices.get(str(o.id), [])),
        "pricedSites": len(prices.get(str(o.id), [])),
        **({"sites": 0, "ports": 0, "alive": 0, "maxPowerKw": None, "quality": None,
            "success": None, "rating": None, "reviews": 0} | agg.get(str(o.id), {})),
    } for o in rows]
    operators.sort(key=lambda r: (-r["sites"], r["name"]))
    return {"operators": operators}


def _operator_facts(o: MarketOperator) -> dict[str, Any]:
    """Что мы знаем о компании помимо её точек.

    Собрано исследованием и прежде не доезжало до экрана: чем компания является
    (владелец сети, агрегатор без своих станций, малая сеть), на чьей платформе
    работает, открыта ли роумингом, как называется юридически и с кем говорить.

    Каждое утверждение идёт со своей достоверностью: реквизиты — с пометкой
    источника («подтверждено», «похоже», «не найдено»), модель — с признаком
    ручной проверки, число точек — с числом источников, которые его подтвердили.
    Компания, найденная тремя источниками, и компания из одного упоминания — разной
    надёжности, и по ним нельзя решать одинаково.
    """
    # Реквизиты годятся для ссылки только с пометкой «подтверждено»: бренд и
    # юрлицо часто не совпадают (Electro.Cars — это ООО «ГРИНДИВИЖН»), а
    # однофамильцы в ЕГРЮЛ встречаются постоянно. «Похоже» и «не найдено» — это
    # версия для проверки, и выдавать её за реквизиты компании нельзя.
    trusted = (o.legal_confidence or "").startswith("подтвержд")
    return {
        "class": o.player_class, "classChecked": o.class_checked,
        # 1 — можно ссылаться; 2 — внутренняя оценка; 3 — только сигнал.
        "dataLevel": o.data_level,
        # Имя `cities` занято разрезом по городам в карточке: число и список —
        # разные вещи, и одно перекрывало другое.
        "baseCity": o.base_city, "citiesCount": o.cities, "districts": o.districts,
        # Платформа и роуминг — про технологию, а не про качество сети.
        "platformCode": o.platform_code, "platformOwner": o.platform_owner,
        "ownPlatform": o.own_platform,
        "roaming": o.ocpi_roaming,
        "roamingPct": float(o.ocpi_pct) if o.ocpi_pct is not None else None,
        # Приложение и публичная карточка — два разных отражения компании.
        "appName": o.app_name, "appPackage": o.app_package,
        "appDeveloper": o.app_developer,
        "appRating": float(o.app_rating) if o.app_rating is not None else None,
        "appReviews": o.app_reviews,
        "publicRating": float(o.public_rating) if o.public_rating is not None else None,
        "publicReviews": o.public_reviews, "publicAddress": o.public_address,
        # Реквизиты: показываем всегда, ссылаться можно только на подтверждённые.
        "legalName": o.legal_name, "inn": o.inn, "ogrn": o.ogrn,
        "director": o.director, "legalAddress": o.legal_address,
        "legalStatus": o.legal_status, "legalConfidence": o.legal_confidence,
        # Достоверность приходит формулировкой, а не флагом: «подтверждено сайтом»,
        # «похоже», «сайт не подтверждает бренд», «ИП (не в ЕГРЮЛ)», «не найдено».
        # Ссылаться можно только на подтверждённое, а формулировку показываем как
        # есть — в ней больше смысла, чем в «да/нет».
        "legalTrusted": trusted,
        "phone": o.phone, "siteUrl": o.site_url, "contacts": o.contacts,
        # Сколько точек и чем это подтверждено.
        "pointsTotal": o.points_total, "pointsRegistry": o.points_registry,
        "pointsOsm": o.points_osm, "cardsYandex": o.cards_yandex,
        "sources": o.sources, "sourceCount": o.source_count,
        "alivePct": float(o.alive_pct) if o.alive_pct is not None else None,
        "paidPct": float(o.paid_pct) if o.paid_pct is not None else None,
        "avgPowerKw": float(o.avg_power_kw) if o.avg_power_kw is not None else None,
    }


@router.get("/operators/{operator_id}")
async def operator_card(
    operator_id: uuid.UUID,
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Карточка компании: где стоит, чем оснащена, почём заряжает и как её оценивают.

    Вопрос карточки — «что делает конкурент»: где он растёт, где уходит, держит ли
    цену и не сыплется ли качество. Поэтому здесь регионы, динамика появления точек
    по месяцам и распределение мощностей, а не просто список станций.
    """
    cid = await _member(company_id, user, db)
    op = (await db.execute(select(MarketOperator).where(
        MarketOperator.id == operator_id,
        MarketOperator.company_id == cid))).scalar_one_or_none()
    if op is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оператор не найден")

    sites = (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid,
        MarketSite.operator_id == operator_id))).scalars().all()
    network = [s for s in sites if (s.site_class or "") != "home"]
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)

    by_city: dict[str, int] = {}
    by_power: dict[str, int] = {}
    by_month: dict[str, int] = {}
    for s in network:
        city = s.city or s.region or "город не указан"
        by_city[city] = by_city.get(city, 0) + 1
        power = float(s.max_power_kw) if s.max_power_kw else None
        bucket = ("нет данных" if power is None else "22 кВт и ниже" if power <= 22
                  else "22–60 кВт" if power <= 60 else "60–150 кВт" if power <= 150
                  else "от 150 кВт")
        by_power[bucket] = by_power.get(bucket, 0) + 1
        # Когда точка появилась: дата открытия источника, иначе — когда мы её впервые
        # увидели. Второе слабее, и это честно помечается в подписи экрана.
        when = s.opened_on or (s.first_seen_at.date().isoformat() if s.first_seen_at else None)
        if when:
            by_month[when[:7]] = by_month.get(when[:7], 0) + 1

    last_price = await _last_prices(db, cid)
    prices = [last_price[str(s.id)]["price"] for s in network if str(s.id) in last_price]

    def _avg(values: list[float]) -> float | None:
        clean = [v for v in values if v is not None]
        return round(sum(clean) / len(clean), 1) if clean else None

    return {
        "id": str(op.id), "name": op.name, "relation": op.relation,
        "notes": op.notes,
        **_operator_facts(op),
        "totals": {
            "sites": len(network),
            "homeSockets": len(sites) - len(network),
            "ports": sum(s.ports or 0 for s in network),
            "alive": sum(1 for s in network if s.last_session_at and s.last_session_at >= alive_since),
            "closed": sum(1 for s in network if s.status == "closed"),
            "planned": sum(1 for s in network if s.status == "planned"),
            "medianPricePerKwh": _median(prices),
            "pricedSites": len(prices),
            "quality": _avg([float(s.connection_quality_24h) for s in network
                             if s.connection_quality_24h is not None]),
            "success": _avg([float(s.success_charge_pct) for s in network
                             if s.success_charge_pct is not None]),
            "rating": (round(sum(float(s.rating) for s in network if s.rating is not None)
                             / max(1, sum(1 for s in network if s.rating is not None)), 2)
                       if any(s.rating is not None for s in network) else None),
            "reviews": sum(s.reviews_count or 0 for s in network),
        },
        "cities": sorted(({"name": k, "sites": v} for k, v in by_city.items()),
                         key=lambda r: -r["sites"])[:12],
        "power": sorted(({"bucket": k, "sites": v} for k, v in by_power.items()),
                        key=lambda r: -r["sites"]),
        "months": sorted(({"month": k, "sites": v} for k, v in by_month.items()),
                         key=lambda r: r["month"])[-18:],
        "sites": sorted(({
            "id": str(s.id), "name": s.name, "city": s.city,
            "ports": s.ports, "maxPowerKw": float(s.max_power_kw) if s.max_power_kw else None,
            "currentType": s.current_type, "status": s.status,
            "rating": float(s.rating) if s.rating is not None else None,
            "quality": float(s.connection_quality_24h) if s.connection_quality_24h is not None else None,
            "lastSessionAt": s.last_session_at.isoformat() if s.last_session_at else None,
            "alive": bool(s.last_session_at and s.last_session_at >= alive_since),
        } for s in network), key=lambda r: (r["city"] or "", r["name"]))[:300],
    }


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


# Полная выгрузка — 12 240 точек, и «отдать все» перестало быть ответом: карта и
# реестр берут страницами, а общее число считается запросом, а не длиной страницы
# (ревизия 12.09.2026, К10).
SITES_PAGE_DEFAULT = 2000
SITES_PAGE_MAX = 5000


@router.get("/sites")
async def list_sites(
    company_id: str = Query(...),
    kind: str | None = Query(None, description="ezs|mall|parking|fuel|…"),
    city: str | None = Query(None),
    bbox: str | None = Query(None, description="юг,запад,север,восток — область карты"),
    site_class: str | None = Query(None, description="network|independent|home"),
    current_type: str | None = Query(None, description="DC|AC|LV"),
    operator_id: str | None = Query(None),
    min_power: float | None = Query(None, ge=0),
    alive: bool | None = Query(None, description="заряжали за 90 дней"),
    search: str | None = Query(None, description="имя, город или адрес"),
    limit: int = Query(SITES_PAGE_DEFAULT, le=SITES_PAGE_MAX),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Точки рынка для карты и списка — с последней ценой и её возрастом.

    Возраст показываем всегда: цена конкурента без даты выглядит достоверной, а решение
    по ней ошибочно (принцип 2 docs/MARKET.md).

    Выдача страничная и честная о своём размере: `total` — сколько точек отвечает
    фильтру, `returned` — сколько уместилось на странице. Прежде `total` считался по
    длине уже урезанного списка, и карта с 12 240 точками показывала «5 000 точек»,
    не сообщая, что остальное не доехало (ревизия 12.09.2026, К10).
    """
    cid = await _member(company_id, user, db)
    own_ids = await _own_operator_ids(db, cid)
    q = select(MarketSite).where(MarketSite.company_id == cid)
    if search and search.strip():
        # Искать надо по всей выдаче, а не по первой странице: список показывал
        # 5 000 из 9 118 и отвечал «ничего не найдено» о точке, которая есть в
        # базе, но не доехала до браузера (аудит А10).
        pattern = f"%{search.strip()}%"
        q = q.where(sa_or(MarketSite.name.ilike(pattern),
                          MarketSite.city.ilike(pattern),
                          MarketSite.address.ilike(pattern)))
    if kind:
        q = q.where(MarketSite.kind == kind)
    if city:
        q = q.where(MarketSite.city == city)
    if site_class:
        q = q.where(MarketSite.site_class == site_class)
    if current_type:
        q = q.where(MarketSite.current_type == current_type)
    if operator_id:
        q = q.where(MarketSite.operator_id == operator_id)
    if min_power is not None:
        q = q.where(MarketSite.max_power_kw >= min_power)
    if alive is not None:
        edge = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)
        q = (q.where(MarketSite.last_session_at >= edge) if alive
             else q.where(sa_or(MarketSite.last_session_at.is_(None),
                                MarketSite.last_session_at < edge)))
    if bbox:
        try:
            south, west, north, east = (float(x) for x in bbox.split(","))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Область карты задаётся как «юг,запад,север,восток»")
        q = q.where(MarketSite.latitude.between(south, north),
                    MarketSite.longitude.between(west, east))
    total = int((await db.execute(
        select(func.count()).select_from(q.subquery()))).scalar() or 0)
    sites = (await db.execute(
        q.order_by(MarketSite.name).offset(offset).limit(limit))).scalars().all()

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
                # Ноль — это цена (бесплатно), а не отсутствие цены: прежде `or None`
                # превращал бесплатную станцию в «цена неизвестна» (К2).
                value = o.price_per_kwh if o.price_per_kwh is not None else o.price_value
                last_price[key] = {
                    "value": float(value) if value is not None else None,
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
        "siteClass": s.site_class or "unknown",
        "currentType": s.current_type,
        "lastSessionAt": s.last_session_at.isoformat() if s.last_session_at else None,
        "address": s.address, "city": s.city, "region": s.region,
        "lat": float(s.latitude) if s.latitude is not None else None,
        "lon": float(s.longitude) if s.longitude is not None else None,
        "ports": s.ports,
        "maxPowerKw": float(s.max_power_kw) if s.max_power_kw is not None else None,
        "connectors": s.connectors, "status": s.status, "openedOn": s.opened_on,
        # Наша станция, увиденная снаружи: во внешнем реестре 429 точек
        # РусГидро, и `location_id` у них пуст, как у всех внешних записей.
        # Признак по нему давал «чужая» и красил наши станции красным — на карте
        # выходило, что рядом с нашим объектом стоит конкурент с тем же адресом.
        "isOurs": bool(s.location_id) or s.operator_id in own_ids,
        "locationId": s.location_id,
        "source": s.source, "sourceRank": s.source_rank,
        "lastSeenAt": s.last_seen_at.isoformat() if s.last_seen_at else None,
        "verifiedAt": s.verified_at.isoformat() if s.verified_at else None,
        "price": last_price.get(str(s.id)),
        "notes": s.notes,
        # Паспорт станции: всё, что приехало парсером и до сих пор лежало без дела.
        # Разъёмы с их мощностями, качество связи, успешность зарядок, оценка и
        # отзывы — по этому и выбирают, с кем сравнивать свою станцию.
        "connectorsJson": s.connectors_json, "connectorsTotal": s.connectors_total,
        "quality24h": (float(s.connection_quality_24h)
                       if s.connection_quality_24h is not None else None),
        "successPct": (float(s.success_charge_pct)
                       if s.success_charge_pct is not None else None),
        "rating": float(s.rating) if s.rating is not None else None,
        "reviews": s.reviews_count,
        "closedConfirmations": s.closed_confirmations,
        "isAlive": s.is_alive, "currency": s.currency,
        "externalId": s.external_id, "vendor": s.vendor,
        "firstSeenAt": s.first_seen_at.isoformat() if s.first_seen_at else None,
        # Ссылки на снимки внешние: файлы лежат у источника. Число снимков
        # сохранено отдельно — по нему видно, что фото были, даже если ссылка
        # перестала открываться.
        "photos": s.photos, "photoCount": s.photo_count,
        "photoAuthors": s.photo_authors,
    } for s in sites], "total": total, "returned": len(sites),
        "offset": offset, "limit": limit}


@router.get("/sites/breakdown")
async def sites_breakdown(
    company_id: str = Query(...),
    city: str | None = Query(None),
    region: str | None = Query(None),
    operator_id: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Разрезы рынка по точкам: чем оснащены, живы ли, кто владеет.

    Считается по ВСЕЙ базе, а не по загруженной странице списка: девять тысяч точек
    не помещаются в браузер, и разрез по пятистам строкам — это разрез по первым
    пятистам строкам, а не по рынку.

    Домашние розетки из разрезов исключены: они не предложение рынка. Их число
    возвращается отдельно, чтобы это не выглядело умолчанием.
    """
    cid = await _member(company_id, user, db)
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)
    own_ids = await _own_operator_ids(db, cid)

    q = select(MarketSite).where(MarketSite.company_id == cid,
                                 MarketSite.kind == "ezs")
    if city:
        q = q.where(MarketSite.city == city)
    if region:
        q = q.where(MarketSite.region == region)
    if operator_id:
        q = q.where(MarketSite.operator_id == uuid.UUID(operator_id))
    rows = (await db.execute(q)).scalars().all()

    home = [x for x in rows if (x.site_class or "") == "home"]
    sites = [x for x in rows if (x.site_class or "") != "home"]
    if not sites:
        return {"total": 0, "homeSockets": len(home),
                "message": "точек рынка по этим условиям нет"}

    ops = {o.id: o.name for o in (await db.execute(select(MarketOperator).where(
        MarketOperator.company_id == cid))).scalars().all()}
    last_price = await _last_prices(db, cid)

    def bucket(items: list[Any], key) -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for it in items:
            name = key(it)
            row = out.setdefault(name, {"name": name, "sites": 0, "alive": 0,
                                        "ports": 0, "prices": []})
            row["sites"] += 1
            row["ports"] += it.ports or 0
            if it.last_session_at and it.last_session_at >= alive_since:
                row["alive"] += 1
            price = last_price.get(str(it.id))
            if price:
                row["prices"].append(price["price"])
        result = []
        for row in out.values():
            prices = row.pop("prices")
            result.append({**row, "medianPrice": _median(prices),
                           "pricedSites": len(prices)})
        return sorted(result, key=lambda r: -r["sites"])

    def power_bucket(x: Any) -> str:
        v = x.max_power_kw
        if v is None:
            return "мощность не указана"
        v = float(v)
        return ("до 22 кВт" if v < 22 else "22–50 кВт" if v < 50
                else "50–150 кВт" if v < 150 else "от 150 кВт")

    # ── разъёмы: тип и мощность лежат в JSON каждой точки ──
    # Это то, по чему водитель вообще может к станции подъехать: машина с CCS не
    # заряжается от GB/T, сколько бы киловатт там ни было.
    connectors: dict[str, dict[str, Any]] = {}
    for x in sites:
        for c in (x.connectors_json or []):
            name = (c.get("type") or "не указан").strip() or "не указан"
            row = connectors.setdefault(name, {"name": name, "count": 0, "sites": 0,
                                               "powers": []})
            row["count"] += 1
            row["sites"] += 1
            if c.get("power_kw"):
                row["powers"].append(float(c["power_kw"]))
    connector_rows = []
    for row in connectors.values():
        powers = row.pop("powers")
        connector_rows.append({**row, "medianPowerKw": _median(powers),
                               "withPower": len(powers)})
    connector_rows.sort(key=lambda r: -r["count"])

    # ── качество: заполнено не везде, и покрытие идёт рядом с числом ──
    quality = [float(x.connection_quality_24h) for x in sites
               if x.connection_quality_24h is not None]
    success = [float(x.success_charge_pct) for x in sites
               if x.success_charge_pct is not None]
    ratings = [float(x.rating) for x in sites if x.rating is not None]
    alive = [x for x in sites if x.last_session_at and x.last_session_at >= alive_since]
    silent = [x for x in sites if x.last_session_at is None]

    return {
        "total": len(sites), "homeSockets": len(home),
        "byPower": bucket(sites, power_bucket),
        "byCurrent": bucket(sites, lambda x: x.current_type or "тип тока не указан"),
        "byClass": bucket(sites, lambda x: {
            "network": "сети", "independent": "независимые",
        }.get(x.site_class or "", "класс не определён")),
        "byOperator": bucket([x for x in sites if x.operator_id],
                             lambda x: ops.get(x.operator_id) or "оператор не назван")[:30],
        "byRegion": bucket(sites, lambda x: x.region or "регион не определён")[:30],
        "byConnector": connector_rows,
        "quality": {
            "alive": len(alive), "aliveDays": ALIVE_DAYS,
            "neverSeenCharging": len(silent),
            "withoutOperator": sum(1 for x in sites if not x.operator_id),
            "ourSites": sum(1 for x in sites if x.operator_id in own_ids),
            "medianQuality": _median(quality), "qualityCoverage": len(quality),
            "medianSuccess": _median(success), "successCoverage": len(success),
            "medianRating": _median(ratings), "ratingCoverage": len(ratings),
            "closedConfirmed": sum(1 for x in sites if (x.closed_confirmations or 0) > 0),
        },
        "note": ("разрезы посчитаны по всей базе точек, а не по видимой странице; "
                 "домашние розетки в них не входят и показаны отдельно. Мощность "
                 "известна не у всех точек, качество связи и успешность зарядок — "
                 "тем более: покрытие показано рядом с каждым числом"),
    }


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


# Срок годности ценового наблюдения. Цена конкурента живёт днями: полугодовалая
# «медиана рынка» выглядит достоверно, а решение по ней уже ошибочно (принцип 2
# MARKET.md). Наблюдения старше в сравнение не идут нигде — это одно основание цены
# на весь продукт (ревизия 12.09.2026, К4).
PRICE_TTL_DAYS = 180


async def _last_prices(db: AsyncSession, cid: uuid.UUID) -> dict[str, dict[str, Any]]:
    """Последнее сравнимое ценовое наблюдение по каждой точке: одно на весь продукт.

    Прежде каждый экран отбирал цену по-своему: список операторов брал всю историю
    наблюдений (и точка с частым импортом весила больше), позиция — последнее
    наблюдение без срока годности. Одна функция — один ответ на вопрос «почём здесь
    заряжают», у всех экранов сразу.
    """
    fresh_from = (datetime.now(timezone.utc) - timedelta(days=PRICE_TTL_DAYS)).date().isoformat()
    out: dict[str, dict[str, Any]] = {}
    for obs in (await db.execute(
        select(MarketObservation)
        .where(MarketObservation.company_id == cid, MarketObservation.kind == "price",
               MarketObservation.price_per_kwh.is_not(None),
               MarketObservation.observed_on >= fresh_from)
        .order_by(MarketObservation.site_id, MarketObservation.observed_on.desc(),
                  MarketObservation.created_at.desc(),
                  MarketObservation.id))).scalars():
        # На одну дату у точки бывает несколько наблюдений с разными основаниями
        # (дневной тариф, ночной, клубный) — у 385 точек из 5 792. Прежде брался
        # произвольный порядок строк: от прогона к прогону медиана рынка гуляла
        # между 19,50 и 20,00 без единого нового наблюдения (аудит А09). Выбор
        # закреплён — самое свежее наблюдение, при равенстве дат последнее
        # записанное, — а число конкурирующих вариантов отдаётся рядом, чтобы
        # экран мог сказать «здесь несколько тарифов», а не делать вид, что он один.
        row = out.setdefault(str(obs.site_id), {
            "price": float(obs.price_per_kwh), "observedOn": obs.observed_on,
            "basis": obs.basis, "channel": obs.channel, "variants": 0,
        })
        if obs.observed_on == row["observedOn"]:
            row["variants"] += 1
    return out


# ── Позиция: наш объект в своём окружении ───────────────────────────────────
# Главный экран пилота (docs/MARKET.md §5). Здесь внешние данные встречаются с
# нашими: слева наша выручка и цена, справа — кто стоит рядом и почём заряжает.

# Радиус окружения по умолчанию. Изохрона (10 мин) точнее, но требует внешнего
# маршрутизатора; 5 км по прямой — её рабочее приближение в городе, и оно не врёт
# в ту сторону, где принимается решение (сосед в 5 км конкурент почти всегда).
DEFAULT_RADIUS_KM = 5.0
EARTH_KM = 6371.0
# Сколько дней без единой зарядки делают точку мёртвой. Признак спроса — дата
# последней сессии, а не статус «Работает»: в публичном реестре полно станций со
# связью 100 % и последней зарядкой год назад (docs/MARKET-ROADMAP.md §3.7).
ALIVE_DAYS = 90
# Меньше этого числа сессий в окне замер ничего не доказывает: процент от десятка
# поездок меняется от одной компании друзей, поехавшей на дачу.
MEASURE_MIN_SESSIONS = 30


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние по прямой (гаверсинус). PostGIS ради одного радиуса не нужен."""
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_KM * asin(sqrt(a))


async def _projects_in_work(db: AsyncSession, cid: uuid.UUID,
                           level: str = "city") -> dict[str, dict[str, Any]]:
    """Территории, где «Проекты» уже ведут площадку: ключ — город или регион.

    Нужен там, где продукт предлагает территорию как возможность. Белое пятно, в
    котором идут переговоры по участку, — это не находка, а работа, о которой экран
    не знал: предлагать её заново значит отправлять человека делать сделанное.
    """
    rows = (await db.execute(select(EzsSite).where(
        EzsSite.company_id == cid,
        EzsSite.stage.notin_(["live", "archive", "on_hold"])))).scalars().all()
    out: dict[str, dict[str, Any]] = {}
    for p in rows:
        raw = (p.city if level == "city" else (p.region_norm or p.region)) or ""
        name = (canon_city(raw) if level == "city" else canon_region(raw)) or raw
        key = name.strip().lower()
        if not key:
            continue
        row = out.setdefault(key, {"projects": 0, "stages": {}, "numbers": []})
        row["projects"] += 1
        row["stages"][p.stage] = row["stages"].get(p.stage, 0) + 1
        if p.project_no and len(row["numbers"]) < 5:
            row["numbers"].append(p.project_no)
    return out


def _geo_index(points: list[Any], cell_km: float) -> dict[tuple[int, int], list[Any]]:
    """Разложить точки по клеткам широты и долготы размером примерно `cell_km`.

    Экран «Наши объекты» считался 24 секунды: для каждого из 619 объектов
    перебирались все 9 118 точек рынка — 5,6 млн вычислений расстояния по формуле
    гаверсинуса. Человек в это время смотрел на серые полосы и считал, что
    приложение зависло (замечание МАГа 13.09.2026).

    Клетка — примерно радиус поиска, поэтому достаточно просмотреть соседние: всё,
    что дальше, в радиус не попадёт по построению.
    """
    step = max(cell_km, 0.1) / 111.0        # 1° широты ≈ 111 км
    index: dict[tuple[int, int], list[Any]] = {}
    for p in points:
        if p.latitude is None or p.longitude is None:
            continue
        key = (int(float(p.latitude) // step), int(float(p.longitude) // step))
        index.setdefault(key, []).append(p)
    return index


def _geo_around(index: dict[tuple[int, int], list[Any]], lat: float, lon: float,
                cell_km: float) -> list[Any]:
    """Точки из клеток вокруг координаты — кандидаты, которые ещё надо померить.

    По долготе клетки физически уже, чем по широте, и тем сильнее, чем севернее:
    на широте Мурманска градус долготы вдвое короче градуса широты. Поэтому окно
    по долготе расширяется на косинус широты, иначе у северных объектов часть
    соседей осталась бы за краем просмотра.
    """
    step = max(cell_km, 0.1) / 111.0
    lat_cell, lon_cell = int(lat // step), int(lon // step)
    span = max(1, int(math.ceil(1.0 / max(math.cos(math.radians(lat)), 0.2))))
    out: list[Any] = []
    for dy in (-1, 0, 1):
        for dx in range(-span, span + 1):
            found = index.get((lat_cell + dy, lon_cell + dx))
            if found:
                out.extend(found)
    return out


async def _own_operator_ids(db: AsyncSession, cid: uuid.UUID) -> set[uuid.UUID]:
    """Операторы, которые есть мы сами.

    Внешний реестр знает нас наравне с остальными: 429 точек РусГидро приехали
    выгрузкой вместе с чужими. Пока их не отделить, мы попадаем в собственные
    конкуренты — считаем свою долю против себя, ищем белые пятна там, где уже
    стоим, и берём свои же точки в признак похожести окружения (аудит 13.09.2026,
    А02–А04, А08).
    """
    return set((await db.execute(select(MarketOperator.id).where(
        MarketOperator.company_id == cid, MarketOperator.relation == "own"))).scalars().all())


def _is_external(site: Any, own_ids: set[uuid.UUID]) -> bool:
    """Точка принадлежит рынку, а не нам."""
    return site.operator_id not in own_ids


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
    # Тестовые стенды заказчика («БЦ Гидропроект (Тест)» и подобные) в рыночный
    # анализ не идут: они ничего не продают, но занимают строки и портят покрытие —
    # «посчитано по 7 из 641» становится «из 638», и это честнее.
    ours = (await db.execute(
        select(ServiceLocation.id, ServiceLocation.name, ServiceLocation.code,
               ServiceLocation.city, ServiceLocation.latitude, ServiceLocation.longitude)
        .where(ServiceLocation.company_id == cid,
               ServiceLocation.is_test.is_(False))
    )).all()

    # ── наши продажи за окно: сессии, энергия, выручка ──
    # Цену считаем только по сессиям с оплатой: у ЮЛ `amount` = 0 (постоплата), и
    # включение их в делимое занижало бы наш тариф вдвое.
    sales_rows = (await db.execute(
        select(ChargeSession.location_id,
               func.count(), func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
               func.coalesce(func.sum(func.coalesce(
                   ChargeSession.client_amount, ChargeSession.amount)), 0),
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
    last_price = await _last_prices(db, cid)
    # Кто чей: имя оператора в строке соседа отвечает на «с кем мы тут спорим»,
    # а `relation` отделяет чужую сеть от нашей собственной.
    ops = {o.id: o for o in (await db.execute(select(MarketOperator).where(
        MarketOperator.company_id == cid))).scalars().all()}
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)
    market_index = _geo_index(market, radius_km)

    rows: list[dict[str, Any]] = []
    for loc_id, name, code, city, lat, lon in ours:
        s = sales.get(str(loc_id), {"sessions": 0, "energyKwh": 0.0, "revenue": 0.0,
                                    "ourPricePerKwh": None})
        neighbours: list[dict[str, Any]] = []
        if lat is not None and lon is not None:
            for m in _geo_around(market_index, float(lat), float(lon), radius_km):
                # Свои же точки в окружение не считаем: конкурент — это чужой.
                if m.location_id == loc_id:
                    continue
                d = _distance_km(float(lat), float(lon), float(m.latitude), float(m.longitude))
                if d > radius_km:
                    continue
                obs = last_price.get(str(m.id))
                op = ops.get(m.operator_id) if m.operator_id else None
                last_session = m.last_session_at
                neighbours.append({
                    "id": str(m.id), "name": m.name, "kind": m.kind,
                    "siteClass": m.site_class or "unknown",
                    "operatorName": op.name if op else None,
                    "relation": op.relation if op else None,
                    "distanceKm": round(d, 1),
                    "ports": m.ports,
                    "maxPowerKw": float(m.max_power_kw) if m.max_power_kw else None,
                    "pricePerKwh": obs["price"] if obs else None,
                    "observedOn": obs["observedOn"] if obs else None,
                    "lastSessionAt": last_session.isoformat() if last_session else None,
                    "alive": bool(last_session and last_session >= alive_since),
                })
        neighbours.sort(key=lambda n: n["distanceKm"])
        # Конкурент — чужая СЕТЕВАЯ зарядка. Домашняя розетка частника рядом с нашей
        # станцией конкуренции не создаёт, а в реестре их половина: посчитав их, мы
        # получили бы «плотный рынок» там, где его нет.
        rivals = [n for n in neighbours
                  if n["kind"] == "ezs" and n["siteClass"] != "home"
                  and n["relation"] != "own"]
        rival_prices = [n["pricePerKwh"] for n in rivals if n["pricePerKwh"] is not None]
        market_price = _median(rival_prices)
        our_price = s["ourPricePerKwh"]
        rows.append({
            "locationId": str(loc_id), "name": name, "code": code, "city": city,
            "lat": float(lat) if lat is not None else None,
            "lon": float(lon) if lon is not None else None,
            "hasGeo": lat is not None and lon is not None,
            **s,
            "rivals": len(rivals),
            # Живой конкурент — тот, на котором заряжали за последние 90 дней.
            # Разрыв между «рядом пять станций» и «из них работают две» — это и есть
            # разница между испугом и решением.
            "rivalsAlive": sum(1 for n in rivals if n["alive"]),
            "rivalPorts": sum(n["ports"] or 0 for n in rivals),
            "homeSockets": sum(1 for n in neighbours if n["siteClass"] == "home"),
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


# ── Источники, свежесть и покрытие ──────────────────────────────────────────
# «Конкурентная разведка — задача о свежести, а не о дашборде»: платформу оценивают
# не числом записей, а тем, насколько свежи сигналы и раскладывается ли число до
# первоисточника (docs/MARKET-ROADMAP.md §3.4). Поэтому покрытие полей — такой же
# показатель продукта, как цена: средняя по 19 точкам из 60, выданная за картину
# района, вреднее отсутствия цифры.

@router.get("/sources")
async def market_sources(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Что мы знаем о рынке, откуда и насколько это свежо."""
    cid = await _member(company_id, user, db)

    rows = (await db.execute(
        select(MarketSite.source,
               func.count(),
               func.max(MarketSite.last_seen_at),
               func.count(MarketSite.latitude),
               func.count(MarketSite.max_power_kw),
               func.count(MarketSite.vendor),
               func.count(MarketSite.success_charge_pct),
               func.count(MarketSite.last_session_at),
               func.sum(case((MarketSite.status == "closed", 1), else_=0)),
               func.sum(case((MarketSite.site_class == "home", 1), else_=0)))
        .where(MarketSite.company_id == cid)
        .group_by(MarketSite.source))).all()

    sources = [{
        "source": src or "manual",
        "rank": SOURCE_RANK.get(src or "manual", 50),
        "sites": int(total),
        "lastSeenAt": last_seen.isoformat() if last_seen else None,
        "closed": int(closed or 0),
        "homeSockets": int(home or 0),
        # Покрытие поля: у скольких точек источника оно заполнено. Неравномерность —
        # свойство источника, а не ошибка загрузки, и прятать её нельзя: по полю с
        # покрытием 10 % выводов не делают.
        "coverage": {
            "geo": round(int(geo) / int(total) * 100) if total else 0,
            "power": round(int(power) / int(total) * 100) if total else 0,
            "vendor": round(int(vendor) / int(total) * 100) if total else 0,
            "successPct": round(int(success) / int(total) * 100) if total else 0,
            "lastSession": round(int(session) / int(total) * 100) if total else 0,
        },
    } for src, total, last_seen, geo, power, vendor, success, session, closed, home in rows]
    sources.sort(key=lambda r: -r["sites"])

    snapshots = [{"date": d, "sites": int(c)} for d, c in (await db.execute(
        select(MarketSiteSnapshot.snapshot_date, func.count())
        .where(MarketSiteSnapshot.company_id == cid)
        .group_by(MarketSiteSnapshot.snapshot_date)
        .order_by(MarketSiteSnapshot.snapshot_date.desc()).limit(12))).all()]

    priced = int((await db.execute(
        select(func.count(func.distinct(MarketObservation.site_id)))
        .where(MarketObservation.company_id == cid, MarketObservation.kind == "price",
               MarketObservation.price_per_kwh.is_not(None)))).scalar() or 0)
    conflicts = int((await db.execute(
        select(func.count()).select_from(MarketObservation)
        .where(MarketObservation.company_id == cid,
               MarketObservation.confidence == "conflict"))).scalar() or 0)
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)
    alive = int((await db.execute(
        select(func.count()).select_from(MarketSite)
        .where(MarketSite.company_id == cid,
               MarketSite.last_session_at >= alive_since))).scalar() or 0)

    return {
        "sources": sources, "snapshots": snapshots,
        "totals": {
            "sites": sum(r["sites"] for r in sources), "priced": priced,
            "conflicts": conflicts, "alive": alive, "aliveDays": ALIVE_DAYS,
        },
    }


@router.get("/changes")
async def market_changes(
    company_id: str = Query(...),
    base: str | None = Query(None, description="дата среза-основания (ISO)"),
    current: str | None = Query(None, description="дата свежего среза (ISO)"),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Что изменилось между двумя срезами реестра.

    Ради этого и хранится ряд: чужой реестр истории не отдаёт, и «кто открылся рядом
    за месяц» восстановить потом будет неоткуда.
    """
    cid = await _member(company_id, user, db)
    dates = [d for (d,) in (await db.execute(
        select(MarketSiteSnapshot.snapshot_date)
        .where(MarketSiteSnapshot.company_id == cid)
        .group_by(MarketSiteSnapshot.snapshot_date)
        .order_by(MarketSiteSnapshot.snapshot_date.desc()).limit(24))).all()]
    if not dates:
        return {"base": None, "current": None, "available": [], "counts": {},
                "message": "срезов рынка ещё нет — загрузите выгрузку реестра в «Коннекторах»"}
    cur_date = current or dates[0]
    base_date = base or next((d for d in dates if d < cur_date), None)
    if base_date is None:
        return {"base": None, "current": cur_date, "available": dates, "counts": {},
                "message": "срез пока один — сравнивать не с чем, следующая выгрузка даст сравнение"}

    async def _snap(date: str) -> dict[str, Any]:
        return {str(s.site_id): s for s in (await db.execute(
            select(MarketSiteSnapshot).where(
                MarketSiteSnapshot.company_id == cid,
                MarketSiteSnapshot.snapshot_date == date))).scalars().all()}

    was, fresh_map = await _snap(base_date), await _snap(cur_date)
    ids = {uuid.UUID(i) for i in (set(was) | set(fresh_map))}
    sites = {str(s.id): s for s in (await db.execute(
        select(MarketSite).where(MarketSite.id.in_(ids)))).scalars().all()} if ids else {}

    def _card(site_id: str) -> dict[str, Any]:
        site = sites.get(site_id)
        return {"id": site_id, "name": site.name if site else "—",
                "city": site.city if site else None,
                "siteClass": (site.site_class if site else None) or "unknown"}

    appeared = [_card(i) for i in fresh_map if i not in was]
    gone = [_card(i) for i in was if i not in fresh_map]
    price_moves: list[dict[str, Any]] = []
    quality_drops: list[dict[str, Any]] = []
    for site_id, snap in fresh_map.items():
        old = was.get(site_id)
        if old is None:
            continue
        if (old.price_per_kwh is not None and snap.price_per_kwh is not None
                and float(old.price_per_kwh) != float(snap.price_per_kwh)):
            price_moves.append({**_card(site_id), "was": float(old.price_per_kwh),
                                "now": float(snap.price_per_kwh)})
        # Падение связи на 20 пунктов и больше — уже не шум измерения, а событие:
        # рядом стоящая станция конкурента начала отказывать.
        if (old.connection_quality_24h is not None and snap.connection_quality_24h is not None
                and float(snap.connection_quality_24h) <= float(old.connection_quality_24h) - 20):
            quality_drops.append({**_card(site_id), "was": float(old.connection_quality_24h),
                                  "now": float(snap.connection_quality_24h)})
    return {
        "base": base_date, "current": cur_date, "available": dates,
        # Переход от частичной выгрузки к полной даёт 8 126 «появлений»,
        # которые никто не открывал: точки просто впервые попали в наблюдение.
        # Пока охват срезов не сопоставим, это счёт наблюдений, а не стройки
        # (аудит А16).
        "appeared": appeared[:limit], "gone": gone[:limit],
        "priceMoves": sorted(price_moves, key=lambda r: -abs(r["now"] - r["was"]))[:limit],
        "qualityDrops": sorted(quality_drops, key=lambda r: r["now"] - r["was"])[:limit],
        "counts": {"appeared": len(appeared), "gone": len(gone),
                   "priceMoves": len(price_moves), "qualityDrops": len(quality_drops)},
    }


# ── Территория как единица анализа ──────────────────────────────────────────
# Клиент не выбирает нашу станцию против нашей же — он выбирает в радиусе
# (docs/MARKET.md §2). Значит и считать надо по территории: сколько там предложения,
# сколько нашего, какая цена держится.
#
# Единица — ГОРОД (и регион сверху), а не гексагон H3, как предполагал план. Причина
# простая: гексагон нужен, чтобы сравнивать плотность спроса по площади, а данных о
# спросе территории (население, парк ЭМ, трафик) у нас пока нет ни одного. Без них
# гексагон даёт ту же информацию, что город, но в виде, о котором нельзя спросить
# человека. H3 вернётся вместе со статистикой — поле `hex_id` в модели уже есть.

def _territory_rows(sites, ours, sales, prices, alive_since, level: str) -> list[dict]:
    """Свод по территории: наше и чужое в одной строке."""
    buckets: dict[str, dict] = {}

    def bucket(key: str | None) -> dict:
        name = key or "территория не определена"
        if name not in buckets:
            buckets[name] = {"name": name, "ourSites": 0, "ourSessions": 0,
                             "ourRevenue": 0.0, "ourEnergyKwh": 0.0,
                             "rivalSites": 0, "rivalAlive": 0, "rivalPorts": 0,
                             "homeSockets": 0, "prices": []}
        return buckets[name]

    for loc_id, name, city, region in ours:
        row = bucket(region if level == "region" else city)
        row["ourSites"] += 1
        sale = sales.get(str(loc_id))
        if sale:
            row["ourSessions"] += sale["sessions"]
            row["ourRevenue"] += sale["revenue"]
            row["ourEnergyKwh"] += sale["energyKwh"]

    for site in sites:
        row = bucket(site.region if level == "region" else site.city)
        if (site.site_class or "") == "home":
            row["homeSockets"] += 1
            continue
        row["rivalSites"] += 1
        row["rivalPorts"] += site.ports or 0
        if site.last_session_at and site.last_session_at >= alive_since:
            row["rivalAlive"] += 1
        price = prices.get(str(site.id))
        if price is not None:
            row["prices"].append(price)

    rows = []
    for row in buckets.values():
        market_price = _median(row.pop("prices"))
        our_price = (round(row["ourRevenue"] / row["ourEnergyKwh"], 2)
                     if row["ourEnergyKwh"] else None)
        total_sites = row["ourSites"] + row["rivalSites"]
        rows.append({
            **row,
            "marketPricePerKwh": market_price,
            "ourPricePerKwh": our_price,
            # Доля считается по ТОЧКАМ сети, а не по портам: порты у чужих известны
            # не везде, и доля по ним прыгала бы от заполненности поля.
            "sharePct": round(row["ourSites"] / total_sites * 100, 1) if total_sites else None,
            "priceGapPct": (round((our_price - market_price) / market_price * 100, 1)
                            if our_price and market_price else None),
        })
    return rows


@router.get("/territories")
async def market_territories(
    company_id: str = Query(...),
    level: str = Query("city", pattern="^(city|region)$"),
    days: int = Query(90, ge=1, le=365),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Территории: где мы стоим, кто рядом, чья доля и какая цена держится."""
    cid = await _member(company_id, user, db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)

    ours = (await db.execute(
        select(ServiceLocation.id, ServiceLocation.name, ServiceLocation.city,
               ServiceLocation.region_id)
        .where(ServiceLocation.company_id == cid,
               ServiceLocation.is_test.is_(False)))).all()
    # Регион объекта берём строкой из паспорта: справочник регионов у нас по id, а
    # рынок несёт название. Сводить их по id пришлось бы обеим сторонам.
    regions = dict((rid, name) for rid, name in (await db.execute(
        select(Region.id, Region.name).where(Region.company_id == cid))).all())
    ours = [(loc_id, name, city, regions.get(rid)) for loc_id, name, city, rid in ours]

    # `amount` — списание с карты; у юрлица оно нулевое, а реализация лежит в
    # `client_amount`. Карта и «Позиция» перешли на общее правило раньше, а
    # территории остались на `amount` и теряли 533 тыс. ₽ за 90 дней (аудит А05).
    sales_rows = (await db.execute(
        select(ChargeSession.location_id, func.count(),
               func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
               func.coalesce(func.sum(func.coalesce(
                   ChargeSession.client_amount, ChargeSession.amount)), 0))
        .where(ChargeSession.company_id == cid, ChargeSession.started_at >= since,
               ChargeSession.location_id.is_not(None))
        .group_by(ChargeSession.location_id))).all()
    sales = {str(loc): {"sessions": int(cnt), "energyKwh": float(energy or 0),
                        "revenue": float(amount or 0)}
             for loc, cnt, energy, amount in sales_rows}

    # Предложение территории — только действующие чужие ЗАРЯДКИ. Торговый центр и
    # парковка объясняют спрос, но конкуренции не создают; планируемая точка ещё не
    # работает. Прежде считались все не-домашние точки, и доля рынка падала там, где
    # рядом просто много мест притяжения (ревизия 12.09.2026, К3).
    # `location_id` для отсева своих не годится: у внешних точек он пуст всегда,
    # включая наши собственные 429 записей. Отделяет только оператор.
    own_ids = await _own_operator_ids(db, cid)
    sites = [x for x in (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid, MarketSite.status == "active",
        MarketSite.kind == "ezs",
        MarketSite.location_id.is_(None)))).scalars().all()
        if _is_external(x, own_ids)]
    prices = {k: v["price"] for k, v in (await _last_prices(db, cid)).items()}

    rows = _territory_rows(sites, ours, sales, prices, alive_since, level)
    rows.sort(key=lambda r: (-(r["ourSessions"]), -r["rivalSites"]))
    return {"level": level, "days": days, "territories": rows, "total": len(rows)}


@router.get("/whitespots")
async def market_whitespots(
    company_id: str = Query(...),
    level: str = Query("city", pattern="^(city|region)$"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Белые пятна: рынок есть, нас нет.

    Спрос территории считаем не по населению (его у нас нет), а по наблюдаемой
    активности рынка: сколько там точек и на скольких заряжали за 90 дней. Это
    слабее демографической модели и честно об этом говорит, но отвечает на вопрос
    «где вообще ездят на электромобилях» по факту, а не по гипотезе.
    """
    cid = await _member(company_id, user, db)
    reply = await market_territories(company_id=company_id, level=level, days=90,
                                     user=user, db=db)
    spots = [r for r in reply["territories"]
             if r["ourSites"] == 0 and r["rivalSites"] > 0
             and r["name"] != "территория не определена"]
    # Пятно, по которому уже идёт работа, перестаёт быть пятном: это не новая
    # возможность, а площадка в воронке. Убирать её из списка нельзя — рынок вокруг
    # по-прежнему нужен тому, кто ведёт проект, — но и предлагать как находку тоже.
    in_work = await _projects_in_work(db, cid, level=level)
    for row in spots:
        side = canon_city(row["name"]) if level == "city" else canon_region(row["name"])
        work = in_work.get((side or row["name"]).strip().lower())
        row["projectsInWork"] = work["projects"] if work else 0
        row["projectStages"] = work["stages"] if work else {}
        row["projectNumbers"] = work["numbers"] if work else []
    # Наверх — где рынок живой и работа ещё не начата: мёртвые точки не доказывают
    # спрос, а начатое не нуждается в повторной находке.
    spots.sort(key=lambda r: (r["projectsInWork"] > 0, -r["rivalAlive"], -r["rivalSites"]))
    taken = sum(1 for r in spots if r["projectsInWork"])
    return {"level": level, "spots": spots, "total": len(spots),
            "withProject": taken,
            "basis": "спрос оценён по активности рынка (живые точки за 90 дней), "
                     "без данных о населении и парке электромобилей; территории, где "
                     "«Проекты» уже ведут площадку, помечены и уходят вниз списка"}


@router.get("/site-score")
async def market_site_score(
    company_id: str = Query(...),
    lat: float = Query(...), lon: float = Query(...),
    radius_km: float = Query(DEFAULT_RADIUS_KM, ge=0.5, le=50),
    days: int = Query(90, ge=30, le=365),
    place: str = Query("auto", pattern="^(auto|city|highway)$",
                       description="тип размещения: город, трасса или определить самим"),
    speed_class: str = Query("auto", pattern="^(auto|fast|slow)$",
                             description="класс будущей станции: быстрая или медленная"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Паспорт места под новую станцию: кто рядом, что мы там потеряем и сколько
    похожие наши объекты зарабатывают.

    Прогноз — методом аналогов: берём НАШИ объекты, у которых похожее окружение
    (столько же живых конкурентов в радиусе), и показываем их медиану. Он объясним
    и его можно оспорить на совещании — в отличие от регрессии на 619 объектах
    (docs/MARKET-ROADMAP.md §3.2).
    """
    cid = await _member(company_id, user, db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)

    own_ids = await _own_operator_ids(db, cid)
    # Свой объект рядом — это каннибализация, её считает отдельный блок ниже. В
    # признаке «сколько живых конкурентов в радиусе», по которому подбираются
    # аналоги, наши точки давали ложное сходство: из 24 «конкурентов» в примере
    # Владивостока 14 оказались нашими (аудит А08).
    sites = [x for x in (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid, MarketSite.status != "closed",
        MarketSite.latitude.is_not(None), MarketSite.longitude.is_not(None)))).scalars().all()
        if _is_external(x, own_ids)]
    ours = (await db.execute(
        select(ServiceLocation.id, ServiceLocation.name, ServiceLocation.city,
               ServiceLocation.latitude, ServiceLocation.longitude,
               ServiceLocation.location_class, ServiceLocation.speed_class)
        .where(ServiceLocation.company_id == cid,
               ServiceLocation.is_test.is_(False),
               ServiceLocation.latitude.is_not(None)))).all()
    sales_rows = (await db.execute(
        select(ChargeSession.location_id, func.count(),
               func.coalesce(func.sum(func.coalesce(
                   ChargeSession.client_amount, ChargeSession.amount)), 0))
        .where(ChargeSession.company_id == cid, ChargeSession.started_at >= since,
               ChargeSession.location_id.is_not(None))
        .group_by(ChargeSession.location_id))).all()
    sales = {str(loc): {"sessions": int(cnt), "revenue": float(amount or 0)}
             for loc, cnt, amount in sales_rows}
    prices = {k: v["price"] for k, v in (await _last_prices(db, cid)).items()}
    ops = {o.id: o.name for o in (await db.execute(select(MarketOperator).where(
        MarketOperator.company_id == cid))).scalars().all()}

    # Тот же индекс, что и в «Наших объектах»: подбор аналогов вызывает окружение
    # для каждого нашего объекта, и полный перебор рынка на каждый вызов давал
    # двадцать секунд на открытие экрана.
    site_index = _geo_index(sites, radius_km)

    def rivals_around(plat: float, plon: float, skip_location: str | None = None) -> list[dict]:
        out = []
        for site in _geo_around(site_index, plat, plon, radius_km):
            if skip_location and site.location_id == skip_location:
                continue
            if (site.site_class or "") == "home" or site.kind != "ezs":
                continue
            distance = _distance_km(plat, plon, float(site.latitude), float(site.longitude))
            if distance > radius_km:
                continue
            out.append({
                "id": str(site.id), "name": site.name,
                "operatorName": ops.get(site.operator_id) if site.operator_id else None,
                "distanceKm": round(distance, 1), "ports": site.ports,
                "maxPowerKw": float(site.max_power_kw) if site.max_power_kw else None,
                "pricePerKwh": prices.get(str(site.id)),
                "alive": bool(site.last_session_at and site.last_session_at >= alive_since),
            })
        return sorted(out, key=lambda r: r["distanceKm"])

    around = rivals_around(lat, lon)
    alive_rivals = sum(1 for r in around if r["alive"])
    market_price = _median([r["pricePerKwh"] for r in around if r["pricePerKwh"] is not None])

    # Каннибализация: чей кусок мы съедим, если встанем здесь.
    near_ours = sorted(({
        "locationId": str(loc_id), "name": name, "city": city,
        "distanceKm": round(_distance_km(lat, lon, float(olat), float(olon)), 1),
        **sales.get(str(loc_id), {"sessions": 0, "revenue": 0.0}),
    } for loc_id, name, city, olat, olon, _cls, _spd in ours
        if _distance_km(lat, lon, float(olat), float(olon)) <= radius_km),
        key=lambda r: r["distanceKm"])

    # Аналоги: наши объекты с похожим окружением. Похожесть — по числу живых
    # конкурентов рядом: это и есть главный внешний фактор, который мы умеем мерить.
    # Похожесть места: столько же конкурентов рядом И тот же тип размещения (город
    # против трассы) И тот же класс скорости. Одного числа соседей мало: у 408 наших
    # объектов из 641 живых конкурентов ноль, и «аналогом» становилась вся сеть.
    # Тип и скорость известны не у всех — где пусто, признак не применяем, но пишем,
    # по какому набору признаков собрана выборка.
    if place in ("city", "highway"):
        want_class = place
        place_guessed = False
    else:
        # Догадка по окружению: место, вокруг которого у точек рынка есть название
        # населённого пункта, — город; голое окружение — трасса. Грубо, поэтому
        # рядом с числом всегда написано, что тип определён автоматически, и человек
        # может поправить одним селектором.
        near_named = sum(1 for site in sites
                         if site.city and _distance_km(
                             lat, lon, float(site.latitude), float(site.longitude)) <= radius_km)
        want_class = "city" if near_named else "highway"
        place_guessed = True
    # Класс скорости будущей станции: быстрая рядом с медленной — не аналог. Если
    # человек не задал, берём преобладающий у соседей, а где и того нет — не
    # фильтруем, но говорим об этом в подписи метода (ревизия 12.09.2026, К8).
    want_speed = speed_class if speed_class != "auto" else None

    analogues = []
    zero_demand = 0
    for loc_id, name, city, olat, olon, loc_class, speed in ours:
        sale = sales.get(str(loc_id))
        if want_class and loc_class and loc_class != want_class:
            continue
        if want_speed and speed and speed != want_speed:
            continue
        near = rivals_around(float(olat), float(olon), str(loc_id))
        rivals_alive = sum(1 for r in near if r["alive"])
        if abs(rivals_alive - alive_rivals) > 1 or abs(len(near) - len(around)) > 2:
            continue
        # Объект без единой сессии — это НЕ отсутствие данных, а настоящий ноль
        # спроса, и выкидывать его значит обещать прогноз только по удачным местам.
        # Считаем его в выборку и отдельно показываем, сколько таких.
        sessions = float(sale["sessions"]) if sale else 0.0
        revenue = float(sale["revenue"]) if sale else 0.0
        if sessions == 0:
            zero_demand += 1
        analogues.append({"locationId": str(loc_id), "name": name, "city": city,
                          "rivals": rivals_alive, "rivalsTotal": len(near),
                          "locationClass": loc_class, "speedClass": speed,
                          "sessions": sessions, "revenue": revenue})
    analogues.sort(key=lambda r: -r["sessions"])

    def _quartile(values: list[float], share: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(len(ordered) * share))]

    # Два числа вместо одного. Ревизия справедливо запретила выкидывать нулевой
    # спрос — прогноз по одним удачным местам обещает больше, чем сеть даёт. Но и
    # медиана по выборке, где большинство молчит, показывает ноль и не помогает
    # решать. Поэтому: медиана РАБОТАЮЩИХ аналогов как ожидание, медиана по всем —
    # как трезвая поправка, и доля молчащих рядом.
    sessions = [float(a["sessions"]) for a in analogues]
    revenues = [float(a["revenue"]) for a in analogues]
    working_sessions = [x for x in sessions if x > 0]
    working_revenues = [float(a["revenue"]) for a in analogues if a["sessions"] > 0]
    sessions_forecast = _median(working_sessions)
    revenue_forecast = _median(working_revenues)

    # ── чего стоит вход: мощность и присоединение по соседним площадкам ──
    # Спрос отвечает «сколько дадут», а решение принимается по «сколько стоит войти».
    # Своих данных о сети в точке у нас нет, но есть опыт соседних площадок в том же
    # регионе: что там со свободной мощностью, во сколько обошлось присоединение и
    # сколько оно заняло. Это не смета, а порядок величин — и так и подписано.
    region_sites = (await db.execute(select(EzsSite).where(
        EzsSite.company_id == cid,
        EzsSite.lat.is_not(None), EzsSite.lon.is_not(None)))).scalars().all()
    nearby_projects = [x for x in region_sites
                       if _distance_km(lat, lon, float(x.lat), float(x.lon)) <= max(radius_km * 6, 60)]
    def _values(rows, field: str) -> list[float]:
        return [float(getattr(x, field)) for x in rows if getattr(x, field)]

    # Поля экономики в «Проектах» заполнены неравномерно: стоимость присоединения
    # известна у 4 % площадок, свободная мощность — у 27 %. Поэтому если рядом
    # значений почти нет, берём опыт всей сети и честно говорим, что это уже не
    # про это место, а про нашу практику вообще.
    MIN_SAMPLES = 3
    scope_label = "по соседним площадкам"
    tp_costs = _values(nearby_projects, "tp_cost")
    if len(tp_costs) < MIN_SAMPLES:
        tp_costs = _values(region_sites, "tp_cost")
        scope_label = "по всем нашим площадкам: рядом таких данных почти нет"
    tp_terms = _values(nearby_projects, "tp_term_months") or _values(region_sites, "tp_term_months")
    free_power = _values(nearby_projects, "free_power_num")
    rents = _values(nearby_projects, "rent_cost_month") or _values(region_sites, "rent_cost_month")
    smr = _values(nearby_projects, "smr_cost") or _values(region_sites, "smr_cost")

    capex = (_median(tp_costs) or 0) + (_median(smr) or 0)
    # Простая окупаемость: во сколько периодов прогнозной выручки обойдётся вход.
    # Без затрат на энергию и обслуживание — поэтому «не раньше чем», а не «через».
    payback_periods = (round(capex / revenue_forecast, 1)
                       if capex and revenue_forecast else None)

    return {
        "point": {"lat": lat, "lon": lon}, "radiusKm": radius_km, "days": days,
        "entry": {
            "projectsNearby": len(nearby_projects),
            "tpCostMedian": _median(tp_costs),
            "tpTermMonthsMedian": _median(tp_terms),
            "freePowerKwtMedian": _median(free_power),
            "rentMonthMedian": _median(rents),
            "smrCostMedian": _median(smr),
            "capexEstimate": capex or None,
            "paybackPeriods": payback_periods,
            # Сколько значений стоит за каждой медианой: две цифры и двадцать —
            # разного веса ответы, и человек должен видеть, какой перед ним.
            "samples": {"tpCost": len(tp_costs), "tpTerm": len(tp_terms),
                        "freePower": len(free_power), "rent": len(rents),
                        "smr": len(smr)},
            "basis": (f"порядок величин {scope_label}, не смета; "
                      f"присоединение посчитано по {len(tp_costs)} значениям, "
                      f"свободная мощность по {len(free_power)}"),
        },
        "rivals": {"total": len(around), "alive": alive_rivals,
                   "ports": sum(r["ports"] or 0 for r in around),
                   "marketPricePerKwh": market_price, "list": around[:20]},
        "cannibalization": {"ourNearby": len(near_ours), "list": near_ours[:10]},
        "placeClass": want_class,
        "placeGuessed": place_guessed,
        "forecast": {
            "method": ("аналоги: наши объекты с тем же окружением, "
                       + ("город" if want_class == "city" else "трасса")
                       + (" (определено автоматически)" if place_guessed else " (задано вами)")
                       + (f", {'быстрые' if want_speed == 'fast' else 'медленные'}"
                          if want_speed else ", любой скорости")),
            # Сколько аналогов не заряжают вовсе: прогноз по одним удачным местам
            # обещает больше, чем сеть даёт в среднем.
            "zeroDemand": zero_demand,
            "analogues": len(analogues),
            "sessionsPerPeriod": sessions_forecast,
            "revenuePerPeriod": revenue_forecast,
            # Разброс важнее одной цифры: половина похожих объектов лежит между
            # этими значениями, и решение принимается по диапазону, а не по точке.
            "sessionsLow": _quartile(working_sessions, 0.25),
            "sessionsHigh": _quartile(working_sessions, 0.75),
            "revenueLow": _quartile(working_revenues, 0.25),
            "revenueHigh": _quartile(working_revenues, 0.75),
            # Поправка на реальность: столько же, но с учётом молчащих объектов.
            "sessionsAllMedian": _median(sessions),
            "revenueAllMedian": _median(revenues),
            "working": len(working_sessions),
            "days": days,
            "sample": analogues[:8],
        },
    }


# ── Цена и позиция ──────────────────────────────────────────────────────────
# Три вопроса тарифа: где мы стоим относительно рынка, что с нами сделал сосед и
# что делает с нами собственная цена. Первые два — про рынок, третий — про нас, но
# без рынка он не читается: рост сессий после снижения цены с тем же успехом
# объясняется сезоном (docs/MARKET-ROADMAP.md §3.3).

POWER_BUCKETS = (
    ("менее 22 кВт", 0.0, 22.0),
    ("22–60 кВт", 22.0, 60.0),
    ("60–150 кВт", 60.0, 150.0),
    ("от 150 кВт", 150.0, 1e6),
)


@router.get("/price-landscape")
async def market_price_landscape(
    company_id: str = Query(...),
    days: int = Query(90, ge=30, le=365),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ценовой ландшафт: почём заряжает рынок по классам мощности и где в нём мы.

    Сравнивать «нашу цену» с «ценой рынка» без класса мощности нельзя: медленная
    AC-зарядка у торгового центра и быстрая DC на трассе — разный товар, и общая
    медиана по ним обеим не значит ничего (принцип 3 MARKET.md).
    """
    cid = await _member(company_id, user, db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)

    sites = {str(s.id): s for s in (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid, MarketSite.status != "closed",
        MarketSite.site_class != "home"))).scalars().all()}
    # Только точки из отобранного списка: прежде общая медиана считалась по более
    # широкому набору наблюдений, чем разложенные по классам мощности (К4).
    last_price = {k: v["price"] for k, v in (await _last_prices(db, cid)).items()
                  if k in sites}

    buckets = []
    for label, low, high in POWER_BUCKETS:
        prices = [price for site_id, price in last_price.items()
                  if (site := sites.get(site_id)) is not None
                  and site.max_power_kw is not None
                  and low <= float(site.max_power_kw) < high]
        ordered = sorted(prices)
        buckets.append({
            "bucket": label, "sites": len(prices),
            "median": _median(prices),
            "low": ordered[int(len(ordered) * 0.25)] if ordered else None,
            "high": ordered[min(len(ordered) - 1, int(len(ordered) * 0.75))] if ordered else None,
        })
    unknown_power = sum(1 for site_id in last_price
                        if (site := sites.get(site_id)) is not None
                        and site.max_power_kw is None)

    # Наша цена — по РОЗНИЧНЫМ сессиям: у юрлица постоплата и `amount` = 0, его
    # энергия в тариф не входит. Прежде знаменатель брал энергию только таких
    # строк, а числитель — выручку всех, включая юрлиц: получалось 19,65 ₽/кВт·ч,
    # не равное ни одному честному разрезу (аудит А06). Теперь обе части считаются
    # по одной выборке, а учётная реализация на всю энергию идёт рядом отдельным
    # числом — это разные величины, и подписаны они по-разному.
    retail = case((ChargeSession.amount > 0, 1), else_=0)
    our = (await db.execute(
        select(func.coalesce(func.sum(case(
                   (ChargeSession.amount > 0, func.coalesce(
                       ChargeSession.client_amount, ChargeSession.amount)), else_=0)), 0),
               func.coalesce(func.sum(
                   case((ChargeSession.amount > 0, ChargeSession.energy_kwh), else_=0)), 0),
               func.coalesce(func.sum(func.coalesce(
                   ChargeSession.client_amount, ChargeSession.amount)), 0),
               func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
               func.coalesce(func.sum(retail), 0), func.count())
        .where(ChargeSession.company_id == cid, ChargeSession.started_at >= since))).one()
    our_price = round(float(our[0]) / float(our[1]), 2) if our[1] and float(our[1]) > 0 else None
    our_realization = (round(float(our[2]) / float(our[3]), 2)
                       if our[3] and float(our[3]) > 0 else None)
    market_all = _median(list(last_price.values()))

    return {
        "days": days, "buckets": buckets,
        "unknownPower": unknown_power,
        "pricedSites": len(last_price),
        "ourPricePerKwh": our_price,
        "ourRealizationPerKwh": our_realization,
        "retailSessions": int(our[4]), "allSessions": int(our[5]),
        "marketMedianPerKwh": market_all,
        "gapPct": (round((our_price - market_all) / market_all * 100, 1)
                   if our_price and market_all else None),
    }


@router.get("/pressure")
async def market_pressure(
    company_id: str = Query(...),
    months: int = Query(24, ge=3, le=60),
    radius_km: float = Query(DEFAULT_RADIUS_KM, ge=0.5, le=50),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Давление конкурента: кто открылся рядом с нашими объектами и что стало с нами.

    Сессии считаются в двух равных окнах — до появления соседа и после. Это ещё не
    разность разностей (для неё нужна контрольная группа, она приходит со
    сценариями), но уже не «мне кажется»: видно, на каких объектах падение совпало
    с appearance соседа, а на каких — нет.
    """
    cid = await _member(company_id, user, db)
    horizon = datetime.now(timezone.utc) - timedelta(days=months * 30)

    ours = (await db.execute(
        select(ServiceLocation.id, ServiceLocation.name, ServiceLocation.city,
               ServiceLocation.latitude, ServiceLocation.longitude)
        .where(ServiceLocation.company_id == cid,
               ServiceLocation.is_test.is_(False),
               ServiceLocation.latitude.is_not(None)))).all()
    window = timedelta(days=90)
    # Окно «после» должно целиком уместиться в прошлом: иначе сравниваются 90 дней
    # до с двумя неделями после, и любой сосед выглядит как обвал на 100 %.
    latest_ok = datetime.now(timezone.utc) - window
    newcomers = [s for s in (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid, MarketSite.site_class != "home",
        MarketSite.kind == "ezs",
        MarketSite.latitude.is_not(None),
        MarketSite.first_seen_at.is_not(None),
        MarketSite.first_seen_at >= horizon,
        MarketSite.first_seen_at <= latest_ok))).scalars().all()]
    # День, в который источник завёл десятки точек разом, — это его загрузка, а не
    # стройка конкурентов. Такие даты из расчёта убираем: иначе весь список
    # «давления» окажется днём, когда мы впервые скачали выгрузку.
    by_day: dict[str, int] = {}
    for site in newcomers:
        day = site.first_seen_at.date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1
    bulk_days = {day for day, count in by_day.items() if count > 15}
    newcomers = [s for s in newcomers
                 if s.first_seen_at.date().isoformat() not in bulk_days]
    ops = {o.id: o.name for o in (await db.execute(select(MarketOperator).where(
        MarketOperator.company_id == cid))).scalars().all()}

    rows = []
    for loc_id, name, city, lat, lon in ours:
        near = [(site, _distance_km(float(lat), float(lon),
                                    float(site.latitude), float(site.longitude)))
                for site in newcomers]
        near = [(site, distance) for site, distance in near if distance <= radius_km]
        if not near:
            continue
        site, distance = min(near, key=lambda pair: pair[0].first_seen_at)
        appeared = site.first_seen_at
        before = (await db.execute(
            select(func.count()).select_from(ChargeSession)
            .where(ChargeSession.company_id == cid, ChargeSession.location_id == loc_id,
                   ChargeSession.started_at >= (appeared - window).replace(tzinfo=None),
                   ChargeSession.started_at < appeared.replace(tzinfo=None)))).scalar() or 0
        after = (await db.execute(
            select(func.count()).select_from(ChargeSession)
            .where(ChargeSession.company_id == cid, ChargeSession.location_id == loc_id,
                   ChargeSession.started_at >= appeared.replace(tzinfo=None),
                   ChargeSession.started_at < (appeared + window).replace(tzinfo=None)))).scalar() or 0
        if not before and not after:
            continue
        rows.append({
            "locationId": str(loc_id), "name": name, "city": city,
            "rivalName": site.name,
            "rivalOperator": ops.get(site.operator_id) if site.operator_id else None,
            "distanceKm": round(distance, 1),
            "appearedOn": appeared.date().isoformat(),
            "sessionsBefore": int(before), "sessionsAfter": int(after),
            "changePct": (round((int(after) - int(before)) / int(before) * 100, 1)
                          if before else None),
            "rivalsNearby": len(near),
        })
    rows.sort(key=lambda r: (r["changePct"] is None, r["changePct"] or 0))
    return {"months": months, "radiusKm": radius_km, "rows": rows, "total": len(rows),
            "bulkDays": sorted(bulk_days),
            "note": "окна по 90 дней до и после появления соседа, оба целиком в "
                    "прошлом; дни массовой загрузки источника из расчёта исключены; "
                    "сезон не снят — для этого нужна контрольная группа сценария"}


@router.get("/elasticity")
async def market_elasticity(
    company_id: str = Query(...),
    weeks: int = Query(52, ge=8, le=156),
    min_change_pct: float = Query(5.0, ge=1.0, le=50.0),
    min_sessions: int = Query(20, ge=1, le=500,
                              description="минимум сессий в неделю, иначе это шум"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Отклик спроса на нашу цену: что было с сессиями после её изменения.

    Считаем по фактической цене оплаченных сессий понедельно. Эластичность — не
    константа продукта: она пересчитывается на каждом замере и отдельно по объектам,
    поэтому здесь возвращается список случаев, а не одно число «эластичность сети».
    """
    cid = await _member(company_id, user, db)
    since = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).replace(tzinfo=None)

    # Цена недели — по розничным сессиям целиком: и деньги, и энергия берутся из
    # одних и тех же строк. Когда числитель считал всю выручку, а знаменатель —
    # энергию только оплаченных строк, неделя с почти полностью корпоративным
    # потреблением давала 2 081 ₽/кВт·ч и «рост цены на 12 216 %» (аудит А07).
    week = func.date_trunc("week", ChargeSession.started_at)
    rows = (await db.execute(
        select(ChargeSession.location_id, week.label("week"), func.count(),
               func.coalesce(func.sum(case(
                   (ChargeSession.amount > 0, func.coalesce(
                       ChargeSession.client_amount, ChargeSession.amount)), else_=0)), 0),
               func.coalesce(func.sum(
                   case((ChargeSession.amount > 0, ChargeSession.energy_kwh), else_=0)), 0))
        .where(ChargeSession.company_id == cid, ChargeSession.started_at >= since,
               ChargeSession.location_id.is_not(None))
        .group_by(ChargeSession.location_id, week)
        .order_by(ChargeSession.location_id, week))).all()

    names = {str(loc_id): name for loc_id, name in (await db.execute(
        select(ServiceLocation.id, ServiceLocation.name)
        .where(ServiceLocation.company_id == cid))).all()}

    series: dict[str, list[dict[str, Any]]] = {}
    for loc_id, week_start, sessions, amount, paid_energy in rows:
        price = (float(amount) / float(paid_energy)) if paid_energy and float(paid_energy) > 0 else None
        series.setdefault(str(loc_id), []).append({
            "week": week_start.date().isoformat(), "sessions": int(sessions), "price": price})

    cases = []
    for loc_id, points in series.items():
        usable = [p for p in points if p["price"]]
        for i in range(1, len(usable)):
            was, now_point = usable[i - 1], usable[i]
            # Недели без розничной цены выброшены, и соседями в списке оказывались
            # недели через месяц друг от друга. Такую пару сравнивать нельзя: между
            # ними менялась не только цена (аудит А07).
            if (date.fromisoformat(now_point["week"])
                    - date.fromisoformat(was["week"])).days != 7:
                continue
            # На объекте с двумя сессиями в неделю «спрос вырос на 900 %» означает,
            # что приехало ещё восемнадцать человек, а не что цена сработала.
            if was["sessions"] < min_sessions or now_point["sessions"] < min_sessions:
                continue
            change = (now_point["price"] - was["price"]) / was["price"] * 100
            if abs(change) < min_change_pct:
                continue
            demand = ((now_point["sessions"] - was["sessions"]) / was["sessions"] * 100
                      if was["sessions"] else None)
            if demand is None:
                continue
            cases.append({
                "locationId": loc_id, "name": names.get(loc_id, "—"),
                "week": now_point["week"],
                "priceWas": round(was["price"], 2), "priceNow": round(now_point["price"], 2),
                "pricePct": round(change, 1),
                "sessionsWas": was["sessions"], "sessionsNow": now_point["sessions"],
                "sessionsPct": round(demand, 1),
                # Эластичность: на сколько процентов изменился спрос на каждый процент
                # цены. Отрицательная — нормальный товар: дороже, значит меньше.
                "elasticity": round(demand / change, 2) if change else None,
            })
    cases.sort(key=lambda r: -abs(r["pricePct"]))
    values = [c["elasticity"] for c in cases if c["elasticity"] is not None]
    return {
        "weeks": weeks, "minChangePct": min_change_pct, "minSessions": min_sessions,
        "cases": cases[:200], "total": len(cases),
        "medianElasticity": _median(values),
        "note": (f"по фактической цене оплаченных сессий, недели тоньше {min_sessions} "
                 "сессий отброшены как шум; сезон и акции не сняты — одиночный случай "
                 "не доказателен, смотреть на распределение"),
    }


# ── Сценарии: гипотеза, действие, замер ─────────────────────────────────────
# Замкнутый цикл, ради которого строится всё остальное. Замер идёт разностью
# разностей: эффект действия — это то, на сколько объекты действия разошлись с
# контрольной группой, а не то, на сколько они изменились сами по себе. Иначе
# продукт приписывает себе сезон (docs/MARKET-ROADMAP.md §3.3).

class ScenarioIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    action_kind: str = "tariff"
    description: str | None = None
    scope: list[str] = Field(default_factory=list)
    control: list[str] = Field(default_factory=list)
    expect: dict[str, Any] | None = None
    cost: float | None = None
    risk: str | None = None
    started_on: str | None = None
    check_on: str | None = None
    status: str = "draft"


async def _sessions_by_location(
    db: AsyncSession, cid: uuid.UUID, locations: list[str],
    date_from: datetime, date_to: datetime,
) -> dict[str, dict[str, float]]:
    """Сессии и выручка по объектам за окно."""
    if not locations:
        return {}
    rows = (await db.execute(
        select(ChargeSession.location_id, func.count(),
               func.coalesce(func.sum(ChargeSession.amount), 0))
        .where(ChargeSession.company_id == cid,
               ChargeSession.location_id.in_(locations),
               ChargeSession.started_at >= date_from.replace(tzinfo=None),
               ChargeSession.started_at < date_to.replace(tzinfo=None))
        .group_by(ChargeSession.location_id))).all()
    return {str(loc): {"sessions": float(cnt), "revenue": float(amount or 0)}
            for loc, cnt, amount in rows}


def _sum_of(values: dict[str, dict[str, float]], key: str) -> float:
    return sum(v[key] for v in values.values())


def _pct(before: float, after: float) -> float | None:
    return round((after - before) / before * 100, 1) if before else None


@router.get("/scenarios")
async def list_scenarios(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Сценарии компании с последним замером каждого."""
    cid = await _member(company_id, user, db)
    rows = (await db.execute(select(MarketScenario).where(
        MarketScenario.company_id == cid)
        .order_by(MarketScenario.created_at.desc()))).scalars().all()
    measures: dict[str, MarketScenarioMeasure] = {}
    for m in (await db.execute(select(MarketScenarioMeasure)
                               .where(MarketScenarioMeasure.company_id == cid)
                               .order_by(MarketScenarioMeasure.measured_on.desc()))).scalars():
        measures.setdefault(str(m.scenario_id), m)
    return {"scenarios": [{
        "id": str(r.id), "title": r.title, "actionKind": r.action_kind,
        "description": r.description, "status": r.status,
        "scope": r.scope_json or [], "control": r.control_json or [],
        "expect": r.expect_json or {},
        "cost": float(r.cost) if r.cost is not None else None,
        "risk": r.risk, "startedOn": r.started_on, "checkOn": r.check_on,
        "ownerName": r.owner_name,
        "measure": ({
            "measuredOn": measures[str(r.id)].measured_on,
            "didSessions": (float(measures[str(r.id)].did_sessions)
                            if measures[str(r.id)].did_sessions is not None else None),
            "didRevenue": (float(measures[str(r.id)].did_revenue)
                           if measures[str(r.id)].did_revenue is not None else None),
            "verdict": measures[str(r.id)].verdict,
            "fact": measures[str(r.id)].fact_json or {},
            "note": measures[str(r.id)].note,
        } if str(r.id) in measures else None),
    } for r in rows]}


@router.post("/scenarios", status_code=status.HTTP_201_CREATED)
async def create_scenario(
    company_id: str = Query(...), body: ScenarioIn = Body(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cid = await _member(company_id, user, db)
    row = MarketScenario(
        company_id=cid, title=body.title, action_kind=body.action_kind,
        description=body.description, scope_json=body.scope, control_json=body.control,
        expect_json=body.expect, cost=body.cost, risk=body.risk,
        started_on=body.started_on, check_on=body.check_on, status=body.status,
        owner_user_id=user.id, owner_name=getattr(user, "full_name", None) or user.email)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "title": row.title}


@router.patch("/scenarios/{scenario_id}")
async def patch_scenario(
    scenario_id: uuid.UUID, company_id: str = Query(...), body: dict = Body(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cid = await _member(company_id, user, db)
    row = (await db.execute(select(MarketScenario).where(
        MarketScenario.id == scenario_id,
        MarketScenario.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сценарий не найден")
    fields = {"title": "title", "status": "status", "risk": "risk",
              "description": "description", "startedOn": "started_on",
              "checkOn": "check_on", "actionKind": "action_kind"}
    for key, column in fields.items():
        if key in body:
            setattr(row, column, body[key])
    if "scope" in body:
        row.scope_json = body["scope"]
    if "control" in body:
        row.control_json = body["control"]
    if "expect" in body:
        row.expect_json = body["expect"]
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": str(row.id), "status": row.status}


@router.get("/scenarios/control-suggest")
async def suggest_control(
    company_id: str = Query(...),
    scope: str = Query(..., description="id наших объектов через запятую"),
    radius_km: float = Query(DEFAULT_RADIUS_KM, ge=0.5, le=50),
    weeks: int = Query(8, ge=4, le=26),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Подобрать контрольную группу и проверить, что тренды до вмешательства шли рядом.

    Похожесть — по числу живых конкурентов рядом и по объёму сессий. Проверка
    параллельности обязательна: если до действия группы уже расходились, разность
    разностей ничего не докажет, и честнее сказать это до эксперимента, а не после.
    """
    cid = await _member(company_id, user, db)
    targets = [x.strip() for x in scope.split(",") if x.strip()]
    if not targets:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не выбраны объекты действия")

    now = datetime.now(timezone.utc)
    window = timedelta(weeks=weeks)
    ours = (await db.execute(
        select(ServiceLocation.id, ServiceLocation.name, ServiceLocation.city,
               ServiceLocation.latitude, ServiceLocation.longitude,
               ServiceLocation.location_class)
        .where(ServiceLocation.company_id == cid,
               ServiceLocation.latitude.is_not(None)))).all()
    sites = (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid, MarketSite.status != "closed",
        MarketSite.site_class != "home", MarketSite.kind == "ezs",
        MarketSite.latitude.is_not(None)))).scalars().all()
    alive_since = now - timedelta(days=ALIVE_DAYS)

    pressure_index = _geo_index(sites, radius_km)

    def rivals_near(lat, lon) -> int:
        return sum(1 for site in _geo_around(pressure_index, float(lat), float(lon), radius_km)
                   if site.last_session_at and site.last_session_at >= alive_since
                   and _distance_km(float(lat), float(lon),
                                    float(site.latitude), float(site.longitude)) <= radius_km)

    recent = await _sessions_by_location(
        db, cid, [str(loc_id) for loc_id, *_ in ours], now - window, now)
    profile = {str(loc_id): {"name": name, "city": city,
                             "rivals": rivals_near(lat, lon), "class": cls,
                             "sessions": recent.get(str(loc_id), {}).get("sessions", 0.0)}
               for loc_id, name, city, lat, lon, cls in ours}

    target_rivals = _median([float(profile[t]["rivals"]) for t in targets if t in profile]) or 0
    target_sessions = _median([profile[t]["sessions"] for t in targets if t in profile]) or 0
    target_class = next((profile[t]["class"] for t in targets
                         if t in profile and profile[t]["class"]), None)

    candidates = []
    for loc_id, info in profile.items():
        if loc_id in targets or not info["sessions"]:
            continue
        if target_class and info["class"] and info["class"] != target_class:
            continue
        if abs(info["rivals"] - target_rivals) > 1:
            continue
        # Объём должен быть сопоставим: объект на 5 сессий в неделю не контроль для
        # объекта на 500 — у них разная чувствительность к любому шуму.
        if target_sessions and not (0.5 <= info["sessions"] / target_sessions <= 2.0):
            continue
        candidates.append({"locationId": loc_id, "name": info["name"], "city": info["city"],
                           "rivals": info["rivals"], "sessions": info["sessions"]})
    candidates.sort(key=lambda r: abs(r["sessions"] - target_sessions))
    control = [c["locationId"] for c in candidates[:10]]

    # Параллельность трендов: два равных окна ДО, сравниваем динамику групп.
    prev_from, prev_to = now - window * 2, now - window
    scope_prev = await _sessions_by_location(db, cid, targets, prev_from, prev_to)
    scope_now = await _sessions_by_location(db, cid, targets, prev_to, now)
    ctrl_prev = await _sessions_by_location(db, cid, control, prev_from, prev_to)
    ctrl_now = await _sessions_by_location(db, cid, control, prev_to, now)
    scope_trend = _pct(_sum_of(scope_prev, "sessions"), _sum_of(scope_now, "sessions"))
    ctrl_trend = _pct(_sum_of(ctrl_prev, "sessions"), _sum_of(ctrl_now, "sessions"))
    gap = (abs(scope_trend - ctrl_trend)
           if scope_trend is not None and ctrl_trend is not None else None)

    return {
        "control": control, "candidates": candidates[:20],
        "targetProfile": {"rivals": target_rivals, "sessions": target_sessions,
                          "class": target_class},
        "parallel": {
            "weeks": weeks,
            "scopeTrendPct": scope_trend, "controlTrendPct": ctrl_trend,
            "gapPct": gap,
            # Расхождение до вмешательства больше 15 пунктов означает, что группы и
            # так живут по-разному: замер после действия будет неубедителен.
            "ok": (gap is not None and gap <= 15),
            "note": ("тренды до вмешательства идут рядом — замер будет читаемым"
                     if gap is not None and gap <= 15 else
                     "группы расходятся ещё до действия: подберите контроль иначе, "
                     "иначе разность разностей ничего не докажет"),
        },
    }


@router.post("/scenarios/{scenario_id}/measure")
async def measure_scenario(
    scenario_id: uuid.UUID, company_id: str = Query(...),
    weeks: int = Query(8, ge=1, le=52),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Замер: разность разностей по сессиям и выручке.

    Берём равные окна до и после даты действия у объектов сценария и у контрольной
    группы. Эффект — разница изменений. Если контроль пуст, замер всё равно
    считается, но вердикт «не ясно»: без контроля отличить действие от сезона нечем.
    """
    cid = await _member(company_id, user, db)
    row = (await db.execute(select(MarketScenario).where(
        MarketScenario.id == scenario_id,
        MarketScenario.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сценарий не найден")
    if not row.started_on:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "У сценария нет даты действия — замерять нечего")

    started = datetime.fromisoformat(row.started_on).replace(tzinfo=timezone.utc)
    window = timedelta(weeks=weeks)
    scope = [str(x) for x in (row.scope_json or [])]
    control = [str(x) for x in (row.control_json or [])]

    scope_before = await _sessions_by_location(db, cid, scope, started - window, started)
    scope_after = await _sessions_by_location(db, cid, scope, started, started + window)
    ctrl_before = await _sessions_by_location(db, cid, control, started - window, started)
    ctrl_after = await _sessions_by_location(db, cid, control, started, started + window)

    scope_sessions = _pct(_sum_of(scope_before, "sessions"), _sum_of(scope_after, "sessions"))
    ctrl_sessions = _pct(_sum_of(ctrl_before, "sessions"), _sum_of(ctrl_after, "sessions"))
    scope_revenue = _pct(_sum_of(scope_before, "revenue"), _sum_of(scope_after, "revenue"))
    ctrl_revenue = _pct(_sum_of(ctrl_before, "revenue"), _sum_of(ctrl_after, "revenue"))

    did_sessions = (round(scope_sessions - ctrl_sessions, 1)
                    if scope_sessions is not None and ctrl_sessions is not None else None)
    did_revenue = (round(scope_revenue - ctrl_revenue, 1)
                   if scope_revenue is not None and ctrl_revenue is not None else None)

    # Вердикт выдаётся только тогда, когда его есть на чём основать. Прежде хватало
    # разницы в 5 п.п. — при незавершённом окне, пересечении групп или десятке сессий
    # это был вердикт по шуму (ревизия 12.09.2026, К7).
    reasons: list[str] = []
    if not control:
        reasons.append("нет контрольной группы — отличить действие от сезона нечем")
    if set(scope) & set(control):
        reasons.append("объекты действия и контроль пересекаются")
    if started + window > datetime.now(timezone.utc):
        reasons.append(f"окно после действия ещё не закрылось: нужно {weeks} нед "
                       f"после {row.started_on}")
    before_n = _sum_of(scope_before, "sessions")
    after_n = _sum_of(scope_after, "sessions")
    if min(before_n, after_n) < MEASURE_MIN_SESSIONS:
        reasons.append(f"мало наблюдений: {int(before_n)} сессий до и {int(after_n)} после "
                       f"при пороге {MEASURE_MIN_SESSIONS}")
    if did_revenue is None:
        reasons.append("не с чем сравнивать: в одном из окон нет выручки")

    if reasons:
        verdict = "unclear"
    elif did_revenue >= 5:
        verdict = "worked"
    elif did_revenue <= -5:
        verdict = "backfired"
    else:
        verdict = "no_effect"

    fact = {
        "weeks": weeks, "startedOn": row.started_on,
        "scope": {"sessionsPct": scope_sessions, "revenuePct": scope_revenue,
                  "objects": len(scope)},
        "control": {"sessionsPct": ctrl_sessions, "revenuePct": ctrl_revenue,
                    "objects": len(control)},
    }
    measure = MarketScenarioMeasure(
        company_id=cid, scenario_id=row.id,
        measured_on=datetime.now(timezone.utc).date().isoformat(),
        fact_json=fact, did_sessions=did_sessions, did_revenue=did_revenue,
        verdict=verdict, author_name=getattr(user, "full_name", None) or user.email,
        note=("; ".join(reasons) if reasons else None))
    db.add(measure)
    row.status = "measured"
    await db.commit()
    return {"scenarioId": str(row.id), "verdict": verdict, "fact": fact,
            "didSessions": did_sessions, "didRevenue": did_revenue,
            "reasons": reasons}


# ── Партнёрство и интеграции ────────────────────────────────────────────────
# Роуминг имеет смысл там, где партнёр нас ДОПОЛНЯЕТ: его точки стоят в городах, где
# нас нет, и наш клиент получает доступ туда, куда сегодня не доезжает. Партнёр,
# который стоит ровно там же, где мы, роумингом ничего не добавляет — он просто
# конкурент, с которым мы поделимся клиентом.

@router.get("/partners")
async def market_partners(
    company_id: str = Query(...),
    min_sites: int = Query(2, ge=1, le=100),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Кандидаты на роуминг: чем каждая сеть дополняет нашу, а чем дублирует."""
    cid = await _member(company_id, user, db)
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)

    our_cities = {city for (city,) in (await db.execute(
        select(ServiceLocation.city).where(
            ServiceLocation.company_id == cid,
            ServiceLocation.is_test.is_(False),
            ServiceLocation.city.is_not(None)))).all() if city}

    sites = (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid, MarketSite.status != "closed",
        MarketSite.site_class != "home", MarketSite.kind == "ezs",
        MarketSite.operator_id.is_not(None)))).scalars().all()
    operators = {o.id: o for o in (await db.execute(select(MarketOperator).where(
        MarketOperator.company_id == cid))).scalars().all()}

    by_op: dict[str, dict[str, Any]] = {}
    for site in sites:
        op = operators.get(site.operator_id)
        if op is None or op.relation == "own":
            continue
        row = by_op.setdefault(str(op.id), {
            "id": str(op.id), "name": op.name, "relation": op.relation,
            "notes": op.notes, "sites": 0, "alive": 0, "ports": 0,
            "overlapSites": 0, "unknownCity": 0,
            "newCities": set(), "sharedCities": set(),
        })
        row["sites"] += 1
        row["ports"] += site.ports or 0
        if site.last_session_at and site.last_session_at >= alive_since:
            row["alive"] += 1
        if site.city:
            if site.city in our_cities:
                row["overlapSites"] += 1
                row["sharedCities"].add(site.city)
            else:
                row["newCities"].add(site.city)
        else:
            # Точка без города не расширяет охват: мы не знаем, где она. Прежде
            # такие попадали в дополнение вычитанием и обещали доступ в городах,
            # которых никто не называл (аудит А12).
            row["unknownCity"] += 1

    rows = []
    for row in by_op.values():
        if row["sites"] < min_sites:
            continue
        new_cities = sorted(row.pop("newCities"))
        shared_cities = sorted(row.pop("sharedCities"))
        complement = row["sites"] - row["overlapSites"] - row["unknownCity"]
        known = row["sites"] - row["unknownCity"]
        rows.append({
            **row,
            "complementSites": complement,
            # Доля дополнения: чем выше, тем больше подключение даёт клиенту. Сеть с
            # нулевым дополнением — это не партнёр, это конкурент в тех же городах.
            # Считается от точек с известным городом, а не от всех.
            "complementPct": round(complement / known * 100, 1) if known else None,
            "newCities": new_cities[:12], "newCitiesTotal": len(new_cities),
            "sharedCities": shared_cities[:12], "sharedCitiesTotal": len(shared_cities),
        })
    rows.sort(key=lambda r: (-r["complementSites"], -r["sites"]))
    return {"partners": rows, "total": len(rows), "ourCities": len(our_cities),
            "unknownCityTotal": sum(r["unknownCity"] for r in rows),
            "note": "дополнение считается по городам: точка партнёра в городе, где "
                    "нас нет, расширяет доступ клиента; точка в нашем городе делит "
                    "с нами тот же спрос; точки без города в дополнение не идут"}


@router.patch("/operators/{operator_id}")
async def patch_operator(
    operator_id: uuid.UUID, company_id: str = Query(...), body: dict = Body(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Отношение к компании и заметка переговоров.

    Отношение — это решение человека, а не свойство данных: одна и та же сеть бывает
    конкурентом в одном регионе и кандидатом на роуминг в другом, и выбор делает тот,
    кто ведёт переговоры.
    """
    cid = await _member(company_id, user, db)
    op = (await db.execute(select(MarketOperator).where(
        MarketOperator.id == operator_id,
        MarketOperator.company_id == cid))).scalar_one_or_none()
    if op is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оператор не найден")
    if "relation" in body:
        allowed = {"competitor", "partner", "candidate", "integrated", "own", "other"}
        if body["relation"] not in allowed:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Отношение должно быть одним из: {', '.join(sorted(allowed))}")
        op.relation = body["relation"]
    if "notes" in body:
        op.notes = body["notes"]
    if "siteUrl" in body:
        op.site_url = body["siteUrl"]
    if "inn" in body:
        op.inn = body["inn"]
    await db.commit()
    return {"id": str(op.id), "relation": op.relation}


# ── Развитие сети: режим присутствия и направления роста ────────────────────
# Продукт смотрит на рынок ГЛАЗАМИ НАШЕЙ КОМПАНИИ (решение МАГа 12.09.2026). Сеть
# растёт не одним способом, и в разных регионах уместны разные:
#
#   • где мы почти одни — растить не сеть, а выручку с неё: цена, корпоратив, клуб;
#   • где делим рынок — держать позицию: цена, качество, точечная стройка;
#   • где нас нет — входить: своя стройка, роуминг с местной сетью, франшиза.
#
# Поэтому «сколько у нас точек» — не ответ. Ответ — режим присутствия по регионам и
# кандидаты в каждом направлении.

# Доля точек сети в регионе, выше которой положение считается монопольным.
MONOPOLY_SHARE = 70.0
# Ниже этой доли мы в регионе присутствуем, но погоду не делаем.
WEAK_SHARE = 25.0

GROWTH_TRACKS = {
    "build": "своя стройка",
    "roaming": "роуминг с чужой сетью",
    "franchise": "франшиза: чужая сеть на нашем обслуживании",
    "corporate": "корпоративные продажи",
    "loyalty": "программа лояльности",
}

PRESENCE_LABEL = {
    "unknown": "рынок здесь не наблюдали",
    "monopoly": "мы почти одни",
    "strong": "мы сильнее рынка",
    "contested": "делим рынок",
    "weak": "мы слабее рынка",
    "absent": "нас нет",
}

# Что уместно делать при таком положении. Не предписание, а подсказка: решает человек.
PRESENCE_TRACKS = {
    # Пока рынок не наблюдали, единственное разумное действие — посмотреть.
    "unknown": [],
    "monopoly": ["corporate", "loyalty", "build"],
    "strong": ["corporate", "loyalty", "build"],
    "contested": ["build", "roaming", "corporate"],
    "weak": ["roaming", "franchise", "build"],
    "absent": ["build", "roaming", "franchise"],
}


def _presence(our_sites: int, rival_sites: int,
              observed: bool = True) -> tuple[str, float | None]:
    """Режим присутствия по доле точек сети в территории.

    Отсутствие конкурентов в БАЗЕ — не то же самое, что их отсутствие на местности:
    регион, где рынок ни разу не наблюдали, выглядел монополией со стопроцентной
    долей, и подсказка «растите выручку, не стройте» опиралась на пустоту
    (ревизия 12.09.2026, К3). Такой регион честнее назвать неизвестным.
    """
    total = our_sites + rival_sites
    if our_sites == 0:
        return "absent", 0.0 if total else None
    if not observed:
        return "unknown", None
    share = our_sites / total * 100 if total else 100.0
    if share >= MONOPOLY_SHARE:
        return "monopoly", round(share, 1)
    if share >= 50:
        return "strong", round(share, 1)
    if share >= WEAK_SHARE:
        return "contested", round(share, 1)
    return "weak", round(share, 1)


@router.get("/growth/presence")
async def growth_presence(
    company_id: str = Query(...),
    days: int = Query(90, ge=30, le=365),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Регионы по нашему положению: где мы одни, где делим рынок, где нас нет.

    Стратегия региона выводится не из его размера, а из нашего положения в нём:
    там, где мы почти одни, строить вторую станцию рядом с собой бессмысленно —
    расти надо выручкой; там, где нас нет, любая цена уже не наша.
    """
    cid = await _member(company_id, user, db)
    reply = await market_territories(company_id=company_id, level="region", days=days,
                                     user=user, db=db)
    # Регион, где нас нет, но идут пятнадцать площадок, — это не «нас нет», это
    # «входим». Решение о территории там уже принято, и предлагать его заново
    # незачем; вопрос другой — что вокруг и хватит ли того, что строим.
    in_work = await _projects_in_work(db, cid, level="region")
    rows = []
    for row in reply["territories"]:
        if row["name"] == "территория не определена":
            continue
        # Наблюдали ли мы здесь рынок вообще: чужие точки или домашние розетки в базе.
        observed = bool(row["rivalSites"] or row["homeSockets"])
        mode, share = _presence(row["ourSites"], row["rivalSites"], observed=observed)
        work = in_work.get((canon_region(row["name"]) or row["name"]).strip().lower())
        rows.append({
            **row, "presence": mode, "presenceLabel": PRESENCE_LABEL[mode],
            "sharePct": share, "suggestedTracks": PRESENCE_TRACKS[mode],
            "projectsInWork": work["projects"] if work else 0,
            "projectStages": work["stages"] if work else {},
            # Классификацию не подменяем: положение считается по точкам, а вход —
            # это факт о работе. Два разных утверждения, и оба нужны словами.
            "entering": bool(work) and row["ourSites"] == 0,
        })
    # Регион точки известен не всегда: у части выгрузки в адресе нет субъекта, а
    # города нет в справочнике. Такие точки лежат в «территории не определена» и в
    # расклад по регионам не входят вовсе. Значит наша доля в каждом регионе —
    # ВЕРХНЯЯ оценка: часть чужих точек могла не попасть в знаменатель. Пока это
    # так, «монополия» — не факт, а предположение, и экран обязан сказать, на каком
    # покрытии оно сделано (аудит А01).
    unplaced = next((r["rivalSites"] for r in reply["territories"]
                     if r["name"] == "территория не определена"), 0)
    placed = sum(r["rivalSites"] for r in rows)
    geo_coverage = (round(placed / (placed + unplaced) * 100, 1)
                    if (placed + unplaced) else None)

    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        g = groups.setdefault(row["presence"], {
            "presence": row["presence"], "label": PRESENCE_LABEL[row["presence"]],
            "regions": 0, "ourSites": 0, "rivalSites": 0, "ourSessions": 0,
            "ourRevenue": 0.0, "tracks": PRESENCE_TRACKS[row["presence"]],
        })
        g["regions"] += 1
        g["ourSites"] += row["ourSites"]
        g["rivalSites"] += row["rivalSites"]
        g["ourSessions"] += row["ourSessions"]
        g["ourRevenue"] += row["ourRevenue"]
    order = ["monopoly", "strong", "contested", "weak", "absent", "unknown"]
    rows.sort(key=lambda r: (order.index(r["presence"]), -r["ourRevenue"], -r["rivalSites"]))
    return {
        "days": days, "regions": rows,
        "groups": [groups[k] for k in order if k in groups],
        "thresholds": {"monopoly": MONOPOLY_SHARE, "weak": WEAK_SHARE},
        "geoCoverage": geo_coverage, "sitesWithoutRegion": unplaced,
        "shareBound": "upper",
        "enteringRegions": sum(1 for r in rows if r["entering"]),
        "projectsInWork": sum(r["projectsInWork"] for r in rows),
        "note": ("доля считается по точкам сети в регионе; домашние розетки не в "
                 "счёт. Это верхняя оценка нашей доли: "
                 + (f"у {unplaced} точек рынка регион неизвестен, они не вошли ни в "
                    f"один расклад" if unplaced else "вся выгрузка разложена по "
                    "регионам")),
    }


@router.get("/growth/overview")
async def growth_overview(
    company_id: str = Query(...),
    days: int = Query(90, ge=30, le=365),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Пять направлений роста с живыми мерами каждого.

    Мера направления — не план, а ФАКТ сегодняшнего дня: сколько возможностей видно
    в данных и сколько из них уже взято в работу. Направление без единой меры
    показывается пустым и говорит, каких данных ему не хватает: пустая строка
    честнее придуманного показателя.
    """
    cid = await _member(company_id, user, db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)

    leads = (await db.execute(select(MarketGrowthLead.track, MarketGrowthLead.status,
                                     func.count())
                              .where(MarketGrowthLead.company_id == cid)
                              .group_by(MarketGrowthLead.track, MarketGrowthLead.status))).all()
    by_track: dict[str, dict[str, int]] = {}
    for track, lead_status, count in leads:
        by_track.setdefault(track, {})[lead_status] = int(count)

    # ── стройка: белые пятна и то, что уже в «Проектах» ──
    spots = await market_whitespots(company_id=company_id, level="city", user=user, db=db)
    alive_spots = [x for x in spots["spots"] if x["rivalAlive"] > 0]
    # «Площадок в Проектах» — это те, что В РАБОТЕ. Введённые в эксплуатацию уже стали
    # объектами сети и считаются в другом месте, архив и заморозка — не работа;
    # сложив всё вместе, получаем тысячу вместо полусотни и радуемся зря.
    projects = dict((stage, int(count)) for stage, count in (await db.execute(
        select(EzsSite.stage, func.count()).where(
            EzsSite.company_id == cid,
            EzsSite.stage.notin_(["live", "archive", "on_hold"]))
        .group_by(EzsSite.stage))).all())

    # ── роуминг и франшиза: чужие сети, дополняющие нас ──
    partners = await market_partners(company_id=company_id, min_sites=1, user=user, db=db)
    complements = [p for p in partners["partners"] if p["complementSites"] > 0]
    # Франшиза — про малые сети: у них нет своего процессинга и обслуживания, и
    # именно им есть смысл встать на наше. Крупная сеть строит своё.
    small = [p for p in partners["partners"] if 1 <= p["sites"] <= 10]

    # ── корпоратив: клиенты ЮЛ и их вес в выручке ──
    corp_total = int((await db.execute(
        select(func.count()).select_from(CorporateClient)
        .where(CorporateClient.company_id == cid))).scalar() or 0)
    corp_rows = (await db.execute(
        select(ChargeSession.user_type, func.count(),
               func.coalesce(func.sum(func.coalesce(
                   ChargeSession.client_amount, ChargeSession.amount)), 0),
               func.count(func.distinct(ChargeSession.user_id)))
        .where(ChargeSession.company_id == cid, ChargeSession.started_at >= since)
        .group_by(ChargeSession.user_type))).all()
    by_type = {(t or "—"): {"sessions": int(c), "revenue": float(a or 0), "users": int(u)}
               for t, c, a, u in corp_rows}
    ul = next((v for k, v in by_type.items() if k.upper().startswith("ЮЛ")), None)
    fl = next((v for k, v in by_type.items() if k.upper().startswith("ФЛ")), None)
    all_sessions = sum(v["sessions"] for v in by_type.values()) or 1

    # ── лояльность: возвращаются ли частные клиенты ──
    # Удержание — про ЧАСТНОГО клиента, который ВЕРНУЛСЯ. Прежде считались любые
    # строки сессий любого типа клиента: две неудачные попытки подряд в одном визите
    # делали человека «вернувшимся», а корпоративный автопарк с ежедневными
    # зарядками поднимал показатель сам собой (ревизия 12.09.2026, К6).
    #
    # Теперь: только ФЛ, только состоявшиеся зарядки (энергия отпущена) и возврат
    # считается по РАЗНЫМ ДНЯМ — повтор попытки в тот же день возвратом не является.
    retail = and_(ChargeSession.company_id == cid,
                  ChargeSession.started_at >= since,
                  ChargeSession.user_id.is_not(None),
                  ChargeSession.energy_kwh > 0,
                  func.upper(func.coalesce(ChargeSession.user_type, "")).like("ФЛ%"))
    visits = (await db.execute(
        select(func.count(func.distinct(ChargeSession.user_id))).where(retail))).scalar() or 0
    repeat_subq = (select(ChargeSession.user_id)
                   .where(retail)
                   .group_by(ChargeSession.user_id)
                   .having(func.count(func.distinct(
                       func.date(ChargeSession.started_at))) > 1)).subquery()
    repeat_users = (await db.execute(
        select(func.count()).select_from(repeat_subq))).scalar() or 0

    tracks = [
        {
            "track": "build", "label": GROWTH_TRACKS["build"],
            "headline": (f"{len(alive_spots)} городов с живым рынком, где нас нет"
                         if alive_spots else "белых пятен с живым рынком не видно"),
            "metrics": [
                {"label": "белых пятен", "value": spots["total"]},
                {"label": "из них с живыми точками", "value": len(alive_spots)},
                {"label": "площадок в работе у «Проектов»", "value": sum(projects.values())},
                # Где стройка уже началась — это ответ на «куда идти», данный
                # раньше вопроса: считать его неизвестным и предлагать те же
                # территории заново значит терять работу, которая уже идёт.
                {"label": "пятен, где площадка уже заведена",
                 "value": spots.get("withProject", 0)},
            ],
            "leads": by_track.get("build", {}),
        },
        {
            "track": "roaming", "label": GROWTH_TRACKS["roaming"],
            "headline": (f"{len(complements)} сетей дополняют нас точками там, где нас нет"
                         if complements else "дополняющих сетей пока не видно"),
            "metrics": [
                {"label": "сетей-кандидатов", "value": len(complements)},
                {"label": "их точек в городах без нас",
                 "value": sum(p["complementSites"] for p in complements)},
            ],
            "leads": by_track.get("roaming", {}),
        },
        {
            "track": "franchise", "label": GROWTH_TRACKS["franchise"],
            "headline": (f"{len(small)} малых сетей — кандидаты на наше обслуживание"
                         if small else "малых сетей в данных не видно"),
            "metrics": [
                {"label": "сетей до 10 точек", "value": len(small)},
                {"label": "их точек всего", "value": sum(p["sites"] for p in small)},
            ],
            "leads": by_track.get("franchise", {}),
        },
        {
            "track": "corporate", "label": GROWTH_TRACKS["corporate"],
            "headline": (f"{corp_total} корпоративных клиентов, их доля "
                         f"{round((ul['sessions'] if ul else 0) / all_sessions * 100)} % сессий"),
            "metrics": [
                {"label": "клиентов в реестре", "value": corp_total},
                {"label": "сессий ЮЛ за период", "value": ul["sessions"] if ul else 0},
                {"label": "плательщиков ЮЛ", "value": ul["users"] if ul else 0},
            ],
            "leads": by_track.get("corporate", {}),
        },
        {
            "track": "loyalty", "label": GROWTH_TRACKS["loyalty"],
            "headline": (f"{round(repeat_users / visits * 100)} % частных клиентов "
                         f"приезжали в разные дни за {days}" if visits
                         else "состоявшихся зарядок частных клиентов за период не было"),
            "metrics": [
                {"label": "частных клиентов с зарядкой", "value": int(visits)},
                {"label": "из них приезжали в разные дни", "value": int(repeat_users)},
                {"label": "сессий ФЛ", "value": fl["sessions"] if fl else 0},
            ],
            "leads": by_track.get("loyalty", {}),
        },
    ]

    presence = await growth_presence(company_id=company_id, days=days, user=user, db=db)
    return {"days": days, "tracks": tracks, "presence": presence["groups"],
            "trackLabels": GROWTH_TRACKS}


# ── Стройка: что уже в работе у «Проектов» ──────────────────────────────────
# Раздел «Развитие» отвечает на вопрос «куда идти», и без этого экрана он отвечал на
# него, не зная, куда мы уже идём: 219 площадок в работе были одним числом в метрике.
# Отсюда две ошибки сразу. Белое пятно предлагалось как возможность там, где проект
# уже заведён, а регион с пятнадцатью проектами в стадии переговоров назывался «нас
# нет» — хотя это ровно «входим». Проект — это уже принятое решение о территории, и
# рынок вокруг него надо показывать рядом с ним, а не искать заново.

# Стадии воронки подбора площадки, от первой к последней (docs SITES_LAND_BANK).
# `live` — уже объект сети, `archive` и `on_hold` — не работа.
PIPELINE_STAGES = ["lead", "screening", "negotiation", "dd", "decision",
                   "contracting", "construction"]
STAGE_LABEL = {
    "lead": "заявка", "screening": "первичный отбор", "negotiation": "переговоры",
    "dd": "проверка", "decision": "решение", "contracting": "договор",
    "construction": "стройка",
}


@router.get("/growth/pipeline")
async def growth_pipeline(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Перспективные проекты рядом с рынком: где мы уже идём и что там вокруг."""
    cid = await _member(company_id, user, db)
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)

    projects = (await db.execute(select(EzsSite).where(
        EzsSite.company_id == cid,
        EzsSite.stage.notin_(["live", "archive", "on_hold"])))).scalars().all()
    if not projects:
        return {"projects": 0, "message": "площадок в работе нет — воронка «Проектов» пуста"}

    own_ids = await _own_operator_ids(db, cid)
    market = [x for x in (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid, MarketSite.status == "active",
        MarketSite.kind == "ezs"))).scalars().all()
        if _is_external(x, own_ids) and (x.site_class or "") != "home"]
    ours = (await db.execute(
        select(ServiceLocation.city, ServiceLocation.region_id)
        .where(ServiceLocation.company_id == cid,
               ServiceLocation.is_test.is_(False)))).all()
    regions = dict((rid, name) for rid, name in (await db.execute(
        select(Region.id, Region.name).where(Region.company_id == cid))).all())

    def key(value: str | None) -> str:
        # «г. Псков», «Псков» и «городской округ Химки» — один и тот же город, и
        # без приведения проект в нём не находил ни рынка, ни нашей сети: экран
        # говорил «рынок здесь не наблюдали» о городе с десятью станциями.
        return (canon_city(value) or "").strip().lower()

    our_cities = {key(c) for c, _ in ours if c}
    our_by_region: dict[str, int] = {}
    for _, rid in ours:
        name = regions.get(rid)
        if name:
            our_by_region[name] = our_by_region.get(name, 0) + 1

    # Рынок по городу: сколько точек и сколько из них заряжали за 90 дней.
    market_city: dict[str, dict[str, int]] = {}
    for site in market:
        bucket = market_city.setdefault(key(site.city), {"sites": 0, "alive": 0})
        bucket["sites"] += 1
        if site.last_session_at and site.last_session_at >= alive_since:
            bucket["alive"] += 1

    # ── воронка ──
    by_stage: dict[str, dict[str, Any]] = {}
    for p in projects:
        row = by_stage.setdefault(p.stage, {
            "stage": p.stage, "label": STAGE_LABEL.get(p.stage, p.stage),
            "projects": 0, "withCity": 0, "withCoords": 0,
            "plannedPoints": 0, "plannedPowerKwt": 0.0, "withPlan": 0,
        })
        row["projects"] += 1
        if p.city:
            row["withCity"] += 1
        if p.lat is not None and p.lon is not None:
            row["withCoords"] += 1
        if p.planned_ezs_count:
            row["plannedPoints"] += int(p.planned_ezs_count)
            row["withPlan"] += 1
        if p.planned_power_kwt:
            row["plannedPowerKwt"] += float(p.planned_power_kwt)
    stages = [by_stage[st] for st in PIPELINE_STAGES if st in by_stage]

    # ── города: проект и рынок рядом ──
    cities: dict[str, dict[str, Any]] = {}
    for p in projects:
        if not p.city:
            continue
        k = key(p.city)
        row = cities.setdefault(k, {
            "city": canon_city(p.city) or p.city.strip(),
            "region": canon_region(p.region_norm or p.region),
            "projects": 0, "stages": {}, "weAreThere": k in our_cities,
            "marketSites": market_city.get(k, {}).get("sites", 0),
            "marketAlive": market_city.get(k, {}).get("alive", 0),
            "marketKnown": k in market_city,
        })
        row["projects"] += 1
        row["stages"][p.stage] = row["stages"].get(p.stage, 0) + 1
    city_rows = sorted(cities.values(),
                       key=lambda r: (-r["projects"], -r["marketAlive"]))

    # Вход в новую территорию: проект есть, действующей сети нет.
    entering = [r for r in city_rows if not r["weAreThere"]]
    # Строим там, где рынок не наблюдали: либо мы первые, либо у данных дыра.
    # Ни то ни другое не должно молчать — это вопрос к источнику, а не вывод.
    unseen = [r for r in city_rows if not r["marketKnown"]]

    # ── регионы: где мы уже входим ──
    by_region: dict[str, dict[str, Any]] = {}
    for p in projects:
        name = canon_region(p.region_norm or p.region)
        if not name:
            continue
        row = by_region.setdefault(name, {
            "region": name, "projects": 0, "cities": set(),
            "ourSites": our_by_region.get(name, 0),
        })
        row["projects"] += 1
        if p.city:
            row["cities"].add(canon_city(p.city) or p.city.strip())
    region_rows = sorted(
        ({**r, "cities": len(r["cities"]),
          "entering": r["ourSites"] == 0} for r in by_region.values()),
        key=lambda r: -r["projects"])

    planned_points = sum(r["plannedPoints"] for r in stages)
    with_plan = sum(r["withPlan"] for r in stages)

    return {
        "projects": len(projects), "stages": stages,
        "cities": city_rows[:60], "citiesTotal": len(city_rows),
        "entering": entering[:40], "enteringTotal": len(entering),
        "unseenByMarket": unseen[:20], "unseenTotal": len(unseen),
        "regions": region_rows[:40],
        "enteringRegions": sum(1 for r in region_rows if r["entering"]),
        "plan": {
            "points": planned_points, "withPlan": with_plan,
            "coverage": round(with_plan / len(projects) * 100, 1) if projects else None,
            "powerKwt": round(sum(r["plannedPowerKwt"] for r in stages), 1),
        },
        "note": ("воронка «Проектов» без введённых в эксплуатацию, архива и заморозки. "
                 "Рынок рядом взят по городу: это грубее радиуса, но город — та "
                 "единица, в которой проект и заводится. Сколько станций добавит "
                 "проект, известно не везде, и доля заполненности показана рядом: "
                 "складывать план по трети проектов и называть это программой нельзя"),
    }


class GrowthLeadIn(BaseModel):
    track: str = "build"
    title: str = Field(min_length=1, max_length=300)
    subject_kind: str | None = None
    subject_ref: str | None = None
    evidence: dict[str, Any] | None = None
    note: str | None = None
    status: str = "new"


@router.get("/growth/leads")
async def list_growth_leads(
    company_id: str = Query(...),
    track: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Воронка кандидатов развития по направлениям."""
    cid = await _member(company_id, user, db)
    query = select(MarketGrowthLead).where(MarketGrowthLead.company_id == cid)
    if track:
        query = query.where(MarketGrowthLead.track == track)
    rows = (await db.execute(query.order_by(MarketGrowthLead.created_at.desc()))).scalars().all()
    return {"leads": [{
        "id": str(r.id), "track": r.track, "trackLabel": GROWTH_TRACKS.get(r.track, r.track),
        "title": r.title, "subjectKind": r.subject_kind, "subjectRef": r.subject_ref,
        "evidence": r.evidence_json or {}, "status": r.status,
        "rejectReason": r.reject_reason, "note": r.note,
        "siteId": str(r.site_id) if r.site_id else None,
        "scenarioId": str(r.scenario_id) if r.scenario_id else None,
        "ownerName": r.owner_name,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


@router.post("/growth/leads", status_code=status.HTTP_201_CREATED)
async def create_growth_lead(
    company_id: str = Query(...), body: GrowthLeadIn = Body(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cid = await _member(company_id, user, db)
    if body.track not in GROWTH_TRACKS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Направление должно быть одним из: {', '.join(GROWTH_TRACKS)}")
    row = MarketGrowthLead(
        company_id=cid, track=body.track, title=body.title,
        subject_kind=body.subject_kind, subject_ref=body.subject_ref,
        evidence_json=body.evidence, note=body.note, status=body.status,
        owner_user_id=user.id, owner_name=getattr(user, "full_name", None) or user.email)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "track": row.track, "title": row.title}


@router.patch("/growth/leads/{lead_id}")
async def patch_growth_lead(
    lead_id: uuid.UUID, company_id: str = Query(...), body: dict = Body(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Движение кандидата по воронке. Отклонение требует причины: список отказов без
    причин через полгода ничему не учит."""
    cid = await _member(company_id, user, db)
    row = (await db.execute(select(MarketGrowthLead).where(
        MarketGrowthLead.id == lead_id,
        MarketGrowthLead.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кандидат не найден")
    if body.get("status") == "rejected" and not (body.get("rejectReason") or row.reject_reason):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "У отказа должна быть причина")
    for key, column in {"title": "title", "status": "status", "note": "note",
                        "rejectReason": "reject_reason", "track": "track"}.items():
        if key in body:
            setattr(row, column, body[key])
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/growth/leads/{lead_id}/to-project", status_code=status.HTTP_201_CREATED)
async def lead_to_project(
    lead_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Взять кандидата в работу: завести площадку в «Проектах» с обоснованием.

    Маркетинг не строит станции — он находит и обосновывает возможность. Переход
    сюда и есть граница двух продуктов: дальше площадка живёт по регламенту стройки
    со своими стадиями и гейтами, а маркетинг хранит ссылку и видит, чем это
    кончилось.

    Снимок обоснования переносится целиком: через полгода вопрос «почему мы сюда
    пошли» задают именно площадке, а не кандидату.
    """
    cid = await _member(company_id, user, db)
    lead = (await db.execute(select(MarketGrowthLead).where(
        MarketGrowthLead.id == lead_id,
        MarketGrowthLead.company_id == cid))).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кандидат не найден")
    if lead.track != "build":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Площадка заводится только из кандидата на стройку: "
                            "роуминг, франшиза и клиенты идут своим путём")
    if lead.site_id:
        return {"siteId": str(lead.site_id), "created": False,
                "message": "площадка по этому кандидату уже заведена"}

    from app.services import ezs_sites

    prefix = ezs_sites.project_no_prefix()
    last = (await db.execute(
        select(func.max(EzsSite.project_no)).where(
            EzsSite.company_id == cid,
            EzsSite.project_no.like(f"{prefix}%")))).scalar()
    seq = ezs_sites.parse_project_seq(last) + 1

    evidence = lead.evidence_json or {}
    today = datetime.now(timezone.utc).date().isoformat()
    site = EzsSite(
        company_id=cid, stage="lead", stage_since=today,
        project_no=ezs_sites.format_project_no(prefix, seq),
        title=lead.title,
        city=(evidence.get("city") or lead.subject_ref),
        region=evidence.get("region"),
        lat=evidence.get("lat"), lon=evidence.get("lon"),
        # Обоснование маркетинга целиком: окружение, прогноз, из чего он собран.
        raw={"marketLead": {
            "leadId": str(lead.id), "track": lead.track, "title": lead.title,
            "evidence": evidence, "note": lead.note,
            "takenOn": today, "takenBy": lead.owner_name,
        }},
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc))
    db.add(site)
    await db.flush()

    lead.site_id = site.id
    lead.status = "in_project"
    lead.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"siteId": str(site.id), "projectNo": site.project_no, "created": True,
            "message": f"площадка {site.project_no} заведена в «Проектах», стадия «Лид»"}


# ── Мы глазами рынка ────────────────────────────────────────────────────────
# Наша сеть есть и в публичном реестре: 429 точек РусГидро в полной выгрузке.
# Это редкая возможность — увидеть себя так, как видит клиент, выбирающий станцию
# в приложении: связь, доля успешных зарядок, оценка, отзывы, цена. И сравнить с
# тем, что мы знаем о себе сами.
#
# Расхождение здесь — не повод спорить с источником. Клиент видит именно эту
# картинку и по ней принимает решение ехать или не ехать.

@router.get("/self")
async def market_self_view(
    company_id: str = Query(...),
    match_km: float = Query(0.3, ge=0.05, le=2.0,
                            description="радиус сопоставления с нашим реестром"),
    days: int = Query(90, ge=30, le=365),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Наш публичный профиль: что о нас говорит рынок и сходится ли это с нами."""
    cid = await _member(company_id, user, db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)

    own_ops = {o.id for o in (await db.execute(select(MarketOperator).where(
        MarketOperator.company_id == cid,
        MarketOperator.relation == "own"))).scalars().all()}
    mine = [s for s in (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid,
        MarketSite.latitude.is_not(None)))).scalars().all()
        if s.operator_id in own_ops]

    ours = (await db.execute(
        select(ServiceLocation.id, ServiceLocation.name, ServiceLocation.city,
               ServiceLocation.latitude, ServiceLocation.longitude)
        .where(ServiceLocation.company_id == cid,
               ServiceLocation.is_test.is_(False),
               ServiceLocation.latitude.is_not(None)))).all()
    sales_rows = (await db.execute(
        select(ChargeSession.location_id, func.count(),
               func.coalesce(func.sum(func.coalesce(
                   ChargeSession.client_amount, ChargeSession.amount)), 0))
        .where(ChargeSession.company_id == cid, ChargeSession.started_at >= since,
               ChargeSession.location_id.is_not(None))
        .group_by(ChargeSession.location_id))).all()
    sales = {str(loc): {"sessions": int(cnt), "revenue": float(amount or 0)}
             for loc, cnt, amount in sales_rows}
    last_price = await _last_prices(db, cid)

    rows = []
    matched = 0
    for site in mine:
        # Сопоставление по расстоянию: у публичной карты своя координата, и она
        # редко совпадает с нашей до метра.
        best, best_km = None, None
        for loc_id, name, city, lat, lon in ours:
            distance = _distance_km(float(site.latitude), float(site.longitude),
                                    float(lat), float(lon))
            if best_km is None or distance < best_km:
                best, best_km = (str(loc_id), name, city), distance
        linked = best if best_km is not None and best_km <= match_km else None
        if linked:
            matched += 1
        sale = sales.get(linked[0]) if linked else None
        obs = last_price.get(str(site.id))
        rows.append({
            "siteId": str(site.id), "marketName": site.name, "city": site.city,
            "locationId": linked[0] if linked else None,
            "ourName": linked[1] if linked else None,
            "matchKm": round(best_km, 2) if best_km is not None else None,
            # Как нас видит клиент
            "quality": float(site.connection_quality_24h) if site.connection_quality_24h is not None else None,
            "successPct": float(site.success_charge_pct) if site.success_charge_pct is not None else None,
            "rating": float(site.rating) if site.rating is not None else None,
            "reviews": site.reviews_count,
            "publicPricePerKwh": obs["price"] if obs else None,
            "lastSessionAt": site.last_session_at.isoformat() if site.last_session_at else None,
            "aliveByMarket": bool(site.last_session_at and site.last_session_at >= alive_since),
            # Что знаем мы
            "ourSessions": sale["sessions"] if sale else None,
            "ourRevenue": sale["revenue"] if sale else None,
        })

    def _avg(values: list[float]) -> float | None:
        clean = [v for v in values if v is not None]
        return round(sum(clean) / len(clean), 1) if clean else None

    quality = _avg([r["quality"] for r in rows])
    success = _avg([r["successPct"] for r in rows])
    rating = _avg([r["rating"] for r in rows])
    alive_market = sum(1 for r in rows if r["aliveByMarket"])
    # Самое неприятное расхождение: рынок говорит «молчит», а у нас сессии идут —
    # значит клиент в приложении видит станцию мёртвой и мимо неё проезжает.
    silent_but_working = [r for r in rows
                          if not r["aliveByMarket"] and (r["ourSessions"] or 0) > 0]

    # Как выглядят на этом фоне лидеры рынка: сравнивать себя не с абсолютом, а с
    # теми, кто рядом в том же реестре.
    rivals = (await db.execute(
        select(MarketOperator.name,
               func.avg(MarketSite.connection_quality_24h),
               func.avg(MarketSite.success_charge_pct),
               func.avg(MarketSite.rating), func.count())
        .join(MarketSite, MarketSite.operator_id == MarketOperator.id)
        .where(MarketOperator.company_id == cid,
               MarketOperator.relation != "own",
               MarketSite.site_class == "network")
        .group_by(MarketOperator.name)
        .having(func.count() >= 30)
        .order_by(func.count().desc()).limit(10))).all()

    return {
        "days": days, "matchKm": match_km,
        # Все 429 точек, а не первые 300: экран сверяет наш реестр с публичным
        # отражением, и обрезанный список молча прячет часть расхождений — ровно
        # то, ради чего экран и открывают (аудит А13).
        "sites": sorted(rows, key=lambda r: (r["successPct"] is None, r["successPct"] or 0)),
        "totals": {
            "inMarket": len(rows), "matchedToRegistry": matched,
            "quality": quality, "success": success, "rating": rating,
            "reviews": sum(r["reviews"] or 0 for r in rows),
            "aliveByMarket": alive_market,
            "silentButWorking": len(silent_but_working),
        },
        "peers": [{"name": name, "quality": round(float(q), 1) if q is not None else None,
                   "success": round(float(sc), 1) if sc is not None else None,
                   "rating": round(float(rt), 2) if rt is not None else None,
                   "sites": int(cnt)}
                  for name, q, sc, rt, cnt in rivals],
        "note": ("сопоставление с реестром по расстоянию; расхождение «рынок молчит, "
                 "а сессии идут» означает, что клиент видит станцию мёртвой"),
    }


@router.get("/territory-profile")
async def territory_profile(
    company_id: str = Query(...),
    name: str = Query(..., description="город или регион"),
    level: str = Query("region", pattern="^(city|region)$"),
    days: int = Query(90, ge=30, le=365),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Что мы знаем о своей сети в этой территории — и что видим на рынке рядом.

    Рыночная часть отвечает на «кто вокруг», наша — на «почему у нас так». Второе мы
    знаем точно: своё оснащение, загрузку портов, состав клиентов, время спроса,
    результаты зарядок и динамику. Без этого разговор о территории сводится к
    подсчёту чужих точек.
    """
    cid = await _member(company_id, user, db)
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).replace(tzinfo=None)
    prev_since = (now - timedelta(days=days * 2)).replace(tzinfo=None)
    alive_since = now - timedelta(days=ALIVE_DAYS)

    regions = dict((rid, rname) for rid, rname in (await db.execute(
        select(Region.id, Region.name).where(Region.company_id == cid))).all())
    locations = (await db.execute(
        select(ServiceLocation).where(
            ServiceLocation.company_id == cid,
            ServiceLocation.is_test.is_(False)))).scalars().all()

    def belongs(loc) -> bool:
        where = regions.get(loc.region_id) if level == "region" else loc.city
        return (where or "") == name

    mine = [loc for loc in locations if belongs(loc)]
    ids = [loc.id for loc in mine]
    if not ids:
        return {"name": name, "level": level, "days": days, "ours": None,
                "message": "в этой территории наших объектов нет"}

    # ── оснащение: чем мы там стоим ──
    ports = sum(loc.connectors_count or 0 for loc in mine)
    powers = [float(loc.power_kwt) for loc in mine if loc.power_kwt]
    by_speed: dict[str, int] = {}
    by_brand: dict[str, int] = {}
    by_status: dict[str, int] = {}
    connector_types: dict[str, int] = {}
    for loc in mine:
        by_speed[loc.speed_class or "не указан"] = by_speed.get(loc.speed_class or "не указан", 0) + 1
        by_brand[loc.brand or "не указан"] = by_brand.get(loc.brand or "не указан", 0) + 1
        by_status[loc.operational_status or "не указан"] = by_status.get(
            loc.operational_status or "не указан", 0) + 1
        for ct in (loc.connector_types or "").split(","):
            ct = ct.strip()
            if ct:
                connector_types[ct] = connector_types.get(ct, 0) + 1

    # ── реализация: что там происходит ──
    money = func.coalesce(ChargeSession.client_amount, ChargeSession.amount)
    now_row = (await db.execute(
        select(func.count(), func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
               func.coalesce(func.sum(money), 0),
               func.coalesce(func.avg(ChargeSession.duration_min), 0),
               func.count(func.distinct(ChargeSession.user_id)),
               func.coalesce(func.sum(
                   case((ChargeSession.amount > 0, ChargeSession.energy_kwh), else_=0)), 0),
               func.coalesce(func.sum(
                   case((ChargeSession.amount > 0, ChargeSession.amount), else_=0)), 0))
        .where(ChargeSession.company_id == cid, ChargeSession.location_id.in_(ids),
               ChargeSession.started_at >= since))).one()
    sessions, energy, revenue, duration, clients, paid_energy, paid_money = now_row
    prev_sessions, prev_revenue = (await db.execute(
        select(func.count(), func.coalesce(func.sum(money), 0))
        .where(ChargeSession.company_id == cid, ChargeSession.location_id.in_(ids),
               ChargeSession.started_at >= prev_since,
               ChargeSession.started_at < since))).one()

    # ── кто заряжается ──
    by_user_type = {(t or "не указан"): {"sessions": int(c), "revenue": float(a or 0)}
                    for t, c, a in (await db.execute(
                        select(ChargeSession.user_type, func.count(),
                               func.coalesce(func.sum(money), 0))
                        .where(ChargeSession.company_id == cid,
                               ChargeSession.location_id.in_(ids),
                               ChargeSession.started_at >= since)
                        .group_by(ChargeSession.user_type))).all()}

    # ── чем заряжаются и чем кончается ──
    by_connector = {(t or "не указан"): int(c) for t, c in (await db.execute(
        select(ChargeSession.connector_type, func.count())
        .where(ChargeSession.company_id == cid, ChargeSession.location_id.in_(ids),
               ChargeSession.started_at >= since)
        .group_by(ChargeSession.connector_type)
        .order_by(func.count().desc()).limit(8))).all()}
    by_result = {(r or "не указан"): int(c) for r, c in (await db.execute(
        select(ChargeSession.result, func.count())
        .where(ChargeSession.company_id == cid, ChargeSession.location_id.in_(ids),
               ChargeSession.started_at >= since)
        .group_by(ChargeSession.result)
        .order_by(func.count().desc()).limit(8))).all()}

    # ── когда заряжаются: час пик решает, хватает ли портов ──
    hours = [{"hour": int(h), "sessions": int(c)} for h, c in (await db.execute(
        select(func.extract("hour", ChargeSession.started_at), func.count())
        .where(ChargeSession.company_id == cid, ChargeSession.location_id.in_(ids),
               ChargeSession.started_at >= since)
        .group_by(func.extract("hour", ChargeSession.started_at))
        .order_by(func.extract("hour", ChargeSession.started_at)))).all()]

    # ── наши объекты поимённо: где густо, где пусто ──
    per_site = {str(loc): {"sessions": int(c), "revenue": float(a or 0)}
                for loc, c, a in (await db.execute(
                    select(ChargeSession.location_id, func.count(),
                           func.coalesce(func.sum(money), 0))
                    .where(ChargeSession.company_id == cid,
                           ChargeSession.location_id.in_(ids),
                           ChargeSession.started_at >= since)
                    .group_by(ChargeSession.location_id))).all()}
    objects = sorted(({
        "locationId": loc.id, "name": loc.name, "city": loc.city,
        "powerKwt": float(loc.power_kwt) if loc.power_kwt else None,
        "ports": loc.connectors_count, "speedClass": loc.speed_class,
        "brand": loc.brand, "status": loc.operational_status,
        **per_site.get(str(loc.id), {"sessions": 0, "revenue": 0.0}),
    } for loc in mine), key=lambda r: -r["sessions"])

    # ── рынок рядом: то же, что в территориях, но для этой одной ──
    own_ids = await _own_operator_ids(db, cid)
    market = [x for x in (await db.execute(select(MarketSite).where(
        MarketSite.company_id == cid, MarketSite.status == "active",
        MarketSite.kind == "ezs", MarketSite.location_id.is_(None)))).scalars().all()
        if ((x.region if level == "region" else x.city) or "") == name
        and _is_external(x, own_ids)]
    ours_working = sum(1 for loc in mine
                       if (loc.operational_status or "") == "working")
    rivals = [x for x in market if (x.site_class or "") == "network"]
    independent = [x for x in market if (x.site_class or "") == "independent"]
    home = [x for x in market if (x.site_class or "") == "home"]
    last_price = await _last_prices(db, cid)
    rival_prices = [last_price[str(x.id)]["price"] for x in rivals + independent
                    if str(x.id) in last_price]

    days_in = max(days, 1)
    return {
        "name": name, "level": level, "days": days,
        "ours": {
            "objects": len(mine), "ports": ports,
            "powerKwtTotal": round(sum(powers), 1) if powers else None,
            "powerKwtMax": max(powers) if powers else None,
            "bySpeed": by_speed, "byBrand": dict(sorted(
                by_brand.items(), key=lambda kv: -kv[1])[:8]),
            "byStatus": by_status, "connectorTypes": dict(sorted(
                connector_types.items(), key=lambda kv: -kv[1])[:8]),
            "sessions": int(sessions), "energyKwh": float(energy or 0),
            "revenue": float(revenue or 0),
            "avgDurationMin": round(float(duration or 0), 1),
            "clients": int(clients or 0),
            "avgCheck": round(float(revenue or 0) / int(sessions), 0) if sessions else None,
            # Наша цена — по оплаченным: у ЮЛ постоплата, и делить на всю энергию нельзя.
            "pricePerKwh": (round(float(paid_money) / float(paid_energy), 2)
                            if paid_energy and float(paid_energy) > 0 else None),
            # Загрузка: сколько сессий и киловатт-часов приходится на порт в сутки —
            # именно это, а не число станций, говорит, нужна ли ещё одна.
            "sessionsPerPortDay": (round(int(sessions) / ports / days_in, 2)
                                   if ports else None),
            "kwhPerPortDay": (round(float(energy or 0) / ports / days_in, 1)
                              if ports else None),
            "byUserType": by_user_type, "byConnector": by_connector,
            "byResult": by_result, "hours": hours,
            "trend": {
                "prevSessions": int(prev_sessions or 0),
                "prevRevenue": float(prev_revenue or 0),
                "sessionsPct": _pct(float(prev_sessions or 0), float(sessions or 0)),
                "revenuePct": _pct(float(prev_revenue or 0), float(revenue or 0)),
            },
            # Полный список, а не первые шестьдесят: 46 объектов Приморья
            # просто не доезжали до экрана, и человек не мог их увидеть никак
            # (аудит А14). Прокрутка — забота таблицы, не сервера.
            "objectsList": objects,
        },
        "market": {
            "rivalSites": len(rivals), "independentSites": len(independent),
            "homeSockets": len(home),
            "rivalPorts": sum(x.ports or 0 for x in rivals),
            "aliveRivals": sum(1 for x in rivals
                               if x.last_session_at and x.last_session_at >= alive_since),
            "marketPricePerKwh": _median(rival_prices),
            "pricedSites": len(rival_prices),
            # Знаменатель — все внешние зарядки территории, и сетевые, и
            # независимые: водитель выбирает из того, что работает, а не из того,
            # у кого есть сеть. Профиль считал только сетевые и показывал в
            # Приморье 98,1% там, где на общем правиле территорий выходит 83,5%
            # (аудит А04). Домашние розетки в знаменатель не входят нигде.
            # С нашей стороны в долю идут ДЕЙСТВУЮЩИЕ объекты, а не весь реестр:
            # в Приморье из 106 записей 24 выведены из эксплуатации, и включать их
            # в предложение территории — то же самое, что считать конкурентом
            # закрытую чужую станцию (аудит А14). Рынок с другой стороны тоже
            # берётся активный — правило симметрично.
            "sharePct": (round(ours_working / (ours_working + len(rivals)
                                               + len(independent)) * 100, 1)
                         if (ours_working + len(rivals) + len(independent)) else None),
            "oursWorking": ours_working, "oursTotal": len(mine),
        },
    }


@router.get("/our-map")
async def our_map_points(
    company_id: str = Query(...),
    days: int = Query(90, ge=7, le=365),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Наши станции для карты — со всем, что мы о них знаем.

    Свой слой карты фильтруется по СВОИМ данным: состояние и связь, класс скорости,
    производитель, мощность, загрузка порта, выручка, доля сорванных зарядок. Рынок
    такого о нас не знает, и в этом весь смысл отдельного слоя — чужие точки можно
    отобрать только по тому, что видно снаружи, свои — по тому, как они работают.
    """
    cid = await _member(company_id, user, db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    money = func.coalesce(ChargeSession.client_amount, ChargeSession.amount)

    rows = (await db.execute(
        select(ChargeSession.location_id, func.count(),
               func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
               func.coalesce(func.sum(money), 0),
               func.sum(case((ChargeSession.result.ilike("%error%"), 1), else_=0)),
               func.count(func.distinct(ChargeSession.user_id)))
        .where(ChargeSession.company_id == cid, ChargeSession.started_at >= since,
               ChargeSession.location_id.is_not(None))
        .group_by(ChargeSession.location_id))).all()
    stats = {str(loc): {"sessions": int(c), "energy": float(e or 0), "revenue": float(a or 0),
                        "errors": int(err or 0), "clients": int(u or 0)}
             for loc, c, e, a, err, u in rows}

    regions = dict((rid, name) for rid, name in (await db.execute(
        select(Region.id, Region.name).where(Region.company_id == cid))).all())
    locations = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.company_id == cid,
        ServiceLocation.is_test.is_(False),
        ServiceLocation.latitude.is_not(None)))).scalars().all()

    points = []
    for loc in locations:
        st = stats.get(str(loc.id), {"sessions": 0, "energy": 0.0, "revenue": 0.0,
                                     "errors": 0, "clients": 0})
        ports = loc.connectors_count or 0
        points.append({
            "id": loc.id, "name": loc.name, "code": loc.code,
            "city": loc.city, "region": regions.get(loc.region_id),
            "lat": float(loc.latitude), "lon": float(loc.longitude),
            # Паспорт: по нему отбирают «быстрые DC от 100 кВт» или «всё, что Fora»
            "powerKwt": float(loc.power_kwt) if loc.power_kwt else None,
            "ports": ports or None,
            "speedClass": loc.speed_class, "locationClass": loc.location_class,
            "brand": loc.brand, "status": loc.operational_status,
            "commissionedOn": loc.installed_on,
            # Работа: по ней отбирают «где пусто» и «где срывается»
            "sessions": st["sessions"], "energyKwh": round(st["energy"], 1),
            "revenue": round(st["revenue"], 2), "clients": st["clients"],
            "errorPct": (round(st["errors"] / st["sessions"] * 100, 1)
                         if st["sessions"] else None),
            "sessionsPerPortDay": (round(st["sessions"] / ports / days, 2)
                                   if ports else None),
        })

    return {
        "days": days, "points": points, "total": len(points),
        "brands": sorted({p["brand"] for p in points if p["brand"]}),
        "statuses": sorted({p["status"] for p in points if p["status"]}),
        "regions": sorted({p["region"] for p in points if p["region"]}),
    }


# ── Расклад сил, платформы и роуминг ────────────────────────────────────────
# Раздел «Рынок» перестаёт быть списком точек: появляются два слоя, которых в
# открытых источниках нет, — кто на чьей ИТ-платформе работает и кто участвует в
# роуминге. Первое говорит, с кем на самом деле идёт разговор о технологии; второе —
# может ли водитель зарядиться у сети чужим приложением.

@router.get("/landscape")
async def market_landscape(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Кто есть кто на рынке: размер, охват, платформа, роуминг, сервис."""
    cid = await _member(company_id, user, db)
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)

    # Считаем ТОЛЬКО сетевые точки: домашние розетки и независимые в доли не идут —
    # иначе «рынок» окажется наполовину частными розетками (§3.8).
    counts = {str(oid): {"sites": int(sites), "ports": int(ports or 0),
                         "alive": int(alive or 0),
                         "quality": round(float(q), 1) if q is not None else None,
                         "success": round(float(sc), 1) if sc is not None else None,
                         "silent": int(silent or 0)}
              for oid, sites, ports, alive, q, sc, silent in (await db.execute(
                  select(MarketSite.operator_id, func.count(),
                         func.sum(MarketSite.ports),
                         func.sum(case((MarketSite.last_session_at >= alive_since, 1), else_=0)),
                         func.avg(MarketSite.connection_quality_24h),
                         func.avg(MarketSite.success_charge_pct),
                         func.sum(case(
                             (and_(MarketSite.last_session_at.is_not(None),
                                   MarketSite.last_session_at < datetime.now(timezone.utc)
                                   - timedelta(days=180)), 1), else_=0)))
                  .where(MarketSite.company_id == cid,
                         MarketSite.operator_id.is_not(None),
                         MarketSite.site_class == "network",
                         MarketSite.status != "closed")
                  .group_by(MarketSite.operator_id))).all()}

    operators = (await db.execute(select(MarketOperator).where(
        MarketOperator.company_id == cid))).scalars().all()
    last_price = await _last_prices(db, cid)
    site_operator = dict((str(sid), str(oid)) for sid, oid in (await db.execute(
        select(MarketSite.id, MarketSite.operator_id)
        .where(MarketSite.company_id == cid,
               MarketSite.operator_id.is_not(None)))).all())
    prices: dict[str, list[float]] = {}
    for site_id, obs in last_price.items():
        oid = site_operator.get(site_id)
        if oid:
            prices.setdefault(oid, []).append(obs["price"])

    rows = []
    for op in operators:
        c = counts.get(str(op.id), {})
        sites = c.get("sites", 0)
        rows.append({
            "id": str(op.id), "name": op.name, "relation": op.relation,
            "isOurs": op.relation == "own",
            # Всё, что о компании собрано: модель, реквизиты, контакты, источники.
            # Расклад сил без этого отвечал только «сколько у него точек», хотя
            # разговор с агрегатором на чужой платформе и с владельцем сети — это
            # два разных разговора.
            **_operator_facts(op),
            "sites": sites, "ports": c.get("ports", 0), "alive": c.get("alive", 0),
            "silentHalfYear": c.get("silent", 0),
            "quality": c.get("quality"), "success": c.get("success"),
            "medianPricePerKwh": _median(prices.get(str(op.id), [])),
            "appInstalls": op.app_installs,
        })

    # Публичные точки без имени владельца: они и есть причина, по которой размеры
    # сетей — нижняя оценка, а не факт.
    unnamed_sites = int((await db.execute(
        select(func.count()).select_from(MarketSite).where(
            MarketSite.company_id == cid, MarketSite.status == "active",
            MarketSite.kind == "ezs", MarketSite.site_class != "home",
            MarketSite.operator_id.is_(None)))).scalar() or 0)

    networks = [r for r in rows if r["sites"] > 0]
    total_sites = sum(r["sites"] for r in networks) or 1
    for r in networks:
        r["sharePct"] = round(r["sites"] / total_sites * 100, 1)
    networks.sort(key=lambda r: -r["sites"])

    # ── платформы: кто кого обслуживает ──
    platforms: dict[str, dict[str, Any]] = {}
    for r in networks:
        owner = r["platformOwner"]
        if not owner:
            continue
        p = platforms.setdefault(owner, {
            "owner": owner, "networks": 0, "sites": 0, "ownSites": 0,
            "clients": [], "ownerIsNetwork": False,
        })
        p["networks"] += 1
        p["sites"] += r["sites"]
        if r["name"] == owner:
            p["ownSites"] = r["sites"]
            p["ownerIsNetwork"] = True
        else:
            p["clients"].append({"name": r["name"], "sites": r["sites"]})
    for p in platforms.values():
        p["clients"].sort(key=lambda c: -c["sites"])
        # Точки клиентов — то, что платформа обслуживает СВЕРХ собственной сети:
        # именно этот объём делает её инфраструктурой рынка, а не просто сетью.
        p["clientSites"] = p["sites"] - p["ownSites"]
    platform_rows = sorted(platforms.values(), key=lambda p: -p["clientSites"])

    known_platform = sum(r["sites"] for r in networks if r["platformOwner"])
    roaming_yes = [r for r in networks if r["roaming"]]
    roaming_no = [r for r in networks if r["roaming"] is False]

    return {
        "operators": rows, "networks": networks,
        "platforms": platform_rows,
        "totals": {
            "networks": len(networks),
            "networkSites": total_sites,
            "withProfile": sum(1 for r in networks if r["platformOwner"] or r["citiesCount"]),
            "ownPlatform": sum(1 for r in networks if r["ownPlatform"]),
            "platformKnownSites": known_platform,
            "roamingNetworks": len(roaming_yes),
            "roamingSites": sum(r["sites"] for r in roaming_yes),
            "closedNetworks": len(roaming_no),
            "closedSites": sum(r["sites"] for r in roaming_no),
            # Наличие приложения — это `appName`, а не рейтинг: у восьми сетей
            # приложение есть, а оценок в магазине нет, и они выпадали из счёта
            # как будто приложения у них нет вовсе (аудит А11).
            "withApp": sum(1 for r in networks if r["appName"]),
            "withAppRating": sum(1 for r in networks if r["appRating"] is not None),
            "legalTrusted": sum(1 for r in networks if r["legalTrusted"]),
            # Уровни достоверности записей о компаниях (data-quality.md): по
            # первому можно говорить вслух, третий — повод проверить, а не вывод.
            "level1": sum(1 for r in networks if r.get("dataLevel") == 1),
            "level2": sum(1 for r in networks if r.get("dataLevel") == 2),
            "level3": sum(1 for r in networks if r.get("dataLevel") == 3),
            "unnamedSites": unnamed_sites,
        },
        # Главная оговорка расклада: размеры сетей ЗАНИЖЕНЫ, и насколько —
        # неизвестно. Часть публичных точек идёт без имени владельца, и какая-то
        # их доля принадлежит компаниям из этого же списка. Поэтому доли здесь —
        # внутренняя оценка (уровень 2), а не измерение рынка: во внешнем
        # материале их нельзя подавать как точные.
        "note": ("доли считаются по сетевым точкам: домашние розетки и независимые "
                 "точки без оператора в расклад сил не входят. Размеры сетей "
                 f"занижены: у {unnamed_sites} публичных точек владелец не указан, "
                 "и часть из них принадлежит компаниям этого списка — насколько, "
                 "неизвестно. Это внутренняя оценка: для внешних материалов "
                 "говорить «от сотни до девятисот точек у крупнейших сетей», а не "
                 "называть точное число"),
    }


@router.get("/coverage")
async def market_coverage(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Обеспеченность регионов: машин на зарядку и на РАБОТАЮЩУЮ зарядку.

    Два разных дефицита, которые обычно смешивают. Где станций мало — нужно строить.
    Где станции есть, но не работают — строить бессмысленно, надо чинить: Татарстан
    по числу точек выглядит благополучно (8 машин на точку), а по работающим — 30,
    вчетверо хуже. Иркутская область тяжелее всех: 63 машины на живую зарядку.

    Парк берётся по электромобилям без гибридов: региональной разбивки по гибридам в
    открытом доступе нет, а их вдвое больше — подмешав, мы завысили бы спрос вдвое.
    """
    cid = await _member(company_id, user, db)
    alive_since = datetime.now(timezone.utc) - timedelta(days=ALIVE_DAYS)

    stats = (await db.execute(select(MarketRegionStat).where(
        MarketRegionStat.company_id == cid))).scalars().all()
    if not stats:
        return {"regions": [], "total": 0,
                "message": "статистики парка электромобилей нет — загрузите ev-market-regions.csv"}

    # Наша сеть в тех же регионах: сколько наших точек и сколько из них работают.
    regions = dict((rid, name) for rid, name in (await db.execute(
        select(Region.id, Region.name).where(Region.company_id == cid))).all())
    ours: dict[str, dict[str, int]] = {}
    for loc in (await db.execute(select(ServiceLocation).where(
            ServiceLocation.company_id == cid,
            ServiceLocation.is_test.is_(False)))).scalars().all():
        name = regions.get(loc.region_id)
        if not name:
            continue
        row = ours.setdefault(name, {"sites": 0, "working": 0})
        row["sites"] += 1
        if loc.operational_status == "working":
            row["working"] += 1

    # Что рынок говорит о регионе сегодня — против того, что записано в статистике.
    market: dict[str, dict[str, int]] = {}
    for site in (await db.execute(select(MarketSite).where(
            MarketSite.company_id == cid, MarketSite.kind == "ezs",
            MarketSite.status != "closed",
            MarketSite.site_class != "home"))).scalars().all():
        if not site.region:
            continue
        row = market.setdefault(site.region, {"sites": 0, "alive": 0})
        row["sites"] += 1
        if site.last_session_at and site.last_session_at >= alive_since:
            row["alive"] += 1

    def _match(name: str) -> dict[str, int]:
        """Сопоставление названий: «Калининградская обл.» и «Калининградская область»."""
        short = name.replace(" обл.", " область").strip()
        return market.get(name) or market.get(short) or {}

    rows = []
    for stat in stats:
        our = ours.get(stat.region) or ours.get(stat.region.replace(" обл.", " область")) or {}
        live = _match(stat.region)
        cars = stat.ev_cars or 0
        alive = stat.stations_alive or 0
        rows.append({
            "region": stat.region,
            "evCars": stat.ev_cars,
            "evSharePct": float(stat.ev_share_pct) if stat.ev_share_pct is not None else None,
            "stations": stat.stations, "stationsDc": stat.stations_dc,
            "stationsAlive": stat.stations_alive,
            "carsPerStation": float(stat.cars_per_station) if stat.cars_per_station is not None else None,
            "carsPerDc": float(stat.cars_per_dc) if stat.cars_per_dc is not None else None,
            "carsPerAlive": float(stat.cars_per_alive) if stat.cars_per_alive is not None else None,
            # Разрыв между «есть» и «работает»: во сколько раз нагрузка на живую
            # зарядку выше, чем кажется по числу станций.
            "deadGapRatio": (round((cars / alive) / (cars / stat.stations), 1)
                             if cars and alive and stat.stations else None),
            "deadStations": ((stat.stations or 0) - alive) if stat.stations else None,
            "ourSites": our.get("sites", 0), "ourWorking": our.get("working", 0),
            "ourSharePct": (round(our.get("sites", 0) / stat.stations * 100, 1)
                            if stat.stations else None),
            "marketSitesNow": live.get("sites"), "marketAliveNow": live.get("alive"),
            "source": stat.source, "asOf": stat.as_of,
        })
    rows.sort(key=lambda r: -(r["carsPerAlive"] or 0))

    return {
        "regions": rows, "total": len(rows),
        "note": ("парк — электромобили без гибридов (их вдвое больше, региональной "
                 "разбивки по ним нет); таблица покрывает только регионы с известным "
                 "парком, для остальных данных о машинах у нас нет"),
    }


# ── Игроки: кто ещё борется за того же водителя ─────────────────────────────
# Карта зарядок показывает владельцев железа. Но за водителя конкурируют и те, у
# кого станций нет вовсе: агрегаторы на чужой инфраструктуре, топливный процессинг
# с готовой базой корпоративных клиентов, мойки, банки, автопроизводители. Их видно
# только через магазин приложений — и это отдельный слой рынка.

# Классы, которые пришли в зарядку с соседнего рынка: у них своя аудитория и
# платёжный слой, а инфраструктуры нет. Это «смежные игроки», а не конкуренты
# по станциям, и называть их надо именно так.
ADJACENT_CLASSES = {"топливный процессинг", "мойки и мультисервис", "банк / финтех",
                    "сеть АЗС (своё приложение)", "поиск АЗС"}


@router.get("/players")
async def market_players(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Игроки рынка: модели бизнеса, классы и качество приложений."""
    cid = await _member(company_id, user, db)
    rows = (await db.execute(select(MarketPlayer).where(
        MarketPlayer.company_id == cid))).scalars().all()
    if not rows:
        return {"players": [], "total": 0,
                "message": "карта игроков не загружена — нужен ev-market-players.csv"}

    operators = {o.id: o for o in (await db.execute(select(MarketOperator).where(
        MarketOperator.company_id == cid))).scalars().all()}

    players = []
    for r in rows:
        op = operators.get(r.operator_id) if r.operator_id else None
        stations = r.own_stations if r.own_stations is not None else (
            None if op is None else None)
        players.append({
            "id": str(r.id), "app": r.app, "package": r.package,
            "class": r.player_class or "прочее",
            "classChecked": r.class_checked,
            "adjacent": (r.player_class or "") in ADJACENT_CLASSES,
            "ownStations": stations,
            "assetLight": r.asset_light,
            "operatorId": str(r.operator_id) if r.operator_id else None,
            "operatorName": op.name if op else r.matched_operator,
            "brand": r.brand, "developer": r.developer, "developerInn": r.developer_inn,
            "rating": float(r.rating) if r.rating is not None else (
                float(op.app_rating) if op is not None and op.app_rating is not None else None),
            "reviews": r.reviews if r.reviews is not None else (
                op.app_reviews if op is not None else None),
            "modelNote": r.model_note, "note": r.note, "source": r.source,
        })

    # ── четыре квадранта: своя инфраструктура против своего приложения ──
    # Приложение есть у всех в этой выборке — их так и нашли. Поэтому вторая ось —
    # ЕСТЬ ЛИ СТАНЦИИ, и она делит рынок на тех, кто владеет железом, и тех, кто
    # борется за интерфейс к чужому.
    with_assets = [p for p in players if (p["ownStations"] or 0) > 0]
    light = [p for p in players if (p["ownStations"] or 0) == 0]

    def unique_stations(group: list[dict[str, Any]]) -> int:
        """Станции по УНИКАЛЬНЫМ сетям, а не по приложениям.

        У одной сети бывает два приложения в магазине — у нас самих их два
        (`com.rucharge.rusgidro` и `ru.rushydro.car`), — и суммирование по строкам
        удваивает её станции (проверка 13.09.2026).
        """
        seen: set[str] = set()
        total = 0
        for p in group:
            key = p["operatorName"] or p["app"]
            if key in seen:
                continue
            seen.add(key)
            total += p["ownStations"] or 0
        return total
    quadrants = [
        {"key": "full", "label": "свои станции и своё приложение",
         "hint": "полный стек: владеют железом и говорят с водителем сами",
         "players": sorted(with_assets, key=lambda p: -(p["ownStations"] or 0))[:40],
         "count": len(with_assets),
         "networks": len({p["operatorName"] or p["app"] for p in with_assets}),
         "stations": unique_stations(with_assets)},
        {"key": "light", "label": "приложение без своих станций",
         "hint": "конкуренция за интерфейс: агрегаторы, процессинг, банки, автопроизводители",
         "players": sorted(light, key=lambda p: (p["class"], p["app"]))[:60],
         "count": len(light), "stations": 0},
    ]

    # ── классы и откуда приходят ──
    by_class: dict[str, dict[str, Any]] = {}
    for p in players:
        c = by_class.setdefault(p["class"], {
            "class": p["class"], "players": 0, "assetLight": 0, "stations": 0,
            "adjacent": p["adjacent"], "rated": [], "examples": [], "_seen": set(),
        })
        c["players"] += 1
        if (p["ownStations"] or 0) == 0:
            c["assetLight"] += 1
        # Сеть с двумя приложениями не должна удваивать станции класса.
        key = p["operatorName"] or p["app"]
        if key not in c["_seen"]:
            c["_seen"].add(key)
            c["stations"] += p["ownStations"] or 0
        if p["rating"] is not None:
            c["rated"].append(p["rating"])
        if len(c["examples"]) < 6:
            c["examples"].append(p["app"])
    class_rows = []
    for c in by_class.values():
        rated = c.pop("rated")
        c.pop("_seen", None)
        median = _median(rated)
        class_rows.append({**c, "medianRating": round(median, 2) if median is not None else None,
                           "withRating": len(rated)})
    class_rows.sort(key=lambda c: -c["players"])

    # ── витрины: чем игрок торгует кроме киловатт ──
    # Вторая выручка и одновременно маркер модели: у чистых агрегаторов витрины нет
    # вовсе, а у владельцев инфраструктуры она норма. Поэтому «нет витрины» — тоже
    # значение, и оно показывается наравне с «есть».
    shops = []
    for shop in (await db.execute(select(MarketShop).where(
            MarketShop.company_id == cid))).scalars().all():
        op = operators.get(shop.operator_id) if shop.operator_id else None
        shops.append({
            "brand": shop.brand, "host": shop.host, "url": shop.url,
            "hasShop": shop.has_shop, "goods": shop.goods,
            "priceMin": float(shop.price_min) if shop.price_min is not None else None,
            "priceMax": float(shop.price_max) if shop.price_max is not None else None,
            "pricesFound": shop.prices_found, "note": shop.note,
            "checkedOn": shop.checked_on,
            "sites": None if op is None else next(
                (p["ownStations"] for p in players
                 if p["operatorName"] == op.name and p["ownStations"]), None),
        })
    shops.sort(key=lambda r: (not r["hasShop"], -(r["pricesFound"] or 0)))

    # ── качество против размера: рейтинг рядом с числом станций ──
    # Сравнивать рейтинги между классами напрямую нельзя: у приложения с пятью
    # оценками и с тремястами разная достоверность, поэтому число отзывов рядом.
    quality = sorted((p for p in players if p["rating"] is not None),
                     key=lambda p: -(p["reviews"] or 0))[:40]
    ratings = [p["rating"] for p in players if p["rating"] is not None]

    return {
        "players": players, "total": len(players),
        "quadrants": quadrants, "classes": class_rows, "quality": quality,
        "shops": shops,
        "totals": {
            "withStations": len(with_assets), "assetLight": len(light),
            "adjacent": sum(1 for p in players if p["adjacent"]),
            "medianRating": (round(_median(ratings), 2)
                             if _median(ratings) is not None else None),
            "withRating": len(ratings),
            # Сети, у которых больше одного приложения: раздвоенная точка контакта
            # с водителем — сама по себе находка.
            "withShop": sum(1 for r in shops if r["hasShop"]),
            "shopsChecked": len(shops),
            "multiApp": sorted({p["operatorName"] or p["app"] for p in players
                                if sum(1 for o in players
                                       if (o["operatorName"] or o["app"])
                                       == (p["operatorName"] or p["app"])) > 1}),
            "unchecked": sum(1 for p in players if not p["classChecked"]),
        },
        "note": ("класс проставлен автоматически по названию и пакету — перед тем как "
                 "называть конкретное имя, его надо подтвердить; наличие приложения "
                 "не означает работы на рынке зарядок: сети АЗС и мойки здесь как "
                 "смежные игроки; выборка сделана по RuStore и не видит App Store "
                 "и Google Play; витрины проверены только у сетей с подтверждённым "
                 "доменом, «нет витрины» значит «не нашли на типовых адресах», а цены "
                 "сняты автоматически и годятся как диапазон, не как прайс-лист"),
    }


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
