"""Корпоративное направление ЭЗС (ЮЛ) — реестр клиентов + метрики/гэп/биллинг.

Изолировано от analytics_service. Источник: `corporate_clients` (реестр из
справочника) LEFT JOIN агрегаты `charge_sessions` (ЮЛ, период). Ключевое —
двойная цена сессии: розница станции (tariff/amount) vs договор ЮЛ
(client_tariff/client_amount) → скидка/наценка направления.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession, CorporateClient


class CorporateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _metrics_by_client(self, company_id, df: date, dt: date) -> dict[str, Any]:
        """Агрегаты сессий по client_name (период). corp = client_amount (договор),
        retail = energy×tariff (розница-эквивалент)."""
        S = ChargeSession
        lo = datetime.combine(df, datetime.min.time())
        hi = datetime.combine(dt, datetime.max.time())
        stmt = select(
            S.client_name.label("name"),
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            func.coalesce(func.sum(S.client_amount), 0).label("corp"),
            func.coalesce(func.sum(S.energy_kwh * S.tariff), 0).label("retail"),
            func.coalesce(func.sum(case((S.result == "Complete", 1), else_=0)), 0).label("success"),
        ).where(
            S.company_id == company_id, S.client_name.is_not(None),
            S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi,
        ).group_by(S.client_name)
        return {r.name: r for r in (await self.db.execute(stmt)).all()}

    @staticmethod
    def _line(c: CorporateClient, m) -> dict[str, Any]:
        sessions = int(m.sessions) if m else 0
        energy = float(m.energy) if m else 0.0
        corp = float(m.corp) if m else 0.0
        retail = float(m.retail) if m else 0.0
        success = int(m.success) if m else 0
        return {
            "name": c.name, "phone": c.phone, "ext_id": c.ext_id,
            "mode": c.mode, "rate": float(c.rate) if c.rate is not None else None,
            "matrix": c.matrix, "contract_start": c.contract_start,
            "status": c.status, "users": c.users,
            "sessions": sessions, "energy_kwh": round(energy, 1),
            "corp_revenue": round(corp, 2), "retail_revenue": round(retail, 2),
            "discount": round(corp - retail, 2),                                  # <0 = скидка ЮЛ
            "discount_pct": round((corp - retail) / retail * 100, 1) if retail else 0.0,
            "avg_tariff": round(corp / energy, 2) if energy else 0.0,
            "success_pct": round(success / sessions * 100, 1) if sessions else 0.0,
        }

    @staticmethod
    def _totals(lines: list[dict[str, Any]]) -> dict[str, Any]:
        def s(k: str) -> float:
            return sum(x[k] for x in lines)
        energy, corp, retail = s("energy_kwh"), s("corp_revenue"), s("retail_revenue")
        return {
            "clients": len(lines),
            "active_clients": sum(1 for x in lines if x["sessions"] > 0),
            "sessions": int(s("sessions")), "energy_kwh": round(energy, 1),
            "corp_revenue": round(corp, 2), "retail_revenue": round(retail, 2),
            "discount": round(corp - retail, 2),
            "discount_pct": round((corp - retail) / retail * 100, 1) if retail else 0.0,
            "avg_tariff": round(corp / energy, 2) if energy else 0.0,
        }

    async def clients(self, company_id, df: date, dt: date) -> dict[str, Any]:
        """Полная строка по каждому клиенту реестра: договор + метрики + гэп. Питает
        табы Клиенты / Тарифы / Рентабельность / Биллинг."""
        regs = (await self.db.execute(
            select(CorporateClient).where(CorporateClient.company_id == company_id)
            .order_by(CorporateClient.name))).scalars().all()
        metrics = await self._metrics_by_client(company_id, df, dt)
        lines = [self._line(c, metrics.get(c.name)) for c in regs]
        lines.sort(key=lambda x: -x["corp_revenue"])
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                "clients": lines, "totals": self._totals(lines)}

    async def billing(self, company_id, df: date, dt: date, client: str | None = None,
                      vat_rate: float = 20.0) -> dict[str, Any]:
        """Данные под УПД: сводка на клиента + детализация-номенклатура (по договорному
        тарифу). Тариф «НДС в том числе» → выделяем НДС из суммы с НДС (gross)."""
        S = ChargeSession
        lo = datetime.combine(df, datetime.min.time())
        hi = datetime.combine(dt, datetime.max.time())
        conds = [
            S.company_id == company_id, S.client_name.is_not(None),
            S.client_amount.is_not(None),
            S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi,
        ]
        if client:
            conds.append(S.client_name == client)
        stmt = select(
            S.client_name, S.client_tariff,
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            func.coalesce(func.sum(S.client_amount), 0).label("gross"),
        ).where(*conds).group_by(S.client_name, S.client_tariff).order_by(S.client_name)
        raw = (await self.db.execute(stmt)).all()

        vf = vat_rate / (100.0 + vat_rate)   # доля НДС в сумме с НДС
        def split(gross: float) -> tuple[float, float]:
            vat = round(gross * vf, 2)
            return vat, round(gross - vat, 2)   # (НДС, без НДС)

        detail: list[dict[str, Any]] = []
        summ: dict[str, dict[str, float]] = {}
        for r in raw:
            name = r.client_name
            tariff = float(r.client_tariff or 0)
            sessions = int(r.sessions)
            energy = float(r.energy)
            gross = float(r.gross)
            vat, net = split(gross)
            detail.append({"client": name, "tariff": tariff, "sessions": sessions,
                           "energy_kwh": round(energy, 3), "gross": round(gross, 2),
                           "vat": vat, "net": net})
            s = summ.setdefault(name, {"sessions": 0.0, "energy": 0.0, "gross": 0.0})
            s["sessions"] += sessions
            s["energy"] += energy
            s["gross"] += gross

        summary: list[dict[str, Any]] = []
        for name, s in summ.items():
            vat, net = split(s["gross"])
            summary.append({"client": name, "sessions": int(s["sessions"]),
                            "energy_kwh": round(s["energy"], 3), "gross": round(s["gross"], 2),
                            "vat": vat, "net": net,
                            "avg_tariff": round(s["gross"] / s["energy"], 2) if s["energy"] else 0.0})
        summary.sort(key=lambda x: -x["gross"])
        detail.sort(key=lambda x: (x["client"], -x["gross"]))
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                "vat_rate": vat_rate, "summary": summary, "detail": detail}

    async def overview(self, company_id, df: date, dt: date) -> dict[str, Any]:
        """Стратегический слой ЮЛ: KPI + топ-клиенты + алерты."""
        data = await self.clients(company_id, df, dt)
        lines: list[dict[str, Any]] = data["clients"]
        top = [x for x in lines if x["corp_revenue"] > 0][:5]
        alerts: list[dict[str, str]] = []
        inactive = [x for x in lines if (x["status"] or "").strip().lower() not in ("действующая", "")]
        if inactive:
            alerts.append({"level": "warn",
                           "message": f"Договор не «Действующая»: {len(inactive)} — {', '.join(x['name'] for x in inactive[:3])}"})
        deep = [x for x in lines if x["corp_revenue"] > 0 and x["discount_pct"] <= -20]
        if deep:
            alerts.append({"level": "warn",
                           "message": f"Глубокая скидка (≤−20%): {len(deep)} клиент(ов) — {', '.join(x['name'] for x in deep[:3])}"})
        idle = [x for x in lines if x["sessions"] == 0]
        if idle:
            alerts.append({"level": "info",
                           "message": f"Без сессий за период: {len(idle)} клиент(ов)"})
        return {"period": data["period"], "totals": data["totals"],
                "top_clients": top, "alerts": alerts}
