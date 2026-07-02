"""
FIFO-движок себестоимости топлива (управленческая маржа на входной себестоимости).

Партия = ТТН-слив с себестоимостью (FuelReceiptCost, ₽/л). По каждой паре
АЗС × вид топлива строится FIFO-очередь партий (по дате поступления); продажи
из смен (FuelShiftSale, в хронологии смен) списываются с головы очереди — «из какой
партии взят проданный литр». Каждый литр несёт себестоимость своей партии.

Итог — маржа по разрезам (fuel / payment / station / month / fuel_payment):
выручка − FIFO-себестоимость. Партии без заданной себестоимости в марже не участвуют
(литры помечаются как «без себестоимости»). Независимо от проводок 1С (90.02).
"""

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FuelStation, FuelShift, FuelShiftSale, FuelReceipt, FuelReceiptCost,
    FuelReceiptOverride,
)
from app.services.fuel_mappings import load_mapping_context

_VAT = 22.0  # НДС, % — выручка приводится к без-НДС как amount × 100/(100+VAT)


@dataclass
class _Batch:
    ttn: str
    received_at: datetime
    remaining: float          # остаток литров партии
    cost_per_liter: float


@dataclass
class _Line:
    label: str
    liters: float = 0.0
    liters_costed: float = 0.0   # литры с известной себестоимостью
    revenue: float = 0.0         # с НДС
    cogs: float = 0.0            # FIFO-себестоимость


@dataclass
class _BatchStat:
    ttn: str
    fuel_code: int
    station_id: str
    total_liters: float
    cost_per_liter: float
    consumed: float = 0.0        # списано литров
    revenue_consumed: float = 0.0  # выручка от списанных литров (пропорция)


def _fkey(code: int | None) -> int:
    return code if code is not None else -1


def _group(group_by: str, fuel_code: int, station_id: str,
           station_names: dict, sale: FuelShiftSale, opened_at: datetime | None):
    if group_by == "payment":
        return sale.payment_channel, sale.payment_channel
    if group_by == "station":
        try:
            nm = station_names.get(uuid.UUID(station_id), station_id)
        except (ValueError, TypeError):
            nm = station_id
        return station_id, nm
    if group_by == "month":
        d = opened_at.date() if opened_at else None
        k = f"{d.year}-{d.month:02d}" if d else "?"
        return k, k
    if group_by == "fuel_payment":
        return f"{fuel_code}|{sale.payment_channel}", (fuel_code, sale.payment_channel)
    return str(fuel_code), fuel_code  # fuel


