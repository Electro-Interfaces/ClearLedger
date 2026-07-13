"""Онлайн-заказы агрегаторов из MSTO IntegratorService (Я.Заправки/Benzuber/FuelUp).

Внешний источник входного контура для сверки ОНЛАЙН-КАНАЛА сменного отчёта.
Данные тянет серверный прокси `reconciliation_proxy.msto_transactions`
(креды MSTO — в settings, JWT кэшируется). Ingest идемпотентен по `external_id`
(MSTO sessionId). Журнал отдаётся на вкладку «Данные» канала.
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
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
        meta = loc.extra_metadata or {}
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


def _location_service_point_ids(location: ServiceLocation) -> set[int]:
    values: set[Any] = set()
    for binding in location.source_bindings or []:
        config = (binding or {}).get("config") or {}
        for key in MSTO_SP_KEYS:
            if config.get(key) is not None:
                values.add(config[key])
    metadata = location.extra_metadata or {}
    if metadata.get("mstoServicePointId") is not None:
        values.add(metadata["mstoServicePointId"])
    values.update(metadata.get("mstoServicePointIds") or [])
    return {parsed for value in values if (parsed := _int(value)) is not None}


async def _company_service_point_ids(
    db: AsyncSession, company_id: uuid.UUID, station_code: str | None = None,
) -> list[int]:
    query = (
        select(ServiceLocation).where(
            ServiceLocation.company_id == company_id,
        )
    )
    if station_code:
        query = query.where(ServiceLocation.code == station_code)
    locations = (await db.execute(query)).scalars().all()
    return sorted({spid for location in locations for spid in _location_service_point_ids(location)})


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
    if service_point_ids is None:
        service_point_ids = await _company_service_point_ids(db, company_id)
    if not service_point_ids:
        return {
            "created": 0,
            "updated": 0,
            "fetched": 0,
            "warning": "Для компании не заданы servicePointId MSTO",
        }
    query: dict[str, Any] = {}
    if date_from:
        query["dateFrom"] = date_from
    if date_to:
        query["dateTo"] = date_to
    conn = await reconciliation_proxy.msto_conn_for_company(db, company_id)
    if service_point_ids:
        async def load_point(service_point_id: int) -> list[dict[str, Any]]:
            page = 0
            size = 2000
            result: list[dict[str, Any]] = []
            while True:
                point_query = {
                    **query,
                    "servicePointIds": [str(service_point_id)],
                    "page": page,
                    "size": size,
                }
                data = await reconciliation_proxy.msto_transactions(point_query, conn=conn)
                point_models = data.get("models") if isinstance(data, dict) else data
                models = point_models if isinstance(point_models, list) else []
                for tx in models:
                    tx["servicePointId"] = service_point_id
                result.extend(models)
                total = _int(data.get("totalCount")) if isinstance(data, dict) else None
                if not models or len(result) >= (total or len(result)) or len(models) < size:
                    break
                page += 1
            return result

        point_results = await asyncio.gather(
            *(load_point(service_point_id) for service_point_id in service_point_ids),
            return_exceptions=True,
        )
        successful = [result for result in point_results if isinstance(result, list)]
        if not successful:
            first_error = next((result for result in point_results if isinstance(result, Exception)), None)
            if first_error:
                raise first_error
        models = [tx for result in successful for tx in result]
    else:
        data = await reconciliation_proxy.msto_transactions(query, conn=conn)
        models = data.get("models") if isinstance(data, dict) else data
        models = models if isinstance(models, list) else []
    sp_to_station, fuel_to_code = await _build_resolvers(db, company_id)
    normalized = [r for r in (_normalize(tx, company_id, sp_to_station, fuel_to_code) for tx in models) if r]
    rows = list({r["external_id"]: r for r in normalized}.values())
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

    for offset in range(0, len(rows), 500):
        stmt = insert(OnlineOrder).values(rows[offset:offset + 500])
        stmt = stmt.on_conflict_do_update(
            index_elements=[OnlineOrder.company_id, OnlineOrder.external_id],
            set_={
                "station_id": stmt.excluded.station_id,
                "service_point_id": stmt.excluded.service_point_id,
                "service_point_name": stmt.excluded.service_point_name,
                "post_number": stmt.excluded.post_number,
                "aggregator": stmt.excluded.aggregator,
                "fuel_name": stmt.excluded.fuel_name,
                "fuel_code": stmt.excluded.fuel_code,
                "order_date": stmt.excluded.order_date,
                "ordered_sum": stmt.excluded.ordered_sum,
                "ordered_volume": stmt.excluded.ordered_volume,
                "actual_sum": stmt.excluded.actual_sum,
                "actual_volume": stmt.excluded.actual_volume,
                "operation_result": stmt.excluded.operation_result,
                "raw_data": stmt.excluded.raw_data,
                "updated_at": func.now(),
            },
        )
        await db.execute(stmt)
    created = len(ext_ids - existing)
    await db.flush()
    return {"created": created, "updated": len(rows) - created, "fetched": len(rows)}


def _to_response(
    o: OnlineOrder, station_code: int | None = None, station_name: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "external_id": o.external_id,
        "station_id": str(o.station_id) if o.station_id else None,
        "station_code": station_code,
        "station_name": station_name,
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
    company_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    station_code: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """Журнал загруженных онлайн-заказов (вкладка «Данные» канала MSTO)."""
    cid = await assert_company_member(company_id, user, db) if company_id else user.company_id
    q = (
        select(OnlineOrder, FuelStation.code, FuelStation.name)
        .outerjoin(FuelStation, FuelStation.id == OnlineOrder.station_id)
        .where(OnlineOrder.company_id == cid)
    )
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
    if station_code and station_code != "all":
        parsed_code = _int(station_code)
        if parsed_code is not None:
            q = q.where(FuelStation.code == parsed_code)
    q = q.order_by(OnlineOrder.order_date.desc().nullslast()).limit(limit)
    rows = (await db.execute(q)).all()
    return [_to_response(order, code, name) for order, code, name in rows]


@router.post("/refresh")
async def refresh_online_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    company_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    station_code: str | None = Query(None),
):
    """Обновить локальный журнал из MSTO для монитора онлайн-заказов."""
    cid = await assert_company_member(company_id, user, db) if company_id else user.company_id
    selected_station_code = station_code if station_code and station_code != "all" else None
    service_point_ids = await _company_service_point_ids(db, cid, selected_station_code)
    if not service_point_ids:
        scope = "выбранной АЗС" if selected_station_code else "компании"
        return {
            "created": 0,
            "updated": 0,
            "fetched": 0,
            "warning": f"Для {scope} не заданы servicePointId MSTO",
        }
    sync_from = date_from
    period_start = None
    period_end = None
    try:
        period_start = datetime.fromisoformat(date_from) if date_from else None
        period_end = datetime.fromisoformat(f"{date_to}T23:59:59") if date_to else None
    except ValueError:
        pass
    latest_query = select(func.max(OnlineOrder.order_date)).where(OnlineOrder.company_id == cid)
    latest_query = latest_query.where(OnlineOrder.service_point_id.in_(service_point_ids))
    if period_start is not None:
        latest_query = latest_query.where(OnlineOrder.order_date >= period_start)
    if period_end is not None:
        latest_query = latest_query.where(OnlineOrder.order_date <= period_end)
    latest = (await db.execute(latest_query)).scalar_one_or_none()
    if latest is not None:
        overlap = (latest - timedelta(days=2)).date().isoformat()
        sync_from = max(date_from, overlap) if date_from else overlap

    result = await ingest_online_orders(db, cid, sync_from, date_to, service_point_ids)
    await db.commit()
    return {
        **result,
        "mode": "incremental" if sync_from != date_from else "full",
        "date_from": sync_from,
        "date_to": date_to,
    }


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
