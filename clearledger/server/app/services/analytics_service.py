"""
Аналитический сервис TradeLedger — единый источник KPI для четырёх режимов:
  management — P&L, маржа, средний чек, маркетинг (виды оплат)
  financial  — cash flow, дебиторка/кредиторка, остатки счетов
  tax        — позиция НДС (исходящий−входящий), налог на прибыль
  forecast   — экстраполяция закрытия текущего месяца

Все расчёты — над уже накопленными данными:
  - AccountingDoc.lines.postings (Дт/Кт/Сумма из РегистрБухгалтерии.Хозрасчетный БП)
  - FuelShift (нормализованные смены STS с разбивкой cash/card/voucher)
  - FuelReceipt (ТТН поступления)
  - ExportPacket (что ушло в 1С vs что ещё в очереди)

Дедуп: для P&L используем РЕАЛЬНЫЕ проводки документов БП (если они подгружены)
+ FuelShift как fallback на текущую смену, по которой ОРП ещё не создан.
"""
from __future__ import annotations

import calendar
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingDoc,
    ChargeSession,
    ExportPacket,
    FuelPump,
    FuelReceipt,
    FuelShift,
    FuelShiftSale,
    FuelStation,
    FuelTank,
    Period,
)
from app.services.mapping import normalize_default


# ─── helpers ─────────────────────────────────────────────────────────

def _starts_with(account: str, prefix: str) -> bool:
    """41 → 41.*, 90.01 → 90.01.* (но не 90.10)."""
    if not account:
        return False
    return account == prefix or account.startswith(prefix + ".")


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return first, last


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _iter_postings(doc: AccountingDoc) -> list[dict[str, Any]]:
    """Извлекает фактические проводки документа из lines.postings."""
    lines = doc.lines
    if isinstance(lines, dict):
        postings = lines.get("postings") or []
        return [p for p in postings if isinstance(p, dict)]
    return []


def _posting_amount(p: dict[str, Any]) -> float:
    for key in ("Сумма", "Amount", "amount"):
        v = p.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _posting_dt(p: dict[str, Any]) -> str:
    for key in ("СчетДт", "AccountDt", "dt"):
        v = p.get(key)
        if v:
            return str(v)
    return ""


def _posting_kt(p: dict[str, Any]) -> str:
    for key in ("СчетКт", "AccountCt", "kt"):
        v = p.get(key)
        if v:
            return str(v)
    return ""


# ─── dataclasses (JSON-сериализуемые) ─────────────────────────────────

@dataclass
class PeriodFilter:
    company_id: uuid.UUID
    date_from: date
    date_to: date
    station_id: uuid.UUID | None = None
    # Сужение сессий ЭЗС (energy): коды станций и/или каноничные регионы. Пусто = вся сеть.
    station_codes: list[str] | None = None
    regions: list[str] | None = None
    # Точечный фильтр по значению разреза (drill-down строки): dim_by=поле, dim_val=значение.
    dim_by: str | None = None
    dim_val: str | None = None


@dataclass
class PnLLine:
    label: str
    revenue: float = 0.0      # Σ Кт 90.01.* (выручка С НДС)
    revenue_net: float = 0.0  # выручка БЕЗ НДС
    cogs: float = 0.0         # Σ Дт 90.02.* (себестоимость)
    gross_margin: float = 0.0
    gross_margin_pct: float = 0.0
    docs_count: int = 0
    liters: float = 0.0


@dataclass
class CashFlowAccount:
    account: str
    name: str
    debit: float = 0.0       # обороты Дт
    credit: float = 0.0      # обороты Кт
    net: float = 0.0         # Дт - Кт (для активных счетов = увеличение остатка)


@dataclass
class PayablesReceivables:
    counterparty: str
    inn: str | None
    debit: float = 0.0       # мы должны (60.01) или нам должны (62.01)
    credit: float = 0.0
    balance: float = 0.0     # активный остаток = Дт-Кт; пассивный = Кт-Дт


@dataclass
class VatPosition:
    output_vat: float = 0.0      # Кт 68.02 (исходящий)
    input_vat: float = 0.0       # Дт 19.03 (входящий)
    payable: float = 0.0         # output − input
    revenue_with_vat: float = 0.0
    revenue_net: float = 0.0


@dataclass
class PaymentMix:
    cash: float = 0.0
    card: float = 0.0
    voucher: float = 0.0
    other: float = 0.0
    total: float = 0.0


@dataclass
class MonthForecast:
    year: int
    month: int
    days_total: int
    days_elapsed: int
    revenue_fact: float = 0.0
    revenue_projected: float = 0.0
    margin_fact: float = 0.0
    margin_projected: float = 0.0
    vat_payable_projected: float = 0.0
    missing_docs: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    daily_avg_revenue: float = 0.0


# ─── сервис ───────────────────────────────────────────────────────────

