"""
Прокси-API для модуля «Сверки» (TradeCorp + MSTO).

Фронт сверки (перенесён из TradeFrame) ходит сюда: /api/tradecorp/*, /api/msto/*.
Секреты внешних API остаются на сервере. Требует авторизации (JWT).
Отдельно от reconciliation_router.py (сверка 1С-документов) — другой домен.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.services import reconciliation_proxy as proxy

logger = logging.getLogger("reconciliation_proxy_api")

router = APIRouter(tags=["Сверка (прокси)"])


class TradecorpTxRequest(BaseModel):
    dateFrom: str
    dateTo: str
    stationIds: list | None = None


def _upstream_error(exc: Exception) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        return HTTPException(status_code=502, detail=f"Upstream error: {exc.response.status_code}")
    if isinstance(exc, httpx.RequestError):
        return HTTPException(status_code=503, detail="Внешний сервис недоступен")
    return HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────── TradeCorp ───────────────────────────
@router.post("/tradecorp/transactions")
async def tradecorp_transactions(body: TradecorpTxRequest, user: User = Depends(get_current_user)):
    try:
        return await proxy.tradecorp_transactions(body.dateFrom, body.dateTo, body.stationIds)
    except Exception as exc:  # noqa: BLE001
        logger.error("[TradeCorp transactions] %s", exc)
        raise _upstream_error(exc)


@router.post("/tradecorp/transactions/summary")
async def tradecorp_summary(body: TradecorpTxRequest, user: User = Depends(get_current_user)):
    try:
        return await proxy.tradecorp_summary(body.dateFrom, body.dateTo, body.stationIds)
    except Exception as exc:  # noqa: BLE001
        logger.error("[TradeCorp summary] %s", exc)
        raise _upstream_error(exc)


@router.get("/tradecorp/health")
async def tradecorp_health(user: User = Depends(get_current_user)):
    try:
        return await proxy.tradecorp_health()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc))


# ─────────────────────────── MSTO ───────────────────────────
@router.get("/msto/servicePoints")
async def msto_service_points(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        conn = await proxy.msto_conn_for_company(db, user.company_id)
        return await proxy.msto_service_points(conn=conn)
    except Exception as exc:  # noqa: BLE001
        logger.error("[MSTO servicePoints] %s", exc)
        raise _upstream_error(exc)


@router.get("/msto/transactions")
async def msto_transactions(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        conn = await proxy.msto_conn_for_company(db, user.company_id)
        return await proxy.msto_transactions(dict(request.query_params), conn=conn)
    except Exception as exc:  # noqa: BLE001
        logger.error("[MSTO transactions] %s", exc)
        raise _upstream_error(exc)


@router.get("/msto/tariffs")
async def msto_tariffs(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        conn = await proxy.msto_conn_for_company(db, user.company_id)
        return await proxy.msto_tariffs(dict(request.query_params), conn=conn)
    except Exception as exc:  # noqa: BLE001
        logger.error("[MSTO tariffs] %s", exc)
        raise _upstream_error(exc)
