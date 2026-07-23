"""Книга резервуара: движение смена за сменой, книга против факта, контроль стыковки.

Что бухгалтер должен увидеть по каждому резервуару и почему:

**Книга** — документальный остаток. Считается арифметикой: остаток на начало
смены + слив по ТТН − отпуск через ТРК = остаток на конец. Проверено на данных
ГИГ: равенство держится в 94% записей, и начало каждой смены равно книжному
концу предыдущей в 95% переходов. То есть книга ведётся непрерывной цепочкой.

**Факт** — замер уровнемером на конец смены (секция `rest` отчёта STS). Меряется
независимо от книги и с ней расходится: у ГИГ отклонение больше 50 л в 59%
записей.

**Книга минус факт** — это и есть недостача (книга больше — топлива в резервуаре
меньше, чем должно быть) или излишек. Система НЕ подтягивает книгу к факту
автоматически: расхождение копится от смены к смене, пока инвентаризация не
спишет его документом. Поэтому важна не столько разница одной смены (её даёт
погрешность замера, температура, наклон резервуара), сколько накопленный тренд
за период — он отделяет естественную убыль от утечки, недолива поставщика или
пролива.

Три независимых контроля, каждый ловит свой класс проблем:

1. **Арифметика книги** внутри смены: (начало + приход − отпуск) − конец ≠ 0.
   Значит сам сменный отчёт внутренне противоречив — считать по нему нельзя.
2. **Стыковка смен**: начало смены ≠ конец предыдущей. Между сменами что-то
   произошло мимо учёта: правка на станции, пропущенная смена, подмена отчёта.
3. **Книга против факта**: расхождение замера с документом — предмет
   инвентаризации.

Разделять их обязательно: сумма расхождений без разбора причины — цифра, по
которой нельзя принять решение.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelShift, FuelStation, FuelTank

# Порог, ниже которого расхождение считаем шумом измерения, а не событием.
# Уровнемер даёт ±0,2–0,5% объёма; для типового резервуара 20–25 м³ это
# десятки литров. Порог применяется только к подсветке, в суммы входит всё.
ARITHMETIC_TOLERANCE_L = 0.5   # книга обязана сходиться точно — это арифметика
CONTINUITY_TOLERANCE_L = 0.5   # стык смен тоже арифметика, а не измерение
FACT_TOLERANCE_L = 50.0        # замер — измерение, у него есть погрешность


def _f(v: Any) -> float:
    return float(v) if v is not None else 0.0


def _n(v: Any) -> float | None:
    return float(v) if v is not None else None


def _fuel_key(tank: FuelTank) -> str:
    if tank.fuel_code is not None:
        return f"code:{tank.fuel_code}"
    return f"name:{(tank.fuel_type or '—').strip().casefold()}"


async def build_tank_ledger(
    db: AsyncSession,
    company_id: uuid.UUID,
    date_from: date,
    date_to: date,
    *,
    station_codes: list[int] | None = None,
    tank_number: int | None = None,
    fuel_codes: list[int] | None = None,
    max_rows: int = 5000,
) -> dict[str, Any]:
    """Журнал движения по резервуарам за период + сводка и замечания."""
    dt_from = datetime(date_from.year, date_from.month, date_from.day)
    dt_to = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)

    q = (
        select(FuelTank, FuelShift, FuelStation)
        .join(FuelShift, FuelShift.id == FuelTank.shift_id)
        .join(FuelStation, FuelStation.id == FuelShift.station_id)
        .where(FuelShift.company_id == company_id,
               FuelShift.opened_at >= dt_from,
               FuelShift.opened_at <= dt_to)
        .order_by(FuelStation.code, FuelTank.tank_number,
                  FuelShift.opened_at, FuelShift.shift_number)
    )
    if station_codes:
        q = q.where(FuelStation.code.in_([int(c) for c in station_codes]))
    if tank_number is not None:
        q = q.where(FuelTank.tank_number == int(tank_number))
    if fuel_codes:
        q = q.where(FuelTank.fuel_code.in_([int(c) for c in fuel_codes]))

    records = (await db.execute(q)).all()

    # Группировка в цепочки по физическому резервуару (станция + номер).
    chains: dict[tuple[int, int], list[tuple[FuelTank, FuelShift, FuelStation]]] = defaultdict(list)
    for tank, shift, station in records:
        chains[(int(station.code), int(tank.tank_number))].append((tank, shift, station))

    rows: list[dict[str, Any]] = []
    tanks_summary: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for (station_code, tank_no), chain in sorted(chains.items()):
        prev: FuelTank | None = None
        prev_shift: FuelShift | None = None
        first = chain[0][0]
        station_name = chain[0][2].name or f"АЗС {station_code}"

        sum_receipts = sum_sales = 0.0
        sum_mass_receipts = sum_mass_sales = 0.0
        arithmetic_breaks = continuity_breaks = fact_breaks = 0
        worst_fact = 0.0
        worst_fact_shift: int | None = None

        for tank, shift, _station in chain:
            book_start = _f(tank.volume_start)
            book_end = _f(tank.volume_end)
            receipts = _f(tank.volume_received)
            sales = _f(tank.sales)
            fact_end = _n(tank.fact_volume)

            # 1. Арифметика книги внутри смены.
            arithmetic_gap = round(book_start + receipts - sales - book_end, 2)
            # 2. Стык с предыдущей сменой.
            continuity_gap = (round(book_start - _f(prev.volume_end), 2)
                              if prev is not None else None)
            # 3. Книга против факта (недостача > 0, излишек < 0).
            fact_gap = round(book_end - fact_end, 2) if fact_end is not None else None
            fuel_changed = prev is not None and _fuel_key(prev) != _fuel_key(tank)

            sum_receipts += receipts
            sum_sales += sales
            sum_mass_receipts += _f(tank.mass_received)
            sum_mass_sales += _f(tank.mass_sales)

            if abs(arithmetic_gap) > ARITHMETIC_TOLERANCE_L:
                arithmetic_breaks += 1
                issues.append({
                    "type": "arithmetic",
                    "station_code": station_code, "station_name": station_name,
                    "tank_number": tank_no, "fuel_name": (tank.fuel_type or "—").strip(),
                    "shift_number": int(shift.shift_number),
                    "date": shift.opened_at.date().isoformat() if shift.opened_at else None,
                    "gap_liters": arithmetic_gap,
                    "detail": (f"начало {book_start:,.1f} + приход {receipts:,.1f} "
                               f"− отпуск {sales:,.1f} ≠ конец {book_end:,.1f}"),
                })
            if continuity_gap is not None and (abs(continuity_gap) > CONTINUITY_TOLERANCE_L or fuel_changed):
                continuity_breaks += 1
                issues.append({
                    "type": "fuel_change" if fuel_changed else "continuity",
                    "station_code": station_code, "station_name": station_name,
                    "tank_number": tank_no, "fuel_name": (tank.fuel_type or "—").strip(),
                    "shift_number": int(shift.shift_number),
                    "prev_shift_number": int(prev_shift.shift_number) if prev_shift else None,
                    "date": shift.opened_at.date().isoformat() if shift.opened_at else None,
                    "gap_liters": continuity_gap,
                    "detail": (f"конец смены {prev_shift.shift_number if prev_shift else '—'} "
                               f"{_f(prev.volume_end):,.1f} ≠ начало смены "
                               f"{shift.shift_number} {book_start:,.1f}"
                               + (" · смена вида топлива" if fuel_changed else "")),
                })
            if fact_gap is not None and abs(fact_gap) > FACT_TOLERANCE_L:
                fact_breaks += 1
                if abs(fact_gap) > abs(worst_fact):
                    worst_fact = fact_gap
                    worst_fact_shift = int(shift.shift_number)

            rows.append({
                "station_code": station_code, "station_name": station_name,
                "tank_number": tank_no,
                "fuel_code": int(tank.fuel_code) if tank.fuel_code is not None else None,
                "fuel_name": (tank.fuel_type or "—").strip(),
                "shift_number": int(shift.shift_number),
                "opened_at": shift.opened_at.isoformat() if shift.opened_at else None,
                "closed_at": shift.closed_at.isoformat() if shift.closed_at else None,
                "book_start": round(book_start, 1),
                "receipts": round(receipts, 1),
                "sales": round(sales, 1),
                "book_end": round(book_end, 1),
                "fact_end": round(fact_end, 1) if fact_end is not None else None,
                "fact_gap": fact_gap,
                "arithmetic_gap": arithmetic_gap,
                "continuity_gap": continuity_gap,
                "mass_start": _n(tank.mass_start), "mass_end": _n(tank.mass_end),
                "mass_received": _n(tank.mass_received), "mass_sales": _n(tank.mass_sales),
                "fact_mass": _n(tank.fact_mass),
                "density_beg": _n(tank.density_beg), "density_end": _n(tank.density),
                "temp_beg": _n(tank.temp_beg), "temp_end": _n(tank.temp_end),
                "level_end": _n(tank.level_end),
                "water_volume": _n(tank.water_volume),
                "fuel_changed": fuel_changed,
            })
            prev, prev_shift = tank, shift

        last = chain[-1][0]
        book_start_period = _f(first.volume_start)
        book_end_period = _f(last.volume_end)
        fact_end_period = _n(last.fact_volume)
        # Расхождение книги и факта на конец периода — то, что пойдёт в инвентаризацию.
        fact_gap_period = (round(book_end_period - fact_end_period, 1)
                           if fact_end_period is not None else None)
        # Разница расхождений начала и конца периода: сколько «набежало» именно
        # за период. Без этого нельзя отделить старую недостачу от новой.
        first_fact_gap = (_f(first.volume_start) - _f(first.fact_volume)
                          if first.fact_volume is not None else None)

        tanks_summary.append({
            "station_code": station_code, "station_name": station_name,
            "tank_number": tank_no,
            "fuel_code": int(last.fuel_code) if last.fuel_code is not None else None,
            "fuel_name": (last.fuel_type or "—").strip(),
            "shifts": len(chain),
            "first_shift": int(chain[0][1].shift_number),
            "last_shift": int(chain[-1][1].shift_number),
            "book_start": round(book_start_period, 1),
            "receipts": round(sum_receipts, 1),
            "sales": round(sum_sales, 1),
            "book_end": round(book_end_period, 1),
            "fact_end": round(fact_end_period, 1) if fact_end_period is not None else None,
            "fact_gap": fact_gap_period,
            "fact_gap_pct": (round(fact_gap_period / sum_sales * 100, 3)
                             if fact_gap_period is not None and sum_sales else None),
            "fact_gap_opening": round(first_fact_gap, 1) if first_fact_gap is not None else None,
            "mass_receipts": round(sum_mass_receipts, 1),
            "mass_sales": round(sum_mass_sales, 1),
            "mass_end": _n(last.mass_end),
            "fact_mass_end": _n(last.fact_mass),
            "arithmetic_breaks": arithmetic_breaks,
            "continuity_breaks": continuity_breaks,
            "fact_breaks": fact_breaks,
            "worst_fact_gap": round(worst_fact, 1) if worst_fact else 0.0,
            "worst_fact_shift": worst_fact_shift,
        })

    # Сортировка: сначала то, где расхождение больше — с этого начинают разбор.
    tanks_summary.sort(key=lambda r: -abs(r["fact_gap"] or 0))
    issues.sort(key=lambda i: -abs(i["gap_liters"] or 0))

    totals = {
        "book_start": round(sum(t["book_start"] for t in tanks_summary), 1),
        "receipts": round(sum(t["receipts"] for t in tanks_summary), 1),
        "sales": round(sum(t["sales"] for t in tanks_summary), 1),
        "book_end": round(sum(t["book_end"] for t in tanks_summary), 1),
        "fact_end": round(sum(t["fact_end"] or 0 for t in tanks_summary), 1),
        "fact_gap": round(sum(t["fact_gap"] or 0 for t in tanks_summary), 1),
        "mass_receipts": round(sum(t["mass_receipts"] for t in tanks_summary), 1),
        "mass_sales": round(sum(t["mass_sales"] for t in tanks_summary), 1),
        "tanks": len(tanks_summary),
        "shifts": len({(r["station_code"], r["shift_number"]) for r in rows}),
        "arithmetic_breaks": sum(t["arithmetic_breaks"] for t in tanks_summary),
        "continuity_breaks": sum(t["continuity_breaks"] for t in tanks_summary),
        "fact_breaks": sum(t["fact_breaks"] for t in tanks_summary),
    }
    totals["fact_gap_pct"] = (round(totals["fact_gap"] / totals["sales"] * 100, 3)
                              if totals["sales"] else 0.0)

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "totals": totals,
        "tanks": tanks_summary,
        "rows": rows[:max_rows],
        "rows_total": len(rows),
        "rows_truncated": len(rows) > max_rows,
        "issues": issues[:500],
        "issues_total": len(issues),
        "tolerances": {
            "arithmetic_liters": ARITHMETIC_TOLERANCE_L,
            "continuity_liters": CONTINUITY_TOLERANCE_L,
            "fact_liters": FACT_TOLERANCE_L,
        },
    }
