import uuid
from collections import defaultdict
from typing import Any

from app.models import FuelShift, FuelStation, FuelTank


CONTINUITY_TOLERANCE_LITERS = 1.0


def build_fuel_balance(
    shifts: list[FuelShift],
    tanks: list[FuelTank],
    stations_map: dict[uuid.UUID, FuelStation],
    group_by: str,
) -> dict[str, Any]:
    shift_map = {shift.id: shift for shift in shifts}

    def shift_order(shift: FuelShift) -> tuple[float, int]:
        moment = shift.closed_at or shift.opened_at
        return (moment.timestamp() if moment else 0.0, int(shift.shift_number or 0))

    def fuel_key(tank: FuelTank) -> str:
        if tank.fuel_code is not None:
            return f"code:{tank.fuel_code}"
        return f"name:{(tank.fuel_type or '—').strip().casefold()}"

    records_by_tank: dict[tuple[uuid.UUID, int], list[tuple[FuelShift, FuelTank]]] = defaultdict(list)
    for tank in tanks:
        shift = shift_map.get(tank.shift_id)
        if shift is not None:
            records_by_tank[(shift.station_id, int(tank.tank_number))].append((shift, tank))

    tank_rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    used_shift_ids: set[uuid.UUID] = set()
    continuity_checks = 0
    fuel_changes = 0

    for (station_id, tank_number), records in records_by_tank.items():
        records.sort(key=lambda pair: shift_order(pair[0]))
        first_shift, first_tank = records[0]
        last_shift, last_tank = records[-1]
        station = stations_map.get(station_id)
        station_name = station.name if station else "АЗС без привязки"
        station_code = int(station.code) if station else None
        first_fuel = (first_tank.fuel_type or "—").strip() or "—"
        last_fuel = (last_tank.fuel_type or "—").strip() or "—"
        fuel_changed = fuel_key(first_tank) != fuel_key(last_tank)
        fuel_name = f"{first_fuel} → {last_fuel}" if fuel_changed else last_fuel
        receipts = sum(float(tank.volume_received or 0) for _, tank in records)
        sales = sum(float(tank.sales or 0) for _, tank in records)
        opening = float(first_tank.volume_start or 0)
        closing = float(last_tank.volume_end or 0)
        variance = opening + receipts - sales - closing
        shift_variance = sum(
            float(tank.volume_start or 0)
            + float(tank.volume_received or 0)
            - float(tank.sales or 0)
            - float(tank.volume_end or 0)
            for _, tank in records
        )
        continuity_gap = 0.0
        continuity_breaks = 0

        for (previous_shift, previous), (current_shift, current) in zip(records, records[1:]):
            continuity_checks += 1
            gap = float(current.volume_start or 0) - float(previous.volume_end or 0)
            continuity_gap += gap
            changed_here = fuel_key(previous) != fuel_key(current)
            if changed_here:
                fuel_changes += 1
            if abs(gap) > CONTINUITY_TOLERANCE_LITERS or changed_here:
                continuity_breaks += 1
                issues.append({
                    "type": "fuel_change" if changed_here else "continuity_gap",
                    "station_id": str(station_id),
                    "station_code": station_code,
                    "station_name": station_name,
                    "tank_number": tank_number,
                    "fuel_name": (
                        f"{(previous.fuel_type or '—').strip()} → {(current.fuel_type or '—').strip()}"
                        if changed_here else (current.fuel_type or previous.fuel_type or "—").strip()
                    ),
                    "previous_shift": int(previous_shift.shift_number),
                    "current_shift": int(current_shift.shift_number),
                    "previous_closed_at": previous_shift.closed_at.isoformat() if previous_shift.closed_at else None,
                    "current_closed_at": current_shift.closed_at.isoformat() if current_shift.closed_at else None,
                    "previous_end_liters": round(float(previous.volume_end or 0), 1),
                    "current_start_liters": round(float(current.volume_start or 0), 1),
                    "gap_liters": round(gap, 1),
                })

        used_shift_ids.update(shift.id for shift, _ in records)
        tank_rows.append({
            "station_id": str(station_id),
            "station_code": station_code,
            "station_name": station_name,
            "tank_number": tank_number,
            "fuel_code": int(last_tank.fuel_code) if last_tank.fuel_code is not None else None,
            "fuel_name": fuel_name,
            "fuel_changed": fuel_changed,
            "first_shift": int(first_shift.shift_number),
            "last_shift": int(last_shift.shift_number),
            "first_closed_at": first_shift.closed_at.isoformat() if first_shift.closed_at else None,
            "last_closed_at": last_shift.closed_at.isoformat() if last_shift.closed_at else None,
            "balance_start_liters": round(opening, 1),
            "receipts_liters": round(receipts, 1),
            "sales_liters": round(sales, 1),
            "balance_end_liters": round(closing, 1),
            "variance_liters": round(variance, 1),
            "variance_pct": round(variance / sales * 100, 3) if sales else 0.0,
            "loss_liters": round(variance, 1),
            "loss_pct": round(variance / sales * 100, 3) if sales else 0.0,
            "shift_variance_liters": round(shift_variance, 1),
            "continuity_gap_liters": round(continuity_gap, 1),
            "continuity_breaks": continuity_breaks,
            "records_count": len(records),
        })

    tank_rows.sort(key=lambda row: (-abs(row["variance_liters"]), row["station_name"], row["tank_number"]))
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "label": "", "station_code": None, "fuel_code": None,
        "start": 0.0, "receipts": 0.0, "sales": 0.0, "end": 0.0,
        "variance": 0.0, "tank_keys": set(), "records": 0, "breaks": 0,
    })

    for row in tank_rows:
        if group_by == "fuel":
            key = f"fuel:{row['fuel_code'] if row['fuel_code'] is not None else row['fuel_name']}"
            label = row["fuel_name"]
        elif group_by == "station_fuel":
            key = f"station:{row['station_id']}|fuel:{row['fuel_code'] if row['fuel_code'] is not None else row['fuel_name']}"
            label = f"{row['station_name']} · {row['fuel_name']}"
        else:
            key = f"station:{row['station_id']}"
            label = row["station_name"]
        group = grouped[key]
        group["label"] = label
        group["station_code"] = row["station_code"] if group_by != "fuel" else None
        group["fuel_code"] = row["fuel_code"] if group_by != "station" else None
        group["start"] += row["balance_start_liters"]
        group["receipts"] += row["receipts_liters"]
        group["sales"] += row["sales_liters"]
        group["end"] += row["balance_end_liters"]
        group["variance"] += row["variance_liters"]
        group["tank_keys"].add((row["station_id"], row["tank_number"]))
        group["records"] += row["records_count"]
        group["breaks"] += row["continuity_breaks"]

    def public_row(group: dict[str, Any]) -> dict[str, Any]:
        opening = round(group["start"], 1)
        receipts = round(group["receipts"], 1)
        sales = round(group["sales"], 1)
        closing = round(group["end"], 1)
        variance = round(opening + receipts - sales - closing, 1)
        return {
            "label": group["label"],
            "station_code": group["station_code"],
            "fuel_code": group["fuel_code"],
            "balance_start_liters": opening,
            "receipts_liters": receipts,
            "sales_liters": sales,
            "balance_end_liters": closing,
            "variance_liters": variance,
            "variance_pct": round(variance / sales * 100, 3) if sales else 0.0,
            "loss_liters": round(variance, 1),
            "loss_pct": round(variance / sales * 100, 3) if sales else 0.0,
            "tanks_count": len(group["tank_keys"]),
            "records_count": group["records"],
            "continuity_breaks": group["breaks"],
        }

    lines = sorted((public_row(group) for group in grouped.values()), key=lambda row: -abs(row["variance_liters"]))
    totals_group = {
        "label": "Итого", "station_code": None, "fuel_code": None,
        "start": sum(row["balance_start_liters"] for row in lines),
        "receipts": sum(row["receipts_liters"] for row in lines),
        "sales": sum(row["sales_liters"] for row in lines),
        "end": sum(row["balance_end_liters"] for row in lines),
        "variance": sum(row["variance_liters"] for row in lines),
        "tank_keys": {(row["station_id"], row["tank_number"]) for row in tank_rows},
        "records": sum(row["records_count"] for row in tank_rows),
        "breaks": sum(row["continuity_breaks"] for row in tank_rows),
    }
    totals = public_row(totals_group)
    issues.sort(key=lambda issue: -abs(issue["gap_liters"]))

    return {
        "lines": lines,
        "tanks": tank_rows,
        "totals": totals,
        "shifts_count": len(used_shift_ids),
        "integrity": {
            "unique_tanks": len(tank_rows),
            "records_count": totals["records_count"],
            "continuity_checks": continuity_checks,
            "continuity_breaks": totals["continuity_breaks"],
            "continuity_gap_liters": round(sum(row["continuity_gap_liters"] for row in tank_rows), 1),
            "fuel_changes": fuel_changes,
            "issues_total": len(issues),
            "issues_truncated": len(issues) > 250,
        },
        "issues": issues[:250],
    }
