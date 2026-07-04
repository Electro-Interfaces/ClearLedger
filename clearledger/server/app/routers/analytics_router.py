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
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, assert_company_module, get_current_user
from app.database import get_db
from app.models import User
from app.services.analytics_service import AnalyticsService, PeriodFilter

router = APIRouter(prefix="/analytics", tags=["Аналитика"])


# ─── helpers ─────────────────────────────────────────────────────────

def _parse_iso_date(s: str, field: str) -> date:
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field}: {s}") from exc


# Разрезы и метрики зарядных сессий (переиспользуются в /timeseries и /compare).
_CS_METRIC_PATTERN = "^(sessions|energy_kwh|amount|avg_check|avg_energy|avg_duration_min|success_pct|price_per_kwh)$"
_CS_GROUP_PATTERN = "^(station|region|connector|user_type|client|charge_type|tariff|result)$"
# Оси сводной таблицы (строки/столбцы): разрезы + временные бакеты.
_CS_PIVOT_DIM = "^(station|region|connector|user_type|client|charge_type|result|cut|tariff|month|week|day|decade|quarter|hour|weekday)$"


def _csv(s: str | None) -> list[str] | None:
    """Comma-separated query → список (пусто → None = без сужения)."""
    if not s:
        return None
    items = [x.strip() for x in s.split(",") if x.strip()]
    return items or None


def _parse_periods(s: str) -> list[tuple[date, date]]:
    """periods=from:to,from:to,... → список (from,to). 2–4 диапазона, иначе 400."""
    out: list[tuple[date, date]] = []
    for chunk in s.split(","):
        a, _, b = chunk.partition(":")
        out.append((_parse_iso_date(a, "period.from"), _parse_iso_date(b, "period.to")))
    if not (2 <= len(out) <= 4):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="periods: ожидается 2–4 диапазона from:to")
    return out


