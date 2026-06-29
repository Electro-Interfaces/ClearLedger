"""Онлайн-заказы агрегаторов из MSTO IntegratorService (Я.Заправки/Benzuber/FuelUp).

Внешний источник входного контура для сверки ОНЛАЙН-КАНАЛА сменного отчёта.
Данные тянет серверный прокси `reconciliation_proxy.msto_transactions`
(креды MSTO — в settings, JWT кэшируется). Ingest идемпотентен по `external_id`
(MSTO sessionId). Журнал отдаётся на вкладку «Данные» канала.
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import OnlineOrder, User, FuelStation, FuelMapping, ServiceLocation
from app.services import reconciliation_proxy

router = APIRouter(prefix="/online-orders", tags=["Онлайн-заказы"])


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _int(v: Any) -> int | None:
    s = str(v or "").strip()
    return int(s) if s.lstrip("-").isdigit() else None


def _parse_dt(s: Any) -> datetime | None:
    if not s:
        return None
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(s), fmt)
        except ValueError:
            continue
    return None


def _norm_fuel(s: Any) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


# Ключи в config привязки локации, где может лежать MSTO servicePointId.
MSTO_SP_KEYS = ("servicePointId", "mstoServicePointId", "msto_service_point_id")


async def _build_resolvers(
    db: AsyncSession, company_id: uuid.UUID,
) -> tuple[dict[int, uuid.UUID], dict[str, int]]:
    """Справочники соответствия источника:
    - servicePointId MSTO → station_id (через привязки локаций → код → FuelStation);
    - имя топлива MSTO → канон service_code (по эталону FuelMapping компании)."""
    code_to_station: dict[int, uuid.UUID] = {}
    for s in (await db.execute(
        select(FuelStation).where(FuelStation.company_id == company_id)
    )).scalars().all():
        try:
            code_to_station[int(s.code)] = s.id
        except (ValueError, TypeError):
            pass

    sp_to_station: dict[int, uuid.UUID] = {}
    for loc in (await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == company_id)
    )).scalars().all():
        try:
            st_id = code_to_station.get(int(str(loc.code)))
        except (ValueError, TypeError):
            st_id = None
        if st_id is None:
            continue
        spids: set[Any] = set()
        for b in (loc.source_bindings or []):
            cfg = (b or {}).get("config") or {}
            for k in MSTO_SP_KEYS:
                if cfg.get(k):
                    spids.add(cfg[k])
        meta = loc.meta or {}
        if meta.get("mstoServicePointId"):
            spids.add(meta["mstoServicePointId"])
        for v in (meta.get("mstoServicePointIds") or []):
            if v:
                spids.add(v)
        for v in spids:
            try:
                sp_to_station[int(v)] = st_id
            except (ValueError, TypeError):
                pass

    fuel_to_code: dict[str, int] = {}
    for f in (await db.execute(
        select(FuelMapping).where(FuelMapping.company_id == company_id)
    )).scalars().all():
        if f.fuel_name:
            fuel_to_code[_norm_fuel(f.fuel_name)] = f.service_code
    return sp_to_station, fuel_to_code


def _normalize(tx: dict[str, Any], company_id: uuid.UUID,
               sp_to_station: dict[int, uuid.UUID],
               fuel_to_code: dict[str, int]) -> dict[str, Any] | None:
    ext = tx.get("sessionId") or tx.get("id")
    if not ext:
        return None
    spid = _int(tx.get("servicePointId"))
    return {
        "company_id": company_id,
        "station_id": sp_to_station.get(spid) if spid is not None else None,
        "external_id": str(ext),
        "service_point_id": spid,
        "service_point_name": tx.get("servicePointName"),
        "post_number": _int(tx.get("postNumber")),
        "aggregator": tx.get("tariff") or tx.get("tariffName"),
        "fuel_name": tx.get("service"),
        "fuel_code": fuel_to_code.get(_norm_fuel(tx.get("service"))),
        "order_date": _parse_dt(tx.get("dateTime")),
        "ordered_sum": _num(tx.get("sum")),
        "ordered_volume": _num(tx.get("value")),
        "actual_sum": _num(tx.get("resultSum")),
        "actual_volume": _num(tx.get("resultValue")),
        "operation_result": tx.get("operationResult"),
        "raw_data": tx,
    }


async def ingest_online_orders(
    db: AsyncSession, company_id: uuid.UUID,
    date_from: str | None, date_to: str | None,
    service_point_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Загрузить онлайн-заказы MSTO за период в online_orders (идемпотентно по external_id)."""
    query: dict[str, Any] = {"operationResult": "sw"}  # success + wait
    if date_from:
        query["dateFrom"] = date_from
    if date_to:
        query["dateTo"] = date_to
    if service_point_ids:
        query["servicePointIds"] = [str(s) for s in service_point_ids]

    conn = await reconciliation_proxy.msto_conn_for_company(db, company_id)
    data = await reconciliation_proxy.msto_transactions(query, conn=conn)
    if isinstance(data, dict):
        models = data.get("models") or []
    elif isinstance(data, list):
        models = data
    else:
        models = []
    sp_to_station, fuel_to_code = await _build_resolvers(db, company_id)
    rows = [r for r in (_normalize(tx, company_id, sp_to_station, fuel_to_code) for tx in models) if r]
    if not rows:
        return {"created": 0, "skipped": 0, "fetched": 0}

    # Дедуп по external_id (натуральный ключ MSTO sessionId).
    ext_ids = {r["external_id"] for r in rows}
    existing = set((await db.execute(
        select(OnlineOrder.external_id).where(
            OnlineOrder.company_id == company_id,
            OnlineOrder.external_id.in_(ext_ids),
        )
    )).scalars().all())

    created = 0
    for r in rows:
        if r["external_id"] in existing:
            continue
        db.add(OnlineOrder(**r))
        existing.add(r["external_id"])
        created += 1
    await db.flush()
    return {"created": created, "skipped": len(rows) - created, "fetched": len(rows)}


