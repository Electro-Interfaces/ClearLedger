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
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FuelStation, FuelShift, FuelShiftSale, FuelReceipt, FuelReceiptCost,
    FuelReceiptOverride, FuelShiftSaleOverride, FuelOpeningBalance,
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


@dataclass
class _EffectiveSale:
    shift_id: uuid.UUID
    payment_channel: str
    fuel_code: int
    liters: float
    amount: float


@dataclass
class _Allocation:
    batch: _Batch | None
    sale: _EffectiveSale
    liters: float
    revenue: float
    cogs: float


def _fkey(code: int | None) -> int:
    return code if code is not None else -1


def _batch_available(batch: _Batch, opened_at: datetime) -> bool:
    if batch.received_at == datetime.min:
        return True
    if opened_at == datetime.min:
        return False
    return batch.received_at <= opened_at


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
    if group_by == "station_fuel":
        try:
            station = station_names.get(uuid.UUID(station_id), station_id)
        except (ValueError, TypeError):
            station = station_id
        return f"{station_id}|{fuel_code}", (station, fuel_code)
    return str(fuel_code), fuel_code  # fuel


class FuelCostingService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID):
        self.session = session
        self.company_id = company_id

    async def _build_queues(self, station_id: str | None = None,
                            fuel_code: int | None = None,
                            include_opening: bool = True) -> dict[tuple[str, int], deque]:
        """FIFO-очереди партий (ТТН с себестоимостью) по (station_id, fuel_code)."""
        cost_query = select(FuelReceiptCost).where(FuelReceiptCost.company_id == self.company_id)
        override_query = select(FuelReceiptOverride).where(FuelReceiptOverride.company_id == self.company_id)
        receipt_query = select(FuelReceipt).where(FuelReceipt.company_id == self.company_id)
        opening_query = select(FuelOpeningBalance).where(
            FuelOpeningBalance.company_id == self.company_id)
        if station_id is not None:
            station_uuid = uuid.UUID(station_id)
            cost_query = cost_query.where(FuelReceiptCost.station_id == station_uuid)
            override_query = override_query.where(FuelReceiptOverride.station_id == station_uuid)
            receipt_query = receipt_query.where(FuelReceipt.station_id == station_uuid)
            opening_query = opening_query.where(FuelOpeningBalance.station_id == station_uuid)
        if fuel_code is not None:
            cost_query = cost_query.where(FuelReceiptCost.fuel_code == fuel_code)
            override_query = override_query.where(FuelReceiptOverride.fuel_code == fuel_code)
            receipt_query = receipt_query.where(
                FuelReceipt.fuel_code.is_(None) if fuel_code == -1 else FuelReceipt.fuel_code == fuel_code
            )
            opening_query = opening_query.where(FuelOpeningBalance.fuel_code == fuel_code)
        costs = {
            (str(c.station_id), c.ttn, c.fuel_code): c
            for c in (await self.session.execute(cost_query)).scalars()
        }
        overrides = {
            (str(o.station_id), o.ttn, o.fuel_code): o
            for o in (await self.session.execute(override_query)).scalars()
        }
        receipts = (await self.session.execute(
            receipt_query.order_by(FuelReceipt.received_at))).scalars().all()

        queues: dict[tuple[str, int], deque] = defaultdict(deque)
        self._batch_stats: dict[tuple[str, str, int], _BatchStat] = {}
        positive_receipts = 0
        costed_receipts = 0
        nonpositive_receipts = 0
        opening_rows = []
        if include_opening:
            opening_rows = (await self.session.execute(opening_query)).scalars().all()
            for row in opening_rows:
                liters = float(row.liters or 0)
                cost = float(row.cost_per_liter or 0)
                if liters <= 0 or cost <= 0:
                    continue
                queues[(str(row.station_id), row.fuel_code)].append(_Batch(
                    ttn="__opening__", received_at=row.as_of,
                    remaining=liters, cost_per_liter=cost,
                ))
        for r in receipts:
            fk = _fkey(r.fuel_code)
            ck = (str(r.station_id), r.ttn, fk)
            ov = overrides.get(ck)
            liters = (float(ov.doc_volume_liters) if ov and ov.doc_volume_liters is not None
                      else float(r.doc_volume_liters or 0))
            if liters <= 0:
                nonpositive_receipts += 1
                continue
            positive_receipts += 1
            c = costs.get(ck)
            if c is None:
                continue  # нет себестоимости — партия не участвует в марже
            costed_receipts += 1
            batch = _Batch(ttn=r.ttn, received_at=r.received_at or datetime.min,
                           remaining=liters, cost_per_liter=float(c.cost_per_liter))
            queues[(str(r.station_id), fk)].append(batch)
            self._batch_stats[ck] = _BatchStat(
                ttn=r.ttn, fuel_code=fk, station_id=str(r.station_id),
                total_liters=liters, cost_per_liter=float(c.cost_per_liter))
        self._costing_readiness = {
            "positive_receipts": positive_receipts,
            "costed_receipts": costed_receipts,
            "uncosted_receipts": positive_receipts - costed_receipts,
            "nonpositive_receipts": nonpositive_receipts,
            "opening_balances": len(opening_rows),
            "opening_balance_liters": round(sum(float(row.liters or 0) for row in opening_rows), 3),
            "opening_balance_value": round(sum(
                float(row.liters or 0) * float(row.cost_per_liter or 0) for row in opening_rows
            ), 2),
        }
        for key, queue in queues.items():
            queues[key] = deque(sorted(queue, key=lambda batch: batch.received_at))
        # partition-level ссылка: очередь ↔ stat по ttn (для учёта consumed по партии)
        return queues

    async def _sales_ordered(self, station_id: str | None = None,
                             fuel_code: int | None = None):
        """Продажи с L2-корректировками и данными смены, в хронологии."""
        shift_query = select(FuelShift).where(FuelShift.company_id == self.company_id)
        if station_id is not None:
            shift_query = shift_query.where(FuelShift.station_id == uuid.UUID(station_id))
        shifts = {s.id: s for s in (await self.session.execute(
            shift_query)).scalars()}
        self._shift_lookup = shifts
        override_query = select(FuelShiftSaleOverride).where(
            FuelShiftSaleOverride.company_id == self.company_id)
        if station_id is not None:
            override_query = override_query.where(FuelShiftSaleOverride.station_id == uuid.UUID(station_id))
        if fuel_code is not None:
            override_query = override_query.where(FuelShiftSaleOverride.fuel_code == fuel_code)
        overrides = {
            (str(o.station_id), o.shift_number, o.payment_channel, o.fuel_code): o
            for o in (await self.session.execute(override_query)).scalars()
        }
        sale_query = select(FuelShiftSale).where(FuelShiftSale.company_id == self.company_id)
        if station_id is not None:
            sale_query = sale_query.where(FuelShiftSale.shift_id.in_(list(shifts)))
        if fuel_code is not None:
            sale_query = sale_query.where(FuelShiftSale.fuel_code == fuel_code)
        sales = (await self.session.execute(sale_query)).scalars().all()
        rows = []
        for s in sales:
            sh = shifts.get(s.shift_id)
            if sh is None:
                continue
            ov = overrides.get((str(sh.station_id), sh.shift_number, s.payment_channel, s.fuel_code))
            sale = _EffectiveSale(
                shift_id=s.shift_id,
                payment_channel=s.payment_channel,
                fuel_code=s.fuel_code,
                liters=float(ov.liters if ov and ov.liters is not None else s.liters or 0),
                amount=float(ov.amount if ov and ov.amount is not None else s.amount or 0),
            )
            rows.append((sh.opened_at or datetime.min, str(sh.station_id), _fkey(s.fuel_code), sale))
        rows.sort(key=lambda x: (x[0], str(x[3].shift_id), x[3].payment_channel))
        return rows

    @staticmethod
    def _sale_groups(sale_rows):
        groups = {}
        for opened_at, station_id, fuel_code, sale in sale_rows:
            key = (opened_at, station_id, fuel_code, sale.shift_id)
            groups.setdefault(key, []).append(sale)
        return [(*key[:3], sales) for key, sales in groups.items()]

    @staticmethod
    def _allocate_group(q: deque | None, opened_at: datetime,
                        sales: list[_EffectiveSale]) -> list[_Allocation]:
        positive = [sale for sale in sales if float(sale.liters or 0) > 1e-9]
        total_liters = sum(float(sale.liters or 0) for sale in positive)
        if total_liters <= 1e-9:
            return []

        chunks: list[tuple[_Batch | None, float]] = []
        need = total_liters
        while need > 1e-9:
            if not q:
                chunks.append((None, need))
                break
            batch = q[0]
            if not _batch_available(batch, opened_at):
                chunks.append((None, need))
                break
            take = min(need, batch.remaining)
            chunks.append((batch, take))
            batch.remaining -= take
            need -= take
            if batch.remaining <= 1e-9:
                q.popleft()

        allocations = []
        for batch, chunk_liters in chunks:
            for sale in positive:
                ratio = float(sale.liters or 0) / total_liters
                liters = chunk_liters * ratio
                revenue = float(sale.amount or 0) * chunk_liters / total_liters
                allocations.append(_Allocation(
                    batch=batch,
                    sale=sale,
                    liters=liters,
                    revenue=revenue,
                    cogs=liters * batch.cost_per_liter if batch is not None else 0.0,
                ))
        return allocations

    async def recalculate_opening_balances(self) -> dict:
        """Рассчитать минимальный входящий остаток, исключающий отрицательный FIFO."""
        queues = await self._build_queues(include_opening=False)
        sales = await self._sales_ordered()
        events: dict[tuple[str, int], list[tuple[datetime, int, float]]] = defaultdict(list)
        first_cost: dict[tuple[str, int], float] = {}
        fuel_cost_value: dict[int, float] = defaultdict(float)
        fuel_cost_liters: dict[int, float] = defaultdict(float)

        for partition, queue in queues.items():
            for batch in queue:
                events[partition].append((batch.received_at, 0, batch.remaining))
                first_cost.setdefault(partition, batch.cost_per_liter)
                fuel_cost_value[partition[1]] += batch.remaining * batch.cost_per_liter
                fuel_cost_liters[partition[1]] += batch.remaining
        for opened_at, station_id, fuel_code, sale in sales:
            liters = float(sale.liters or 0)
            if liters > 0:
                events[(station_id, fuel_code)].append((opened_at, 1, -liters))

        all_value = sum(fuel_cost_value.values())
        all_liters = sum(fuel_cost_liters.values())
        existing = {
            (str(row.station_id), row.fuel_code): row
            for row in (await self.session.execute(select(FuelOpeningBalance).where(
                FuelOpeningBalance.company_id == self.company_id))).scalars().all()
        }
        required = {}
        for partition, partition_events in events.items():
            balance = 0.0
            minimum = 0.0
            for _, _, delta in sorted(partition_events, key=lambda item: (item[0], item[1])):
                balance += delta
                minimum = min(minimum, balance)
            liters = math.ceil(max(0.0, -minimum) * 1000.0) / 1000.0
            if liters <= 0:
                continue
            cost = first_cost.get(partition)
            if cost is None and fuel_cost_liters.get(partition[1], 0) > 0:
                cost = fuel_cost_value[partition[1]] / fuel_cost_liters[partition[1]]
            if cost is None and all_liters > 0:
                cost = all_value / all_liters
            if cost is None:
                continue
            as_of = min(item[0] for item in partition_events) - timedelta(seconds=1)
            required[partition] = (liters, round(cost, 4), as_of)

        for partition, (liters, cost, as_of) in required.items():
            row = existing.get(partition)
            if row is not None and row.source == "manual":
                continue
            if row is None:
                row = FuelOpeningBalance(
                    company_id=self.company_id,
                    station_id=uuid.UUID(partition[0]),
                    fuel_code=partition[1],
                )
                self.session.add(row)
            row.as_of = as_of
            row.liters = liters
            row.cost_per_liter = cost
            row.source = "auto"
            row.note = "Минимальный входящий остаток по загруженной истории FIFO"

        for partition, row in existing.items():
            if row.source == "auto" and partition not in required:
                await self.session.delete(row)
        await self.session.flush()
        rows = (await self.session.execute(select(FuelOpeningBalance).where(
            FuelOpeningBalance.company_id == self.company_id))).scalars().all()
        return {
            "count": len(rows),
            "liters": round(sum(float(row.liters or 0) for row in rows), 3),
            "value": round(sum(
                float(row.liters or 0) * float(row.cost_per_liter or 0) for row in rows
            ), 2),
        }

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

        for opened_at, station_id, fuel_code, sales in self._sale_groups(sale_rows):
            q = queues.get((station_id, fuel_code))
            allocations = self._allocate_group(q, opened_at, sales)
            in_period = date_from <= (opened_at.date() if opened_at else date_from) <= date_to
            if not in_period:
                continue
            for allocation in allocations:
                key, raw_label = _group(
                    group_by, fuel_code, station_id, station_names,
                    allocation.sale, opened_at,
                )
                label = self._label(group_by, raw_label, ctx)
                line = lines[key]
                line.label = label
                line.liters += allocation.liters
                line.liters_costed += allocation.liters if allocation.batch is not None else 0.0
                line.revenue += allocation.revenue
                line.cogs += allocation.cogs

        return self._finalize(lines, date_from, date_to, group_by)

    def _label(self, group_by, raw_label, ctx) -> str:
        if group_by in ("fuel",):
            fm = ctx.fuel(raw_label) if isinstance(raw_label, int) else None
            return (fm.fuel_name if fm else None) or f"код {raw_label}"
        if group_by == "fuel_payment" and isinstance(raw_label, tuple):
            code, ch = raw_label
            fm = ctx.fuel(code)
            return f"{(fm.fuel_name if fm else None) or ('код ' + str(code))} · {ch}"
        if group_by == "station_fuel" and isinstance(raw_label, tuple):
            station, code = raw_label
            fm = ctx.fuel(code)
            fuel = (fm.fuel_name if fm else None) or f"код {code}"
            return f"{station} · {fuel}"
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
                "avg_sale_price": round(g.revenue / g.liters, 4) if g.liters > 1e-9 else 0.0,
                "avg_sale_price_net": round(rev_net / g.liters, 4) if g.liters > 1e-9 else 0.0,
                "margin_pct": round(margin / rev_net_costed * 100.0, 2) if rev_net_costed > 1e-9 else 0.0,
                "coverage_pct": round(cost_ratio * 100.0, 2),
            })
            tot.liters += g.liters
            tot.liters_costed += g.liters_costed
            tot.revenue += g.revenue
            tot.cogs += g.cogs
        out.sort(key=lambda x: -x["revenue"])
        tot_rev_net = tot.revenue * 100.0 / (100.0 + _VAT)
        tot_ratio = (tot.liters_costed / tot.liters) if tot.liters > 1e-9 else 0.0
        tot_margin = tot_rev_net * tot_ratio - tot.cogs
        tot_rev_net_costed = tot_rev_net * tot_ratio
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
                "margin_per_liter": round(tot_margin / tot.liters_costed, 4) if tot.liters_costed > 1e-9 else 0.0,
                "avg_cost_per_liter": round(tot.cogs / tot.liters_costed, 4) if tot.liters_costed > 1e-9 else 0.0,
                "avg_sale_price": round(tot.revenue / tot.liters, 4) if tot.liters > 1e-9 else 0.0,
                "avg_sale_price_net": round(tot_rev_net / tot.liters, 4) if tot.liters > 1e-9 else 0.0,
                "margin_pct": round(tot_margin / tot_rev_net_costed * 100.0, 2) if tot_rev_net_costed > 1e-9 else 0.0,
                "coverage_pct": round(tot_ratio * 100.0, 2),
            },
        }

    async def decision_dashboard(self, date_from: date, date_to: date) -> dict:
        """Один FIFO-прогон для управленческого экрана: текущий и прошлый периоды,
        разрезы топлива, АЗС, АЗС × топливо и месячная динамика."""
        queues = await self._build_queues()
        sale_rows = await self._sales_ordered()
        station_names = {
            st.id: st.name for st in (await self.session.execute(
                select(FuelStation).where(FuelStation.company_id == self.company_id))).scalars()
        }
        ctx = await load_mapping_context(self.session, self.company_id)

        days = (date_to - date_from).days + 1
        previous_to = date_from - timedelta(days=1)
        previous_from = previous_to - timedelta(days=days - 1)
        group_names = ("fuel", "station", "station_fuel", "month")
        current = {name: defaultdict(lambda: _Line(label="")) for name in group_names}
        previous = defaultdict(lambda: _Line(label=""))

        def add_line(target, group_by, opened_at, station_id, fuel_code,
                     sale, liters, revenue, costed, cogs):
            key, raw_label = _group(group_by, fuel_code, station_id, station_names, sale, opened_at)
            row = target[key]
            row.label = self._label(group_by, raw_label, ctx)
            row.liters += liters
            row.liters_costed += costed
            row.revenue += revenue
            row.cogs += cogs

        for opened_at, station_id, fuel_code, sales in self._sale_groups(sale_rows):
            q = queues.get((station_id, fuel_code))
            allocations = self._allocate_group(q, opened_at, sales)

            sale_date = opened_at.date() if opened_at else None
            if sale_date is not None and date_from <= sale_date <= date_to:
                for allocation in allocations:
                    costed = allocation.liters if allocation.batch is not None else 0.0
                    for group_by in group_names:
                        add_line(
                            current[group_by], group_by, opened_at, station_id, fuel_code,
                            allocation.sale, allocation.liters, allocation.revenue,
                            costed, allocation.cogs,
                        )
            elif sale_date is not None and previous_from <= sale_date <= previous_to:
                for allocation in allocations:
                    add_line(
                        previous, "fuel", opened_at, station_id, fuel_code,
                        allocation.sale, allocation.liters, allocation.revenue,
                        allocation.liters if allocation.batch is not None else 0.0,
                        allocation.cogs,
                    )

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "previous_period": {"from": previous_from.isoformat(), "to": previous_to.isoformat()},
            "fuel": self._finalize(current["fuel"], date_from, date_to, "fuel"),
            "station": self._finalize(current["station"], date_from, date_to, "station"),
            "station_fuel": self._finalize(current["station_fuel"], date_from, date_to, "station_fuel"),
            "month": self._finalize(current["month"], date_from, date_to, "month"),
            "previous": self._finalize(previous, previous_from, previous_to, "fuel"),
            "readiness": self._costing_readiness,
        }

    async def batch_stats(self, receipt: FuelReceipt) -> dict:
        """Итоги, каналы и микропартии реализации одной ТТН по FIFO."""
        fk = _fkey(receipt.fuel_code)
        station_id = str(receipt.station_id)
        queues = await self._build_queues(station_id, fk)
        sale_rows = await self._sales_ordered(station_id, fk)

        # найти нашу партию в очереди станции+топлива
        q = queues.get((station_id, fk), deque())
        target = next((b for b in q if b.ttn == receipt.ttn), None)
        if target is None:
            return {"has_cost": False}
        total = target.remaining
        consumed = 0.0
        revenue_consumed = 0.0
        micro_lots = []
        channels = defaultdict(lambda: {
            "liters": 0.0, "revenue": 0.0, "revenue_net": 0.0,
            "cogs": 0.0, "margin": 0.0, "allocations_count": 0,
        })
        for opened_at, st_id, fuel_code, sales in self._sale_groups(sale_rows):
            if st_id != station_id or fuel_code != fk:
                continue
            allocations = self._allocate_group(q, opened_at, sales)
            for allocation in allocations:
                if allocation.batch is target:
                    take = allocation.liters
                    revenue = allocation.revenue
                    revenue_net = revenue * 100.0 / (100.0 + _VAT)
                    cogs = allocation.cogs
                    margin = revenue_net - cogs
                    price = revenue / take if take > 1e-9 else 0.0
                    consumed += take
                    revenue_consumed += revenue
                    sale = allocation.sale
                    sh = self._shift_lookup.get(sale.shift_id)
                    micro_lots.append({
                        "id": f"{sale.shift_id}:{sale.payment_channel}:{fk}",
                        "opened_at": opened_at.isoformat() if opened_at != datetime.min else None,
                        "shift_id": str(sale.shift_id),
                        "shift_number": sh.shift_number if sh else None,
                        "channel": sale.payment_channel,
                        "liters": round(take, 3),
                        "avg_sale_price": round(price, 4),
                        "revenue": round(revenue, 2),
                        "revenue_net": round(revenue_net, 2),
                        "cogs": round(cogs, 2),
                        "margin": round(margin, 2),
                        "margin_pct": round(margin / revenue_net * 100.0, 2) if revenue_net > 1e-9 else 0.0,
                    })
                    ch = channels[sale.payment_channel]
                    ch["liters"] += take
                    ch["revenue"] += revenue
                    ch["revenue_net"] += revenue_net
                    ch["cogs"] += cogs
                    ch["margin"] += margin
                    ch["allocations_count"] += 1
            if target.remaining <= 1e-9 and target not in q:
                # партия исчерпана — дальнейшие продажи её не касаются
                if all(b is not target for b in q):
                    break
        remaining = max(0.0, total - consumed)
        cost = target.cost_per_liter
        revenue_net_consumed = revenue_consumed * 100.0 / (100.0 + _VAT)
        margin_consumed = revenue_net_consumed - consumed * cost
        channel_rows = []
        for channel, values in channels.items():
            channel_rows.append({
                "channel": channel,
                "liters": round(values["liters"], 3),
                "share_pct": round(values["liters"] / consumed * 100.0, 2) if consumed > 1e-9 else 0.0,
                "allocations_count": values["allocations_count"],
                "avg_sale_price": round(values["revenue"] / values["liters"], 4) if values["liters"] > 1e-9 else 0.0,
                "revenue": round(values["revenue"], 2),
                "revenue_net": round(values["revenue_net"], 2),
                "cogs": round(values["cogs"], 2),
                "margin": round(values["margin"], 2),
                "margin_pct": round(values["margin"] / values["revenue_net"] * 100.0, 2) if values["revenue_net"] > 1e-9 else 0.0,
            })
        channel_rows.sort(key=lambda row: -row["revenue"])
        return {
            "has_cost": True,
            "allocation_method": "shift_channel_pro_rata",
            "allocation_method_label": "FIFO по времени смен; граница ТТН распределяется пропорционально каналам оплаты смены",
            "cost_per_liter": round(cost, 4),
            "total_liters": round(total, 2),
            "consumed_liters": round(consumed, 2),
            "remaining_liters": round(remaining, 2),
            "avg_sale_price": round(revenue_consumed / consumed, 4) if consumed > 1e-9 else 0.0,
            "cogs_consumed": round(consumed * cost, 2),
            "revenue_consumed": round(revenue_consumed, 2),
            "revenue_net_consumed": round(revenue_net_consumed, 2),
            "margin_consumed": round(margin_consumed, 2),
            "margin_pct": round(margin_consumed / revenue_net_consumed * 100.0, 2) if revenue_net_consumed > 1e-9 else 0.0,
            "channels": channel_rows,
            "micro_lots": micro_lots,
        }
