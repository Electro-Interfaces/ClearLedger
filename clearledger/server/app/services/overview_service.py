"""Executive-обзор сети ЭЗС (energy, РусГидро) — стратегический слой поверх
операционных пунктов (Сессии / Тарифы / Корпоратив).

Изолирован: НЕ трогает contended `analytics_service.py` / `analytics_router.py`
(их правит параллельная работа) — только ВЫЗЫВАЕТ готовый `AnalyticsService`
и `CorporateService`. Собирает единый ответ для дашборда «Обзор»:
KPI с Δ% к прошлому периоду + спарклайны, гейджи, тренд с оверлеем, доли,
топ/дно станций, корпоратив, алерты, meta. Полные количественные разрезы по
всем измерениям фронт берёт отдельно через существующий /charge-sessions.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession
from app.services.analytics_service import AnalyticsService, PeriodFilter
from app.services.corporate_service import CorporateService


def _dpct(cur: float, prev: float) -> float | None:
    """Δ% (cur−prev)/prev. None — если базы нет (нельзя посчитать рост)."""
    if prev:
        return round((cur - prev) / prev * 100, 1)
    return None if not cur else 100.0


def _dir(delta: float | None) -> str:
    if delta is None:
        return "flat"
    if delta > 0.05:
        return "up"
    if delta < -0.05:
        return "down"
    return "flat"


def _util_accent(v: float) -> str:
    return "success" if v >= 15 else "warning" if v >= 10 else "danger"


def _succ_accent(v: float) -> str:
    return "success" if v >= 85 else "warning" if v >= 70 else "danger"


def _unpaid_accent(v: float) -> str:
    return "success" if v <= 3 else "warning" if v <= 10 else "danger"


class OverviewService:
    """Собирает executive-дашборд одним запросом; дельты считает сервер."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.a = AnalyticsService(db)
        self.corp = CorporateService(db)

    @staticmethod
    def _bucket_for(days: int) -> str:
        """Авто-гранулярность тренда/спарклайнов под длину периода."""
        if days <= 60:
            return "day"
        if days <= 250:
            return "week"
        return "month"

    async def _spark(self, f: PeriodFilter, bucket: str, metric: str) -> list[float | None]:
        ts = await self.a.charge_timeseries(f, bucket=bucket, metric=metric)
        return [d.get("value") for d in ts["data"]]

    async def overview(self, company_id: Any, df: date, dt: date, compare: str = "prev") -> dict[str, Any]:
        period_days = (dt - df).days + 1
        prev_to = df - timedelta(days=1)
        prev_from = prev_to - timedelta(days=period_days - 1)
        bucket = self._bucket_for(period_days)

        f_cur = PeriodFilter(company_id=company_id, date_from=df, date_to=dt)
        f_prev = PeriodFilter(company_id=company_id, date_from=prev_from, date_to=prev_to)

        # ─── тоталы текущего/прошлого периода (разрез station → заодно активные ЭЗС) ───
        cur = await self.a.charge_sessions(f_cur, "station")
        prev = await self.a.charge_sessions(f_prev, "station")
        tc, tp = cur["totals"], prev["totals"]
        stations_lines = cur["lines"]
        active_cur = len(stations_lines)
        active_prev = len(prev["lines"])
        # База для сравнения есть только если в прошлом периоде реально были сессии.
        # Иначе (данные начались позже) все дельты — фиктивные «+100%»; честнее null.
        has_prev = tp["sessions"] > 0

        # ─── спарклайны (по метрикам, что поддерживает timeseries) ───
        spark_amount = await self._spark(f_cur, bucket, "amount")
        spark_sessions = await self._spark(f_cur, bucket, "sessions")
        spark_energy = await self._spark(f_cur, bucket, "energy")
        spark_success = await self._spark(f_cur, bucket, "success_pct")
        spark_price = await self._spark(f_cur, bucket, "price_per_kwh")

        def kpi(key, label, value, prev_value, fmt, unit, spark=None, accent=None):
            d = _dpct(float(value), float(prev_value)) if has_prev else None
            item = {
                "key": key, "label": label, "value": round(float(value), 2),
                "prev": round(float(prev_value), 2), "fmt": fmt, "unit": unit,
                "delta_pct": d, "dir": _dir(d),
            }
            if spark is not None:
                item["spark"] = spark
            if accent is not None:
                item["accent"] = accent
            # для метрик, где рост = хорошо (все 7), знак дельты задаёт цвет
            item["good"] = "higher"
            return item

        kpis = [
            kpi("revenue", "Выручка", tc["amount"], tp["amount"], "moneyShort", "₽", spark_amount),
            kpi("sessions", "Сессии", tc["sessions"], tp["sessions"], "int", "", spark_sessions),
            kpi("energy_kwh", "Энергия", tc["energy_kwh"], tp["energy_kwh"], "kwh", "кВтч", spark_energy),
            kpi("utilization_pct", "Загрузка", tc["utilization_pct"], tp["utilization_pct"], "pct", "%",
                None, _util_accent(tc["utilization_pct"])),
            kpi("success_pct", "Успешных", tc["success_pct"], tp["success_pct"], "pct", "%",
                spark_success, _succ_accent(tc["success_pct"])),
            kpi("price_per_kwh", "Цена", tc["price_per_kwh"], tp["price_per_kwh"], "price", "₽/кВтч", spark_price),
            kpi("active_stations", "Активных ЭЗС", active_cur, active_prev, "int", ""),
        ]

        # ─── корпоратив (ЮЛ) ───
        corp = await self.corp.overview(company_id, df, dt)
        corp_rev = corp["totals"]["corp_revenue"]
        total_rev = tc["amount"] or 0.0
        corp_share = round(corp_rev / total_rev * 100, 1) if total_rev else 0.0

        # ─── гейджи-кольца (доля от 100%) ───
        gauges = [
            {"key": "utilization_pct", "label": "Загрузка портов", "value": tc["utilization_pct"],
             "unit": "%", "accent": _util_accent(tc["utilization_pct"]),
             "hint": f"{int(tc['ports'])} портов"},
            {"key": "success_pct", "label": "Успешных сессий", "value": tc["success_pct"],
             "unit": "%", "accent": _succ_accent(tc["success_pct"])},
            {"key": "corp_share", "label": "Доля ЮЛ (выручка)", "value": corp_share,
             "unit": "%", "accent": "info"},
        ]

        # ─── тренд выручки с оверлеем прошлого периода (выравнивание по индексу) ───
        cur_ts = await self.a.charge_timeseries(f_cur, bucket=bucket, metric="amount")
        prev_ts = await self.a.charge_timeseries(f_prev, bucket=bucket, metric="amount")
        cur_pts = cur_ts["data"]
        prev_vals = [d.get("value") for d in prev_ts["data"]] if has_prev else []
        n = len(cur_pts)
        prev_aligned = (prev_vals + [None] * n)[:n]  # паддинг/усечение под текущую ось
        trend = {
            "bucket": bucket,
            "points": [
                {"label": cur_pts[i]["bucket"], "current": cur_pts[i].get("value"), "previous": prev_aligned[i]}
                for i in range(n)
            ],
        }

        # ─── доли (донаты): коннекторы + тип клиента ───
        conn = await self.a.charge_sessions(f_cur, "connector")
        usr = await self.a.charge_sessions(f_cur, "user_type")

        def share_rows(lines: list[dict], top: int = 6) -> list[dict]:
            rows = [{"label": l["label"], "amount": l["amount"], "sessions": l["sessions"],
                     "energy_kwh": l["energy_kwh"], "share_pct": l["share_pct"]} for l in lines[:top]]
            rest = lines[top:]
            if rest:
                rows.append({
                    "label": "Прочие",
                    "amount": round(sum(l["amount"] for l in rest), 2),
                    "sessions": sum(l["sessions"] for l in rest),
                    "energy_kwh": round(sum(l["energy_kwh"] for l in rest), 1),
                    "share_pct": round(sum(l["share_pct"] for l in rest), 2),
                })
            return rows

        shares = {
            "connector": share_rows(conn["lines"]),
            "user_type": share_rows(usr["lines"]),
            "corp_retail": [
                {"label": "Корпоратив (ЮЛ)", "amount": round(corp_rev, 2),
                 "share_pct": corp_share, "sessions": corp["totals"]["sessions"]},
                {"label": "Розница (ФЛ)", "amount": round(total_rev - corp_rev, 2),
                 "share_pct": round(100 - corp_share, 1),
                 "sessions": max(0, tc["sessions"] - corp["totals"]["sessions"])},
            ],
        }

        # ─── топ/дно станций по загрузке (порт-нормировано; фильтр по объёму) ───
        MIN_SESS = 30
        qualified = [l for l in stations_lines if l["sessions"] >= MIN_SESS]
        by_util = sorted(qualified, key=lambda l: -l["utilization_pct"])

        def st_row(l: dict) -> dict:
            return {"label": l["label"], "sessions": l["sessions"], "energy_kwh": l["energy_kwh"],
                    "amount": l["amount"], "utilization_pct": l["utilization_pct"],
                    "success_pct": l["success_pct"], "throughput_port": l["throughput_port"]}

        stations = {
            "top": [st_row(l) for l in by_util[:5]],
            "bottom": [st_row(l) for l in by_util[-5:][::-1]] if len(by_util) > 5 else [],
            "by_revenue": [st_row(l) for l in sorted(stations_lines, key=lambda l: -l["amount"])[:5]],
            "qualified": len(qualified), "min_sessions": MIN_SESS,
        }

        # ─── профиль активности: по часам суток (0-23) + по дням недели (1=Пн..7=Вс) ───
        hourly_raw = await self.a.charge_sessions(f_cur, "hour")
        hmap: dict[int, dict] = {}
        for l in hourly_raw["lines"]:
            try:
                hmap[int(str(l["label"])[:2])] = l
            except (ValueError, TypeError):
                continue
        hourly = [{"hour": h, "label": f"{h:02d}:00",
                   "sessions": hmap[h]["sessions"] if h in hmap else 0,
                   "amount": hmap[h]["amount"] if h in hmap else 0.0} for h in range(24)]

        wd_raw = await self.a.charge_sessions(f_cur, "weekday")
        _WD = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}
        wdm: dict[int, dict] = {}
        for l in wd_raw["lines"]:
            try:
                wdm[int(float(l["label"]))] = l
            except (ValueError, TypeError):
                continue
        wd_days = [{"weekday": w, "label": _WD[w],
                    "amount": wdm[w]["amount"] if w in wdm else 0.0,
                    "sessions": wdm[w]["sessions"] if w in wdm else 0,
                    "energy_kwh": wdm[w]["energy_kwh"] if w in wdm else 0.0} for w in range(1, 8)]
        _nz = [x for x in wd_days if x["amount"] > 0]
        weekday = {
            "days": wd_days,
            "best": max(_nz, key=lambda x: x["amount"])["weekday"] if _nz else None,
            "worst": min(_nz, key=lambda x: x["amount"])["weekday"] if _nz else None,
        }

        # ─── алерты (пороги сети + корпоратив) ───
        alerts: list[dict[str, str]] = []
        if tc["success_pct"] < 85:
            alerts.append({"level": "warn",
                           "message": f"Успешных {tc['success_pct']:.1f}% — {100 - tc['success_pct']:.1f}% сессий с ошибкой"})
        if tc["utilization_pct"] < 15:
            alerts.append({"level": "warn",
                           "message": f"Загрузка сети {tc['utilization_pct']:.1f}% — ниже порога безубыточности (15%)"})
        if tc["unpaid_pct"] > 3:
            alerts.append({"level": "warn", "message": f"Без оплаты {tc['unpaid_pct']:.1f}% сессий"})
        risky = [l for l in stations_lines if l["sessions"] >= MIN_SESS and l["success_pct"] < 70]
        if risky:
            names = ", ".join(l["label"] for l in sorted(risky, key=lambda l: l["success_pct"])[:3])
            alerts.append({"level": "warn",
                           "message": f"Станции риска (успех <70%): {len(risky)} — {names}"})
        alerts.extend(corp.get("alerts", []))

        return {
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
            "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
            "has_baseline": has_prev,
            "compare": compare,
            "period_days": period_days,
            "kpis": kpis,
            "gauges": gauges,
            "trend": trend,
            "shares": shares,
            "stations": stations,
            "hourly": hourly,
            "weekday": weekday,
            "corporate": {
                "corp_revenue": round(corp_rev, 2),
                "retail_revenue": round(corp["totals"]["retail_revenue"], 2),
                "discount": corp["totals"]["discount"],
                "discount_pct": corp["totals"]["discount_pct"],
                "active_clients": corp["totals"]["active_clients"],
                "clients": corp["totals"]["clients"],
                "corp_share_pct": corp_share,
                "top_clients": corp["top_clients"],
            },
            "alerts": alerts,
            "meta": {
                "active_stations": active_cur,
                "ports": int(tc["ports"]),
                "sessions": tc["sessions"],
            },
        }

    async def station_metrics(self, company_id: Any, df: date, dt: date) -> dict[str, Any]:
        """Агрегаты сессий по станции (location_id) за период — для раскраски/размера
        точек на карте. Джойн с координатами делает фронт по location_id (= ServiceLocation.id).
        Учитываются только сопоставленные сессии (location_id проставлен при загрузке)."""
        S = ChargeSession
        lo = datetime.combine(df, datetime.min.time())
        hi = datetime.combine(dt, datetime.max.time())
        days = (dt - df).days + 1
        stmt = select(
            S.location_id.label("loc"),
            func.count().label("cnt"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            func.coalesce(func.sum(func.coalesce(S.client_amount, S.amount)), 0).label("amount"),
            func.coalesce(func.sum(S.duration_min), 0).label("dur"),
            func.coalesce(func.sum(case((S.result == "Complete", 1), else_=0)), 0).label("succ"),
            func.count(distinct(S.connector_no)).label("ports"),
        ).where(
            S.company_id == company_id, S.location_id.is_not(None),
            S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi,
        ).group_by(S.location_id)
        rows = (await self.db.execute(stmt)).all()
        metrics = []
        for r in rows:
            cnt = int(r.cnt)
            ports = int(r.ports or 0)
            port_min = ports * days * 1440
            metrics.append({
                "location_id": r.loc,
                "sessions": cnt,
                "energy_kwh": round(float(r.energy), 1),
                "amount": round(float(r.amount), 2),
                "success_pct": round(int(r.succ) / cnt * 100, 1) if cnt else 0.0,
                "utilization_pct": round(float(r.dur) / port_min * 100, 1) if port_min else 0.0,
            })
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()}, "metrics": metrics}