async def _filter_from_query(
    company_id: str, date_from: str, date_to: str, station_id: str | None,
    db: AsyncSession, current_user: User, module: str | None = None,
) -> PeriodFilter:
    cid = (
        await assert_company_module(company_id, current_user, db, module) if module
        else await assert_company_member(company_id, current_user, db)
    )
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
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """P&L: выручка, себестоимость, маржа. group_by=station|fuel|month."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db, current_user, "management")
    svc = AnalyticsService(db)
    return await svc.pnl(f, group_by=group_by)


@router.get("/fuel-balance")
async def get_fuel_balance(
    company_id: str,
    date_from: str,
    date_to: str,
    group_by: str = Query("station", pattern="^(station|fuel|station_fuel)$"),
    station_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Топливный баланс: приход(ТТН) − реализация ± остатки = недостача. group_by=station|fuel|station_fuel."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db, current_user, "management")
    svc = AnalyticsService(db)
    return await svc.fuel_balance(f, group_by=group_by)


@router.get("/sales-channels")
async def get_sales_channels(
    company_id: str,
    date_from: str,
    date_to: str,
    station_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Продажи по каналам оплаты: объём/сумма/доля/ср.цена ₽/л. Комиссии/категории — на клиенте."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db, current_user, "management")
    svc = AnalyticsService(db)
    return await svc.sales_channels(f)


@router.get("/charge-sessions")
async def get_charge_sessions(
    company_id: str,
    date_from: str,
    date_to: str,
    group_by: str = Query("station", pattern="^(station|region|connector|user_type|client|charge_type|tariff|hour|day|result)$"),
    station_id: str | None = None,
    stations: str | None = None,
    regions: str | None = None,
    dim: str | None = None,
    dim_val: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Зарядные сессии ЭЗС по разрезу: выручка/энергия/сессии/ср.чек/успех."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db, current_user, "management")
    f.station_codes = _csv(stations); f.regions = _csv(regions)
    f.dim_by = dim; f.dim_val = dim_val
    svc = AnalyticsService(db)
    return await svc.charge_sessions(f, group_by=group_by)


@router.get("/charge-sessions/timeseries")
async def get_charge_timeseries(
    company_id: str,
    date_from: str,
    date_to: str,
    bucket: str = Query("day", pattern="^(day|week|decade|month|quarter)$"),
    series_by: str | None = Query(None, pattern=_CS_GROUP_PATTERN),
    metric: str = Query("amount", pattern=_CS_METRIC_PATTERN),
    top_n: int = Query(5, ge=1, le=10),
    station_id: str | None = None,
    stations: str | None = None,
    regions: str | None = None,
    dim: str | None = None,
    dim_val: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Динамика метрики зарядных сессий по бакетам времени (+ разбивка по разрезу — multi-series)."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db, current_user, "management")
    f.station_codes = _csv(stations); f.regions = _csv(regions)
    f.dim_by = dim; f.dim_val = dim_val
    svc = AnalyticsService(db)
    return await svc.charge_timeseries(f, bucket=bucket, series_by=series_by, metric=metric, top_n=top_n)


@router.get("/charge-sessions/slice")
async def get_charge_slice(
    company_id: str,
    date_from: str,
    date_to: str,
    bucket: str = Query("month", pattern="^(day|week|decade|month|quarter)$"),
    group_by: str | None = Query(None, pattern=_CS_GROUP_PATTERN),
    metric: str = Query("amount", pattern=_CS_METRIC_PATTERN),
    top_n: int = Query(25, ge=1, le=1000),
    station_id: str | None = None,
    stations: str | None = None,
    regions: str | None = None,
    dim: str | None = None,
    dim_val: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Нарезка периода на интервалы (неделя/декада/месяц/квартал) и сравнение по разрезу.
    group_by отсутствует → «Вся сеть» (одна строка-итог)."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db, current_user, "management")
    f.station_codes = _csv(stations); f.regions = _csv(regions)
    f.dim_by = dim; f.dim_val = dim_val
    svc = AnalyticsService(db)
    return await svc.charge_sessions_slice(f, bucket=bucket, group_by=group_by, metric=metric, top_n=top_n)


@router.get("/charge-sessions/compare")
async def get_charge_sessions_compare(
    company_id: str,
    periods: str | None = None,
    a_from: str | None = None,
    a_to: str | None = None,
    b_from: str | None = None,
    b_to: str | None = None,
    group_by: str = Query("station", pattern=_CS_GROUP_PATTERN),
    metric: str = Query("amount", pattern=_CS_METRIC_PATTERN),
    stations: str | None = None,
    regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сравнение периодов зарядных сессий. periods=from:to,... (2–4) → мульти-режим;
    иначе — два периода a_from/a_to/b_from/b_to (обратная совместимость)."""
    cid = await assert_company_module(company_id, current_user, db, "management")
    svc = AnalyticsService(db)
    if periods:
        return await svc.charge_sessions_compare_multi(
            cid, _parse_periods(periods), group_by=group_by, metric=metric,
            station_codes=_csv(stations), regions=_csv(regions),
        )
    if not (a_from and a_to and b_from and b_to):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="нужны periods или a_from/a_to/b_from/b_to")
    return await svc.charge_sessions_compare(
        cid,
        _parse_iso_date(a_from, "a_from"), _parse_iso_date(a_to, "a_to"),
        _parse_iso_date(b_from, "b_from"), _parse_iso_date(b_to, "b_to"),
        group_by=group_by,
    )