class FuelCostingService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID):
        self.session = session
        self.company_id = company_id

    async def _build_queues(self) -> dict[tuple[str, int], deque]:
        """FIFO-очереди партий (ТТН с себестоимостью) по (station_id, fuel_code)."""
        costs = {
            (str(c.station_id), c.ttn, c.fuel_code): c
            for c in (await self.session.execute(select(FuelReceiptCost).where(
                FuelReceiptCost.company_id == self.company_id))).scalars()
        }
        overrides = {
            (str(o.station_id), o.ttn, o.fuel_code): o
            for o in (await self.session.execute(select(FuelReceiptOverride).where(
                FuelReceiptOverride.company_id == self.company_id))).scalars()
        }
        receipts = (await self.session.execute(
            select(FuelReceipt).where(FuelReceipt.company_id == self.company_id)
            .order_by(FuelReceipt.received_at))).scalars().all()

        queues: dict[tuple[str, int], deque] = defaultdict(deque)
        self._batch_stats: dict[tuple[str, str, int], _BatchStat] = {}
        for r in receipts:
            fk = _fkey(r.fuel_code)
            ck = (str(r.station_id), r.ttn, fk)
            c = costs.get(ck)
            if c is None:
                continue  # нет себестоимости — партия не участвует в марже
            ov = overrides.get(ck)
            liters = (float(ov.doc_volume_liters) if ov and ov.doc_volume_liters is not None
                      else float(r.doc_volume_liters or 0))
            if liters <= 0:
                continue
            batch = _Batch(ttn=r.ttn, received_at=r.received_at or datetime.min,
                           remaining=liters, cost_per_liter=float(c.cost_per_liter))
            queues[(str(r.station_id), fk)].append(batch)
            self._batch_stats[ck] = _BatchStat(
                ttn=r.ttn, fuel_code=fk, station_id=str(r.station_id),
                total_liters=liters, cost_per_liter=float(c.cost_per_liter))
        # partition-level ссылка: очередь ↔ stat по ttn (для учёта consumed по партии)
        return queues

    async def _sales_ordered(self):
        """Продажи (FuelShiftSale) с датой/станцией смены, в хронологии."""
        shifts = {s.id: s for s in (await self.session.execute(
            select(FuelShift).where(FuelShift.company_id == self.company_id))).scalars()}
        sales = (await self.session.execute(select(FuelShiftSale).where(
            FuelShiftSale.company_id == self.company_id))).scalars().all()
        rows = []
        for s in sales:
            sh = shifts.get(s.shift_id)
            if sh is None:
                continue
            rows.append((sh.opened_at or datetime.min, str(sh.station_id), _fkey(s.fuel_code), s))
        rows.sort(key=lambda x: x[0])
        return rows

    async def compute(self, date_from: date, date_to: date, group_by: str = "fuel") -> dict:
        queues = await self._build_queues()
        sale_rows = await self._sales_ordered()

        station_names = {
            st.id: st.name for st in (await self.session.execute(
                select(FuelStation).where(FuelStation.company_id == self.company_id))).scalars()
        }
        ctx = await load_mapping_context(self.session, self.company_id)

        lines: dict[str, _Line] = defaultdict(lambda: _Line(label=""))
        # ключ партии для consumed-статистики: (station, fuel) → список партий очереди
        # используем сами _Batch (мутируем remaining), consumed = total − remaining в конце.
        # Для выручки партии считаем цену продажи списанных литров пропорцией.

        for opened_at, station_id, fuel_code, sale in sale_rows:
            q = queues.get((station_id, fuel_code))
            need = float(sale.liters or 0)
            sale_amount = float(sale.amount or 0)
            price_per_l = (sale_amount / need) if need > 1e-9 else 0.0
            cogs = 0.0
            costed = 0.0
            if q:
                while need > 1e-9 and q:
                    b = q[0]
                    take = min(need, b.remaining)
                    cogs += take * b.cost_per_liter
                    costed += take
                    b.remaining -= take
                    need -= take
                    if b.remaining <= 1e-9:
                        q.popleft()

            in_period = date_from <= (opened_at.date() if opened_at else date_from) <= date_to
            if not in_period:
                continue
            key, raw_label = _group(group_by, fuel_code, station_id, station_names, sale, opened_at)
            label = self._label(group_by, raw_label, ctx)
            g = lines[key]
            g.label = label
            g.liters += float(sale.liters or 0)
            g.liters_costed += costed
            g.revenue += sale_amount
            g.cogs += cogs

        return self._finalize(lines, date_from, date_to, group_by)

    def _label(self, group_by, raw_label, ctx) -> str:
        if group_by in ("fuel",):
            fm = ctx.fuel(raw_label) if isinstance(raw_label, int) else None
            return (fm.fuel_name if fm else None) or f"код {raw_label}"
        if group_by == "fuel_payment" and isinstance(raw_label, tuple):
            code, ch = raw_label
            fm = ctx.fuel(code)
            return f"{(fm.fuel_name if fm else None) or ('код ' + str(code))} · {ch}"
        return str(raw_label)

    def _finalize(self, lines, date_from, date_to, group_by) -> dict:
        out = []
        tot = _Line(label="Итого")
        for g in lines.values():
            rev_net = g.revenue * 100.0 / (100.0 + _VAT)
            # маржа считается только на литрах с себестоимостью (costed);
            # если часть литров без себестоимости — выручку тоже берём пропорционально
            cost_ratio = (g.liters_costed / g.liters) if g.liters > 1e-9 else 0.0
            rev_net_costed = rev_net * cost_ratio
            margin = rev_net_costed - g.cogs
            out.append({
                "label": g.label,
                "liters": round(g.liters, 2),
                "liters_costed": round(g.liters_costed, 2),
                "liters_uncosted": round(g.liters - g.liters_costed, 2),
                "revenue": round(g.revenue, 2),
                "revenue_net": round(rev_net, 2),
                "cogs": round(g.cogs, 2),
                "margin": round(margin, 2),
                "margin_per_liter": round(margin / g.liters_costed, 4) if g.liters_costed > 1e-9 else 0.0,
                "avg_cost_per_liter": round(g.cogs / g.liters_costed, 4) if g.liters_costed > 1e-9 else 0.0,
            })
            tot.liters += g.liters
            tot.liters_costed += g.liters_costed
            tot.revenue += g.revenue
            tot.cogs += g.cogs
        out.sort(key=lambda x: -x["revenue"])
        tot_rev_net = tot.revenue * 100.0 / (100.0 + _VAT)
        tot_ratio = (tot.liters_costed / tot.liters) if tot.liters > 1e-9 else 0.0
        tot_margin = tot_rev_net * tot_ratio - tot.cogs
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "group_by": group_by,
            "lines": out,
            "totals": {
                "liters": round(tot.liters, 2),
                "liters_costed": round(tot.liters_costed, 2),
                "liters_uncosted": round(tot.liters - tot.liters_costed, 2),
                "revenue": round(tot.revenue, 2),
                "revenue_net": round(tot_rev_net, 2),
                "cogs": round(tot.cogs, 2),
                "margin": round(tot_margin, 2),
            },
        }

    async def batch_stats(self, receipt: FuelReceipt) -> dict:
        """Показатели одной партии (ТТН): списано / остаток / средняя цена реализации / маржа.
        Полный прогон FIFO по станции+топливу, накопление по этой партии."""
        fk = _fkey(receipt.fuel_code)
        station_id = str(receipt.station_id)
        queues = await self._build_queues()
        sale_rows = await self._sales_ordered()

        # найти нашу партию в очереди станции+топлива
        q = queues.get((station_id, fk), deque())
        target = next((b for b in q if b.ttn == receipt.ttn), None)
        if target is None:
            return {"has_cost": False}
        total = target.remaining
        consumed = 0.0
        revenue_consumed = 0.0
        for opened_at, st_id, fuel_code, sale in sale_rows:
            if st_id != station_id or fuel_code != fk:
                continue
            need = float(sale.liters or 0)
            price = (float(sale.amount or 0) / need) if need > 1e-9 else 0.0
            while need > 1e-9 and q:
                b = q[0]
                take = min(need, b.remaining)
                if b is target:
                    consumed += take
                    revenue_consumed += take * price
                b.remaining -= take
                need -= take
                if b.remaining <= 1e-9:
                    q.popleft()
            if target.remaining <= 1e-9 and target not in q:
                # партия исчерпана — дальнейшие продажи её не касаются
                if all(b is not target for b in q):
                    break
        remaining = max(0.0, total - consumed)
        cost = target.cost_per_liter
        return {
            "has_cost": True,
            "cost_per_liter": round(cost, 4),
            "total_liters": round(total, 2),
            "consumed_liters": round(consumed, 2),
            "remaining_liters": round(remaining, 2),
            "avg_sale_price": round(revenue_consumed / consumed, 4) if consumed > 1e-9 else 0.0,
            "cogs_consumed": round(consumed * cost, 2),
            "revenue_consumed": round(revenue_consumed, 2),
            "margin_consumed": round(revenue_consumed * 100.0 / (100.0 + _VAT) - consumed * cost, 2),
        }
