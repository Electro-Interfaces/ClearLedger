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

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FuelShift, FuelShiftSale, FuelReceipt, FuelCashMovement, FuelStation, FuelTransaction,
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
        by_station = await self._by_station(shifts, sales)
        onboarding = await self._onboarding()
        # Разрез оплат/топлива со счётчиком НАЛИВОВ — из пооперационных транзакций
        # (fuel_transactions, грейн=налив). Фолбэк на сырые отчёты смен (без count),
        # если транзакции за период ещё не загружены.
        payment_methods, fuel_types_raw = await self._tx_breakdowns(date_from, date_to, station_ids)
        if not payment_methods:
            payment_methods, fuel_types_raw = await self._raw_breakdowns(date_from, date_to, station_ids)
        activity = await self._activity(date_from, date_to, station_ids)
        top_cards = await self._top_cards(date_from, date_to, station_ids)
        # Средние показатели АЗС (по наливам): средний чек, средний объём заправки,
        # операций/день — как OverviewKPICards в TradeFrame. Из транзакций (count).
        _txc = sum(int(p.get("count") or 0) for p in payment_methods)
        _txa = sum(float(p.get("revenue") or 0) for p in payment_methods)
        _txl = sum(float(p.get("volume") or 0) for p in payment_methods)
        _days = (date_to - date_from).days + 1
        averages = {
            "tx_count": _txc,
            "avg_check": round(_txa / _txc, 2) if _txc else 0.0,
            "avg_fill_liters": round(_txl / _txc, 2) if _txc else 0.0,
            "ops_per_day": round(_txc / _days, 1) if _days else 0.0,
        }

        result = {
            "period": {
                "from": date_from.isoformat(), "to": date_to.isoformat(),
                "days": (date_to - date_from).days + 1,
            },
            **kpis,
            "charts": charts,
            "by_station": by_station,
            "onboarding": onboarding,
            "payment_methods": payment_methods,
            "fuel_types_raw": fuel_types_raw,
            "activity": activity,
            "top_cards": top_cards,
            "averages": averages,
        }
        # Средняя цена ₽/л + счётчики размерностей (для executive-«Обзора»).
        tv = result["volume"]["total"]
        tr = result["financial"]["total_revenue"]
        result["financial"]["avg_price"] = round(tr / tv, 2) if tv else 0.0
        result["operational"]["stations_count"] = len({s.station_id for s in shifts})
        result["operational"]["fuel_types_count"] = len(result["volume"]["by_fuel"])
        if compare:
            days = (date_to - date_from).days + 1
            cmp_to = date_from - timedelta(days=1)
            cmp_from = cmp_to - timedelta(days=days - 1)
            c_shifts, c_sales, c_cash, c_receipts = await self._load(cmp_from, cmp_to, station_ids)
            c_kpis = self._kpis(c_shifts, c_sales, c_cash, c_receipts, fuel_name)
            result["trends"] = self._trends(kpis, c_kpis)
        return result

    async def sales_channels(self, date_from: date, date_to: date,
                             station_codes: list[int] | None = None,
                             fuel_codes: list[int] | None = None,
                             pay_types: list[str] | None = None) -> dict:
        """Связанные разрезы продаж по операциям STS для менеджерской аналитики."""
        T = FuelTransaction
        conds = [
            T.company_id == self.company_id,
            T.dt >= datetime(date_from.year, date_from.month, date_from.day),
            T.dt <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59),
        ]
        if station_codes:
            conds.append(T.station_code.in_(station_codes))
        if fuel_codes:
            conds.append(T.fuel_code.in_(fuel_codes))
        if pay_types:
            conds.append(T.pay_type_name.in_(pay_types))

        totals = (await self.session.execute(select(
            func.count().label("n"),
            func.coalesce(func.sum(T.liters), 0).label("liters"),
            func.coalesce(func.sum(T.amount), 0).label("amount"),
            func.count(func.distinct(T.station_code)).label("stations"),
        ).where(*conds))).one()
        total_count = int(totals.n)
        total_liters = float(totals.liters)
        total_amount = float(totals.amount)

        station_names = {
            int(row.code): row.name or f"АЗС {row.code}"
            for row in (await self.session.execute(select(FuelStation).where(
                FuelStation.company_id == self.company_id
            ))).scalars().all()
        }

        def metrics(count: int, liters: float, amount: float, share_base: float) -> dict:
            return {
                "count": count,
                "liters": round(liters, 2),
                "amount": round(amount, 2),
                "share": round(100 * amount / share_base, 2) if share_base else 0.0,
                "avg_check": round(amount / count, 2) if count else 0.0,
                "avg_fill": round(liters / count, 2) if count else 0.0,
                "avg_price": round(amount / liters, 2) if liters else 0.0,
            }

        station_rows = (await self.session.execute(select(
            T.station_code.label("key"), func.count().label("n"),
            func.coalesce(func.sum(T.liters), 0).label("liters"),
            func.coalesce(func.sum(T.amount), 0).label("amount"),
        ).where(*conds).group_by(T.station_code)
            .order_by(func.coalesce(func.sum(T.amount), 0).desc()))).all()
        by_station = [{
            "code": int(row.key),
            "name": station_names.get(int(row.key), f"АЗС {row.key}"),
            **metrics(int(row.n), float(row.liters), float(row.amount), total_amount),
        } for row in station_rows]

        payment_rows = (await self.session.execute(select(
            T.pay_type_name.label("key"), func.count().label("n"),
            func.coalesce(func.sum(T.liters), 0).label("liters"),
            func.coalesce(func.sum(T.amount), 0).label("amount"),
        ).where(*conds).group_by(T.pay_type_name)
            .order_by(func.coalesce(func.sum(T.amount), 0).desc()))).all()
        by_payment = [{
            "name": row.key or "—",
            **metrics(int(row.n), float(row.liters), float(row.amount), total_amount),
        } for row in payment_rows]

        fuel_rows = (await self.session.execute(select(
            T.fuel_code.label("code"), T.fuel_name.label("name"), func.count().label("n"),
            func.coalesce(func.sum(T.liters), 0).label("liters"),
            func.coalesce(func.sum(T.amount), 0).label("amount"),
        ).where(*conds).group_by(T.fuel_code, T.fuel_name)
            .order_by(func.coalesce(func.sum(T.amount), 0).desc()))).all()
        by_fuel = [{
            "code": int(row.code) if row.code is not None else None,
            "name": row.name or "—",
            **metrics(int(row.n), float(row.liters), float(row.amount), total_amount),
        } for row in fuel_rows]

        day_expr = func.date(func.timezone("Europe/Moscow", T.dt))
        daily_rows = (await self.session.execute(select(
            day_expr.label("day"), func.count().label("n"),
            func.coalesce(func.sum(T.liters), 0).label("liters"),
            func.coalesce(func.sum(T.amount), 0).label("amount"),
        ).where(*conds).group_by(day_expr).order_by(day_expr))).all()
        daily = [{
            "date": row.day.isoformat(),
            "count": int(row.n),
            "liters": round(float(row.liters), 2),
            "amount": round(float(row.amount), 2),
        } for row in daily_rows]

        matrix_rows = (await self.session.execute(select(
            T.station_code.label("station_code"), T.pay_type_name.label("payment"),
            func.count().label("n"),
            func.coalesce(func.sum(T.liters), 0).label("liters"),
            func.coalesce(func.sum(T.amount), 0).label("amount"),
        ).where(*conds).group_by(T.station_code, T.pay_type_name)
            .order_by(T.station_code, func.coalesce(func.sum(T.amount), 0).desc()))).all()
        station_amounts = {row["code"]: row["amount"] for row in by_station}
        station_payment = [{
            "station_code": int(row.station_code),
            "station_name": station_names.get(int(row.station_code), f"АЗС {row.station_code}"),
            "payment": row.payment or "—",
            **metrics(
                int(row.n), float(row.liters), float(row.amount),
                station_amounts.get(int(row.station_code), 0.0),
            ),
        } for row in matrix_rows]

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "totals": {
                **metrics(total_count, total_liters, total_amount, total_amount),
                "stations": int(totals.stations),
            },
            "by_station": by_station,
            "by_payment": by_payment,
            "by_fuel": by_fuel,
            "daily": daily,
            "station_payment": station_payment,
        }

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

    async def _by_station(self, shifts, sales) -> list[dict]:
        """Продажи по АЗС (revenue/volume/смены/ср.цена) — для «Станции: лидеры/аутсайдеры»
        и разреза Обзора. Имена станций резолвятся из FuelStation по station_id."""
        if not shifts:
            return []
        shift_station = {s.id: s.station_id for s in shifts}
        st_ids = {s.station_id for s in shifts}
        rows = (await self.session.execute(select(
            FuelStation.id, FuelStation.code, FuelStation.name,
        ).where(FuelStation.id.in_(st_ids)))).all()
        names = {r.id: (r.name or f"АЗС {r.code}") for r in rows}

        agg: dict = defaultdict(lambda: {"volume": 0.0, "revenue": 0.0})
        for s in sales:
            st = shift_station.get(s.shift_id)
            if st is None:
                continue
            agg[st]["volume"] += float(s.liters or 0)
            agg[st]["revenue"] += float(s.amount or 0)
        shift_cnt: dict = defaultdict(int)
        for s in shifts:
            shift_cnt[s.station_id] += 1

        out = [{
            "station_id": str(st),
            "station_name": names.get(st, "—"),
            "revenue": round(d["revenue"], 2),
            "volume": round(d["volume"], 2),
            "shifts": shift_cnt.get(st, 0),
            "avg_price": round(d["revenue"] / d["volume"], 2) if d["volume"] else 0.0,
        } for st, d in agg.items()]
        out.sort(key=lambda x: -x["revenue"])
        return out

    def _tx_conds(self, date_from: date, date_to: date, station_ids: list | None):
        T = FuelTransaction
        conds = [T.company_id == self.company_id,
                 T.dt >= datetime(date_from.year, date_from.month, date_from.day),
                 T.dt <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)]
        if station_ids:
            conds.append(T.station_id.in_(station_ids))
        return conds

    async def _activity(self, date_from: date, date_to: date, station_ids: list | None) -> dict:
        """Профиль активности из транзакций: по часам суток (0-23) и дням недели (Пн-Вс),
        число наливов + выручка. Час/день — в МСК (AT TIME ZONE), независимо от TZ сессии."""
        T = FuelTransaction
        conds = self._tx_conds(date_from, date_to, station_ids) + [T.dt.is_not(None)]
        msk = func.timezone("Europe/Moscow", T.dt)
        hh = (await self.session.execute(select(
            func.extract("hour", msk).label("k"), func.count().label("n"),
            func.coalesce(func.sum(T.amount), 0).label("a")).where(*conds).group_by("k"))).all()
        hmap = {int(r.k): r for r in hh}
        hourly = [{"hour": h, "label": f"{h:02d}", "count": int(hmap[h].n) if h in hmap else 0,
                   "amount": round(float(hmap[h].a), 2) if h in hmap else 0.0} for h in range(24)]
        wd = (await self.session.execute(select(
            func.extract("isodow", msk).label("k"), func.count().label("n"),
            func.coalesce(func.sum(T.amount), 0).label("a")).where(*conds).group_by("k"))).all()
        wmap = {int(r.k): r for r in wd}
        _WD = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}
        weekday = [{"weekday": w, "label": _WD[w], "count": int(wmap[w].n) if w in wmap else 0,
                    "amount": round(float(wmap[w].a), 2) if w in wmap else 0.0} for w in range(1, 8)]
        _nz = [x for x in weekday if x["amount"] > 0]
        return {
            "hourly": hourly, "weekday": weekday,
            "peak_hour": max(hourly, key=lambda x: x["count"])["hour"] if any(x["count"] for x in hourly) else None,
            "best_weekday": max(_nz, key=lambda x: x["amount"])["weekday"] if _nz else None,
        }

    async def _top_cards(self, date_from: date, date_to: date, station_ids: list | None,
                         top: int = 12) -> list[dict]:
        """Топ карт по обороту (корпоратив/лояльность) — из транзакций. Технические
        «нулевые» карты (наличные без карты) исключаются."""
        T = FuelTransaction
        conds = self._tx_conds(date_from, date_to, station_ids) + [
            T.card.is_not(None), T.card != "", T.card.op("!~")("^0+$")]
        rows = (await self.session.execute(select(
            T.card, func.count().label("n"),
            func.coalesce(func.sum(T.liters), 0).label("l"),
            func.coalesce(func.sum(T.amount), 0).label("a"))
            .where(*conds).group_by(T.card)
            .order_by(func.coalesce(func.sum(T.amount), 0).desc()).limit(top))).all()
        return [{
            "card": (r.card or "").lstrip("0") or r.card,
            "count": int(r.n), "liters": round(float(r.l), 2), "amount": round(float(r.a), 2),
        } for r in rows]

    async def _tx_breakdowns(self, date_from: date, date_to: date,
                             station_ids: list | None) -> tuple[list[dict], list[dict]]:
        """Разрез по видам оплаты и топлива из пооперационных транзакций (наливов).
        Даёт три колонки как в эталоне: наливы(count) · выручка · объём."""
        dt_from = datetime(date_from.year, date_from.month, date_from.day)
        dt_to = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)
        T = FuelTransaction
        conds = [T.company_id == self.company_id, T.dt >= dt_from, T.dt <= dt_to]
        if station_ids:
            conds.append(T.station_id.in_(station_ids))
        pay = (await self.session.execute(
            select(T.pay_type_name, func.count().label("n"),
                   func.coalesce(func.sum(T.liters), 0).label("vol"),
                   func.coalesce(func.sum(T.amount), 0).label("rev"))
            .where(*conds).group_by(T.pay_type_name)
            .order_by(func.coalesce(func.sum(T.amount), 0).desc()))).all()
        fuel = (await self.session.execute(
            select(T.fuel_name, T.fuel_code, func.count().label("n"),
                   func.coalesce(func.sum(T.liters), 0).label("vol"),
                   func.coalesce(func.sum(T.amount), 0).label("rev"))
            .where(*conds).group_by(T.fuel_name, T.fuel_code)
            .order_by(func.coalesce(func.sum(T.amount), 0).desc()))).all()
        payments = [{
            "name": r.pay_type_name or "—", "count": int(r.n),
            "revenue": round(float(r.rev), 2), "volume": round(float(r.vol), 2),
        } for r in pay]
        fuel_agg: dict = defaultdict(lambda: {"code": None, "count": 0, "revenue": 0.0, "volume": 0.0})
        for r in fuel:
            nm = r.fuel_name or "—"
            fuel_agg[nm]["count"] += int(r.n)
            fuel_agg[nm]["revenue"] += float(r.rev)
            fuel_agg[nm]["volume"] += float(r.vol)
            if fuel_agg[nm]["code"] is None and r.fuel_code is not None:
                fuel_agg[nm]["code"] = r.fuel_code
        fuels = [{
            "name": nm, "code": d["code"], "count": d["count"],
            "revenue": round(d["revenue"], 2), "volume": round(d["volume"], 2),
        } for nm, d in sorted(fuel_agg.items(), key=lambda x: -x[1]["revenue"])]
        return payments, fuels

    async def _raw_breakdowns(self, date_from: date, date_to: date,
                              station_ids: list | None) -> tuple[list[dict], list[dict]]:
        """Полный разрез продаж из СЫРЫХ отчётов STS (raw_report.sales) — по КАЖДОМУ
        виду оплаты (pay_type.name) и по видам топлива, БЕЗ маппинга/отбрасывания.
        Именно так «Способы оплаты» показывает эталонная система (все методы, вкл.
        Купон/Прокачку/Тех.отпуск). FuelShiftSale для этого не годится — он свёрнут в
        каналы 1С и роняет неучётные типы."""
        dt_from = datetime(date_from.year, date_from.month, date_from.day)
        dt_to = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)
        params: dict = {"cid": self.company_id, "df": dt_from, "dt": dt_to}
        st_clause = ""
        if station_ids:
            st_clause = " AND fs.station_id = ANY(:sids)"
            params["sids"] = list(station_ids)
        base_from = (
            "FROM fuel_shifts fs, "
            "jsonb_array_elements(fs.raw_report->'sales') s, "
            "jsonb_array_elements(s->'fuel') f "
            "WHERE fs.company_id = :cid AND fs.raw_report IS NOT NULL "
            "AND fs.opened_at >= :df AND fs.opened_at <= :dt" + st_clause
        )
        pay_sql = text(
            "SELECT s->'pay_type'->>'name' AS name, "
            "COALESCE(sum((f->'release'->>'cost')::numeric), 0) AS revenue, "
            "COALESCE(sum((f->'release'->>'volume')::numeric), 0) AS volume "
            + base_from + " GROUP BY 1 ORDER BY 2 DESC")
        fuel_sql = text(
            "SELECT f->'service'->>'service_name' AS name, "
            "(f->'service'->>'service_code') AS code, "
            "COALESCE(sum((f->'release'->>'cost')::numeric), 0) AS revenue, "
            "COALESCE(sum((f->'release'->>'volume')::numeric), 0) AS volume "
            + base_from + " GROUP BY 1, 2 ORDER BY 3 DESC")
        pm_rows = (await self.session.execute(pay_sql, params)).all()
        ft_rows = (await self.session.execute(fuel_sql, params)).all()
        payments = [{
            "name": r.name or "—",
            "revenue": round(float(r.revenue), 2), "volume": round(float(r.volume), 2),
        } for r in pm_rows]
        # схлопнуть дубли имён видов топлива (разные service_code с одним именем)
        fuel_agg: dict = defaultdict(lambda: {"code": None, "revenue": 0.0, "volume": 0.0})
        for r in ft_rows:
            nm = r.name or "—"
            fuel_agg[nm]["revenue"] += float(r.revenue)
            fuel_agg[nm]["volume"] += float(r.volume)
            if fuel_agg[nm]["code"] is None and r.code:
                try:
                    fuel_agg[nm]["code"] = int(r.code)
                except (TypeError, ValueError):
                    pass
        fuels = [{
            "name": nm, "code": d["code"],
            "revenue": round(d["revenue"], 2), "volume": round(d["volume"], 2),
        } for nm, d in sorted(fuel_agg.items(), key=lambda x: -x[1]["revenue"])]
        return payments, fuels

    async def _onboarding(self) -> list[dict]:
        """Даты подключения станций = первая смена за ВСЮ историю (не за период) —
        маркеры на графике «Реализация по дням»; фронт рисует их, если дата попадает
        в видимый диапазон. Абсолютная дата, чтобы маркер был стабилен при смене периода."""
        rows = (await self.session.execute(
            select(FuelShift.station_id, func.min(FuelShift.opened_at).label("fst"))
            .where(FuelShift.company_id == self.company_id, FuelShift.opened_at.is_not(None))
            .group_by(FuelShift.station_id))).all()
        if not rows:
            return []
        ids = [r.station_id for r in rows]
        srows = (await self.session.execute(select(
            FuelStation.id, FuelStation.code, FuelStation.name).where(FuelStation.id.in_(ids)))).all()
        nm = {r.id: (r.code, r.name) for r in srows}
        out = []
        for r in rows:
            code, name = nm.get(r.station_id, (None, None))
            out.append({
                "station_id": str(r.station_id), "code": code,
                "name": name or (f"АЗС {code}" if code is not None else "—"),
                "date": r.fst.date().isoformat(),
            })
        out.sort(key=lambda x: x["date"])
        return out

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
            # Снимки, НЕ потоки: накопительные счётчики ККТ (сотни млрд) и остатки
            # касс — не приход/расход; без этого income раздувался на порядки.
            if "показания" in name and ("счётчик" in name or "счетчик" in name):
                cf_details.append({
                    "operation": m.operation_name, "type": "meter", "amount": round(amt, 2),
                    "pos": m.pos_number, "shift": shift_num.get(m.shift_id),
                })
                continue
            if "остаток на нач" in name or "остаток на начало" in name:
                cf_details.append({
                    "operation": m.operation_name, "type": "opening", "amount": round(amt, 2),
                    "pos": m.pos_number, "shift": shift_num.get(m.shift_id),
                })
                continue
            if "остаток на кон" in name or "остаток на конец" in name:
                cf_details.append({
                    "operation": m.operation_name, "type": "closing", "amount": round(amt, 2),
                    "pos": m.pos_number, "shift": shift_num.get(m.shift_id),
                })
                continue
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


