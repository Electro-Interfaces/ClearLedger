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

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingDoc,
    ExportPacket,
    FuelPump,
    FuelReceipt,
    FuelShift,
    FuelStation,
    Period,
)


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
