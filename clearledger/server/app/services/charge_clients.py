"""
Когорты клиентов зарядных сессий (раздел «Продажи» ЭЗС → «Сравнение периодов»).

Механика «НОВЫЕ клиенты»: сравнивая интервалы, показываем сколько и какие
конкретно клиенты появились в каждом интервале ВПЕРВЫЕ — то есть никогда не
заряжались раньше (первая сессия за всю историю наблюдений попадает в интервал).

Клиент = организация (client_name, ЮЛ) либо телефон (user_id, ФЛ):
COALESCE(NULLIF(client_name,''), user_id); сессии без идентификатора клиента
в когортах не участвуют. «Историю» считаем В РАМКАХ выбранных фильтров
(станции/регион/тип клиента): сравнивая регион — «новый для региона».

Изолирован от contended AnalyticsService (нарезка интервалов переиспользуется —
_cs_bucket_axis/_cs_interval, чтобы интервалы совпадали со вкладкой 1-в-1).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession
from app.services.analytics_service import AnalyticsService

S = ChargeSession
CLIENT_KEY = func.coalesce(func.nullif(S.client_name, ""), func.nullif(S.user_id, ""))
REVENUE = func.coalesce(S.client_amount, S.amount)

_DIM_COLS = {
    "station": S.station_code,
    "region": S.region,
    "connector": S.connector_type,
    "user_type": S.user_type,
    "charge_type": S.charge_type,
    "result": S.result,
    "client": S.client_name,
}


def _conds(company_id, station_codes: list[str] | None, regions: list[str] | None,
           dim: str | None, dim_val: str | None) -> list:
    conds = [S.company_id == company_id, CLIENT_KEY.is_not(None),
             S.started_at.is_not(None)]
    if station_codes:
        conds.append(S.station_code.in_(station_codes))
    if regions:
        conds.append(S.region.in_(regions))
    if dim and dim_val is not None:
        col = _DIM_COLS.get(dim)
        if col is not None:
            conds.append(col == dim_val)
        elif dim == "tariff":
            try:
                conds.append(S.tariff == float(dim_val))
            except ValueError:
                pass
    return conds


async def _first_seen(db: AsyncSession, conds: list) -> dict[str, date]:
    """Первая сессия каждого клиента за всю историю (в рамках фильтров, БЕЗ дат)."""
    rows = (await db.execute(
        select(CLIENT_KEY.label("k"), func.min(S.started_at).label("fa"))
        .where(*conds).group_by(CLIENT_KEY)
    )).all()
    return {r.k: r.fa.date() for r in rows if r.k and r.fa}


async def new_clients_slice(
    db: AsyncSession, company_id, date_from: date, date_to: date, bucket: str,
    station_codes: list[str] | None = None, regions: list[str] | None = None,
    dim: str | None = None, dim_val: str | None = None,
) -> dict[str, Any]:
    """По интервалам нарезки периода: активные/новые клиенты + вклад новых."""
    conds = _conds(company_id, station_codes, regions, dim, dim_val)
    first = await _first_seen(db, conds)

    # активность по (клиент, день) одним проходом — далее биннинг по интервалам
    day = func.date_trunc("day", S.started_at).label("d")
    act = (await db.execute(
        select(CLIENT_KEY.label("k"), day,
               func.count().label("n"),
               func.sum(S.energy_kwh).label("kwh"),
               func.sum(REVENUE).label("rub"))
        .where(*conds,
               S.started_at >= date_from,
               S.started_at < date_to + timedelta(days=1))
        .group_by(CLIENT_KEY, day)
    )).all()

    axis = AnalyticsService._cs_bucket_axis(date_from, date_to, bucket)
    intervals = []
    for b in axis:
        iv = AnalyticsService._cs_interval(bucket, b)
        iv["partial"] = (date.fromisoformat(iv["from"]) < date_from) or \
                        (date.fromisoformat(iv["to"]) > date_to)
        intervals.append(iv)
    bounds = [(date.fromisoformat(iv["from"]), date.fromisoformat(iv["to"])) for iv in intervals]

    per: list[dict[str, Any]] = [
        {"active": set(), "new": set(), "nS": 0, "nK": 0.0, "nR": 0.0,
         "tS": 0, "tK": 0.0, "tR": 0.0}
        for _ in intervals
    ]
    for r in act:
        d = r.d.date()
        idx = next((i for i, (lo, hi) in enumerate(bounds) if lo <= d <= hi), None)
        if idx is None:
            continue
        c = per[idx]
        c["active"].add(r.k)
        c["tS"] += int(r.n); c["tK"] += float(r.kwh or 0); c["tR"] += float(r.rub or 0)
        fa = first.get(r.k)
        if fa is not None and bounds[idx][0] <= fa <= bounds[idx][1]:
            c["new"].add(r.k)
            c["nS"] += int(r.n); c["nK"] += float(r.kwh or 0); c["nR"] += float(r.rub or 0)

    out = []
    for iv, c in zip(intervals, per):
        n_new, n_act = len(c["new"]), len(c["active"])
        out.append({
            **iv,
            "activeClients": n_act,
            "newClients": n_new,
            "returningClients": n_act - n_new,
            "newSharePct": round(n_new / n_act * 100, 1) if n_act else None,
            "newSessions": c["nS"],
            "newKwh": round(c["nK"], 1),
            "newRevenue": round(c["nR"], 2),
            "totalRevenue": round(c["tR"], 2),
            "newRevenueSharePct": round(c["nR"] / c["tR"] * 100, 1) if c["tR"] else None,
        })
    total_new = len({k for c in per for k in c["new"]})
    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "bucket": bucket, "intervals": out,
        # начало истории наблюдений: интервалы, начинающиеся раньше/на старте
        # истории, показывают завышенных «новых» (вся база выглядит новой)
        "historyFrom": min(first.values()).isoformat() if first else None,
        "totals": {
            "newClients": total_new,
            "activeClients": len({k for c in per for k in c["active"]}),
            "newRevenue": round(sum(c["nR"] for c in per), 2),
        },
    }


async def new_clients_list(
    db: AsyncSession, company_id, date_from: date, date_to: date,
    station_codes: list[str] | None = None, regions: list[str] | None = None,
    dim: str | None = None, dim_val: str | None = None, limit: int = 500,
) -> dict[str, Any]:
    """Конкретные НОВЫЕ клиенты интервала: кто, когда впервые, сколько принёс."""
    conds = _conds(company_id, station_codes, regions, dim, dim_val)
    first_sq = (
        select(CLIENT_KEY.label("k"), func.min(S.started_at).label("fa"))
        .where(*conds).group_by(CLIENT_KEY).subquery()
    )
    hi = date_to + timedelta(days=1)
    rows = (await db.execute(
        select(
            CLIENT_KEY.label("k"),
            func.max(S.user_type).label("user_type"),
            func.max(S.client_name).label("client_name"),
            func.max(S.user_id).label("user_id"),
            first_sq.c.fa.label("first_at"),
            func.count().label("sessions"),
            func.sum(S.energy_kwh).label("kwh"),
            func.sum(REVENUE).label("revenue"),
            func.count(func.distinct(S.station_code)).label("stations"),
        )
        .join(first_sq, first_sq.c.k == CLIENT_KEY)
        .where(*conds,
               S.started_at >= date_from, S.started_at < hi,
               first_sq.c.fa >= date_from, first_sq.c.fa < hi)
        .group_by(CLIENT_KEY, first_sq.c.fa)
        .order_by(func.sum(REVENUE).desc())
    )).all()
    clients = [{
        "key": r.k,
        "userType": r.user_type,
        "clientName": r.client_name or None,
        "userId": r.user_id or None,
        "firstAt": r.first_at.isoformat(sep=" ", timespec="minutes") if r.first_at else None,
        "sessions": int(r.sessions or 0),
        "kwh": round(float(r.kwh or 0), 1),
        "revenue": round(float(r.revenue or 0), 2),
        "stations": int(r.stations or 0),
    } for r in rows[:limit]]
    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "count": len(rows), "clients": clients,
    }
