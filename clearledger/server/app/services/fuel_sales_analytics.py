"""
Аналитика продаж топлива по наливам (fuel_transactions) — раздел «Продажи» ГИГ,
группы «Аналитика» (Наливы) и «Коммерция» (Тарифы / Корпоратив / Частные лица).

Зеркало ЭЗС-контура (_cs_* в analytics_service + charge_clients), но на грейне
«один налив»: литры, цена ₽/л, виды оплаты STS. Классификация вида оплаты в
канал — через MappingContext (единственный источник истины, подстрочный матч
по sort_order): раз в запрос берём DISTINCT pay_type_name компании, резолвим
каждое имя в Python и строим SQL CASE по ТОЧНЫМ именам (без LIKE в SQL).

Семантика цен (разведка dev-БД 14.07.2026, 338 412 наливов ГИГ):
  price  — номинал стеллы/ТРК на момент налива (₽/л);
  amount — фактически уплачено; скидки на грейне налива ≈ 0 (живут в сменном
           sales-блоке fuel_shift_sales.discount);
  факт-цена ВЕЗДЕ = Σamount/Σliters — у «Наличных» встречается amount≠liters·price
  (смена цены внутри смены/округления), avg(price) не использовать.
Дубли-аналитика («Дисконт»/«Кред.рубл») исключаются из всех сумм — на грейне
наливов их нет (проверено), но защита обязательна. STS cost cap (1 млн) —
артефакт сменного блока, на наливах недостижим.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FuelShift, FuelShiftSale, FuelStation, FuelTransaction, PaymentChannel,
)
from app.services.analytics_cache import cached_report
from app.services.analytics_service import AnalyticsService
from app.services.fuel_mappings import _DUP_ANALYTIC_PAY, load_mapping_context

T = FuelTransaction

# Ключ карты: трим (в STS хвостовые пробелы), пустые → NULL.
CARD = func.nullif(func.trim(T.card), "")

# Сегменты бизнеса из каналов оплаты. ignored = явный игнор маппинга
# (купоны/прокачка), unmapped = вид оплаты без правила — показываем, не теряем.
SEGMENT_OF_CHANNEL: dict[str, str] = {
    "cards": "corp", "ledger": "corp",
    "retail_cash": "retail", "retail_card": "retail", "retail": "retail",
    "online": "online",
    "voucher": "other", "writeoff_fuel": "other", "ignored": "other",
}
SEGMENT_LABELS = {
    "corp": "Корпоратив", "retail": "Частные лица", "online": "Онлайн",
    "other": "Прочее", "unmapped": "Не размечено",
}
FALLBACK_CHANNEL_LABELS = {
    "ignored": "Игнорируемые (купоны)", "unmapped": "Не размечено",
}
WEEKDAY_LABELS = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}

_METRICS = ("amount", "liters", "fills", "avg_check", "avg_fill", "avg_price")


class _Classification:
    """Разметка видов оплаты компании: имя → канал/сегмент + списки имён."""

    def __init__(self, channel_by_name: dict[str, str], channel_labels: dict[str, str]):
        self.channel_by_name = channel_by_name          # pay_type_name → channel_code
        self.channel_labels = channel_labels            # channel_code → русское имя
        self.names_by_channel: dict[str, list[str]] = defaultdict(list)
        for name, ch in channel_by_name.items():
            self.names_by_channel[ch].append(name)
        self.names_by_segment: dict[str, list[str]] = defaultdict(list)
        for name, ch in channel_by_name.items():
            seg = "unmapped" if ch == "unmapped" else SEGMENT_OF_CHANNEL.get(ch, "other")
            self.names_by_segment[seg].append(name)

    def channel_case(self):
        whens = [(T.pay_type_name.in_(names), ch)
                 for ch, names in self.names_by_channel.items() if ch != "unmapped" and names]
        return case(*whens, else_="unmapped") if whens else func.coalesce(T.pay_type_name, "unmapped")

    def segment_case(self):
        whens = [(T.pay_type_name.in_(names), seg)
                 for seg, names in self.names_by_segment.items() if seg != "unmapped" and names]
        return case(*whens, else_="unmapped") if whens else func.coalesce(T.pay_type_name, "unmapped")

    def channel_label(self, code: str) -> str:
        return self.channel_labels.get(code) or FALLBACK_CHANNEL_LABELS.get(code) or code

    def segment_names(self, segment: str) -> list[str]:
        return self.names_by_segment.get(segment, [])

    def channel_names(self, channel: str) -> list[str]:
        return self.names_by_channel.get(channel, [])


class FuelSalesAnalytics:
    """Агрегаты продаж по наливам. Методы кешируются версионным кешем компании."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─── классификация и общие условия ─────────────────────────────────

    async def _classification(self, company_id) -> tuple[_Classification, list[str]]:
        """(разметка видов оплаты, имена дублей-аналитики). Один DISTINCT-скан."""
        names = [n for n in (await self.db.execute(
            select(T.pay_type_name).where(T.company_id == company_id).distinct()
        )).scalars().all() if n]
        ctx = await load_mapping_context(self.db, company_id)
        channel_by_name: dict[str, str] = {}
        dup_names: list[str] = []
        for n in names:
            low = n.lower()
            if any(p in low for p in _DUP_ANALYTIC_PAY):
                dup_names.append(n)
                continue
            code, _wh = ctx.resolve_channel(n)
            channel_by_name[n] = "ignored" if code == "" else (code or "unmapped")
        labels = {c.code: c.name for c in (await self.db.execute(
            select(PaymentChannel).where(PaymentChannel.company_id == company_id)
        )).scalars().all()}
        return _Classification(channel_by_name, labels), dup_names

    @staticmethod
    def _conds(company_id, date_from: date, date_to: date, dup_names: list[str],
               station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
               pay_names: list[str] | None = None, card: str | None = None) -> list:
        """Базовый WHERE. pay_names — уже развёрнутый фильтр канала/сегмента."""
        conds = [
            T.company_id == company_id,
            T.dt >= datetime(date_from.year, date_from.month, date_from.day),
            T.dt <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59),
        ]
        if dup_names:
            conds.append(T.pay_type_name.notin_(dup_names))
        if station_codes:
            conds.append(T.station_code.in_(station_codes))
        if fuel_codes:
            conds.append(T.fuel_code.in_(fuel_codes))
        if pay_names is not None:
            conds.append(T.pay_type_name.in_(pay_names))
        if card:
            conds.append(func.trim(T.card) == card.strip())
        return conds

    @staticmethod
    def _pay_filter(cls: _Classification, segment: str | None, channel: str | None) -> list[str] | None:
        """segment/channel → список точных имён видов оплаты (None = без фильтра)."""
        if channel:
            return cls.channel_names(channel)
        if segment:
            return cls.segment_names(segment)
        return None

    @staticmethod
    def _msk():
        return func.timezone("Europe/Moscow", T.dt)

    def _group_col(self, group_by: str, cls: _Classification):
        msk = self._msk()
        if group_by == "fuel":
            return func.coalesce(T.fuel_name, "—")
        if group_by == "pay_type":
            return func.coalesce(T.pay_type_name, "—")
        if group_by == "channel":
            return cls.channel_case()
        if group_by == "segment":
            return cls.segment_case()
        if group_by == "hour":
            return func.extract("hour", msk)
        if group_by == "weekday":
            return func.extract("isodow", msk)  # 1=Пн .. 7=Вс
        if group_by == "shift":
            return T.shift_number
        if group_by == "card":
            return CARD
        if group_by == "day":
            return func.to_char(msk, "YYYY-MM-DD")
        if group_by == "week":
            return func.to_char(func.date_trunc("week", msk), "YYYY-MM-DD")
        if group_by == "decade":
            day = func.extract("day", msk)
            dec = case((day <= 10, 1), (day <= 20, 2), else_=3)
            return func.concat(func.to_char(msk, "YYYY-MM"), "-Д", dec)
        if group_by == "month":
            return func.to_char(msk, "YYYY-MM")
        if group_by == "quarter":
            return func.concat(func.to_char(msk, "YYYY"), "-Q", func.to_char(msk, "Q"))
        return T.station_code  # station: лейбл собирается по справочнику имён

    async def _station_names(self, company_id) -> dict[int, str]:
        return {int(s.code): s.name for s in (await self.db.execute(
            select(FuelStation).where(FuelStation.company_id == company_id)
        )).scalars().all()}

    def _label(self, group_by: str, g, cls: _Classification, names: dict[int, str]) -> str:
        if g is None:
            return "—"
        if group_by == "station":
            code = int(g)
            return f"{names.get(code) or 'АЗС'} ({code})"
        if group_by == "channel":
            return cls.channel_label(str(g))
        if group_by == "segment":
            return SEGMENT_LABELS.get(str(g), str(g))
        if group_by == "weekday":
            try:
                return WEEKDAY_LABELS.get(int(float(g)), str(g))
            except (ValueError, TypeError):
                return str(g)
        if group_by == "shift":
            return f"Смена №{g}"
        # hour/decade/month/quarter/day/week — форматы совпадают с ЭЗС
        return AnalyticsService._cs_label(group_by, g)

    # ─── метрики ────────────────────────────────────────────────────────

    @staticmethod
    def _metric_from_sums(metric: str, cnt, liters, amount) -> float:
        cnt = int(cnt or 0)
        liters = float(liters or 0)
        amount = float(amount or 0)
        m = {
            "fills": cnt,
            "liters": round(liters, 1),
            "amount": round(amount, 2),
            "avg_check": amount / cnt if cnt else 0.0,
            "avg_fill": liters / cnt if cnt else 0.0,
            "avg_price": amount / liters if liters else 0.0,
        }
        return round(float(m.get(metric, 0.0)), 2)

    @staticmethod
    def _is_ratio(metric: str) -> bool:
        """Ratio-метрики: пустой бакет → null (не 0), чтобы линия не проваливалась."""
        return metric in ("avg_check", "avg_fill", "avg_price")

    # ─── Наливы: разрезы ────────────────────────────────────────────────

    @cached_report("fuel:fills")
    async def fills(self, company_id, date_from: date, date_to: date,
                    group_by: str = "station",
                    station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                    segment: str | None = None, channel: str | None = None,
                    card: str | None = None, top: int = 500) -> dict[str, Any]:
        """Разрез наливов: выручка/литры/наливы/ср.чек/ср.налив/ср.цена по группе."""
        cls, dups = await self._classification(company_id)
        pay_names = self._pay_filter(cls, segment, channel)
        conds = self._conds(company_id, date_from, date_to, dups,
                            station_codes, fuel_codes, pay_names, card)
        gcol = self._group_col(group_by, cls)
        valid_card = CARD.is_not(None) & func.trim(T.card).op("!~")("^0+$")
        if group_by == "card":
            conds.append(valid_card)
        rows = (await self.db.execute(
            select(
                gcol.label("g"),
                func.count().label("cnt"),
                func.coalesce(func.sum(T.liters), 0).label("liters"),
                func.coalesce(func.sum(T.amount), 0).label("amount"),
                func.count(distinct(T.station_code)).label("stations"),
                func.count(distinct(CARD)).filter(valid_card).label("cards"),
            ).where(*conds).group_by(gcol)
        )).all()
        names = await self._station_names(company_id) if group_by == "station" else {}

        lines = []
        for r in rows:
            cnt = int(r.cnt)
            liters = float(r.liters)
            amount = float(r.amount)
            lines.append({
                "key": str(r.g) if r.g is not None else "—",
                "label": self._label(group_by, r.g, cls, names),
                "fills": cnt,
                "liters": round(liters, 1),
                "amount": round(amount, 2),
                "avg_check": round(amount / cnt, 2) if cnt else 0.0,
                "avg_fill": round(liters / cnt, 2) if cnt else 0.0,
                "avg_price": round(amount / liters, 2) if liters else 0.0,
                "stations": int(r.stations or 0),
                "cards": int(r.cards or 0),
            })
        total_amount = sum(l["amount"] for l in lines)
        for l in lines:
            l["share_pct"] = round(l["amount"] / total_amount * 100, 2) if total_amount else 0.0
        if group_by in ("hour", "weekday", "day", "week", "month", "quarter", "decade"):
            lines.sort(key=lambda x: x["key"] if group_by not in ("hour", "weekday")
                       else float(x["key"]))
        else:
            lines.sort(key=lambda x: -x["amount"])
        truncated = max(0, len(lines) - top)
        lines = lines[:top]

        tot = (await self.db.execute(select(
            func.count(), func.coalesce(func.sum(T.liters), 0), func.coalesce(func.sum(T.amount), 0),
            func.count(distinct(T.station_code)),
            func.count(distinct(CARD)).filter(valid_card),
        ).where(*conds))).one()
        tc, tl, ta = int(tot[0]), float(tot[1]), float(tot[2])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "group_by": group_by,
            "lines": lines,
            "truncated": truncated,
            "totals": {
                "label": "Итого", "fills": tc, "liters": round(tl, 1), "amount": round(ta, 2),
                "avg_check": round(ta / tc, 2) if tc else 0.0,
                "avg_fill": round(tl / tc, 2) if tc else 0.0,
                "avg_price": round(ta / tl, 2) if tl else 0.0,
                "stations": int(tot[3] or 0), "cards": int(tot[4] or 0), "share_pct": 100.0,
            },
        }

    # ─── Наливы: динамика / нарезка / сравнение / heatmap ──────────────

    async def _aggregate_2d(self, company_id, date_from, date_to, bucket_by: str,
                            series_by: str | None, cls: _Classification, dups: list[str],
                            station_codes=(), fuel_codes=(), pay_names=None, card=None) -> list[Any]:
        """Сырые суммы по (бакет [× серия])."""
        bcol = self._group_col(bucket_by, cls)
        sel = [
            bcol.label("b"),
            func.count().label("cnt"),
            func.coalesce(func.sum(T.liters), 0).label("liters"),
            func.coalesce(func.sum(T.amount), 0).label("amount"),
        ]
        groups = [bcol]
        if series_by:
            scol = self._group_col(series_by, cls)
            sel.insert(1, scol.label("s"))
            groups.append(scol)
        stmt = select(*sel).where(*self._conds(
            company_id, date_from, date_to, dups, station_codes, fuel_codes, pay_names, card,
        )).group_by(*groups)
        return list((await self.db.execute(stmt)).all())

    @cached_report("fuel:fills_ts")
    async def fills_timeseries(self, company_id, date_from: date, date_to: date,
                               bucket: str = "day", metric: str = "amount",
                               series_by: str | None = None, top_n: int = 5,
                               station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                               segment: str | None = None, channel: str | None = None,
                               card: str | None = None) -> dict[str, Any]:
        """Динамика метрики по бакетам; series_by → multi-series (топ-N + «Прочие»)."""
        cls, dups = await self._classification(company_id)
        pay_names = self._pay_filter(cls, segment, channel)
        rows = await self._aggregate_2d(company_id, date_from, date_to, bucket, series_by,
                                        cls, dups, station_codes, fuel_codes, pay_names, card)
        axis = AnalyticsService._cs_bucket_axis(date_from, date_to, bucket)
        empty = None if self._is_ratio(metric) else 0
        base = {"bucket": bucket, "metric": metric,
                "period": {"from": date_from.isoformat(), "to": date_to.isoformat()}}
        names = await self._station_names(company_id) if series_by == "station" else {}

        if not series_by:
            by = {r.b: r for r in rows}
            data = [{"bucket": b,
                     "value": (self._metric_from_sums(metric, by[b].cnt, by[b].liters, by[b].amount)
                               if b in by else empty)} for b in axis]
            return {**base, "series": ["value"], "data": data}

        tot: dict[str, float] = defaultdict(float)
        for r in rows:
            tot[self._label(series_by, r.s, cls, names)] += float(r.amount)
        top = [s for s, _ in sorted(tot.items(), key=lambda kv: -kv[1])[:top_n]]
        top_set = set(top)
        has_other = len(tot) > len(top_set)
        cell: dict[tuple, list] = defaultdict(lambda: [0, 0.0, 0.0])
        for r in rows:
            lbl = self._label(series_by, r.s, cls, names)
            key = lbl if lbl in top_set else "Прочие"
            c = cell[(r.b, key)]
            c[0] += int(r.cnt)
            c[1] += float(r.liters)
            c[2] += float(r.amount)
        series = top + (["Прочие"] if has_other else [])
        data = []
        for b in axis:
            row: dict[str, Any] = {"bucket": b}
            for s in series:
                c = cell.get((b, s))
                row[s] = self._metric_from_sums(metric, *c) if c else empty
            data.append(row)
        return {**base, "series": series, "data": data}

    @cached_report("fuel:fills_slice")
    async def fills_slice(self, company_id, date_from: date, date_to: date,
                          bucket: str = "month", group_by: str | None = None,
                          metric: str = "amount", top_n: int = 8,
                          station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                          segment: str | None = None, channel: str | None = None) -> dict[str, Any]:
        """Нарезка периода на интервалы; строки = разрез (или «Вся сеть»)."""
        cls, dups = await self._classification(company_id)
        pay_names = self._pay_filter(cls, segment, channel)
        rows = await self._aggregate_2d(company_id, date_from, date_to, bucket, group_by,
                                        cls, dups, station_codes, fuel_codes, pay_names)
        axis = AnalyticsService._cs_bucket_axis(date_from, date_to, bucket)
        intervals = []
        for b in axis:
            iv = AnalyticsService._cs_interval(bucket, b)
            iv["partial"] = (date.fromisoformat(iv["from"]) < date_from) or \
                            (date.fromisoformat(iv["to"]) > date_to)
            intervals.append(iv)
        complete_idx = [i for i, iv in enumerate(intervals) if not iv["partial"]]
        empty = None if self._is_ratio(metric) else 0
        names = await self._station_names(company_id) if group_by == "station" else {}

        def slice_line(label: str, values: list) -> dict[str, Any]:
            idx = complete_idx or list(range(len(values)))
            first = values[idx[0]] or 0
            last = values[idx[-1]] or 0
            prev = (values[idx[-2]] if len(idx) > 1 else 0) or 0
            return {
                "label": label, "values": values,
                "delta_first": round(last - first, 2),
                "delta_prev": round(last - prev, 2),
                "delta_pct_prev": round((last - prev) / prev * 100, 1) if prev else (100.0 if last else 0.0),
            }

        net: dict[str, list] = defaultdict(lambda: [0, 0.0, 0.0])
        for r in rows:
            c = net[r.b]
            c[0] += int(r.cnt)
            c[1] += float(r.liters)
            c[2] += float(r.amount)
        net_values = [self._metric_from_sums(metric, *net[b]) if b in net else empty for b in axis]

        if not group_by:
            lines = [slice_line("Вся сеть", net_values)]
        else:
            tot: dict[str, float] = defaultdict(float)
            for r in rows:
                tot[self._label(group_by, r.s, cls, names)] += float(r.amount)
            top = [s for s, _ in sorted(tot.items(), key=lambda kv: -kv[1])[:top_n]]
            top_set = set(top)
            has_other = len(tot) > len(top_set)
            cell: dict[tuple, list] = defaultdict(lambda: [0, 0.0, 0.0])
            for r in rows:
                lbl = self._label(group_by, r.s, cls, names)
                key = lbl if lbl in top_set else "Прочие"
                c = cell[(key, r.b)]
                c[0] += int(r.cnt)
                c[1] += float(r.liters)
                c[2] += float(r.amount)
            series = top + (["Прочие"] if has_other else [])
            lines = [slice_line(s, [self._metric_from_sums(metric, *cell[(s, b)])
                                    if (s, b) in cell else empty for b in axis])
                     for s in series]

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "bucket": bucket, "metric": metric, "group_by": group_by or "__net__",
            "intervals": intervals, "lines": lines,
            "totals": {"values": net_values},
        }

    @cached_report("fuel:fills_cmp")
    async def fills_compare_multi(self, company_id, periods: tuple[tuple[str, str], ...],
                                  group_by: str = "station", metric: str = "amount",
                                  station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                                  segment: str | None = None, channel: str | None = None) -> dict[str, Any]:
        """Сравнение 2–4 произвольных периодов по разрезу."""
        cls, dups = await self._classification(company_id)
        pay_names = self._pay_filter(cls, segment, channel)
        names = await self._station_names(company_id) if group_by == "station" else {}
        gcol = self._group_col(group_by, cls)

        maps: list[dict[str, Any]] = []
        totals: list[float] = []
        for pf_s, pt_s in periods:
            pf, pt = date.fromisoformat(pf_s), date.fromisoformat(pt_s)
            rows = (await self.db.execute(
                select(gcol.label("g"), func.count().label("cnt"),
                       func.coalesce(func.sum(T.liters), 0).label("liters"),
                       func.coalesce(func.sum(T.amount), 0).label("amount"))
                .where(*self._conds(company_id, pf, pt, dups, station_codes, fuel_codes, pay_names))
                .group_by(gcol)
            )).all()
            maps.append({self._label(group_by, r.g, cls, names): r for r in rows})
            totals.append(self._metric_from_sums(
                metric,
                sum(int(r.cnt) for r in rows),
                sum(float(r.liters) for r in rows),
                sum(float(r.amount) for r in rows)))
        labels = sorted(set().union(*[set(m) for m in maps])) if maps else []

        def mv(m, lb):
            r = m.get(lb)
            if r is None:
                return None if self._is_ratio(metric) else 0
            return self._metric_from_sums(metric, r.cnt, r.liters, r.amount)

        lines = []
        for lb in labels:
            vals = [mv(m, lb) for m in maps]
            first = vals[0] or 0
            prev = (vals[-2] if len(vals) > 1 else 0) or 0
            last = vals[-1] or 0
            lines.append({
                "label": lb, "values": vals,
                "delta_first": round(last - first, 2),
                "delta_prev": round(last - prev, 2),
                "delta_pct_prev": round((last - prev) / prev * 100, 1) if prev else (100.0 if last else 0.0),
            })
        lines.sort(key=lambda x: -abs(x["delta_prev"]))
        return {
            "periods": [{"from": pf, "to": pt} for pf, pt in periods],
            "group_by": group_by, "metric": metric, "lines": lines,
            "totals": {"values": [round(t, 2) for t in totals]},
        }

    @cached_report("fuel:fills_heat")
    async def fills_heatmap(self, company_id, date_from: date, date_to: date,
                            metric: str = "fills",
                            station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                            segment: str | None = None, channel: str | None = None) -> dict[str, Any]:
        """Матрица час (0–23) × день недели (1=Пн..7=Вс)."""
        cls, dups = await self._classification(company_id)
        pay_names = self._pay_filter(cls, segment, channel)
        rows = await self._aggregate_2d(company_id, date_from, date_to, "hour", "weekday",
                                        cls, dups, station_codes, fuel_codes, pay_names)
        cells = []
        for r in rows:
            try:
                h = int(float(r.b))
                wd = int(float(r.s))
            except (ValueError, TypeError):
                continue
            cells.append({"hour": h, "weekday": wd,
                          "value": self._metric_from_sums(metric, r.cnt, r.liters, r.amount)})
        return {"metric": metric, "cells": cells,
                "period": {"from": date_from.isoformat(), "to": date_to.isoformat()}}

    # ─── Наливы: когорты «новые карты» ──────────────────────────────────

    def _card_conds(self, company_id, dups: list[str], pay_names: list[str] | None,
                    station_codes=(), fuel_codes=()) -> list:
        """Условия для когорт: только наливы с валидной картой (без периода)."""
        conds = [T.company_id == company_id,
                 CARD.is_not(None),
                 func.trim(T.card).op("!~")("^0+$")]
        if dups:
            conds.append(T.pay_type_name.notin_(dups))
        if station_codes:
            conds.append(T.station_code.in_(station_codes))
        if fuel_codes:
            conds.append(T.fuel_code.in_(fuel_codes))
        if pay_names is not None:
            conds.append(T.pay_type_name.in_(pay_names))
        return conds

    @cached_report("fuel:new_cards")
    async def new_cards_slice(self, company_id, date_from: date, date_to: date,
                              bucket: str = "month",
                              station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                              segment: str | None = None, channel: str | None = None) -> dict[str, Any]:
        """По интервалам: активные/новые/вернувшиеся карты + вклад новых.

        «Новая» = первый налив карты за всю историю наблюдений попадает в
        интервал (история — в рамках фильтров: сегмент/станции/топливо)."""
        cls, dups = await self._classification(company_id)
        pay_names = self._pay_filter(cls, segment, channel)
        conds = self._card_conds(company_id, dups, pay_names, station_codes, fuel_codes)

        first_rows = (await self.db.execute(
            select(CARD.label("k"), func.min(T.dt).label("fa"))
            .where(*conds).group_by(CARD)
        )).all()
        first = {r.k: r.fa.date() for r in first_rows if r.k and r.fa}

        day = func.date_trunc("day", self._msk()).label("d")
        act = (await self.db.execute(
            select(CARD.label("k"), day,
                   func.count().label("n"),
                   func.sum(T.liters).label("liters"),
                   func.sum(T.amount).label("rub"))
            .where(*conds,
                   T.dt >= datetime(date_from.year, date_from.month, date_from.day),
                   T.dt <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59))
            .group_by(CARD, day)
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
            {"active": set(), "new": set(), "nF": 0, "nL": 0.0, "nR": 0.0, "tR": 0.0}
            for _ in intervals
        ]
        for r in act:
            d = r.d.date()
            idx = next((i for i, (lo, hi) in enumerate(bounds) if lo <= d <= hi), None)
            if idx is None:
                continue
            c = per[idx]
            c["active"].add(r.k)
            c["tR"] += float(r.rub or 0)
            fa = first.get(r.k)
            if fa is not None and bounds[idx][0] <= fa <= bounds[idx][1]:
                c["new"].add(r.k)
                c["nF"] += int(r.n)
                c["nL"] += float(r.liters or 0)
                c["nR"] += float(r.rub or 0)

        out = []
        for iv, c in zip(intervals, per):
            n_new, n_act = len(c["new"]), len(c["active"])
            out.append({
                **iv,
                "activeCards": n_act,
                "newCards": n_new,
                "returningCards": n_act - n_new,
                "newSharePct": round(n_new / n_act * 100, 1) if n_act else None,
                "newFills": c["nF"],
                "newLiters": round(c["nL"], 1),
                "newRevenue": round(c["nR"], 2),
                "totalRevenue": round(c["tR"], 2),
                "newRevenueSharePct": round(c["nR"] / c["tR"] * 100, 1) if c["tR"] else None,
            })
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "bucket": bucket, "intervals": out,
            "historyFrom": min(first.values()).isoformat() if first else None,
            "totals": {
                "newCards": len({k for c in per for k in c["new"]}),
                "activeCards": len({k for c in per for k in c["active"]}),
                "newRevenue": round(sum(c["nR"] for c in per), 2),
            },
        }

    @cached_report("fuel:new_cards_list")
    async def new_cards_list(self, company_id, date_from: date, date_to: date,
                             station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                             segment: str | None = None, channel: str | None = None,
                             limit: int = 500) -> dict[str, Any]:
        """Конкретные НОВЫЕ карты интервала: когда впервые, сколько принесли."""
        cls, dups = await self._classification(company_id)
        pay_names = self._pay_filter(cls, segment, channel)
        conds = self._card_conds(company_id, dups, pay_names, station_codes, fuel_codes)
        first_sq = (
            select(CARD.label("k"), func.min(T.dt).label("fa"))
            .where(*conds).group_by(CARD).subquery()
        )
        lo = datetime(date_from.year, date_from.month, date_from.day)
        hi = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)
        ch_case = cls.channel_case()
        rows = (await self.db.execute(
            select(
                CARD.label("k"),
                first_sq.c.fa.label("first_at"),
                func.count().label("fills"),
                func.sum(T.liters).label("liters"),
                func.sum(T.amount).label("revenue"),
                func.count(distinct(T.station_code)).label("stations"),
                func.max(ch_case).label("channel"),
            )
            .join(first_sq, first_sq.c.k == CARD)
            .where(*conds, T.dt >= lo, T.dt <= hi,
                   first_sq.c.fa >= lo, first_sq.c.fa <= hi)
            .group_by(CARD, first_sq.c.fa)
            .order_by(func.sum(T.amount).desc(), CARD)  # tie-break: при равной выручке
            # усечение rows[:limit] иначе давало разный состав между запросами
        )).all()
        cards = [{
            "card": r.k,
            "firstAt": r.first_at.isoformat(sep=" ", timespec="minutes") if r.first_at else None,
            "fills": int(r.fills or 0),
            "liters": round(float(r.liters or 0), 1),
            "revenue": round(float(r.revenue or 0), 2),
            "stations": int(r.stations or 0),
            "channel": cls.channel_label(str(r.channel)) if r.channel else "—",
        } for r in rows[:limit]]
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "count": len(rows), "cards": cards,
        }

    # ─── Тарифы ─────────────────────────────────────────────────────────

    @cached_report("fuel:tariff_grid")
    async def tariff_grid(self, company_id, date_from: date, date_to: date) -> dict[str, Any]:
        """Прайс-сетка станция × вид топлива: номинал стеллы (взвеш.), диапазон, факт."""
        _cls, dups = await self._classification(company_id)
        conds = self._conds(company_id, date_from, date_to, dups)
        rows = (await self.db.execute(
            select(
                T.station_code, T.fuel_code,
                func.max(T.fuel_name).label("fuel_name"),
                func.count().label("cnt"),
                func.coalesce(func.sum(T.liters), 0).label("liters"),
                func.coalesce(func.sum(T.amount), 0).label("amount"),
                func.coalesce(func.sum(T.liters * T.price), 0).label("lp"),
                func.min(T.price).label("pmin"),
                func.max(T.price).label("pmax"),
            ).where(*conds, T.price.is_not(None), T.price > 0)
            .group_by(T.station_code, T.fuel_code)
        )).all()
        names = await self._station_names(company_id)
        st_codes = sorted({int(r.station_code) for r in rows if r.station_code is not None})
        fuels_map = {int(r.fuel_code): (r.fuel_name or f"Топливо {r.fuel_code}")
                     for r in rows if r.fuel_code is not None}
        fuels = [{"code": c, "name": fuels_map[c]} for c in sorted(fuels_map)]
        cells = []
        for r in rows:
            liters = float(r.liters)
            pmin, pmax = float(r.pmin or 0), float(r.pmax or 0)
            cells.append({
                "station_code": int(r.station_code),
                "fuel_code": int(r.fuel_code),
                "fills": int(r.cnt),
                "liters": round(liters, 1),
                "price_avg": round(float(r.lp) / liters, 2) if liters else None,
                "price_min": round(pmin, 2),
                "price_max": round(pmax, 2),
                "varies": (pmax - pmin) > 0.005,
                "realized": round(float(r.amount) / liters, 2) if liters else None,
            })
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "stations": [{"code": c, "name": names.get(c) or f"АЗС {c}"} for c in st_codes],
            "fuels": fuels,
            "cells": cells,
        }

    @cached_report("fuel:tariff_dev")
    async def price_deviations(self, company_id, date_from: date, date_to: date) -> dict[str, Any]:
        """Отклонение факт-цены станции от средней по сети (на вид топлива) +
        скидки по каналам из сменного sales-блока (fuel_shift_sales.discount)."""
        _cls, dups = await self._classification(company_id)
        conds = self._conds(company_id, date_from, date_to, dups)
        rows = (await self.db.execute(
            select(
                T.station_code, T.fuel_code,
                func.max(T.fuel_name).label("fuel_name"),
                func.count().label("cnt"),
                func.coalesce(func.sum(T.liters), 0).label("liters"),
                func.coalesce(func.sum(T.amount), 0).label("amount"),
            ).where(*conds).group_by(T.station_code, T.fuel_code)
        )).all()
        names = await self._station_names(company_id)
        net: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])  # fuel → [liters, amount]
        for r in rows:
            net[int(r.fuel_code)][0] += float(r.liters)
            net[int(r.fuel_code)][1] += float(r.amount)
        lines = []
        for r in rows:
            liters, amount = float(r.liters), float(r.amount)
            if not liters:
                continue
            nl, na = net[int(r.fuel_code)]
            net_price = na / nl if nl else 0.0
            price = amount / liters
            lines.append({
                "station_code": int(r.station_code),
                "station": f"{names.get(int(r.station_code)) or 'АЗС'} ({r.station_code})",
                "fuel_code": int(r.fuel_code),
                "fuel": r.fuel_name or "—",
                "fills": int(r.cnt),
                "liters": round(liters, 1),
                "price": round(price, 2),
                "net_avg": round(net_price, 2),
                "delta": round(price - net_price, 2),
                "delta_pct": round((price - net_price) / net_price * 100, 2) if net_price else 0.0,
            })
        lines.sort(key=lambda x: -abs(x["delta"]))

        # Скидки по каналам — из сменного sales-блока (на грейне наливов скидок нет)
        disc_rows = (await self.db.execute(
            select(FuelShiftSale.payment_channel,
                   func.coalesce(func.sum(FuelShiftSale.amount), 0).label("amount"),
                   func.coalesce(func.sum(FuelShiftSale.discount), 0).label("discount"))
            .join(FuelShift, FuelShift.id == FuelShiftSale.shift_id)
            .where(FuelShiftSale.company_id == company_id,
                   FuelShift.closed_at.is_not(None),
                   FuelShift.closed_at >= datetime(date_from.year, date_from.month, date_from.day),
                   FuelShift.closed_at <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59))
            .group_by(FuelShiftSale.payment_channel)
        )).all()
        labels = {c.code: c.name for c in (await self.db.execute(
            select(PaymentChannel).where(PaymentChannel.company_id == company_id)
        )).scalars().all()}
        discounts = [{
            "channel": r.payment_channel,
            "label": labels.get(r.payment_channel, r.payment_channel),
            "amount": round(float(r.amount), 2),
            "discount": round(float(r.discount), 2),
        } for r in disc_rows if float(r.amount) or float(r.discount)]
        discounts.sort(key=lambda x: -x["amount"])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "lines": lines,
            "discounts_by_channel": discounts,
        }

    @cached_report("fuel:price_ts")
    async def price_timeseries(self, company_id, date_from: date, date_to: date,
                               bucket: str = "week",
                               fuel_codes: tuple[int, ...] = ()) -> dict[str, Any]:
        """Динамика факт-цены ₽/л по видам топлива (средневзвешенная по литрам)."""
        cls, dups = await self._classification(company_id)
        rows = await self._aggregate_2d(company_id, date_from, date_to, bucket, "fuel",
                                        cls, dups, (), fuel_codes)
        axis = AnalyticsService._cs_bucket_axis(date_from, date_to, bucket)
        fuels = sorted({str(r.s) for r in rows if r.s})
        cell: dict[tuple, list] = {}
        for r in rows:
            cell[(r.b, str(r.s))] = [float(r.liters), float(r.amount)]
        data = []
        for b in axis:
            row: dict[str, Any] = {"bucket": b}
            for f in fuels:
                c = cell.get((b, f))
                row[f] = round(c[1] / c[0], 2) if c and c[0] else None
            data.append(row)
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "bucket": bucket, "series": fuels, "data": data,
        }

    # ─── Корпоратив (сегмент corp = cards + ledger) ─────────────────────

    @cached_report("fuel:corp_overview")
    async def corporate_overview(self, company_id, date_from: date, date_to: date) -> dict[str, Any]:
        """KPI corp-сегмента + структура по топливу/станциям/каналам + помесячно."""
        cls, dups = await self._classification(company_id)
        corp_names = cls.segment_names("corp")
        conds = self._conds(company_id, date_from, date_to, dups, pay_names=corp_names)
        valid_card = CARD.is_not(None) & func.trim(T.card).op("!~")("^0+$")

        kpi_row = (await self.db.execute(select(
            func.count(), func.coalesce(func.sum(T.liters), 0), func.coalesce(func.sum(T.amount), 0),
            func.count(distinct(CARD)).filter(valid_card),
            func.count(distinct(T.station_code)),
        ).where(*conds))).one()
        cnt, liters, amount = int(kpi_row[0]), float(kpi_row[1]), float(kpi_row[2])

        total_all = float((await self.db.execute(select(
            func.coalesce(func.sum(T.amount), 0)
        ).where(*self._conds(company_id, date_from, date_to, dups)))).scalar_one())

        async def breakdown(gcol, label_fn):
            rows = (await self.db.execute(
                select(gcol.label("g"), func.count().label("cnt"),
                       func.coalesce(func.sum(T.liters), 0).label("liters"),
                       func.coalesce(func.sum(T.amount), 0).label("amount"))
                .where(*conds).group_by(gcol)
            )).all()
            out = [{
                "label": label_fn(r.g), "fills": int(r.cnt),
                "liters": round(float(r.liters), 1), "amount": round(float(r.amount), 2),
                "share_pct": round(float(r.amount) / amount * 100, 2) if amount else 0.0,
            } for r in rows]
            out.sort(key=lambda x: -x["amount"])
            return out

        names = await self._station_names(company_id)
        by_fuel = await breakdown(func.coalesce(T.fuel_name, "—"), lambda g: str(g))
        by_station = await breakdown(T.station_code,
                                     lambda g: f"{names.get(int(g)) or 'АЗС'} ({g})" if g is not None else "—")
        by_channel = await breakdown(cls.channel_case(), lambda g: cls.channel_label(str(g)))

        month_col = func.to_char(self._msk(), "YYYY-MM")
        monthly_rows = (await self.db.execute(
            select(month_col.label("m"), func.count().label("cnt"),
                   func.coalesce(func.sum(T.liters), 0).label("liters"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"),
                   func.count(distinct(CARD)).filter(valid_card).label("cards"))
            .where(*conds).group_by(month_col).order_by(month_col)
        )).all()
        monthly = [{
            "month": r.m, "fills": int(r.cnt), "liters": round(float(r.liters), 1),
            "amount": round(float(r.amount), 2), "cards": int(r.cards or 0),
        } for r in monthly_rows]

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "kpi": {
                "amount": round(amount, 2), "liters": round(liters, 1), "fills": cnt,
                "active_cards": int(kpi_row[3] or 0), "stations": int(kpi_row[4] or 0),
                "avg_fill": round(liters / cnt, 2) if cnt else 0.0,
                "avg_price": round(amount / liters, 2) if liters else 0.0,
                "share_of_total_pct": round(amount / total_all * 100, 2) if total_all else 0.0,
            },
            "by_fuel": by_fuel, "by_station": by_station, "by_channel": by_channel,
            "monthly": monthly,
        }

    @cached_report("fuel:corp_cparties")
    async def corporate_counterparties(self, company_id, date_from: date, date_to: date) -> dict[str, Any]:
        """Контрагенты-процессоры corp-сегмента (уровень вида оплаты): БАЛТОП,
        VIAcard, Инфорком и т.д. — готовые «клиенты» без НСИ."""
        cls, dups = await self._classification(company_id)
        corp_names = cls.segment_names("corp")
        conds = self._conds(company_id, date_from, date_to, dups, pay_names=corp_names)
        valid_card = CARD.is_not(None) & func.trim(T.card).op("!~")("^0+$")
        rows = (await self.db.execute(
            select(T.pay_type_name.label("name"),
                   func.count().label("cnt"),
                   func.coalesce(func.sum(T.liters), 0).label("liters"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"),
                   func.count(distinct(T.station_code)).label("stations"),
                   func.count(distinct(CARD)).filter(valid_card).label("cards"))
            .where(*conds).group_by(T.pay_type_name)
        )).all()
        # тренд по месяцам одним 2D-проходом
        month_col = func.to_char(self._msk(), "YYYY-MM")
        tr_rows = (await self.db.execute(
            select(T.pay_type_name.label("name"), month_col.label("m"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"))
            .where(*conds).group_by(T.pay_type_name, month_col)
        )).all()
        months = AnalyticsService._cs_bucket_axis(date_from, date_to, "month")
        tr: dict[str, dict[str, float]] = defaultdict(dict)
        for r in tr_rows:
            tr[r.name or "—"][r.m] = float(r.amount)
        total_amount = sum(float(r.amount) for r in rows)
        out = []
        for r in rows:
            name = r.name or "—"
            cnt, liters, amount = int(r.cnt), float(r.liters), float(r.amount)
            out.append({
                "name": name,
                "channel": cls.channel_label(cls.channel_by_name.get(name, "unmapped")),
                "fills": cnt, "liters": round(liters, 1), "amount": round(amount, 2),
                "avg_fill": round(liters / cnt, 2) if cnt else 0.0,
                "avg_price": round(amount / liters, 2) if liters else 0.0,
                "stations": int(r.stations or 0), "cards": int(r.cards or 0),
                "share_pct": round(amount / total_amount * 100, 2) if total_amount else 0.0,
                "trend": [round(tr[name].get(m, 0.0), 2) for m in months],
            })
        out.sort(key=lambda x: -x["amount"])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "months": months, "rows": out,
            "totals": {"amount": round(total_amount, 2),
                       "fills": sum(x["fills"] for x in out),
                       "liters": round(sum(x["liters"] for x in out), 1)},
        }

    _CARDS_SORT = ("amount", "liters", "fills", "avg_fill", "first_dt", "last_dt")

    @cached_report("fuel:corp_cards")
    async def corporate_cards(self, company_id, date_from: date, date_to: date,
                              sort: str = "amount", order: str = "desc",
                              limit: int = 50, offset: int = 0,
                              search: str | None = None,
                              segment: str = "corp") -> dict[str, Any]:
        """Реестр карт сегмента (по умолчанию corp): серверная пагинация/поиск.

        Точка расширения НСИ «карта→организация»: каждая строка несёт org=null;
        при появлении справочника группировка меняется на COALESCE(org, card)."""
        cls, dups = await self._classification(company_id)
        pay_names = cls.segment_names(segment)
        conds = self._card_conds(company_id, dups, pay_names)
        conds += [
            T.dt >= datetime(date_from.year, date_from.month, date_from.day),
            T.dt <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59),
        ]
        if search:
            conds.append(func.trim(T.card).ilike(f"%{search.strip()}%"))

        tot = (await self.db.execute(select(
            func.count(distinct(CARD)), func.count(),
            func.coalesce(func.sum(T.liters), 0), func.coalesce(func.sum(T.amount), 0),
        ).where(*conds))).one()

        rows = (await self.db.execute(
            select(CARD.label("card"),
                   func.count().label("cnt"),
                   func.coalesce(func.sum(T.liters), 0).label("liters"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"),
                   func.count(distinct(T.station_code)).label("stations"),
                   func.count(distinct(T.fuel_code)).label("fuels"),
                   func.min(T.dt).label("first_dt"),
                   func.max(T.dt).label("last_dt"),
                   func.max(T.pay_type_name).label("pay_type"))
            .where(*conds).group_by(CARD).order_by(CARD)  # стабильный исходный порядок:
            # Python sorted() ниже стабилен, но БД без ORDER BY отдаёт ties в
            # произвольном порядке → состав страницы «плавал» между запросами.
        )).all()

        def key(r):
            if sort == "liters":
                return float(r.liters)
            if sort == "fills":
                return int(r.cnt)
            if sort == "avg_fill":
                return float(r.liters) / int(r.cnt) if int(r.cnt) else 0.0
            if sort == "first_dt":
                return r.first_dt or datetime.min
            if sort == "last_dt":
                return r.last_dt or datetime.min
            return float(r.amount)

        rows = sorted(rows, key=key, reverse=(order != "asc"))
        page = rows[offset:offset + limit]

        # мини-тренд по месяцам — только для карт страницы
        months = AnalyticsService._cs_bucket_axis(date_from, date_to, "month")[-6:]
        trends: dict[str, dict[str, float]] = defaultdict(dict)
        page_cards = [r.card for r in page if r.card]
        if page_cards:
            month_col = func.to_char(self._msk(), "YYYY-MM")
            tr_rows = (await self.db.execute(
                select(CARD.label("card"), month_col.label("m"),
                       func.coalesce(func.sum(T.amount), 0).label("amount"))
                .where(*conds, CARD.in_(page_cards))
                .group_by(CARD, month_col)
            )).all()
            for r in tr_rows:
                trends[r.card][r.m] = float(r.amount)

        out = [{
            "card": r.card,
            "org": None,  # расширение: НСИ «карта→организация»
            "pay_type": r.pay_type,
            "fills": int(r.cnt),
            "liters": round(float(r.liters), 1),
            "amount": round(float(r.amount), 2),
            "avg_fill": round(float(r.liters) / int(r.cnt), 2) if int(r.cnt) else 0.0,
            "stations": int(r.stations or 0),
            "fuels": int(r.fuels or 0),
            "first_dt": r.first_dt.isoformat() if r.first_dt else None,
            "last_dt": r.last_dt.isoformat() if r.last_dt else None,
            "trend": [round(trends[r.card].get(m, 0.0), 2) for m in months],
        } for r in page]
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "total": int(tot[0] or 0),
            "months": months,
            "totals": {"cards": int(tot[0] or 0), "fills": int(tot[1] or 0),
                       "liters": round(float(tot[2]), 1), "amount": round(float(tot[3]), 2)},
            "rows": out,
        }

    # ─── Частные лица (retail = retail_cash + retail_card + retail) ─────

    @cached_report("fuel:retail_overview")
    async def retail_overview(self, company_id, date_from: date, date_to: date) -> dict[str, Any]:
        """KPI розницы + нал/безнал + структура + гистограмма чеков + понедельно."""
        cls, dups = await self._classification(company_id)
        retail_names = cls.segment_names("retail")
        conds = self._conds(company_id, date_from, date_to, dups, pay_names=retail_names)

        kpi_row = (await self.db.execute(select(
            func.count(), func.coalesce(func.sum(T.liters), 0), func.coalesce(func.sum(T.amount), 0),
        ).where(*conds))).one()
        cnt, liters, amount = int(kpi_row[0]), float(kpi_row[1]), float(kpi_row[2])

        total_all = float((await self.db.execute(select(
            func.coalesce(func.sum(T.amount), 0)
        ).where(*self._conds(company_id, date_from, date_to, dups)))).scalar_one())

        ch_case = cls.channel_case()
        by_pay_rows = (await self.db.execute(
            select(ch_case.label("g"), func.count().label("cnt"),
                   func.coalesce(func.sum(T.liters), 0).label("liters"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"))
            .where(*conds).group_by(ch_case)
        )).all()
        by_pay = [{
            "channel": str(r.g), "label": cls.channel_label(str(r.g)),
            "fills": int(r.cnt), "liters": round(float(r.liters), 1),
            "amount": round(float(r.amount), 2),
            "share_pct": round(float(r.amount) / amount * 100, 2) if amount else 0.0,
        } for r in by_pay_rows]
        by_pay.sort(key=lambda x: -x["amount"])
        cashless = sum(x["amount"] for x in by_pay if x["channel"] == "retail_card")

        async def breakdown(gcol, label_fn):
            rows = (await self.db.execute(
                select(gcol.label("g"), func.count().label("cnt"),
                       func.coalesce(func.sum(T.liters), 0).label("liters"),
                       func.coalesce(func.sum(T.amount), 0).label("amount"))
                .where(*conds).group_by(gcol)
            )).all()
            out = [{
                "label": label_fn(r.g), "fills": int(r.cnt),
                "liters": round(float(r.liters), 1), "amount": round(float(r.amount), 2),
                "avg_check": round(float(r.amount) / int(r.cnt), 2) if int(r.cnt) else 0.0,
                "share_pct": round(float(r.amount) / amount * 100, 2) if amount else 0.0,
            } for r in rows]
            out.sort(key=lambda x: -x["amount"])
            return out

        names = await self._station_names(company_id)
        by_fuel = await breakdown(func.coalesce(T.fuel_name, "—"), lambda g: str(g))
        by_station = await breakdown(T.station_code,
                                     lambda g: f"{names.get(int(g)) or 'АЗС'} ({g})" if g is not None else "—")

        # гистограмма чеков: границы в ₽
        edges = [250, 500, 750, 1000, 1500, 2000, 3000, 5000]
        wb = func.width_bucket(T.amount, edges)
        hist_rows = (await self.db.execute(
            select(wb.label("b"), func.count().label("cnt"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"))
            .where(*conds).group_by(wb).order_by(wb)
        )).all()
        bin_labels = ["до 250", "250–500", "500–750", "750–1 000", "1 000–1 500",
                      "1 500–2 000", "2 000–3 000", "3 000–5 000", "5 000+"]
        hist_map = {int(r.b): r for r in hist_rows}
        check_histogram = [{
            "label": bin_labels[i],
            "count": int(hist_map[i].cnt) if i in hist_map else 0,
            "amount": round(float(hist_map[i].amount), 2) if i in hist_map else 0.0,
        } for i in range(len(bin_labels))]

        median = (await self.db.execute(select(
            func.percentile_cont(0.5).within_group(T.amount),
            func.percentile_cont(0.9).within_group(T.amount),
        ).where(*conds))).one()

        week_col = func.to_char(func.date_trunc("week", self._msk()), "YYYY-MM-DD")
        weekly_rows = (await self.db.execute(
            select(week_col.label("w"), func.count().label("cnt"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"))
            .where(*conds).group_by(week_col).order_by(week_col)
        )).all()
        weekly = [{
            "week": r.w, "fills": int(r.cnt), "amount": round(float(r.amount), 2),
            "avg_check": round(float(r.amount) / int(r.cnt), 2) if int(r.cnt) else 0.0,
        } for r in weekly_rows]

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "kpi": {
                "amount": round(amount, 2), "liters": round(liters, 1), "fills": cnt,
                "avg_check": round(amount / cnt, 2) if cnt else 0.0,
                "avg_fill": round(liters / cnt, 2) if cnt else 0.0,
                "cashless_pct": round(cashless / amount * 100, 1) if amount else 0.0,
                "share_of_total_pct": round(amount / total_all * 100, 2) if total_all else 0.0,
                "check_median": round(float(median[0] or 0), 2),
                "check_p90": round(float(median[1] or 0), 2),
            },
            "by_pay": by_pay, "by_fuel": by_fuel, "by_station": by_station,
            "check_histogram": check_histogram, "weekly": weekly,
        }

    @cached_report("fuel:retail_loyalty")
    async def retail_loyalty(self, company_id, date_from: date, date_to: date) -> dict[str, Any]:
        """Лояльность розницы по картам (токены банковских карт «Карта МПС»):
        постоянные vs разовые, частота визитов, топ-карты, выручка повторных."""
        cls, dups = await self._classification(company_id)
        retail_names = cls.segment_names("retail")
        conds = self._card_conds(company_id, dups, retail_names)
        conds += [
            T.dt >= datetime(date_from.year, date_from.month, date_from.day),
            T.dt <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59),
        ]
        rows = (await self.db.execute(
            select(CARD.label("card"), func.count().label("cnt"),
                   func.coalesce(func.sum(T.liters), 0).label("liters"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"))
            .where(*conds).group_by(CARD)
        )).all()

        # покрытие картами внутри розницы (наличные карт не несут)
        seg_tot = (await self.db.execute(select(
            func.count(), func.coalesce(func.sum(T.amount), 0),
        ).where(*self._conds(company_id, date_from, date_to, dups, pay_names=retail_names)))).one()
        seg_fills, seg_amount = int(seg_tot[0]), float(seg_tot[1])

        bins = [("1 визит", 1, 1), ("2 визита", 2, 2), ("3–5", 3, 5),
                ("6–10", 6, 10), ("11–20", 11, 20), ("21+", 21, 10 ** 9)]
        freq = [{"label": lb, "cards": 0, "fills": 0, "amount": 0.0} for lb, _, _ in bins]
        repeat_fills = repeat_amount = 0.0
        card_fills = card_amount = 0.0
        for r in rows:
            n = int(r.cnt)
            a = float(r.amount)
            card_fills += n
            card_amount += a
            if n >= 2:
                repeat_fills += n
                repeat_amount += a
            for i, (_lb, lo, hi) in enumerate(bins):
                if lo <= n <= hi:
                    freq[i]["cards"] += 1
                    freq[i]["fills"] += n
                    freq[i]["amount"] += a
                    break
        for f in freq:
            f["amount"] = round(f["amount"], 2)

        top_cards = sorted(rows, key=lambda r: -float(r.amount))[:20]
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "kpi": {
                "cards": len(rows),
                "repeat_cards": sum(1 for r in rows if int(r.cnt) >= 2),
                "repeat_share_pct": round(sum(1 for r in rows if int(r.cnt) >= 2) / len(rows) * 100, 1) if rows else 0.0,
                "repeat_revenue_pct": round(repeat_amount / card_amount * 100, 1) if card_amount else 0.0,
                "avg_fills_per_card": round(card_fills / len(rows), 1) if rows else 0.0,
                "card_coverage_fills_pct": round(card_fills / seg_fills * 100, 1) if seg_fills else 0.0,
                "card_coverage_amount_pct": round(card_amount / seg_amount * 100, 1) if seg_amount else 0.0,
            },
            "freq_histogram": freq,
            "top_cards": [{
                "card": r.card, "fills": int(r.cnt),
                "liters": round(float(r.liters), 1), "amount": round(float(r.amount), 2),
            } for r in top_cards],
        }
