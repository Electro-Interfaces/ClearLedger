"""ABC-XYZ классификация станций ЭЗС — управление активом сети.

Классика управления парком, перенесённая на зарядную сеть:

  • ABC — вклад станции в результат сети (выручка или энергия). Станции
    сортируются по убыванию, берётся накопленная доля: A — верхушка (по умолчанию
    до 80% результата), B — следующие (до 95%), C — длинный хвост. Пара станций
    класса A даёт бо́льшую часть выручки — их берегут; хвост C — кандидаты на
    вывод/переезд.

  • XYZ — стабильность спроса. По бакетам времени (неделя/месяц) считается
    коэффициент вариации (σ/μ) выручки станции, включая НУЛЕВЫЕ периоды: станция,
    что возит каждую неделю ровно, — X (предсказуемая); та, что вспыхивает раз в
    месяц, — Z (рваная). Нули учитываются честно — μ = итог / число_бакетов, а не
    среднее по «рабочим» неделям, иначе спорадическая станция выглядела бы ровной.

На пересечении — 9 групп. AX = ядро сети (высокая ценность + предсказуемость,
беречь и грузить); CZ = низкая ценность + рвань (кандидаты на вывод/переезд).

Скоуп: компания (обязателен) + сужение по станциям/регионам из контура. Станция
резолвится ТОЛЬКО через `charge_sessions.location_id → service_locations`
(station_code партнёров не совпадает — канон CLAUDE.md).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.station_owner import CLASS_LABELS, owner_class_sql

ABC_LABELS = {"A": "A — лидеры", "B": "B — середина", "C": "C — хвост"}
XYZ_LABELS = {
    "X": "X — стабильный спрос",
    "Y": "Y — переменный",
    "Z": "Z — рваный",
    "—": "— мало данных",
}
# Что означает каждая из 9 клеток — коротко, для подсказок в матрице.
CELL_HINT = {
    "AX": "Ядро сети: высокая выручка и стабильный спрос — беречь, грузить, тиражировать.",
    "AY": "Крупные, но с колебаниями — сгладить спрос (тариф/промо в провалы).",
    "AZ": "Крупные, но рваные — разобрать причину скачков (сезон, разовые клиенты).",
    "BX": "Крепкий середняк со стабильным спросом — опора сети.",
    "BY": "Середняк с колебаниями — потенциал роста при выравнивании.",
    "BZ": "Середняк с рваным спросом — точечная работа.",
    "CX": "Малая выручка, но стабильно — ниша/локальная нужда, держать дёшево.",
    "CY": "Малая и переменная — наблюдать.",
    "CZ": "Хвост с рваным спросом — кандидаты на вывод/переезд/пересмотр.",
}


def _n_buckets(df: date, dt: date, bucket: str) -> int:
    """Сколько бакетов (недель/месяцев) покрывает период — знаменатель для μ с нулями."""
    if bucket == "month":
        return (dt.year - df.year) * 12 + (dt.month - df.month) + 1
    # неделя: считаем понедельники (date_trunc('week') = ISO-понедельник)
    start = df - timedelta(days=df.weekday())
    end = dt - timedelta(days=dt.weekday())
    return int((end - start).days // 7) + 1


async def station_abc_xyz(
    db: AsyncSession, company_id: Any, df: date, dt: date, *,
    measure: str = "amount", bucket: str = "week",
    stations: list[str] | None = None, regions: list[str] | None = None,
    a_pct: float = 80.0, b_pct: float = 95.0,
    x_cv: float = 0.5, y_cv: float = 1.0,
) -> dict[str, Any]:
    """ABC-XYZ по станциям за период. measure: amount|energy, bucket: week|month."""
    measure = "energy" if measure == "energy" else "amount"
    bucket = "month" if bucket == "month" else "week"
    m_sql = "cs.energy_kwh" if measure == "energy" else "coalesce(cs.client_amount, cs.amount)"

    lo = datetime.combine(df, datetime.min.time())
    hi = datetime.combine(dt, datetime.max.time())
    params: dict[str, Any] = {"cid": company_id, "lo": lo, "hi": hi, "bucket": bucket}

    scope = ""
    if stations:
        scope += " and cs.station_code = any(:stations)"
        params["stations"] = list(stations)
    if regions:
        scope += (" and cs.location_id in (select sl2.id from service_locations sl2 "
                  "join regions r2 on r2.id = sl2.region_id "
                  "where sl2.company_id = :cid and r2.name = any(:regions))")
        params["regions"] = list(regions)

    rows = (await db.execute(text(f"""
        with base as (
            select cs.location_id as loc,
                   date_trunc(:bucket, cs.started_at) as b,
                   {m_sql} as v
            from charge_sessions cs
            where cs.company_id = :cid and cs.location_id is not null
              and cs.started_at is not null
              and cs.started_at >= :lo and cs.started_at <= :hi{scope}
        ),
        per_bucket as (
            select loc, b, coalesce(sum(v), 0) as v from base group by loc, b
        ),
        agg as (
            select loc,
                   sum(v) as total,
                   count(*) as active_buckets,
                   sum(v * v) as sv2
            from per_bucket group by loc
        ),
        sess as (
            select location_id as loc, count(*) as sessions,
                   coalesce(sum(energy_kwh), 0) as energy,
                   coalesce(sum(coalesce(client_amount, amount)), 0) as amount
            from charge_sessions
            where company_id = :cid and location_id is not null
              and started_at >= :lo and started_at <= :hi
            group by location_id
        )
        select a.loc, a.total, a.active_buckets, a.sv2,
               coalesce(s.sessions, 0) as sessions,
               coalesce(s.energy, 0) as energy, coalesce(s.amount, 0) as amount,
               sl.name, sl.station_number, coalesce(sl.owner, '') as owner,
               {owner_class_sql('sl.owner')} as owner_cls,
               coalesce(r.name, '—') as region
        from agg a
        join service_locations sl on sl.id = a.loc
        left join regions r on r.id = sl.region_id
        left join sess s on s.loc = a.loc
        where a.total > 0
        order by a.total desc
    """), params)).mappings().all()

    n_buckets = max(1, _n_buckets(df, dt, bucket))
    total_net = sum(float(r["total"]) for r in rows) or 1.0

    stations_out: list[dict[str, Any]] = []
    cum = 0.0
    for r in rows:
        total = float(r["total"])
        cum += total
        cum_share = cum / total_net * 100.0
        abc = "A" if cum_share <= a_pct else ("B" if cum_share <= b_pct else "C")
        # XYZ по коэффициенту вариации с нулевыми бакетами
        mean = total / n_buckets
        var = float(r["sv2"]) / n_buckets - mean * mean
        sd = math.sqrt(var) if var > 0 else 0.0
        cv = (sd / mean) if mean > 0 else 0.0
        if n_buckets < 2:
            xyz = "—"
        else:
            xyz = "X" if cv <= x_cv else ("Y" if cv <= y_cv else "Z")
        stations_out.append({
            "location_id": r["loc"],
            "name": r["name"] or f"№{r['station_number'] or r['loc']}",
            "station_number": r["station_number"],
            "region": r["region"], "owner": r["owner"] or None,
            "owner_cls": r["owner_cls"], "owner_label": CLASS_LABELS.get(r["owner_cls"], "—"),
            "measure": round(total, 2),
            "share_pct": round(total / total_net * 100.0, 2),
            "cum_share_pct": round(cum_share, 2),
            "sessions": int(r["sessions"]),
            "energy_kwh": round(float(r["energy"]), 1),
            "amount": round(float(r["amount"]), 2),
            "active_buckets": int(r["active_buckets"]),
            "cv": round(cv, 3),
            "abc": abc, "xyz": xyz, "class": f"{abc}{xyz}",
        })

    # матрица 3×3 (+ колонка «—» при коротком периоде)
    xyz_keys = ["X", "Y", "Z"] + (["—"] if n_buckets < 2 else [])
    cells: dict[str, dict[str, Any]] = {}
    for a in ("A", "B", "C"):
        for x in xyz_keys:
            cells[f"{a}{x}"] = {"abc": a, "xyz": x, "stations": 0, "measure": 0.0,
                                "sessions": 0, "hint": CELL_HINT.get(f"{a}{x}", "")}
    for s in stations_out:
        c = cells.setdefault(s["class"], {"abc": s["abc"], "xyz": s["xyz"], "stations": 0,
                                          "measure": 0.0, "sessions": 0, "hint": ""})
        c["stations"] += 1
        c["measure"] += s["measure"]
        c["sessions"] += s["sessions"]
    cells_out = []
    for c in cells.values():
        c["measure"] = round(c["measure"], 2)
        c["share_pct"] = round(c["measure"] / total_net * 100.0, 2)
        cells_out.append(c)

    def _sum(pred) -> dict[str, Any]:
        sel = [s for s in stations_out if pred(s)]
        return {"stations": len(sel),
                "measure": round(sum(s["measure"] for s in sel), 2),
                "share_pct": round(sum(s["measure"] for s in sel) / total_net * 100.0, 2)}

    return {
        "period": {"from": df.isoformat(), "to": dt.isoformat()},
        "measure": measure, "bucket": bucket,
        "n_buckets": n_buckets,
        "total_measure": round(total_net, 2),
        "stations_total": len(stations_out),
        "thresholds": {"a_pct": a_pct, "b_pct": b_pct, "x_cv": x_cv, "y_cv": y_cv},
        "abc_labels": ABC_LABELS, "xyz_labels": XYZ_LABELS,
        "cells": cells_out,
        "abc_summary": {k: _sum(lambda s, k=k: s["abc"] == k) for k in ("A", "B", "C")},
        "xyz_summary": {k: _sum(lambda s, k=k: s["xyz"] == k) for k in ("X", "Y", "Z")},
        "core": _sum(lambda s: s["class"] == "AX"),
        "tail": _sum(lambda s: s["class"] == "CZ"),
        "stations": stations_out,
    }
