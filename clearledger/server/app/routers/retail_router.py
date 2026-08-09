"""/api/retail/* — розничное направление ЭЗС (ФЛ): аналитика в разрезе аккаунтов
частных лиц. Телефоны псевдонимизированы (хеш-ID + маска). Питает пункт
«Частные лица» в разделе «Продажи».
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services.retail_service import RetailService

router = APIRouter(prefix="/retail", tags=["Частные лица"])


def _d(s: str, field: str) -> date:
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field}: {s}") from exc


def _csv(s: str | None) -> list[str] | None:
    """Comma-separated query → список (пусто → None = без сужения)."""
    if not s:
        return None
    vals = [x.strip() for x in s.split(",") if x.strip()]
    return vals or None


@router.get("/overview")
async def retail_overview(
    company_id: str, date_from: str, date_to: str,
    stations: str | None = None, regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """KPI розничной базы ФЛ: аккаунты/активные/новые, выручка, ARPA, средний чек."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).overview(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=_csv(stations), regions=_csv(regions))


@router.get("/segments")
async def retail_segments(
    company_id: str, date_from: str, date_to: str,
    stations: str | None = None, regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """RFM-сегментация аккаунтов ФЛ (Чемпионы/Лояльные/Под риском/…/Отток)."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).segments(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=_csv(stations), regions=_csv(regions))


@router.get("/economics")
async def retail_economics(
    company_id: str, date_from: str, date_to: str,
    stations: str | None = None, regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Концентрация выручки (Pareto топ-X%→Y%) + распределение сессий-на-аккаунт."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).economics(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=_csv(stations), regions=_csv(regions))


@router.get("/geo")
async def retail_geo(
    company_id: str, date_from: str, date_to: str,
    stations: str | None = None, regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Гео-станционная привязка: моно- vs мульти-станция + топ-регионы розницы."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).geo(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=_csv(stations), regions=_csv(regions))


@router.get("/cohorts")
async def retail_cohorts(
    company_id: str, months: int = 12,
    stations: str | None = None, regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Удержание по когортам месяца первой сессии (retention-матрица, вся история)."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).cohorts(
        cid, months, stations=_csv(stations), regions=_csv(regions))


@router.get("/customers")
async def retail_customers(
    company_id: str, months: int = 24,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Клиентская база витрины: регистрации по месяцам, активация, карты.

    Не зависит от периода рабочей области: база — это состояние справочника, а
    не события за интервал."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).customers(cid, months)


@router.get("/accounts")
async def retail_accounts(
    company_id: str, date_from: str, date_to: str,
    region: str | None = None, station: str | None = None, segment: str | None = None,
    min_sessions: int = 0, search: str | None = None,
    sort: str = "revenue", order: str = "desc", limit: int = 200,
    stations: str | None = None, regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Реестр аккаунтов ФЛ: фильтры (сегмент/регион/станция/мин-сессий/поиск) + сортировка."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).accounts(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        region=region, station=station, segment=segment, min_sessions=min_sessions,
        search=search, sort=sort, order=order, limit=min(max(limit, 1), 2000),
        stations=_csv(stations), regions=_csv(regions))


@router.get("/dimensions")
async def retail_dimensions(
    company_id: str, date_from: str, date_to: str,
    stations: str | None = None, regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Справочники для фильтров: регионы и станции (с числом аккаунтов/сессий)."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).dimensions(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=_csv(stations), regions=_csv(regions))


@router.get("/profile")
async def retail_profile(
    company_id: str, date_from: str, date_to: str,
    station: str | None = None, region: str | None = None,
    stations: str | None = None, regions: str | None = None,
    tz: str = "msk",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Разрез по станции/региону: KPI + профиль по часам/дням недели + топ аккаунтов.
    tz=local — профиль по местному времени станции."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).profile(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"), station=station, region=region,
        stations=_csv(stations), regions=_csv(regions), tz=tz if tz in ("msk", "local") else "msk")


@router.get("/account")
async def retail_account(
    company_id: str, date_from: str, date_to: str, account: str,
    stations: str | None = None, regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Детальная карточка аккаунта ФЛ (по хеш-ID): разбивки + последние сессии."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).account(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"), account,
        stations=_csv(stations), regions=_csv(regions))


@router.get("/marketing")
async def retail_marketing(
    company_id: str, date_from: str, date_to: str,
    stations: str | None = None, regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """B2C-KPI розничной базы + автоматические маркетинговые выводы."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).marketing(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=_csv(stations), regions=_csv(regions))


@router.get("/dashboard")
async def retail_dashboard(
    company_id: str, date_from: str, date_to: str,
    stations: str | None = None, regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """BI-витрина «Обзора ФЛ»: динамика/дельты, retention, CLV, heatmap, поведение, концентрация."""
    cid = await assert_company_member(company_id, current_user, db)
    return await RetailService(db).dashboard(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=_csv(stations), regions=_csv(regions))
