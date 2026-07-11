"""
Раздел «Магазин» — аналитика товароучёта сопутки/общепита.

Пока: «Обзор магазина» (GoodsDashboardService) — выручка/категории/оплаты/НДС/
динамика/станции по продажам из канала ЦБ ЭЛСИ.АЗК (DataEntry clean).
Далее: ABC, маржа/GMROI (FIFO с поступлениями), остатки, инвентаризация.
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.services.goods_dashboard import GoodsDashboardService

router = APIRouter(prefix="/store", tags=["Магазин"])


@router.get("/overview")
async def store_overview(
    date_from: str = Query(..., description="ISO дата начала периода"),
    date_to: str = Query(..., description="ISO дата конца периода"),
    stations: str | None = Query(None, description="коды АЗС через запятую (опц.)"),
    compare: bool = Query(False, description="сравнить с предыдущим периодом (Δ%)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """KPI обзора магазина за период (продажи сопутки/общепита)."""
    cid: uuid.UUID = user.company_id
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, cid).compute(
        date.fromisoformat(date_from), date.fromisoformat(date_to), st, compare,
    )


@router.get("/skus")
async def store_skus(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр SKU с маржой и ABC (питает Ассортимент / Цены-маржа / Номенклатуру)."""
    cid: uuid.UUID = user.company_id
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, cid).sku_analytics(
        date.fromisoformat(date_from), date.fromisoformat(date_to), st,
    )


@router.get("/sales")
async def store_sales(
    date_from: str = Query(...),
    date_to: str = Query(...),
    group_by: str = Query("sku", description="sku|category|kind|marking|vat|day|payment"),
    category: str = Query("all", description="all|soputka|obshepit"),
    marked: str = Query("all", description="all|marked|plain"),
    q: str = Query(""),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Анализ продаж с гибкой группировкой и фильтрами (инструмент менеджера)."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, user.company_id).sales_analysis(
        date.fromisoformat(date_from), date.fromisoformat(date_to),
        group_by=group_by, category=category, marked=marked, q=q, stations=st,
    )


@router.get("/nomenclature")
async def store_nomenclature(
    date_from: str = Query(...),
    date_to: str = Query(...),
    kind: str = Query("all"),
    marked: str = Query("all"),
    weighed: str = Query("all"),
    has_sales: str = Query("all"),
    q: str = Query(""),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Полный справочник номенклатуры + обогащение продажами/ШК + фильтры (мастер-НСИ)."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, user.company_id).nomenclature_catalog(
        date.fromisoformat(date_from), date.fromisoformat(date_to),
        kind=kind, marked=marked, weighed=weighed, has_sales=has_sales, q=q, stations=st,
    )


@router.get("/stock")
async def store_stock(
    warehouse: str | None = Query(None, description="код склада (по умолч. — с макс. SKU, обычно 208)"),
    q: str = Query(""),
    marked: str = Query("all", description="all|marked|plain"),
    only_negative: bool = Query(False, description="только отрицательные остатки"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Достоверный остаток товара (снимок регистров ЦБ ТоварыНаАЗК+Партии), не оценка."""
    return await GoodsDashboardService(db, user.company_id).stock_onhand(
        warehouse=warehouse, q=q, marked=marked, only_negative=only_negative,
    )


def _stations(stations: str | None) -> list[str] | None:
    return [s.strip() for s in stations.split(",") if s.strip()] if stations else None


@router.get("/{report}")
async def store_report(
    report: str,
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отчёты раздела: receipts · suppliers · catering · categories · barcodes · recipes."""
    svc = GoodsDashboardService(db, user.company_id)
    method = {"receipts": svc.receipts, "suppliers": svc.suppliers,
              "catering": svc.catering, "categories": svc.categories,
              "barcodes": svc.barcodes, "recipes": svc.recipes}.get(report)
    if method is None:
        from fastapi import HTTPException
        raise HTTPException(404, f"Неизвестный отчёт: {report}")
    return await method(date.fromisoformat(date_from), date.fromisoformat(date_to), _stations(stations))
