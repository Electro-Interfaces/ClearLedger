"""
Fuel CRUD: станции, смены, ТТН, документы на экспорт.
+ Нормализация из STS API.
"""

import uuid
from datetime import datetime, timedelta, timezone


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
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    FuelStation, FuelShift, FuelTank, FuelPump, FuelCashMovement,
    FuelReceipt, FuelExportDoc, FuelShiftSale, ExportPacket, User, DataEntry,
)
from app.services.fuel_documents import build_shift_documents, build_ttn_documents
from app.services.fuel_mappings import MappingContext, load_mapping_context
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
    return [_shift_out(s, stations.get(s.station_id)) for s in shifts]


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
    # Разбивка продаж по каналам оплаты (для вкладки «Реализация»)
    sales = (await db.execute(
        select(FuelShiftSale).where(FuelShiftSale.shift_id == shift.id))).scalars().all()
    # ТТН периода станции (для вкладки «Поступления»)
    rcpts = (await db.execute(
        select(FuelReceipt).where(
            FuelReceipt.company_id == cid, FuelReceipt.station_id == shift.station_id)
        .order_by(FuelReceipt.received_at.desc()).limit(50))).scalars().all()
    return ShiftDetailOut(
        **out.model_dump(),
        tanks=[TankOut.model_validate(t) for t in shift.tanks],
        pumps=[PumpOut.model_validate(p) for p in shift.pumps],
        cash_movements=[CashMovementOut.model_validate(m) for m in shift.cash_movements],
        sales=[ShiftSaleOut.model_validate(s) for s in sales],
        receipts=[_receipt_out(r, station) for r in rcpts],
        raw_report=shift.raw_report,
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_id = await _company_id(user, db)
    q = select(FuelReceipt).where(FuelReceipt.company_id == company_id)
    if station_code is not None:
        q = q.join(FuelStation).where(FuelStation.code == station_code)
    q = q.order_by(FuelReceipt.created_at.desc()).limit(200)
    rcpts = list((await db.execute(q)).scalars())
    st_ids = {r.station_id for r in rcpts}
    stations = {st.id: st for st in (await db.execute(
        select(FuelStation).where(FuelStation.id.in_(st_ids)))).scalars()} if st_ids else {}
    return [_receipt_out(r, stations.get(r.station_id)) for r in rcpts]


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
        sales_data = report.get("sales", [])
        chan_agg: dict[tuple[str, int], dict] = {}
        for sale in sales_data:
            pay_name = sale.get("pay_type", {}).get("name", "")
            channel, warehouse = ctx.resolve_channel(pay_name)
            if not channel:      # не замаплено (→ctx.unmapped) или явный игнор (купон/прокачка)
                continue
            for f in sale.get("fuel", []):
                rel = f.get("release", {})
                try:
                    code = int(f.get("service", {}).get("service_code"))
                except (TypeError, ValueError):
                    continue
                agg = chan_agg.setdefault(
                    (channel, code),
                    {"liters": 0.0, "amount": 0.0, "discount": 0.0, "warehouse": warehouse},
                )
                agg["liters"] += float(rel.get("volume", 0) or 0)
                agg["amount"] += float(rel.get("cost", 0) or 0)
                agg["discount"] += float(rel.get("discount", 0) or 0)

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

def _shift_out(s: FuelShift, station: FuelStation | None = None) -> ShiftOut:
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
        created_at=s.created_at,
    )


def _receipt_out(r: FuelReceipt, station: FuelStation | None = None) -> ReceiptOut:
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
        doc_volume_liters=float(r.doc_volume_liters or 0),
        fact_volume_liters=float(r.fact_volume_liters or 0),
        diff_volume=float(r.diff_volume or 0),
        doc_mass_kg=float(r.doc_mass_kg or 0),
        fact_mass_kg=float(r.fact_mass_kg or 0),
        diff_mass=float(r.diff_mass or 0),
        density=float(r.density) if r.density else None,
        fact_density=float(r.fact_density) if r.fact_density else None,
        doc_temp=float(r.doc_temp) if r.doc_temp is not None else None,
        fact_temp=float(r.fact_temp) if r.fact_temp is not None else None,
        status=r.status,
        received_at=r.received_at,
        created_at=r.created_at,
    )


# ═══════════════════════════════════════════════════════════════
# Документы 1С из смены/ТТН (конвейер L2 → пакеты для БП)
# ═══════════════════════════════════════════════════════════════

async def _build_shift_docs(db: AsyncSession, shift: FuelShift, company_id: uuid.UUID) -> list[dict]:
    """Построить документы 1С из разбивки смены (FuelShiftSale)."""
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
    sales = [{"payment_channel": s.payment_channel, "fuel_code": s.fuel_code,
              "liters": float(s.liters or 0), "amount": float(s.amount or 0),
              "discount": float(s.discount or 0), "warehouse_name": s.warehouse_name}
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
    """Построить документы 1С из ТТН (Перемещение тонн + Комплектация)."""
    station = await db.get(FuelStation, receipt.station_id)
    ctx = await load_mapping_context(db, company_id)
    fm = ctx.fuel(receipt.fuel_code) if receipt.fuel_code is not None else None
    # Тонны для документов: из массы ТТН, а при её отсутствии — из объёма×плотности
    # (плотность ТТН или справочная из маппинга). Иначе ТТН без массы не дала бы
    # НИ ОДНОГО документа (гард tonnes>0 в build_ttn_documents).
    liters = float(receipt.doc_volume_liters or 0)
    mass_kg = float(receipt.doc_mass_kg or 0)
    dens = float(receipt.density) if receipt.density else (
        float(fm.density) if (fm and fm.density is not None) else None)
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
