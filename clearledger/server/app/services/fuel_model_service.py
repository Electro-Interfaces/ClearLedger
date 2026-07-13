"""Модели данных топливного контура (ГИГ, fuel) для раздела «Нормализация».

Тот же контракт, что AnalyticsService.charge_model (слои L1→L4, звёздная схема
факт+измерения, качество/канонизация) — фронт-витрина EnergyNormalizationModel
переиспользуется как есть. Три набора данных по коннекторам ГИГ:
  • shifts    — смены STS (FuelShift + строки продаж + наливы fuel_transactions);
  • receipts  — поступления ТТН (FuelReceipt + себестоимость FIFO-партий);
  • sidegoods — сопутка/общепит ЦБ (DataEntry oneC + НСИ-кеши Cb*).
По всему датасету компании (без периода).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Numeric, case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CbBarcode, CbInventoryDoc, CbMovementDoc, CbNomenclature, CbRef,
    DataEntry, ExportPacket, FuelReceipt, FuelReceiptCost, FuelShift,
    FuelShiftSale, FuelStation, FuelTransaction,
)


def _pct(n: int, total: int) -> float:
    return round((n or 0) / total * 100, 1) if total else 0.0


async def _members(db: AsyncSession, col, where, limit: int) -> list[dict[str, Any]]:
    r = (await db.execute(
        select(col.label("m"), func.count().label("cnt"))
        .where(*where, col.is_not(None))
        .group_by(col).order_by(func.count().desc()).limit(limit)
    )).all()
    return [{"label": str(x.m), "count": int(x.cnt)} for x in r]


# ────────────────────────── смены STS ──────────────────────────

async def fuel_shifts_model(db: AsyncSession, company_id) -> dict[str, Any]:
    """Факт «Смена АЗС» (STS): грейн = 1 закрытая смена станции."""
    S = FuelShift
    agg = (await db.execute(select(
        func.count().label("rows"),
        func.coalesce(func.sum(S.total_amount), 0).label("amount"),
        func.coalesce(func.sum(S.total_liters), 0).label("liters"),
        func.min(S.closed_at).label("dt_min"),
        func.max(S.closed_at).label("dt_max"),
        func.count(S.opened_at).label("f_opened"),
        func.count(S.closed_at).label("f_closed"),
        func.count(S.operator).label("f_operator"),
        func.count(S.raw_report).label("f_raw"),
        func.coalesce(func.sum(case((S.total_amount > 0, 1), else_=0)), 0).label("f_amount"),
        func.coalesce(func.sum(case((S.total_liters > 0, 1), else_=0)), 0).label("f_liters"),
        func.count(distinct(S.station_id)).label("d_station"),
        func.count(distinct(func.to_char(S.closed_at, "YYYY-MM"))).label("d_month"),
        func.count(distinct(S.status)).label("d_status"),
    ).where(S.company_id == company_id))).one()
    rows = int(agg.rows or 0)
    if rows == 0:
        return {"rows": 0, "l1_files": 0, "layers": [], "fact": None,
                "dimensions": [], "quality": None}

    # строки продаж (агрегат смена×канал×топливо) и наливы (операции ТРК)
    sales = (await db.execute(select(
        func.count().label("rows"),
        func.count(distinct(FuelShiftSale.payment_channel)).label("d_channel"),
        func.count(distinct(FuelShiftSale.fuel_code)).label("d_fuel"),
        func.count(distinct(FuelShiftSale.shift_id)).label("shifts_covered"),
    ).where(FuelShiftSale.company_id == company_id))).one()
    tx = (await db.execute(select(
        func.count().label("rows"),
        func.count(FuelTransaction.shift_number).label("f_shift"),
        func.count(FuelTransaction.card).label("f_card"),
        func.count(distinct(FuelTransaction.pay_type_name)).label("d_pay"),
        func.count(distinct(FuelTransaction.fuel_name)).label("d_fuel_name"),
    ).where(FuelTransaction.company_id == company_id))).one()
    tx_rows = int(tx.rows or 0)

    where = [S.company_id == company_id]
    st_lbl = func.concat(func.coalesce(FuelStation.name, "АЗС"), " (", FuelStation.code, ")")
    m_station = [{"label": str(x.m), "count": int(x.cnt)} for x in (await db.execute(
        select(st_lbl.label("m"), func.count().label("cnt"))
        .select_from(S).join(FuelStation, FuelStation.id == S.station_id)
        .where(*where).group_by(st_lbl).order_by(func.count().desc()).limit(6)
    )).all()]
    m_status = await _members(db, S.status, where, 6)
    m_channel = [{"label": str(x.m), "count": int(x.cnt)} for x in (await db.execute(
        select(FuelShiftSale.payment_channel.label("m"), func.count().label("cnt"))
        .where(FuelShiftSale.company_id == company_id)
        .group_by(FuelShiftSale.payment_channel).order_by(func.count().desc()).limit(12)
    )).all()]
    m_fuel = await _members(
        db, FuelTransaction.fuel_name, [FuelTransaction.company_id == company_id], 8)

    # L1: сырые сменные отчёты STS (raw_report «как есть» внутри смены)
    l1 = int(agg.f_raw or 0)
    # L4: пакеты выгрузки в 1С по сменам (ОРП/ПКО/перемещения)
    l4 = int((await db.execute(select(func.count()).where(
        ExportPacket.company_id == company_id,
        ExportPacket.kind.in_(("shift_orp", "cash_pko", "fuel_transfer")),
    ))).scalar() or 0)

    layers = [
        {"key": "l1", "code": "L1 · RAW", "title": "Сырьё",
         "desc": "Сменные отчёты STS API «как есть» (psm/release/sales/receipt/money) — источник эталонной формы смены.",
         "records": l1, "unit": "отчётов", "tone": "raw"},
        {"key": "l2", "code": "L2 · CLEAN", "title": "Нормализованная база",
         "desc": "Смены + строки продаж (канал оплаты × топливо, канонизация 18 видов оплаты STS) + наливы (операции ТРК, дедуп по STS id).",
         "records": rows, "unit": "смен", "tone": "clean"},
        {"key": "l3", "code": "L3 · EXPORT", "title": "Витрины / срезы (OLAP)",
         "desc": "Продажи/Обзор/Каналы/Операции/Маржа FIFO — агрегаты куба под дашборды и экспорт.",
         "records": None, "unit": "куб", "tone": "export"},
        {"key": "l4", "code": "L4 · 1C_REF", "title": "Связь с 1С",
         "desc": "Пакеты выгрузки смен в БП (ОРП, ПКО, перемещения топлива) — очередь L3→1С.",
         "records": l4, "unit": "пакетов", "tone": "ref",
         **({"status": "planned"} if l4 == 0 else {})},
    ]

    amount = float(agg.amount or 0)
    liters = float(agg.liters or 0)
    fact = {
        "table": "fuel_shifts",
        "name": "Смена АЗС",
        "grain": "1 строка = 1 закрытая смена станции (STS)",
        "rows": rows,
        "period": {"from": agg.dt_min.date().isoformat() if agg.dt_min else None,
                   "to": agg.dt_max.date().isoformat() if agg.dt_max else None},
        "measures": [
            {"key": "count", "label": "Смены", "value": rows, "unit": "шт", "agg": "COUNT"},
            {"key": "amount", "label": "Выручка", "value": round(amount, 2), "unit": "₽", "agg": "SUM"},
            {"key": "liters", "label": "Топливо", "value": round(liters, 0), "unit": "л", "agg": "SUM"},
            {"key": "tx", "label": "Наливы (операции ТРК)", "value": tx_rows, "unit": "шт", "agg": "COUNT"},
            {"key": "sales_rows", "label": "Строк продаж (канал×топливо)", "value": int(sales.rows or 0), "unit": "шт", "agg": "COUNT"},
            {"key": "avg_shift", "label": "Средняя выручка смены", "value": round(amount / rows, 0) if rows else 0, "unit": "₽", "agg": "AVG"},
        ],
    }

    dimensions = [
        {"key": "station", "label": "Станция", "field": "station_id → fuel_stations",
         "cardinality": int(agg.d_station or 0), "fill_pct": 100.0,
         "canonical": True, "members": m_station},
        {"key": "channel", "label": "Канал оплаты", "field": "fuel_shift_sales.payment_channel",
         "cardinality": int(sales.d_channel or 0), "fill_pct": _pct(int(sales.shifts_covered or 0), rows),
         "canonical": True, "members": m_channel},
        {"key": "fuel", "label": "Вид топлива", "field": "fuel_code / fuel_name",
         "cardinality": int(sales.d_fuel or 0), "fill_pct": 100.0,
         "canonical": True, "members": m_fuel},
        {"key": "status", "label": "Статус смены", "field": "status",
         "cardinality": int(agg.d_status or 0), "fill_pct": 100.0,
         "canonical": False, "members": m_status},
        {"key": "time", "label": "Время", "field": "closed_at",
         "cardinality": int(agg.d_month or 0), "fill_pct": _pct(int(agg.f_closed or 0), rows),
         "canonical": False, "grain": "год → месяц → день → смена", "members": []},
    ]

    quality_fields = [
        {"field": "shift_number", "label": "Номер смены", "role": "ключ (дедуп со станцией)", "fill_pct": 100.0},
        {"field": "opened_at", "label": "Открытие смены", "role": "измерение · время", "fill_pct": _pct(int(agg.f_opened or 0), rows)},
        {"field": "closed_at", "label": "Закрытие смены", "role": "измерение · время", "fill_pct": _pct(int(agg.f_closed or 0), rows)},
        {"field": "operator", "label": "Оператор", "role": "атрибут", "fill_pct": _pct(int(agg.f_operator or 0), rows)},
        {"field": "total_amount", "label": "Выручка смены", "role": "мера (>0)", "fill_pct": _pct(int(agg.f_amount or 0), rows)},
        {"field": "total_liters", "label": "Литры смены", "role": "мера (>0)", "fill_pct": _pct(int(agg.f_liters or 0), rows)},
        {"field": "raw_report", "label": "Сырой отчёт STS (L1)", "role": "источник эталонной формы", "fill_pct": _pct(l1, rows)},
        {"field": "source_uuid", "label": "ИсточникUUID (для 1С)", "role": "ключ идемпотентности", "fill_pct": 100.0},
        {"field": "tx.shift_number", "label": "Налив привязан к смене", "role": "связь фактов", "fill_pct": _pct(int(tx.f_shift or 0), tx_rows) if tx_rows else 0.0},
        {"field": "tx.card", "label": "Карта в наливе", "role": "атрибут (корпоратив)", "fill_pct": _pct(int(tx.f_card or 0), tx_rows) if tx_rows else 0.0},
    ]
    canonicalization = [
        {"name": "Канал оплаты", "from": f"вид оплаты STS ({int(tx.d_pay or 0)} сырых)", "to": "канон-канал (PaymentChannel)",
         "members": int(sales.d_channel or 0), "coverage_pct": 100.0},
        {"name": "Вид топлива", "from": "код/имя STS", "to": "канонический код топлива",
         "members": int(sales.d_fuel or 0), "coverage_pct": 100.0},
        {"name": "Дедупликация смен", "from": "станция + № смены", "to": "UNIQUE(station_id, shift_number)",
         "members": rows, "coverage_pct": 100.0},
        {"name": "Дедупликация наливов", "from": "STS transaction id", "to": "UNIQUE(company, station, ext_id)",
         "members": tx_rows, "coverage_pct": 100.0},
        {"name": "Связь наливов со сменой", "from": "shift_number налива", "to": "смена (факт-к-факту)",
         "members": None, "coverage_pct": _pct(int(tx.f_shift or 0), tx_rows) if tx_rows else 0.0},
    ]

    return {"rows": rows, "l1_files": l1, "layers": layers, "fact": fact,
            "dimensions": dimensions,
            "quality": {"fields": quality_fields, "canonicalization": canonicalization}}


# ────────────────────────── поступления ТТН ──────────────────────────

async def fuel_receipts_model(db: AsyncSession, company_id) -> dict[str, Any]:
    """Факт «Поступление топлива (ТТН)»: грейн = 1 ТТН на станцию."""
    R = FuelReceipt
    agg = (await db.execute(select(
        func.count().label("rows"),
        func.coalesce(func.sum(R.doc_volume_liters), 0).label("doc_vol"),
        func.coalesce(func.sum(R.fact_volume_liters), 0).label("fact_vol"),
        func.coalesce(func.sum(R.doc_mass_kg), 0).label("doc_mass"),
        func.coalesce(func.sum(R.diff_volume), 0).label("diff_vol"),
        func.min(R.received_at).label("dt_min"),
        func.max(R.received_at).label("dt_max"),
        func.count(R.ttn).label("f_ttn"),
        func.count(R.supplier).label("f_supplier"),
        func.count(R.density).label("f_density"),
        func.count(R.fact_density).label("f_fact_density"),
        func.count(R.received_at).label("f_received"),
        func.count(R.shift_number).label("f_shift"),
        func.count(R.tank).label("f_tank"),
        func.count(R.raw_entry_id).label("f_raw"),
        func.count(distinct(R.fuel_name)).label("d_fuel"),
        func.count(distinct(R.supplier)).label("d_supplier"),
        func.count(distinct(R.station_id)).label("d_station"),
        func.count(distinct(func.to_char(R.received_at, "YYYY-MM"))).label("d_month"),
    ).where(R.company_id == company_id))).one()
    rows = int(agg.rows or 0)
    if rows == 0:
        return {"rows": 0, "l1_files": 0, "layers": [], "fact": None,
                "dimensions": [], "quality": None}

    # себестоимость партий (FIFO): сколько ТТН закрыто ценой
    costed = int((await db.execute(select(func.count(distinct(FuelReceiptCost.ttn))).where(
        FuelReceiptCost.company_id == company_id))).scalar() or 0)
    l4 = int((await db.execute(select(func.count()).where(
        ExportPacket.company_id == company_id,
        ExportPacket.kind.in_(("ttn_assembly", "ttn_transfer")),
    ))).scalar() or 0)

    where = [R.company_id == company_id]
    m_fuel = await _members(db, R.fuel_name, where, 8)
    m_supplier = await _members(db, R.supplier, where, 6)
    st_lbl = func.concat(func.coalesce(FuelStation.name, "АЗС"), " (", FuelStation.code, ")")
    m_station = [{"label": str(x.m), "count": int(x.cnt)} for x in (await db.execute(
        select(st_lbl.label("m"), func.count().label("cnt"))
        .select_from(R).join(FuelStation, FuelStation.id == R.station_id)
        .where(*where).group_by(st_lbl).order_by(func.count().desc()).limit(6)
    )).all()]

    layers = [
        {"key": "l1", "code": "L1 · RAW", "title": "Сырьё",
         "desc": "Приёмки STS API (receipts смены) «как есть» — документ-основание ТТН.",
         "records": int(agg.f_raw or 0), "unit": "документов", "tone": "raw",
         **({"status": "direct"} if int(agg.f_raw or 0) == 0 else {})},
        {"key": "l2", "code": "L2 · CLEAN", "title": "Нормализованная база",
         "desc": "ТТН: объём/масса док↔факт, плотность, расхождения; себестоимость партии (FIFO) поверх — ₽/л для маржи.",
         "records": rows, "unit": "ТТН", "tone": "clean"},
        {"key": "l3", "code": "L3 · EXPORT", "title": "Витрины / срезы (OLAP)",
         "desc": "Журнал поступлений, партии закупки, маржа FIFO — под дашборды и экспорт.",
         "records": None, "unit": "куб", "tone": "export"},
        {"key": "l4", "code": "L4 · 1C_REF", "title": "Связь с 1С",
         "desc": "Пакеты выгрузки ТТН в БП (комплектация/перемещение) — очередь L3→1С.",
         "records": l4, "unit": "пакетов", "tone": "ref",
         **({"status": "planned"} if l4 == 0 else {})},
    ]

    fact = {
        "table": "fuel_receipts",
        "name": "Поступление топлива (ТТН)",
        "grain": "1 строка = 1 ТТН на станцию",
        "rows": rows,
        "period": {"from": agg.dt_min.date().isoformat() if agg.dt_min else None,
                   "to": agg.dt_max.date().isoformat() if agg.dt_max else None},
        "measures": [
            {"key": "count", "label": "ТТН", "value": rows, "unit": "шт", "agg": "COUNT"},
            {"key": "doc_vol", "label": "Объём по документу", "value": round(float(agg.doc_vol or 0), 0), "unit": "л", "agg": "SUM"},
            {"key": "fact_vol", "label": "Объём фактический", "value": round(float(agg.fact_vol or 0), 0), "unit": "л", "agg": "SUM"},
            {"key": "doc_mass", "label": "Масса по документу", "value": round(float(agg.doc_mass or 0), 0), "unit": "кг", "agg": "SUM"},
            {"key": "diff_vol", "label": "Расхождение объёма", "value": round(float(agg.diff_vol or 0), 0), "unit": "л", "agg": "SUM"},
            {"key": "costed_pct", "label": "ТТН с себестоимостью (FIFO)", "value": _pct(costed, rows), "unit": "%", "agg": "AVG"},
        ],
    }

    dimensions = [
        {"key": "station", "label": "Станция", "field": "station_id → fuel_stations",
         "cardinality": int(agg.d_station or 0), "fill_pct": 100.0,
         "canonical": True, "members": m_station},
        {"key": "fuel", "label": "Вид топлива", "field": "fuel_name / fuel_code",
         "cardinality": int(agg.d_fuel or 0), "fill_pct": 100.0,
         "canonical": True, "members": m_fuel},
        {"key": "supplier", "label": "Поставщик", "field": "supplier",
         "cardinality": int(agg.d_supplier or 0), "fill_pct": _pct(int(agg.f_supplier or 0), rows),
         "canonical": False, "members": m_supplier},
        {"key": "time", "label": "Время", "field": "received_at",
         "cardinality": int(agg.d_month or 0), "fill_pct": _pct(int(agg.f_received or 0), rows),
         "canonical": False, "grain": "год → месяц → день → смена приёмки", "members": []},
    ]

    quality_fields = [
        {"field": "ttn", "label": "Номер ТТН", "role": "ключ (дедуп)", "fill_pct": _pct(int(agg.f_ttn or 0), rows)},
        {"field": "received_at", "label": "Дата приёмки", "role": "измерение · время", "fill_pct": _pct(int(agg.f_received or 0), rows)},
        {"field": "supplier", "label": "Поставщик", "role": "измерение", "fill_pct": _pct(int(agg.f_supplier or 0), rows)},
        {"field": "density", "label": "Плотность (док.)", "role": "пересчёт кг↔л", "fill_pct": _pct(int(agg.f_density or 0), rows)},
        {"field": "fact_density", "label": "Плотность (факт)", "role": "пересчёт кг↔л", "fill_pct": _pct(int(agg.f_fact_density or 0), rows)},
        {"field": "shift_number", "label": "Смена приёмки", "role": "связь со сменой", "fill_pct": _pct(int(agg.f_shift or 0), rows)},
        {"field": "tank", "label": "Резервуар", "role": "атрибут", "fill_pct": _pct(int(agg.f_tank or 0), rows)},
        {"field": "cost_per_liter", "label": "Себестоимость партии (₽/л)", "role": "обогащение · FIFO", "fill_pct": _pct(costed, rows)},
        {"field": "source_uuid", "label": "ИсточникUUID (для 1С)", "role": "ключ идемпотентности", "fill_pct": 100.0},
    ]
    canonicalization = [
        {"name": "Дедупликация ТТН", "from": "№ ТТН + станция + топливо", "to": "уникальная ТТН",
         "members": rows, "coverage_pct": 100.0},
        {"name": "Пересчёт кг↔л", "from": "масса + плотность ТТН", "to": "литры (вычислено)",
         "members": None, "coverage_pct": _pct(int(agg.f_density or 0), rows)},
        {"name": "Себестоимость партии", "from": "закупочные партии / ручной ввод", "to": "cost_per_liter (FIFO)",
         "members": costed, "coverage_pct": _pct(costed, rows)},
        {"name": "Привязка к смене", "from": "номер смены STS", "to": "смена приёмки",
         "members": None, "coverage_pct": _pct(int(agg.f_shift or 0), rows)},
    ]

    return {"rows": rows, "l1_files": int(agg.f_raw or 0), "layers": layers, "fact": fact,
            "dimensions": dimensions,
            "quality": {"fields": quality_fields, "canonicalization": canonicalization}}


# ────────────────────────── сопутка/общепит ЦБ ──────────────────────────

async def sidegoods_model(db: AsyncSession, company_id) -> dict[str, Any]:
    """Факт «Смена сопутки (ОРП ЦБ)» + связанные документы дня и НСИ-кеши ЦБ."""
    E = DataEntry
    base = [E.company_id == company_id, E.source == "oneC"]
    doc_meta = E.meta

    # распаковка кортежей: Row.t в SQLAlchemy 2.0 — встроенный алиас, затеняет label
    by_type = {str(t): int(cnt) for t, cnt in (await db.execute(
        select(E.doc_type_id, func.count())
        .where(*base).group_by(E.doc_type_id)
    )).all()}
    retail = int(by_type.get("retail_sale_sidegoods") or 0)
    total_entries = sum(by_type.values())
    if retail == 0:
        return {"rows": 0, "l1_files": 0, "layers": [], "fact": None,
                "dimensions": [], "quality": None}

    # агрегаты retail-смен из JSONB (СуммаДокумента, GUID смены, дни)
    sm = (await db.execute(select(
        func.coalesce(func.sum(
            func.cast(func.nullif(doc_meta["Документ"]["СуммаДокумента"].as_string(), ""), Numeric)
        ), 0).label("amount"),
        func.count(func.nullif(doc_meta["Смена"]["Смена"].as_string(), "")).label("f_guid"),
        func.count(distinct(func.substr(doc_meta["Смена"]["Закрытие"].as_string(), 1, 7))).label("d_month"),
        func.min(func.substr(doc_meta["Смена"]["Закрытие"].as_string(), 1, 10)).label("dt_min"),
        func.max(func.substr(doc_meta["Смена"]["Закрытие"].as_string(), 1, 10)).label("dt_max"),
    ).where(*base, E.doc_type_id == "retail_sale_sidegoods"))).one()

    # НСИ-кеши ЦБ
    nom = (await db.execute(select(
        func.count().label("rows"), func.count(CbNomenclature.vat).label("f_vat"),
    ).where(CbNomenclature.company_id == company_id))).one()
    bc = (await db.execute(select(
        func.count().label("rows"), func.count(CbBarcode.owner_ref).label("f_owner"),
    ).where(CbBarcode.company_id == company_id))).one()
    refs = {str(k): int(cnt) for k, cnt in (await db.execute(
        select(CbRef.kind, func.count())
        .where(CbRef.company_id == company_id).group_by(CbRef.kind)
    )).all()}
    inv = int((await db.execute(select(func.count()).where(
        CbInventoryDoc.company_id == company_id))).scalar() or 0)
    mov = {str(k): int(cnt) for k, cnt in (await db.execute(
        select(CbMovementDoc.kind, func.count())
        .where(CbMovementDoc.company_id == company_id).group_by(CbMovementDoc.kind)
    )).all()}

    layers = [
        {"key": "l1", "code": "L1 · RAW", "title": "Сырьё",
         "desc": "Пакеты смен ЦБ ЭЛСИ.АЗК (COM-пул fetch_cb_shifts, v2) — принимаются напрямую в нормализацию.",
         "records": 0, "unit": "", "tone": "raw", "status": "direct"},
        {"key": "l2", "code": "L2 · CLEAN", "title": "Нормализованная база",
         "desc": "Смены сопутки/общепита (ОРП) + приходы ПТУ + выпуски блюд + ТТК + оприходования; движение (инвентаризации/списания/перемещения) и НСИ-кеши ЦБ (номенклатура, штрихкоды, склады, контрагенты).",
         "records": total_entries, "unit": "документов", "tone": "clean"},
        {"key": "l3", "code": "L3 · EXPORT", "title": "Пакеты БП",
         "desc": "Эмиттер «Выгрузка в БП»: пакет смены (retail/purchase/recipe/production/inventory/writeoff/transfer + НСИ + хеш) в каталог обмена.",
         "records": None, "unit": "по требованию", "tone": "export"},
        {"key": "l4", "code": "L4 · 1C_REF", "title": "Связь с 1С",
         "desc": "Приёмник TradeLedger.cfe в БП ГИГ: документы по ИсточникUUID, идемпотентность, сверка сумм (вторая ветка = дубль первой).",
         "records": None, "unit": "", "tone": "ref"},
    ]

    fact = {
        "table": "data_entries (source=oneC)",
        "name": "Смена сопутки (ОРП ЦБ)",
        "grain": "1 строка = 1 смена ОРП станции (сопутка + общепит)",
        "rows": retail,
        "period": {"from": sm.dt_min, "to": sm.dt_max},
        "measures": [
            {"key": "count", "label": "Смены (ОРП)", "value": retail, "unit": "шт", "agg": "COUNT"},
            {"key": "amount", "label": "Выручка сопутки", "value": round(float(sm.amount or 0), 2), "unit": "₽", "agg": "SUM"},
            {"key": "purchase", "label": "Приходы (ПТУ)", "value": int(by_type.get("purchase") or 0), "unit": "шт", "agg": "COUNT"},
            {"key": "production", "label": "Выпуски блюд", "value": int(by_type.get("production_release") or 0), "unit": "шт", "agg": "COUNT"},
            {"key": "recipe", "label": "ТТК (рецептуры)", "value": int(by_type.get("recipe") or 0), "unit": "шт", "agg": "COUNT"},
            {"key": "movement", "label": "Движение (инв/спис/перем)",
             "value": inv + int(mov.get("writeoff") or 0) + int(mov.get("transfer") or 0),
             "unit": "док", "agg": "COUNT"},
        ],
    }

    dimensions = [
        {"key": "doc_type", "label": "Тип документа", "field": "doc_type_id",
         "cardinality": len(by_type), "fill_pct": 100.0, "canonical": True,
         "members": [{"label": k, "count": v} for k, v in sorted(by_type.items(), key=lambda x: -x[1])]},
        {"key": "nomenclature", "label": "Номенклатура (НСИ ЦБ)", "field": "cb_nomenclature (GUID)",
         "cardinality": int(nom.rows or 0), "fill_pct": _pct(int(nom.f_vat or 0), int(nom.rows or 1)),
         "canonical": True, "members": []},
        {"key": "barcode", "label": "Штрихкоды", "field": "cb_barcode",
         "cardinality": int(bc.rows or 0), "fill_pct": _pct(int(bc.f_owner or 0), int(bc.rows or 1)),
         "canonical": False, "members": []},
        {"key": "counterparty", "label": "Контрагенты", "field": "cb_ref (kind=counterparty)",
         "cardinality": int(refs.get("counterparty") or 0), "fill_pct": 100.0,
         "canonical": True, "members": []},
        {"key": "warehouse", "label": "Склады / организации", "field": "cb_ref (warehouse/organization)",
         "cardinality": int(refs.get("warehouse") or 0) + int(refs.get("organization") or 0),
         "fill_pct": 100.0, "canonical": True, "members": []},
        {"key": "time", "label": "Время", "field": "Смена.Закрытие",
         "cardinality": int(sm.d_month or 0), "fill_pct": 100.0,
         "canonical": False, "grain": "месяц → день → смена (GUID)", "members": []},
    ]

    quality_fields = [
        {"field": "Смена.Смена (GUID)", "label": "GUID смены ЦБ", "role": "ключ пакета БП", "fill_pct": _pct(int(sm.f_guid or 0), retail)},
        {"field": "Документ.СуммаДокумента", "label": "Сумма смены", "role": "мера", "fill_pct": 100.0},
        {"field": "Документ.Проведен", "label": "Проведен/ПометкаУдаления", "role": "статус документа ЦБ", "fill_pct": 100.0},
        {"field": "cb_nomenclature.vat", "label": "Ставка НДС карточки", "role": "fallback НДС строк", "fill_pct": _pct(int(nom.f_vat or 0), int(nom.rows or 1))},
        {"field": "cb_barcode.owner_ref", "label": "Штрихкод → GUID товара", "role": "связь по GUID", "fill_pct": _pct(int(bc.f_owner or 0), int(bc.rows or 1))},
        {"field": "cb_inventory_doc.lines", "label": "Инвентаризации полными строками", "role": "носитель факта БП", "fill_pct": 100.0 if inv else 0.0},
    ]
    canonicalization = [
        {"name": "Ключ смены", "from": "ОРП ЦБ (ссылка)", "to": "GUID смены (Смена.Смена)",
         "members": retail, "coverage_pct": _pct(int(sm.f_guid or 0), retail)},
        {"name": "Ставка НДС", "from": "ставка строки ЦБ («22%», «НДС05»)", "to": "канон контракта (НДС22, НДС5_105…)",
         "members": None, "coverage_pct": 100.0},
        {"name": "Имена по GUID", "from": "GUID номенклатуры в строках", "to": "имя из кеша CbNomenclature",
         "members": int(nom.rows or 0), "coverage_pct": 100.0},
        {"name": "Дедупликация ПТУ", "from": "GUID документа ЦБ", "to": "уникальный DataEntry (двухсменные дни без дублей)",
         "members": int(by_type.get("purchase") or 0), "coverage_pct": 100.0},
        {"name": "Проведен/ПометкаУдаления", "from": "документ ЦБ", "to": "статус в пакете БП (удалённые не эмитятся)",
         "members": None, "coverage_pct": 100.0},
    ]

    return {"rows": retail, "l1_files": 0, "layers": layers, "fact": fact,
            "dimensions": dimensions,
            "quality": {"fields": quality_fields, "canonicalization": canonicalization}}
