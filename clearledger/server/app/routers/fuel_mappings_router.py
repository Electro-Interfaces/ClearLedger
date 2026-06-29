"""
CRUD справочников маппингов топливных каналов (компания-scoped):
  - payment_channels — каналы оплаты (склад, требует перемещения)
  - payment_mappings — образец имени STS → канал
  - fuel_mappings    — service_code → номенклатура т/л + плотность

Источник истины маппингов — приложение (решение 28.06.2026). Дефолты ГИГ
сидятся в seed._seed_gig_fuel_mappings; здесь — ручное ведение бухгалтером.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import FuelMapping, PaymentChannel, PaymentMapping, ReconcileMapping, User

router = APIRouter(prefix="/fuel-mappings", tags=["Маппинги топлива"])


async def _cid(user: User) -> uuid.UUID:
    if user.company_id is None:
        raise HTTPException(400, "Пользователь не привязан к компании")
    return user.company_id


# ─── Схемы ──────────────────────────────────────────────────────────────────
class PaymentChannelIn(BaseModel):
    code: str
    name: str
    warehouse_name: str | None = None
    requires_transfer: bool = False
    counterparty_name: str | None = None
    sort_order: int = 0


class PaymentMappingIn(BaseModel):
    pattern: str
    channel_code: str = ""
    warehouse_override: str | None = None
    sort_order: int = 0


class FuelMappingIn(BaseModel):
    service_code: int
    fuel_name: str
    nomenclature_tonnes: str | None = None
    nomenclature_liters: str | None = None
    nomenclature_t_ref: str | None = None
    nomenclature_l_ref: str | None = None
    density: float | None = None
    sort_order: int = 0


def _ch_out(c: PaymentChannel) -> dict:
    return {"id": str(c.id), "code": c.code, "name": c.name,
            "warehouse_name": c.warehouse_name, "requires_transfer": c.requires_transfer,
            "counterparty_name": c.counterparty_name, "sort_order": c.sort_order}


def _pm_out(m: PaymentMapping) -> dict:
    return {"id": str(m.id), "pattern": m.pattern, "channel_code": m.channel_code,
            "warehouse_override": m.warehouse_override, "sort_order": m.sort_order}


def _fm_out(f: FuelMapping) -> dict:
    return {"id": str(f.id), "service_code": f.service_code, "fuel_name": f.fuel_name,
            "nomenclature_tonnes": f.nomenclature_tonnes,
            "nomenclature_liters": f.nomenclature_liters,
            "nomenclature_t_ref": f.nomenclature_t_ref,
            "nomenclature_l_ref": f.nomenclature_l_ref,
            "density": float(f.density) if f.density is not None else None,
            "sort_order": f.sort_order}


async def _sync_reconcile_fuel(db: AsyncSession, cid, f: FuelMapping) -> None:
    """Вывести reconcile-маппинг 'fuel' (компания-уровень) из справочника видов
    топлива: код топлива → Номенклатура 1С (литры, GUID). Единый источник правды —
    fuel_mappings; reconcile-fuel не ведётся параллельно, а синхронизируется отсюда."""
    if not f.nomenclature_l_ref:
        return
    existing = (await db.execute(
        select(ReconcileMapping).where(
            ReconcileMapping.company_id == cid,
            ReconcileMapping.kind == "fuel",
            ReconcileMapping.channel_id.is_(None),
            ReconcileMapping.source_key == str(f.service_code),
        ).limit(1)
    )).scalar_one_or_none()
    if existing:
        existing.target_ref = f.nomenclature_l_ref
        existing.target_name = f.nomenclature_liters
    else:
        db.add(ReconcileMapping(
            company_id=cid, channel_id=None, kind="fuel",
            source_key=str(f.service_code),
            target_ref=f.nomenclature_l_ref, target_name=f.nomenclature_liters,
        ))


# ─── Свод ───────────────────────────────────────────────────────────────────
@router.get("")
async def list_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Все три справочника одним вызовом (для страницы каналов)."""
    cid = await _cid(user)
    chs = (await db.execute(select(PaymentChannel).where(
        PaymentChannel.company_id == cid).order_by(PaymentChannel.sort_order))).scalars().all()
    pms = (await db.execute(select(PaymentMapping).where(
        PaymentMapping.company_id == cid).order_by(PaymentMapping.sort_order))).scalars().all()
    fms = (await db.execute(select(FuelMapping).where(
        FuelMapping.company_id == cid).order_by(FuelMapping.service_code))).scalars().all()
    return {
        "payment_channels": [_ch_out(c) for c in chs],
        "payment_mappings": [_pm_out(m) for m in pms],
        "fuel_mappings": [_fm_out(f) for f in fms],
    }


