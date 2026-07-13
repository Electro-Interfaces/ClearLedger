"""
Fuel CRUD: станции, смены, ТТН, документы на экспорт.
+ Нормализация из STS API.
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone


def _parse_dt(val: str | None) -> datetime | None:
    """Parse ISO datetime string to datetime object."""
    if not val:
        return None
    return datetime.fromisoformat(val)


def _int_or_none(val):
    try:
        return int(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _num_or_none(val):
    try:
        return round(float(val), 4) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _density(val) -> float | None:
    """Плотность → г/см³ (кг/л), как «Плотность» в 1С (поле Numeric(6,4)).

    STS отдаёт плотность в кг/м³ (≈700-900) — не влезает в Numeric(6,4).
    Нормализуем к г/см³ (÷1000), страхуемся от выхода за диапазон столбца.
    """
    if val in (None, ""):
        return None
    try:
        d = float(val)
    except (TypeError, ValueError):
        return None
    if d == 0:
        return None
    if abs(d) > 10:          # кг/м³ → г/см³
        d = d / 1000.0
    if abs(d) >= 100:        # страховка под Numeric(6,4)
        return None
    return round(d, 4)

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import assert_company_member, get_current_user
from app.database import get_db, async_session_factory
from app.models import (
    FuelStation, FuelShift, FuelTank, FuelPump, FuelCashMovement,
    FuelReceipt, FuelReceiptOverride, FuelReceiptCost, FuelOpeningBalance, FuelPurchaseBatch,
    FuelExportDoc, FuelShiftSale, FuelShiftSaleOverride, FuelShiftCorrectionNote,
    FuelTransaction, ExportPacket, User, DataEntry,
)
from app.services.fuel_documents import build_shift_documents, build_ttn_documents
from app.services.fuel_costing import FuelCostingService
from app.services.fuel_dashboard import FuelDashboardService
from app.services.fuel_mappings import MappingContext, build_sales_agg, load_mapping_context
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
    station_code: int = 0
    station_name: str | None = None
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
    has_corrections: bool = False   # внесена хоть одна корректировка (FuelShiftSaleOverride)
    created_at: datetime
    model_config = {"from_attributes": True}


class TankOut(BaseModel):
    tank_number: int
    fuel_type: str
    fuel_code: int | None = None
    volume_start: float
    volume_end: float
    sales: float
    volume_received: float = 0
    density: float | None = None
    density_beg: float | None = None
    temp_end: float | None = None
    level_end: float | None = None
    water_level: float | None = None
    water_volume: float | None = None
    model_config = {"from_attributes": True}


class PumpOut(BaseModel):
    pump_number: int
    nozzle: str | None = None
    fuel_type: str
    fuel_code: int | None = None
    tank_number: int | None = None
    sales_volume: float
    amount: float
    psm_beg: float | None = None
    psm_end: float | None = None
    price: float | None = None
    density: float | None = None
    model_config = {"from_attributes": True}


class CashMovementOut(BaseModel):
    operation_id: int
    operation_name: str
    amount: float
    pos_number: int | None = None
    model_config = {"from_attributes": True}


class ShiftSaleOut(BaseModel):
    payment_channel: str
    fuel_code: int
    liters: float
    amount: float
    discount: float = 0
    warehouse_name: str | None = None
    # Корректировка (L2 CLEAN): is_manual=строка скорректирована вручную;
    # src_* — исходные STS-значения для показа «было → стало».
    is_manual: bool = False
    src_liters: float | None = None
    src_amount: float | None = None
    src_discount: float | None = None
    note: str | None = None
    model_config = {"from_attributes": True}


class ShiftDetailOut(ShiftOut):
    tanks: list[TankOut] = []
    pumps: list[PumpOut] = []
    cash_movements: list[CashMovementOut] = []
    sales: list[ShiftSaleOut] = []
    receipts: list["ReceiptOut"] = []
    # Сырой сменный отчёт STS ({psm, release, sales, receipt, money}) — вход
    # эталонного просмотрщика. None у смен, загруженных до v2.9 (нужна переигровка).
    raw_report: dict | None = None
    # Комментарий менеджера по корректировке (в целом по документу)
    correction_note: str | None = None
    correction_note_author: str | None = None


class ReceiptOut(BaseModel):
    id: str
    station_id: str
    station_code: int = 0
    station_name: str | None = None
    ttn: str
    fuel_name: str
    fuel_code: int | None = None
    supplier: str | None = None
    shift_number: int | None = None
    tank: int | None = None
    doc_volume_liters: float
    fact_volume_liters: float
    diff_volume: float
    doc_mass_kg: float = 0
    fact_mass_kg: float = 0
    diff_mass: float = 0
    density: float | None = None
    fact_density: float | None = None
    doc_temp: float | None = None
    fact_temp: float | None = None
    status: str
    received_at: datetime | None = None
    created_at: datetime
    # Корректировка (L2 CLEAN): is_manual + исходные STS-значения документа.
    is_manual: bool = False
    has_corrections: bool = False   # реальная правка значений ИЛИ комментарий менеджера
    src_volume: float | None = None
    src_mass: float | None = None
    src_density: float | None = None
    note: str | None = None
    # Себестоимость партии (L2, задаётся менеджером; cost_per_liter — норм. ₽/л для маржи).
    has_cost: bool = False
    cost_unit: str | None = None
    cost_unit_price: float | None = None
    cost_per_liter: float | None = None
    model_config = {"from_attributes": True}


# ShiftDetailOut.receipts ссылается на ReceiptOut (forward ref) — дорезолвить.
ShiftDetailOut.model_rebuild()


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
    date_from: str | None = None  # YYYY-MM-DD — ограничение периода смен
    date_to: str | None = None


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

@router.get("/count")
async def fuel_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реальное количество загруженных смен/ТТН компании (БД), без limit —
    для карточки «Загружено» (список /shifts ограничен 200)."""
    cid = await _company_id(user, db)
    shifts = (await db.execute(
        select(func.count()).select_from(FuelShift).where(FuelShift.company_id == cid)
    )).scalar() or 0
    receipts = (await db.execute(
        select(func.count()).select_from(FuelReceipt).where(FuelReceipt.company_id == cid)
    )).scalar() or 0
    return {"shifts": int(shifts), "receipts": int(receipts)}


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
    shifts = list((await db.execute(q)).scalars())
    st_ids = {s.station_id for s in shifts}
    stations = {st.id: st for st in (await db.execute(
        select(FuelStation).where(FuelStation.id.in_(st_ids)))).scalars()} if st_ids else {}
    # Смены с реальной корректировкой (override с полем, отличным от STS-снимка).
    ov_rows = (await db.execute(
        select(FuelShiftSaleOverride.station_id, FuelShiftSaleOverride.shift_number)
        .where(
            FuelShiftSaleOverride.company_id == company_id,
            or_(
                and_(FuelShiftSaleOverride.liters.isnot(None),
                     FuelShiftSaleOverride.liters != FuelShiftSaleOverride.src_liters),
                and_(FuelShiftSaleOverride.amount.isnot(None),
                     FuelShiftSaleOverride.amount != FuelShiftSaleOverride.src_amount),
                and_(FuelShiftSaleOverride.discount.isnot(None),
                     FuelShiftSaleOverride.discount != FuelShiftSaleOverride.src_discount),
            ),
        ).distinct())).all()
    ov_keys = {(r[0], r[1]) for r in ov_rows}
    return [
        _shift_out(s, stations.get(s.station_id), (s.station_id, s.shift_number) in ov_keys)
        for s in shifts
    ]


@router.get("/shifts/{shift_id}", response_model=ShiftDetailOut)
async def get_shift(
    shift_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FuelShift)
        .options(
            selectinload(FuelShift.tanks), selectinload(FuelShift.pumps),
            selectinload(FuelShift.cash_movements),
        )
        .where(FuelShift.id == uuid.UUID(shift_id))
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(404, "Смена не найдена")
    cid = await _company_id(user, db)
    if shift.company_id != cid:
        raise HTTPException(404, "Смена не найдена")
    station = await db.get(FuelStation, shift.station_id)
    out = _shift_out(shift, station)
    # Разбивка продаж по каналам оплаты (для вкладки «Реализация») + корректировки L2
    sales = (await db.execute(
        select(FuelShiftSale).where(FuelShiftSale.shift_id == shift.id))).scalars().all()
    ov_map = await _load_sale_overrides(db, cid, shift.station_id, shift.shift_number)
    # ТТН периода станции (для вкладки «Поступления»)
    rcpts = (await db.execute(
        select(FuelReceipt).where(
            FuelReceipt.company_id == cid, FuelReceipt.station_id == shift.station_id)
        .order_by(FuelReceipt.received_at.desc()).limit(50))).scalars().all()
    # Комментарий менеджера по корректировке (в целом по документу)
    note = (await db.execute(select(FuelShiftCorrectionNote).where(
        FuelShiftCorrectionNote.company_id == cid,
        FuelShiftCorrectionNote.station_id == shift.station_id,
        FuelShiftCorrectionNote.shift_number == shift.shift_number,
    ))).scalar_one_or_none()
    return ShiftDetailOut(
        **out.model_dump(),
        tanks=[TankOut.model_validate(t) for t in shift.tanks],
        pumps=[PumpOut.model_validate(p) for p in shift.pumps],
        cash_movements=[CashMovementOut.model_validate(m) for m in shift.cash_movements],
        sales=[_sale_out_with_override(s, ov_map.get((s.payment_channel, s.fuel_code))) for s in sales],
        receipts=[_receipt_out(r, station) for r in rcpts],
        raw_report=shift.raw_report,
        correction_note=note.note if note else None,
        correction_note_author=note.author if note else None,
    )


# ═══════════════════════════════════════════════════════════════
# Удаление загруженных смен/ТТН (UI: «Удалить» / «Обновить» за период + точки)
# ═══════════════════════════════════════════════════════════════

class DeletePeriodRequest(BaseModel):
    """Удаление загруженных данных за период по выбранным станциям.
    kind: 'shift' (смены) | 'receipt' (ТТН). station_codes пуст → все станции
    компании. Период по opened_at (смены) / received_at (ТТН)."""
    kind: str = "shift"
    station_codes: list[int] = []
    date_from: str | None = None
    date_to: str | None = None


