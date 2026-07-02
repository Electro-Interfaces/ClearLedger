"""
Агрегатор дашборда сменных отчётов (аналог TradeFrame shiftDashboardService).

Возвращает данные для дашборда: по видам топлива, по способам оплаты, поступления
по ТТН, движение наличных, инкассация, график по дням, операционные метрики и тренды
(сравнение с предыдущим периодом). Источники — FuelShiftSale (продажи по каналам×топливо),
FuelReceipt (ТТН), FuelCashMovement (касса), FuelShift (смены/даты).
"""

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FuelShift, FuelShiftSale, FuelReceipt, FuelCashMovement,
)
from app.services.fuel_mappings import load_mapping_context

# payment_channel (код TradeLedger) → (тип оплаты для UI, только объём без выручки)
_PAY_MAP: dict[str, tuple[str, bool]] = {
    "retail_cash": ("cash", False),
    "retail_card": ("card", False),
    "cards": ("fuel_card", True),
    "online": ("online", True),
    "voucher": ("coupon", True),
    "ledger": ("corporate", True),
}


class FuelDashboardService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID):
        self.session = session
        self.company_id = company_id

    async def _load(self, date_from: date, date_to: date, station_ids: list[uuid.UUID] | None):
        dt_from = datetime(date_from.year, date_from.month, date_from.day)
        dt_to = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)
        q = select(FuelShift).where(
            FuelShift.company_id == self.company_id,
            FuelShift.opened_at >= dt_from,
            FuelShift.opened_at <= dt_to,
        )
        if station_ids:
            q = q.where(FuelShift.station_id.in_(station_ids))
        shifts = (await self.session.execute(q)).scalars().all()
        shift_ids = [s.id for s in shifts]
        sales = (await self.session.execute(select(FuelShiftSale).where(
            FuelShiftSale.shift_id.in_(shift_ids)))).scalars().all() if shift_ids else []
        cash = (await self.session.execute(select(FuelCashMovement).where(
            FuelCashMovement.shift_id.in_(shift_ids)))).scalars().all() if shift_ids else []
        rq = select(FuelReceipt).where(
            FuelReceipt.company_id == self.company_id,
            FuelReceipt.received_at >= dt_from,
            FuelReceipt.received_at <= dt_to,
        )
        if station_ids:
            rq = rq.where(FuelReceipt.station_id.in_(station_ids))
        receipts = (await self.session.execute(rq)).scalars().all()
        return shifts, sales, cash, receipts

    async def compute(self, date_from: date, date_to: date,
                      station_ids: list[uuid.UUID] | None = None, compare: bool = False) -> dict:
        ctx = await load_mapping_context(self.session, self.company_id)

        def fuel_name(code: int) -> str:
            fm = ctx.fuel(code) if code is not None else None
            return (fm.fuel_name if fm else None) or f"код {code}"

        shifts, sales, cash, receipts = await self._load(date_from, date_to, station_ids)
        kpis = self._kpis(shifts, sales, cash, receipts, fuel_name)
        charts = self._charts(shifts, sales, date_from, date_to, fuel_name)

        result = {
            "period": {
                "from": date_from.isoformat(), "to": date_to.isoformat(),
                "days": (date_to - date_from).days + 1,
            },
            **kpis,
            "charts": charts,
        }
        if compare:
            days = (date_to - date_from).days + 1
            cmp_to = date_from - timedelta(days=1)
            cmp_from = cmp_to - timedelta(days=days - 1)
            c_shifts, c_sales, c_cash, c_receipts = await self._load(cmp_from, cmp_to, station_ids)
            c_kpis = self._kpis(c_shifts, c_sales, c_cash, c_receipts, fuel_name)
            result["trends"] = self._trends(kpis, c_kpis)
        return result

    def _kpis(self, shifts, sales, cash, receipts, fuel_name) -> dict:
        fuel_agg = defaultdict(lambda: {"volume": 0.0, "revenue": 0.0})
        pay_agg: dict[str, dict[int, dict]] = defaultdict(lambda: defaultdict(lambda: {"volume": 0.0, "revenue": 0.0}))
        total_revenue = 0.0
        for s in sales:
            fc = s.fuel_code
            liters = float(s.liters or 0)
            amount = float(s.amount or 0)
            fuel_agg[fc]["volume"] += liters
            fuel_agg[fc]["revenue"] += amount
            total_revenue += amount
            pt = _PAY_MAP.get(s.payment_channel)
            if pt:
                ptype = pt[0]
                pay_agg[ptype][fc]["volume"] += liters
                pay_agg[ptype][fc]["revenue"] += amount

        total_volume = sum(f["volume"] for f in fuel_agg.values())
        by_fuel = [{
            "fuel_code": fc, "fuel_name": fuel_name(fc),
            "volume": round(d["volume"], 2), "revenue": round(d["revenue"], 2),
            "percent": round(100 * d["volume"] / total_volume, 1) if total_volume else 0.0,
        } for fc, d in sorted(fuel_agg.items(), key=lambda x: -x[1]["revenue"])]

        payment_details = {}
        for ptype, fuels in pay_agg.items():
            rev = sum(d["revenue"] for d in fuels.values())
            vol = sum(d["volume"] for d in fuels.values())
            vol_only = next((v[1] for v in _PAY_MAP.values() if v[0] == ptype), False)
            payment_details[ptype] = {
                "revenue": round(rev, 2), "volume": round(vol, 2), "volume_only": vol_only,
                "by_fuel": [{
                    "fuel_code": fc, "fuel_name": fuel_name(fc),
                    "revenue": round(d["revenue"], 2), "volume": round(d["volume"], 2),
                } for fc, d in sorted(fuels.items(), key=lambda x: -x[1]["revenue"])],
            }

        return {
            "volume": {"total": round(total_volume, 2), "by_fuel": by_fuel},
            "financial": {"total_revenue": round(total_revenue, 2), "payment_details": payment_details},
            "receipts": self._receipts(receipts, fuel_name),
            **self._cash(cash, shifts),
            "operational": {"shifts_count": len(shifts)},
        }

    def _receipts(self, receipts, fuel_name) -> dict:
        agg = defaultdict(lambda: {"doc": 0.0, "fact": 0.0, "diff": 0.0, "count": 0})
        details = []
        for r in receipts:
            fc = r.fuel_code if r.fuel_code is not None else -1
            dv = float(r.doc_volume_liters or 0)
            fv = float(r.fact_volume_liters or 0)
            diff = float(r.diff_volume or 0) or (fv - dv)
            agg[fc]["doc"] += dv
            agg[fc]["fact"] += fv
            agg[fc]["diff"] += diff
            agg[fc]["count"] += 1
            details.append({
                "ttn": r.ttn, "fuel_code": fc, "fuel_name": r.fuel_name or fuel_name(fc),
                "doc_volume": round(dv, 2), "fact_volume": round(fv, 2), "diff": round(diff, 2),
                "supplier": r.supplier, "tank": r.tank,
                "datetime": r.received_at.isoformat() if r.received_at else None,
            })
        by_fuel = [{
            "fuel_code": fc, "fuel_name": fuel_name(fc),
            "doc_volume": round(d["doc"], 2), "fact_volume": round(d["fact"], 2),
            "diff": round(d["diff"], 2), "ttn_count": d["count"],
        } for fc, d in sorted(agg.items(), key=lambda x: -x[1]["doc"])]
        return {
            "total_doc": round(sum(d["doc"] for d in agg.values()), 2),
            "total_fact": round(sum(d["fact"] for d in agg.values()), 2),
            "total_diff": round(sum(d["diff"] for d in agg.values()), 2),
            "ttn_count": len(details),
            "by_fuel": by_fuel,
            "details": details,
        }

    def _cash(self, cash, shifts) -> dict:
        shift_num = {s.id: s.shift_number for s in shifts}
        income = expense = cashout_total = 0.0
        cf_details, co_details = [], []
        for m in cash:
            name = (m.operation_name or "").lower()
            amt = float(m.amount or 0)
            if "инкасс" in name or "сдан" in name or "изъят" in name:
                cashout_total += amt
                expense += amt
                op_type = "expense"
                co_details.append({
                    "operation": m.operation_name, "amount": round(amt, 2),
                    "pos": m.pos_number, "shift": shift_num.get(m.shift_id),
                })
            elif "внесен" in name or "выручк" in name or "приход" in name:
                income += amt
                op_type = "income"
            elif "выдан" in name or "расход" in name:
                expense += amt
                op_type = "expense"
            elif "открыт" in name or "остаток на нач" in name:
                op_type = "opening"
            elif "закрыт" in name or "передан" in name:
                op_type = "closing"
            else:
                op_type = "income" if amt >= 0 else "expense"
                if amt >= 0:
                    income += amt
                else:
                    expense += abs(amt)
            cf_details.append({
                "operation": m.operation_name, "type": op_type, "amount": round(amt, 2),
                "pos": m.pos_number, "shift": shift_num.get(m.shift_id),
            })
        calc = income - expense
        return {
            "cash_flow": {
                "income": round(income, 2), "expense": round(expense, 2),
                "calculated": round(calc, 2), "closing": round(calc, 2), "difference": 0.0,
                "operations_count": len(cf_details), "details": cf_details,
            },
            "cashout": {
                "total": round(cashout_total, 2), "count": len(co_details), "details": co_details,
            },
        }

    def _charts(self, shifts, sales, date_from, date_to, fuel_name) -> dict:
        sales_by_shift: dict[uuid.UUID, list] = defaultdict(list)
        for s in sales:
            sales_by_shift[s.shift_id].append(s)

        day_agg = {}
        d = date_from
        while d <= date_to:
            day_agg[d.isoformat()] = {
                "date": d.isoformat(), "revenue": 0.0, "volume": 0.0,
                "cash": 0.0, "card": 0.0, "online": 0.0, "corporate": 0.0, "coupon": 0.0,
            }
            d += timedelta(days=1)
        for sh in shifts:
            dkey = sh.opened_at.date().isoformat() if sh.opened_at else None
            g = day_agg.get(dkey)
            if g is None:
                continue
            for s in sales_by_shift.get(sh.id, []):
                amount = float(s.amount or 0)
                g["revenue"] += amount
                g["volume"] += float(s.liters or 0)
                pt = _PAY_MAP.get(s.payment_channel)
                if pt:
                    key = {"fuel_card": "corporate"}.get(pt[0], pt[0])
                    if key in g:
                        g[key] += amount
        daily = [{
            "date": v["date"], "revenue": round(v["revenue"], 2), "volume": round(v["volume"], 2),
            "cash": round(v["cash"], 2), "card": round(v["card"], 2), "online": round(v["online"], 2),
            "corporate": round(v["corporate"], 2), "coupon": round(v["coupon"], 2),
        } for v in sorted(day_agg.values(), key=lambda x: x["date"])]

        fuel_agg = defaultdict(lambda: {"volume": 0.0, "revenue": 0.0})
        for s in sales:
            fuel_agg[s.fuel_code]["volume"] += float(s.liters or 0)
            fuel_agg[s.fuel_code]["revenue"] += float(s.amount or 0)
        total_v = sum(f["volume"] for f in fuel_agg.values())
        by_fuel = [{
            "fuel_code": fc, "fuel_name": fuel_name(fc),
            "volume": round(d["volume"], 2), "revenue": round(d["revenue"], 2),
            "percent": round(100 * d["volume"] / total_v, 1) if total_v else 0.0,
        } for fc, d in sorted(fuel_agg.items(), key=lambda x: -x[1]["volume"])]
        return {"daily": daily, "by_fuel": by_fuel}

    def _trends(self, cur, prev) -> dict:
        def tr(c, p):
            delta = c - p
            pct = (delta / p * 100) if p else (100.0 if c > 0 else 0.0)
            return {
                "current": round(c, 2), "previous": round(p, 2), "delta": round(delta, 2),
                "percent": round(pct, 1),
                "direction": "up" if pct > 0.5 else ("down" if pct < -0.5 else "neutral"),
            }
        return {
            "revenue": tr(cur["financial"]["total_revenue"], prev["financial"]["total_revenue"]),
            "volume": tr(cur["volume"]["total"], prev["volume"]["total"]),
            "shifts": tr(cur["operational"]["shifts_count"], prev["operational"]["shifts_count"]),
        }