@router.get("/charge-sessions/heatmap")
async def get_charge_heatmap(
    company_id: str,
    date_from: str,
    date_to: str,
    metric: str = Query("sessions", pattern=_CS_METRIC_PATTERN),
    station_id: str | None = None,
    stations: str | None = None,
    regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Загрузка час × день недели (heatmap) для ToU-анализа."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db, current_user, "management")
    f.station_codes = _csv(stations); f.regions = _csv(regions)
    return await AnalyticsService(db).charge_heatmap(f, metric=metric)


@router.get("/charge-sessions/dimensions")
async def get_charge_dimensions(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Справочник фильтра раздела для ЭЗС: станции (код+имя) и каноничные регионы."""
    cid = await assert_company_module(company_id, current_user, db, "management")
    return await AnalyticsService(db).charge_dimensions(cid)


@router.get("/charge-sessions/model")
async def get_charge_model(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Модель данных ЭЗС для раздела «Нормализация»: слои L1→L4, звёздная схема
    (факт + измерения), качество нормализации. По всему датасету компании."""
    cid = await assert_company_module(company_id, current_user, db, "management")
    return await AnalyticsService(db).charge_model(cid)


@router.get("/stations/model")
async def get_stations_model(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Модель данных станций ЭЗС (объекты) для «Нормализации»: слои L1→L4, звёздная
    схема (факт «Станция» + измерения), качество паспорта. По всему датасету компании."""
    from app.services.stations_model_service import stations_model
    cid = await assert_company_module(company_id, current_user, db, "management")
    return await stations_model(db, cid)


@router.get("/stations/linkage")
async def get_stations_linkage(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Связь каналов по станции (конформная размерность): покрытие и разрывы —
    сессии/оплаты/справочник ссылаются на общий объект-станцию."""
    from app.services.stations_model_service import stations_linkage
    cid = await assert_company_module(company_id, current_user, db, "management")
    return await stations_linkage(db, cid)


@router.get("/charge-sessions/pivot")
async def get_charge_pivot(
    company_id: str,
    date_from: str,
    date_to: str,
    rows: str = Query("region", pattern=_CS_PIVOT_DIM),
    cols: str | None = Query(None, pattern=_CS_PIVOT_DIM),
    metric: str = Query("amount", pattern=_CS_METRIC_PATTERN),
    stations: str | None = None,
    regions: str | None = None,
    station_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сводная таблица сессий ЭЗС (строки × столбцы × мера) для экспорта из
    «Нормализации». cols пусто → одномерная. Оси — разрезы + временные бакеты."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db, current_user, "management")
    f.station_codes = _csv(stations); f.regions = _csv(regions)
    return await AnalyticsService(db).charge_pivot(f, rows=rows, cols=cols or None, metric=metric)


@router.get("/charge-sessions/rows")
async def get_charge_rows(
    company_id: str,
    date_from: str,
    date_to: str,
    limit: int = Query(100000, ge=1, le=500000),
    stations: str | None = None,
    regions: str | None = None,
    station_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Детальные строки нормализованных сессий (L2) за период — лист «Сессии»
    в шаблонах экспорта сводной из «Нормализации»."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db, current_user, "management")
    f.station_codes = _csv(stations); f.regions = _csv(regions)
    return await AnalyticsService(db).charge_rows(f, limit=limit)


@router.get("/payment-mix")
async def get_payment_mix(
    company_id: str,
    date_from: str,
    date_to: str,
    station_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Маркетинг: доли cash/card/voucher + средний чек по сменам."""
    f = await _filter_from_query(company_id, date_from, date_to, station_id, db, current_user, "management")
    svc = AnalyticsService(db)
    return await svc.payment_mix(f)


# ─── financial ───────────────────────────────────────────────────────

@router.get("/cash-flow")
async def get_cash_flow(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Обороты по 50/51/52/57/55."""
    f = await _filter_from_query(company_id, date_from, date_to, None, db, current_user, "financial")
    svc = AnalyticsService(db)
    return await svc.cash_flow(f)


@router.get("/payables-receivables")
async def get_payables_receivables(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Дебиторка (62) и кредиторка (60.01) по контрагентам."""
    f = await _filter_from_query(company_id, date_from, date_to, None, db, current_user, "financial")
    svc = AnalyticsService(db)
    return await svc.payables_receivables(f)


# ─── tax ─────────────────────────────────────────────────────────────

@router.get("/vat")
async def get_vat(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Позиция НДС: исходящий (68.02) − входящий (19.03)."""
    f = await _filter_from_query(company_id, date_from, date_to, None, db, current_user, "tax")
    svc = AnalyticsService(db)
    return await svc.vat_position(f)


@router.get("/profit")
async def get_profit(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Налог на прибыль: оценочный финрезультат."""
    f = await _filter_from_query(company_id, date_from, date_to, None, db, current_user, "tax")
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
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Прогноз закрытия месяца: экстраполяция, недостающие документы, риски."""
    cid = await assert_company_module(company_id, current_user, db, "accounting")
    sid: uuid.UUID | None = None
    if station_id:
        try:
            sid = uuid.UUID(station_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid station_id") from exc
    svc = AnalyticsService(db)
    return await svc.month_forecast(cid, year, month, sid)
