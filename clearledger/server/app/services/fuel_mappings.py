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