# ────────────────────────────────────────────────────────────────────────────
# Касса и инкассация (бухгалтерский контур): журнал инкассаций из money-секции
# смен + остатки касс по АЗС. Данные — FuelCashMovement (money-секция STS):
# «Выручка» = ВСЯ наличка ККТ (топливо + сопутка), «Инкассация»/«Сдано»,
# «Выдано наличными», «Остаток на конец смены по всей АЗС» (снимок кассы).
# «Накоплено с прошлой инкассации» = Σ выручки между инкассациями станции —
# основание для РКО в 1С (в пакеты БП инкассация не выгружается: приёмник
# TradeLedger.cfe её не принимает).
# ────────────────────────────────────────────────────────────────────────────
class CashCollectionsService:
    def __init__(self, session: AsyncSession, company_id):
        self.session = session
        self.company_id = company_id

    @staticmethod
    def _kind(name: str) -> str:
        n = (name or "").lower()
        if "инкасс" in n or "сдан" in n or "изъят" in n:
            return "collection"
        if "выручк" in n or "внесен" in n:
            return "revenue"
        if "выдан" in n:
            return "payout"
        if ("остаток на кон" in n or "остаток на конец" in n) and "азс" in n:
            return "closing_azs"
        return "other"

    async def compute(self, date_from: date, date_to: date) -> dict:
        rows = (await self.session.execute(
            select(
                FuelCashMovement.operation_name, FuelCashMovement.amount,
                FuelCashMovement.pos_number,
                FuelShift.opened_at, FuelShift.shift_number,
                FuelStation.id.label("station_id"), FuelStation.code, FuelStation.name,
            )
            .join(FuelShift, FuelShift.id == FuelCashMovement.shift_id)
            .join(FuelStation, FuelStation.id == FuelShift.station_id)
            .where(FuelShift.company_id == self.company_id,
                   FuelShift.opened_at.is_not(None))
            .order_by(FuelStation.code, FuelShift.opened_at, FuelShift.shift_number)
        )).all()

        lo = datetime.combine(date_from, datetime.min.time())
        hi = datetime.combine(date_to, datetime.max.time())

        def naive(dt):
            return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo else dt

        journal: list[dict] = []
        payouts: list[dict] = []
        st: dict = {}   # station_id → состояние накопления/остатка
        for r in rows:
            kind = self._kind(r.operation_name)
            if kind == "other":
                continue
            amt = float(r.amount or 0)
            opened = naive(r.opened_at)
            s = st.setdefault(r.station_id, {
                "code": r.code, "name": r.name,
                "accrued": 0.0, "last_coll_at": None, "last_coll_amount": None,
                "balance": None, "balance_at": None, "collected_total": 0.0,
            })
            if kind == "revenue":
                s["accrued"] += amt
            elif kind == "collection":
                row = {
                    "date": opened.isoformat(),
                    "station_code": r.code, "station_name": r.name,
                    "shift_number": r.shift_number, "pos": r.pos_number,
                    "amount": round(amt, 2),
                    "accrued_since_last": round(s["accrued"], 2),
                    "diff": round(amt - s["accrued"], 2),
                }
                if lo <= opened <= hi:
                    journal.append(row)
                    s["collected_total"] += amt
                s["accrued"] = 0.0
                s["last_coll_at"] = opened
                s["last_coll_amount"] = amt
            elif kind == "payout":
                if lo <= opened <= hi:
                    payouts.append({
                        "date": opened.isoformat(),
                        "station_code": r.code, "station_name": r.name,
                        "shift_number": r.shift_number, "amount": round(amt, 2),
                    })
            elif kind == "closing_azs":
                s["balance"] = amt
                s["balance_at"] = opened

        ref = hi if hi < datetime.now() else datetime.now()
        stations = []
        for s in st.values():
            days = (ref - s["last_coll_at"]).days if s["last_coll_at"] else None
            stations.append({
                "station_code": s["code"], "station_name": s["name"],
                "balance": round(s["balance"], 2) if s["balance"] is not None else None,
                "balance_at": s["balance_at"].isoformat() if s["balance_at"] else None,
                "accrued_since_last": round(s["accrued"], 2),
                "last_collection_at": s["last_coll_at"].isoformat() if s["last_coll_at"] else None,
                "last_collection_amount": round(s["last_coll_amount"], 2) if s["last_coll_amount"] is not None else None,
                "days_since_collection": days,
            })
        stations.sort(key=lambda x: -(x["days_since_collection"] if x["days_since_collection"] is not None else 10_000))

        journal.sort(key=lambda x: x["date"], reverse=True)
        revenue_period = 0.0
        for r in rows:
            if self._kind(r.operation_name) == "revenue" and lo <= naive(r.opened_at) <= hi:
                revenue_period += float(r.amount or 0)
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "kpis": {
                "collected": round(sum(j["amount"] for j in journal), 2),
                "collections": len(journal),
                "cashRevenue": round(revenue_period, 2),
                "payouts": round(sum(p["amount"] for p in payouts), 2),
                "networkBalance": round(sum(s["balance"] or 0 for s in stations), 2),
                "stale7": sum(1 for s in stations
                              if (s["days_since_collection"] or 0) >= 7 and (s["accrued_since_last"] or 0) > 0),
            },
            "journal": journal[:500],
            "payouts": payouts[:100],
            "stations": stations,
        }
