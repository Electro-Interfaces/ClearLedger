"""
Управленческий кокпит ЭЗС (раздел «Управленческий», energy) — обзор ситуации,
конкретные расхождения и рабочие списки для управленческих решений.
Изолированный слой поверх L2 (station_energy_periods + charge_sessions +
station_contract_settlements) — см. services/ops_dashboard.py.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services.ops_dashboard import (
    ops_balance, ops_completeness, ops_overview, ops_station,
)

router = APIRouter(prefix="/ops", tags=["Управленческий кокпит (ЭЗС)"])


@router.get("/overview")
async def get_ops_overview(
    company_id: str = Query(...),
    region: str | None = Query(None, description="фильтр: регион (federalSubject)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Обзор: помесячная серия вход/отпуск/СН/сверхнорматив/деньги + светофор
    проблем с рабочими списками (нет данных · небаланс · простой · не оплачено ·
    договор истёк · нет тарифа · сироты)."""
    cid = await assert_company_member(company_id, current_user, db)
    return await ops_overview(db, cid, region=region)


@router.get("/balance")
async def get_ops_balance(
    company_id: str = Query(...),
    period: str | None = Query(None, description="месяц 'YYYY-MM-01'; пусто = последний полный"),
    region: str | None = Query(None, description="фильтр: регион (federalSubject)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Пообъектный энергобаланс за месяц: вход · отпуск · собственные нужды
    (оценка) · сверхнормативный небаланс · стоимость · выручка · маржа."""
    cid = await assert_company_member(company_id, current_user, db)
    return await ops_balance(db, cid, period, region=region)


@router.get("/completeness")
async def get_ops_completeness(
    company_id: str = Query(...),
    date_from: str | None = Query(None, alias="from", description="месяц 'YYYY-MM-01'"),
    date_to: str | None = Query(None, alias="to", description="месяц 'YYYY-MM-01'"),
    region: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """«Полнота данных»: каких документов/данных не хватает за период анализа —
    матрица «вид данных × месяц» + списки недостающего (станция → месяцы)."""
    cid = await assert_company_member(company_id, current_user, db)
    return await ops_completeness(db, cid, date_from, date_to, region=region)


@router.get("/station/{location_id}")
async def get_ops_station(
    location_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Карточка объекта (drill-down): паспорт + помесячный энергобаланс +
    договорные контуры (э/э / аренда / сервис) с контрагентами и оплатами."""
    cid = await assert_company_member(company_id, current_user, db)
    return await ops_station(db, cid, location_id)
