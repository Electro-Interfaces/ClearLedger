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
from app.deps import capture_company_header, scope_company_id
from app.models import (
    FuelStation, FuelShift, FuelTank, FuelPump, FuelCashMovement,
    FuelReceipt, FuelReceiptOverride, FuelReceiptCost, FuelOpeningBalance, FuelPurchaseBatch,
    FuelExportDoc, FuelShiftSale, FuelShiftSaleOverride, FuelShiftCorrectionNote,
    FuelTransaction, ExportPacket, User, DataEntry, RawBatchRecord,
)
from app.services.analytics_cache import bump_version
from app.services.fuel_documents import build_shift_documents, build_ttn_documents
from app.services.fuel_costing import FuelCostingService
from app.services.fuel_dashboard import FuelDashboardService
from app.services.fuel_mappings import MappingContext, build_sales_agg, load_mapping_context
from app.services.fuel_network_analytics import FuelNetworkAnalytics
from app.services.fuel_pricing import FuelPricing
from app.services.fuel_sales_analytics import FuelSalesAnalytics
from app.services.payment_normalize import normalize_payment_method
from app.services.sts_client import (
    sts_get_shifts, sts_get_shift_report, sts_get_receipts,
    sts_test_connection,
)
async def _company_id(user: User, db: AsyncSession) -> uuid.UUID:
    """company_id раздела: выбранная в UI компания (X-Company-Id, с проверкой
    членства) либо дефолтная user.company_id. Раньше игнорировала выбор в шапке."""
    return await scope_company_id(user, db)

