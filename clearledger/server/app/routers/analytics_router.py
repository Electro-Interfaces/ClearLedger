"""
/api/analytics/* — единая точка KPI для 4 режимов воркспейса:
  management — P&L (выручка/себестоимость/маржа) + payment mix
  financial  — cash flow + дебиторка/кредиторка
  tax        — позиция НДС + налог на прибыль
  forecast   — прогноз закрытия текущего/выбранного месяца

Все расчёты делегируются в AnalyticsService, ответы — простой JSON для UI.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Company, User
from app.services.analytics_service import AnalyticsService, PeriodFilter

router = APIRouter(prefix="/analytics", tags=["Аналитика"])


# ─── helpers ─────────────────────────────────────────────────────────

async def _resolve_company_id(value: str, db: AsyncSession) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        pass
    result = await db.execute(select(Company).where(Company.slug == value))
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Unknown company: {value}")
    return company.id


def _parse_iso_date(s: str, field: str) -> date:
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field}: {s}") from exc


async def _filter_from_query(
    company_id: str, date_from: str, date_to: str, station_id: str | None,
    db: AsyncSession,
) -> PeriodFilter:
    cid = await _resolve_company_id(company_id, db)
    df = _parse_iso_date(date_from, "date_from")
    dt = _parse_iso_date(date_to, "date_to")
    sid: uuid.UUID | None = None
    if station_id:
        try:
            sid = uuid.UUID(station_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid station_id") from exc
    return PeriodFilter(company_id=cid, date_from=df, date_to=dt, station_id=sid)


# ─── management ──────────────────────────────────────────────────────

@router.get("/pnl")
async def get_pnl(
    company_id: str,
    date_from: str,
    date_to: str,
    group_by: str = Query("station", pattern="^(station|fuel|month)$"),
    station_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """P&L: выручка, себестоимость, маржа. group_by=station|fuel|month."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db)
    svc = AnalyticsService(db)
    return await svc.pnl(f, group_by=group_by)


@router.get("/payment-mix")
async def get_payment_mix(
    company_id: str,
    date_from: str,
    date_to: str,
    station_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Маркетинг: доли cash/card/voucher + средний чек по сменам."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db)
    svc = AnalyticsService(db)
    return await svc.payment_mix(f)


# ─── financial ───────────────────────────────────────────────────────

@router.get("/cash-flow")
async def get_cash_flow(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Обороты по 50/51/52/57/55."""
    f = await _filter_from_query(company_id, date_from, date_to, None, db)
    svc = AnalyticsService(db)
    return await svc.cash_flow(f)


@router.get("/payables-receivables")
async def get_payables_receivables(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Дебиторка (62) и кредиторка (60.01) по контрагентам."""
    f = await _filter_from_query(company_id, date_from, date_to, None, db)
    svc = AnalyticsService(db)
    return await svc.payables_receivables(f)


# ─── tax ─────────────────────────────────────────────────────────────

@router.get("/vat")
async def get_vat(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Позиция НДС: исходящий (68.02) − входящий (19.03)."""
    f = await _filter_from_query(company_id, date_from, date_to, None, db)
    svc = AnalyticsService(db)
    return await svc.vat_position(f)


@router.get("/profit")
async def get_profit(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Налог на прибыль: оценочный финрезультат."""
    f = await _filter_from_query(company_id, date_from, date_to, None, db)
    svc = AnalyticsService(db)
    return await svc.profit_position(f)


# ─── forecast ────────────────────────────────────────────────────────

@router.get("/forecast/month")
async def get_month_forecast(
    company_id: str,
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    station_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Прогноз закрытия месяца: экстраполяция, недостающие документы, риски."""
    cid = await _resolve_company_id(company_id, db)
    sid: uuid.UUID | None = None
    if station_id:
        try:
            sid = uuid.UUID(station_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid station_id") from exc
    svc = AnalyticsService(db)
    return await svc.month_forecast(cid, year, month, sid)
