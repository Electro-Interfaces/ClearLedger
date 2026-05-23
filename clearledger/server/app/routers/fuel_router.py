"""
Fuel CRUD: станции, смены, ТТН, документы на экспорт.
+ Нормализация из STS API.
"""

import uuid
from datetime import datetime, timezone


def _parse_dt(val: str | None) -> datetime | None:
    """Parse ISO datetime string to datetime object."""
    if not val:
        return None
    return datetime.fromisoformat(val)

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    FuelStation, FuelShift, FuelTank, FuelPump,
    FuelReceipt, FuelExportDoc, User,
)
from app.services.sts_client import (
    sts_get_shifts, sts_get_shift_report, sts_get_receipts,
    sts_test_connection,
)
async def _company_id(user: User, db: AsyncSession) -> uuid.UUID:
    """Resolve company_id from user."""
    return user.company_id

router = APIRouter(prefix="/fuel", tags=["Топливо"])


# ═══════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════

class StationOut(BaseModel):
    id: str
    code: int
    name: str
    sts_system_code: int | None = None
    model_config = {"from_attributes": True}


class ShiftOut(BaseModel):
    id: str
    station_id: str
    shift_number: int
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    operator: str | None = None
    status: str
    total_liters: float
    total_amount: float
    cash: float
    card: float
    voucher: float
    created_at: datetime
    model_config = {"from_attributes": True}


class TankOut(BaseModel):
    tank_number: int
    fuel_type: str
    volume_start: float
    volume_end: float
    sales: float
    density: float | None = None
    model_config = {"from_attributes": True}


class PumpOut(BaseModel):
    pump_number: int
    nozzle: str | None = None
    fuel_type: str
    sales_volume: float
    amount: float
    model_config = {"from_attributes": True}


class ShiftDetailOut(ShiftOut):
    tanks: list[TankOut] = []
    pumps: list[PumpOut] = []


class ReceiptOut(BaseModel):
    id: str
    station_id: str
    ttn: str
    fuel_name: str
    supplier: str | None = None
    doc_volume_liters: float
    fact_volume_liters: float
    diff_volume: float
    density: float | None = None
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}


class ExportDocOut(BaseModel):
    id: str
    type: str
    label: str | None = None
    status: str
    export_format: str | None = None
    created_at: datetime
    exported_at: datetime | None = None
    model_config = {"from_attributes": True}


class StsConnectionIn(BaseModel):
    base_url: str = "https://pos.autooplata.ru/tms"
    login: str
    password: str
    system_code: int = 65


class NormalizeRequest(BaseModel):
    station_code: int
    shift_number: int | None = None
    base_url: str = "https://pos.autooplata.ru/tms"
    login: str
    password: str
    system_code: int = 65


# ═══════════════════════════════════════════════════════════════
# Станции
# ═══════════════════════════════════════════════════════════════

@router.get("/stations", response_model=list[StationOut])
async def list_stations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_id = await _company_id(user, db)
    result = await db.execute(
        select(FuelStation).where(FuelStation.company_id == company_id)
    )
    return [StationOut(id=str(s.id), code=s.code, name=s.name, sts_system_code=s.sts_system_code)
            for s in result.scalars()]


# ═══════════════════════════════════════════════════════════════
# Смены
# ═══════════════════════════════════════════════════════════════