# capture_company_header кладёт X-Company-Id в contextvar до тела эндпоинта.
router = APIRouter(prefix="/fuel", tags=["Топливо"],
                   dependencies=[Depends(capture_company_header)])


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
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(200, le=20000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_id = await _company_id(user, db)
    q = select(FuelShift).where(FuelShift.company_id == company_id)
    if station_code is not None:
        q = q.join(FuelStation).where(FuelStation.code == station_code)
    # Отбор по периоду рабочей области. Без него срабатывал limit по номеру
    # смены: журнал отдавал последние 200 смен, и период месячной давности
    # показывал «нет смен», хотя они загружены.
    #
    # Границы приводятся к `date` В PYTHON, а не передаются строкой: asyncpg не
    # приводит текст к дате сам, и сравнение `date >= character varying` роняло
    # ручку в 500. Журнал смен из-за этого выглядел пустым — и здесь, и в
    # «Бухгалтерском», который зовёт ту же ручку с периодом.
    try:
        if date_from:
            q = q.where(func.date(FuelShift.opened_at) >= date.fromisoformat(date_from))
        if date_to:
            q = q.where(func.date(FuelShift.opened_at) <= date.fromisoformat(date_to))
    except ValueError:
        raise HTTPException(400, "Неверный формат дат (ожидается YYYY-MM-DD)")
    # Внутри периода — свежие сверху (по дате открытия, номер как tie-breaker).
    q = q.order_by(FuelShift.opened_at.desc(), FuelShift.shift_number.desc()).limit(limit)
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
    channel_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
    sync_log_id: uuid.UUID | None = None,
) -> dict:
    """Ядро fuel-ingest продаж (STS shift_report → FuelShift + L1-маркеры смен).

    Зовётся роутером /fuel/normalize и оркестратором канала продаж (fuel_shift).
    with_receipts: если False — ТТН (приём) НЕ создаются здесь; приём идёт
    отдельным каналом fuel_delivery через ingest_fuel_deliveries (как в расширении
    БП: ОбработатьСмену и ОбработатьТТН — раздельные ветки). По умолчанию True
    для обратной совместимости /fuel/normalize.
    channel_id/source_id/sync_log_id передаёт оркестратор канала: трасса «какой
    канал породил запись» + L1-батч сырого ответа STS (docs/CONNECT.md, В3).
    При ручном /fuel/normalize их нет — записи остаются без трассы, как раньше.
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
        # L1: сырой ответ STS /shifts как пришёл — до клиентских фильтров.
        # Тяжёлые отчёты смен НЕ дублируются: они и так лежат в FuelShift.raw_report,
        # батч фиксирует «что источник отдал в этот прогон» (docs/CONNECT.md, В3).
        if source_id is not None:
            db.add(RawBatchRecord(
                company_id=company_id, source_id=source_id,
                channel_id=channel_id, sync_log_id=sync_log_id,
                doc_type="fuel_shift",
                since=_parse_dt(body.date_from), until=_parse_dt(body.date_to),
                items=shifts_to_process, items_count=len(shifts_to_process),
                meta={"station_code": body.station_code,
                      "system_code": body.system_code},
            ))
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
            # Отчёт снят, но продаж в нём нет вовсе — это пробел источника, а не
            # нулевая выручка (смена ещё открыта / станция не отдаёт детализацию).
            # Снимется автоматически переигровкой, когда STS отдаст продажи.
            sales_missing=(not psm_total and not report.get("sales")),
            # Сырой отчёт STS как есть — для эталонного просмотрщика «Детали смены».
            raw_report=report,
            channel_id=channel_id,
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
            _rest = t.get("rest", {}) or {}
            _recv = t.get("receipt", {}) or {}
            db.add(FuelTank(
                shift_id=shift.id,
                tank_number=t.get("tank", 0),
                fuel_type=svc.get("service_name", ""),
                fuel_code=_int_or_none(svc.get("service_code")),
                # книга: doc_beg + приход − отпуск = doc_end
                volume_start=float(doc_beg.get("volume", 0) or 0),
                volume_end=float(doc_end.get("volume", 0) or 0),
                sales=float(rel.get("volume", 0) or 0),
                volume_received=float(_recv.get("volume", 0) or 0),
                # факт: замер уровнемером на конец смены (секция rest)
                fact_volume=_num_or_none(_rest.get("volume")),
                fact_mass=_num_or_none(_rest.get("amount")),
                # масса (кг) по тем же точкам — учёт ГСМ ведётся в тоннах
                mass_start=_num_or_none(doc_beg.get("amount")),
                mass_end=_num_or_none(doc_end.get("amount")),
                mass_sales=_num_or_none(rel.get("amount")),
                mass_received=_num_or_none(_recv.get("amount")),
                density=_density(t.get("density_end")),
                density_beg=_density(t.get("density_beg")),
                temp_beg=_num_or_none(t.get("temp_beg")),
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
                channel_id=channel_id,
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
                channel_id=channel_id,
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
                channel_id=channel_id,
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
    *,
    channel_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
    sync_log_id: uuid.UUID | None = None,
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
    raw_items: list[dict] = []   # L1: сырые receipts STS по сменам прогона

    for shift_info in shifts:
        shift_num = shift_info.get("shift")
        if shift_num is None:
            continue
        scanned += 1
        receipts = await sts_get_receipts(
            body.base_url, body.login, body.password,
            body.system_code, body.station_code, shift_num,
        )
        if source_id is not None and receipts:
            raw_items.append({"shift": shift_num, "receipts": receipts})
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
                    channel_id=channel_id,
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
                channel_id=channel_id,
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

    # L1: сырой ответ STS /receipts за прогон одним батчем (docs/CONNECT.md, В3).
    if source_id is not None and raw_items:
        db.add(RawBatchRecord(
            company_id=company_id, source_id=source_id,
            channel_id=channel_id, sync_log_id=sync_log_id,
            doc_type="fuel_delivery",
            since=_parse_dt(body.date_from), until=_parse_dt(body.date_to),
            items=raw_items, items_count=sum(len(x["receipts"]) for x in raw_items),
            meta={"station_code": body.station_code, "system_code": body.system_code},
        ))

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
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Управленческая маржа по FIFO-себестоимости партий (по разрезам).
    Независимо от проводок 1С: продажи − себестоимость партий (ТТН), списанная по ФИФО."""
    cid = await _company_id(user, db)
    svc = FuelCostingService(db, cid)
    return await svc.compute(date.fromisoformat(date_from), date.fromisoformat(date_to), group_by,
                             fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/costing/decision-dashboard")
async def costing_decision_dashboard(
    company_id: str = Query(...),
    date_from: str = Query(...),
    date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
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
    return await svc.decision_dashboard(period_from, period_to,
                                        fuel_codes=tuple(_csv_ints(fuel_codes)))


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


async def _resolve_station_filter(
    db: AsyncSession, cid: uuid.UUID, stations: str | None
) -> list[uuid.UUID] | None:
    """CSV станций из фильтра рабочей области -> список station_id.

    Принимает и UUID станций, и КОДЫ («208»): фронт оперирует кодами, они же
    лежат в fuel_stations.code. Раньше здесь стоял `except ValueError:
    station_ids = None` — любой некорректный элемент молча превращал фильтр во
    «всю сеть», и дашборд показывал сетевые цифры под заголовком с одной АЗС.
    Теперь неразобранный идентификатор — ошибка 400, а не тихая подмена.

    Возвращает None только если фильтр не задан. Если станции заданы, но ни
    одна не найдена, возвращается пустой список — «данных нет» честнее, чем
    «данные по всем».
    """
    if not stations:
        return None
    raw = [s.strip() for s in stations.split(",") if s.strip()]
    if not raw:
        return None

    ids: list[uuid.UUID] = []
    codes: list[int] = []
    for item in raw:
        try:
            ids.append(uuid.UUID(item))
            continue
        except ValueError:
            pass
        if item.isdigit():
            codes.append(int(item))
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Некорректный идентификатор станции: {item!r}. Ожидается UUID или код.",
            )

    if codes:
        rows = await db.execute(
            select(FuelStation.id).where(
                FuelStation.company_id == cid, FuelStation.code.in_(codes)
            )
        )
        ids.extend(rows.scalars().all())
    return ids


@router.get("/shift-dashboard")
async def shift_dashboard(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),   # CSV station_ids (UUID); пусто = все АЗС компании
    fuel_codes: str | None = Query(None),
    compare: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Дашборд аналитики по сменным отчётам: виды топлива · способы оплаты · поступления ТТН ·
    движение наличных · инкассация · график по дням · тренды (сравнение периодов)."""
    cid = await _company_id(user, db)
    station_ids = await _resolve_station_filter(db, cid, stations)
    svc = FuelDashboardService(db, cid)
    return await svc.compute(
        date.fromisoformat(date_from), date.fromisoformat(date_to), station_ids, compare,
        fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/cash-collections")
async def fuel_cash_collections(
    date_from: str = Query(...),
    date_to: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Касса и инкассация (бухгалтерский контур): журнал инкассаций за период
    (сумма + накоплено с прошлой инкассации — основание для РКО в 1С), выдачи
    наличных, остатки касс по АЗС (последний снимок «по всей АЗС»), дни без
    инкассации. Источник — money-секция сменных отчётов STS."""
    from app.services.fuel_dashboard import CashCollectionsService
    cid = await _company_id(user, db)
    svc = CashCollectionsService(db, cid)
    return await svc.compute(date.fromisoformat(date_from), date.fromisoformat(date_to))


@router.get("/cash-collections/station")
async def fuel_cash_station_detail(
    station_code: int = Query(...),
    shifts: int = Query(2, ge=1, le=10),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Детализация кассы станции: money-операции последних N смен по рабочим
    местам (POS) — раскрытие строки в «Кассе и инкассации». Состояние
    купюроприёмника по номиналам STS TMS не отдаёт (терминальный уровень) —
    до подключения такого источника показываем разрез по POS."""
    from app.models import FuelCashMovement, FuelShift, FuelStation
    cid = await _company_id(user, db)
    st = (await db.execute(select(FuelStation).where(
        FuelStation.company_id == cid, FuelStation.code == station_code))).scalars().first()
    if st is None:
        raise HTTPException(404, "Станция не найдена")
    last_shifts = (await db.execute(
        select(FuelShift).where(FuelShift.station_id == st.id, FuelShift.opened_at.is_not(None))
        .order_by(FuelShift.opened_at.desc()).limit(shifts))).scalars().all()
    ids = [s.id for s in last_shifts]
    moves = (await db.execute(select(FuelCashMovement).where(
        FuelCashMovement.shift_id.in_(ids)))).scalars().all() if ids else []
    by_shift: dict = {s.id: {"shift_number": s.shift_number,
                             "opened_at": s.opened_at.isoformat() if s.opened_at else None,
                             "status": s.status, "operations": []} for s in last_shifts}
    for m in moves:
        by_shift[m.shift_id]["operations"].append({
            "pos": m.pos_number, "operation": m.operation_name,
            "amount": float(m.amount or 0),
        })
    out = sorted(by_shift.values(), key=lambda x: -(x["shift_number"] or 0))
    for sh in out:
        sh["operations"].sort(key=lambda o: (o["pos"] or 0, o["operation"]))
    return {"station_code": station_code, "station_name": st.name, "shifts": out}


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
    # Тот же разбор, что и у shift-dashboard: коды или UUID, ошибка вместо
    # молчаливого «фильтра нет».
    station_ids = await _resolve_station_filter(db, cid, stations)
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
# Переигровка смен — дописать продажи, которые STS отдал позже
# ═══════════════════════════════════════════════════════════════

# Прогресс фоновой переигровки по компании (в памяти воркера).
_SHIFT_REFRESH: dict[str, dict] = {}


class ShiftRefreshRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    station_codes: list[int] | None = None
    # По умолчанию — только смены с нулевой выручкой (доводка пробелов).
    only_zero: bool = True
    # Ничего не пишем, только считаем, что удалось бы восстановить.
    dry_run: bool = False


async def _shift_refresh_bg(company_id: uuid.UUID, body: ShiftRefreshRequest) -> None:
    from app.services.fuel_shift_refresh import refresh_shifts

    key = str(company_id)
    try:
        async with async_session_factory() as db:
            def _progress(st: dict) -> None:
                _SHIFT_REFRESH[key] = {
                    "running": True, **st,
                    "message": f"смена {st['checked']}/{st['total']}, "
                               f"восстановлено {st['recovered']}",
                }

            stats = await refresh_shifts(
                db, company_id,
                station_codes=body.station_codes,
                date_from=body.date_from, date_to=body.date_to,
                only_zero=body.only_zero, dry_run=body.dry_run,
                progress=_progress,
            )
            if stats.get("recovered") and not body.dry_run:
                # выручка смен изменилась → версионный кеш аналитики невалиден
                await bump_version(db, company_id)
                await db.commit()
            _SHIFT_REFRESH[key] = {
                "running": False, **stats,
                "message": (
                    f"готово: восстановлено {stats.get('recovered', 0)} смен на "
                    f"{stats.get('recovered_amount', 0):,.2f} ₽; "
                    f"без данных в источнике {stats.get('no_data', 0)}; "
                    f"честный ноль {stats.get('true_zero', 0)}"
                ),
            }
    except Exception as e:  # noqa: BLE001
        _SHIFT_REFRESH[key] = {"running": False, "message": f"сбой переигровки: {str(e)[:120]}"}


@router.post("/shift-refresh")
async def shifts_refresh(
    body: ShiftRefreshRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Переспросить STS по уже загруженным сменам и дописать продажи.

    Канал приёма пропускает существующую смену — смена, снятая открытой, так и
    остаётся с нулевой выручкой. Здесь она добирается. Пустой ответ источника
    сохранённые продажи не затирает.
    """
    cid = await _company_id(user, db)
    key = str(cid)
    if _SHIFT_REFRESH.get(key, {}).get("running"):
        return {"status": "already_running", **_SHIFT_REFRESH[key]}
    b = body or ShiftRefreshRequest()
    if b.dry_run:
        from app.services.fuel_shift_refresh import refresh_shifts
        return {"status": "done", **await refresh_shifts(
            db, cid, station_codes=b.station_codes, date_from=b.date_from,
            date_to=b.date_to, only_zero=b.only_zero, dry_run=True,
        )}
    _SHIFT_REFRESH[key] = {"running": True, "checked": 0, "total": 0,
                           "recovered": 0, "message": "старт…"}
    asyncio.create_task(_shift_refresh_bg(cid, b))
    return {"status": "running"}


@router.get("/shift-refresh/status")
async def shifts_refresh_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _company_id(user, db)
    return _SHIFT_REFRESH.get(str(cid), {"running": False, "checked": 0, "total": 0,
                                         "recovered": 0, "message": ""})


# ═══════════════════════════════════════════════════════════════
# Инвентаризация резервуаров — корректировка книги на факт
# ═══════════════════════════════════════════════════════════════

class InventoryDraftRequest(BaseModel):
    date: str  # дата инвентаризации YYYY-MM-DD
    station_codes: list[int] | None = None
    fuel_codes: list[int] | None = None


class InventorySaveRow(BaseModel):
    station_id: str
    tank_number: int
    fuel_code: int | None = None
    fuel_name: str | None = None
    shift_number: int | None = None
    book_volume: float = 0
    fact_volume: float = 0
    book_mass: float | None = None
    fact_mass: float | None = None


class InventorySaveRequest(BaseModel):
    date: str
    rows: list[InventorySaveRow]
    note: str | None = None


@router.post("/inventory/draft")
async def inventory_draft(
    body: InventoryDraftRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Черновик ведомости инвентаризации на дату: книга/факт/корректировка по резервуарам."""
    from datetime import date as _date
    from app.services.tank_inventory import build_draft

    cid = await _company_id(user, db)
    inv_date = _date.fromisoformat(body.date)
    return await build_draft(db, cid, inv_date,
                             station_codes=body.station_codes, fuel_codes=body.fuel_codes)


@router.post("/inventory")
async def inventory_save(
    body: InventorySaveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Провести инвентаризацию: зафиксировать корректировки (книга приведена к факту)."""
    from datetime import date as _date
    from app.services.tank_inventory import save

    cid = await _company_id(user, db)
    inv_date = _date.fromisoformat(body.date)
    rows = [r.model_dump() for r in body.rows]
    result = await save(db, cid, inv_date, rows, note=body.note)
    # новые корректировки → инвалидация версионного кеша аналитики
    await bump_version(db, cid)
    await db.commit()
    return result


@router.get("/inventory")
async def inventory_list(
    station_codes: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Проведённые инвентаризации, сгруппированные по дате."""
    from app.services.tank_inventory import list_inventories

    cid = await _company_id(user, db)
    codes = [int(c) for c in station_codes.split(",") if c.strip()] if station_codes else None
    return await list_inventories(db, cid, station_codes=codes)


# ─── Паспорт резервуаров: вместимость для отбраковки замеров ───

class TankSpecRow(BaseModel):
    station_id: str
    tank_number: int
    fuel_name: str | None = None
    nominal_liters: float | None = None
    usable_liters: float | None = None
    dead_liters: float | None = None
    note: str | None = None


class TankSpecSaveRequest(BaseModel):
    rows: list[TankSpecRow]


@router.get("/tank-specs")
async def tank_specs_list(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Паспорт резервуаров + оценка по книге и наибольшее показание прибора.

    Список резервуаров берётся из сменных данных (что реально работает), а не из
    паспорта: иначе новый резервуар не появился бы, пока его не заведут руками.
    """
    from app.models import FuelTankSpec
    from app.services.tank_ledger import FACT_SANITY_RATIO
    cid = await _company_id(user, db)

    specs = {
        (str(s.station_id), int(s.tank_number)): s
        for s in (await db.execute(select(FuelTankSpec).where(
            FuelTankSpec.company_id == cid))).scalars().all()
    }
    T, S = FuelTank, FuelShift
    rows = (await db.execute(
        select(S.station_id, FuelStation.code, FuelStation.name, T.tank_number,
               func.max(func.greatest(T.volume_start, T.volume_end)).label("book_max"),
               func.max(T.fact_volume).label("fact_max"),
               func.count().label("records"),
               func.count(T.fact_volume).label("measured"),
               func.max(T.fuel_type).label("fuel_name"))
        .join(S, S.id == T.shift_id)
        .join(FuelStation, FuelStation.id == S.station_id)
        .where(S.company_id == cid)
        .group_by(S.station_id, FuelStation.code, FuelStation.name, T.tank_number)
        .order_by(FuelStation.code, T.tank_number)
    )).all()

    # Последняя смена по каждому резервуару: остаток, уровень и условия замера. Это
    # «состояние резервуара сейчас» — то же, что показывает «Монитор» карточками.
    last_state: dict[tuple[str, int], dict[str, Any]] = {}
    for row in (await db.execute(
        select(S.station_id, T.tank_number, S.shift_number, S.opened_at,
               T.volume_end, T.fact_volume, T.level_end, T.temp_end, T.density,
               T.water_volume, T.fact_mass)
        .join(S, S.id == T.shift_id)
        .where(S.company_id == cid)
        .order_by(S.station_id, T.tank_number, S.opened_at, S.shift_number)
    )).all():
        (station_id, tank_no, shift_no, opened_at, book_end, fact_vol,
         level, temp, dens, water, mass) = row
        # Список отсортирован по времени — последняя запись перетирает предыдущую.
        last_state[(str(station_id), int(tank_no))] = {
            "shift_number": int(shift_no) if shift_no is not None else None,
            "shift_date": opened_at.date().isoformat() if opened_at else None,
            "book_end": round(float(book_end or 0), 1),
            "fact_volume": round(float(fact_vol), 1) if fact_vol is not None else None,
            "level_mm": round(float(level), 1) if level is not None else None,
            "temp_c": round(float(temp), 1) if temp is not None else None,
            "density": float(dens) if dens is not None else None,
            "water_liters": round(float(water), 1) if water is not None else None,
            "mass_kg": round(float(mass), 1) if mass is not None else None,
        }

    # Показания, равные вместимости из паспорта: прибор отдал предел шкалы вместо
    # измерения. Считаем отдельно — по этой цифре видно, какой прибор сбойный.
    at_limit: dict[tuple[str, int], int] = {}
    for station_id, tank_no, cnt in (await db.execute(
        select(S.station_id, T.tank_number, func.count())
        .join(S, S.id == T.shift_id)
        .join(FuelTankSpec, and_(FuelTankSpec.station_id == S.station_id,
                                 FuelTankSpec.tank_number == T.tank_number,
                                 FuelTankSpec.company_id == cid))
        .where(S.company_id == cid,
               FuelTankSpec.usable_liters.is_not(None),
               func.abs(T.fact_volume - FuelTankSpec.usable_liters) < 0.5)
        .group_by(S.station_id, T.tank_number)
    )).all():
        at_limit[(str(station_id), int(tank_no))] = int(cnt)

    out = []
    for station_id, code, name, tank_no, book_max, fact_max, records, measured, fuel_name in rows:
        sp = specs.get((str(station_id), int(tank_no)))
        usable = float(sp.usable_liters) if sp and sp.usable_liters else None
        limit = (usable or round(float(book_max or 0), 1)) * FACT_SANITY_RATIO
        out.append({
            "station_id": str(station_id), "station_code": int(code),
            "station_name": name or f"АЗС {code}", "tank_number": int(tank_no),
            "fuel_name": (sp.fuel_name if sp and sp.fuel_name else fuel_name) or "—",
            "nominal_liters": float(sp.nominal_liters) if sp and sp.nominal_liters else None,
            "usable_liters": usable,
            "dead_liters": float(sp.dead_liters) if sp and sp.dead_liters else None,
            "note": sp.note if sp else None,
            "source": sp.source if sp else None,
            "synced_at": sp.synced_at.isoformat() if sp and sp.synced_at else None,
            "book_max": round(float(book_max or 0), 1),
            "fact_max": round(float(fact_max or 0), 1),
            "records": int(records),
            "measured": int(measured),
            # Сколько раз прибор отдал ровно свою вместимость вместо измерения.
            "at_limit": at_limit.get((str(station_id), int(tank_no)), 0),
            # Порог, по которому сейчас отбраковывается показание прибора.
            "fact_limit": round(limit, 1),
            # Состояние на последнюю смену: остаток, уровень, температура, вода.
            "state": last_state.get((str(station_id), int(tank_no))),
        })
    return {"rows": out, "sanity_ratio": FACT_SANITY_RATIO}


@router.put("/tank-specs")
async def tank_specs_save(
    body: TankSpecSaveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить паспорт вручную — это уточнение поверх синхронизации из STS."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models import FuelTankSpec
    cid = await _company_id(user, db)
    saved = 0
    for r in body.rows:
        values = dict(
            id=uuid.uuid4(), company_id=cid, station_id=uuid.UUID(r.station_id),
            tank_number=int(r.tank_number), fuel_name=r.fuel_name,
            nominal_liters=r.nominal_liters, usable_liters=r.usable_liters,
            dead_liters=r.dead_liters, note=r.note, source="manual",
        )
        stmt = pg_insert(FuelTankSpec).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["company_id", "station_id", "tank_number"],
            set_={k: values[k] for k in (
                "fuel_name", "nominal_liters", "usable_liters", "dead_liters", "note", "source")},
        )
        await db.execute(stmt)
        saved += 1
    await bump_version(db, cid)
    await db.commit()
    return {"saved": saved}


@router.post("/tank-specs/sync-sts")
async def tank_specs_sync_sts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Забрать вместимость резервуаров из STS (`/v1/tanks`, поле `volume_max`).

    Ручной паспорт не перетирается: человек уточняет то, чего источник не знает.
    Нулевую ёмкость игнорируем — так STS отвечает, когда уровнемера на резервуаре
    нет вовсе, и «ёмкость 0» отбраковала бы вообще все замеры.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models import FuelTankSpec
    from app.services.fuel_transactions import resolve_sts
    from app.services.sts_client import sts_get_tanks

    cid = await _company_id(user, db)
    conn = await resolve_sts(db, cid)
    if conn is None:
        raise HTTPException(400, "нет STS-источника у компании")

    stations = (await db.execute(select(FuelStation).where(
        FuelStation.company_id == cid))).scalars().all()
    now = datetime.now(timezone.utc)
    updated = skipped = 0
    errors: list[str] = []
    for st in stations:
        got = False
        for sysid in conn["systems"]:
            if got:
                break
            try:
                tanks = await sts_get_tanks(conn["base_url"], conn["login"], conn["pwd"],
                                            sysid, int(st.code))
            except Exception as e:  # noqa: BLE001 — станция недоступна, идём дальше
                errors.append(f"АЗС {st.code}: {str(e)[:60]}")
                continue
            if not tanks:
                continue
            got = True
            for t in tanks:
                num = _int_or_none(t.get("number") or t.get("id"))
                vmax = _num_or_none(t.get("volume_max"))
                if num is None or not vmax or float(vmax) <= 0:
                    skipped += 1
                    continue
                values = dict(
                    id=uuid.uuid4(), company_id=cid, station_id=st.id, tank_number=int(num),
                    fuel_name=t.get("fuel_name"), nominal_liters=float(vmax),
                    usable_liters=float(vmax), dead_liters=None,
                    note="вместимость из STS (/v1/tanks · volume_max)",
                    source="sts", synced_at=now,
                )
                stmt = pg_insert(FuelTankSpec).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["company_id", "station_id", "tank_number"],
                    # Ручной паспорт сильнее источника: он появился именно потому,
                    # что источнику по этому резервуару не поверили.
                    set_={"fuel_name": values["fuel_name"],
                          "nominal_liters": values["nominal_liters"],
                          "usable_liters": values["usable_liters"],
                          "note": values["note"], "source": "sts", "synced_at": now},
                    where=FuelTankSpec.source != "manual",
                )
                await db.execute(stmt)
                updated += 1
    await bump_version(db, cid)
    await db.commit()
    return {"updated": updated, "skipped": skipped, "stations": len(stations),
            "warning": "; ".join(errors[:3]) if errors else None}


class InventoryCancelRequest(BaseModel):
    date: str
    station_codes: list[int] | None = None


@router.post("/inventory/cancel")
async def inventory_cancel(
    body: InventoryCancelRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отменить проведённую ведомость на дату — иначе ошибку в ней не исправить."""
    from datetime import date as _date
    from app.services.tank_inventory import cancel

    cid = await _company_id(user, db)
    result = await cancel(db, cid, _date.fromisoformat(body.date),
                          station_codes=body.station_codes)
    await bump_version(db, cid)
    await db.commit()
    return result


# ═══════════════════════════════════════════════════════════════
# Пооперационные транзакции (реализации) — STS /v2/transactions
# ═══════════════════════════════════════════════════════════════

# Прогресс фонового синка транзакций по компании (в памяти воркера).
_TX_SYNC: dict[str, dict] = {}


class TxSyncRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    station_codes: list[int] | None = None
    all_period: bool = False


async def _tx_sync_bg(company_id, date_from, date_to, station_codes, all_period):
    """Фоновая загрузка реализаций: по станциям × помесячным окнам, дедуп по STS id."""
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
            if loaded:
                # новые реализации → инвалидация версионного кеша аналитики продаж
                await bump_version(db, company_id)
            _TX_SYNC[key] = {"running": False, "stations_done": total, "stations_total": total,
                             "loaded": loaded, "message": f"готово: {loaded} реализаций"}
    except Exception as e:  # noqa: BLE001
        _TX_SYNC[key] = {"running": False, "stations_done": 0, "stations_total": 0,
                         "loaded": 0, "message": f"сбой синка: {str(e)[:80]}"}


@router.post("/transactions/sync")
async def transactions_sync(
    body: TxSyncRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Запустить фоновую загрузку пооперационных транзакций (реализаций) из STS /v2/transactions."""
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


# Возраст, после которого активный купон считаем залежавшимся: срок жизни по
# умолчанию в STS — 7 дней, дальше клиент за сдачей, скорее всего, не вернётся.
COUPON_STALE_DAYS = 7

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


def _tx_conds(cid, df: str, dt: str, station_code, fuel_codes: list[int], pay_types: list[str], search,
              shift: int | None = None, receipt: int | None = None, pos: int | None = None,
              card: str | None = None, status: str | None = None):
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
        # Фильтр по НОРМАЛИЗОВАННОМУ виду оплаты (как в «Мониторе»): карточки KPI
        # сгруппированы по нему же. Строки до бэкфилла (payment_method IS NULL)
        # подхватываются по сырому имени — иначе выборка молча теряет их.
        conds.append(or_(T.payment_method.in_(pay_types),
                         and_(T.payment_method.is_(None), T.pay_type_name.in_(pay_types))))
    if status:
        conds.append(T.status == status)
    # Точные поля умного поиска («смена 9 азс 6 чек 42 карта 1234»).
    if shift is not None:
        conds.append(T.shift_number == shift)
    if receipt is not None:
        conds.append(T.receipt == receipt)
    if pos is not None:
        conds.append(T.pos == pos)
    if card:
        conds.append(T.card.ilike(f"%{card.strip()}%"))
    if search:
        # Свободный остаток строки: номер карты, вид топлива или число (чек/сумма).
        s = search.strip()
        free = [T.card.ilike(f"%{s}%"), T.fuel_name.ilike(f"%{s}%"), T.pay_type_name.ilike(f"%{s}%")]
        if s.isdigit():
            free.append(T.receipt == int(s))
        conds.append(or_(*free))
    return conds


@router.get("/transactions/rows")
async def transactions_rows(
    date_from: str = Query(...), date_to: str = Query(...),
    station_code: int | None = Query(None), fuel_codes: str | None = Query(None),
    pay_types: str | None = Query(None), search: str | None = Query(None),
    shift: int | None = Query(None), receipt: int | None = Query(None),
    pos: int | None = Query(None), card: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("dt"), order: str = Query("desc"),
    limit: int = Query(100, le=1000), offset: int = Query(0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Построчный реестр реализаций (пооперационно) — серверная пагинация/фильтры/сортировка.
    fuel_codes/pay_types — CSV (мультивыбор через KPI-карточки); shift/receipt/pos/card —
    точные поля умного поиска, search — свободный остаток строки."""
    cid = await _company_id(user, db)
    T = FuelTransaction
    conds = _tx_conds(cid, date_from, date_to, station_code, _csv_ints(fuel_codes),
                      _csv_strs(pay_types), search, shift, receipt, pos, card, status)
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
        "id": str(r.id), "ext_id": r.ext_id, "dt": r.dt.isoformat() if r.dt else None,
        "station_code": r.station_code, "station_name": names.get(r.station_code) or f"АЗС {r.station_code}",
        "shift_number": r.shift_number, "receipt": r.receipt,
        "pos": r.pos, "nozzle": r.nozzle, "tank": r.tank,
        "fuel_code": r.fuel_code, "fuel_name": r.fuel_name,
        "pay_type_name": r.pay_type_name,
        "payment_method": r.payment_method or normalize_payment_method(r.pay_type_name),
        "card": r.card,
        "liters": float(r.liters or 0), "price": float(r.price) if r.price is not None else None,
        "amount": float(r.amount or 0),
        "mass": float(r.mass) if r.mass is not None else None,
        "density": float(r.density) if r.density is not None else None,
        "order_qty": float(r.order_qty) if r.order_qty is not None else None,
        "order_cost": float(r.order_cost) if r.order_cost is not None else None,
        "status": r.status or "completed",
    } for r in rows]
    return {
        "total": int(tot[0]),
        "totals": {"count": int(tot[0]), "liters": round(float(tot[1]), 2), "amount": round(float(tot[2]), 2)},
        "rows": out,
    }


@router.get("/transactions/pivot")
async def transactions_pivot(
    date_from: str = Query(...), date_to: str = Query(...),
    dims: str = Query(..., description="ключи измерений через запятую, например station,fuel"),
    station_code: int | None = Query(None), fuel_codes: str | None = Query(None),
    pay_types: str | None = Query(None), search: str | None = Query(None),
    shift: int | None = Query(None), receipt: int | None = Query(None),
    pos: int | None = Query(None), card: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20000, le=50000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Листья сводной по реализациям: агрегаты по НАБОРУ измерений, без иерархии.

    Дерево, подытоги и доли собирает браузер. Отсюда два следствия: SQL остаётся
    обычным GROUP BY без ROLLUP, а смена ПОРЯДКА уровней не идёт в сеть - это те же
    листья, просто иначе собранные.

    Фильтры берутся тем же билдером, что и построчный реестр (`_tx_conds`). Копия
    здесь была бы гарантией расхождения: правку внесли бы в одном месте, а сводная
    показывала бы не то, что список.
    """
    from app.services.pivot_dims import (
        dim_label, dim_select, metric_selects, metrics_catalog, parse_dims,
    )

    cid = await _company_id(user, db)
    try:
        keys = parse_dims(dims, "transactions")
    except ValueError as e:
        raise HTTPException(400, str(e))

    conds = _tx_conds(cid, date_from, date_to, station_code, _csv_ints(fuel_codes),
                      _csv_strs(pay_types), search, shift, receipt, pos, card, status)
    cols = [dim_select(k, "transactions").label(f"d{i}") for i, k in enumerate(keys)]
    metrics = metric_selects("transactions")
    mcols = [expr.label(f"m{i}") for i, (_, expr, _) in enumerate(metrics)]
    res = (await db.execute(select(*cols, *mcols).where(*conds)
                            .group_by(*cols).limit(limit + 1))).all()
    truncated = len(res) > limit
    rows = res[:limit]

    # Подписи станций: код в ключе, имя на экране. «АЗС 210» без названия читается плохо.
    names: dict[str, str] = {}
    if "station" in keys:
        names = {str(int(st.code)): st.name for st in (await db.execute(
            select(FuelStation).where(FuelStation.company_id == cid))).scalars().all()}

    return {
        "dims": keys,
        "labels": [dim_label(k, "transactions") for k in keys],
        "metrics": metrics_catalog("transactions"),
        "stationNames": names,
        "rows": [{
            "keys": [r[i] for i in range(len(keys))],
            "m": {k: round(float(r[len(keys) + j]), d) for j, (k, _, d) in enumerate(metrics)},
        } for r in rows],
        "truncated": truncated,
    }


@router.get("/receipts/pivot")
async def receipts_pivot(
    dims: str = Query(..., description="ключи измерений через запятую, например supplier,fuel"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    station_code: int | None = Query(None),
    limit: int = Query(20000, le=50000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Листья сводной по приёмке ТТН.

    Метрики здесь свои и это не косметика: приёмку сверяют по МАССЕ, объём зависит от
    температуры. Отклонение факта от документа считается суммой по листу, а не
    выводится из средних - иначе подытог перестанет сходиться с строками.

    Отдельный источник от реализаций намеренно: смешивать приход и продажу в одной
    сводной нельзя, итоги разойдутся с обоими экранами сразу.
    """
    from app.services.pivot_dims import (
        dim_label, dim_select, metric_selects, metrics_catalog, parse_dims,
    )

    cid = await _company_id(user, db)
    try:
        keys = parse_dims(dims, "receipts")
    except ValueError as e:
        raise HTTPException(400, str(e))

    conds = [FuelReceipt.company_id == cid]
    if date_from:
        conds.append(FuelReceipt.received_at >= datetime.fromisoformat(date_from))
    if date_to:
        d1 = date.fromisoformat(date_to)
        conds.append(FuelReceipt.received_at <= datetime(d1.year, d1.month, d1.day, 23, 59, 59))
    if station_code is not None:
        st = (await db.execute(select(FuelStation.id).where(
            FuelStation.company_id == cid, FuelStation.code == station_code))).scalar()
        conds.append(FuelReceipt.station_id == st)

    cols = [dim_select(k, "receipts").label(f"d{i}") for i, k in enumerate(keys)]
    metrics = metric_selects("receipts")
    mcols = [expr.label(f"m{i}") for i, (_, expr, _) in enumerate(metrics)]
    res = (await db.execute(select(*cols, *mcols).where(*conds)
                            .group_by(*cols).limit(limit + 1))).all()
    truncated = len(res) > limit
    rows = res[:limit]

    # У поступлений станция хранится идентификатором, а не кодом: подписи обязательны,
    # иначе в разрезе будут UUID.
    names: dict[str, str] = {}
    if "station" in keys:
        names = {str(st.id): st.name for st in (await db.execute(
            select(FuelStation).where(FuelStation.company_id == cid))).scalars().all()}

    return {
        "dims": keys,
        "labels": [dim_label(k, "receipts") for k in keys],
        "metrics": metrics_catalog("receipts"),
        "stationNames": names,
        "rows": [{
            "keys": [r[i] for i in range(len(keys))],
            "m": {k: round(float(r[len(keys) + j]), d) for j, (k, _, d) in enumerate(metrics)},
        } for r in rows],
        "truncated": truncated,
    }


@router.get("/pivot/dims")
async def pivot_dims_catalog(
    source: str = Query("transactions", description="transactions | receipts"),
    user: User = Depends(get_current_user),
):
    """Справочник измерений и метрик источника (тот же, что режет SQL)."""
    from app.services.pivot_dims import dims_catalog, metrics_catalog
    try:
        return {"dims": dims_catalog(source), "metrics": metrics_catalog(source)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/transactions/coupon")
async def transactions_coupon(
    station_code: int = Query(...), dt: str = Query(..., description="время реализации, ISO"),
    number: str = Query(..., description="номер купона из реализации"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Дата выдачи купона, которым оплачена реализация (STS /v1/coupons).

    В реализации остаётся только номер; когда купон выдан, знает лишь справочник STS.
    Ищем по станции реализации за 30 дней до него (срок жизни купона по умолчанию 7
    дней, запас на «долгие»), как это делает «Монитор».
    """
    from app.services.fuel_transactions import resolve_sts
    from app.services.sts_client import sts_get_coupons
    cid = await _company_id(user, db)
    conn = await resolve_sts(db, cid)
    if conn is None:
        return {"issued_at": None, "reason": "нет STS-источника у компании"}
    try:
        op_dt = datetime.fromisoformat(dt)
    except ValueError:
        raise HTTPException(400, "Неверный формат времени реализации")
    beg = (op_dt - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    end = (op_dt + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    for sysid in conn["systems"]:
        try:
            coupons = await sts_get_coupons(conn["base_url"], conn["login"], conn["pwd"],
                                            sysid, station_code, beg, end)
        except Exception:  # noqa: BLE001 — нет доступа к STS: покажем только номер купона
            continue
        for c in coupons:
            if str(c.get("number")) == str(number):
                return {"issued_at": c.get("dt")}
    return {"issued_at": None}


@router.get("/coupons")
async def coupons_journal(
    date_from: str = Query(...), date_to: str = Query(...),
    station_code: int | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Журнал купонов (сдача топливом) — STS /v1/coupons за период.

    Купоны не материализуются в Ledger: это живой остаток обязательства перед
    клиентом, он меняется при каждом отпуске, и хранить его копию значило бы
    показывать вчерашний долг. Читаем напрямую, ответ отдаёт всю сеть системы
    одним запросом.

    Дата реализации берётся из реализаций: у купонной операции в `card` лежит номер
    купона, и по нему видно, когда купон отоварили, — в «Мониторе» эта колонка
    пустует, потому что STS её не отдаёт вовсе.
    """
    from app.services.fuel_transactions import resolve_sts
    from app.services.sts_client import sts_get_coupons
    cid = await _company_id(user, db)
    conn = await resolve_sts(db, cid)
    if conn is None:
        return {"coupons": [], "stats": {}, "warning": "нет STS-источника у компании"}

    d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    beg, end = f"{d0.isoformat()} 00:00:00", f"{d1.isoformat()} 23:59:59"
    raw: list[dict] = []
    warning: str | None = None
    for sysid in conn["systems"]:
        try:
            raw.extend(await sts_get_coupons(conn["base_url"], conn["login"], conn["pwd"],
                                             sysid, station_code, beg, end))
        except Exception as e:  # noqa: BLE001 — одна система недоступна, остальные отдаём
            warning = f"STS не ответил по системе {sysid}: {str(e)[:80]}"

    names = {int(s.code): s.name for s in (await db.execute(
        select(FuelStation).where(FuelStation.company_id == cid))).scalars().all()}

    # Когда купон отоварили: последний реализация с этим номером карты и оплатой «Купон».
    numbers = {str(c.get("number")) for c in raw if c.get("number") is not None}
    redeemed: dict[str, str] = {}
    if numbers:
        T = FuelTransaction
        rows = (await db.execute(
            select(T.card, func.max(T.dt)).where(
                T.company_id == cid, T.card.in_(numbers),
                func.coalesce(T.payment_method, T.pay_type_name).ilike("%купон%"),
            ).group_by(T.card))).all()
        redeemed = {r[0]: r[1].isoformat() for r in rows if r[0] and r[1]}

    def _f(v) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    out = []
    for c in raw:
        code = _int_or_none(c.get("station"))
        svc = c.get("service") or {}
        state = c.get("state") or {}
        typ = c.get("type") or {}
        usr = c.get("user") or {}
        number = str(c.get("number")) if c.get("number") is not None else ""
        out.append({
            "number": number,
            "dt": c.get("dt"),
            "redeemed_at": redeemed.get(number),
            "station_code": code,
            "station_name": names.get(code) or (f"АЗС {code}" if code else "—"),
            "pos": _int_or_none(c.get("pos")), "shift": _int_or_none(c.get("shift")),
            "opernum": _int_or_none(c.get("opernum")),
            "fuel_code": _int_or_none(svc.get("service_code")),
            "fuel_name": svc.get("service_name"),
            "price": _f(c.get("price")),
            "qty_total": _f(c.get("qty_total")), "qty_used": _f(c.get("qty_used")),
            "rest_qty": _f(c.get("rest_qty")),
            "summ_total": _f(c.get("summ_total")), "summ_used": _f(c.get("summ_used")),
            "rest_summ": _f(c.get("rest_summ")),
            "state_id": _int_or_none(state.get("id")), "state_name": state.get("name") or "—",
            "type_name": typ.get("name"), "author": usr.get("name"),
            "comment": c.get("comment") or None,
        })
    out.sort(key=lambda r: r["dt"] or "", reverse=True)

    # Активный купон (state_id = 0) — непогашенное обязательство перед клиентом;
    # «просрочен» считаем по возрасту (у STS отдельного состояния для этого нет).
    now = datetime.now(timezone.utc)
    issued_liters = sum(r["qty_total"] for r in out)
    active = [r for r in out if r["state_id"] == 0]
    stale = 0
    for r in active:
        try:
            issued_at = datetime.fromisoformat(r["dt"]) if r["dt"] else None
        except (TypeError, ValueError):
            continue
        if issued_at is None:
            continue
        # STS отдаёт время без зоны; вычитание наивной даты из aware падает
        # TypeError, и счётчик молча оставался нулевым.
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        if (now - issued_at).days > COUPON_STALE_DAYS:
            stale += 1
    return {
        "coupons": out,
        "stats": {
            "issued": len(out), "issued_liters": round(issued_liters, 2),
            "used": len([r for r in out if r["qty_used"] > 0]),
            "used_liters": round(sum(r["qty_used"] for r in out), 2),
            "active": len(active),
            "active_liters": round(sum(r["rest_qty"] for r in active), 2),
            "active_amount": round(sum(r["rest_summ"] for r in active), 2),
            "stale": stale, "stale_days": COUPON_STALE_DAYS,
        },
        "warning": warning,
    }


@router.get("/transactions/filters")
async def transactions_filters(
    date_from: str = Query(...), date_to: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Значения для фильтров реестра (станции/топливо/виды оплаты за период).
    Виды оплаты — нормализованные: по ним же фильтруется реестр и считаются карточки."""
    cid = await _company_id(user, db)
    T = FuelTransaction
    conds = _tx_conds(cid, date_from, date_to, None, [], [], None)
    names = {int(s.code): s.name for s in (await db.execute(
        select(FuelStation).where(FuelStation.company_id == cid))).scalars().all()}
    st = (await db.execute(select(T.station_code).where(*conds).distinct().order_by(T.station_code))).scalars().all()
    fu = (await db.execute(select(T.fuel_code, T.fuel_name).where(*conds).distinct())).all()
    pay = func.coalesce(T.payment_method, T.pay_type_name)
    pt = (await db.execute(select(pay).where(*conds).distinct().order_by(pay))).scalars().all()
    fuels = sorted({(r[0], r[1]) for r in fu if r[0] is not None}, key=lambda x: x[0])
    return {
        "stations": [{"code": c, "name": names.get(c) or f"АЗС {c}"} for c in st],
        "fuels": [{"code": c, "name": n} for c, n in fuels],
        "pay_types": [p for p in pt if p],
    }


@router.get("/transactions/overview")
async def transactions_overview(
    date_from: str = Query(...), date_to: str = Query(...),
    station_code: int | None = Query(None), fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Агрегаты периода для KPI-карточек «Операций»: итого + по видам топлива + по оплате
    + кросс-разрез «топливо × оплата».

    Не зависит от кликов по KPI (fuel/pay) — они фильтруют только список. Кросс нужен
    для ПЕРЕКРЁСТНОГО пересчёта карточек без похода в сеть (как в «Мониторе»): выбрал
    АИ-92 — карточки оплат показывают суммы только по нему, и наоборот. Разрез мелкий
    (виды топлива × виды оплаты — десятки строк), считается тем же проходом.
    Оплата группируется по НОРМАЛИЗОВАННОМУ имени; у строк до бэкфилла его нет —
    падаем на сырое (coalesce), иначе они соберутся в общую корзину «—».
    """
    cid = await _company_id(user, db)
    T = FuelTransaction
    pay = func.coalesce(T.payment_method, T.pay_type_name)
    # fuel_codes здесь — сквозной фильтр вида нефтепродукта из шапки рабочей области
    # (не клик по карточке): разрезы обязаны считаться в тех же границах, что и реестр.
    conds = _tx_conds(cid, date_from, date_to, station_code, _csv_ints(fuel_codes), [], None)
    kpi = (await db.execute(select(
        func.count(), func.coalesce(func.sum(T.liters), 0), func.coalesce(func.sum(T.amount), 0)
    ).where(*conds))).one()
    fu = (await db.execute(select(
        T.fuel_code, T.fuel_name, func.count().label("n"),
        func.coalesce(func.sum(T.liters), 0).label("l"), func.coalesce(func.sum(T.amount), 0).label("a"),
    ).where(*conds).group_by(T.fuel_code, T.fuel_name)
        .order_by(func.coalesce(func.sum(T.amount), 0).desc()))).all()
    pm = (await db.execute(select(
        pay.label("m"), func.count().label("n"),
        func.coalesce(func.sum(T.liters), 0).label("l"), func.coalesce(func.sum(T.amount), 0).label("a"),
    ).where(*conds).group_by(pay)
        .order_by(func.coalesce(func.sum(T.amount), 0).desc()))).all()
    cross = (await db.execute(select(
        T.fuel_code, T.fuel_name, pay.label("m"), func.count().label("n"),
        func.coalesce(func.sum(T.liters), 0).label("l"), func.coalesce(func.sum(T.amount), 0).label("a"),
    ).where(*conds).group_by(T.fuel_code, T.fuel_name, pay))).all()
    return {
        "kpi": {"count": int(kpi[0]), "liters": round(float(kpi[1]), 2), "amount": round(float(kpi[2]), 2)},
        "by_fuel": [{"fuel_code": r.fuel_code, "fuel_name": r.fuel_name or "—", "count": int(r.n),
                     "liters": round(float(r.l), 2), "amount": round(float(r.a), 2)} for r in fu],
        "by_payment": [{"name": r.m or "—", "count": int(r.n),
                        "liters": round(float(r.l), 2), "amount": round(float(r.a), 2)} for r in pm],
        "by_fuel_payment": [{"fuel_code": r.fuel_code, "fuel_name": r.fuel_name or "—",
                             "name": r.m or "—", "count": int(r.n),
                             "liters": round(float(r.l), 2), "amount": round(float(r.a), 2)} for r in cross],
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


# ═══════════════════════════════════════════════════════════════
# Аналитика продаж по реализациям (раздел «Продажи» → «Аналитика» / «Коммерция»)
# ═══════════════════════════════════════════════════════════════

_FA_GROUPS = {"station", "fuel", "pay_type", "channel", "segment", "hour", "weekday",
              "shift", "card", "day", "week", "decade", "month", "quarter"}
_FA_BUCKETS = {"day", "week", "decade", "month", "quarter"}
_FA_METRICS = {"amount", "liters", "fills", "avg_check", "avg_fill", "avg_price"}


def _fa_dates(date_from: str, date_to: str) -> tuple[date, date]:
    try:
        return date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(400, "Неверный формат дат (ожидается YYYY-MM-DD)")


def _fa_check(value: str | None, allowed: set[str], what: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(400, f"Недопустимое значение {what}: {value}")


@router.get("/analytics/fills")
async def analytics_fills(
    date_from: str = Query(...), date_to: str = Query(...),
    group_by: str = Query("station"),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    card: str | None = Query(None), top: int = Query(500, le=2000),
    dim: str | None = Query(None), dim_val: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Разрез реализаций: выручка/литры/реализации/ср.чек/ср.заправка/ср.цена по группе.

    `dim`/`dim_val` — сужение до одного значения ДРУГОГО разреза (провал вглубь).
    """
    cid = await _company_id(user, db)
    _fa_check(group_by, _FA_GROUPS, "group_by")
    _fa_check(dim, _FA_GROUPS, "dim")
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).fills(
        cid, df, dt, group_by=group_by,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None, card=card or None, top=top,
        dim=dim or None, dim_val=dim_val)


@router.get("/analytics/fills/timeseries")
async def analytics_fills_timeseries(
    date_from: str = Query(...), date_to: str = Query(...),
    bucket: str = Query("day"), metric: str = Query("amount"),
    series_by: str | None = Query(None), top_n: int = Query(5, le=12),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    card: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Динамика метрики реализаций по бакетам; series_by → multi-series (топ-N + «Прочие»)."""
    cid = await _company_id(user, db)
    _fa_check(bucket, _FA_BUCKETS, "bucket")
    _fa_check(metric, _FA_METRICS, "metric")
    _fa_check(series_by, _FA_GROUPS, "series_by")
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).fills_timeseries(
        cid, df, dt, bucket=bucket, metric=metric, series_by=series_by or None, top_n=top_n,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None, card=card or None)


@router.get("/analytics/fills/slice")
async def analytics_fills_slice(
    date_from: str = Query(...), date_to: str = Query(...),
    bucket: str = Query("month"), group_by: str | None = Query(None),
    metric: str = Query("amount"), top_n: int = Query(8, le=1000),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Нарезка периода на интервалы; строки = разрез (или «Вся сеть»)."""
    cid = await _company_id(user, db)
    _fa_check(bucket, _FA_BUCKETS, "bucket")
    _fa_check(metric, _FA_METRICS, "metric")
    _fa_check(group_by, _FA_GROUPS, "group_by")
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).fills_slice(
        cid, df, dt, bucket=bucket, group_by=group_by or None, metric=metric, top_n=top_n,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None)


@router.get("/analytics/fills/compare")
async def analytics_fills_compare(
    periods: str = Query(..., description="CSV пар YYYY-MM-DD:YYYY-MM-DD (2–4 периода)"),
    group_by: str = Query("station"), metric: str = Query("amount"),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Сравнение 2–4 произвольных периодов по разрезу."""
    cid = await _company_id(user, db)
    _fa_check(group_by, _FA_GROUPS, "group_by")
    _fa_check(metric, _FA_METRICS, "metric")
    pairs: list[tuple[str, str]] = []
    for chunk in periods.split(","):
        parts = chunk.strip().split(":")
        if len(parts) != 2:
            raise HTTPException(400, f"Неверный период: {chunk}")
        _fa_dates(parts[0], parts[1])  # валидация формата
        pairs.append((parts[0], parts[1]))
    if not 2 <= len(pairs) <= 4:
        raise HTTPException(400, "Ожидается 2–4 периода")
    return await FuelSalesAnalytics(db).fills_compare_multi(
        cid, tuple(pairs), group_by=group_by, metric=metric,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None)


@router.get("/analytics/fills/heatmap")
async def analytics_fills_heatmap(
    date_from: str = Query(...), date_to: str = Query(...),
    metric: str = Query("fills"),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Матрица час (0–23) × день недели (1=Пн..7=Вс) по реализациям."""
    cid = await _company_id(user, db)
    _fa_check(metric, _FA_METRICS, "metric")
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).fills_heatmap(
        cid, df, dt, metric=metric,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None)


@router.get("/analytics/fills/new-cards")
async def analytics_fills_new_cards(
    date_from: str = Query(...), date_to: str = Query(...),
    bucket: str = Query("month"),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Когорты «новые карты» по интервалам нарезки периода."""
    cid = await _company_id(user, db)
    _fa_check(bucket, _FA_BUCKETS, "bucket")
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).new_cards_slice(
        cid, df, dt, bucket=bucket,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None)


@router.get("/analytics/fills/new-cards/list")
async def analytics_fills_new_cards_list(
    date_from: str = Query(...), date_to: str = Query(...),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    limit: int = Query(500, le=2000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Конкретные новые карты интервала (для модалки списка)."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).new_cards_list(
        cid, df, dt,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None, limit=limit)


# ─── Сеть: оборудование, актив, клиенты, визиты (fuel_network_analytics) ────
# Отвечают не «сколько продали» (это разрезы выше), а «где сеть не работает и где
# лежат деньги» — перенос приёмов ЭЗС-контура на топливный грейн.

_FN_LEVELS = {"pos", "nozzle"}
_FN_DIMS = {"station", "fuel", "station_fuel"}
_FN_MEASURES = {"amount", "liters"}
_FN_ABC_BUCKETS = {"week", "month"}


@router.get("/analytics/pumps")
async def analytics_pumps(
    date_from: str = Query(...), date_to: str = Query(...),
    level: str = Query("nozzle"),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Загрузка ТРК и пистолетов: реализаций в сутки на единицу, простой, молчащие."""
    cid = await _company_id(user, db)
    _fa_check(level, _FN_LEVELS, "level")
    df, dt = _fa_dates(date_from, date_to)
    return await FuelNetworkAnalytics(db).pumps(
        cid, df, dt, level=level,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None)


@router.get("/analytics/silent")
async def analytics_silent(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Станции, ТРК и пистолеты без единой реализации за период (с историей до него)."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelNetworkAnalytics(db).silent(cid, df, dt, fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/analytics/shift-coverage")
async def analytics_shift_coverage(
    date_from: str = Query(...), date_to: str = Query(...),
    station_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Полнота сменных отчётов: за каждый рабочий день станции ждём хотя бы одну смену.

    Путь под `/analytics/`, а не `/shifts/coverage`: там уже живёт `/shifts/{shift_id}`,
    и статический сегмент пришлось бы объявлять раньше динамического.
    """
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelNetworkAnalytics(db).shift_coverage(
        cid, df, dt, station_codes=tuple(_csv_ints(station_codes)))


@router.get("/analytics/unit")
async def analytics_unit(
    date_from: str = Query(...), date_to: str = Query(...),
    station_code: int = Query(...),
    pos: int | None = Query(None), nozzle: int | None = Query(None),
    fuel_code: int | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Расшифровка строки «Загрузки ТРК»: динамика по суткам, часы, простои, источник."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelNetworkAnalytics(db).unit_detail(
        cid, df, dt, station_code=station_code, pos=pos, nozzle=nozzle, fuel_code=fuel_code)


@router.get("/analytics/abc-xyz")
async def analytics_abc_xyz(
    date_from: str = Query(...), date_to: str = Query(...),
    dimension: str = Query("station_fuel"), bucket: str = Query("week"),
    measure: str = Query("amount"),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """ABC (вклад) × XYZ (стабильность спроса) + квинтили концентрации."""
    cid = await _company_id(user, db)
    _fa_check(dimension, _FN_DIMS, "dimension")
    _fa_check(bucket, _FN_ABC_BUCKETS, "bucket")
    _fa_check(measure, _FN_MEASURES, "measure")
    df, dt = _fa_dates(date_from, date_to)
    return await FuelNetworkAnalytics(db).abc_xyz(
        cid, df, dt, dimension=dimension, bucket=bucket, measure=measure,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None)


@router.get("/analytics/clients")
async def analytics_clients(
    date_from: str = Query(...), date_to: str = Query(...),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Когорты карт по частоте покупок + приток/отток базы к прошлому периоду."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelNetworkAnalytics(db).clients(
        cid, df, dt,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None)


@router.get("/analytics/visits")
async def analytics_visits(
    date_from: str = Query(...), date_to: str = Query(...),
    gap_min: int = Query(10, ge=1, le=120),
    station_codes: str | None = Query(None), fuel_codes: str | None = Query(None),
    segment: str | None = Query(None), channel: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Визиты вместо реализаций: склейка соседних реализаций карты на одной станции."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelNetworkAnalytics(db).visits(
        cid, df, dt, gap_min=gap_min,
        station_codes=tuple(_csv_ints(station_codes)), fuel_codes=tuple(_csv_ints(fuel_codes)),
        segment=segment or None, channel=channel or None)


@router.get("/analytics/insights")
async def analytics_insights(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Короткие выводы для шапки «Обзора» — из тех же агрегатов, что и экраны."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelNetworkAnalytics(db).insights(cid, df, dt, fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/tariffs/grid")
async def tariffs_grid(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Прайс-сетка станция × вид топлива (номинал стеллы, диапазон, факт)."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).tariff_grid(cid, df, dt, fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/tariffs/deviations")
async def tariffs_deviations(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Отклонения факт-цены станций от сети + скидки по каналам (сменный блок)."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).price_deviations(cid, df, dt, fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/tariffs/timeseries")
async def tariffs_timeseries(
    date_from: str = Query(...), date_to: str = Query(...),
    bucket: str = Query("week"), fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Динамика цены ₽/л по видам топлива (средневзвешенная по литрам)."""
    cid = await _company_id(user, db)
    _fa_check(bucket, _FA_BUCKETS, "bucket")
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).price_timeseries(
        cid, df, dt, bucket=bucket, fuel_codes=tuple(_csv_ints(fuel_codes)))


# ─── Ценообразование: решение о цене, а не атрибут продажи ────────────────
# Отдельный сервис (fuel_pricing), потому что разрезы продаж отвечают «по какой цене
# продали», а эти три ручки — «кто, когда и на сколько цену двинул и что вышло».


@router.get("/pricing/changes")
async def pricing_changes(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Журнал изменений цены: было → стало, шаг, удержание, реакция объёма, волны."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelPricing(db).changes(cid, df, dt, fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/pricing/calendar")
async def pricing_calendar(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_code: int = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Матрица станция × день по одному виду топлива: как волна идёт по сети."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelPricing(db).calendar(cid, df, dt, fuel_code=fuel_code)


@router.get("/pricing/spread")
async def pricing_spread(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Разброс цен по сети на конец периода: размах, ранг станции, возраст цены."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelPricing(db).spread(cid, df, dt, fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/corporate/overview")
async def corporate_overview(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """KPI корпоративного сегмента (топливные карты + ведомости)."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).corporate_overview(cid, df, dt, fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/corporate/counterparties")
async def corporate_counterparties(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Контрагенты-процессоры corp-сегмента (уровень вида оплаты)."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).corporate_counterparties(cid, df, dt, fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/corporate/cards")
async def corporate_cards(
    date_from: str = Query(...), date_to: str = Query(...),
    sort: str = Query("amount"), order: str = Query("desc"),
    limit: int = Query(50, le=1000), offset: int = Query(0),
    search: str | None = Query(None), segment: str = Query("corp"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Реестр карт сегмента: пагинация/сортировка/поиск по номеру."""
    cid = await _company_id(user, db)
    if sort not in FuelSalesAnalytics._CARDS_SORT:
        raise HTTPException(400, f"Недопустимая сортировка: {sort}")
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).corporate_cards(
        cid, df, dt, sort=sort, order=order, limit=limit, offset=offset,
        search=search or None, segment=segment)


@router.get("/retail/overview")
async def retail_overview(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """KPI розницы: нал/безнал, структура, гистограмма чеков, понедельно."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).retail_overview(cid, df, dt, fuel_codes=tuple(_csv_ints(fuel_codes)))


@router.get("/retail/loyalty")
async def retail_loyalty(
    date_from: str = Query(...), date_to: str = Query(...),
    fuel_codes: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Лояльность розницы по токенам банковских карт."""
    cid = await _company_id(user, db)
    df, dt = _fa_dates(date_from, date_to)
    return await FuelSalesAnalytics(db).retail_loyalty(cid, df, dt, fuel_codes=tuple(_csv_ints(fuel_codes)))


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
    """АЗС с координатами и метрики за период — для Карты АЗС.

    Выручка, реализации и объём отвечают на ОДИН вопрос («насколько станция большая»)
    и рисуют три почти одинаковых картинки. Чтобы карта отвечала на разные
    вопросы, к ним добавлены величины, которые не следуют за размером станции:
    средний чек и цена (какой клиент и по какой цене заправляется), интенсивность
    (реализаций в сутки — сравнивает станции при разной длине периода), динамика к
    прошлому периоду (кто растёт, кто падает) и ведущий вид топлива (структура
    спроса: дизельная точка на трассе и бензиновая в городе — разный бизнес).
    """
    cid = await _company_id(user, db)
    d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    T = FuelTransaction
    days = max(1, (d1 - d0).days + 1)
    # База сравнения — предыдущий отрезок той же длины, встык к выбранному.
    p1 = d0 - timedelta(days=1)
    p0 = p1 - timedelta(days=days - 1)

    def _window(a: date, b: date):
        return [T.company_id == cid,
                T.dt >= datetime(a.year, a.month, a.day),
                T.dt <= datetime(b.year, b.month, b.day, 23, 59, 59)]

    agg = (await db.execute(select(
        T.station_code, func.count().label("n"),
        func.coalesce(func.sum(T.liters), 0).label("l"),
        func.coalesce(func.sum(T.amount), 0).label("a"),
        func.count(func.distinct(func.nullif(func.trim(T.card), ""))).label("cards"),
        func.max(T.dt).label("last_at"),
    ).where(*_window(d0, d1)).group_by(T.station_code))).all()
    prev = {int(r.station_code): float(r.a) for r in (await db.execute(select(
        T.station_code, func.coalesce(func.sum(T.amount), 0).label("a"),
    ).where(*_window(p0, p1)).group_by(T.station_code))).all()}
    # Структура спроса: разбивка выручки по видам топлива внутри станции.
    # Выражение группировки — ОДИН объект на select и group_by: два одинаковых
    # coalesce дают разные bind-параметры, и Postgres отвечает «must appear in the
    # GROUP BY clause». Из-за этого ручка падала, а карта показывала пустое
    # состояние «нет АЗС с координатами» — хотя координаты у 12 станций есть.
    fuel_col = func.coalesce(T.fuel_name, "—")
    mix_rows = (await db.execute(select(
        T.station_code, fuel_col.label("fuel"),
        func.coalesce(func.sum(T.amount), 0).label("a"),
        func.coalesce(func.sum(T.liters), 0).label("l"),
    ).where(*_window(d0, d1)).group_by(T.station_code, fuel_col))).all()
    mix: dict[int, list[dict]] = {}
    for r in mix_rows:
        mix.setdefault(int(r.station_code), []).append(
            {"fuel_name": str(r.fuel), "amount": round(float(r.a), 2), "liters": round(float(r.l), 1)})

    m = {int(r.station_code): r for r in agg}
    stations = (await db.execute(select(FuelStation).where(FuelStation.company_id == cid))).scalars().all()
    out = []
    for s in stations:
        code = int(s.code)
        r = m.get(code)
        amount = round(float(r.a), 2) if r else 0.0
        liters = round(float(r.l), 2) if r else 0.0
        fills = int(r.n) if r else 0
        prev_amount = round(prev.get(code, 0.0), 2)
        by_fuel = sorted(mix.get(code, []), key=lambda x: -x["amount"])
        top = by_fuel[0] if by_fuel else None
        out.append({
            "code": s.code, "name": s.name, "address": s.address,
            "latitude": float(s.latitude) if s.latitude is not None else None,
            "longitude": float(s.longitude) if s.longitude is not None else None,
            "transactions": fills,
            "liters": liters,
            "amount": amount,
            "cards": int(r.cards) if r else 0,
            "last_at": r.last_at.isoformat() if r and r.last_at else None,
            "avg_check": round(amount / fills, 2) if fills else 0.0,
            "avg_price": round(amount / liters, 2) if liters else 0.0,
            "fills_per_day": round(fills / days, 2),
            "prev_amount": prev_amount,
            # Рост в процентах к прошлому периоду; None — сравнивать не с чем
            # (станция открылась внутри периода), и это НЕ то же самое, что ноль.
            "growth_pct": (round((amount - prev_amount) / prev_amount * 100, 1)
                           if prev_amount > 0 else None),
            "top_fuel": top["fuel_name"] if top else None,
            "top_fuel_pct": (round(top["amount"] / amount * 100, 1)
                             if top and amount > 0 else None),
            "by_fuel": by_fuel,
        })
    with_coords = sum(1 for s in out if s["latitude"] is not None)
    return {"stations": out, "with_coords": with_coords, "total": len(out),
            "days": days, "prev_period": {"from": p0.isoformat(), "to": p1.isoformat()}}


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
