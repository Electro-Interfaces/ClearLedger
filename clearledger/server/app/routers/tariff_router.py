"""/api/tariffs/* — тарифная аналитика ЭЗС (ценообразование сети, розница).
Прайс-сетка регион×коннектор + факт vs номинал. Питает пункт «Тарифы».
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services.tariff_service import TariffService

router = APIRouter(prefix="/tariffs", tags=["Тарифы"])


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


@router.get("/grid")
async def tariff_grid(
    company_id: str,
    date_from: str,
    date_to: str,
    by: str = Query("region", pattern="^(region|station)$"),
    user_type: str | None = None,
    stations: str | None = None,
    regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Тарифная сетка: <region|station> × коннектор → преобладающий тариф + диапазон + объём."""
    cid = await assert_company_member(company_id, current_user, db)
    return await TariffService(db).price_grid(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"), by, user_type,
        stations=_csv(stations), regions=_csv(regions))


@router.get("/fact-vs-nominal")
async def tariff_fact_vs_nominal(
    company_id: str,
    date_from: str,
    date_to: str,
    group_by: str = Query("region", pattern="^(region|station|connector|user_type)$"),
    user_type: str | None = None,
    stations: str | None = None,
    regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """По разрезу: номинал (энерговзвеш. tariff) vs факт (выручка÷энергия) + отклонение."""
    cid = await assert_company_member(company_id, current_user, db)
    return await TariffService(db).fact_vs_nominal(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"), group_by, user_type,
        stations=_csv(stations), regions=_csv(regions))


@router.get("/pricelist-vs-fact")
async def tariff_pricelist_vs_fact(
    company_id: str,
    date_from: str,
    date_to: str,
    stations: str | None = None,
    regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Объявленный прайс АСУиМ против фактической цены: регион × тип разъёма.

    Прайс сопоставляется с регионом по названию тарифа — привязки к станциям
    витрина не отдаёт. Несколько версий цены показываются диапазоном."""
    cid = await assert_company_member(company_id, current_user, db)
    return await TariffService(db).pricelist_vs_fact(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=_csv(stations), regions=_csv(regions))
