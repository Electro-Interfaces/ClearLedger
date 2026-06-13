"""
Резолвер МАППИНГА значений между системами — конфигурация уровня КАНАЛА.

Виды (kind): fuel | paytype | station | nomenclature | counterparty.
Значения топлива/оплат/станций называются по-РАЗНОМУ в STS / TradeCorp / MSTO /
ЦБ ЭЛСИ.АЗК, поэтому маппинг — ДАННЫЕ (`ReconcileMapping`), а не хардкод.

Приоритет резолва:
  1. channel-specific (ReconcileMapping.channel_id = канал) — оптимизация под канал;
  2. company-default (channel_id IS NULL) — общий для компании;
  3. канонический СИД (ниже) — дефолт «из коробки».

Сиды перекрываются маппингом канала/компании. resolve() — рантайм (БД+сид);
normalize_default() — только сид (без БД, для стадии нормализации потока).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReconcileMapping

# ── Канонические СИДЫ (дефолты; перекрываются ReconcileMapping) ──────────────
_FUEL_SEED = {
    "бензин аи-92": "АИ-92", "аи-92": "АИ-92", "92": "АИ-92", "regular": "АИ-92",
    "бензин аи-95": "АИ-95", "аи-95": "АИ-95", "95": "АИ-95", "premium": "АИ-95",
    "бензин аи-98": "АИ-98", "аи-98": "АИ-98", "98": "АИ-98", "super": "АИ-98",
    "бензин аи-100": "АИ-100", "аи-100": "АИ-100", "100": "АИ-100", "ultimate": "АИ-100",
    "дизельное топливо": "ДТ", "дизель": "ДТ", "дт": "ДТ", "diesel": "ДТ",
    "дт зимнее": "ДТ", "дт летнее": "ДТ", "дт-к5": "ДТ", "дт-премиум": "ДТ",
    "дт к5": "ДТ", "дт премиум": "ДТ",
    "пропан": "Пропан", "propane": "Пропан", "газ": "Пропан", "спбт": "Пропан",
    "метан": "Метан", "methane": "Метан", "cng": "Метан",
}
# Способы оплаты: STS pay_type.id / названия форм (ОРП/эквайринг) → канон
_PAYTYPE_SEED = {
    "1": "Наличные", "наличные": "Наличные",
    "2": "Банковская карта", "карты мпс": "Банковская карта",
    "банковские карты": "Банковская карта", "retail_card": "Банковская карта",
    "cards": "Топливная карта", "топливные карты": "Топливная карта",
    "online": "Онлайн", "онлайн": "Онлайн", "online (яндекс, мобилпр.)": "Онлайн",
    "voucher": "Талоны", "талоны": "Талоны",
    "ledger": "Ведомости", "ведомости": "Ведомости",
    "retail_cash": "Наличные",
}
_SEEDS: dict[str, dict[str, str]] = {"fuel": _FUEL_SEED, "paytype": _PAYTYPE_SEED}


def normalize_default(kind: str, source_key) -> str:
    """Канон-сид (без БД): нормализовать значение по дефолтной карте вида."""
    raw = str(source_key or "").strip()
    return _SEEDS.get(kind, {}).get(raw.lower(), raw)


async def load_kind_map(
    db: AsyncSession,
    company_id: uuid.UUID,
    kind: str,
    channel_id: uuid.UUID | None = None,
) -> dict[str, str]:
    """Карта {source_key.lower(): target} для вида — ОДНИМ запросом на прогон.

    channel-override поверх company-default (channel выигрывает). Применять через
    apply(); чего нет в карте — фолбэк на канон-сид (normalize_default).
    """
    rows = (
        await db.execute(
            select(ReconcileMapping).where(
                ReconcileMapping.company_id == company_id,
                ReconcileMapping.kind == kind,
            )
        )
    ).scalars().all()
    company_map: dict[str, str] = {}
    channel_map: dict[str, str] = {}
    for m in rows:
        tgt = m.target_name or m.target_ref
        if not tgt:
            continue
        key = str(m.source_key or "").strip().lower()
        if m.channel_id is None:
            company_map[key] = tgt
        elif channel_id is not None and m.channel_id == channel_id:
            channel_map[key] = tgt
    return {**company_map, **channel_map}


def apply(kind: str, value, kind_map: dict[str, str]) -> str:
    """Применить загруженную карту: override → канон-сид → как есть."""
    raw = str(value or "").strip()
    return kind_map.get(raw.lower()) or normalize_default(kind, raw)


async def resolve(
    db: AsyncSession,
    company_id: uuid.UUID,
    kind: str,
    source_key,
    channel_id: uuid.UUID | None = None,
) -> str:
    """Резолв значения: channel-override → company-default → канон-сид.

    Возвращает target_name/target_ref маппинга, иначе — нормализованный сид.
    """
    sk = str(source_key or "").strip()
    rows = (
        await db.execute(
            select(ReconcileMapping).where(
                ReconcileMapping.company_id == company_id,
                ReconcileMapping.kind == kind,
                ReconcileMapping.source_key == sk,
            )
        )
    ).scalars().all()
    if rows:
        chosen = None
        if channel_id is not None:
            chosen = next((m for m in rows if m.channel_id == channel_id), None)
        chosen = chosen or next((m for m in rows if m.channel_id is None), None) or rows[0]
        return chosen.target_name or chosen.target_ref or normalize_default(kind, sk)
    return normalize_default(kind, sk)
