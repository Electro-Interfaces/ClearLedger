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

from app.auth import assert_company_product, get_current_user
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
    regions: str | None = None,
    top: int = Query(15, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Качество использования портов: idle (занят без зарядки), фактическая
    мощность против номинала, dwell time. Занятость ≠ работа — на быстрых
    портах простой стоит дороже всего (см. services/port_efficiency.py)."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    from app.services.port_efficiency import port_efficiency

    codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    regs = [x.strip() for x in regions.split(",") if x.strip()] if regions else None
    return await port_efficiency(
        db, cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=codes, top=top, regions=regs)


@router.get("/overview/silent-stations")
async def silent_stations_list(
    company_id: str,
    date_from: str,
    date_to: str,
    stations: str | None = None,
    regions: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Станции парка без единой сессии за период — раскрывается с карточки обзора.

    Разделены на «не работали никогда» (вопрос запуска) и «замолчали» (вопрос
    поломки или демонтажа): это разные задачи для разных служб."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    from app.services.overview_insights import silent_stations

    codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    regs = [x.strip() for x in regions.split(",") if x.strip()] if regions else None
    return await silent_stations(
        db, cid, _d(date_from, "date_from"), _d(date_to, "date_to"), limit=limit,
        stations=codes, regions=regs)


@router.get("/overview")
async def charge_overview(
    company_id: str,
    date_from: str,
    date_to: str,
    compare: str = Query("prev", pattern="^(prev)$"),
    stations: str | None = None,
    regions: str | None = None,
    tz: str = Query("msk", pattern="^(msk|local)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Executive-сводка сети ЭЗС за период с дельтами к прошлому периоду.
    tz=local — профиль активности (часы/дни недели) по местному времени станций."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    regs = [x.strip() for x in regions.split(",") if x.strip()] if regions else None
    # today передаём явно → входит в ключ кэша: run_rate пересчитывается при смене
    # суток, а не застревает на прошлой дате в пределах TTL.
    return await OverviewService(db).overview(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"), compare,
        today=date.today(), stations=codes, regions=regs, tz=tz)


@router.get("/station-metrics")
async def station_metrics(
    company_id: str,
    date_from: str,
    date_to: str,
    stations: str | None = None,
    regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Агрегаты сессий по станции (location_id) за период — для раскраски/размера точек на карте."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    regs = [x.strip() for x in regions.split(",") if x.strip()] if regions else None
    return await OverviewService(db).station_metrics(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=codes, regions=regs)


@router.get("/owners")
async def owners_breakdown(
    company_id: str,
    date_from: str,
    date_to: str,
    stations: str | None = None,
    regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Парк по владельцу: свои (РусГидро) vs партнёрские (СНК) — станции, простой,
    сессии, надёжность за период."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    regs = [x.strip() for x in regions.split(",") if x.strip()] if regions else None
    return await OverviewService(db).owners_breakdown(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=codes, regions=regs)


@router.get("/speed")
async def speed_breakdown(
    company_id: str,
    date_from: str,
    date_to: str,
    stations: str | None = None,
    regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Парк по скорости: медленные (AC) vs быстрые (DC) — станции, простой,
    сессии, надёжность за период."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    regs = [x.strip() for x in regions.split(",") if x.strip()] if regions else None
    return await OverviewService(db).speed_breakdown(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        stations=codes, regions=regs)


@router.get("/speed/stations")
async def speed_stations_list(
    company_id: str,
    date_from: str,
    date_to: str,
    cls: str = Query("fast", pattern="^(fast|slow|unknown)$"),
    stations: str | None = None,
    regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Список станций одной скорости (fast|slow|unknown) — по клику с карточки «Парк по скорости»."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    regs = [x.strip() for x in regions.split(",") if x.strip()] if regions else None
    return await OverviewService(db).speed_stations(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"), cls,
        regions=regs, stations=codes)


@router.get("/abc-xyz")
async def abc_xyz_report(
    company_id: str,
    date_from: str,
    date_to: str,
    measure: str = Query("amount", pattern="^(amount|energy)$"),
    bucket: str = Query("week", pattern="^(week|month)$"),
    stations: str | None = None,
    regions: str | None = None,
    a_pct: float = Query(80.0, ge=1, le=99),
    b_pct: float = Query(95.0, ge=1, le=99.9),
    x_cv: float = Query(0.5, ge=0.05, le=5),
    y_cv: float = Query(1.0, ge=0.1, le=10),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """ABC-XYZ классификация станций: вклад в результат (ABC) × стабильность
    спроса (XYZ). measure=amount|energy, bucket=week|month (для XYZ)."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    from app.services.station_abcxyz import station_abc_xyz

    codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    regs = [x.strip() for x in regions.split(",") if x.strip()] if regions else None
    return await station_abc_xyz(
        db, cid, _d(date_from, "date_from"), _d(date_to, "date_to"),
        measure=measure, bucket=bucket, stations=codes, regions=regs,
        a_pct=a_pct, b_pct=b_pct, x_cv=x_cv, y_cv=y_cv)


@router.get("/owners/stations")
async def owner_stations_list(
    company_id: str,
    date_from: str,
    date_to: str,
    cls: str = Query("own", pattern="^(own|partner|unknown)$"),
    stations: str | None = None,
    regions: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Список станций одного владельца (own|partner|unknown) с их работой за
    период — раскрывается по клику с карточки «Парк по владельцу»."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    regs = [x.strip() for x in regions.split(",") if x.strip()] if regions else None
    return await OverviewService(db).owner_stations(
        cid, _d(date_from, "date_from"), _d(date_to, "date_to"), cls,
        regions=regs, stations=codes)
