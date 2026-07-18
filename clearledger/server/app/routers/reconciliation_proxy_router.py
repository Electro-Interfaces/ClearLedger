"""
Прокси-API для модуля «Сверки» (TradeCorp + MSTO).

Фронт сверки (перенесён из TradeFrame) ходит сюда: /api/tradecorp/*, /api/msto/*.
Секреты внешних API остаются на сервере. Требует авторизации (JWT).
Отдельно от reconciliation_router.py (сверка 1С-документов) — другой домен.

Все обращения скоупятся по компании (scope_company_id): подключение к внешнему
API берётся из источника ЭТОЙ компании, глобальные креды из .env не подставляются.
"""
from __future__ import annotations

import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.deps import capture_company_header, scope_company_id
from app.models import User
from app.services import reconciliation_proxy as proxy

logger = logging.getLogger("reconciliation_proxy_api")

# capture_company_header кладёт X-Company-Id в contextvar до тела эндпоинта.
router = APIRouter(tags=["Сверка (прокси)"],
                   dependencies=[Depends(capture_company_header)])

_STATION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")


class TradecorpTxRequest(BaseModel):
    dateFrom: str
    dateTo: str
    stationIds: list | None = None

    @field_validator("stationIds")
    @classmethod
    def _check_station_ids(cls, v: list | None) -> list | None:
        """stationIds уходит внутрь JSON-RPC filter — пускаем только скаляры-идентификаторы,
        иначе клиент может подменить структуру фильтра."""
        if v is None:
            return v
        if len(v) > 500:
            raise ValueError("Слишком много станций в stationIds (максимум 500)")
        for item in v:
            if isinstance(item, bool) or not isinstance(item, (str, int)):
                raise ValueError("stationIds должен содержать номера станций (строки или числа)")
            if not _STATION_ID_RE.match(str(item)):
                raise ValueError(f"Недопустимый номер станции: {item!r}")
        return v


def _upstream_error(exc: Exception) -> HTTPException:
    if isinstance(exc, proxy.MissingCompanyConnection):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, httpx.HTTPStatusError):
        return HTTPException(status_code=502, detail=f"Upstream error: {exc.response.status_code}")
    if isinstance(exc, httpx.RequestError):
        return HTTPException(status_code=503, detail="Внешний сервис недоступен")
    return HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────── TradeCorp ───────────────────────────
@router.post("/tradecorp/transactions")
async def tradecorp_transactions(body: TradecorpTxRequest, user: User = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    cid = await scope_company_id(user, db)
    try:
        conn = await proxy.tradecorp_conn_for_company(db, cid)
        return await proxy.tradecorp_transactions(body.dateFrom, body.dateTo, body.stationIds,
                                                  conn=conn)
    except Exception as exc:  # noqa: BLE001
        logger.error("[TradeCorp transactions] %s", exc)
        raise _upstream_error(exc)


@router.post("/tradecorp/transactions/summary")
async def tradecorp_summary(body: TradecorpTxRequest, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    cid = await scope_company_id(user, db)
    try:
        conn = await proxy.tradecorp_conn_for_company(db, cid)
        return await proxy.tradecorp_summary(body.dateFrom, body.dateTo, body.stationIds, conn=conn)
    except Exception as exc:  # noqa: BLE001
        logger.error("[TradeCorp summary] %s", exc)
        raise _upstream_error(exc)


@router.get("/tradecorp/health")
async def tradecorp_health(user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    cid = await scope_company_id(user, db)
    try:
        conn = await proxy.tradecorp_conn_for_company(db, cid)
        return await proxy.tradecorp_health(conn=conn)
    except proxy.MissingCompanyConnection as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc))


# ─────────────────────────── MSTO ───────────────────────────
@router.get("/msto/servicePoints")
async def msto_service_points(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid = await scope_company_id(user, db)
    try:
        conn = await proxy.msto_conn_for_company(db, cid)
        return await proxy.msto_service_points(conn=conn)
    except Exception as exc:  # noqa: BLE001
        logger.error("[MSTO servicePoints] %s", exc)
        raise _upstream_error(exc)


@router.get("/msto/transactions")
async def msto_transactions(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid = await scope_company_id(user, db)
    try:
        conn = await proxy.msto_conn_for_company(db, cid)
        return await proxy.msto_transactions(dict(request.query_params), conn=conn, company_id=cid)
    except Exception as exc:  # noqa: BLE001
        logger.error("[MSTO transactions] %s", exc)
        raise _upstream_error(exc)


@router.get("/msto/tariffs")
async def msto_tariffs(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid = await scope_company_id(user, db)
    try:
        conn = await proxy.msto_conn_for_company(db, cid)
        return await proxy.msto_tariffs(dict(request.query_params), conn=conn, company_id=cid)
    except Exception as exc:  # noqa: BLE001
        logger.error("[MSTO tariffs] %s", exc)
        raise _upstream_error(exc)