def _to_response(o: OnlineOrder) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "external_id": o.external_id,
        "station_id": str(o.station_id) if o.station_id else None,
        "service_point_id": o.service_point_id,
        "service_point_name": o.service_point_name,
        "post_number": o.post_number,
        "aggregator": o.aggregator,
        "fuel_name": o.fuel_name,
        "fuel_code": o.fuel_code,
        "order_date": o.order_date.isoformat() if o.order_date else None,
        "ordered_sum": float(o.ordered_sum or 0),
        "ordered_volume": float(o.ordered_volume or 0),
        "actual_sum": float(o.actual_sum or 0),
        "actual_volume": float(o.actual_volume or 0),
        "operation_result": o.operation_result,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


@router.get("")
async def list_online_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """Журнал загруженных онлайн-заказов (вкладка «Данные» канала MSTO)."""
    q = select(OnlineOrder).where(OnlineOrder.company_id == user.company_id)
    if date_from:
        try:
            q = q.where(OnlineOrder.order_date >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.where(OnlineOrder.order_date <= datetime.fromisoformat(date_to + "T23:59:59"))
        except ValueError:
            pass
    q = q.order_by(OnlineOrder.order_date.desc().nullslast()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [_to_response(o) for o in rows]


@router.get("/count")
async def count_online_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    n = (await db.execute(
        select(func.count()).select_from(OnlineOrder)
        .where(OnlineOrder.company_id == user.company_id)
    )).scalar_one()
    return {"orders": int(n or 0)}


@router.get("/check")
async def check_availability(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Проверка ДОСТУПНОСТИ данных MSTO (без сохранения): авторизация + наличие
    точек обслуживания и заказов за период. Для внешнего контрольного источника
    сверки — грузить всё не требуется, важно лишь что данные на связи."""
    df = date_from or (date.today() - timedelta(days=1)).isoformat()
    dt = date_to or date.today().isoformat()
    try:
        conn = await reconciliation_proxy.msto_conn_for_company(db, user.company_id)
        sp = await reconciliation_proxy.msto_service_points(conn=conn)
        sp_models = sp.get("models") if isinstance(sp, dict) else sp
        sp_count = len(sp_models or [])

        data = await reconciliation_proxy.msto_transactions(
            {"operationResult": "sw", "dateFrom": df, "dateTo": dt}, conn=conn
        )
        models = data.get("models") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        models = models or []
        by_agg: dict[str, int] = {}
        for tx in models:
            a = tx.get("tariff") or "—"
            by_agg[a] = by_agg.get(a, 0) + 1

        return {
            "available": True,
            "service_points": sp_count,
            "orders": len(models),
            "period": [df, dt],
            "aggregators": by_agg,
        }
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)[:300], "period": [df, dt]}