# ─── payment_channels ───────────────────────────────────────────────────────
@router.get("/payment-channels")
async def list_channels(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    rows = (await db.execute(select(PaymentChannel).where(
        PaymentChannel.company_id == cid).order_by(PaymentChannel.sort_order))).scalars().all()
    return [_ch_out(c) for c in rows]


@router.post("/payment-channels")
async def create_channel(body: PaymentChannelIn, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    ch = PaymentChannel(company_id=cid, **body.model_dump())
    db.add(ch)
    await db.commit()
    await db.refresh(ch)
    return _ch_out(ch)


@router.put("/payment-channels/{ch_id}")
async def update_channel(ch_id: str, body: PaymentChannelIn,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    ch = await db.get(PaymentChannel, uuid.UUID(ch_id))
    if ch is None or ch.company_id != cid:
        raise HTTPException(404, "Канал не найден")
    for k, v in body.model_dump().items():
        setattr(ch, k, v)
    await db.commit()
    await db.refresh(ch)
    return _ch_out(ch)


@router.delete("/payment-channels/{ch_id}")
async def delete_channel(ch_id: str, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    ch = await db.get(PaymentChannel, uuid.UUID(ch_id))
    if ch is None or ch.company_id != cid:
        raise HTTPException(404, "Канал не найден")
    await db.delete(ch)
    await db.commit()
    return {"deleted": ch_id}


# ─── payment_mappings ───────────────────────────────────────────────────────
@router.get("/payment-mappings")
async def list_payment_mappings(user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    rows = (await db.execute(select(PaymentMapping).where(
        PaymentMapping.company_id == cid).order_by(PaymentMapping.sort_order))).scalars().all()
    return [_pm_out(m) for m in rows]


@router.post("/payment-mappings")
async def create_payment_mapping(body: PaymentMappingIn, user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    m = PaymentMapping(company_id=cid, pattern=body.pattern.lower().strip(),
                       channel_code=body.channel_code,
                       warehouse_override=body.warehouse_override, sort_order=body.sort_order)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return _pm_out(m)


@router.put("/payment-mappings/{m_id}")
async def update_payment_mapping(m_id: str, body: PaymentMappingIn,
                                user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    m = await db.get(PaymentMapping, uuid.UUID(m_id))
    if m is None or m.company_id != cid:
        raise HTTPException(404, "Маппинг не найден")
    m.pattern = body.pattern.lower().strip()
    m.channel_code = body.channel_code
    m.warehouse_override = body.warehouse_override
    m.sort_order = body.sort_order
    await db.commit()
    await db.refresh(m)
    return _pm_out(m)


@router.delete("/payment-mappings/{m_id}")
async def delete_payment_mapping(m_id: str, user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    m = await db.get(PaymentMapping, uuid.UUID(m_id))
    if m is None or m.company_id != cid:
        raise HTTPException(404, "Маппинг не найден")
    await db.delete(m)
    await db.commit()
    return {"deleted": m_id}


# ─── fuel_mappings ──────────────────────────────────────────────────────────
@router.get("/fuel-types")
async def list_fuel_mappings(user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    rows = (await db.execute(select(FuelMapping).where(
        FuelMapping.company_id == cid).order_by(FuelMapping.service_code))).scalars().all()
    return [_fm_out(f) for f in rows]


@router.post("/fuel-types")
async def create_fuel_mapping(body: FuelMappingIn, user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    f = FuelMapping(company_id=cid, **body.model_dump())
    db.add(f)
    await db.flush()
    await _sync_reconcile_fuel(db, cid, f)
    await db.commit()
    await db.refresh(f)
    return _fm_out(f)


@router.put("/fuel-types/{f_id}")
async def update_fuel_mapping(f_id: str, body: FuelMappingIn,
                             user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    f = await db.get(FuelMapping, uuid.UUID(f_id))
    if f is None or f.company_id != cid:
        raise HTTPException(404, "Вид топлива не найден")
    for k, v in body.model_dump().items():
        setattr(f, k, v)
    await db.flush()
    await _sync_reconcile_fuel(db, cid, f)
    await db.commit()
    await db.refresh(f)
    return _fm_out(f)


@router.delete("/fuel-types/{f_id}")
async def delete_fuel_mapping(f_id: str, user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    cid = await _cid(user)
    f = await db.get(FuelMapping, uuid.UUID(f_id))
    if f is None or f.company_id != cid:
        raise HTTPException(404, "Вид топлива не найден")
    await db.delete(f)
    await db.commit()
    return {"deleted": f_id}
