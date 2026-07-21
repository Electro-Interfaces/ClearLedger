"""Качество использования портов ЭЗС — idle, мощность, dwell time.

Отраслевые дашборды CPO стоят на трёх столпах: uptime, utilization и user
experience. Наша «загрузка» до сих пор отвечала только на вопрос «сколько
времени порт был занят» и не отличала занятость от работы. А это разные вещи:

  • **Занят и заряжает** — порт приносит деньги.
  • **Занят и не заряжает** (idle) — машина стоит подключённой, порт недоступен
    другим, выручки нет. В индустрии это отдельная метрика — *idle time share*,
    и на быстрых портах она дороже всего: DC-порт, занятый три часа под 2 кВт,
    это потерянная очередь, а не медленная зарядка.

**Порог зависит от типа коннектора.** Для Schuko и Type 1 мощность 2–3 кВт —
паспортная норма, а не простой: на них 68–76% времени «медленные», и мерить их
одной линейкой с DC бессмысленно. Поэтому idle считается ТОЛЬКО по быстрым
портам (CCS Combo 2 / CHAdeMO / GB/T DC), где низкая мощность при долгой стоянке
означает проблему: авто закончило зарядку и не отключено, ограничение бортового
зарядного устройства или деградация станции.

**Мощность — по медиане, не по среднему.** Короткая сессия даёт арифметический
выброс (5 кВтч за минуту = 300 кВт), и среднее по CCS выходило 140 кВт при
медиане 30,6. Медиана и p90 описывают парк честно.

На данных сети: 3 290 порт-часов блокировки быстрых портов за 7 месяцев, из них
2 455 — CHAdeMO, у которого медианная мощность 16 кВт при номинале 50.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Быстрые порты: здесь низкая мощность — сигнал, а не характеристика.
DC_CONNECTORS = ("CCS Combo 2", "CHAdeMO", "GB/T DC")

# Порог «порт занят, но не работает»: ниже 7 кВт DC-зарядкой не является
# (это уровень бытовой розетки), дольше часа — уже не «доливает остаток».
IDLE_KW_BELOW = 7.0
IDLE_MIN_ABOVE = 60.0

# Сессии короче двух минут в статистику мощности не берём: деление на
# околонулевую длительность даёт сотни кВт и ломает перцентили.
MIN_DURATION_MIN = 2.0

_BASE = """
WITH s AS (
    SELECT station_code, station_name, connector_type, duration_min, energy_kwh,
           energy_kwh / (duration_min / 60.0) AS kw,
           connector_type = ANY(:dc) AS is_dc
      FROM charge_sessions
     WHERE company_id = :company_id
       AND started_at >= CAST(:date_from AS date)
       AND started_at < CAST(:date_to AS date) + 1
       AND duration_min >= :min_dur AND energy_kwh > 0
       {station_filter}
)
"""


def _f(v: Any) -> Any:
    return float(v) if isinstance(v, Decimal) else v


def _rows(res: Any) -> list[dict[str, Any]]:
    return [{k: _f(v) for k, v in dict(r).items()} for r in res.mappings().all()]


async def port_efficiency(
    db: AsyncSession, company_id, date_from: date, date_to: date,
    stations: list[str] | None = None, top: int = 15,
    regions: list[str] | None = None,
) -> dict[str, Any]:
    """Idle, мощность и dwell по сети, коннекторам и станциям."""
    p = {
        "company_id": str(company_id), "date_from": date_from, "date_to": date_to,
        "dc": list(DC_CONNECTORS), "min_dur": MIN_DURATION_MIN,
        "idle_kw": IDLE_KW_BELOW, "idle_min": IDLE_MIN_ABOVE, "top": top,
    }
    flt = ""
    if stations is not None:
        p["stations"] = stations
        flt += " AND station_code = ANY(:stations)"
    if regions is not None:
        p["regions"] = regions
        # Регион — из справочника (Ф1.3): location_id → region_id → regions.name.
        flt += (" AND location_id IN (SELECT sl.id FROM service_locations sl"
                " JOIN regions r ON r.id = sl.region_id"
                " WHERE sl.company_id = :company_id AND r.name = ANY(:regions))")
    base = _BASE.format(station_filter=flt)

    async def q(sql: str) -> list[dict[str, Any]]:
        return _rows(await db.execute(text(base + sql), p))

    totals = (await q("""
        SELECT count(*) AS sessions,
               coalesce(sum(duration_min), 0) / 60.0 AS port_hours,
               coalesce(sum(duration_min) FILTER (WHERE is_dc), 0) / 60.0 AS dc_port_hours,
               count(*) FILTER (WHERE is_dc AND kw < :idle_kw AND duration_min > :idle_min) AS idle_sessions,
               coalesce(sum(duration_min) FILTER (
                   WHERE is_dc AND kw < :idle_kw AND duration_min > :idle_min), 0) / 60.0 AS idle_hours,
               coalesce(sum(energy_kwh), 0) AS kwh,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_min) AS median_min
          FROM s
    """))[0]

    by_connector = await q("""
        SELECT connector_type AS label, bool_or(is_dc) AS is_dc,
               count(*) AS sessions,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY kw) AS median_kw,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY kw) AS p90_kw,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_min) AS median_min,
               -- Только DC: на Schuko и Type 1 мощность 3 кВт — паспортная
               -- норма, и общий порог показал бы им «простой 97%».
               count(*) FILTER (WHERE is_dc AND kw < :idle_kw AND duration_min > :idle_min) AS idle_sessions,
               coalesce(sum(duration_min) FILTER (
                   WHERE is_dc AND kw < :idle_kw AND duration_min > :idle_min), 0) / 60.0 AS idle_hours,
               coalesce(sum(duration_min), 0) / 60.0 AS port_hours,
               coalesce(sum(energy_kwh), 0) AS kwh
          FROM s WHERE connector_type IS NOT NULL
         GROUP BY 1 ORDER BY port_hours DESC
    """)
    for r in by_connector:
        # Для AC метрика неприменима — отдаём null, а не ноль: ноль читался бы
        # как «простоя нет», хотя его там просто не измеряют.
        r["idle_time_pct"] = (round(r["idle_hours"] / r["port_hours"] * 100, 1)
                              if r["is_dc"] and r["port_hours"] else None)

    # Станции, где блокировка быстрых портов съедает больше всего времени —
    # адресный список для работы с площадкой (разметка, тариф за простой, инфо).
    by_station = await q("""
        SELECT coalesce(max(station_name), station_code) || ' (' || station_code || ')' AS label,
               station_code,
               count(*) FILTER (WHERE is_dc AND kw < :idle_kw AND duration_min > :idle_min) AS idle_sessions,
               coalesce(sum(duration_min) FILTER (
                   WHERE is_dc AND kw < :idle_kw AND duration_min > :idle_min), 0) / 60.0 AS idle_hours,
               coalesce(sum(duration_min) FILTER (WHERE is_dc), 0) / 60.0 AS dc_port_hours,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY kw) FILTER (WHERE is_dc) AS median_kw
          FROM s WHERE station_code IS NOT NULL
         GROUP BY station_code
        HAVING coalesce(sum(duration_min) FILTER (
                   WHERE is_dc AND kw < :idle_kw AND duration_min > :idle_min), 0) > 0
         ORDER BY idle_hours DESC, station_code LIMIT :top
    """)
    for r in by_station:
        r["idle_time_pct"] = round(r["idle_hours"] / r["dc_port_hours"] * 100, 1) if r["dc_port_hours"] else 0.0

    # Распределение по фактической мощности — форма парка одним взглядом.
    bands = await q("""
        SELECT CASE WHEN kw < 3 THEN 1 WHEN kw < 7 THEN 2 WHEN kw < 22 THEN 3
                    WHEN kw < 50 THEN 4 WHEN kw < 100 THEN 5 ELSE 6 END AS band,
               count(*) AS sessions,
               coalesce(sum(duration_min), 0) / 60.0 AS port_hours,
               coalesce(sum(energy_kwh), 0) AS kwh
          FROM s GROUP BY 1 ORDER BY 1
    """)
    band_labels = {1: "< 3 кВт", 2: "3–7 кВт", 3: "7–22 кВт", 4: "22–50 кВт",
                   5: "50–100 кВт", 6: "100+ кВт"}
    for r in bands:
        r["label"] = band_labels.get(int(r["band"]), "—")

    dc_hours = totals["dc_port_hours"] or 0
    idle_hours = totals["idle_hours"] or 0
    return {
        "thresholds": {"idle_kw": IDLE_KW_BELOW, "idle_min": IDLE_MIN_ABOVE,
                       "dc_connectors": list(DC_CONNECTORS)},
        "totals": {
            "sessions": int(totals["sessions"] or 0),
            "port_hours": round(totals["port_hours"] or 0, 1),
            "dc_port_hours": round(dc_hours, 1),
            "idle_sessions": int(totals["idle_sessions"] or 0),
            "idle_hours": round(idle_hours, 1),
            # Доля времени быстрых портов, потраченная впустую — та самая
            # idle time share из отраслевых дашбордов.
            "idle_time_pct": round(idle_hours / dc_hours * 100, 1) if dc_hours else 0.0,
            "kwh": round(totals["kwh"] or 0, 1),
            "median_min": round(totals["median_min"] or 0, 1),
        },
        "connectors": by_connector,
        "stations": by_station,
        "bands": bands,
    }
