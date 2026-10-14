"""
API отчётов складского учёта оборудования ЭЗС: остатки на дату, оборотная
ведомость, что числится за контрагентом, единицы в ремонте.

Авторизация — членство в компании, как в equipment_router. Расчёт —
services/ezs_equipment_reports.py.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services import ezs_equipment_reports as R

router = APIRouter(prefix="/equipment/reports", tags=["Оборудование ЭЗС"])


def _day(value: str | None, what: str = "Дата") -> str:
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(400, f"{what} указана неверно")


@router.get("/stock")
async def stock(
    company_id: str = Query(...), date: str | None = None, location_id: str | None = None,
    counterparty_id: str | None = None, contract_id: str | None = None,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    return await R.stock_report(db, cid, _day(date), location_id or None, counterparty_id or None, contract_id or None)


@router.get("/turnover")
async def turnover(
    company_id: str = Query(...), date_from: str | None = None, date_to: str | None = None,
    location_id: str | None = None,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    end = _day(date_to, "Дата окончания периода")
    start = _day(date_from, "Дата начала периода") if date_from else end[:8] + "01"
    if start > end:
        raise HTTPException(400, "Начало периода позже окончания")
    return await R.turnover_report(db, cid, start, end, location_id or None)


@router.get("/holders")
async def holders(
    company_id: str = Query(...), date: str | None = None,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    return await R.holders_report(db, cid, _day(date))


@router.get("/repairs")
async def repairs(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    return await R.repairs_report(db, cid)
