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
    return await OverviewService(db).overview(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"), compare)


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
