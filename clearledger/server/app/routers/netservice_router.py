"""
/api/netservice/* — Сервисный центр (управление сервисом сети, MVP: 3-я линия HubEx).

- capabilities — какие линии доступны (для скрытия раздела/подпунктов в UI).
- hubex/sync — ручной запуск синхронизации заявок/справочников в Postgres.
- analytics/* — агрегаты состояния сети, SLA, надёжности (по hubex_tasks).
- tasks — рабочий список заявок с фильтрами/пагинацией.

Разрезы (регион/точка/тип/подрядчик) — query-параметры, период по умолчанию 90 дней.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import ServiceLocation, User
from app.services import hubex_service, hubex_sync
from app.services.netservice_analytics_service import NetServiceAnalytics, NetServiceFilter

router = APIRouter(prefix="/netservice", tags=["Сервисный центр"])


def _parse_date(s: str | None, default: date) -> date:
    if not s:
        return default
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid date: {s}") from exc


async def _filter(
    company_id: str, date_from: str | None, date_to: str | None,
    region: str | None, location_id: str | None, location_type: str | None,
    contractor: str | None, db: AsyncSession, user: User,
) -> NetServiceFilter:
    cid = await assert_company_member(company_id, user, db)
    today = date.today()
    dt = _parse_date(date_to, today)
    df = _parse_date(date_from, today - timedelta(days=90))
    return NetServiceFilter(
        company_id=cid, date_from=df, date_to=dt, region=region,
        location_id=location_id, location_type=location_type, contractor=contractor,
    )


@router.get("/capabilities")
async def capabilities(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Доступность линий поддержки (для подключаемости раздела)."""
    cid = await assert_company_member(company_id, current_user, db)
    has_assets = (await db.execute(text(
        "SELECT count(*) FROM service_locations "
        "WHERE company_id = :cid AND extra_metadata->>'hubexAssetId' IS NOT NULL"
    ), {"cid": str(cid)})).scalar_one()
    return {
        "hubex": bool(hubex_service.is_configured() and has_assets),
        "line1": False,  # телефония МегаФон + КЦ — Фаза 2
        "line2": False,  # удалённая диагностика — Фаза 3
        "assetsLinked": int(has_assets),
    }


@router.post("/hubex/sync")
async def hubex_sync_run(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Запустить синхронизацию HubEx (справочники + заявки) в Postgres."""
    cid = await assert_company_member(company_id, current_user, db)
    if not hubex_service.is_configured():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="HubEx не сконфигурирован")
    return await hubex_sync.sync_all(db, cid)


@router.get("/analytics/network-health")
async def network_health(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    region: str | None = None,
    location_id: str | None = None,
    location_type: str | None = None,
    contractor: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    f = await _filter(company_id, date_from, date_to, region, location_id,
                      location_type, contractor, db, current_user)
    return await NetServiceAnalytics(db).network_health(f)


@router.get("/analytics/sla")
async def sla(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    breakdown: str = Query("criticality", pattern="^(criticality|contractor|task_type)$"),
    region: str | None = None,
    location_id: str | None = None,
    location_type: str | None = None,
    contractor: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    f = await _filter(company_id, date_from, date_to, region, location_id,
                      location_type, contractor, db, current_user)
    return await NetServiceAnalytics(db).sla(f, breakdown=breakdown)


@router.get("/analytics/asset-reliability")
async def asset_reliability(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    top: int = Query(10, ge=1, le=100),
    region: str | None = None,
    location_id: str | None = None,
    location_type: str | None = None,
    contractor: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    f = await _filter(company_id, date_from, date_to, region, location_id,
                      location_type, contractor, db, current_user)
    return await NetServiceAnalytics(db).asset_reliability(f, top=top)


@router.get("/tasks")
async def tasks(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    status_filter: str = Query("all", alias="status", pattern="^(all|open|closed|overdue)$"),
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    region: str | None = None,
    location_id: str | None = None,
    location_type: str | None = None,
    contractor: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    f = await _filter(company_id, date_from, date_to, region, location_id,
                      location_type, contractor, db, current_user)
    return await NetServiceAnalytics(db).tasks_list(
        f, status=status_filter, q=q, limit=limit, offset=offset)
