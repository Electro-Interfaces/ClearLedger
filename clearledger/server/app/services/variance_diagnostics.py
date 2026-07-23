"""Диагностика причин расхождения книги с фактом по каждому резервуару.

Расхождение книга↔факт на одной смене само по себе причину не выдаёт: замер
уровнемера шумит, книжная и фактическая масса считаются по разной плотности
(на данных ГИГ недостачи и излишки по массе почти поровну и в тонны — реальные
потери так не выглядят). Причина читается по ПОВЕДЕНИЮ расхождения во времени —
как оно ведёт себя от смены к смене по каждому резервуару:

* `stable`  — расхождение держится около постоянного уровня (низкий разброс).
  Топливо не теряется и не прибывает — это старая некорректированная разница
  или систематическое смещение замера. Лечится разовой инвентаризацией.
* `drift`   — расхождение монотонно растёт: недостача (или излишек) копится
  смена за сменой. Это реальный систематический процесс — испарение в жару,
  утечка, недоучёт счётчиков ТРК. Нужно искать причину, а не просто списывать.
* `jump`    — расхождение резко изменилось в одну смену и осталось. Разовое
  событие: чаще всего слив бензовоза (приёмка), подкачка или сбой замера.
  Разбирается конкретная смена.
* `noise`   — большой разброс без тренда и без единичного скачка: замер
  нестабилен (неисправный уровнемер, подтоварная вода, наклон резервуара).

Отдельный признак `temperature` — часть колебания объёма, объяснимая тем, что
масса топлива держится стабильно, а объём гуляет: это тепловое расширение, а не
потеря. Он не заменяет класс, а дополняет его.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelShift, FuelStation, FuelTank

VOL_TOL = 50.0    # допуск по объёму (л) — погрешность уровнемера
MASS_TOL = 40.0   # допуск по массе (кг) ≈ 50 л по типовой плотности
MIN_SHIFTS = 4    # меньше — ряда для диагностики не хватает


def _f(v: Any) -> float:
    return float(v) if v is not None else 0.0


def _slope(ys: list[float]) -> float:
    """Наклон линии тренда (МНК) по равномерным точкам 0..n-1. Л/смену."""
    n = len(ys)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2.0
    my = sum(ys) / n
    num = sum((i - mx) * (ys[i] - my) for i in range(n))
    den = sum((i - mx) ** 2 for i in range(n))
    return num / den if den else 0.0


def _stddev(ys: list[float]) -> float:
    n = len(ys)
    if n < 2:
        return 0.0
    m = sum(ys) / n
    return (sum((y - m) ** 2 for y in ys) / (n - 1)) ** 0.5


_NATURE_TITLES = {
    "stable": "Стабильное смещение",
    "drift": "Систематическая убыль/прибыль",
    "jump": "Разовый скачок",
    "noise": "Нестабильный замер",
    "short": "Мало смен для диагностики",
}


def _diagnose(rows: list[dict]) -> dict[str, Any]:
    """Классифицировать причину расхождения одного резервуара по ряду смен."""
    gaps = [r["gap_vol"] for r in rows]
    n = len(gaps)
    if n < MIN_SHIFTS:
        return {"nature": "short", "nature_title": _NATURE_TITLES["short"],
                "mean_gap": round(sum(gaps) / n, 1) if n else 0.0,
                "std_gap": 0.0, "trend_per_shift": 0.0, "accumulated": 0.0,
                "jump_liters": 0.0, "jump_shift": None, "jump_on_receipt": False,
                "temperature_share": 0.0}

    std = _stddev(gaps)
    slope = _slope(gaps)
    accumulated = slope * (n - 1)  # насколько тренд сдвинул расхождение за период

    # крупнейший скачок между соседними сменами
    jump = 0.0
    jump_idx = 0
    for i in range(1, n):
        d = gaps[i] - gaps[i - 1]
        if abs(d) > abs(jump):
            jump, jump_idx = d, i
    jump_row = rows[jump_idx] if jump else None

    # температурная доля: масса держится, объём гуляет
    temp_hits = sum(1 for r in rows if abs(r["gap_mass"]) <= MASS_TOL and abs(r["gap_vol"]) > VOL_TOL)
    temp_share = temp_hits / n

    if std <= VOL_TOL * 1.2:
        nature = "stable"
    elif abs(accumulated) >= max(150.0, 1.5 * std) and abs(accumulated) >= abs(jump) * 0.8:
        nature = "drift"
    elif abs(jump) >= max(300.0, 3.0 * std):
        nature = "jump"
    else:
        nature = "noise"

    return {
        "nature": nature, "nature_title": _NATURE_TITLES[nature],
        "mean_gap": round(sum(gaps) / n, 1),
        "std_gap": round(std, 1),
        "trend_per_shift": round(slope, 2),
        "accumulated": round(accumulated, 1),
        "jump_liters": round(jump, 1),
        "jump_shift": int(jump_row["shift_number"]) if jump_row else None,
        "jump_on_receipt": bool(jump_row and jump_row["receipts"] > 1) if jump_row else False,
        "temperature_share": round(temp_share, 2),
    }


async def build_variance_diagnostics(
    db: AsyncSession,
    company_id: uuid.UUID,
    date_from: date,
    date_to: date,
    *,
    station_codes: list[int] | None = None,
    fuel_codes: list[int] | None = None,
) -> dict[str, Any]:
    """Разбор причин расхождения книга↔факт по резервуарам за период."""
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
    if fuel_codes:
        q = q.where(FuelTank.fuel_code.in_([int(c) for c in fuel_codes]))

    records = (await db.execute(q)).all()

    chains: dict[tuple[int, int], list[dict]] = defaultdict(list)
    meta: dict[tuple[int, int], dict] = {}
    for tank, shift, station in records:
        # факт нужен: без замера диагностировать нечего
        if tank.fact_volume is None:
            continue
        key = (int(station.code), int(tank.tank_number))
        chains[key].append({
            "shift_number": int(shift.shift_number),
            "gap_vol": _f(tank.volume_end) - _f(tank.fact_volume),
            "gap_mass": (_f(tank.mass_end) - _f(tank.fact_mass)) if tank.fact_mass is not None else 0.0,
            "receipts": _f(tank.volume_received),
        })
        meta[key] = {"station_name": station.name or f"АЗС {station.code}",
                     "fuel_name": (tank.fuel_type or "—").strip(),
                     "fuel_code": int(tank.fuel_code) if tank.fuel_code is not None else None}

    tanks: list[dict[str, Any]] = []
    by_nature: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "abs_accum": 0.0})
    for (st_code, tank_no), rows in chains.items():
        diag = _diagnose(rows)
        m = meta[(st_code, tank_no)]
        tanks.append({
            "station_code": st_code, "station_name": m["station_name"],
            "tank_number": tank_no, "fuel_code": m["fuel_code"], "fuel_name": m["fuel_name"],
            "shifts": len(rows),
            "last_gap": round(rows[-1]["gap_vol"], 1),
            **diag,
        })
        by_nature[diag["nature"]]["count"] += 1
        by_nature[diag["nature"]]["abs_accum"] += abs(diag["accumulated"])

    order = ["drift", "jump", "noise", "stable", "short"]
    natures = [{
        "nature": k, "title": _NATURE_TITLES[k],
        "count": int(by_nature[k]["count"]),
        "abs_accum": round(by_nature[k]["abs_accum"], 1),
    } for k in order if by_nature.get(k, {}).get("count")]

    # сначала то, что растёт (drift), потом скачки — с этого начинают разбор
    priority = {"drift": 0, "jump": 1, "noise": 2, "stable": 3, "short": 4}
    tanks.sort(key=lambda t: (priority.get(t["nature"], 9), -abs(t["accumulated"])))

    temp_driven = sum(1 for t in tanks if t["temperature_share"] >= 0.5)

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "totals": {
            "tanks": len(tanks),
            "drift": int(by_nature.get("drift", {}).get("count", 0)),
            "jump": int(by_nature.get("jump", {}).get("count", 0)),
            "noise": int(by_nature.get("noise", {}).get("count", 0)),
            "stable": int(by_nature.get("stable", {}).get("count", 0)),
            "temperature_driven": temp_driven,
        },
        "natures": natures,
        "tanks": tanks,
        "tolerance": {"vol_liters": VOL_TOL, "mass_kg": MASS_TOL, "min_shifts": MIN_SHIFTS},
    }
