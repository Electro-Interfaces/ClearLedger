"""
Резолвер маппингов топливных каналов (оплаты + топливо) для компании.

Применяется на ingest STS-смены/ТТН: pay_type.name → канал оплаты + склад
(по PaymentMapping, матч подстрокой), service_code → номенклатура/плотность
(по FuelMapping). Воспроизводит TL_СозданиеДокументов.НайтиЗаписьМаппинга
и TL_Маппинг.НайтиНоменклатуруТоплива из расширения TradeLedger.cfe.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelMapping, PaymentChannel, PaymentMapping


class MappingContext:
    """Загруженные маппинги компании + резолверы. Создавать один на прогон."""

    def __init__(
        self,
        payment_mappings: list[PaymentMapping],
        channels: dict[str, PaymentChannel],
        fuel_by_code: dict[int, FuelMapping],
    ) -> None:
        self.payment_mappings = payment_mappings  # отсортированы по sort_order
        self.channels = channels                  # code -> PaymentChannel
        self.fuel_by_code = fuel_by_code          # service_code -> FuelMapping
        self.unmapped: set[str] = set()           # незамапленные pay_type.name

    def resolve_channel(self, pay_type_name: str | None) -> tuple[str | None, str | None]:
        """pay_type.name → (channel_code, warehouse_name).

        Матч — подстрока (lower), первое совпадение по sort_order.
        Возврат:
          (code, warehouse) — найден рабочий канал;
          ("", None)        — явный игнор (купоны/прокачка, channel_code пуст);
          (None, None)      — не найдено (имя добавлено в unmapped).
        """
        name = (pay_type_name or "").lower().strip()
        if name:
            for m in self.payment_mappings:
                if m.pattern and m.pattern in name:
                    if not m.channel_code:
                        return "", None  # явный игнор
                    ch = self.channels.get(m.channel_code)
                    warehouse = m.warehouse_override or (ch.warehouse_name if ch else None)
                    return m.channel_code, warehouse
        self.unmapped.add(pay_type_name or "")
        return None, None

    def fuel(self, service_code) -> FuelMapping | None:
        """service_code → FuelMapping (номенклатура т/л + плотность)."""
        try:
            return self.fuel_by_code.get(int(service_code))
        except (TypeError, ValueError):
            return None


# Значение-обрезка поля cost в sales-блоке STS (аудит L2 13.07.2026): на крупных
# сменах строка канала капится ровно на 1 000 000.00 при честных литрах
# (208/7041 СберБанк АИ-92: cost=1млн, наливы того же канала = 1 695 506,11).
STS_COST_CAP = 1_000_000.00
# Дубли-аналитика sales-блока: НЕ входят в psm.total (пробы 13.07.2026 — продажи
# по дисконтным картам уже включены в Наличные/СберБанк). Исключаются из сверки
# с psm при репейре обрезки. См. memory sts-pay-types-semantics.
_DUP_ANALYTIC_PAY = ("дисконт", "кред.рубл")


def build_sales_agg(raw_report: dict | None, ctx: "MappingContext") -> dict[tuple[str, int], dict]:
    """sales-блок STS-смены → {(канал, код топлива): {liters, amount, discount, warehouse}}.

    Единая логика ingest (fuel_router) и пересборки (renormalize_shift_sales):
    resolve_channel по имени вида оплаты; игноры/незамапленные пропускаются.

    Репейр обрезки STS_COST_CAP: если по топливу ровно одна строка с
    cost=1 000 000.00 и Σ sales топлива (без дублей-аналитики) меньше psm.total
    этого топлива — недостающая сумма доначисляется этой строке (Σ строк смены
    сходится с psm; сверено с наливами: 1 695 673 расч. vs 1 695 506 факт, ±скидки).
    """
    raw = raw_report or {}

    # psm.total по топливу — эталон суммы топлива в смене
    psm_by_fuel: dict[int, float] = {}
    for t in (raw.get("psm") or {}).get("total") or []:
        try:
            code = int((t.get("service") or {}).get("service_code"))
        except (TypeError, ValueError):
            continue
        psm_by_fuel[code] = psm_by_fuel.get(code, 0.0) + float((t.get("release") or {}).get("amount", 0) or 0)

    agg: dict[tuple[str, int], dict] = {}
    sales_by_fuel: dict[int, float] = {}  # Σ по топливу всех строк, входящих в psm
    capped: dict[int, list[dict]] = {}    # топливо → строки agg с обрезкой

    for sale in raw.get("sales") or []:
        pay_name = (sale.get("pay_type") or {}).get("name", "")
        is_dup = any(p in (pay_name or "").lower() for p in _DUP_ANALYTIC_PAY)
        channel, warehouse = ctx.resolve_channel(pay_name)
        for f in sale.get("fuel") or []:
            rel = f.get("release") or {}
            try:
                code = int((f.get("service") or {}).get("service_code"))
            except (TypeError, ValueError):
                continue
            cost = float(rel.get("cost", 0) or 0)
            if not is_dup:  # дубли-аналитика не входят в psm.total
                sales_by_fuel[code] = sales_by_fuel.get(code, 0.0) + cost
            if not channel:
                continue
            a = agg.setdefault((channel, code),
                               {"liters": 0.0, "amount": 0.0, "discount": 0.0, "warehouse": warehouse})
            a["liters"] += float(rel.get("volume", 0) or 0)
            a["amount"] += cost
            a["discount"] += float(rel.get("discount", 0) or 0)
            if cost == STS_COST_CAP:
                capped.setdefault(code, []).append(a)

    # Репейр: ровно одна обрезанная строка топлива + недобор против psm → доначислить
    for code, rows in capped.items():
        if len(rows) != 1:
            continue
        gap = round(psm_by_fuel.get(code, 0.0) - sales_by_fuel.get(code, 0.0), 2)
        if gap > 0.02:
            rows[0]["amount"] = round(rows[0]["amount"] + gap, 2)

    return agg


async def load_mapping_context(db: AsyncSession, company_id: uuid.UUID) -> MappingContext:
    """Загрузить маппинги оплат/каналов/топлива компании одним проходом."""
    pms = (
        await db.execute(
            select(PaymentMapping)
            .where(PaymentMapping.company_id == company_id)
            .order_by(PaymentMapping.sort_order)
        )
    ).scalars().all()
    chs = (
        await db.execute(
            select(PaymentChannel).where(PaymentChannel.company_id == company_id)
        )
    ).scalars().all()
    fms = (
        await db.execute(
            select(FuelMapping).where(FuelMapping.company_id == company_id)
        )
    ).scalars().all()
    return MappingContext(
        payment_mappings=list(pms),
        channels={c.code: c for c in chs},
        fuel_by_code={f.service_code: f for f in fms},
    )
