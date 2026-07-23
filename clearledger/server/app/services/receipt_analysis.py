"""Анализ приёмки топлива: ошибки слива бензовозов по каждой ТТН.

Недолив/перелив при сливе — одна из причин расхождения книги с фактом в
резервуаре. Считается ТОЛЬКО по массе (кг), а не по объёму: объём «дышит» с
температурой, и на практике станция часто вписывает объём накладной в факт
один-в-один (проверено на ГИГ: в 74% ТТН doc.volume = fact.volume), тогда как
масса меряется через плотность и показывает настоящее расхождение приёмки.

Каждая ТТН классифицируется по причине — их нельзя складывать в одну цифру:

* `not_measured`  — факт ≈ 0 при документе > 0: слив приняли по накладной, замер
  не делали. Это не недолив, а приёмка вслепую (риск, но недостача не доказана).
* `broken_measure`— факт замерен, но составляет < 85% документа: физически
  бензовоз столько не недоливает — это сорванный/частичный замер, данные
  ненадёжны (либо ТТН разлита по нескольким резервуарам).
* `shortfall`     — факт полноценно замерен и меньше документа сверх допуска:
  реальный недолив, предмет претензии поставщику.
* `surplus`       — факт больше документа сверх допуска: перелив.
* `ok`            — расхождение в пределах допуска приёмки.

Отдельный флаг `density_mismatch` — плотность в накладной и по замеру расходятся:
принята другая партия/марка, чем в документе.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelReceipt, FuelStation

# Допуск приёмки по массе: погрешность взвешивания/замера. Норма для
# нефтепродуктов — доли процента; берём 0,5% массы, но не меньше 20 кг
# (на мелкой ТТН относительный порог даёт слишком узкий коридор).
TOLERANCE_PCT = 0.005
TOLERANCE_MIN_KG = 20.0
# Ниже этой доли документа факт считаем не полноценным замером, а сорванным.
MEASURED_MIN_RATIO = 0.85
# Факт ниже этой доли — замера фактически не было.
NOT_MEASURED_RATIO = 0.02
# Порог расхождения плотности документ↔замер (пересорт/другая партия).
DENSITY_TOLERANCE = 0.003


def _f(v: Any) -> float:
    return float(v) if v is not None else 0.0


def _n(v: Any) -> float | None:
    return float(v) if v is not None else None


def _classify(doc_kg: float, fact_kg: float) -> tuple[str, float]:
    """Причина по массе документа и факта. Возвращает (класс, допуск в кг)."""
    tol = max(doc_kg * TOLERANCE_PCT, TOLERANCE_MIN_KG)
    if doc_kg <= 0:
        return "ok", tol
    ratio = fact_kg / doc_kg if doc_kg else 0.0
    if ratio < NOT_MEASURED_RATIO:
        return "not_measured", tol
    if ratio < MEASURED_MIN_RATIO:
        return "broken_measure", tol
    diff = fact_kg - doc_kg  # < 0 недолив, > 0 перелив
    if diff < -tol:
        return "shortfall", tol
    if diff > tol:
        return "surplus", tol
    return "ok", tol


_CLASS_TITLES = {
    "not_measured": "Без замера (принято по накладной)",
    "broken_measure": "Сорванный замер (данные ненадёжны)",
    "shortfall": "Недолив (претензия поставщику)",
    "surplus": "Перелив",
    "ok": "В норме",
}


async def build_receipt_analysis(
    db: AsyncSession,
    company_id: uuid.UUID,
    date_from: date,
    date_to: date,
    *,
    station_codes: list[int] | None = None,
    fuel_codes: list[int] | None = None,
    max_rows: int = 5000,
) -> dict[str, Any]:
    """Разбор приёмки по ТТН за период: классы причин, сводка, разрез по АЗС."""
    dt_from = datetime(date_from.year, date_from.month, date_from.day)
    dt_to = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)

    q = (
        select(FuelReceipt, FuelStation.code, FuelStation.name)
        .join(FuelStation, FuelStation.id == FuelReceipt.station_id)
        .where(FuelReceipt.company_id == company_id,
               FuelReceipt.received_at >= dt_from,
               FuelReceipt.received_at <= dt_to)
        .order_by(FuelReceipt.received_at.desc())
    )
    if station_codes:
        q = q.where(FuelStation.code.in_([int(c) for c in station_codes]))
    if fuel_codes:
        q = q.where(FuelReceipt.fuel_code.in_([int(c) for c in fuel_codes]))

    records = (await db.execute(q)).all()

    rows: list[dict[str, Any]] = []
    by_class: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "doc_kg": 0.0, "diff_kg": 0.0})
    by_station: dict[int, dict[str, Any]] = {}
    density_mismatch = 0
    sum_doc = sum_fact = 0.0

    for rec, st_code, st_name in records:
        doc_kg = _f(rec.doc_mass_kg)
        fact_kg = _f(rec.fact_mass_kg)
        diff_kg = round(fact_kg - doc_kg, 1)  # < 0 недолив
        cls, tol = _classify(doc_kg, fact_kg)

        dens_doc = _n(rec.density)
        dens_fact = _n(rec.fact_density)
        dens_bad = (dens_doc is not None and dens_fact is not None
                    and abs(dens_doc - dens_fact) > DENSITY_TOLERANCE)
        if dens_bad:
            density_mismatch += 1

        sum_doc += doc_kg
        sum_fact += fact_kg
        c = by_class[cls]
        c["count"] += 1
        c["doc_kg"] += doc_kg
        c["diff_kg"] += diff_kg

        stt = by_station.setdefault(int(st_code), {
            "station_code": int(st_code), "station_name": st_name or f"АЗС {st_code}",
            "ttn": 0, "doc_kg": 0.0, "diff_kg": 0.0,
            "shortfall": 0, "surplus": 0, "not_measured": 0, "broken_measure": 0,
        })
        stt["ttn"] += 1
        stt["doc_kg"] += doc_kg
        stt["diff_kg"] += diff_kg
        if cls in ("shortfall", "surplus", "not_measured", "broken_measure"):
            stt[cls] += 1

        rows.append({
            "ttn": rec.ttn,
            "date": rec.received_at.date().isoformat() if rec.received_at else None,
            "station_code": int(st_code), "station_name": st_name or f"АЗС {st_code}",
            "tank": rec.tank,
            "fuel_code": int(rec.fuel_code) if rec.fuel_code is not None else None,
            "fuel_name": rec.fuel_name,
            "supplier": rec.supplier or "—",
            "doc_mass_kg": round(doc_kg, 1),
            "fact_mass_kg": round(fact_kg, 1),
            "diff_mass_kg": diff_kg,
            "diff_pct": round(diff_kg / doc_kg * 100, 2) if doc_kg else None,
            "doc_volume_l": round(_f(rec.doc_volume_liters), 1),
            "fact_volume_l": round(_f(rec.fact_volume_liters), 1),
            "density_doc": dens_doc,
            "density_fact": dens_fact,
            "density_mismatch": dens_bad,
            "temp_doc": _n(rec.doc_temp),
            "temp_fact": _n(rec.fact_temp),
            "klass": cls,
            "klass_title": _CLASS_TITLES[cls],
        })

    # Итоги по классам с человекочитаемым порядком.
    order = ["shortfall", "not_measured", "broken_measure", "surplus", "ok"]
    classes = [{
        "klass": k, "title": _CLASS_TITLES[k],
        "count": int(by_class[k]["count"]),
        "doc_kg": round(by_class[k]["doc_kg"], 1),
        "diff_kg": round(by_class[k]["diff_kg"], 1),
    } for k in order if by_class.get(k, {}).get("count")]

    stations = sorted(by_station.values(), key=lambda s: s["diff_kg"])
    for s in stations:
        s["doc_kg"] = round(s["doc_kg"], 1)
        s["diff_kg"] = round(s["diff_kg"], 1)

    # Сортировка ленты: сначала самые крупные отклонения по модулю массы.
    rows.sort(key=lambda r: -abs(r["diff_mass_kg"]))

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "totals": {
            "ttn": len(rows),
            "doc_tonn": round(sum_doc / 1000, 1),
            "fact_tonn": round(sum_fact / 1000, 1),
            "diff_kg": round(sum_fact - sum_doc, 1),
            "shortfall_ttn": int(by_class.get("shortfall", {}).get("count", 0)),
            "shortfall_kg": round(by_class.get("shortfall", {}).get("diff_kg", 0.0), 1),
            "surplus_ttn": int(by_class.get("surplus", {}).get("count", 0)),
            "not_measured_ttn": int(by_class.get("not_measured", {}).get("count", 0)),
            "not_measured_kg": round(by_class.get("not_measured", {}).get("doc_kg", 0.0), 1),
            "broken_measure_ttn": int(by_class.get("broken_measure", {}).get("count", 0)),
            "density_mismatch": density_mismatch,
        },
        "classes": classes,
        "by_station": stations,
        "rows": rows[:max_rows],
        "rows_total": len(rows),
        "rows_truncated": len(rows) > max_rows,
        "tolerance": {"pct": TOLERANCE_PCT, "min_kg": TOLERANCE_MIN_KG},
    }
