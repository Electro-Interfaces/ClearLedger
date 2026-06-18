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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    FuelStation, FuelShift, FuelTank, FuelPump,
    FuelReceipt, FuelExportDoc, User, DataEntry,
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
                density=_density(t.get("density_end")),
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

        # ТТН — из receipt[]. Только если with_receipts (для /fuel/normalize);
        # в канале продаж приём отключён — он идёт каналом fuel_delivery.
        for r in (report.get("receipt", []) if with_receipts else []):
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
                density=_density(doc.get("density")),
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
                    "supplier_name": base.get("name", ""),
                    "supplier_inn":  base.get("inn", ""),
                    "inn":           base.get("inn", ""),
                    "fuel_name":     svc.get("service_name", ""),
                    "fuel_code":     str(svc.get("service_code", "") or ""),
                    "doc_volume_l":  str(doc.get("volume", 0)),
                    "doc_mass_kg":   str(doc.get("amount", 0)),
                    "fact_volume_l": str(fact.get("volume", 0)),
                    "fact_mass_kg":  str(fact.get("amount", 0)),
                    "density":       str(doc.get("density", "") or ""),
                    "station_code":  str(body.station_code),
                    "shift_id":      str(shift_num),
                },
            ))

        created += 1

    return {"created": created, "skipped": skipped, "station": station.name}


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
            dens = _density(doc.get("density") or fact.get("density"))
            ttn_dt = _parse_dt(r.get("dt"))
            ttn_date_iso = ttn_dt.date().isoformat() if ttn_dt else ""
            fuel_name = svc.get("service_name") or ""
            supplier = base.get("name") or ""
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
                    "supplier_name": supplier,
                    "supplier_inn":  base.get("inn", ""),
                    "inn":           base.get("inn", ""),
                    "fuel_name":     fuel_name,
                    "fuel_code":     str(code or ""),
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