class AnalyticsService:
    """Единый источник аналитических расчётов."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _load_docs(self, f: PeriodFilter, doc_types: tuple[str, ...] | None = None) -> list[AccountingDoc]:
        stmt = select(AccountingDoc).where(
            AccountingDoc.company_id == f.company_id,
            AccountingDoc.date >= f.date_from.isoformat(),
            AccountingDoc.date <= f.date_to.isoformat() + "T23:59:59",
        )
        if doc_types:
            stmt = stmt.where(AccountingDoc.doc_type.in_(doc_types))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _load_shifts(self, f: PeriodFilter) -> list[FuelShift]:
        stmt = select(FuelShift).where(
            FuelShift.company_id == f.company_id,
            FuelShift.closed_at.is_not(None),
            FuelShift.closed_at >= datetime.combine(f.date_from, datetime.min.time()),
            FuelShift.closed_at <= datetime.combine(f.date_to, datetime.max.time()),
        )
        if f.station_id is not None:
            stmt = stmt.where(FuelShift.station_id == f.station_id)
        return list((await self.session.execute(stmt)).scalars().all())

    # ─── management: P&L ──────────────────────────────────────────────

    async def pnl(self, f: PeriodFilter, group_by: str = "station") -> dict[str, Any]:
        """P&L по группе:
          'station' — по станции (из FuelShift.station_id + AccountingDoc по company)
          'fuel'    — по виду топлива (из FuelPump.fuel_type)
          'month'   — по месяцам в периоде
        """
        orps = await self._load_docs(f, doc_types=("ОРП",))
        ptus = await self._load_docs(f, doc_types=("ПТУ",))
        shifts = await self._load_shifts(f)

        groups: dict[str, PnLLine] = defaultdict(lambda: PnLLine(label=""))
        # ─── выручка/себестоимость из проводок ОРП ─────────────────────
        for doc in orps:
            postings = _iter_postings(doc)
            rev_with_vat = sum(_posting_amount(p) for p in postings if _starts_with(_posting_kt(p), "90.01"))
            rev_vat = sum(_posting_amount(p) for p in postings if _starts_with(_posting_kt(p), "68.02") and _starts_with(_posting_dt(p), "90.03"))
            cogs = sum(_posting_amount(p) for p in postings if _starts_with(_posting_dt(p), "90.02"))
            # Fallback на amount шапки, если проводок нет
            if rev_with_vat == 0:
                rev_with_vat = float(doc.amount or 0.0)
                rev_vat = round(rev_with_vat * 22.0 / 122.0, 2) if rev_with_vat else 0.0

            if group_by == "month":
                d = _parse_date(doc.date) or f.date_from
                key = f"{d.year}-{d.month:02d}"
                label = f"{d.year}-{d.month:02d}"
            else:
                key = label = doc.organization_name or "Все ЮЛ"

            g = groups[key]
            g.label = label
            g.revenue += rev_with_vat
            g.revenue_net += rev_with_vat - rev_vat
            g.cogs += cogs
            g.docs_count += 1

        # ─── литры/станция-разбивка из FuelShift ───────────────────────
        station_ids = {s.station_id for s in shifts if s.station_id}
        stations_map: dict[uuid.UUID, FuelStation] = {}
        if station_ids:
            for st in (await self.session.execute(
                select(FuelStation).where(FuelStation.id.in_(station_ids))
            )).scalars().all():
                stations_map[st.id] = st

        if group_by == "station":
            for sh in shifts:
                st = stations_map.get(sh.station_id) if sh.station_id else None
                key = label = (st.name if st else "АЗС без привязки")
                g = groups[key]
                g.label = label
                g.liters += float(sh.total_liters or 0.0)
                # Если ОРП ещё не создан для смены — учтём её в выручке fallback
                # (отметка по флагу: shift.status == 'pending' и нет docs_count)
                if not orps:
                    g.revenue += float(sh.total_amount or 0.0)
                    g.revenue_net += float(sh.total_amount or 0.0) * 100 / 122
        elif group_by == "fuel":
            # Литры/выручка по виду топлива из FuelPump
            shift_ids = [s.id for s in shifts]
            if shift_ids:
                pumps = (await self.session.execute(
                    select(FuelPump).where(FuelPump.shift_id.in_(shift_ids))
                )).scalars().all()
                fuel_agg: dict[str, dict[str, float]] = defaultdict(lambda: {"liters": 0.0, "amount": 0.0})
                for p in pumps:
                    ft = (p.fuel_type or "?").strip()
                    fuel_agg[ft]["liters"] += float(p.sales_volume or 0.0)
                    fuel_agg[ft]["amount"] += float(p.amount or 0.0)
                # Перезаписываем groups по топливу
                groups = defaultdict(lambda: PnLLine(label=""))
                for ft, a in fuel_agg.items():
                    g = groups[ft]
                    g.label = ft
                    g.liters = a["liters"]
                    g.revenue = a["amount"]
                    g.revenue_net = a["amount"] * 100 / 122
                # Себестоимость по топливу — без раскрытия проводок невозможно
                # точно отнести; даём пропорцию от общего COGS по выручке.
                total_amount = sum(g.revenue for g in groups.values())
                total_cogs = sum(sum(_posting_amount(p) for p in _iter_postings(d) if _starts_with(_posting_dt(p), "90.02")) for d in orps)
                if total_amount > 0 and total_cogs > 0:
                    for g in groups.values():
                        g.cogs = round(total_cogs * (g.revenue / total_amount), 2)

        # ─── финализация ───────────────────────────────────────────────
        result_lines: list[PnLLine] = []
        for g in groups.values():
            g.gross_margin = round(g.revenue_net - g.cogs, 2)
            g.gross_margin_pct = round(100 * g.gross_margin / g.revenue_net, 2) if g.revenue_net else 0.0
            g.revenue = round(g.revenue, 2)
            g.revenue_net = round(g.revenue_net, 2)
            g.cogs = round(g.cogs, 2)
            g.liters = round(g.liters, 2)
            result_lines.append(g)

        result_lines.sort(key=lambda x: -x.revenue)

        total = PnLLine(label="Итого")
        for g in result_lines:
            total.revenue += g.revenue
            total.revenue_net += g.revenue_net
            total.cogs += g.cogs
            total.gross_margin += g.gross_margin
            total.docs_count += g.docs_count
            total.liters += g.liters
        total.gross_margin_pct = round(100 * total.gross_margin / total.revenue_net, 2) if total.revenue_net else 0.0

        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "group_by": group_by,
            "lines": [
                {
                    "label": g.label,
                    "revenue": g.revenue,
                    "revenue_net": g.revenue_net,
                    "cogs": g.cogs,
                    "gross_margin": g.gross_margin,
                    "gross_margin_pct": g.gross_margin_pct,
                    "docs_count": g.docs_count,
                    "liters": g.liters,
                } for g in result_lines
            ],
            "totals": {
                "revenue": round(total.revenue, 2),
                "revenue_net": round(total.revenue_net, 2),
                "cogs": round(total.cogs, 2),
                "gross_margin": round(total.gross_margin, 2),
                "gross_margin_pct": total.gross_margin_pct,
                "docs_count": total.docs_count,
                "liters": round(total.liters, 2),
            },
            "ptu_count": len(ptus),
            "shifts_count": len(shifts),
        }

    async def payment_mix(self, f: PeriodFilter) -> dict[str, Any]:
        """Маркетинговый разрез: средний чек + доли cash/card/voucher по FuelShift.
        Это «как продавалось» (с точки зрения АЗС), а не «как пришло в 1С»."""
        shifts = await self._load_shifts(f)
        mix = PaymentMix()
        for s in shifts:
            mix.cash += float(s.cash or 0.0)
            mix.card += float(s.card or 0.0)
            mix.voucher += float(s.voucher or 0.0)
        mix.total = mix.cash + mix.card + mix.voucher
        # Other = total_amount − (cash+card+voucher) — может быть отрицательным
        # при ошибках разбивки; нормализуем до >= 0.
        total_amount = sum(float(s.total_amount or 0.0) for s in shifts)
        mix.other = round(max(0.0, total_amount - mix.total), 2)
        mix.total = round(mix.total + mix.other, 2)
        # Средний чек = total_amount / receipts_count (нет в FuelShift отдельно — считаем через смены)
        avg_receipt = round(total_amount / max(1, len(shifts)), 2) if shifts else 0.0
        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "shifts_count": len(shifts),
            "total_amount": round(total_amount, 2),
            "avg_per_shift": avg_receipt,
            "breakdown": {
                "cash": round(mix.cash, 2),
                "card": round(mix.card, 2),
                "voucher": round(mix.voucher, 2),
                "other": mix.other,
            },
            "shares_pct": {
                "cash": round(100 * mix.cash / mix.total, 2) if mix.total else 0.0,
                "card": round(100 * mix.card / mix.total, 2) if mix.total else 0.0,
                "voucher": round(100 * mix.voucher / mix.total, 2) if mix.total else 0.0,
                "other": round(100 * mix.other / mix.total, 2) if mix.total else 0.0,
            },
        }

    # ─── management: топливный баланс ─────────────────────────────────

    async def fuel_balance(self, f: PeriodFilter, group_by: str = "station") -> dict[str, Any]:
        """Топливный баланс сети АЗС по резервуарам (FuelTank):
          недостача_смены = (остаток_нач + приход_ТТН − реализация) − остаток_факт
          сумма по сменам/резервуарам за период = потери учёта/хранения.
        group_by = station | fuel | station_fuel.
        """
        shifts = await self._load_shifts(f)
        shift_station = {s.id: s.station_id for s in shifts}
        shift_ids = [s.id for s in shifts]

        station_ids = {s.station_id for s in shifts if s.station_id}
        stations_map: dict[uuid.UUID, FuelStation] = {}
        if station_ids:
            for st in (await self.session.execute(
                select(FuelStation).where(FuelStation.id.in_(station_ids))
            )).scalars().all():
                stations_map[st.id] = st

        tanks: list[FuelTank] = []
        if shift_ids:
            tanks = list((await self.session.execute(
                select(FuelTank).where(FuelTank.shift_id.in_(shift_ids))
            )).scalars().all())

        agg: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"label": "", "start": 0.0, "receipts": 0.0, "sales": 0.0, "end": 0.0, "loss": 0.0, "tanks": 0}
        )
        for t in tanks:
            st = stations_map.get(shift_station.get(t.shift_id)) if t.shift_id else None
            station_name = st.name if st else "АЗС без привязки"
            fuel = (t.fuel_type or (str(t.fuel_code) if t.fuel_code is not None else "—")).strip() or "—"
            if group_by == "fuel":
                key = label = fuel
            elif group_by == "station_fuel":
                key = f"{station_name}|{fuel}"
                label = f"{station_name} · {fuel}"
            else:
                key = label = station_name

            vs = float(t.volume_start or 0.0)
            ve = float(t.volume_end or 0.0)
            vr = float(t.volume_received or 0.0)
            sl = float(t.sales or 0.0)

            g = agg[key]
            g["label"] = label
            g["start"] += vs
            g["receipts"] += vr
            g["sales"] += sl
            g["end"] += ve
            g["loss"] += (vs + vr - sl) - ve  # недостача(+)/излишек(−) смены
            g["tanks"] += 1

        def _line(g: dict[str, Any]) -> dict[str, Any]:
            throughput = g["start"] + g["receipts"]
            loss = g["loss"]
            return {
                "label": g["label"],
                "balance_start_liters": round(g["start"], 1),
                "receipts_liters": round(g["receipts"], 1),
                "sales_liters": round(g["sales"], 1),
                "balance_end_liters": round(g["end"], 1),
                "loss_liters": round(loss, 1),
                "loss_pct": round(loss / throughput * 100, 3) if throughput else 0.0,
                "tanks_count": g["tanks"],
            }

        lines = sorted((_line(g) for g in agg.values()), key=lambda x: -abs(x["loss_liters"]))

        tot = {"start": 0.0, "receipts": 0.0, "sales": 0.0, "end": 0.0, "loss": 0.0, "tanks": 0}
        for g in agg.values():
            for k in ("start", "receipts", "sales", "end", "loss", "tanks"):
                tot[k] += g[k]
        tot_through = tot["start"] + tot["receipts"]
        totals = {
            "label": "Итого",
            "balance_start_liters": round(tot["start"], 1),
            "receipts_liters": round(tot["receipts"], 1),
            "sales_liters": round(tot["sales"], 1),
            "balance_end_liters": round(tot["end"], 1),
            "loss_liters": round(tot["loss"], 1),
            "loss_pct": round(tot["loss"] / tot_through * 100, 3) if tot_through else 0.0,
            "tanks_count": tot["tanks"],
        }

        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "group_by": group_by,
            "lines": lines,
            "totals": totals,
            "shifts_count": len(shifts),
        }

    # ─── management: каналы продаж ────────────────────────────────────

    async def sales_channels(self, f: PeriodFilter) -> dict[str, Any]:
        """Разрез продаж по каналам оплаты (FuelShiftSale.payment_channel):
        объём, сумма, доля, ср. цена ₽/л. Комиссии/категории — на клиенте (конфиг).
        """
        shifts = await self._load_shifts(f)
        shift_ids = [s.id for s in shifts]

        sales: list[FuelShiftSale] = []
        if shift_ids:
            sales = list((await self.session.execute(
                select(FuelShiftSale).where(FuelShiftSale.shift_id.in_(shift_ids))
            )).scalars().all())

        agg: dict[str, dict[str, float]] = defaultdict(lambda: {"liters": 0.0, "amount": 0.0, "count": 0})
        for s in sales:
            ch = (s.payment_channel or "—").strip() or "—"
            g = agg[ch]
            g["liters"] += float(s.liters or 0.0)
            g["amount"] += float(s.amount or 0.0)
            g["count"] += 1

        total_amount = sum(g["amount"] for g in agg.values())
        total_liters = sum(g["liters"] for g in agg.values())

        lines = [
            {
                "channel": ch,
                "label": normalize_default("paytype", ch),
                "liters": round(g["liters"], 1),
                "amount": round(g["amount"], 2),
                "count": int(g["count"]),
                "avg_price": round(g["amount"] / g["liters"], 2) if g["liters"] else 0.0,
                "share_pct": round(g["amount"] / total_amount * 100, 2) if total_amount else 0.0,
            }
            for ch, g in agg.items()
        ]
        lines.sort(key=lambda x: -x["amount"])

        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "lines": lines,
            "total_amount": round(total_amount, 2),
            "total_liters": round(total_liters, 1),
            "shifts_count": len(shifts),
        }

    # ─── management (energy): зарядные сессии ЭЗС ──────────────────────

    def _cs_group_col(self, group_by: str):
        S = ChargeSession
        if group_by == "region":
            return func.coalesce(S.region, "—")
        if group_by == "connector":
            return func.coalesce(S.connector_type, "—")
        if group_by == "user_type":
            return func.coalesce(S.user_type, "—")
        if group_by == "charge_type":
            return func.coalesce(S.charge_type, "—")
        if group_by == "result":
            return func.coalesce(S.result, "—")
        if group_by == "tariff":
            return S.tariff
        if group_by == "hour":
            return func.extract("hour", S.started_at)
        if group_by == "weekday":
            return func.extract("isodow", S.started_at)  # 1=Пн .. 7=Вс
        if group_by == "day":
            return func.to_char(S.started_at, "YYYY-MM-DD")
        if group_by == "week":
            # понедельник недели (как date_trunc('week')); лейбл сортируем лексически
            return func.to_char(func.date_trunc("week", S.started_at), "YYYY-MM-DD")
        if group_by == "decade":
            # декада = треть месяца (1–10 / 11–20 / 21–конец) → "YYYY-MM-Дn"
            day = func.extract("day", S.started_at)
            dec = case((day <= 10, 1), (day <= 20, 2), else_=3)
            return func.concat(func.to_char(S.started_at, "YYYY-MM"), "-Д", dec)
        if group_by == "month":
            return func.to_char(S.started_at, "YYYY-MM")
        if group_by == "quarter":
            return func.concat(func.to_char(S.started_at, "YYYY"), "-Q", func.to_char(S.started_at, "Q"))
        # station: уникальна по КОДУ (одно имя часто у многих ЭЗС, напр. «СНК» у 60 станций),
        # поэтому в ключ включаем код — иначе одноимённые станции схлопываются. Подпись «Имя (код)».
        return func.concat(func.coalesce(S.station_name, "Станция"), " (", func.coalesce(S.station_code, "—"), ")")

    @staticmethod
    def _dim_cond(dim_by, dim_val):
        """Точечный фильтр по значению разреза (drill-down строки)."""
        if not dim_by or dim_val is None:
            return None
        S = ChargeSession
        cols = {"station": S.station_code, "region": S.region, "connector": S.connector_type,
                "user_type": S.user_type, "charge_type": S.charge_type, "result": S.result}
        if dim_by in cols:
            return cols[dim_by] == dim_val
        if dim_by == "tariff":
            try:
                return S.tariff == float(str(dim_val).replace(",", "."))
            except (ValueError, TypeError):
                return None
        return None

    def _cs_conds(self, company_id, date_from, date_to, station_codes=None, regions=None, dim_by=None, dim_val=None):
        """Условия WHERE для сессий: период + сужение по станциям/регионам + точечный dim-фильтр."""
        S = ChargeSession
        lo = datetime.combine(date_from, datetime.min.time())
        hi = datetime.combine(date_to, datetime.max.time())
        conds = [S.company_id == company_id, S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi]
        if station_codes:
            conds.append(S.station_code.in_(station_codes))
        if regions:
            conds.append(S.region.in_(regions))
        dc = self._dim_cond(dim_by, dim_val)
        if dc is not None:
            conds.append(dc)
        return conds

    @staticmethod
    def _port_key():
        """Физический порт = станция + номер коннектора (для распределения на порты)."""
        S = ChargeSession
        return func.concat(func.coalesce(S.station_code, ""), "|", func.coalesce(S.connector_no, ""))

    async def _cs_aggregate(self, company_id, date_from, date_to, group_by: str,
                            station_codes=None, regions=None, dim_by=None, dim_val=None) -> list[Any]:
        S = ChargeSession
        gcol = self._cs_group_col(group_by)
        stmt = select(
            gcol.label("g"),
            func.count().label("cnt"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            func.coalesce(func.sum(S.amount), 0).label("amount"),
            func.coalesce(func.sum(S.duration_min), 0).label("duration"),
            func.coalesce(func.sum(case((S.result == "Complete", 1), else_=0)), 0).label("success"),
            func.coalesce(func.sum(case((S.paid_at.is_not(None), 1), else_=0)), 0).label("paid"),
            func.count(distinct(self._port_key())).label("ports"),
        ).where(*self._cs_conds(company_id, date_from, date_to, station_codes, regions, dim_by, dim_val)).group_by(gcol)
        return list((await self.session.execute(stmt)).all())

    async def _cs_ports(self, company_id, date_from, date_to, station_codes=None, regions=None, dim_by=None, dim_val=None) -> int:
        """Число физических портов сети (distinct станция+коннектор) за период/сужение."""
        stmt = select(func.count(distinct(self._port_key()))).where(
            *self._cs_conds(company_id, date_from, date_to, station_codes, regions, dim_by, dim_val))
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    @staticmethod
    def _cs_label(group_by: str, g) -> str:
        if g is None:
            return "—"
        if group_by == "hour":
            try:
                return f"{int(float(g)):02d}:00"
            except (ValueError, TypeError):
                return str(g)
        if group_by == "tariff":
            return f"{float(g):g} ₽/кВтч"
        if group_by == "decade":  # "YYYY-MM-Дn" → "Дn MM.YYYY"
            try:
                ym, dn = str(g).rsplit("-Д", 1)
                y, m = ym.split("-")
                return f"Д{dn} {m}.{y}"
            except ValueError:
                return str(g)
        if group_by == "month":  # "YYYY-MM" → "MM.YYYY"
            try:
                y, m = str(g).split("-")[:2]
                return f"{m}.{y}"
            except (ValueError, IndexError):
                return str(g)
        if group_by == "quarter":  # "YYYY-Qn" → "Qn YYYY"
            try:
                y, q = str(g).split("-Q")
                return f"Q{q} {y}"
            except ValueError:
                return str(g)
        return str(g)

    def _cs_metrics(self, group_by: str, r, period_days: int = 0) -> dict[str, Any]:
        cnt = int(r.cnt); energy = float(r.energy); amount = float(r.amount)
        dur = float(r.duration); success = int(r.success)
        paid = int(getattr(r, "paid", 0) or 0)
        ports = int(getattr(r, "ports", 0) or 0)
        port_min = ports * period_days * 1440  # доступные порт-минуты за период
        return {
            "label": self._cs_label(group_by, r.g),
            "sessions": cnt,
            "energy_kwh": round(energy, 1),
            "amount": round(amount, 2),
            "avg_check": round(amount / cnt, 2) if cnt else 0.0,
            "avg_energy": round(energy / cnt, 2) if cnt else 0.0,
            "avg_duration_min": round(dur / cnt, 1) if cnt else 0.0,
            "success_pct": round(success / cnt * 100, 1) if cnt else 0.0,
            "price_per_kwh": round(amount / energy, 2) if energy else 0.0,
            # порт-нормированные метрики (валидны для физических разрезов: станция/коннектор/регион)
            "ports": ports,
            "utilization_pct": round(dur / port_min * 100, 1) if port_min else 0.0,
            "throughput_port": round(energy / ports / period_days, 1) if (ports and period_days) else 0.0,
            "revenue_port": round(amount / ports, 0) if ports else 0.0,
            "unpaid_pct": round((cnt - paid) / cnt * 100, 1) if cnt else 0.0,
            "_dur_sum": dur, "_success": success, "_paid": paid,
        }

    async def _cs_aggregate_2d(
        self, company_id, date_from, date_to, bucket_by: str, series_by: str | None,
        station_codes=None, regions=None, dim_by=None, dim_val=None,
    ) -> list[Any]:
        """Сырые суммы по (бакет [× серия]). series_by=None → только колонка бакета."""
        S = ChargeSession
        bcol = self._cs_group_col(bucket_by)
        sel = [
            bcol.label("b"),
            func.count().label("cnt"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            func.coalesce(func.sum(S.amount), 0).label("amount"),
            func.coalesce(func.sum(S.duration_min), 0).label("duration"),
            func.coalesce(func.sum(case((S.result == "Complete", 1), else_=0)), 0).label("success"),
        ]
        groups = [bcol]
        if series_by:
            scol = self._cs_group_col(series_by)
            sel.insert(1, scol.label("s"))
            groups.append(scol)
        stmt = select(*sel).where(
            *self._cs_conds(company_id, date_from, date_to, station_codes, regions, dim_by, dim_val)
        ).group_by(*groups)
        return list((await self.session.execute(stmt)).all())

    _CS_METRICS = ("sessions", "energy_kwh", "amount", "avg_check", "avg_energy",
                   "avg_duration_min", "success_pct", "price_per_kwh")

    @staticmethod
    def _cs_metric_from_sums(metric: str, cnt, energy, amount, dur, success) -> float:
        """Значение метрики из сырых сумм ячейки (guard-деление)."""
        cnt = int(cnt); energy = float(energy); amount = float(amount)
        dur = float(dur); success = int(success)
        m = {
            "sessions": cnt, "energy_kwh": round(energy, 1), "amount": round(amount, 2),
            "avg_check": amount / cnt if cnt else 0.0,
            "avg_energy": energy / cnt if cnt else 0.0,
            "avg_duration_min": dur / cnt if cnt else 0.0,
            "success_pct": success / cnt * 100 if cnt else 0.0,
            "price_per_kwh": amount / energy if energy else 0.0,
        }
        return round(float(m.get(metric, 0.0)), 2)

    @staticmethod
    def _cs_is_ratio(metric: str) -> bool:
        """Ratio-метрики: пустой бакет → null (не 0), чтобы линия не проваливалась."""
        return metric in ("avg_check", "avg_energy", "avg_duration_min", "success_pct", "price_per_kwh")

    @staticmethod
    def _cs_bucket_axis(date_from, date_to, bucket: str) -> list[str]:
        """Полная ось бакетов (формат совпадает с _cs_group_col) — заполнение пустых."""
        out: list[str] = []
        if bucket == "day":
            d = date_from
            while d <= date_to:
                out.append(d.strftime("%Y-%m-%d")); d += timedelta(days=1)
        elif bucket == "week":
            d = date_from - timedelta(days=date_from.weekday())  # выравнивание на понедельник
            while d <= date_to:
                out.append(d.strftime("%Y-%m-%d")); d += timedelta(days=7)
        elif bucket == "decade":
            y, m = date_from.year, date_from.month
            while (y, m) <= (date_to.year, date_to.month):
                for n in (1, 2, 3):
                    out.append(f"{y}-{m:02d}-Д{n}")
                m += 1
                if m > 12:
                    y += 1; m = 1
        elif bucket == "month":
            y, m = date_from.year, date_from.month
            while (y, m) <= (date_to.year, date_to.month):
                out.append(f"{y}-{m:02d}")
                m += 1
                if m > 12:
                    y += 1; m = 1
        else:  # quarter
            y, q = date_from.year, (date_from.month - 1) // 3 + 1
            endy, endq = date_to.year, (date_to.month - 1) // 3 + 1
            while (y, q) <= (endy, endq):
                out.append(f"{y}-Q{q}")
                q += 1
                if q > 4:
                    y += 1; q = 1
        return out

    async def charge_sessions(self, f: PeriodFilter, group_by: str = "station") -> dict[str, Any]:
        """Разрез зарядных сессий ЭЗС: выручка/энергия/сессии/ср.чек/успех по группе."""
        period_days = (f.date_to - f.date_from).days + 1
        rows = await self._cs_aggregate(f.company_id, f.date_from, f.date_to, group_by, f.station_codes, f.regions, f.dim_by, f.dim_val)
        lines = [self._cs_metrics(group_by, r, period_days) for r in rows]
        total_amount = sum(l["amount"] for l in lines)
        for l in lines:
            l["share_pct"] = round(l["amount"] / total_amount * 100, 2) if total_amount else 0.0
        if group_by in ("hour", "day"):
            lines.sort(key=lambda x: x["label"])
        else:
            lines.sort(key=lambda x: -x["amount"])

        ts = sum(l["sessions"] for l in lines)
        te = sum(l["energy_kwh"] for l in lines)
        td = sum(l["_dur_sum"] for l in lines)
        tsucc = sum(l["_success"] for l in lines)
        tpaid = sum(l["_paid"] for l in lines)
        # порты сети — distinct (не сумма строк: для нефизических разрезов порт делят сегменты)
        net_ports = await self._cs_ports(f.company_id, f.date_from, f.date_to, f.station_codes, f.regions, f.dim_by, f.dim_val)
        port_min = net_ports * period_days * 1440
        totals = {
            "label": "Итого", "sessions": ts, "energy_kwh": round(te, 1), "amount": round(total_amount, 2),
            "avg_check": round(total_amount / ts, 2) if ts else 0.0,
            "avg_energy": round(te / ts, 2) if ts else 0.0,
            "avg_duration_min": round(td / ts, 1) if ts else 0.0,
            "success_pct": round(tsucc / ts * 100, 1) if ts else 0.0,
            "price_per_kwh": round(total_amount / te, 2) if te else 0.0,
            "ports": net_ports,
            "utilization_pct": round(td / port_min * 100, 1) if port_min else 0.0,
            "throughput_port": round(te / net_ports / period_days, 1) if (net_ports and period_days) else 0.0,
            "revenue_port": round(total_amount / net_ports, 0) if net_ports else 0.0,
            "unpaid_pct": round((ts - tpaid) / ts * 100, 1) if ts else 0.0,
            "share_pct": 100.0,
        }
        for l in lines:
            l.pop("_dur_sum", None); l.pop("_success", None); l.pop("_paid", None)
        return {"period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
                "group_by": group_by, "lines": lines, "totals": totals, "period_days": period_days}

    async def charge_sessions_compare(
        self, company_id, a_from, a_to, b_from, b_to, group_by: str = "station",
    ) -> dict[str, Any]:
        """Сравнение двух периодов по группе (обычно station): Δ выручка/энергия/сессии."""
        rows_a = await self._cs_aggregate(company_id, a_from, a_to, group_by)
        rows_b = await self._cs_aggregate(company_id, b_from, b_to, group_by)
        ma = {self._cs_label(group_by, r.g): r for r in rows_a}
        mb = {self._cs_label(group_by, r.g): r for r in rows_b}
        labels = sorted(set(ma) | set(mb))

        def val(r, attr):
            return float(getattr(r, attr)) if r is not None else 0.0

        lines = []
        for lb in labels:
            ra, rb = ma.get(lb), mb.get(lb)
            a_amt, b_amt = val(ra, "amount"), val(rb, "amount")
            a_en, b_en = val(ra, "energy"), val(rb, "energy")
            a_ss, b_ss = int(val(ra, "cnt")), int(val(rb, "cnt"))
            lines.append({
                "label": lb,
                "a_amount": round(a_amt, 2), "b_amount": round(b_amt, 2),
                "delta_amount": round(b_amt - a_amt, 2),
                "delta_pct": round((b_amt - a_amt) / a_amt * 100, 1) if a_amt else (100.0 if b_amt else 0.0),
                "a_energy": round(a_en, 1), "b_energy": round(b_en, 1),
                "delta_energy": round(b_en - a_en, 1),
                "a_sessions": a_ss, "b_sessions": b_ss, "delta_sessions": b_ss - a_ss,
            })
        lines.sort(key=lambda x: -abs(x["delta_amount"]))
        return {
            "period_a": {"from": a_from.isoformat(), "to": a_to.isoformat()},
            "period_b": {"from": b_from.isoformat(), "to": b_to.isoformat()},
            "group_by": group_by, "lines": lines,
            "totals": {
                "a_amount": round(sum(l["a_amount"] for l in lines), 2),
                "b_amount": round(sum(l["b_amount"] for l in lines), 2),
                "delta_amount": round(sum(l["delta_amount"] for l in lines), 2),
                "a_sessions": sum(l["a_sessions"] for l in lines),
                "b_sessions": sum(l["b_sessions"] for l in lines),
            },
        }

    async def charge_timeseries(
        self, f: PeriodFilter, bucket: str = "day",
        series_by: str | None = None, metric: str = "amount", top_n: int = 5,
    ) -> dict[str, Any]:
        """Динамика метрики по бакетам времени; series_by → multi-series (топ-N + «Прочие»)."""
        rows = await self._cs_aggregate_2d(f.company_id, f.date_from, f.date_to, bucket, series_by, f.station_codes, f.regions, f.dim_by, f.dim_val)
        axis = self._cs_bucket_axis(f.date_from, f.date_to, bucket)
        empty = None if self._cs_is_ratio(metric) else 0
        base = {"bucket": bucket, "metric": metric,
                "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()}}

        if not series_by:
            by = {r.b: r for r in rows}
            data = [{"bucket": b,
                     "value": (self._cs_metric_from_sums(metric, by[b].cnt, by[b].energy, by[b].amount, by[b].duration, by[b].success)
                               if b in by else empty)} for b in axis]
            return {**base, "series": ["value"], "data": data}

        # multi-series: топ-N серий по суммарной выручке, остальное сворачиваем в «Прочие»
        tot: dict[str, float] = defaultdict(float)
        for r in rows:
            tot[self._cs_label(series_by, r.s)] += float(r.amount)
        top = [s for s, _ in sorted(tot.items(), key=lambda kv: -kv[1])[:top_n]]
        top_set = set(top)
        has_other = len(tot) > len(top_set)
        # сырые суммы по (бакет × эффективная серия) — «Прочие» суммируем ДО метрики
        cell: dict[tuple, list] = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0])  # cnt,energy,amount,dur,success
        for r in rows:
            lbl = self._cs_label(series_by, r.s)
            key = lbl if lbl in top_set else "Прочие"
            c = cell[(r.b, key)]
            c[0] += int(r.cnt); c[1] += float(r.energy); c[2] += float(r.amount)
            c[3] += float(r.duration); c[4] += int(r.success)
        series = top + (["Прочие"] if has_other else [])
        data = []
        for b in axis:
            row: dict[str, Any] = {"bucket": b}
            for s in series:
                c = cell.get((b, s))
                row[s] = self._cs_metric_from_sums(metric, *c) if c else empty
            data.append(row)
        return {**base, "series": series, "data": data}

    async def charge_heatmap(self, f: PeriodFilter, metric: str = "sessions") -> dict[str, Any]:
        """Матрица загрузки час (0–23) × день недели (1=Пн..7=Вс) для heatmap."""
        rows = await self._cs_aggregate_2d(
            f.company_id, f.date_from, f.date_to, "hour", "weekday", f.station_codes, f.regions)
        cells = []
        for r in rows:
            try:
                h = int(float(r.b)); wd = int(float(r.s))
            except (ValueError, TypeError):
                continue
            cells.append({
                "hour": h, "weekday": wd,
                "value": self._cs_metric_from_sums(metric, r.cnt, r.energy, r.amount, r.duration, r.success),
            })
        return {"metric": metric, "cells": cells,
                "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()}}

    async def charge_sessions_compare_multi(
        self, company_id, periods: list[tuple[date, date]],
        group_by: str = "station", metric: str = "amount",
        station_codes=None, regions=None,
    ) -> dict[str, Any]:
        """Сравнение N периодов (2–4) по разрезу: значения метрики каждого + дельты."""
        maps: list[dict[str, Any]] = []
        totals: list[float] = []
        for pf, pt in periods:
            rows = await self._cs_aggregate(company_id, pf, pt, group_by, station_codes, regions)
            maps.append({self._cs_label(group_by, r.g): r for r in rows})
            # total метрики за период из сырых сумм всех групп (корректно для ratio-метрик)
            tc = sum(int(r.cnt) for r in rows)
            te = sum(float(r.energy) for r in rows)
            ta = sum(float(r.amount) for r in rows)
            tdur = sum(float(r.duration) for r in rows)
            tsucc = sum(int(r.success) for r in rows)
            totals.append(self._cs_metric_from_sums(metric, tc, te, ta, tdur, tsucc))
        labels = sorted(set().union(*[set(m) for m in maps])) if maps else []

        def mv(m, lb):
            r = m.get(lb)
            if r is None:
                return None if self._cs_is_ratio(metric) else 0
            return self._cs_metric_from_sums(metric, r.cnt, r.energy, r.amount, r.duration, r.success)

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
            "periods": [{"from": pf.isoformat(), "to": pt.isoformat()} for pf, pt in periods],
            "group_by": group_by, "metric": metric, "lines": lines,
            "totals": {"values": [round(t, 2) for t in totals]},
        }

    @staticmethod
    def _cs_interval(bucket: str, key: str) -> dict[str, str]:
        """Границы и подпись интервала по его ключу (из _cs_group_col/_cs_bucket_axis)."""
        try:
            if bucket == "day":
                return {"key": key, "from": key, "to": key, "label": key[5:]}
            if bucket == "week":
                d = date.fromisoformat(key)
                end = d + timedelta(days=6)
                return {"key": key, "from": key, "to": end.isoformat(),
                        "label": f"{d.strftime('%d.%m')}–{end.strftime('%d.%m')}"}
            if bucket == "decade":
                ym, dn = key.rsplit("-Д", 1)
                y, m = (int(x) for x in ym.split("-"))
                n = int(dn)
                start_day = 1 + (n - 1) * 10
                end_day = n * 10 if n < 3 else calendar.monthrange(y, m)[1]
                return {"key": key, "from": date(y, m, start_day).isoformat(),
                        "to": date(y, m, end_day).isoformat(), "label": f"Д{n} {m:02d}.{y}"}
            if bucket == "month":
                y, m = (int(x) for x in key.split("-"))
                last = calendar.monthrange(y, m)[1]
                return {"key": key, "from": date(y, m, 1).isoformat(),
                        "to": date(y, m, last).isoformat(), "label": f"{m:02d}.{y}"}
            # quarter "YYYY-Qn"
            ys, qs = key.split("-Q")
            y = int(ys); q = int(qs)
            sm = (q - 1) * 3 + 1; em = sm + 2
            last = calendar.monthrange(y, em)[1]
            return {"key": key, "from": date(y, sm, 1).isoformat(),
                    "to": date(y, em, last).isoformat(), "label": f"Q{q} {y}"}
        except (ValueError, IndexError):
            return {"key": key, "from": key, "to": key, "label": key}

    def _cs_slice_line(self, label: str, values: list, complete_idx: list[int] | None = None) -> dict[str, Any]:
        """Строка нарезки: значения по интервалам + дельты. Дельты считаются только по
        ПОЛНЫМ интервалам (complete_idx) — неполный последний/первый в сравнение не идёт."""
        idx = complete_idx if complete_idx else list(range(len(values)))
        last_i = idx[-1]
        prev_i = idx[-2] if len(idx) > 1 else None
        first = values[idx[0]] or 0
        last = values[last_i] or 0
        prev = (values[prev_i] if prev_i is not None else 0) or 0
        return {
            "label": label, "values": values,
            "delta_first": round(last - first, 2),
            "delta_prev": round(last - prev, 2),
            "delta_pct_prev": round((last - prev) / prev * 100, 1) if prev else (100.0 if last else 0.0),
        }

    async def charge_sessions_slice(
        self, f: PeriodFilter, bucket: str = "month",
        group_by: str | None = None, metric: str = "amount", top_n: int = 8,
    ) -> dict[str, Any]:
        """Нарезка периода на интервалы (bucket) и сравнение по разрезу (group_by).
        Строки = разрез (или «Вся сеть»), колонки = интервалы. Один SQL-проход."""
        rows = await self._cs_aggregate_2d(f.company_id, f.date_from, f.date_to, bucket, group_by, f.station_codes, f.regions, f.dim_by, f.dim_val)
        axis = self._cs_bucket_axis(f.date_from, f.date_to, bucket)
        # интервалы + пометка «неполный» (границы выходят за пределы заданного периода)
        intervals = []
        for b in axis:
            iv = self._cs_interval(bucket, b)
            iv["partial"] = (date.fromisoformat(iv["from"]) < f.date_from) or (date.fromisoformat(iv["to"]) > f.date_to)
            intervals.append(iv)
        complete_idx = [i for i, iv in enumerate(intervals) if not iv["partial"]]
        empty = None if self._cs_is_ratio(metric) else 0

        # «Вся сеть» по интервалам (для totals и режима без разреза) — из сырых сумм
        net: dict[str, list] = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0])
        for r in rows:
            c = net[r.b]
            c[0] += int(r.cnt); c[1] += float(r.energy); c[2] += float(r.amount)
            c[3] += float(r.duration); c[4] += int(r.success)
        net_values = [self._cs_metric_from_sums(metric, *net[b]) if b in net else empty for b in axis]

        if not group_by:
            lines = [self._cs_slice_line("Вся сеть", net_values, complete_idx)]
        else:
            tot: dict[str, float] = defaultdict(float)
            for r in rows:
                tot[self._cs_label(group_by, r.s)] += float(r.amount)
            top = [s for s, _ in sorted(tot.items(), key=lambda kv: -kv[1])[:top_n]]
            top_set = set(top)
            has_other = len(tot) > len(top_set)
            cell: dict[tuple, list] = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0])
            for r in rows:
                lbl = self._cs_label(group_by, r.s)
                key = lbl if lbl in top_set else "Прочие"
                c = cell[(key, r.b)]
                c[0] += int(r.cnt); c[1] += float(r.energy); c[2] += float(r.amount)
                c[3] += float(r.duration); c[4] += int(r.success)
            series = top + (["Прочие"] if has_other else [])
            lines = []
            for s in series:
                values = [self._cs_metric_from_sums(metric, *cell[(s, b)]) if (s, b) in cell else empty for b in axis]
                lines.append(self._cs_slice_line(s, values, complete_idx))

        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "bucket": bucket, "metric": metric, "group_by": group_by or "__net__",
            "intervals": intervals, "lines": lines,
            "totals": {"values": net_values},
        }

    async def charge_dimensions(self, company_id) -> dict[str, Any]:
        """Справочник для фильтра раздела: станции ЭЗС (код+имя) и регионы компании."""
        S = ChargeSession
        st_rows = (await self.session.execute(
            select(S.station_code, func.max(S.station_name).label("name"), func.count().label("cnt"))
            .where(S.company_id == company_id, S.station_code.is_not(None))
            .group_by(S.station_code).order_by(func.count().desc())
        )).all()
        rg_rows = (await self.session.execute(
            select(S.region, func.count().label("cnt"))
            .where(S.company_id == company_id, S.region.is_not(None))
            .group_by(S.region).order_by(S.region)
        )).all()
        return {
            "stations": [{"code": r.station_code, "name": r.name or r.station_code, "sessions": int(r.cnt)} for r in st_rows],
            "regions": [{"region": r.region, "sessions": int(r.cnt)} for r in rg_rows],
        }

    # ─── financial: cash flow + дебиторка/кредиторка ──────────────────

    async def cash_flow(self, f: PeriodFilter) -> dict[str, Any]:
        """Обороты по денежным счетам 50/51/57 за период."""
        docs = await self._load_docs(f)
        accounts: dict[str, CashFlowAccount] = {
            "50":    CashFlowAccount("50", "Касса"),
            "51":    CashFlowAccount("51", "Расчётные счета"),
            "52":    CashFlowAccount("52", "Валютные счета"),
            "57.03": CashFlowAccount("57.03", "Эквайринг"),
            "55":    CashFlowAccount("55", "Спец. счета"),
        }
        for doc in docs:
            for p in _iter_postings(doc):
                amt = _posting_amount(p)
                if amt <= 0:
                    continue
                dt, kt = _posting_dt(p), _posting_kt(p)
                for prefix, acc in accounts.items():
                    if _starts_with(dt, prefix):
                        acc.debit += amt
                    if _starts_with(kt, prefix):
                        acc.credit += amt

        for acc in accounts.values():
            acc.net = round(acc.debit - acc.credit, 2)
            acc.debit = round(acc.debit, 2)
            acc.credit = round(acc.credit, 2)

        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "accounts": [
                {"account": a.account, "name": a.name, "debit": a.debit, "credit": a.credit, "net": a.net}
                for a in accounts.values()
            ],
            "inflow_total": round(sum(a.debit for a in accounts.values()), 2),
            "outflow_total": round(sum(a.credit for a in accounts.values()), 2),
            "net_total": round(sum(a.net for a in accounts.values()), 2),
        }

    async def payables_receivables(self, f: PeriodFilter) -> dict[str, Any]:
        """Дебиторка (62.01/62.Р) и кредиторка (60.01) — обороты по контрагентам."""
        docs = await self._load_docs(f)
        payables: dict[str, PayablesReceivables] = {}  # мы должны → 60.01
        receivables: dict[str, PayablesReceivables] = {}  # нам должны → 62.01/62.Р
        for doc in docs:
            cp = doc.counterparty_name or "—"
            inn = doc.counterparty_inn
            for p in _iter_postings(doc):
                amt = _posting_amount(p)
                if amt <= 0:
                    continue
                dt, kt = _posting_dt(p), _posting_kt(p)
                if _starts_with(dt, "60.01") or _starts_with(kt, "60.01"):
                    bucket = payables.setdefault(cp, PayablesReceivables(cp, inn))
                    if _starts_with(dt, "60.01"):
                        bucket.debit += amt
                    if _starts_with(kt, "60.01"):
                        bucket.credit += amt
                if _starts_with(dt, "62") or _starts_with(kt, "62"):
                    bucket = receivables.setdefault(cp, PayablesReceivables(cp, inn))
                    if _starts_with(dt, "62"):
                        bucket.debit += amt
                    if _starts_with(kt, "62"):
                        bucket.credit += amt
        for b in payables.values():
            b.balance = round(b.credit - b.debit, 2)  # пассивный остаток
            b.debit = round(b.debit, 2); b.credit = round(b.credit, 2)
        for b in receivables.values():
            b.balance = round(b.debit - b.credit, 2)  # активный остаток
            b.debit = round(b.debit, 2); b.credit = round(b.credit, 2)
        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "payables": sorted(
                [{"counterparty": b.counterparty, "inn": b.inn, "debit": b.debit, "credit": b.credit, "balance": b.balance}
                 for b in payables.values()],
                key=lambda x: -abs(x["balance"])
            ),
            "receivables": sorted(
                [{"counterparty": b.counterparty, "inn": b.inn, "debit": b.debit, "credit": b.credit, "balance": b.balance}
                 for b in receivables.values()],
                key=lambda x: -abs(x["balance"])
            ),
            "totals": {
                "payables_balance": round(sum(b.balance for b in payables.values()), 2),
                "receivables_balance": round(sum(b.balance for b in receivables.values()), 2),
            },
        }

    # ─── tax: НДС позиция ─────────────────────────────────────────────

    async def vat_position(self, f: PeriodFilter) -> dict[str, Any]:
        docs = await self._load_docs(f)
        pos = VatPosition()
        for doc in docs:
            for p in _iter_postings(doc):
                amt = _posting_amount(p)
                if amt <= 0:
                    continue
                dt, kt = _posting_dt(p), _posting_kt(p)
                # Исходящий: Дт 90.03 Кт 68.02 (выделение НДС из выручки розницы)
                # либо просто Кт 68.02 (B2B Реализация)
                if _starts_with(kt, "68.02"):
                    pos.output_vat += amt
                # Входящий: Дт 19.03 (приобретение)
                if _starts_with(dt, "19.03"):
                    pos.input_vat += amt
                # Выручка с НДС: Кт 90.01.*
                if _starts_with(kt, "90.01"):
                    pos.revenue_with_vat += amt
        pos.revenue_net = round(pos.revenue_with_vat - pos.output_vat, 2)
        pos.payable = round(pos.output_vat - pos.input_vat, 2)
        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "output_vat": round(pos.output_vat, 2),
            "input_vat": round(pos.input_vat, 2),
            "payable": pos.payable,
            "revenue_with_vat": round(pos.revenue_with_vat, 2),
            "revenue_net": pos.revenue_net,
            "effective_rate_pct": round(100 * pos.output_vat / pos.revenue_net, 2) if pos.revenue_net else 0.0,
        }

    async def profit_position(self, f: PeriodFilter) -> dict[str, Any]:
        """Налог на прибыль: оценка финрезультата за период.
        Прибыль до налогообложения ≈ Σ Кт 90.01 − Σ Дт 90.02 − Σ Дт 90.03 − Σ Дт 44 − Σ Дт 91.*"""
        docs = await self._load_docs(f)
        rev = cogs = vat_out = sga = other_exp = other_inc = 0.0
        for doc in docs:
            for p in _iter_postings(doc):
                amt = _posting_amount(p)
                if amt <= 0:
                    continue
                dt, kt = _posting_dt(p), _posting_kt(p)
                if _starts_with(kt, "90.01"):     rev += amt
                if _starts_with(dt, "90.02"):     cogs += amt
                if _starts_with(dt, "90.03"):     vat_out += amt
                if _starts_with(dt, "44"):        sga += amt
                if _starts_with(dt, "91.02"):     other_exp += amt
                if _starts_with(kt, "91.01"):     other_inc += amt
        rev_net = rev - vat_out
        profit_before_tax = round(rev_net - cogs - sga + other_inc - other_exp, 2)
        # Ставка налога на прибыль для ОСН в РФ — 25% с 2025 г.
        # (до 2025 была 20%; с 2025 — 20% + 5% надбавка = 25%).
        rate = 25.0
        tax = round(max(0.0, profit_before_tax) * rate / 100, 2)
        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "revenue_net": round(rev_net, 2),
            "cogs": round(cogs, 2),
            "vat_output": round(vat_out, 2),
            "sga": round(sga, 2),
            "other_income": round(other_inc, 2),
            "other_expenses": round(other_exp, 2),
            "profit_before_tax": profit_before_tax,
            "tax_rate_pct": rate,
            "tax_estimated": tax,
            "net_profit": round(profit_before_tax - tax, 2),
        }

    # ─── forecast: закрытие месяца ────────────────────────────────────

    async def month_forecast(self, company_id: uuid.UUID, year: int, month: int, station_id: uuid.UUID | None = None) -> dict[str, Any]:
        first, last = _month_bounds(year, month)
        today = date.today()
        # Фактический период — от начала месяца до сегодня (или до конца месяца, если в прошлом)
        elapsed_to = min(today, last)
        days_total = (last - first).days + 1
        days_elapsed = max(1, (elapsed_to - first).days + 1)
        # Если месяц целиком в будущем — никаких фактов
        if today < first:
            days_elapsed = 0
        f_fact = PeriodFilter(company_id=company_id, date_from=first, date_to=elapsed_to, station_id=station_id)
        pnl_fact = await self.pnl(f_fact, group_by="station") if days_elapsed > 0 else {"totals": {"revenue": 0, "gross_margin": 0}}
        vat_fact = await self.vat_position(f_fact) if days_elapsed > 0 else {"payable": 0.0}

        rev_fact = pnl_fact["totals"]["revenue"]
        margin_fact = pnl_fact["totals"]["gross_margin"]
        vat_payable_fact = vat_fact.get("payable", 0.0)

        # Простая экстраполяция: среднее в день * дней всего
        rev_projected = round(rev_fact / days_elapsed * days_total, 2) if days_elapsed else 0.0
        margin_projected = round(margin_fact / days_elapsed * days_total, 2) if days_elapsed else 0.0
        vat_projected = round(vat_payable_fact / days_elapsed * days_total, 2) if days_elapsed else 0.0

        missing_docs: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []

        # ── Поиск отсутствующих ОРП по сменам ──
        shifts_in_period = (await self.session.execute(
            select(FuelShift).where(
                FuelShift.company_id == company_id,
                FuelShift.closed_at >= datetime.combine(first, datetime.min.time()),
                FuelShift.closed_at <= datetime.combine(elapsed_to, datetime.max.time()),
                FuelShift.status.in_(("pending", "verified")),
            )
        )).scalars().all() if days_elapsed > 0 else []

        orps = await self._load_docs(f_fact, doc_types=("ОРП",)) if days_elapsed > 0 else []
        # АЗС × день — есть ОРП?
        orp_keys: set[tuple[str, str]] = set()
        for d in orps:
            wh = (d.organization_name or "")
            dd = (d.date or "")[:10]
            orp_keys.add((wh, dd))

        # Проверяем смены, для которых нет ОРП
        no_orp_count = 0
        no_orp_amount = 0.0
        for sh in shifts_in_period:
            if not sh.closed_at:
                continue
            no_orp_count += 1  # упрощённо: каждая смена ждёт ОРП
            no_orp_amount += float(sh.total_amount or 0.0)
        if no_orp_count > 0:
            missing_docs.append({
                "type": "ОРП",
                "reason": "Смены закрыты, ОРП ещё не создан",
                "count": no_orp_count,
                "amount": round(no_orp_amount, 2),
            })

        # ── Незаквичированные ExportPacket ──
        queued = (await self.session.execute(
            select(ExportPacket).where(
                ExportPacket.company_id == company_id,
                ExportPacket.status.in_(("queued", "sent")),
            )
        )).scalars().all()
        if queued:
            by_kind: dict[str, int] = defaultdict(int)
            for q in queued:
                by_kind[q.kind] += 1
            for kind, n in by_kind.items():
                risks.append({
                    "severity": "warn",
                    "type": "queued_packets",
                    "message": f"{n} пакетов «{kind}» в очереди ожидают приёма расширением 1С",
                })

        # ── Расхождения в документах ──
        with_discrepancy = (await self.session.execute(
            select(func.count(AccountingDoc.id)).where(
                AccountingDoc.company_id == company_id,
                AccountingDoc.date >= first.isoformat(),
                AccountingDoc.date <= last.isoformat() + "T23:59:59",
                AccountingDoc.discrepancy_status.in_(("minor", "material", "rounding")),
            )
        )).scalar() or 0
        if with_discrepancy:
            risks.append({
                "severity": "warn",
                "type": "discrepancies",
                "message": f"{with_discrepancy} документов с расхождениями (rounding/minor/material)",
            })

        # ── Период уже закрыт? ──
        period_status = (await self.session.execute(
            select(Period).where(
                Period.company_id == company_id,
                Period.year == year,
                Period.month == month,
            )
        )).scalar_one_or_none()
        period_closed = period_status is not None and period_status.status == "closed"
        if period_closed:
            risks.append({
                "severity": "info",
                "type": "period_closed",
                "message": "Период уже закрыт в БП — изменения требуют сторнирования",
            })

        return {
            "year": year,
            "month": month,
            "days_total": days_total,
            "days_elapsed": days_elapsed,
            "daily_avg_revenue": round(rev_fact / days_elapsed, 2) if days_elapsed else 0.0,
            "revenue": {"fact": rev_fact, "projected": rev_projected},
            "margin": {"fact": margin_fact, "projected": margin_projected},
            "vat_payable": {"fact": vat_payable_fact, "projected": vat_projected},
            "missing_docs": missing_docs,
            "risks": risks,
            "period_closed": period_closed,
        }
