"""Оперативная трёхсторонняя сверка онлайн-заказов: MSTO ↔ STS операции ↔ смены."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import (
    FuelShift,
    FuelShiftSale,
    FuelShiftSaleOverride,
    FuelStation,
    FuelTransaction,
    OnlineOrder,
    OnlineReconciliationDecision,
    User,
)
from app.routers.online_orders_router import ingest_online_orders
from app.utils import MSK

router = APIRouter(prefix="/reconciliation/online", tags=["Сверка / Онлайн-заказы"])

TIME_TOLERANCE = timedelta(minutes=30)
VOLUME_TOLERANCE = 1.0
SUM_TOLERANCE = 10.0
ONLINE_PATTERNS = ("%мобил%", "%онлайн%", "%online%", "%яндекс%", "%benzuber%", "%fuelup%")


class OnlineRunRequest(BaseModel):
    company_id: str
    date_from: date
    date_to: date
    station_codes: list[int] = Field(default_factory=list)
    include_empty_shifts: bool = False
    refresh_msto: bool = True


class DecisionRequest(BaseModel):
    company_id: str
    case_key: str = Field(min_length=3, max_length=180)
    station_id: uuid.UUID | None = None
    shift_number: int | None = None
    fuel_code: int | None = None
    online_order_id: uuid.UUID | None = None
    fuel_transaction_id: uuid.UUID | None = None
    status: Literal["open", "in_progress", "resolved"] = "resolved"
    resolution: Literal["accept_msto", "accept_transaction", "accept_shift", "manual", "exclude"]
    target_system: Literal["msto", "sts_transaction", "shift_report", "ledger", "none"] = "ledger"
    canonical_amount: float | None = Field(default=None, ge=0)
    canonical_volume: float | None = Field(default=None, ge=0)
    instruction: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)
    assignee: str | None = Field(default=None, max_length=200)
    source_snapshot: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_manual(self):
        if self.resolution == "manual" and (
            self.canonical_amount is None or self.canonical_volume is None
        ):
            raise ValueError("Для ручной корректировки укажите сумму и объём")
        if self.resolution == "accept_shift" and not self.case_key.startswith("shift-gap:"):
            raise ValueError("Итог смены можно принять только для расхождения смены")
        return self


class ApplyRequest(BaseModel):
    company_id: str
    date_from: date
    date_to: date
    station_codes: list[int] = Field(default_factory=list)


def _bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    if date_to < date_from:
        raise HTTPException(400, "Дата окончания раньше даты начала")
    if (date_to - date_from).days > 92:
        raise HTTPException(400, "Период сверки не должен превышать 93 дня")
    # Сутки московские — как в остальном топливном контуре: заказ, оформленный
    # ночью, должен попадать в тот же день, что и реализация по нему.
    return (
        datetime.combine(date_from, time.min, tzinfo=MSK),
        datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MSK),
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _f(value: Any) -> float:
    return round(float(value or 0), 3)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _decision_out(row: OnlineReconciliationDecision | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "status": row.status,
        "resolution": row.resolution,
        "target_system": row.target_system,
        "canonical_amount": _f(row.canonical_amount) if row.canonical_amount is not None else None,
        "canonical_volume": _f(row.canonical_volume) if row.canonical_volume is not None else None,
        "instruction": row.instruction,
        "note": row.note,
        "assignee": row.assignee,
        "applied_at": _iso(row.applied_at),
        "updated_at": _iso(row.updated_at),
    }


def _case_status(base: str, decision: OnlineReconciliationDecision | None) -> str:
    return "resolved" if decision and decision.status == "resolved" else base


def _effective(case: dict[str, Any]) -> tuple[float, float]:
    decision = case.get("decision") or {}
    resolution = decision.get("resolution")
    if resolution == "exclude":
        return 0.0, 0.0
    if resolution == "manual":
        return _f(decision.get("canonical_amount")), _f(decision.get("canonical_volume"))
    if resolution == "accept_msto":
        return _f(case.get("msto_amount")), _f(case.get("msto_volume"))
    if resolution == "accept_shift":
        return _f(case.get("shift_amount")), _f(case.get("shift_volume"))
    return _f(case.get("transaction_amount")), _f(case.get("transaction_volume"))


async def _build_workspace(
    db: AsyncSession,
    company_id: uuid.UUID,
    date_from: date,
    date_to: date,
    station_codes: list[int],
    include_empty_shifts: bool = False,
) -> dict[str, Any]:
    dt_from, dt_to = _bounds(date_from, date_to)
    stations = (await db.execute(
        select(FuelStation).where(FuelStation.company_id == company_id)
    )).scalars().all()
    station_by_id = {s.id: s for s in stations}
    code_filter = set(station_codes)
    station_filter = {s.id for s in stations if s.code in code_filter}
    filtering_stations = bool(code_filter)

    oq = select(OnlineOrder).where(
        OnlineOrder.company_id == company_id,
        OnlineOrder.order_date >= dt_from,
        OnlineOrder.order_date < dt_to,
        or_(OnlineOrder.actual_volume > 0.01, OnlineOrder.actual_sum > 1),
    )
    if filtering_stations:
        oq = oq.where(OnlineOrder.station_id.in_(station_filter))
    orders = list((await db.execute(oq.order_by(OnlineOrder.order_date))).scalars().all())

    online_pay = or_(*(FuelTransaction.pay_type_name.ilike(p) for p in ONLINE_PATTERNS))
    tq = select(FuelTransaction).where(
        FuelTransaction.company_id == company_id,
        FuelTransaction.dt >= dt_from,
        FuelTransaction.dt < dt_to,
        online_pay,
    )
    if filtering_stations:
        tq = tq.where(FuelTransaction.station_id.in_(station_filter))
    transactions = list((await db.execute(tq.order_by(FuelTransaction.dt))).scalars().all())

    sq = select(FuelShift).where(
        FuelShift.company_id == company_id,
        FuelShift.opened_at < dt_to,
        or_(FuelShift.closed_at.is_(None), FuelShift.closed_at >= dt_from),
    )
    if filtering_stations:
        sq = sq.where(FuelShift.station_id.in_(station_filter))
    shifts = list((await db.execute(sq.order_by(FuelShift.opened_at))).scalars().all())
    shift_ids = [s.id for s in shifts]

    sales = []
    overrides = []
    if shift_ids:
        sales = list((await db.execute(
            select(FuelShiftSale).where(
                FuelShiftSale.shift_id.in_(shift_ids),
                FuelShiftSale.payment_channel == "online",
            )
        )).scalars().all())
        overrides = list((await db.execute(
            select(FuelShiftSaleOverride).where(
                FuelShiftSaleOverride.company_id == company_id,
                FuelShiftSaleOverride.payment_channel == "online",
            )
        )).scalars().all())

    decisions = list((await db.execute(
        select(OnlineReconciliationDecision).where(
            OnlineReconciliationDecision.company_id == company_id
        )
    )).scalars().all())
    decision_by_key = {d.case_key: d for d in decisions}

    shifts_by_station: dict[uuid.UUID, list[FuelShift]] = defaultdict(list)
    shift_by_natural: dict[tuple[uuid.UUID, int], FuelShift] = {}
    for shift in shifts:
        shifts_by_station[shift.station_id].append(shift)
        shift_by_natural[(shift.station_id, shift.shift_number)] = shift

    def find_shift(station_id: uuid.UUID | None, moment: datetime | None, number: int | None = None):
        if station_id is None:
            return None
        if number is not None and (station_id, number) in shift_by_natural:
            return shift_by_natural[(station_id, number)]
        when = _aware(moment)
        if when is None:
            return None
        for shift in shifts_by_station.get(station_id, []):
            opened = _aware(shift.opened_at)
            closed = _aware(shift.closed_at) or dt_to
            if opened and opened <= when <= closed:
                return shift
        return None

    tx_by_station: dict[uuid.UUID, list[FuelTransaction]] = defaultdict(list)
    for tx in transactions:
        if tx.station_id:
            tx_by_station[tx.station_id].append(tx)
    used_tx: set[uuid.UUID] = set()
    cases: list[dict[str, Any]] = []

    def add_case(
        key: str,
        base_status: str,
        order: OnlineOrder | None,
        tx: FuelTransaction | None,
        shift: FuelShift | None,
    ) -> None:
        station_id = (order.station_id if order else None) or (tx.station_id if tx else None) or (shift.station_id if shift else None)
        station = station_by_id.get(station_id)
        decision = decision_by_key.get(key)
        row = {
            "case_key": key,
            "kind": "transaction",
            "status": _case_status(base_status, decision),
            "base_status": base_status,
            "station_id": str(station_id) if station_id else None,
            "station_code": station.code if station else (tx.station_code if tx else None),
            "station_name": station.name if station else (order.service_point_name if order else "Станция не сопоставлена"),
            "shift_number": shift.shift_number if shift else (tx.shift_number if tx else None),
            "shift_key": f"{station_id}:{shift.shift_number}" if station_id and shift else None,
            "fuel_code": (order.fuel_code if order else None) or (tx.fuel_code if tx else None),
            "fuel_name": (order.fuel_name if order else None) or (tx.fuel_name if tx else None) or "—",
            "event_at": _iso((order.order_date if order else None) or (tx.dt if tx else None)),
            "aggregator": order.aggregator if order else None,
            "external_order_id": order.external_id if order else None,
            "online_order_id": str(order.id) if order else None,
            "fuel_transaction_id": str(tx.id) if tx else None,
            "transaction_ext_id": tx.ext_id if tx else None,
            "msto_amount": _f(order.actual_sum) if order else None,
            "msto_volume": _f(order.actual_volume) if order else None,
            "transaction_amount": _f(tx.amount) if tx else None,
            "transaction_volume": _f(tx.liters) if tx else None,
            "shift_amount": None,
            "shift_volume": None,
            "operation_result": order.operation_result if order else None,
            "decision": _decision_out(decision),
            "locked": bool(shift and shift.is_locked),
        }
        effective_amount, effective_volume = _effective(row)
        row["effective_amount"] = effective_amount
        row["effective_volume"] = effective_volume
        cases.append(row)

    for order in orders:
        best = None
        best_score = float("inf")
        order_at = _aware(order.order_date)
        for tx in tx_by_station.get(order.station_id, []):
            if tx.id in used_tx:
                continue
            if order.fuel_code and tx.fuel_code and order.fuel_code != tx.fuel_code:
                continue
            tx_at = _aware(tx.dt)
            if order_at is None or tx_at is None:
                continue
            time_diff = abs(order_at - tx_at)
            volume_diff = abs(_f(order.actual_volume) - _f(tx.liters))
            if time_diff > TIME_TOLERANCE or volume_diff > VOLUME_TOLERANCE * 2:
                continue
            score = time_diff.total_seconds() + volume_diff * 300
            if score < best_score:
                best, best_score = tx, score
        shift = find_shift(order.station_id, order.order_date, best.shift_number if best else None)
        if best:
            used_tx.add(best.id)
            mismatch = (
                abs(_f(order.actual_volume) - _f(best.liters)) > VOLUME_TOLERANCE
                or abs(_f(order.actual_sum) - _f(best.amount)) > SUM_TOLERANCE
            )
            base = "mismatch" if mismatch else ("wait_done" if order.operation_result == "wait" else "matched")
        else:
            base = "only_msto"
        add_case(f"msto:{order.id}", base, order, best, shift)

    for tx in transactions:
        if tx.id in used_tx:
            continue
        shift = find_shift(tx.station_id, tx.dt, tx.shift_number)
        add_case(f"transaction:{tx.id}", "only_transaction", None, tx, shift)

    sales_by_shift: dict[uuid.UUID, list[FuelShiftSale]] = defaultdict(list)
    for sale in sales:
        sales_by_shift[sale.shift_id].append(sale)
    override_by_key = {
        (o.station_id, o.shift_number, o.fuel_code): o for o in overrides
    }

    groups: dict[str, dict[str, Any]] = {}
    cases_by_shift: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        if case["shift_key"]:
            cases_by_shift[case["shift_key"]].append(case)

    raw_shift_total_amount = 0.0
    raw_shift_total_volume = 0.0
    effective_shift_total_amount = 0.0
    effective_shift_total_volume = 0.0
    for shift in shifts:
        key = f"{shift.station_id}:{shift.shift_number}"
        related = cases_by_shift.get(key, [])
        shift_sales = sales_by_shift.get(shift.id, [])
        if not include_empty_shifts and not related and not shift_sales:
            continue
        raw_amount = sum(_f(s.amount) for s in shift_sales)
        raw_volume = sum(_f(s.liters) for s in shift_sales)
        effective_amount = 0.0
        effective_volume = 0.0
        for sale in shift_sales:
            ov = override_by_key.get((shift.station_id, shift.shift_number, sale.fuel_code))
            effective_amount += _f(ov.amount if ov and ov.amount is not None else sale.amount)
            effective_volume += _f(ov.liters if ov and ov.liters is not None else sale.liters)
        raw_shift_total_amount += raw_amount
        raw_shift_total_volume += raw_volume
        effective_shift_total_amount += effective_amount
        effective_shift_total_volume += effective_volume
        msto_amount = sum(_f(c["msto_amount"]) for c in related)
        msto_volume = sum(_f(c["msto_volume"]) for c in related)
        tx_amount = sum(_f(c["transaction_amount"]) for c in related)
        tx_volume = sum(_f(c["transaction_volume"]) for c in related)
        gap = (
            abs(msto_amount - tx_amount) > SUM_TOLERANCE
            or abs(msto_volume - tx_volume) > VOLUME_TOLERANCE
            or abs(tx_amount - raw_amount) > SUM_TOLERANCE
            or abs(tx_volume - raw_volume) > VOLUME_TOLERANCE
        )
        gap_key = f"shift-gap:{shift.station_id}:{shift.shift_number}"
        gap_decision = decision_by_key.get(gap_key)
        gap_status = "resolved" if gap_decision and gap_decision.status == "resolved" else ("shift_mismatch" if gap else "matched")
        if gap:
            gap_case = {
                "case_key": gap_key,
                "kind": "shift_gap",
                "status": gap_status,
                "base_status": "shift_mismatch",
                "station_id": str(shift.station_id),
                "station_code": station_by_id.get(shift.station_id).code if station_by_id.get(shift.station_id) else None,
                "station_name": station_by_id.get(shift.station_id).name if station_by_id.get(shift.station_id) else "АЗС",
                "shift_number": shift.shift_number,
                "shift_key": key,
                "fuel_code": None,
                "fuel_name": "Итог смены",
                "event_at": _iso(shift.closed_at or shift.opened_at),
                "aggregator": None,
                "external_order_id": None,
                "online_order_id": None,
                "fuel_transaction_id": None,
                "transaction_ext_id": None,
                "msto_amount": round(msto_amount, 2),
                "msto_volume": round(msto_volume, 3),
                "transaction_amount": round(tx_amount, 2),
                "transaction_volume": round(tx_volume, 3),
                "shift_amount": round(raw_amount, 2),
                "shift_volume": round(raw_volume, 3),
                "operation_result": None,
                "decision": _decision_out(gap_decision),
                "locked": shift.is_locked,
            }
            gap_case["effective_amount"], gap_case["effective_volume"] = _effective(gap_case)
            cases.append(gap_case)
            related.append(gap_case)
        station = station_by_id.get(shift.station_id)
        groups[key] = {
            "key": key,
            "station_id": str(shift.station_id),
            "station_code": station.code if station else None,
            "station_name": station.name if station else "АЗС",
            "shift_number": shift.shift_number,
            "opened_at": _iso(shift.opened_at),
            "closed_at": _iso(shift.closed_at),
            "locked": shift.is_locked,
            "status": gap_status,
            "msto": {"count": sum(1 for c in related if c["online_order_id"]), "amount": round(msto_amount, 2), "volume": round(msto_volume, 3)},
            "transactions": {"count": sum(1 for c in related if c["fuel_transaction_id"]), "amount": round(tx_amount, 2), "volume": round(tx_volume, 3)},
            "shift": {"count": len(shift_sales), "amount": round(raw_amount, 2), "volume": round(raw_volume, 3)},
            "normalized": {"amount": round(effective_amount, 2), "volume": round(effective_volume, 3)},
            "case_count": len(related),
            "unresolved_count": sum(1 for c in related if c["status"] not in ("matched", "resolved")),
        }

    cases.sort(key=lambda c: (c["status"] in ("matched", "resolved"), c["event_at"] or ""))
    status_counts: dict[str, int] = defaultdict(int)
    for case in cases:
        status_counts[case["status"]] += 1

    total_msto_amount = sum(_f(o.actual_sum) for o in orders)
    total_msto_volume = sum(_f(o.actual_volume) for o in orders)
    total_tx_amount = sum(_f(t.amount) for t in transactions)
    total_tx_volume = sum(_f(t.liters) for t in transactions)
    return {
        "period": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "sources": {
            "msto": {"count": len(orders), "amount": round(total_msto_amount, 2), "volume": round(total_msto_volume, 3)},
            "transactions": {"count": len(transactions), "amount": round(total_tx_amount, 2), "volume": round(total_tx_volume, 3)},
            "shifts": {"count": len(groups), "amount": round(raw_shift_total_amount, 2), "volume": round(raw_shift_total_volume, 3)},
            "normalized": {"count": len(groups), "amount": round(effective_shift_total_amount, 2), "volume": round(effective_shift_total_volume, 3)},
        },
        "status_counts": dict(status_counts),
        "unresolved_count": sum(v for k, v in status_counts.items() if k not in ("matched", "resolved")),
        "shifts": sorted(groups.values(), key=lambda g: (g["station_code"] or 0, g["shift_number"])),
        "cases": cases,
    }


async def _company(company_ref: str, user: User, db: AsyncSession) -> uuid.UUID:
    return await assert_company_member(company_ref, user, db)


@router.get("/workspace")
async def get_workspace(
    company_id: str,
    date_from: date,
    date_to: date,
    station_codes: str | None = Query(None),
    include_empty_shifts: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company(company_id, user, db)
    codes = [int(v) for v in station_codes.split(",") if v] if station_codes else []
    return await _build_workspace(db, cid, date_from, date_to, codes, include_empty_shifts)


@router.post("/run")
async def run_workspace(
    body: OnlineRunRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company(body.company_id, user, db)
    refresh: dict[str, Any] = {"msto": "skipped"}
    if body.refresh_msto:
        try:
            refresh["msto"] = await ingest_online_orders(
                db, cid, body.date_from.isoformat(), body.date_to.isoformat()
            )
            await db.commit()
        except Exception as exc:  # внешний источник не должен скрывать локальную сверку
            await db.rollback()
            refresh["msto"] = {"error": str(exc)[:300]}
    result = await _build_workspace(
        db, cid, body.date_from, body.date_to, body.station_codes, body.include_empty_shifts
    )
    result["refresh"] = refresh
    return result


@router.put("/decision")
async def put_decision(
    body: DecisionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company(body.company_id, user, db)
    if body.station_id:
        station = await db.get(FuelStation, body.station_id)
        if station is None or station.company_id != cid:
            raise HTTPException(404, "Станция не найдена")
    values = body.model_dump(exclude={"company_id"})
    values.update(company_id=cid, created_by=user.id, updated_by=user.id)
    stmt = insert(OnlineReconciliationDecision).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[OnlineReconciliationDecision.company_id, OnlineReconciliationDecision.case_key],
        set_={
            "station_id": stmt.excluded.station_id,
            "shift_number": stmt.excluded.shift_number,
            "fuel_code": stmt.excluded.fuel_code,
            "online_order_id": stmt.excluded.online_order_id,
            "fuel_transaction_id": stmt.excluded.fuel_transaction_id,
            "status": stmt.excluded.status,
            "resolution": stmt.excluded.resolution,
            "target_system": stmt.excluded.target_system,
            "canonical_amount": stmt.excluded.canonical_amount,
            "canonical_volume": stmt.excluded.canonical_volume,
            "instruction": stmt.excluded.instruction,
            "note": stmt.excluded.note,
            "assignee": stmt.excluded.assignee,
            "source_snapshot": stmt.excluded.source_snapshot,
            "updated_by": user.id,
            "updated_at": datetime.now(timezone.utc),
        },
    ).returning(OnlineReconciliationDecision)
    row = (await db.execute(stmt)).scalar_one()
    await db.commit()
    return _decision_out(row)


@router.delete("/decision/{case_key}")
async def delete_decision(
    case_key: str,
    company_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company(company_id, user, db)
    result = await db.execute(delete(OnlineReconciliationDecision).where(
        OnlineReconciliationDecision.company_id == cid,
        OnlineReconciliationDecision.case_key == case_key,
        OnlineReconciliationDecision.applied_at.is_(None),
    ))
    await db.commit()
    return {"deleted": result.rowcount or 0}


@router.post("/apply")
async def apply_decisions(
    body: ApplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company(body.company_id, user, db)
    workspace = await _build_workspace(db, cid, body.date_from, body.date_to, body.station_codes)
    unresolved = [c for c in workspace["cases"] if c["status"] not in ("matched", "resolved")]
    if unresolved:
        raise HTTPException(409, f"Остались неразобранные расхождения: {len(unresolved)}")

    cases = [c for c in workspace["cases"] if c["kind"] == "transaction" and c["shift_key"]]
    totals: dict[tuple[uuid.UUID, int, int], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for case in cases:
        if case["fuel_code"] is None:
            raise HTTPException(409, f"Не определён вид топлива: {case['case_key']}")
        amount, volume = _effective(case)
        key = (uuid.UUID(case["station_id"]), int(case["shift_number"]), int(case["fuel_code"]))
        totals[key][0] += amount
        totals[key][1] += volume

    affected_shifts = {
        (uuid.UUID(c["station_id"]), int(c["shift_number"]))
        for c in workspace["cases"]
        if c["station_id"] and c["shift_number"] is not None
    }
    shifts = list((await db.execute(select(FuelShift).where(
        FuelShift.company_id == cid,
        FuelShift.station_id.in_({k[0] for k in affected_shifts}),
    ))).scalars().all()) if affected_shifts else []
    shift_by_key = {(s.station_id, s.shift_number): s for s in shifts}
    sale_rows = list((await db.execute(select(FuelShiftSale).where(
        FuelShiftSale.shift_id.in_([s.id for s in shifts]),
        FuelShiftSale.payment_channel == "online",
    ))).scalars().all()) if shifts else []
    sale_by_key = {}
    shift_natural_by_id = {s.id: (s.station_id, s.shift_number) for s in shifts}
    for sale in sale_rows:
        station_id, shift_number = shift_natural_by_id[sale.shift_id]
        sale_by_key[(station_id, shift_number, sale.fuel_code)] = sale

    transaction_cases_by_shift: dict[tuple[uuid.UUID, int], list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        transaction_cases_by_shift[(uuid.UUID(case["station_id"]), int(case["shift_number"]))].append(case)

    for gap in (c for c in workspace["cases"] if c["kind"] == "shift_gap" and c["decision"]):
        natural = (uuid.UUID(gap["station_id"]), int(gap["shift_number"]))
        resolution = gap["decision"]["resolution"]
        for key in [key for key in totals if key[:2] == natural]:
            del totals[key]
        if resolution == "accept_shift":
            continue
        shift_sales = [(key, sale) for key, sale in sale_by_key.items() if key[:2] == natural]
        if resolution == "exclude":
            for key, _sale in shift_sales:
                totals[key] = [0.0, 0.0]
            continue
        if resolution == "manual":
            if not shift_sales:
                raise HTTPException(409, f"В смене {natural[1]} нет строк онлайн-продаж для распределения")
            amount = _f(gap["decision"]["canonical_amount"])
            volume = _f(gap["decision"]["canonical_volume"])
            base_amount = sum(_f(sale.amount) for _key, sale in shift_sales)
            base_volume = sum(_f(sale.liters) for _key, sale in shift_sales)
            for key, sale in shift_sales:
                amount_share = _f(sale.amount) / base_amount if base_amount else 1 / max(len(shift_sales), 1)
                volume_share = _f(sale.liters) / base_volume if base_volume else 1 / max(len(shift_sales), 1)
                totals[key] = [amount * amount_share, volume * volume_share]
            continue
        source = "msto" if resolution == "accept_msto" else "transaction"
        for case in transaction_cases_by_shift.get(natural, []):
            if case["fuel_code"] is None:
                raise HTTPException(409, f"Не определён вид топлива: {case['case_key']}")
            key = (natural[0], natural[1], int(case["fuel_code"]))
            totals[key][0] += _f(case[f"{source}_amount"])
            totals[key][1] += _f(case[f"{source}_volume"])

    applied = 0
    now = datetime.now(timezone.utc)
    for key, (amount, volume) in totals.items():
        shift = shift_by_key.get((key[0], key[1]))
        if shift is None:
            raise HTTPException(409, f"Смена {key[1]} не найдена")
        if shift.is_locked:
            raise HTTPException(409, f"Смена {key[1]} находится в закрытом периоде")
        sale = sale_by_key.get(key)
        if sale is None:
            raise HTTPException(409, f"В смене {key[1]} нет строки онлайн-продаж по топливу {key[2]}")
        target_amount = round(amount, 2)
        target_volume = round(volume, 3)
        if abs(target_amount - _f(sale.amount)) <= 0.005 and abs(target_volume - _f(sale.liters)) <= 0.005:
            continue
        stmt = insert(FuelShiftSaleOverride).values(
            company_id=cid,
            station_id=key[0],
            shift_number=key[1],
            payment_channel="online",
            fuel_code=key[2],
            amount=target_amount,
            liters=target_volume,
            src_amount=_f(sale.amount),
            src_liters=_f(sale.liters),
            src_discount=_f(sale.discount),
            note="Применено из сверки онлайн-заказов",
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                FuelShiftSaleOverride.company_id,
                FuelShiftSaleOverride.station_id,
                FuelShiftSaleOverride.shift_number,
                FuelShiftSaleOverride.payment_channel,
                FuelShiftSaleOverride.fuel_code,
            ],
            set_={
                "amount": stmt.excluded.amount,
                "liters": stmt.excluded.liters,
                "src_amount": stmt.excluded.src_amount,
                "src_liters": stmt.excluded.src_liters,
                "note": stmt.excluded.note,
                "updated_at": now,
            },
        )
        await db.execute(stmt)
        if shift.status == "new":
            shift.status = "verified"
        applied += 1

    case_keys = [c["case_key"] for c in workspace["cases"] if c["decision"]]
    if case_keys:
        await db.execute(update(OnlineReconciliationDecision).where(
            OnlineReconciliationDecision.company_id == cid,
            OnlineReconciliationDecision.case_key.in_(case_keys),
        ).values(applied_at=now, updated_by=user.id))
    await db.commit()
    return {"ok": True, "applied": applied, "resolved_cases": len(case_keys)}