@router.get("/shifts", response_model=list[ShiftOut])
async def list_shifts(
    station_code: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_id = await _company_id(user, db)
    q = select(FuelShift).where(FuelShift.company_id == company_id)
    if station_code is not None:
        q = q.join(FuelStation).where(FuelStation.code == station_code)
    q = q.order_by(FuelShift.shift_number.desc()).limit(200)
    result = await db.execute(q)
    return [_shift_out(s) for s in result.scalars()]


@router.get("/shifts/{shift_id}", response_model=ShiftDetailOut)
async def get_shift(
    shift_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FuelShift)
        .options(selectinload(FuelShift.tanks), selectinload(FuelShift.pumps))
        .where(FuelShift.id == uuid.UUID(shift_id))
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(404, "Смена не найдена")
    out = _shift_out(shift)
    return ShiftDetailOut(
        **out.model_dump(),
        tanks=[TankOut.model_validate(t) for t in shift.tanks],
        pumps=[PumpOut.model_validate(p) for p in shift.pumps],
    )


# ═══════════════════════════════════════════════════════════════
# ТТН
# ═══════════════════════════════════════════════════════════════

@router.get("/receipts", response_model=list[ReceiptOut])
async def list_receipts(
    station_code: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_id = await _company_id(user, db)
    q = select(FuelReceipt).where(FuelReceipt.company_id == company_id)
    if station_code is not None:
        q = q.join(FuelStation).where(FuelStation.code == station_code)
    q = q.order_by(FuelReceipt.created_at.desc()).limit(200)
    result = await db.execute(q)
    return [_receipt_out(r) for r in result.scalars()]


# ═══════════════════════════════════════════════════════════════
# Экспорт
# ═══════════════════════════════════════════════════════════════

@router.get("/export-docs", response_model=list[ExportDocOut])
async def list_export_docs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_id = await _company_id(user, db)
    result = await db.execute(
        select(FuelExportDoc)
        .where(FuelExportDoc.company_id == company_id)
        .order_by(FuelExportDoc.created_at.desc())
    )
    return [ExportDocOut(id=str(d.id), type=d.type, label=d.label,
                         status=d.status, export_format=d.export_format,
                         created_at=d.created_at, exported_at=d.exported_at)
            for d in result.scalars()]


# ═══════════════════════════════════════════════════════════════
# STS: тест подключения
# ═══════════════════════════════════════════════════════════════

@router.post("/sts/test")
async def test_sts_connection(body: StsConnectionIn):
    return await sts_test_connection(
        body.base_url, body.login, body.password, body.system_code,
    )


# ═══════════════════════════════════════════════════════════════
# Нормализация: STS → PostgreSQL
# ═══════════════════════════════════════════════════════════════

@router.post("/normalize")
async def normalize_shifts(
    body: NormalizeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Загрузить смены из STS API, нормализовать и сохранить в БД."""
    company_id = await _company_id(user, db)

    # Получить или создать станцию
    result = await db.execute(
        select(FuelStation).where(
            FuelStation.company_id == company_id,
            FuelStation.code == body.station_code,
        )
    )
    station = result.scalar_one_or_none()
    if not station:
        station = FuelStation(
            company_id=company_id,
            code=body.station_code,
            name=f"АЗС №{body.station_code}",
            sts_system_code=body.system_code,
        )
        db.add(station)
        await db.flush()

    # Загрузить смены из STS
    if body.shift_number:
        shifts_to_process = [{"shift": body.shift_number}]
    else:
        shifts_to_process = await sts_get_shifts(
            body.base_url, body.login, body.password,
            body.system_code, body.station_code,
        )

    created = 0
    skipped = 0

    for shift_info in shifts_to_process:
        shift_num = shift_info["shift"]

        # Проверка дубля
        existing = await db.execute(
            select(FuelShift).where(
                FuelShift.station_id == station.id,
                FuelShift.shift_number == shift_num,
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        # Загрузить детали смены
        # STS API возвращает: { psm, release, receipt, sales, money }
        report = await sts_get_shift_report(
            body.base_url, body.login, body.password,
            body.system_code, body.station_code, shift_num,
        )

        # Найти dt_open/dt_close из списка смен
        shift_meta = next((s for s in shifts_to_process if s["shift"] == shift_num), {})

        # psm.total — итого продаж по топливу
        psm_total = report.get("psm", {}).get("total", [])
        total_liters = sum(t.get("release", {}).get("quantity", 0) for t in psm_total)
        total_amount = sum(t.get("release", {}).get("amount", 0) for t in psm_total)

        # sales — продажи по типам оплаты
        sales_data = report.get("sales", [])
        cash = 0.0
        card = 0.0
        voucher = 0.0
        for sale in sales_data:
            pay_id = sale.get("pay_type", {}).get("id", 0)
            pay_total = sum(float(f.get("release", {}).get("cost", 0)) for f in sale.get("fuel", []))
            if pay_id == 1:       # Наличные
                cash = pay_total
            elif pay_id == 2:     # Безнал/карта
                card = pay_total
            else:                 # Талоны и прочие
                voucher += pay_total

        shift = FuelShift(
            company_id=company_id,
            station_id=station.id,
            shift_number=shift_num,
            opened_at=_parse_dt(shift_meta.get("dt_open")),
            closed_at=_parse_dt(shift_meta.get("dt_close")),
            operator="",
            status="new",
            total_liters=total_liters,
            total_amount=total_amount,
            cash=cash,
            card=card,
            voucher=voucher,
        )
        db.add(shift)
        await db.flush()

        # Резервуары — из release[]
        for t in report.get("release", []):
            svc = t.get("service", {})
            doc_beg = t.get("doc_beg", {})
            doc_end = t.get("doc_end", {})
            rel = t.get("release", {})
            db.add(FuelTank(
                shift_id=shift.id,
                tank_number=t.get("tank", 0),
                fuel_type=svc.get("service_name", ""),
                volume_start=float(doc_beg.get("volume", 0)),
                volume_end=float(doc_end.get("volume", 0)),
                sales=float(rel.get("volume", 0)),
                density=t.get("density_end"),
            ))

        # ТРК — из psm.data[]
        for p in report.get("psm", {}).get("data", []):
            svc = p.get("service", {})
            rel = p.get("release", {})
            db.add(FuelPump(
                shift_id=shift.id,
                pump_number=p.get("pump", 0),
                nozzle=str(p.get("nozzle", "")),
                fuel_type=svc.get("service_name", ""),
                sales_volume=float(rel.get("volume", 0)),
                amount=float(rel.get("cost", 0)),
            ))

        # ТТН — из receipt[]
        for r in report.get("receipt", []):
            doc = r.get("doc", {})
            fact = r.get("fact", {})
            doc_vol = float(doc.get("volume", 0))
            fact_vol = float(fact.get("volume", 0))
            doc_mass = float(doc.get("amount", 0))
            fact_mass = float(fact.get("amount", 0))
            svc = r.get("service", {})

            db.add(FuelReceipt(
                company_id=company_id,
                station_id=station.id,
                shift_id=shift.id,
                ttn=r.get("ttn", ""),
                fuel_name=svc.get("service_name", ""),
                fuel_code=svc.get("service_code"),
                supplier=r.get("base", {}).get("name", ""),
                doc_volume_liters=doc_vol,
                doc_mass_kg=doc_mass,
                doc_cost=0,
                fact_volume_liters=fact_vol,
                fact_mass_kg=fact_mass,
                fact_cost=0,
                density=doc.get("density"),
                diff_volume=fact_vol - doc_vol,
                diff_mass=fact_mass - doc_mass,
                received_at=_parse_dt(r.get("dt")),
                status="new",
            ))

        created += 1

    return {"created": created, "skipped": skipped, "station": station.name}


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _shift_out(s: FuelShift) -> ShiftOut:
    return ShiftOut(
        id=str(s.id),
        station_id=str(s.station_id),
        shift_number=s.shift_number,
        opened_at=s.opened_at,
        closed_at=s.closed_at,
        operator=s.operator,
        status=s.status,
        total_liters=float(s.total_liters or 0),
        total_amount=float(s.total_amount or 0),
        cash=float(s.cash or 0),
        card=float(s.card or 0),
        voucher=float(s.voucher or 0),
        created_at=s.created_at,
    )


def _receipt_out(r: FuelReceipt) -> ReceiptOut:
    return ReceiptOut(
        id=str(r.id),
        station_id=str(r.station_id),
        ttn=r.ttn,
        fuel_name=r.fuel_name,
        supplier=r.supplier,
        doc_volume_liters=float(r.doc_volume_liters or 0),
        fact_volume_liters=float(r.fact_volume_liters or 0),
        diff_volume=float(r.diff_volume or 0),
        density=float(r.density) if r.density else None,
        status=r.status,
        created_at=r.created_at,
    )
