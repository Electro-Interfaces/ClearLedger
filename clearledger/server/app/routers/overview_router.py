"""/api/analytics/charge-sessions/overview — executive-дашборд сети ЭЗС.

Единый эндпоинт управленческого пункта «Обзор»: KPI с Δ% к прошлому периоду +
спарклайны, гейджи, тренд с оверлеем, доли, топ/дно станций, корпоратив, алерты.
Изолирован от analytics_router (его правит параллельная работа) — вызывает
`OverviewService`, который переиспользует `AnalyticsService`/`CorporateService`.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services.overview_service import OverviewService

router = APIRouter(prefix="/analytics/charge-sessions", tags=["Обзор ЭЗС"])


def _d(s: str, field: str) -> date:
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field}: {s}") from exc


@router.get("/port-efficiency")
async def port_efficiency_report(
    company_id: str,
    date_from: str,
    date_to: str,
    stations: str | None = None,
    top: int = Query(15, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Качество использования портов: idle (занят без зарядки), фактическая
    мощность против номинала, dwell time. Занятость ≠ работа — на быстрых
    портах простой стоит дороже всего (см. services/port_efficiency.py)."""
    cid = await assert_company_member(company_id, current_user, db)
    from app.services.port_efficiency import port_efficiency

    codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    return await port_efficiency(
        db, cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=codes, top=top)


@router.get("/overview/silent-stations")
async def silent_stations_list(
    company_id: str,
    date_from: str,
    date_to: str,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Станции парка без единой сессии за период — раскрывается с карточки обзора.

    Разделены на «не работали никогда» (вопрос запуска) и «замолчали» (вопрос
    поломки или демонтажа): это разные задачи для разных служб."""
    cid = await assert_company_member(company_id, current_user, db)
    from app.services.overview_insights import silent_stations

    return await silent_stations(
        db, cid, _d(date_from, "date_from"), _d(date_to, "date_to"), limit=limit)


@router.get("/overview")
async def charge_overview(
    company_id: str,
    date_from: str,
    date_to: str,
    compare: str = Query("prev", pattern="^(prev)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Executive-сводка сети ЭЗС за период с дельтами к прошлому периоду."""
    cid = await assert_company_member(company_id, current_user, db)
    # today передаём явно → входит в ключ кэша: run_rate пересчитывается при смене
    # суток, а не застревает на прошлой дате в пределах TTL.
    return await OverviewService(db).overview(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"), compare,
        today=date.today())


@router.get("/station-metrics")
async def station_metrics(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Агрегаты сессий по станции (location_id) за период — для раскраски/размера точек на карте."""
    cid = await assert_company_member(company_id, current_user, db)
    return await OverviewService(db).station_metrics(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"))