@router.post("/delete-period")
async def delete_period(
    body: DeletePeriodRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удалить загруженные смены/ТТН за период по станциям. Закрытые периодом
    смены (is_locked) пропускаются. L1-маркеры смен чистятся — повторная
    загрузка пересоздаёт их свежими (с сырым отчётом для новой формы)."""
    cid = await _company_id(user, db)
    df = (body.date_from or "")[:10] or None
    dt = (body.date_to or "")[:10] or None
    lo = datetime.fromisoformat(df) if df else None
    hi = (datetime.fromisoformat(dt) + timedelta(days=1)) if dt else None

    st_ids: list[uuid.UUID] = []
    if body.station_codes:
        st_ids = list((await db.execute(
            select(FuelStation.id).where(
                FuelStation.company_id == cid,
                FuelStation.code.in_(body.station_codes))
        )).scalars())
        if not st_ids:
            return {"deleted": 0}

    if body.kind == "receipt":
        q = select(FuelReceipt.id).where(FuelReceipt.company_id == cid)
        if st_ids:
            q = q.where(FuelReceipt.station_id.in_(st_ids))
        if lo is not None:
            q = q.where(FuelReceipt.received_at >= lo)
        if hi is not None:
            q = q.where(FuelReceipt.received_at < hi)
        ids = list((await db.execute(q)).scalars())
        if ids:
            # L1-маркеры ТТН (sts-ttn-*) — по натуральному ключу станция+номер ТТН.
            # Оба формата маркера (shift-путь и delivery-путь) хранят в meta
            # station_code и ttn_number. Без этой чистки re-ingest делает continue
            # по уцелевшему маркеру и НЕ пересоздаёт приём → потеря данных при «Обновить».
            pairs = (await db.execute(
                select(FuelStation.code, FuelReceipt.ttn)
                .join(FuelStation, FuelStation.id == FuelReceipt.station_id)
                .where(FuelReceipt.id.in_(ids))
            )).all()
            keys = [f"{code}|{ttn}" for code, ttn in pairs if ttn]
            if keys:
                await db.execute(delete(DataEntry).where(
                    DataEntry.company_id == cid,
                    DataEntry.source_label.like("sts-ttn-%"),
                    func.concat(DataEntry.meta["station_code"].astext, "|",
                                DataEntry.meta["ttn_number"].astext).in_(keys),
                ))
            await db.execute(delete(FuelReceipt).where(FuelReceipt.id.in_(ids)))
        return {"deleted": len(ids), "kind": "receipt"}

    # смены
    q = select(FuelShift.id).where(
        FuelShift.company_id == cid, FuelShift.is_locked.is_(False))
    if st_ids:
        q = q.where(FuelShift.station_id.in_(st_ids))
    if lo is not None:
        q = q.where(FuelShift.opened_at >= lo)
    if hi is not None:
        q = q.where(FuelShift.opened_at < hi)
    ids = list((await db.execute(q)).scalars())
    if ids:
        # L1-маркеры смен (sts-shift-*) — по натуральному ключу станция+номер смены
        # (meta.station_code + meta.shift_number). НЕ по fuel_shift_id: он
        # рассинхронизируется — маркер дедуплицируется по source_label и при
        # re-ingest не пересоздаётся, его fuel_shift_id остаётся от прежней смены
        # (с новым UUID). Так очистка реально матчит маркеры и «Обновить»
        # восстанавливает L1-слой.
        pairs = (await db.execute(
            select(FuelStation.code, FuelShift.shift_number)
            .join(FuelStation, FuelStation.id == FuelShift.station_id)
            .where(FuelShift.id.in_(ids))
        )).all()
        keys = [f"{code}|{num}" for code, num in pairs]
        if keys:
            await db.execute(delete(DataEntry).where(
                DataEntry.company_id == cid,
                DataEntry.source_label.like("sts-shift-%"),
                func.concat(DataEntry.meta["station_code"].astext, "|",
                            DataEntry.meta["shift_number"].astext).in_(keys),
            ))
        # Core DELETE: DB ON DELETE CASCADE для tanks/pumps/cash/sales,
        # FuelReceipt.shift_id → SET NULL. ORM-delete падал бы на NOT NULL FK.
        await db.execute(delete(FuelShift).where(FuelShift.id.in_(ids)))
    return {"deleted": len(ids), "kind": "shift"}


@router.get("/loaded-stations")
async def loaded_stations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Станции компании, по которым ЕСТЬ загруженные смены или ТТН — для выбора
    в диалоге «Удалить»/«Обновить». Вкладка «Загружено» показывает данные всей
    компании (не только станций канала), поэтому удалять нужно по любой из них."""
    cid = await _company_id(user, db)
    sh_ids = set((await db.execute(
        select(FuelShift.station_id).where(FuelShift.company_id == cid).distinct()
    )).scalars())
    rc_ids = set((await db.execute(
        select(FuelReceipt.station_id).where(FuelReceipt.company_id == cid).distinct()
    )).scalars())
    ids = sh_ids | rc_ids
    if not ids:
        return []
    stations = (await db.execute(
        select(FuelStation).where(FuelStation.id.in_(ids)))).scalars()
    return sorted(
        [{"code": s.code, "name": s.name} for s in stations],
        key=lambda x: x["code"],
    )


# ═══════════════════════════════════════════════════════════════
# ТТН
# ═══════════════════════════════════════════════════════════════

@router.get("/receipts", response_model=list[ReceiptOut])
async def list_receipts(
    station_code: int | None = Query(None),
    limit: int = Query(5000, le=20000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_id = await _company_id(user, db)
    q = select(FuelReceipt).where(FuelReceipt.company_id == company_id)
    if station_code is not None:
        q = q.join(FuelStation).where(FuelStation.code == station_code)
    q = q.order_by(FuelReceipt.created_at.desc()).limit(limit)
    rcpts = list((await db.execute(q)).scalars())
    st_ids = {r.station_id for r in rcpts}
    stations = {st.id: st for st in (await db.execute(
        select(FuelStation).where(FuelStation.id.in_(st_ids)))).scalars()} if st_ids else {}
    ov_map = await _load_receipt_overrides(db, company_id)
    cost_map = await _load_receipt_costs(db, company_id)
    return [
        _receipt_out(
            r, stations.get(r.station_id),
            ov_map.get((str(r.station_id), r.ttn, _receipt_fuel_key(r.fuel_code))),
            cost_map.get((str(r.station_id), r.ttn, _receipt_fuel_key(r.fuel_code))),
        )
        for r in rcpts
    ]


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
    return await ingest_fuel_shifts(body, company_id, db)


async def ingest_fuel_shifts(
    body: NormalizeRequest,
    company_id: uuid.UUID,
    db: AsyncSession,
    *,
    with_receipts: bool = True,
) -> dict:
    """Ядро fuel-ingest продаж (STS shift_report → FuelShift + L1-маркеры смен).

    Зовётся роутером /fuel/normalize и оркестратором канала продаж (fuel_shift).
    with_receipts: если False — ТТН (приём) НЕ создаются здесь; приём идёт
    отдельным каналом fuel_delivery через ingest_fuel_deliveries (как в расширении
    БП: ОбработатьСмену и ОбработатьТТН — раздельные ветки). По умолчанию True
    для обратной совместимости /fuel/normalize.
    """

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
            body.date_from, body.date_to,
        )
        # Клиентский фильтр периода: STS API не всегда фильтрует надёжно,
        # иначе загрузится вся история станции.
        if body.date_from:
            _df = body.date_from
            _dt = body.date_to or "9999-12-31"

            def _opened(s: dict) -> str:
                return str(s.get("dt_open") or s.get("opened") or s.get("dt") or "")[:10]

            shifts_to_process = [
                s for s in shifts_to_process if _df <= _opened(s) <= _dt
            ]

    # Маппинги оплат/каналов/топлива компании — применяются к секции sales.
    ctx = await load_mapping_context(db, company_id)

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

        # sales — раскладка по КАНАЛУ ОПЛАТЫ × виду топлива через маппинг
        # приложения (PaymentMapping/PaymentChannel). Эталон — TradeLedger.cfe:
        # канал определяется по pay_type.name (подстрока), НЕ по pay_type.id.
        # Общая логика с пересборкой (renormalize_shift_sales) + репейр обрезки
        # cost=1млн sales-блока STS — build_sales_agg.
        chan_agg = build_sales_agg(report, ctx)

        # legacy-агрегаты FuelShift (обратная совместимость UI): нал / карта / прочее
        cash = sum(a["amount"] for (ch, _), a in chan_agg.items() if ch == "retail_cash")
        card = sum(a["amount"] for (ch, _), a in chan_agg.items() if ch == "retail_card")
        voucher = sum(a["amount"] for (ch, _), a in chan_agg.items()
                      if ch not in ("retail_cash", "retail_card"))

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
            # Сырой отчёт STS как есть — для эталонного просмотрщика «Детали смены».
            raw_report=report,
        )
        db.add(shift)
        await db.flush()

        # Разбивка смены по каналам оплаты × топливу → FuelShiftSale (L2,
        # основа для построения документов 1С).
        for (channel, code), a in chan_agg.items():
            db.add(FuelShiftSale(
                company_id=company_id,
                shift_id=shift.id,
                payment_channel=channel,
                fuel_code=code,
                liters=a["liters"],
                amount=a["amount"],
                discount=a["discount"],
                warehouse_name=a["warehouse"],
            ))

        # Резервуары — из release[]
        for t in report.get("release", []):
            svc = t.get("service", {})
            doc_beg = t.get("doc_beg", {})
            doc_end = t.get("doc_end", {})
            rel = t.get("release", {})
            water = t.get("water", {}) or {}
            db.add(FuelTank(
                shift_id=shift.id,
                tank_number=t.get("tank", 0),
                fuel_type=svc.get("service_name", ""),
                fuel_code=_int_or_none(svc.get("service_code")),
                volume_start=float(doc_beg.get("volume", 0) or 0),
                volume_end=float(doc_end.get("volume", 0) or 0),
                sales=float(rel.get("volume", 0) or 0),
                volume_received=float((t.get("receipt", {}) or {}).get("volume", 0) or 0),
                density=_density(t.get("density_end")),
                density_beg=_density(t.get("density_beg")),
                temp_end=_num_or_none(t.get("temp_end")),
                level_end=_num_or_none(t.get("level_end")),
                water_level=_num_or_none(water.get("level")),
                water_volume=_num_or_none(water.get("volume")),
            ))

        # ТРК — из psm.data[] (счётчики, цена, плотность, резервуар)
        for p in report.get("psm", {}).get("data", []):
            svc = p.get("service", {})
            rel = p.get("release", {})
            db.add(FuelPump(
                shift_id=shift.id,
                pump_number=p.get("pump", 0),
                nozzle=str(p.get("nozzle", "")),
                fuel_type=svc.get("service_name", ""),
                fuel_code=_int_or_none(svc.get("service_code")),
                tank_number=_int_or_none(p.get("tank")),
                sales_volume=float(rel.get("volume", 0) or 0),
                amount=float(rel.get("cost", 0) or 0),
                psm_beg=_num_or_none(p.get("psm_beg")),
                psm_end=_num_or_none(p.get("psm_end")),
                price=_num_or_none(p.get("price")),
                density=_density(p.get("density")),
            ))

        # Движение наличных — из money[] (касса: остаток/выручка/инкассация)
        for m in report.get("money", []):
            op = m.get("operation", {}) or {}
            db.add(FuelCashMovement(
                shift_id=shift.id,
                operation_id=int(op.get("id", 0) or 0),
                operation_name=str(op.get("name", "") or ""),
                amount=float(m.get("volume", 0) or 0),
                pos_number=_int_or_none(m.get("pos")),
            ))

        # ТТН — из receipt[]. Только если with_receipts (для /fuel/normalize);
        # в канале продаж приём отключён — он идёт каналом fuel_delivery.
        for r in (report.get("receipt", []) if with_receipts else []):
            svc = r.get("service", {})
            _rc = svc.get("service_code")
            r_fuel_code = int(_rc) if _rc not in (None, "") else None
            r_ttn = (r.get("ttn") or "").strip()
            # Дедуп приёма по натуральному ключу (company, station, ttn, code) —
            # как в delivery-ветке. Иначе один физический ТТН задваивается между
            # shift-путём (/fuel/normalize) и каналом fuel_delivery.
            if r_ttn:
                _dup = (await db.execute(
                    select(FuelReceipt.id).where(
                        FuelReceipt.company_id == company_id,
                        FuelReceipt.station_id == station.id,
                        FuelReceipt.ttn == r_ttn,
                        FuelReceipt.fuel_code == r_fuel_code,
                    ).limit(1)
                )).scalar_one_or_none()
                if _dup:
                    continue
            doc = r.get("doc", {})
            fact = r.get("fact", {})
            doc_vol = float(doc.get("volume", 0))
            fact_vol = float(fact.get("volume", 0))
            doc_mass = float(doc.get("amount", 0))
            fact_mass = float(fact.get("amount", 0))

            db.add(FuelReceipt(
                company_id=company_id,
                station_id=station.id,
                shift_id=shift.id,
                shift_number=shift_num,
                tank=_int_or_none(r.get("tank")),
                ttn=r_ttn,
                fuel_name=svc.get("service_name", ""),
                fuel_code=r_fuel_code,
                supplier=r.get("base", {}).get("name", ""),
                doc_volume_liters=doc_vol,
                doc_mass_kg=doc_mass,
                doc_cost=0,
                fact_volume_liters=fact_vol,
                fact_mass_kg=fact_mass,
                fact_cost=0,
                density=_density(doc.get("density")),
                fact_density=_density(fact.get("density")),
                doc_temp=_num_or_none(doc.get("temp")),
                fact_temp=_num_or_none(fact.get("temp")),
                diff_volume=fact_vol - doc_vol,
                diff_mass=fact_mass - doc_mass,
                received_at=_parse_dt(r.get("dt")),
                status="new",
            ))

        # Раскладка по видам топлива из psm.total (для UI и сверки по литрам).
        # Каждый элемент psm.total — { service: {service_code, service_name},
        #                              release: {quantity (литры), amount (₽)} }
        fuel_breakdown = []
        for t in psm_total:
            svc = t.get("service") or {}
            rel = t.get("release") or {}
            code = str(svc.get("service_code") or "").strip()
            name = str(svc.get("service_name") or "").strip()
            if not code and not name:
                continue
            fuel_breakdown.append({
                "fuel_code":  code,
                "fuel_name":  name,
                "liters":     float(rel.get("quantity") or 0),
                "amount":     float(rel.get("amount") or 0),
            })

        # L1 DataEntry — копия смены в общую таблицу для 4-слойного reconcile.
        # Дедупликация по shift_id+station_code в meta (sts-api source).
        shift_l1_marker = f"sts-shift-{body.system_code}-{body.station_code}-{shift_num}"
        exists_l1 = (await db.execute(
            select(DataEntry).where(
                DataEntry.company_id == company_id,
                DataEntry.source_label == shift_l1_marker,
            ).limit(1)
        )).scalar_one_or_none()
        if not exists_l1:
            shift_date = shift.opened_at.date().isoformat() if shift.opened_at else ""
            db.add(DataEntry(
                id=uuid.uuid4(),
                title=f"Смена №{shift_num} АЗС {body.station_code} от {shift_date}",
                category_id="operational",
                subcategory_id="shifts",
                doc_type_id="shift_orp",
                company_id=company_id,
                status="recognized",
                source="api",
                source_label=shift_l1_marker,
                layer="raw",
                meta={
                    "shift_id":     str(shift_num),
                    "shift_number": str(shift_num),
                    "station_code": str(body.station_code),
                    "system_code":  str(body.system_code),
                    "shift_date":   shift_date,
                    "docDate":      shift_date,
                    "amount":       str(total_amount),
                    "totalAmount":  str(total_amount),
                    "totalLiters":  str(total_liters),
                    "cash":         str(cash),
                    "card":         str(card),
                    "voucher":      str(voucher),
                    "fuel_shift_id": str(shift.id),
                    # Разрез по видам нефтепродуктов — для UI и построчной сверки
                    # ОРП.ТЧ.Товары ↔ shift.fuel_breakdown через ReconcileMapping('fuel').
                    "fuel_breakdown": fuel_breakdown,
                },
            ))

        # L1 DataEntry per ТТН (для сверки ТТН-файл ↔ ПТУ) — только with_receipts.
        for r in (report.get("receipt", []) if with_receipts else []):
            ttn_no = (r.get("ttn") or "").strip()
            if not ttn_no:
                continue
            ttn_marker = f"sts-ttn-{body.station_code}-{shift_num}-{ttn_no}"
            exists_ttn = (await db.execute(
                select(DataEntry).where(
                    DataEntry.company_id == company_id,
                    DataEntry.source_label == ttn_marker,
                ).limit(1)
            )).scalar_one_or_none()
            if exists_ttn:
                continue
            doc = r.get("doc", {})
            fact = r.get("fact", {})
            svc = r.get("service", {})
            base = r.get("base", {})
            ttn_date = _parse_dt(r.get("dt"))
            ttn_date_iso = ttn_date.date().isoformat() if ttn_date else ""
            # Полная meta как в delivery-ветке: тонны + номенклатура т/л из маппинга
            # (иначе L1-маркер ТТН неконсистентен и не годен для документов/сверки).
            _tc = svc.get("service_code")
            _tfc = int(_tc) if _tc not in (None, "") else None
            _tfm = ctx.fuel(_tfc) if _tfc is not None else None
            _tdens = _density(doc.get("density") or fact.get("density"))
            if _tdens is None and _tfm is not None and _tfm.density is not None:
                _tdens = float(_tfm.density)
            _tmass = float(doc.get("amount", 0) or 0)
            _tvol = float(doc.get("volume", 0) or 0)
            if _tmass <= 0 and _tvol > 0 and _tdens:
                _tmass = round(_tvol * _tdens, 3)
            db.add(DataEntry(
                id=uuid.uuid4(),
                title=f"ТТН {ttn_no} · {svc.get('service_name', '')} · {base.get('name', '')}",
                category_id="primary",
                subcategory_id="ttn",
                doc_type_id="purchase_ttn",
                company_id=company_id,
                status="recognized",
                source="api",
                source_label=ttn_marker,
                layer="raw",
                meta={
                    "ttn_number":    ttn_no,
                    "docNumber":     ttn_no,
                    "ttn_date":      ttn_date_iso,
                    "docDate":       ttn_date_iso,
                    "supplier_name":    base.get("name", ""),
                    "supplier_base_id": str(base.get("id")) if base.get("id") is not None else "",
                    "fuel_name":     svc.get("service_name", ""),
                    "fuel_code":     str(svc.get("service_code", "") or ""),
                    "nomenclature_t": (_tfm.nomenclature_tonnes if _tfm else "") or "",
                    "nomenclature_l": (_tfm.nomenclature_liters if _tfm else "") or "",
                    "doc_volume_l":  str(doc.get("volume", 0)),
                    "doc_mass_kg":   str(doc.get("amount", 0)),
                    "doc_mass_t":    str(round(_tmass / 1000.0, 3)),
                    "fact_volume_l": str(fact.get("volume", 0)),
                    "fact_mass_kg":  str(fact.get("amount", 0)),
                    "density":       str(doc.get("density", "") or ""),
                    "station_code":  str(body.station_code),
                    "shift_id":      str(shift_num),
                },
            ))

        created += 1

    return {
        "created": created,
        "skipped": skipped,
        "station": station.name,
        "unmapped_paytypes": sorted(p for p in ctx.unmapped if p),
    }


async def ingest_fuel_deliveries(
    body: NormalizeRequest,
    company_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """Ядро fuel-ingest приёма (STS /v1/report/receipts → FuelReceipt + L1 ТТН).

    Отдельный канал fuel_delivery — зеркало ветки ОбработатьТТН расширения БП:
    приём топлива по ТТН → в БП это Перемещение(тонны, Дт 41.01) + Комплектация
    (литры, Дт 41.02) с пересчётом масса→объём по плотности. Здесь формируем L1:
    физический приём (FuelReceipt) + DataEntry-маркер с метаданными для двухзвенной
    проводки (масса в тоннах, плотность, объём в литрах, код топлива, поставщик).

    Идемпотентность по STS-тройке: sts-ttn-{system}-{station}-{ttn}[-{code}] —
    совпадает с нативным ключом .cfe TL|ТТН|система|станция|номер_ТТН[|код_топлива],
    что выравнивает cutover (без задвоения приёма на живой бухгалтерии).
    """
    # станция (get-or-create)
    station = (await db.execute(
        select(FuelStation).where(
            FuelStation.company_id == company_id,
            FuelStation.code == body.station_code,
        )
    )).scalar_one_or_none()
    if not station:
        station = FuelStation(
            company_id=company_id, code=body.station_code,
            name=f"АЗС №{body.station_code}", sts_system_code=body.system_code,
        )
        db.add(station)
        await db.flush()

    # смены периода — приём STS отдаётся в разрезе смен, перебираем их
    shifts = await sts_get_shifts(
        body.base_url, body.login, body.password,
        body.system_code, body.station_code, body.date_from, body.date_to,
    )
    if body.date_from:
        _df = body.date_from
        _dt = body.date_to or "9999-12-31"

        def _opened(s: dict) -> str:
            return str(s.get("dt_open") or s.get("opened") or s.get("dt") or "")[:10]

        shifts = [s for s in shifts if _df <= _opened(s) <= _dt]

    # Маппинг топлива компании: справочная плотность + номенклатура для документов
    ctx = await load_mapping_context(db, company_id)

    created = 0
    skipped = 0
    scanned = 0
    seen_keys: set[str] = set()

    for shift_info in shifts:
        shift_num = shift_info.get("shift")
        if shift_num is None:
            continue
        scanned += 1
        receipts = await sts_get_receipts(
            body.base_url, body.login, body.password,
            body.system_code, body.station_code, shift_num,
        )
        for r in receipts:
            ttn_no = str(r.get("ttn") or "").strip()
            if not ttn_no:
                continue
            svc = r.get("service") or {}
            code = svc.get("service_code")
            fuel_code = int(code) if code not in (None, "") else None

            marker = f"sts-ttn-{body.system_code}-{body.station_code}-{ttn_no}"
            if fuel_code is not None:
                marker += f"-{fuel_code}"
            if marker in seen_keys:
                continue
            seen_keys.add(marker)

            exists = (await db.execute(
                select(DataEntry).where(
                    DataEntry.company_id == company_id,
                    DataEntry.source_label == marker,
                ).limit(1)
            )).scalar_one_or_none()
            if exists:
                skipped += 1
                continue

            doc = r.get("doc") or {}
            fact = r.get("fact") or {}
            base = r.get("base") or {}
            doc_vol = float(doc.get("volume") or 0)    # литры
            doc_mass = float(doc.get("amount") or 0)   # кг
            fact_vol = float(fact.get("volume") or 0)
            fact_mass = float(fact.get("amount") or 0)
            fm = ctx.fuel(fuel_code)
            dens = _density(doc.get("density") or fact.get("density"))
            if dens is None and fm is not None and fm.density is not None:
                dens = float(fm.density)               # справочная плотность из маппинга
            ttn_dt = _parse_dt(r.get("dt"))
            ttn_date_iso = ttn_dt.date().isoformat() if ttn_dt else ""
            fuel_name = svc.get("service_name") or (fm.fuel_name if fm else "")
            supplier = base.get("name") or ""
            supplier_base_id = base.get("id")
            # масса: STS doc.amount (кг). Нет — считаем из объёма по плотности.
            if doc_mass <= 0 and doc_vol > 0 and dens:
                doc_mass = round(doc_vol * dens, 3)
            mass_t = round(doc_mass / 1000.0, 3)       # тонны для Перемещения (Дт 41.01)

            # физический приём — дедуп по (company, station, ttn, code)
            rcpt_exists = (await db.execute(
                select(FuelReceipt).where(
                    FuelReceipt.company_id == company_id,
                    FuelReceipt.station_id == station.id,
                    FuelReceipt.ttn == ttn_no,
                    FuelReceipt.fuel_code == fuel_code,
                ).limit(1)
            )).scalar_one_or_none()
            if not rcpt_exists:
                db.add(FuelReceipt(
                    company_id=company_id,
                    station_id=station.id,
                    shift_id=None,  # приём — событие поставки, не кассовая смена
                    shift_number=_int_or_none(r.get("shift")) or shift_num,
                    tank=_int_or_none(r.get("tank")),
                    ttn=ttn_no,
                    fuel_name=fuel_name,
                    fuel_code=fuel_code,
                    supplier=supplier,
                    doc_volume_liters=doc_vol,
                    doc_mass_kg=doc_mass,
                    doc_cost=0,
                    fact_volume_liters=fact_vol,
                    fact_mass_kg=fact_mass,
                    fact_cost=0,
                    density=dens,
                    fact_density=_density(fact.get("density")),
                    doc_temp=_num_or_none(doc.get("temp")),
                    fact_temp=_num_or_none(fact.get("temp")),
                    diff_volume=fact_vol - doc_vol,
                    diff_mass=fact_mass - doc_mass,
                    received_at=ttn_dt,
                    status="new",
                ))

            db.add(DataEntry(
                id=uuid.uuid4(),
                title=f"ТТН {ttn_no} · {fuel_name} · {supplier}",
                category_id="primary",
                subcategory_id="ttn",
                doc_type_id="purchase_ttn",
                company_id=company_id,
                status="recognized",
                source="api",
                source_label=marker,
                layer="raw",
                meta={
                    "ttn_number":    ttn_no,
                    "docNumber":     ttn_no,
                    "ttn_date":      ttn_date_iso,
                    "docDate":       ttn_date_iso,
                    "supplier_name":    supplier,
                    "supplier_base_id": str(supplier_base_id) if supplier_base_id is not None else "",
                    "fuel_name":        fuel_name,
                    "fuel_code":        str(code or ""),
                    "nomenclature_t":   (fm.nomenclature_tonnes if fm else "") or "",
                    "nomenclature_l":   (fm.nomenclature_liters if fm else "") or "",
                    "tank":          str(r.get("tank", "") or ""),
                    "doc_volume_l":  str(doc_vol),
                    "doc_mass_kg":   str(doc_mass),
                    "doc_mass_t":    str(mass_t),   # тонны → Перемещение (Дт 41.01)
                    "fact_volume_l": str(fact_vol),
                    "fact_mass_kg":  str(fact_mass),
                    "density":       str(dens if dens is not None else ""),
                    "station_code":  str(body.station_code),
                    "system_code":   str(body.system_code),
                    "shift":         str(shift_num),
                },
            ))
            created += 1

    return {"created": created, "skipped": skipped,
            "shifts_scanned": scanned, "station": station.name}


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _shift_out(s: FuelShift, station: FuelStation | None = None,
               has_corrections: bool = False) -> ShiftOut:
    return ShiftOut(
        id=str(s.id),
        station_id=str(s.station_id),
        station_code=station.code if station else 0,
        station_name=station.name if station else None,
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
        has_corrections=has_corrections,
        created_at=s.created_at,
    )


def _receipt_fuel_key(fuel_code: int | None) -> int:
    """Нормализация fuel_code для натурального ключа override (NULL → -1)."""
    return fuel_code if fuel_code is not None else -1


def _receipt_out(
    r: FuelReceipt, station: FuelStation | None = None,
    ov: "FuelReceiptOverride | None" = None,
    cost: "FuelReceiptCost | None" = None,
) -> ReceiptOut:
    doc_vol = float(r.doc_volume_liters or 0)
    doc_mass = float(r.doc_mass_kg or 0)
    dens = float(r.density) if r.density else None
    return ReceiptOut(
        id=str(r.id),
        station_id=str(r.station_id),
        station_code=station.code if station else 0,
        station_name=station.name if station else None,
        ttn=r.ttn,
        fuel_name=r.fuel_name,
        fuel_code=r.fuel_code,
        supplier=r.supplier,
        shift_number=r.shift_number,
        tank=r.tank,
        doc_volume_liters=float(ov.doc_volume_liters) if ov and ov.doc_volume_liters is not None else doc_vol,
        fact_volume_liters=float(r.fact_volume_liters or 0),
        diff_volume=float(r.diff_volume or 0),
        doc_mass_kg=float(ov.doc_mass_kg) if ov and ov.doc_mass_kg is not None else doc_mass,
        fact_mass_kg=float(r.fact_mass_kg or 0),
        diff_mass=float(r.diff_mass or 0),
        density=(float(ov.density) if ov and ov.density is not None else dens),
        fact_density=float(r.fact_density) if r.fact_density else None,
        doc_temp=float(r.doc_temp) if r.doc_temp is not None else None,
        fact_temp=float(r.fact_temp) if r.fact_temp is not None else None,
        status=r.status,
        received_at=r.received_at,
        created_at=r.created_at,
        is_manual=ov is not None,
        has_corrections=ov is not None and (
            (ov.doc_volume_liters is not None and abs(float(ov.doc_volume_liters) - doc_vol) > 0.005)
            or (ov.doc_mass_kg is not None and abs(float(ov.doc_mass_kg) - doc_mass) > 0.005)
            or (ov.density is not None and dens is not None and abs(float(ov.density) - dens) > 0.005)
            or bool(ov.note and ov.note.strip())
        ),
        src_volume=doc_vol if ov is not None else None,
        src_mass=doc_mass if ov is not None else None,
        src_density=dens if ov is not None else None,
        note=ov.note if ov is not None else None,
        has_cost=cost is not None,
        cost_unit=cost.unit if cost is not None else None,
        cost_unit_price=float(cost.unit_cost) if cost is not None else None,
        cost_per_liter=float(cost.cost_per_liter) if cost is not None else None,
    )


async def _load_receipt_overrides(
    db: AsyncSession, company_id: uuid.UUID
) -> dict[tuple[str, str, int], FuelReceiptOverride]:
    """Корректировки ТТН компании, ключ (station_id, ttn, fuel_code)."""
    rows = (await db.execute(select(FuelReceiptOverride).where(
        FuelReceiptOverride.company_id == company_id))).scalars().all()
    return {(str(o.station_id), o.ttn, o.fuel_code): o for o in rows}


async def _load_receipt_costs(
    db: AsyncSession, company_id: uuid.UUID
) -> dict[tuple[str, str, int], FuelReceiptCost]:
    """Себестоимость партий (ТТН) компании, ключ (station_id, ttn, fuel_code)."""
    rows = (await db.execute(select(FuelReceiptCost).where(
        FuelReceiptCost.company_id == company_id))).scalars().all()
    return {(str(c.station_id), c.ttn, c.fuel_code): c for c in rows}


# ═══════════════════════════════════════════════════════════════
# Документы 1С из смены/ТТН (конвейер L2 → пакеты для БП)
# ═══════════════════════════════════════════════════════════════

async def _load_sale_overrides(
    db: AsyncSession, company_id: uuid.UUID, station_id: uuid.UUID, shift_number: int
) -> dict[tuple[str, int], FuelShiftSaleOverride]:
    """Ручные корректировки строк продаж смены (L2 CLEAN) по натуральному ключу."""
    rows = (await db.execute(
        select(FuelShiftSaleOverride).where(
            FuelShiftSaleOverride.company_id == company_id,
            FuelShiftSaleOverride.station_id == station_id,
            FuelShiftSaleOverride.shift_number == shift_number,
        )
    )).scalars().all()
    return {(o.payment_channel, o.fuel_code): o for o in rows}


def _apply_sale_override(sale: dict, ov: "FuelShiftSaleOverride | None") -> dict:
    """Наложить корректировку на строку продаж (NULL-показатели в override не трогают)."""
    if ov is None:
        return sale
    if ov.liters is not None:
        sale["liters"] = float(ov.liters)
    if ov.amount is not None:
        sale["amount"] = float(ov.amount)
    if ov.discount is not None:
        sale["discount"] = float(ov.discount)
    if ov.warehouse_name is not None:
        sale["warehouse_name"] = ov.warehouse_name
    return sale


def _sale_out_with_override(s: FuelShiftSale, ov: "FuelShiftSaleOverride | None") -> ShiftSaleOut:
    """ShiftSaleOut с наложенной корректировкой (+ исходные src_* и флаг is_manual)."""
    liters = float(s.liters or 0)
    amount = float(s.amount or 0)
    discount = float(s.discount or 0)
    if ov is None:
        return ShiftSaleOut(
            payment_channel=s.payment_channel, fuel_code=s.fuel_code,
            liters=liters, amount=amount, discount=discount,
            warehouse_name=s.warehouse_name,
        )
    return ShiftSaleOut(
        payment_channel=s.payment_channel, fuel_code=s.fuel_code,
        liters=float(ov.liters) if ov.liters is not None else liters,
        amount=float(ov.amount) if ov.amount is not None else amount,
        discount=float(ov.discount) if ov.discount is not None else discount,
        warehouse_name=ov.warehouse_name or s.warehouse_name,
        is_manual=True,
        src_liters=liters, src_amount=amount, src_discount=discount,
        note=ov.note,
    )


async def _build_shift_docs(db: AsyncSession, shift: FuelShift, company_id: uuid.UUID) -> list[dict]:
    """Построить документы 1С из разбивки смены (FuelShiftSale + корректировки L2)."""
    station = await db.get(FuelStation, shift.station_id)
    ctx = await load_mapping_context(db, company_id)
    fuel_by_code = {
        code: {"fuel_name": fm.fuel_name,
               "nomenclature_tonnes": fm.nomenclature_tonnes,
               "nomenclature_liters": fm.nomenclature_liters}
        for code, fm in ctx.fuel_by_code.items()
    }
    channels_by_code = {
        c.code: {"requires_transfer": c.requires_transfer,
                 "warehouse_name": c.warehouse_name, "name": c.name}
        for c in ctx.channels.values()
    }
    rows = (await db.execute(
        select(FuelShiftSale).where(FuelShiftSale.shift_id == shift.id)
    )).scalars().all()
    ov_map = await _load_sale_overrides(db, company_id, shift.station_id, shift.shift_number)
    sales = [_apply_sale_override(
                {"payment_channel": s.payment_channel, "fuel_code": s.fuel_code,
                 "liters": float(s.liters or 0), "amount": float(s.amount or 0),
                 "discount": float(s.discount or 0), "warehouse_name": s.warehouse_name},
                ov_map.get((s.payment_channel, s.fuel_code)))
             for s in rows]
    return build_shift_documents(
        system=station.sts_system_code or 15,
        station_code=station.code,
        shift_number=shift.shift_number,
        shift_date=shift.opened_at.date().isoformat() if shift.opened_at else "",
        warehouse_azs=station.name,
        sales=sales,
        fuel_by_code=fuel_by_code,
        channels_by_code=channels_by_code,
    )


async def _build_receipt_docs(db: AsyncSession, receipt: FuelReceipt, company_id: uuid.UUID) -> list[dict]:
    """Построить документы 1С из ТТН (Перемещение тонн + Комплектация) с корректировками L2."""
    station = await db.get(FuelStation, receipt.station_id)
    ctx = await load_mapping_context(db, company_id)
    fm = ctx.fuel(receipt.fuel_code) if receipt.fuel_code is not None else None
    # Ручная корректировка ТТН перед выгрузкой (L2): объём/масса/плотность документа.
    ov = (await db.execute(select(FuelReceiptOverride).where(
        FuelReceiptOverride.company_id == company_id,
        FuelReceiptOverride.station_id == receipt.station_id,
        FuelReceiptOverride.ttn == receipt.ttn,
        FuelReceiptOverride.fuel_code == _receipt_fuel_key(receipt.fuel_code),
    ).limit(1))).scalar_one_or_none()
    # Тонны для документов: из массы ТТН, а при её отсутствии — из объёма×плотности
    # (плотность ТТН или справочная из маппинга). Иначе ТТН без массы не дала бы
    # НИ ОДНОГО документа (гард tonnes>0 в build_ttn_documents).
    liters = float(ov.doc_volume_liters) if ov and ov.doc_volume_liters is not None else float(receipt.doc_volume_liters or 0)
    mass_kg = float(ov.doc_mass_kg) if ov and ov.doc_mass_kg is not None else float(receipt.doc_mass_kg or 0)
    dens = float(ov.density) if ov and ov.density is not None else (
        float(receipt.density) if receipt.density else (
            float(fm.density) if (fm and fm.density is not None) else None))
    if mass_kg <= 0 and liters > 0 and dens:
        mass_kg = round(liters * dens, 3)
    return build_ttn_documents(
        system=station.sts_system_code or 15,
        station_code=station.code,
        ttn=receipt.ttn,
        fuel_code=receipt.fuel_code or 0,
        nomenclature_t=(fm.nomenclature_tonnes if fm else "") or "",
        nomenclature_l=(fm.nomenclature_liters if fm else "") or "",
        tonnes=round(mass_kg / 1000.0, 3),
        liters=liters,
        ttn_date=receipt.received_at.date().isoformat() if receipt.received_at else "",
        warehouse_azs=station.name,
    )


async def _materialize_packets(
    db: AsyncSession, company_id: uuid.UUID, docs: list[dict], source_ids: list[str]
) -> dict:
    """Upsert документов в ExportPacket по натуральному ключу (idem_key)."""
    created = updated = 0
    for d in docs:
        pkt = (await db.execute(
            select(ExportPacket).where(
                ExportPacket.company_id == company_id,
                ExportPacket.idem_key == d["idem_key"],
                ExportPacket.status != "rejected",
            ).limit(1)
        )).scalar_one_or_none()
        if pkt is not None:
            pkt.payload = d["payload"]
            pkt.kind = d["kind"]
            updated += 1
        else:
            db.add(ExportPacket(
                company_id=company_id, kind=d["kind"], idem_key=d["idem_key"],
                payload=d["payload"], source_entry_ids=source_ids, status="draft",
            ))
            created += 1
    await db.commit()
    return {"created": created, "updated": updated, "total": len(docs)}


@router.get("/shifts/{shift_id}/documents")
async def preview_shift_documents(
    shift_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Предпросмотр документов 1С, которые сформирует смена (без сохранения)."""
    cid = await _company_id(user, db)
    shift = await db.get(FuelShift, uuid.UUID(shift_id))
    if shift is None or shift.company_id != cid:
        raise HTTPException(404, "Смена не найдена")
    docs = await _build_shift_docs(db, shift, cid)
    return {"shift_id": shift_id, "count": len(docs), "documents": docs}


@router.post("/shifts/{shift_id}/build-packets")
async def build_shift_packets(
    shift_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Материализовать документы смены в ExportPacket (очередь для БП ГИГ)."""
    cid = await _company_id(user, db)
    shift = await db.get(FuelShift, uuid.UUID(shift_id))
    if shift is None or shift.company_id != cid:
        raise HTTPException(404, "Смена не найдена")
    docs = await _build_shift_docs(db, shift, cid)
    return await _materialize_packets(db, cid, docs, [shift_id])


class SaleEdit(BaseModel):
    """Корректировка одной строки продаж смены (канал оплаты × топливо).
    NULL-показатель = не переопределён (берётся исходное STS-значение)."""
    payment_channel: str
    fuel_code: int
    liters: float | None = None
    amount: float | None = None
    discount: float | None = None
    warehouse_name: str | None = None
    note: str | None = None


@router.patch("/shifts/{shift_id}/sales")
async def patch_shift_sales(
    shift_id: str,
    edits: list[SaleEdit],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ручная корректировка строк продаж смены (слой L2 CLEAN).

    Правки хранятся в отдельном override-слое по натуральному ключу смены —
    переживают «Обновить период» (delete+reingest) и накладываются при построении
    документов 1С. Для применения к очереди — повторить build-packets.
    """
    cid = await _company_id(user, db)
    shift = await db.get(FuelShift, uuid.UUID(shift_id))
    if shift is None or shift.company_id != cid:
        raise HTTPException(404, "Смена не найдена")
    if shift.is_locked:
        raise HTTPException(409, "Смена в закрытом периоде — корректировка запрещена")

    # Исходные STS-значения (для снимка src_* и сравнения — правка ли).
    base = {(s.payment_channel, s.fuel_code): s for s in (await db.execute(
        select(FuelShiftSale).where(FuelShiftSale.shift_id == shift.id))).scalars().all()}
    existing = await _load_sale_overrides(db, cid, shift.station_id, shift.shift_number)

    _EPS = 0.005  # порог сравнения (копейки/мл) — float STS vs введённое

    def _diff(new: float | None, src: float | None) -> bool:
        """Изменено ли поле относительно STS (None во вводе = поле не правится)."""
        return new is not None and (src is None or abs(float(new) - float(src)) > _EPS)

    changed = 0
    for e in edits:
        key = (e.payment_channel, e.fuel_code)
        src = base.get(key)
        s_lit = float(src.liters) if src and src.liters is not None else None
        s_amt = float(src.amount) if src and src.amount is not None else None
        s_dis = float(src.discount) if src and src.discount is not None else None
        # Поля, реально отличающиеся от STS (остальные не считаются правкой).
        f_lit = e.liters if _diff(e.liters, s_lit) else None
        f_amt = e.amount if _diff(e.amount, s_amt) else None
        f_dis = e.discount if _diff(e.discount, s_dis) else None
        f_wh = e.warehouse_name if (e.warehouse_name is not None
                                    and e.warehouse_name != (src.warehouse_name if src else None)) else None
        has_change = f_lit is not None or f_amt is not None or f_dis is not None or f_wh is not None

        ov = existing.get(key)
        if not has_change:
            # Значения вернулись к STS — правки нет: убрать прежний ложный override.
            if ov is not None:
                await db.delete(ov)
            continue
        if ov is None:
            ov = FuelShiftSaleOverride(
                company_id=cid, station_id=shift.station_id,
                shift_number=shift.shift_number,
                payment_channel=e.payment_channel, fuel_code=e.fuel_code,
                src_liters=s_lit, src_amount=s_amt, src_discount=s_dis,
            )
            db.add(ov)
        # В override — только изменённые поля (NULL = берётся из STS при наложении).
        ov.liters = f_lit
        ov.amount = f_amt
        ov.discount = f_dis
        if f_wh is not None:
            ov.warehouse_name = f_wh
        if e.note is not None:
            ov.note = e.note
        changed += 1

    if changed and shift.status == "new":
        shift.status = "verified"
    await db.commit()
    return {"ok": True, "changed": changed}


@router.delete("/shifts/{shift_id}/sales/override")
async def reset_shift_sale_overrides(
    shift_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Откатить все ручные корректировки смены к исходным STS-значениям."""
    cid = await _company_id(user, db)
    shift = await db.get(FuelShift, uuid.UUID(shift_id))
    if shift is None or shift.company_id != cid:
        raise HTTPException(404, "Смена не найдена")
    res = await db.execute(
        delete(FuelShiftSaleOverride).where(
            FuelShiftSaleOverride.company_id == cid,
            FuelShiftSaleOverride.station_id == shift.station_id,
            FuelShiftSaleOverride.shift_number == shift.shift_number,
        )
    )
    # Полный сброс — убрать и комментарий корректировки
    await db.execute(
        delete(FuelShiftCorrectionNote).where(
            FuelShiftCorrectionNote.company_id == cid,
            FuelShiftCorrectionNote.station_id == shift.station_id,
            FuelShiftCorrectionNote.shift_number == shift.shift_number,
        )
    )
    await db.commit()
    return {"ok": True, "removed": res.rowcount}


class ShiftNoteEdit(BaseModel):
    note: str


@router.put("/shifts/{shift_id}/correction-note")
async def put_shift_correction_note(
    shift_id: str,
    body: ShiftNoteEdit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Комментарий менеджера по корректировке смены (в целом по документу).

    Пустой текст удаляет комментарий. Хранится по натуральному ключу смены — переживает reingest.
    """
    cid = await _company_id(user, db)
    shift = await db.get(FuelShift, uuid.UUID(shift_id))
    if shift is None or shift.company_id != cid:
        raise HTTPException(404, "Смена не найдена")
    text = (body.note or "").strip()[:2000]
    existing = (await db.execute(select(FuelShiftCorrectionNote).where(
        FuelShiftCorrectionNote.company_id == cid,
        FuelShiftCorrectionNote.station_id == shift.station_id,
        FuelShiftCorrectionNote.shift_number == shift.shift_number,
    ))).scalar_one_or_none()
    if not text:
        if existing is not None:
            await db.delete(existing)
        await db.commit()
        return {"ok": True, "note": "", "author": None}
    author = getattr(user, "full_name", None) or getattr(user, "name", None) or user.email
    if existing is None:
        existing = FuelShiftCorrectionNote(
            company_id=cid, station_id=shift.station_id,
            shift_number=shift.shift_number, note=text, author=author,
        )
        db.add(existing)
    else:
        existing.note = text
        existing.author = author
    await db.commit()
    return {"ok": True, "note": text, "author": author}


@router.get("/receipts/{receipt_id}/documents")
async def preview_receipt_documents(
    receipt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Предпросмотр документов 1С из ТТН (Перемещение тонн + Комплектация)."""
    cid = await _company_id(user, db)
    rcpt = await db.get(FuelReceipt, uuid.UUID(receipt_id))
    if rcpt is None or rcpt.company_id != cid:
        raise HTTPException(404, "ТТН не найдена")
    docs = await _build_receipt_docs(db, rcpt, cid)
    return {"receipt_id": receipt_id, "count": len(docs), "documents": docs}


@router.post("/receipts/{receipt_id}/build-packets")
async def build_receipt_packets(
    receipt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Материализовать документы ТТН в ExportPacket."""
    cid = await _company_id(user, db)
    rcpt = await db.get(FuelReceipt, uuid.UUID(receipt_id))
    if rcpt is None or rcpt.company_id != cid:
        raise HTTPException(404, "ТТН не найдена")
    docs = await _build_receipt_docs(db, rcpt, cid)
    return await _materialize_packets(db, cid, docs, [receipt_id])


class ReceiptEdit(BaseModel):
    """Корректировка ТТН перед выгрузкой (значения документа: объём/масса/плотность).
    NULL-показатель = не переопределён (берётся исходное STS-значение)."""
    doc_volume_liters: float | None = None
    doc_mass_kg: float | None = None
    density: float | None = None
    note: str | None = None


@router.patch("/receipts/{receipt_id}/override")
async def patch_receipt_override(
    receipt_id: str,
    edit: ReceiptEdit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ручная корректировка значений ТТН (L2 CLEAN) перед выгрузкой в 1С.

    Правки хранятся в override-слое по натуральному ключу ТТН — переживают
    reingest и накладываются при построении документов (Перемещение тонн +
    Комплектация). Для применения к очереди — повторить build-packets.
    """
    cid = await _company_id(user, db)
    rcpt = await db.get(FuelReceipt, uuid.UUID(receipt_id))
    if rcpt is None or rcpt.company_id != cid:
        raise HTTPException(404, "ТТН не найдена")
    if rcpt.is_locked:
        raise HTTPException(409, "ТТН в закрытом периоде — корректировка запрещена")
    fkey = _receipt_fuel_key(rcpt.fuel_code)
    ov = (await db.execute(select(FuelReceiptOverride).where(
        FuelReceiptOverride.company_id == cid,
        FuelReceiptOverride.station_id == rcpt.station_id,
        FuelReceiptOverride.ttn == rcpt.ttn,
        FuelReceiptOverride.fuel_code == fkey,
    ).limit(1))).scalar_one_or_none()

    _EPS = 0.005
    src_vol = float(rcpt.doc_volume_liters or 0)
    src_mass = float(rcpt.doc_mass_kg or 0)
    src_dens = float(rcpt.density) if rcpt.density else None

    def _diff(new: float | None, src: float | None) -> bool:
        return new is not None and (src is None or abs(float(new) - float(src)) > _EPS)

    # В override — только поля, реально отличные от STS (NULL = берётся из STS).
    f_vol = edit.doc_volume_liters if _diff(edit.doc_volume_liters, src_vol) else None
    f_mass = edit.doc_mass_kg if _diff(edit.doc_mass_kg, src_mass) else None
    f_dens = edit.density if _diff(edit.density, src_dens) else None
    note = (edit.note or "").strip()[:500] or None
    has_change = f_vol is not None or f_mass is not None or f_dens is not None or note is not None

    if not has_change:
        # Ни правки значений, ни комментария — убрать прежний (в т.ч. ложный) override.
        if ov is not None:
            await db.delete(ov)
        await db.commit()
        return {"ok": True}
    if ov is None:
        ov = FuelReceiptOverride(
            company_id=cid, station_id=rcpt.station_id, ttn=rcpt.ttn, fuel_code=fkey,
            src_volume=src_vol, src_mass=src_mass, src_density=src_dens,
        )
        db.add(ov)
    ov.doc_volume_liters = f_vol
    ov.doc_mass_kg = f_mass
    ov.density = f_dens
    ov.note = note
    if (f_vol is not None or f_mass is not None or f_dens is not None) and rcpt.status == "new":
        rcpt.status = "verified"
    await db.commit()
    return {"ok": True}


@router.delete("/receipts/{receipt_id}/override")
async def reset_receipt_override(
    receipt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Откатить корректировку ТТН к исходным STS-значениям."""
    cid = await _company_id(user, db)
    rcpt = await db.get(FuelReceipt, uuid.UUID(receipt_id))
    if rcpt is None or rcpt.company_id != cid:
        raise HTTPException(404, "ТТН не найдена")
    res = await db.execute(delete(FuelReceiptOverride).where(
        FuelReceiptOverride.company_id == cid,
        FuelReceiptOverride.station_id == rcpt.station_id,
        FuelReceiptOverride.ttn == rcpt.ttn,
        FuelReceiptOverride.fuel_code == _receipt_fuel_key(rcpt.fuel_code),
    ))
    await db.commit()
    return {"ok": True, "removed": res.rowcount}


class CostEdit(BaseModel):
    """Себестоимость партии ТТН. unit: 'liter' (₽/л) | 'kg' (₽/кг, пересчёт по плотности)."""
    unit: str = "liter"
    unit_cost: float
    density: float | None = None  # для ₽/кг; если пусто — берётся плотность ТТН
    note: str | None = None


@router.patch("/receipts/{receipt_id}/cost")
async def patch_receipt_cost(
    receipt_id: str,
    edit: CostEdit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Задать себестоимость партии (ТТН) — ₽/л или ₽/кг. Нормализуется в ₽/л для FIFO-маржи."""
    cid = await _company_id(user, db)
    rcpt = await db.get(FuelReceipt, uuid.UUID(receipt_id))
    if rcpt is None or rcpt.company_id != cid:
        raise HTTPException(404, "ТТН не найдена")
    dens = edit.density or (float(rcpt.density) if rcpt.density else None)
    if edit.unit == "kg":
        if not dens:
            raise HTTPException(422, "Для ₽/кг нужна плотность (в ТТН нет — укажите вручную)")
        cost_per_liter = round(edit.unit_cost * dens, 4)   # ₽/кг × кг/л = ₽/л
    else:
        cost_per_liter = round(edit.unit_cost, 4)
    fkey = _receipt_fuel_key(rcpt.fuel_code)
    row = (await db.execute(select(FuelReceiptCost).where(
        FuelReceiptCost.company_id == cid,
        FuelReceiptCost.station_id == rcpt.station_id,
        FuelReceiptCost.ttn == rcpt.ttn,
        FuelReceiptCost.fuel_code == fkey,
    ).limit(1))).scalar_one_or_none()
    if row is None:
        row = FuelReceiptCost(company_id=cid, station_id=rcpt.station_id, ttn=rcpt.ttn, fuel_code=fkey)
        db.add(row)
    row.unit = edit.unit
    row.unit_cost = edit.unit_cost
    row.density_used = dens
    row.cost_per_liter = cost_per_liter
    row.source = "manual"
    if edit.note is not None:
        row.note = edit.note
    await db.commit()
    return {"ok": True, "cost_per_liter": cost_per_liter}


@router.delete("/receipts/{receipt_id}/cost")
async def delete_receipt_cost(
    receipt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Убрать себестоимость партии (ТТН)."""
    cid = await _company_id(user, db)
    rcpt = await db.get(FuelReceipt, uuid.UUID(receipt_id))
    if rcpt is None or rcpt.company_id != cid:
        raise HTTPException(404, "ТТН не найдена")
    res = await db.execute(delete(FuelReceiptCost).where(
        FuelReceiptCost.company_id == cid,
        FuelReceiptCost.station_id == rcpt.station_id,
        FuelReceiptCost.ttn == rcpt.ttn,
        FuelReceiptCost.fuel_code == _receipt_fuel_key(rcpt.fuel_code),
    ))
    await db.commit()
    return {"ok": True, "removed": res.rowcount}


@router.get("/costing/margin")
async def costing_margin(
    date_from: str = Query(...),
    date_to: str = Query(...),
    group_by: str = Query("fuel"),   # fuel | payment | station | month | fuel_payment
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Управленческая маржа по FIFO-себестоимости партий (по разрезам).
    Независимо от проводок 1С: продажи − себестоимость партий (ТТН), списанная по ФИФО."""
    cid = await _company_id(user, db)
    svc = FuelCostingService(db, cid)
    return await svc.compute(date.fromisoformat(date_from), date.fromisoformat(date_to), group_by)


@router.get("/costing/decision-dashboard")
async def costing_decision_dashboard(
    company_id: str = Query(...),
    date_from: str = Query(...),
    date_to: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FIFO-маржа и ценовые разрезы для управленческих решений."""
    cid = await assert_company_member(company_id, user, db)
    period_from = date.fromisoformat(date_from)
    period_to = date.fromisoformat(date_to)
    if period_from > period_to:
        raise HTTPException(422, "Начало периода позже окончания")
    svc = FuelCostingService(db, cid)
    return await svc.decision_dashboard(period_from, period_to)


@router.get("/costing/opening-balances")
async def costing_opening_balances(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Входящие остатки по АЗС × топливо перед началом загруженной истории."""
    cid = await _company_id(user, db)
    rows = (await db.execute(select(FuelOpeningBalance).where(
        FuelOpeningBalance.company_id == cid
    ).order_by(FuelOpeningBalance.as_of, FuelOpeningBalance.station_id,
               FuelOpeningBalance.fuel_code))).scalars().all()
    stations = {station.id: station for station in (await db.execute(select(FuelStation).where(
        FuelStation.company_id == cid))).scalars().all()}
    ctx = await load_mapping_context(db, cid)
    result = []
    for row in rows:
        station = stations.get(row.station_id)
        fuel = ctx.fuel(row.fuel_code)
        result.append({
            "id": str(row.id),
            "station_id": str(row.station_id),
            "station_code": station.code if station else None,
            "station_name": station.name if station else str(row.station_id),
            "fuel_code": row.fuel_code,
            "fuel_name": (fuel.fuel_name if fuel else None) or f"Код {row.fuel_code}",
            "as_of": row.as_of.isoformat(),
            "liters": float(row.liters or 0),
            "cost_per_liter": float(row.cost_per_liter or 0),
            "value": round(float(row.liters or 0) * float(row.cost_per_liter or 0), 2),
            "source": row.source,
            "note": row.note,
        })
    return {
        "rows": result,
        "totals": {
            "count": len(result),
            "liters": round(sum(row["liters"] for row in result), 3),
            "value": round(sum(row["value"] for row in result), 2),
        },
    }


@router.post("/costing/opening-balances/auto")
async def recalculate_costing_opening_balances(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Пересчитать минимальные входящие остатки по загруженной истории FIFO."""
    cid = await _company_id(user, db)
    result = await FuelCostingService(db, cid).recalculate_opening_balances()
    await db.commit()
    return {"ok": True, **result}


@router.get("/receipts/{receipt_id}/costing")
async def receipt_costing(
    receipt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Показатели партии (ТТН): списано/остаток/средняя цена реализации/маржа (FIFO)."""
    cid = await _company_id(user, db)
    rcpt = await db.get(FuelReceipt, uuid.UUID(receipt_id))
    if rcpt is None or rcpt.company_id != cid:
        raise HTTPException(404, "ТТН не найдена")
    svc = FuelCostingService(db, cid)
    return await svc.batch_stats(rcpt)


# ═══════════════════════════════════════════════════════════════
# Закупочные партии (Шаг 2): крупная закупка → FIFO-распределение на ТТН АЗС
# ═══════════════════════════════════════════════════════════════

class PurchaseBatchCreate(BaseModel):
    supplier: str | None = None
    fuel_code: int
    fuel_name: str | None = None
    total_liters: float
    unit: str = "liter"           # 'liter' | 'kg'
    unit_cost: float
    density: float | None = None  # для ₽/кг
    purchase_date: str | None = None
    target_station_ids: list[str] = []
    note: str | None = None


class PurchaseBatchOut(BaseModel):
    id: str
    supplier: str | None = None
    fuel_code: int
    fuel_name: str | None = None
    total_liters: float
    unit: str
    unit_cost: float
    cost_per_liter: float
    density: float | None = None
    purchase_date: str | None = None
    target_station_ids: list[str] = []
    status: str
    allocated_liters: float
    note: str | None = None


def _batch_out(b: FuelPurchaseBatch) -> PurchaseBatchOut:
    return PurchaseBatchOut(
        id=str(b.id), supplier=b.supplier, fuel_code=b.fuel_code, fuel_name=b.fuel_name,
        total_liters=float(b.total_liters or 0), unit=b.unit, unit_cost=float(b.unit_cost or 0),
        cost_per_liter=float(b.cost_per_liter or 0),
        density=float(b.density) if b.density else None,
        purchase_date=b.purchase_date.isoformat() if b.purchase_date else None,
        target_station_ids=list(b.target_station_ids or []),
        status=b.status, allocated_liters=float(b.allocated_liters or 0), note=b.note,
    )


@router.get("/purchase-batches", response_model=list[PurchaseBatchOut])
async def list_purchase_batches(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company_id(user, db)
    rows = (await db.execute(select(FuelPurchaseBatch).where(
        FuelPurchaseBatch.company_id == cid)
        .order_by(FuelPurchaseBatch.created_at.desc()))).scalars().all()
    return [_batch_out(b) for b in rows]


@router.post("/purchase-batches", response_model=PurchaseBatchOut)
async def create_purchase_batch(
    body: PurchaseBatchCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Завести закупочную партию. cost_per_liter нормализуется (₽/кг × плотность → ₽/л)."""
    cid = await _company_id(user, db)
    dens = body.density
    if body.unit == "kg":
        if not dens:
            raise HTTPException(422, "Для ₽/кг нужна плотность")
        cost_per_liter = round(body.unit_cost * dens, 4)
    else:
        cost_per_liter = round(body.unit_cost, 4)
    b = FuelPurchaseBatch(
        company_id=cid, supplier=body.supplier, fuel_code=body.fuel_code, fuel_name=body.fuel_name,
        total_liters=body.total_liters, unit=body.unit, unit_cost=body.unit_cost,
        cost_per_liter=cost_per_liter, density=dens,
        purchase_date=_parse_dt(body.purchase_date),
        target_station_ids=body.target_station_ids, note=body.note, status="draft",
    )
    db.add(b)
    await db.commit()
    await db.refresh(b)
    return _batch_out(b)


@router.delete("/purchase-batches/{batch_id}")
async def delete_purchase_batch(
    batch_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удалить закупочную партию и снять созданную ею себестоимость с ТТН."""
    cid = await _company_id(user, db)
    b = await db.get(FuelPurchaseBatch, uuid.UUID(batch_id))
    if b is None or b.company_id != cid:
        raise HTTPException(404, "Партия не найдена")
    await db.execute(delete(FuelReceiptCost).where(
        FuelReceiptCost.company_id == cid,
        FuelReceiptCost.purchase_batch_id == b.id))
    await db.delete(b)
    await db.commit()
    return {"ok": True}


@router.post("/purchase-batches/{batch_id}/allocate")
async def allocate_purchase_batch(
    batch_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Распределить объём закупки на ТТН выбранных АЗС по ФИФО (по дате поступления):
    покрытые ТТН получают себестоимость партии (FuelReceiptCost source='purchase_batch')."""
    cid = await _company_id(user, db)
    b = await db.get(FuelPurchaseBatch, uuid.UUID(batch_id))
    if b is None or b.company_id != cid:
        raise HTTPException(404, "Партия не найдена")
    try:
        station_uuids = [uuid.UUID(s) for s in (b.target_station_ids or [])]
    except (ValueError, TypeError):
        station_uuids = []
    if not station_uuids:
        raise HTTPException(422, "Не выбраны АЗС для распределения")

    receipt_filters = [
        FuelReceipt.company_id == cid,
        FuelReceipt.station_id.in_(station_uuids),
        FuelReceipt.fuel_code == b.fuel_code,
    ]
    if b.purchase_date is not None:
        receipt_filters.append(FuelReceipt.received_at >= b.purchase_date)
    receipts = (await db.execute(select(FuelReceipt).where(
        *receipt_filters,
    ).order_by(FuelReceipt.received_at))).scalars().all()

    remaining = float(b.total_liters or 0)
    allocated = 0.0
    covered = 0
    for r in receipts:
        if remaining <= 1e-6:
            break
        liters = float(r.doc_volume_liters or 0)
        if liters <= 0:
            continue
        if liters - remaining > 1e-6:
            break
        fkey = _receipt_fuel_key(r.fuel_code)
        cost = (await db.execute(select(FuelReceiptCost).where(
            FuelReceiptCost.company_id == cid,
            FuelReceiptCost.station_id == r.station_id,
            FuelReceiptCost.ttn == r.ttn,
            FuelReceiptCost.fuel_code == fkey,
        ).limit(1))).scalar_one_or_none()
        if cost is not None and not (
            cost.source == "purchase_batch" and cost.purchase_batch_id == b.id
        ):
            continue
        if cost is None:
            cost = FuelReceiptCost(company_id=cid, station_id=r.station_id, ttn=r.ttn, fuel_code=fkey)
            db.add(cost)
        cost.unit = b.unit
        cost.unit_cost = b.unit_cost
        cost.cost_per_liter = b.cost_per_liter
        cost.density_used = b.density or (float(r.density) if r.density else None)
        cost.source = "purchase_batch"
        cost.purchase_batch_id = b.id
        remaining -= liters
        allocated += liters
        covered += 1

    b.allocated_liters = allocated
    b.status = "allocated" if remaining <= 1e-6 else "partial"
    await db.commit()
    return {
        "ok": True,
        "allocated_liters": round(allocated, 2),
        "receipts_covered": covered,
        "remaining_liters": round(max(0.0, remaining), 2),
    }


@router.get("/shift-dashboard")
async def shift_dashboard(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),   # CSV station_ids (UUID); пусто = все АЗС компании
    compare: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Дашборд аналитики по сменным отчётам: виды топлива · способы оплаты · поступления ТТН ·
    движение наличных · инкассация · график по дням · тренды (сравнение периодов)."""
    cid = await _company_id(user, db)
    station_ids = None
    if stations:
        try:
            station_ids = [uuid.UUID(s.strip()) for s in stations.split(",") if s.strip()]
        except ValueError:
            station_ids = None
    svc = FuelDashboardService(db, cid)
    return await svc.compute(
        date.fromisoformat(date_from), date.fromisoformat(date_to), station_ids, compare)


@router.get("/readiness")
async def fuel_readiness(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Готовность к 1С за период: смены и ТТН (приёмка, корректировки) + очередь выгрузки."""
    cid = await _company_id(user, db)
    station_ids = None
    if stations:
        try:
            station_ids = [uuid.UUID(s.strip()) for s in stations.split(",") if s.strip()]
        except ValueError:
            station_ids = None
    df = date.fromisoformat(date_from)
    dtt = date.fromisoformat(date_to)
    dt_from = datetime(df.year, df.month, df.day)
    dt_to = datetime(dtt.year, dtt.month, dtt.day, 23, 59, 59)

    # ── Смены периода ──
    sq = select(FuelShift).where(
        FuelShift.company_id == cid,
        FuelShift.opened_at >= dt_from, FuelShift.opened_at <= dt_to)
    if station_ids:
        sq = sq.where(FuelShift.station_id.in_(station_ids))
    shifts = (await db.execute(sq)).scalars().all()
    shift_keys = {(s.station_id, s.shift_number) for s in shifts}

    ov_rows = (await db.execute(
        select(FuelShiftSaleOverride.station_id, FuelShiftSaleOverride.shift_number).where(
            FuelShiftSaleOverride.company_id == cid,
            or_(
                and_(FuelShiftSaleOverride.liters.isnot(None), FuelShiftSaleOverride.liters != FuelShiftSaleOverride.src_liters),
                and_(FuelShiftSaleOverride.amount.isnot(None), FuelShiftSaleOverride.amount != FuelShiftSaleOverride.src_amount),
                and_(FuelShiftSaleOverride.discount.isnot(None), FuelShiftSaleOverride.discount != FuelShiftSaleOverride.src_discount),
            )).distinct())).all()
    shift_ov_keys = {(r[0], r[1]) for r in ov_rows}

    # ── ТТН периода (статусы приёмки) ──
    rq = select(FuelReceipt).where(
        FuelReceipt.company_id == cid,
        FuelReceipt.received_at >= dt_from, FuelReceipt.received_at <= dt_to)
    if station_ids:
        rq = rq.where(FuelReceipt.station_id.in_(station_ids))
    receipts = (await db.execute(rq)).scalars().all()
    st_counts = {"pending": 0, "confirmed": 0, "corrected": 0, "rejected": 0}
    for r in receipts:
        st_counts[r.status if r.status in st_counts else "pending"] += 1

    rcpt_ov = (await db.execute(select(FuelReceiptOverride).where(
        FuelReceiptOverride.company_id == cid))).scalars().all()
    ov_keys = set()
    for o in rcpt_ov:
        changed = (
            (o.doc_volume_liters is not None and o.src_volume is not None and abs(float(o.doc_volume_liters) - float(o.src_volume)) > 0.005)
            or (o.doc_mass_kg is not None and o.src_mass is not None and abs(float(o.doc_mass_kg) - float(o.src_mass)) > 0.005)
            or (o.density is not None and o.src_density is not None and abs(float(o.density) - float(o.src_density)) > 0.005)
            or bool(o.note and o.note.strip())
        )
        if changed:
            ov_keys.add((str(o.station_id), o.ttn, o.fuel_code))
    receipts_corrected = sum(1 for r in receipts
                             if (str(r.station_id), r.ttn, _receipt_fuel_key(r.fuel_code)) in ov_keys)

    # ── Очередь выгрузки (пакеты по компании) ──
    pk_rows = (await db.execute(select(ExportPacket.status, func.count()).where(
        ExportPacket.company_id == cid).group_by(ExportPacket.status))).all()
    pk = {row[0]: row[1] for row in pk_rows}

    return {
        "period": {"from": df.isoformat(), "to": dtt.isoformat()},
        "shifts": {"total": len(shifts), "corrected": len(shift_keys & shift_ov_keys)},
        "receipts": {"total": len(receipts), **st_counts, "with_corrections": receipts_corrected},
        "packets": {
            "draft": pk.get("draft", 0),
            "in_flight": pk.get("queued", 0) + pk.get("sent", 0),
            "acked": pk.get("acked", 0),
            "rejected": pk.get("rejected", 0),
        },
    }


# ═══════════════════════════════════════════════════════════════
# Пооперационные транзакции (наливы) — STS /v2/transactions
# ═══════════════════════════════════════════════════════════════

# Прогресс фонового синка транзакций по компании (в памяти воркера).
_TX_SYNC: dict[str, dict] = {}


class TxSyncRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    station_codes: list[int] | None = None
    all_period: bool = False


async def _tx_sync_bg(company_id, date_from, date_to, station_codes, all_period):
    """Фоновая загрузка наливов: по станциям × помесячным окнам, дедуп по STS id."""
    from app.services.fuel_transactions import (
        resolve_sts, list_stations, ingest_station_window, month_windows,
    )
    key = str(company_id)
    try:
        async with async_session_factory() as db:
            conn = await resolve_sts(db, company_id)
            if conn is None:
                _TX_SYNC[key] = {"running": False, "stations_done": 0, "stations_total": 0,
                                 "loaded": 0, "message": "нет STS-источника у компании"}
                return
            # Период: явный [date_from, date_to] или (all_period) от первой смены до сегодня.
            if all_period or not (date_from and date_to):
                first = await db.scalar(select(func.min(FuelShift.opened_at)).where(
                    FuelShift.company_id == company_id))
                df = first.date().isoformat() if first else "2025-01-01"
                dt = datetime.now(timezone.utc).date().isoformat()
            else:
                df, dt = date_from, date_to
            stations = await list_stations(db, company_id, conn)
            if station_codes:
                wanted = {int(c) for c in station_codes}
                stations = [s for s in stations if s["code"] in wanted]
            windows = month_windows(df, dt)
            total = len(stations)
            loaded = 0
            _TX_SYNC[key] = {"running": True, "stations_done": 0, "stations_total": total,
                             "loaded": 0, "message": f"период {df}…{dt}, станций {total}"}
            for idx, st in enumerate(stations):
                _TX_SYNC[key].update({"message": f"АЗС {idx + 1}/{total} (код {st['code']})…"})
                for wf, wt in windows:
                    try:
                        r = await ingest_station_window(db, company_id, st, conn, wf, wt)
                        loaded += r["created"]
                        await db.commit()
                    except Exception as e:  # noqa: BLE001 — окно не валит весь синк
                        await db.rollback()
                        _TX_SYNC[key].update({"message": f"АЗС {st['code']} {wf}: ошибка {str(e)[:60]}"})
                    _TX_SYNC[key].update({"loaded": loaded})
                _TX_SYNC[key].update({"stations_done": idx + 1, "loaded": loaded})
            _TX_SYNC[key] = {"running": False, "stations_done": total, "stations_total": total,
                             "loaded": loaded, "message": f"готово: {loaded} наливов"}
    except Exception as e:  # noqa: BLE001
        _TX_SYNC[key] = {"running": False, "stations_done": 0, "stations_total": 0,
                         "loaded": 0, "message": f"сбой синка: {str(e)[:80]}"}


@router.post("/transactions/sync")
async def transactions_sync(
    body: TxSyncRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Запустить фоновую загрузку пооперационных транзакций (наливов) из STS /v2/transactions."""
    cid = await _company_id(user, db)
    key = str(cid)
    if _TX_SYNC.get(key, {}).get("running"):
        return {"status": "already_running", **_TX_SYNC[key]}
    b = body or TxSyncRequest()
    _TX_SYNC[key] = {"running": True, "stations_done": 0, "stations_total": 0, "loaded": 0, "message": "старт…"}
    asyncio.create_task(_tx_sync_bg(cid, b.date_from, b.date_to, b.station_codes, b.all_period))
    return {"status": "running"}


@router.get("/transactions/sync-status")
async def transactions_sync_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company_id(user, db)
    return _TX_SYNC.get(str(cid), {"running": False, "stations_done": 0, "stations_total": 0, "loaded": 0, "message": ""})


@router.get("/transactions/count")
async def transactions_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company_id(user, db)
    n = await db.scalar(select(func.count()).select_from(FuelTransaction).where(FuelTransaction.company_id == cid))
    return {"transactions": int(n or 0)}


_TX_SORT = {
    "dt": FuelTransaction.dt, "amount": FuelTransaction.amount,
    "liters": FuelTransaction.liters, "price": FuelTransaction.price,
    "station": FuelTransaction.station_code, "fuel": FuelTransaction.fuel_name,
    "pay_type": FuelTransaction.pay_type_name,
}


def _csv_ints(v: str | None) -> list[int]:
    if not v:
        return []
    out = []
    for x in v.split(","):
        try:
            out.append(int(x.strip()))
        except (TypeError, ValueError):
            pass
    return out


def _csv_strs(v: str | None) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()] if v else []


def _tx_conds(cid, df: str, dt: str, station_code, fuel_codes: list[int], pay_types: list[str], search):
    d0, d1 = date.fromisoformat(df), date.fromisoformat(dt)
    T = FuelTransaction
    conds = [T.company_id == cid,
             T.dt >= datetime(d0.year, d0.month, d0.day),
             T.dt <= datetime(d1.year, d1.month, d1.day, 23, 59, 59)]
    if station_code:
        conds.append(T.station_code == station_code)
    if fuel_codes:
        conds.append(T.fuel_code.in_(fuel_codes))
    if pay_types:
        conds.append(T.pay_type_name.in_(pay_types))
    if search:
        conds.append(T.card.ilike(f"%{search.strip()}%"))
    return conds


@router.get("/transactions/rows")
async def transactions_rows(
    date_from: str = Query(...), date_to: str = Query(...),
    station_code: int | None = Query(None), fuel_codes: str | None = Query(None),
    pay_types: str | None = Query(None), search: str | None = Query(None),
    sort: str = Query("dt"), order: str = Query("desc"),
    limit: int = Query(100, le=1000), offset: int = Query(0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Построчный реестр наливов (пооперационно) — серверная пагинация/фильтры/сортировка.
    fuel_codes/pay_types — CSV (мультивыбор через KPI-карточки)."""
    cid = await _company_id(user, db)
    T = FuelTransaction
    conds = _tx_conds(cid, date_from, date_to, station_code, _csv_ints(fuel_codes), _csv_strs(pay_types), search)
    tot = (await db.execute(select(
        func.count(), func.coalesce(func.sum(T.liters), 0), func.coalesce(func.sum(T.amount), 0)
    ).where(*conds))).one()
    col = _TX_SORT.get(sort, T.dt)
    col = col.desc() if order == "desc" else col.asc()
    rows = (await db.execute(
        select(T).where(*conds).order_by(col, T.id.desc()).limit(limit).offset(offset))).scalars().all()
    names = {int(s.code): s.name for s in (await db.execute(
        select(FuelStation).where(FuelStation.company_id == cid))).scalars().all()}
    out = [{
        "id": str(r.id), "dt": r.dt.isoformat() if r.dt else None,
        "station_code": r.station_code, "station_name": names.get(r.station_code) or f"АЗС {r.station_code}",
        "shift_number": r.shift_number, "pos": r.pos, "nozzle": r.nozzle, "tank": r.tank,
        "fuel_code": r.fuel_code, "fuel_name": r.fuel_name,
        "pay_type_name": r.pay_type_name, "card": r.card,
        "liters": float(r.liters or 0), "price": float(r.price) if r.price is not None else None,
        "amount": float(r.amount or 0),
    } for r in rows]
    return {
        "total": int(tot[0]),
        "totals": {"count": int(tot[0]), "liters": round(float(tot[1]), 2), "amount": round(float(tot[2]), 2)},
        "rows": out,
    }


@router.get("/transactions/filters")
async def transactions_filters(
    date_from: str = Query(...), date_to: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Значения для фильтров реестра (станции/топливо/виды оплаты за период)."""
    cid = await _company_id(user, db)
    T = FuelTransaction
    conds = _tx_conds(cid, date_from, date_to, None, [], [], None)
    names = {int(s.code): s.name for s in (await db.execute(
        select(FuelStation).where(FuelStation.company_id == cid))).scalars().all()}
    st = (await db.execute(select(T.station_code).where(*conds).distinct().order_by(T.station_code))).scalars().all()
    fu = (await db.execute(select(T.fuel_code, T.fuel_name).where(*conds).distinct())).all()
    pt = (await db.execute(select(T.pay_type_name).where(*conds).distinct().order_by(T.pay_type_name))).scalars().all()
    fuels = sorted({(r[0], r[1]) for r in fu if r[0] is not None}, key=lambda x: x[0])
    return {
        "stations": [{"code": c, "name": names.get(c) or f"АЗС {c}"} for c in st],
        "fuels": [{"code": c, "name": n} for c, n in fuels],
        "pay_types": [p for p in pt if p],
    }


@router.get("/transactions/overview")
async def transactions_overview(
    date_from: str = Query(...), date_to: str = Query(...),
    station_code: int | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Агрегаты периода для KPI-карточек «Операций»: итого + по видам топлива + по оплате.
    Не зависит от кликов по KPI (fuel/pay) — они фильтруют только список."""
    cid = await _company_id(user, db)
    T = FuelTransaction
    conds = _tx_conds(cid, date_from, date_to, station_code, [], [], None)
    kpi = (await db.execute(select(
        func.count(), func.coalesce(func.sum(T.liters), 0), func.coalesce(func.sum(T.amount), 0)
    ).where(*conds))).one()
    fu = (await db.execute(select(
        T.fuel_code, T.fuel_name, func.count().label("n"),
        func.coalesce(func.sum(T.liters), 0).label("l"), func.coalesce(func.sum(T.amount), 0).label("a"),
    ).where(*conds).group_by(T.fuel_code, T.fuel_name)
        .order_by(func.coalesce(func.sum(T.amount), 0).desc()))).all()
    pm = (await db.execute(select(
        T.pay_type_name, func.count().label("n"),
        func.coalesce(func.sum(T.liters), 0).label("l"), func.coalesce(func.sum(T.amount), 0).label("a"),
    ).where(*conds).group_by(T.pay_type_name)
        .order_by(func.coalesce(func.sum(T.amount), 0).desc()))).all()
    return {
        "kpi": {"count": int(kpi[0]), "liters": round(float(kpi[1]), 2), "amount": round(float(kpi[2]), 2)},
        "by_fuel": [{"fuel_code": r.fuel_code, "fuel_name": r.fuel_name or "—", "count": int(r.n),
                     "liters": round(float(r.l), 2), "amount": round(float(r.a), 2)} for r in fu],
        "by_payment": [{"name": r.pay_type_name or "—", "count": int(r.n),
                        "liters": round(float(r.l), 2), "amount": round(float(r.a), 2)} for r in pm],
    }


@router.get("/sales-channels")
async def sales_channels(
    date_from: str = Query(...), date_to: str = Query(...),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    pay_types: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Каналы продаж: связанные разрезы АЗС × оплата × топливо × день."""
    cid = await _company_id(user, db)
    return await FuelDashboardService(db, cid).sales_channels(
        date.fromisoformat(date_from), date.fromisoformat(date_to),
        _csv_ints(station_codes), _csv_ints(fuel_codes), _csv_strs(pay_types),
    )


@router.post("/stations/sync-geo")
async def stations_sync_geo(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Подтянуть координаты/адрес АЗС из STS /v1/points → FuelStation (для Карты АЗС)."""
    from app.services.fuel_transactions import resolve_sts
    from app.services.sts_client import sts_get_points as _points
    cid = await _company_id(user, db)
    conn = await resolve_sts(db, cid)
    if conn is None:
        return {"updated": 0, "message": "нет STS-источника у компании"}
    geo: dict[int, dict] = {}
    for sysid in conn["systems"]:
        try:
            pts = await _points(conn["base_url"], conn["login"], conn["pwd"], sysid)
        except Exception:  # noqa: BLE001
            pts = []
        for p in pts:
            try:
                code = int(p.get("number") or p.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if not code:
                continue
            geo[code] = {
                "lat": _num_or_none(p.get("latitude")), "lon": _num_or_none(p.get("longitude")),
                "address": p.get("address"),
            }
    stations = (await db.execute(select(FuelStation).where(FuelStation.company_id == cid))).scalars().all()
    updated = 0
    for s in stations:
        g = geo.get(int(s.code))
        if not g:
            continue
        if g["lat"] is not None:
            s.latitude = g["lat"]
        if g["lon"] is not None:
            s.longitude = g["lon"]
        if g.get("address"):
            s.address = g["address"]
        updated += 1
    await db.commit()
    return {"updated": updated, "with_coords": sum(1 for s in stations if s.latitude is not None)}


@router.get("/stations/map")
async def stations_map(
    date_from: str = Query(...), date_to: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """АЗС с координатами + метрики за период (наливы/объём/выручка) — для Карты АЗС."""
    cid = await _company_id(user, db)
    d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    T = FuelTransaction
    agg = (await db.execute(select(
        T.station_code, func.count().label("n"),
        func.coalesce(func.sum(T.liters), 0).label("l"),
        func.coalesce(func.sum(T.amount), 0).label("a"),
    ).where(
        T.company_id == cid,
        T.dt >= datetime(d0.year, d0.month, d0.day),
        T.dt <= datetime(d1.year, d1.month, d1.day, 23, 59, 59),
    ).group_by(T.station_code))).all()
    m = {int(r.station_code): r for r in agg}
    stations = (await db.execute(select(FuelStation).where(FuelStation.company_id == cid))).scalars().all()
    out = []
    for s in stations:
        r = m.get(int(s.code))
        out.append({
            "code": s.code, "name": s.name, "address": s.address,
            "latitude": float(s.latitude) if s.latitude is not None else None,
            "longitude": float(s.longitude) if s.longitude is not None else None,
            "transactions": int(r.n) if r else 0,
            "liters": round(float(r.l), 2) if r else 0.0,
            "amount": round(float(r.a), 2) if r else 0.0,
        })
    with_coords = sum(1 for s in out if s["latitude"] is not None)
    return {"stations": out, "with_coords": with_coords, "total": len(out)}


# ═══════════════════════════════════════════════════════════════
# Подтверждение приёмки ТТН менеджером (workflow статусов)
# ═══════════════════════════════════════════════════════════════

_RECEIPT_STATUSES = {"pending", "confirmed", "corrected", "rejected"}


class ReceiptStatusEdit(BaseModel):
    status: str            # pending | confirmed | corrected | rejected
    reason: str | None = None  # обязателен для rejected


@router.patch("/receipts/{receipt_id}/status")
async def patch_receipt_status(
    receipt_id: str,
    edit: ReceiptStatusEdit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Подтверждение приёмки ТТН: принято/скорректировано/отклонено (сверка док↔факт до 1С)."""
    if edit.status not in _RECEIPT_STATUSES:
        raise HTTPException(422, f"Недопустимый статус: {edit.status}")
    cid = await _company_id(user, db)
    rcpt = await db.get(FuelReceipt, uuid.UUID(receipt_id))
    if rcpt is None or rcpt.company_id != cid:
        raise HTTPException(404, "ТТН не найдена")
    if rcpt.is_locked:
        raise HTTPException(409, "ТТН в закрытом периоде")
    if edit.status == "rejected" and not (edit.reason and edit.reason.strip()):
        raise HTTPException(422, "Для отклонения нужна причина")
    rcpt.status = edit.status
    await db.commit()
    return {"ok": True, "status": rcpt.status}


class BulkReceiptStatus(BaseModel):
    ids: list[str]
    status: str


@router.post("/receipts/status/bulk")
async def bulk_receipt_status(
    body: BulkReceiptStatus,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Массовое подтверждение приёмки ТТН."""
    if body.status not in _RECEIPT_STATUSES:
        raise HTTPException(422, f"Недопустимый статус: {body.status}")
    cid = await _company_id(user, db)
    try:
        ids = [uuid.UUID(i) for i in body.ids]
    except (ValueError, TypeError):
        raise HTTPException(422, "Некорректные id")
    if not ids:
        return {"ok": True, "updated": 0}
    res = await db.execute(update(FuelReceipt).where(
        FuelReceipt.company_id == cid,
        FuelReceipt.id.in_(ids),
        FuelReceipt.is_locked == False,  # noqa: E712
    ).values(status=body.status))
    await db.commit()
    return {"ok": True, "updated": res.rowcount}
