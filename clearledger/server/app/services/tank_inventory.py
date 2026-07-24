"""Инвентаризация резервуаров: ведомость корректировок книги на факт.

Расхождение книга↔факт само не списывается — копится, пока инвентаризация не
оформит корректировку. Здесь:

* `build_draft` — по каждому резервуару контура берёт последнюю смену на дату
  инвентаризации, её книжный остаток (doc_end) и фактический замер (rest) и
  считает корректировку = факт − книга (плюс — оприходование излишка, минус —
  списание недостачи). Ничего не пишет — это черновик ведомости на просмотр.
* `save` — фиксирует ведомость (status=confirmed). Ключ натуральный (станция +
  резервуар + дата), поэтому повтор на ту же дату перезаписывает, а не двоит,
  и запись переживает переигровку смен.

Факт берётся из уже сохранённого замера (`fuel_tanks.fact_volume`), STS повторно
не опрашивается — инвентаризация оформляет то, что уже намеряно.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelShift, FuelStation, FuelTank, FuelTankInventory


def _f(v: Any) -> float:
    return float(v) if v is not None else 0.0


def _n(v: Any) -> float | None:
    return float(v) if v is not None else None


async def build_draft(
    db: AsyncSession,
    company_id: uuid.UUID,
    inventory_date: date,
    *,
    station_codes: list[int] | None = None,
    fuel_codes: list[int] | None = None,
) -> dict[str, Any]:
    """Черновик ведомости инвентаризации на дату: книга/факт/корректировка по резервуарам."""
    dt_to = datetime(inventory_date.year, inventory_date.month, inventory_date.day, 23, 59, 59)

    q = (
        select(FuelTank, FuelShift, FuelStation)
        .join(FuelShift, FuelShift.id == FuelTank.shift_id)
        .join(FuelStation, FuelStation.id == FuelShift.station_id)
        .where(FuelShift.company_id == company_id,
               FuelShift.opened_at <= dt_to,
               # Строго > 0: ноль в замере означает «уровнемер не дал показание»,
               # а не пустой резервуар. Иначе корректировка = 0 − книга, и ведомость
               # списала бы весь остаток (АЗС 207 рез.1 — 19 044 л). Резервуар без
               # замера в инвентаризацию не берём — мерить нечего.
               FuelTank.fact_volume > 0)
        .order_by(FuelStation.code, FuelTank.tank_number,
                  FuelShift.opened_at, FuelShift.shift_number)
    )
    if station_codes:
        q = q.where(FuelStation.code.in_([int(c) for c in station_codes]))
    if fuel_codes:
        q = q.where(FuelTank.fuel_code.in_([int(c) for c in fuel_codes]))

    records = (await db.execute(q)).all()

    # По резервуару берём ПОСЛЕДНЮЮ смену на дату (список уже упорядочен по времени).
    last: dict[tuple[int, int], tuple] = {}
    for tank, shift, station in records:
        last[(int(station.code), int(tank.tank_number))] = (tank, shift, station)

    # Уже проведённые инвентаризации на эту дату — чтобы показать статус.
    existing = {
        (str(r.station_id), r.tank_number): r
        for r in (await db.execute(select(FuelTankInventory).where(
            FuelTankInventory.company_id == company_id,
            FuelTankInventory.inventory_date == inventory_date,
        ))).scalars().all()
    }

    rows: list[dict[str, Any]] = []
    sum_adj_vol = 0.0
    for (st_code, tank_no), (tank, shift, station) in sorted(last.items()):
        book_v = _f(tank.volume_end)
        fact_v = _f(tank.fact_volume)
        adj_v = round(fact_v - book_v, 2)
        book_m = _n(tank.mass_end)
        fact_m = _n(tank.fact_mass)
        adj_m = round(fact_m - book_m, 3) if (book_m is not None and fact_m is not None) else None
        prev = existing.get((str(station.id), int(tank_no)))
        sum_adj_vol += adj_v
        rows.append({
            "station_id": str(station.id),
            "station_code": st_code,
            "station_name": station.name or f"АЗС {st_code}",
            "tank_number": int(tank_no),
            "fuel_code": int(tank.fuel_code) if tank.fuel_code is not None else None,
            "fuel_name": (tank.fuel_type or "—").strip(),
            "shift_number": int(shift.shift_number),
            "shift_date": shift.opened_at.date().isoformat() if shift.opened_at else None,
            "book_volume": round(book_v, 1),
            "fact_volume": round(fact_v, 1),
            "adjustment_volume": adj_v,
            "book_mass": round(book_m, 1) if book_m is not None else None,
            "fact_mass": round(fact_m, 1) if fact_m is not None else None,
            "adjustment_mass": round(adj_m, 1) if adj_m is not None else None,
            "kind": "излишек" if adj_v > 0.05 else "недостача" if adj_v < -0.05 else "сходится",
            "already_confirmed": bool(prev and prev.status == "confirmed"),
        })

    return {
        "inventory_date": inventory_date.isoformat(),
        "rows": rows,
        "totals": {
            "tanks": len(rows),
            "surplus_tanks": sum(1 for r in rows if r["adjustment_volume"] > 0.05),
            "shortfall_tanks": sum(1 for r in rows if r["adjustment_volume"] < -0.05),
            "adjustment_volume": round(sum_adj_vol, 1),
        },
    }


async def save(
    db: AsyncSession,
    company_id: uuid.UUID,
    inventory_date: date,
    rows: list[dict[str, Any]],
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """Провести инвентаризацию: зафиксировать корректировки (upsert по натур. ключу)."""
    now = datetime.now()
    saved = 0
    for r in rows:
        station_id = uuid.UUID(str(r["station_id"]))
        tank_no = int(r["tank_number"])
        book_v = _f(r.get("book_volume"))
        fact_v = _f(r.get("fact_volume"))
        adj_v = round(fact_v - book_v, 2)
        book_m = _n(r.get("book_mass"))
        fact_m = _n(r.get("fact_mass"))
        adj_m = round(fact_m - book_m, 3) if (book_m is not None and fact_m is not None) else None

        values = dict(
            company_id=company_id, station_id=station_id, tank_number=tank_no,
            fuel_code=r.get("fuel_code"), fuel_name=r.get("fuel_name"),
            inventory_date=inventory_date, shift_number=r.get("shift_number"),
            book_volume=book_v, fact_volume=fact_v, adjustment_volume=adj_v,
            book_mass=book_m, fact_mass=fact_m, adjustment_mass=adj_m,
            status="confirmed", note=note, confirmed_at=now,
        )
        stmt = pg_insert(FuelTankInventory).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["company_id", "station_id", "tank_number", "inventory_date"],
            set_={k: values[k] for k in (
                "fuel_code", "fuel_name", "shift_number", "book_volume", "fact_volume",
                "adjustment_volume", "book_mass", "fact_mass", "adjustment_mass",
                "status", "note", "confirmed_at",
            )},
        )
        await db.execute(stmt)
        saved += 1
    await db.commit()
    return {"saved": saved, "inventory_date": inventory_date.isoformat()}


async def list_inventories(
    db: AsyncSession,
    company_id: uuid.UUID,
    *,
    station_codes: list[int] | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Проведённые инвентаризации, сгруппированные по дате."""
    q = (
        select(FuelTankInventory, FuelStation.code, FuelStation.name)
        .join(FuelStation, FuelStation.id == FuelTankInventory.station_id)
        .where(FuelTankInventory.company_id == company_id,
               FuelTankInventory.status == "confirmed")
        .order_by(FuelTankInventory.inventory_date.desc(), FuelStation.code)
        .limit(limit)
    )
    if station_codes:
        q = q.where(FuelStation.code.in_([int(c) for c in station_codes]))
    records = (await db.execute(q)).all()

    by_date: dict[str, dict[str, Any]] = {}
    for inv, st_code, st_name in records:
        d = inv.inventory_date.isoformat()
        grp = by_date.setdefault(d, {
            "inventory_date": d, "tanks": 0,
            "adjustment_volume": 0.0, "surplus_tanks": 0, "shortfall_tanks": 0,
            "confirmed_at": inv.confirmed_at.isoformat() if inv.confirmed_at else None,
            "rows": [],
        })
        adj = _f(inv.adjustment_volume)
        grp["tanks"] += 1
        grp["adjustment_volume"] += adj
        if adj > 0.05:
            grp["surplus_tanks"] += 1
        elif adj < -0.05:
            grp["shortfall_tanks"] += 1
        grp["rows"].append({
            "station_code": int(st_code), "station_name": st_name or f"АЗС {st_code}",
            "tank_number": inv.tank_number, "fuel_name": inv.fuel_name,
            "book_volume": round(_f(inv.book_volume), 1),
            "fact_volume": round(_f(inv.fact_volume), 1),
            "adjustment_volume": round(adj, 1),
            "note": inv.note,
        })

    groups = sorted(by_date.values(), key=lambda g: g["inventory_date"], reverse=True)
    for g in groups:
        g["adjustment_volume"] = round(g["adjustment_volume"], 1)
    return {"inventories": groups}
