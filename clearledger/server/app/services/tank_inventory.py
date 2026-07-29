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
# Порог достоверности замера — общий с книгой резервуара: два разных порога дали
# бы ведомость, расходящуюся с экраном, по которому её сверяют.
from app.services.tank_ledger import FACT_SANITY_RATIO


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
    # Заодно — последняя смена на дату КАЖДОЙ прошлой ведомости: по ней видно, какое
    # расхождение та ведомость закрыла.
    by_date: dict[tuple[int, int, date], tuple] = {}
    for tank, shift, station in records:
        key = (int(station.code), int(tank.tank_number))
        last[key] = (tank, shift, station)
        if shift.opened_at:
            by_date[(key[0], key[1], shift.opened_at.date())] = (tank, shift, station)

    # Ведомости ПРОШЛЫХ дат. Расхождение в источнике накапливается — книга к замеру
    # не приводится, и списанное ранее продолжает сидеть в цифре «факт − книга».
    # Без этой поправки ведомость второй раз списывает уже оформленную недостачу.
    last_prior: dict[tuple[str, int], FuelTankInventory] = {}
    for r in (await db.execute(select(FuelTankInventory).where(
        FuelTankInventory.company_id == company_id,
        FuelTankInventory.status == "confirmed",
        FuelTankInventory.inventory_date < inventory_date,
    ).order_by(FuelTankInventory.inventory_date))).scalars().all():
        last_prior[(str(r.station_id), int(r.tank_number))] = r  # остаётся самая поздняя

    # Уже проведённые инвентаризации на эту дату — чтобы показать статус.
    existing = {
        (str(r.station_id), r.tank_number): r
        for r in (await db.execute(select(FuelTankInventory).where(
            FuelTankInventory.company_id == company_id,
            FuelTankInventory.inventory_date == inventory_date,
        ))).scalars().all()
    }

    # Вместимость резервуара по книге — ею отбраковываем невозможные замеры.
    # Уровнемер на АЗС 8 рез.2 отдаёт 53 763 л при уровне 262 мм (входит ~25 000 л):
    # взяв это за факт, ведомость предложила бы оприходовать 28 тысяч литров,
    # которых нет. Логика и порог — те же, что в книге резервуара (tank_ledger).
    capacity: dict[tuple[int, int], float] = {}
    for tank, shift, station in records:
        key = (int(station.code), int(tank.tank_number))
        capacity[key] = max(capacity.get(key, 0.0),
                            _f(tank.volume_start), _f(tank.volume_end))

    rows: list[dict[str, Any]] = []
    sum_adj_vol = 0.0
    skipped_suspect: list[dict[str, Any]] = []
    for (st_code, tank_no), (tank, shift, station) in sorted(last.items()):
        book_v = _f(tank.volume_end)
        fact_v = _f(tank.fact_volume)
        cap = capacity.get((st_code, int(tank_no)), 0.0)
        if cap > 0 and fact_v > cap * FACT_SANITY_RATIO:
            # Мерить нечем: показание прибора невозможно. В ведомость не берём и
            # говорим об этом прямо — иначе резервуар молча исчезнет из списка.
            skipped_suspect.append({
                "station_code": st_code, "station_name": station.name or f"АЗС {st_code}",
                "tank_number": int(tank_no), "fuel_name": (tank.fuel_type or "—").strip(),
                "fact_volume": round(fact_v, 1), "book_volume": round(book_v, 1),
                "capacity_hint": round(cap, 0),
                "reason": "показание уровнемера больше вместимости резервуара — прибор требует проверки",
            })
            continue
        adj_v = round(fact_v - book_v, 2)
        book_m = _n(tank.mass_end)
        fact_m = _n(tank.fact_mass)
        adj_m = round(fact_m - book_m, 3) if (book_m is not None and fact_m is not None) else None
        prev = existing.get((str(station.id), int(tank_no)))
        # Что закрыла последняя прошлая ведомость и сколько набежало после неё.
        # `adjustment_open` — то, что подлежит оформлению сейчас; `adjustment_volume`
        # оставлен как есть (всё накопленное), чтобы обе величины были на виду.
        earlier = last_prior.get((str(station.id), int(tank_no)))
        adj_open = adj_v
        earlier_gap: float | None = None
        if earlier is not None:
            at = by_date.get((st_code, int(tank_no), earlier.inventory_date))
            if at is not None:
                earlier_gap = round(_f(at[0].fact_volume) - _f(at[0].volume_end), 2)
                adj_open = round(adj_v - earlier_gap, 2)
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
            # Прошлая ведомость по этому резервуару: когда, на сколько и какое
            # расхождение она закрыла.
            "prior_date": earlier.inventory_date.isoformat() if earlier else None,
            "prior_adjustment": round(_f(earlier.adjustment_volume), 1) if earlier else None,
            "prior_gap": earlier_gap,
            "adjustment_open": adj_open,
        })

    return {
        "inventory_date": inventory_date.isoformat(),
        "rows": rows,
        "totals": {
            "tanks": len(rows),
            "surplus_tanks": sum(1 for r in rows if r["adjustment_volume"] > 0.05),
            "shortfall_tanks": sum(1 for r in rows if r["adjustment_volume"] < -0.05),
            "adjustment_volume": round(sum_adj_vol, 1),
            # К оформлению за вычетом того, что закрыли прошлые ведомости.
            "adjustment_open": round(sum(r["adjustment_open"] for r in rows), 1),
            "tanks_with_prior": sum(1 for r in rows if r["prior_date"]),
            "skipped_suspect": len(skipped_suspect),
        },
        # Резервуары, выпавшие из ведомости из-за неисправного прибора: их надо
        # промерить вручную, иначе они просто не попадут в инвентаризацию.
        "suspect": skipped_suspect,
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


async def cancel(
    db: AsyncSession,
    company_id: uuid.UUID,
    inventory_date: date,
    *,
    station_codes: list[int] | None = None,
) -> dict[str, Any]:
    """Отменить проведённую ведомость на дату (целиком или по выбранным АЗС).

    Без отмены ошибку в ведомости нельзя исправить: повторное проведение на ту же
    дату перезапишет строки, но если резервуар попал в ведомость по недосмотру, из
    неё его уже не убрать. Удаляем строки, а не помечаем — ведомость это факт
    оформления, а «отменённый факт оформления» в отчётности читается как оформленный.
    """
    q = select(FuelTankInventory).where(
        FuelTankInventory.company_id == company_id,
        FuelTankInventory.inventory_date == inventory_date,
    )
    if station_codes:
        ids = (await db.execute(select(FuelStation.id).where(
            FuelStation.company_id == company_id,
            FuelStation.code.in_([int(c) for c in station_codes])))).scalars().all()
        q = q.where(FuelTankInventory.station_id.in_(ids))
    rows = (await db.execute(q)).scalars().all()
    for row in rows:
        await db.delete(row)
    await db.commit()
    return {"cancelled": len(rows), "inventory_date": inventory_date.isoformat()}


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
