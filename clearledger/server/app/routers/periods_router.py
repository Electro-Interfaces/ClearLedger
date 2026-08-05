"""
/api/periods/* — учётные периоды.

Идеология v3: TradeLedger не управляет периодами — она их РЕПЛИЦИРУЕТ из
БП (через дату запрета изменений) или строит сводку на основе
импортированных AccountingDoc. UI показывает: какие месяцы есть в данных,
сколько в них документов и закрыт ли период в эталоне.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import (
    AccountingDoc, DataEntry, FuelShift, OneCConnection, OneCSyncLog, Period,
    StockOnHand, User,
)
from app.services.goods_dashboard import _day

router = APIRouter(prefix="/periods", tags=["Учётные периоды"])


def _ts(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


# ─── Схемы ───────────────────────────────────────────────────

class PeriodRow(BaseModel):
    id: str | None = None        # null, если ещё нет записи в таблице periods
    year: int
    month: int
    status: str                  # open | closed
    closedAt: str | None = None
    closureSource: str           # from_bp | manual | derived
    docsCount: int
    minDate: str | None = None
    maxDate: str | None = None


class PeriodsSummary(BaseModel):
    items: list[PeriodRow]
    totalDocs: int
    openCount: int
    closedCount: int


class PeriodToggleRequest(BaseModel):
    company_id: str
    year: int
    month: int
    closed: bool                 # true → закрыть, false → открыть


# ─── GET /periods/summary ────────────────────────────────────

@router.get("/summary", response_model=PeriodsSummary)
async def periods_summary(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сводка по периодам компании.

    Источник:
    - docsCount, minDate, maxDate берутся из AccountingDoc.date (строка
      "YYYY-MM-DD"), агрегируем по (year, month).
    - status, closedAt, closureSource берутся из таблицы Period — если
      записи нет, статус "open", источник "derived".
    """
    cid = await assert_company_member(company_id, current_user, db)

    # 1) Агрегат из документов. SUBSTR(date, 1, 4)/(6,2) — у нас даты строкой.
    year_col = func.substring(AccountingDoc.date, 1, 4)
    month_col = func.substring(AccountingDoc.date, 6, 2)
    docs_stmt = (
        select(
            year_col.label("y"),
            month_col.label("m"),
            func.count(AccountingDoc.id).label("c"),
            func.min(AccountingDoc.date).label("mn"),
            func.max(AccountingDoc.date).label("mx"),
        )
        .where(AccountingDoc.company_id == cid, AccountingDoc.date.is_not(None))
        .group_by(year_col, month_col)
    )
    docs_rows = (await db.execute(docs_stmt)).all()
    doc_buckets: dict[tuple[int, int], dict] = {}
    for y, m, c, mn, mx in docs_rows:
        try:
            yi, mi = int(y), int(m)
        except (TypeError, ValueError):
            continue
        if not (1 <= mi <= 12):
            continue
        doc_buckets[(yi, mi)] = {"count": int(c or 0), "min": mn, "max": mx}

    # 2) Period-записи (имеют статус и closed_at)
    period_rows = (await db.execute(
        select(Period).where(Period.company_id == cid)
    )).scalars().all()
    period_map: dict[tuple[int, int], Period] = {(p.year, p.month): p for p in period_rows}

    # 3) Объединяем — берём все ключи из периодов и доков
    all_keys = set(doc_buckets.keys()) | set(period_map.keys())
    items: list[PeriodRow] = []
    for y, m in sorted(all_keys, reverse=True):
        b = doc_buckets.get((y, m), {})
        p = period_map.get((y, m))
        items.append(PeriodRow(
            id=str(p.id) if p else None,
            year=y,
            month=m,
            status=p.status if p else "open",
            closedAt=_ts(p.closed_at) if p and p.closed_at else None,
            closureSource=p.closure_source if p else "derived",
            docsCount=b.get("count", 0),
            minDate=b.get("min"),
            maxDate=b.get("max"),
        ))

    return PeriodsSummary(
        items=items,
        totalDocs=sum(b["count"] for b in doc_buckets.values()),
        openCount=sum(1 for it in items if it.status == "open"),
        closedCount=sum(1 for it in items if it.status == "closed"),
    )


# ─── GET /periods/readiness ──────────────────────────────────

class UnpostedRow(BaseModel):
    docType: str
    count: int


class OurDocRow(BaseModel):
    kind: str
    count: int
    lastDate: str | None = None
    stations: int


class PeriodReadiness(BaseModel):
    year: int
    month: int | None = None
    quarter: int | None = None
    scope: str                    # month | quarter | year
    docsInPeriod: int
    ourDocs: list[OurDocRow] = []
    unposted: list[UnpostedRow]
    unpostedTotal: int
    lastDocDate: str | None = None
    lastSyncAt: str | None = None
    lastSyncStatus: str | None = None
    negativePositions: int
    negativeWarehouses: int
    stockSnapshotAt: str | None = None
    futureDated: int
    backdatedIntoClosed: int


@router.get("/readiness", response_model=PeriodReadiness)
async def period_readiness(
    company_id: str = Query(...),
    year: int = Query(...),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Готовность периода к закрытию — то, что бухгалтер проверяет руками.

    Масштаб задают параметры: `month` — месяц, `quarter` — квартал (НДС и
    авансовые платежи считаются именно по нему), ни того ни другого — год.
    Проверки одни и те же, меняется только окно дат: закрывают месяц, а сдают
    квартал, и смотреть их приходится в обоих масштабах.

    Четыре вопроса, на каждый свой счётчик:

    1. Свежие ли данные. Экраны периода складывают то, что доехало из БП; если
       обратный поток стоит месяц, сводка будет выглядеть правдоподобно и врать.
       Поэтому дата последней синхронизации и дата самого свежего документа —
       первое, что показывается.
    2. Всё ли проведено. Документ со статусом «Записан» проводок не делает:
       период с непроведёнными закрыт только на бумаге.
    3. Нет ли отрицательных остатков. Минус на складе роняет расчёт
       себестоимости при закрытии месяца в БП. Считаем по последнему снимку —
       он не привязан к периоду, и подпись на экране об этом говорит.
    4. Нет ли документов не из своего времени: дата в будущем и документы,
       заведённые в уже закрытый период. Это классические ошибки ввода,
       которые всплывают на сдаче отчётности.
    """
    cid = await assert_company_member(company_id, current_user, db)

    # Окно дат: месяц — по префиксу, квартал и год — по границам, потому что
    # даты хранятся строкой «YYYY-MM-DD» и лексикографическое сравнение для них
    # совпадает с хронологическим.
    if month is not None:
        scope, start, end = "month", f"{year}-{month:02d}-01", f"{year}-{month:02d}-32"
    elif quarter is not None:
        first = quarter * 3 - 2
        scope, start, end = "quarter", f"{year}-{first:02d}-01", f"{year}-{first + 2:02d}-32"
    else:
        scope, start, end = "year", f"{year}-01-01", f"{year}-12-32"

    in_period = (AccountingDoc.company_id == cid,
                 AccountingDoc.date >= start, AccountingDoc.date <= end)

    docs_in_period = (await db.execute(
        select(func.count(AccountingDoc.id)).where(*in_period)
    )).scalar_one() or 0

    unposted_rows = (await db.execute(
        select(AccountingDoc.doc_type, func.count(AccountingDoc.id))
        .where(*in_period, AccountingDoc.status_1c != "Проведён")
        .group_by(AccountingDoc.doc_type)
        .order_by(func.count(AccountingDoc.id).desc())
    )).all()
    unposted = [UnpostedRow(docType=t or "—", count=int(c or 0)) for t, c in unposted_rows]

    last_doc_date = (await db.execute(
        select(func.max(AccountingDoc.date)).where(AccountingDoc.company_id == cid)
    )).scalar_one_or_none()

    # Последняя синхронизация именно ИЗ 1С: выгрузка наверх о свежести данных
    # ничего не говорит.
    sync_row = (await db.execute(
        select(OneCSyncLog.finished_at, OneCSyncLog.started_at, OneCSyncLog.status)
        .join(OneCConnection, OneCConnection.id == OneCSyncLog.connection_id)
        .where(OneCConnection.company_id == cid, OneCSyncLog.direction == "import")
        .order_by(OneCSyncLog.started_at.desc())
        .limit(1)
    )).first()

    neg = (await db.execute(
        select(func.count(StockOnHand.id), func.count(func.distinct(StockOnHand.warehouse_code)))
        .where(StockOnHand.company_id == cid, StockOnHand.quantity < 0)
    )).first()
    snapshot_at = (await db.execute(
        select(func.max(StockOnHand.snapshot_at)).where(StockOnHand.company_id == cid)
    )).scalar_one_or_none()

    # Документы НАШЕЙ линии за период — по видам.
    #
    # Закрытый день это не только сменный отчёт: товар приходил, перемещался между
    # складом и залом, списывался, пересчитывался. Пока этих документов нет, период
    # выглядит полным по сменам и при этом неполон по товару — ровно так и получались
    # минусы на кухне, где выпуск собран, а приход сырья нет.
    # Дата и станция лежат по-разному: товарный контур в «Смене», топливный —
    # плоскими полями STS. Читаем оба, иначе половина линии не считается.
    day_expr = func.left(func.coalesce(
        DataEntry.meta["Документ"]["Дата"].astext,
        DataEntry.meta["Смена"]["Открытие"].astext,
        DataEntry.meta["shift_date"].astext,
        DataEntry.meta["docDate"].astext), 10)
    station_any = func.coalesce(
        DataEntry.meta["Смена"]["КодАЗС"].astext,
        DataEntry.meta["station_code"].astext)
    our_rows = (await db.execute(
        select(DataEntry.doc_type_id, func.count(DataEntry.id), func.max(day_expr),
               func.count(func.distinct(station_any)))
        .where(DataEntry.company_id == cid,
               DataEntry.source.in_(("edge", "oneC")),
               day_expr >= start, day_expr <= end)
        .group_by(DataEntry.doc_type_id)
        .order_by(func.count(DataEntry.id).desc())
    )).all()
    our_docs = [OurDocRow(kind=k or "—", count=int(c or 0), lastDate=last, stations=int(st or 0))
                for k, c, last, st in our_rows]

    today = datetime.now(timezone.utc).date().isoformat()
    future_dated = (await db.execute(
        select(func.count(AccountingDoc.id))
        .where(AccountingDoc.company_id == cid, AccountingDoc.date > today)
    )).scalar_one() or 0

    backdated = (await db.execute(
        select(func.count(AccountingDoc.id))
        .where(AccountingDoc.company_id == cid, AccountingDoc.period_status == "closed",
               AccountingDoc.status_1c != "Проведён")
    )).scalar_one() or 0

    return PeriodReadiness(
        year=year, month=month, quarter=quarter, scope=scope,
        docsInPeriod=int(docs_in_period),
        ourDocs=our_docs,
        unposted=unposted,
        unpostedTotal=sum(u.count for u in unposted),
        lastDocDate=last_doc_date,
        lastSyncAt=_ts(sync_row[0] or sync_row[1]) if sync_row else None,
        lastSyncStatus=sync_row[2] if sync_row else None,
        negativePositions=int(neg[0] or 0) if neg else 0,
        negativeWarehouses=int(neg[1] or 0) if neg else 0,
        stockSnapshotAt=_ts(snapshot_at),
        futureDated=int(future_dated),
        backdatedIntoClosed=int(backdated),
    )


# ─── GET /periods/coverage ───────────────────────────────────

class CoverageCell(BaseModel):
    kind: str
    count: int
    lastDate: str | None = None
    silentDays: int          # рабочих дней станции ПОСЛЕ последнего такого документа
    typicalGap: int | None = None   # обычный интервал между такими документами, раб. дней
    status: str              # ok | attention | none


class CoverageStation(BaseModel):
    station: str
    workedDays: int          # дней со сменой
    expectedDays: int        # дней в окне работы станции внутри периода
    missingDays: int         # дней окна БЕЗ смены — прямой пробел первички
    firstDay: str | None = None
    lastDay: str | None = None
    status: str              # ok | attention
    docs: list[CoverageCell]


@router.get("/coverage", response_model=list[CoverageStation])
async def periods_coverage(
    company_id: str = Query(...),
    year: int = Query(...),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Покрыт ли РАБОЧИЙ день станции документами — по видам.

    Отсутствие документа само по себе ничего не значит: станция могла не работать,
    поставки могло не быть, пересчёт бывает раз в месяц. Значение имеет другое —
    станция работала, смены шли, а документа вида нет. Поэтому тишина меряется не
    календарными днями, а РАБОЧИМИ: сколько дней после последнего прихода
    (перемещения, списания…) станция отторговала, ничего такого не оформив.

    Рабочий день = день, за который есть сменный документ: топливный `shift_orp`
    либо товарный `retail_sale_sidegoods`. Это тот же признак, по которому день
    считается отработанным в карте полноты, — второго определения быть не должно.
    """
    cid = await assert_company_member(company_id, current_user, db)

    if month is not None:
        start, end = f"{year}-{month:02d}-01", f"{year}-{month:02d}-32"
    elif quarter is not None:
        first = quarter * 3 - 2
        start, end = f"{year}-{first:02d}-01", f"{year}-{first + 2:02d}-32"
    else:
        start, end = f"{year}-01-01", f"{year}-12-32"

    # Код станции и дата лежат в разных полях у разных источников: товарный контур
    # (edge/ЦБ) кладёт их в «Смену», топливный (STS) — плоскими `station_code` и
    # `shift_date`. Первая версия смотрела только в «Смену», и тринадцать топливных
    # станций из четырнадцати молча выпадали из покрытия.
    day_expr = func.left(func.coalesce(
        DataEntry.meta["Документ"]["Дата"].astext,
        DataEntry.meta["Смена"]["Открытие"].astext,
        DataEntry.meta["shift_date"].astext,
        DataEntry.meta["docDate"].astext), 10)
    station_expr = func.coalesce(
        DataEntry.meta["Смена"]["КодАЗС"].astext,
        DataEntry.meta["station_code"].astext)

    rows = (await db.execute(
        select(station_expr, DataEntry.doc_type_id, day_expr)
        .where(DataEntry.company_id == cid,
               DataEntry.source.in_(("edge", "oneC", "api")),
               day_expr >= start, day_expr <= end)
    )).all()

    # Рабочие дни и дни по видам — одним проходом: данных за месяц немного, а два
    # запроса разошлись бы по фильтрам при первой же правке.
    worked: dict[str, set[str]] = {}
    by_kind: dict[tuple[str, str], list[str]] = {}
    SHIFT_KINDS = {"shift_orp", "retail_sale_sidegoods"}
    for station, kind, day in rows:
        st = str(station or "").strip()
        if not st or not day:
            continue
        if kind in SHIFT_KINDS:
            worked.setdefault(st, set()).add(day)
        by_kind.setdefault((st, kind or "—"), []).append(day)

    out: list[CoverageStation] = []
    for st in sorted(worked, key=lambda s: (len(s), s)):
        days = sorted(worked[st])
        # Окно работы станции внутри периода: от первой смены до последней. Дни за
        # его пределами — не пробел, станция тогда просто не торговала (открылась
        # позже, закрылась раньше, стояла на ремонте).
        window = _days_between(days[0], days[-1]) if days else 0
        missing = max(0, window - len(days))

        cells: list[CoverageCell] = []
        for (station, kind), kind_days in by_kind.items():
            if station != st:
                continue
            uniq = sorted(set(kind_days))
            last = uniq[-1]
            # Тишина считается в РАБОЧИХ днях: календарные дни закрытой станции
            # тревогой не являются.
            silent = sum(1 for d in days if d > last)
            # Обычный ритм этого документа на этой станции: медиана интервалов.
            # Приход не обязан быть ежедневным, и «десять дней без поставки» значат
            # разное на станции, куда возят раз в три дня, и на той, куда раз в
            # две недели. Сравнивать надо с её собственным ритмом.
            gaps = [sum(1 for d in days if uniq[i] < d <= uniq[i + 1])
                    for i in range(len(uniq) - 1)]
            typical = sorted(gaps)[len(gaps) // 2] if gaps else None
            # Внимание, когда молчание вдвое дольше обычного ритма и при этом
            # набежала хотя бы неделя рабочих дней: удвоение короткого интервала
            # (был день — стало два) поводом не является.
            loud = silent >= 7 and (typical is None or silent >= max(2 * typical, 3))
            cells.append(CoverageCell(
                kind=kind, count=len(kind_days), lastDate=last, silentDays=silent,
                typicalGap=typical, status="attention" if loud else "ok"))

        out.append(CoverageStation(
            station=st, workedDays=len(days), expectedDays=window, missingDays=missing,
            firstDay=days[0] if days else None, lastDay=days[-1] if days else None,
            status="attention" if (missing > 0 or any(c.status == "attention" for c in cells)) else "ok",
            docs=sorted(cells, key=lambda c: -c.count),
        ))
    return out


def _days_between(first: str, last: str) -> int:
    """Календарных дней в окне включительно; на кривых датах — 0, а не исключение."""
    try:
        a = datetime.fromisoformat(first).date()
        b = datetime.fromisoformat(last).date()
    except ValueError:
        return 0
    return (b - a).days + 1


# ─── GET /periods/trend ──────────────────────────────────────

class TrendMonth(BaseModel):
    year: int
    month: int
    fuelShifts: int
    fuelAmount: float
    fuelLiters: float
    storeShifts: int
    soputka: float
    obshepit: float
    docs1c: int
    unposted: int


@router.get("/trend", response_model=list[TrendMonth])
async def periods_trend(
    company_id: str = Query(...),
    months: int = Query(6, ge=2, le=24),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Помесячный ряд по трём потокам — чтобы провал был виден без арифметики.

    Закрытие смотрят по одному месяцу, но понимают его только в сравнении: «в
    июле тридцать смен, в августе двенадцать» — это либо станция встала, либо
    данные не доехали, и оба ответа требуют действий. Одна цифра за месяц такого
    вопроса не задаёт.

    Считается из тех же источников, что и разделы потоков: топливо из смен STS,
    магазин и общепит — из секций сменного документа (там они разделены на
    приёме), документы — из поднятой первички БП.
    """
    cid = await assert_company_member(company_id, current_user, db)

    today = datetime.now(timezone.utc).date()
    keys: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    since = f"{keys[0][0]}-{keys[0][1]:02d}-01"

    buckets: dict[tuple[int, int], TrendMonth] = {
        k: TrendMonth(year=k[0], month=k[1], fuelShifts=0, fuelAmount=0, fuelLiters=0,
                      storeShifts=0, soputka=0, obshepit=0, docs1c=0, unposted=0)
        for k in keys
    }

    # Топливо: смена относится к месяцу по ОТКРЫТИЮ — так её датирует и 1С.
    month_col = func.to_char(FuelShift.opened_at, "YYYY-MM")
    fuel_rows = (await db.execute(
        select(month_col, func.count(FuelShift.id),
               func.coalesce(func.sum(FuelShift.total_amount), 0),
               func.coalesce(func.sum(FuelShift.total_liters), 0))
        .where(FuelShift.company_id == cid, FuelShift.opened_at.is_not(None))
        .group_by(month_col)
    )).all()
    for key, cnt, amount, liters in fuel_rows:
        k = _month_key(key)
        if k in buckets:
            buckets[k].fuelShifts = int(cnt or 0)
            buckets[k].fuelAmount = round(float(amount or 0), 2)
            buckets[k].fuelLiters = round(float(liters or 0), 2)

    # Магазин и общепит: суммы лежат в секциях сменного документа — там они
    # разделены ещё на приёме, и складывать их заново по номенклатуре незачем.
    entries = (await db.execute(
        select(DataEntry.meta).where(
            DataEntry.company_id == cid,
            DataEntry.doc_type_id == "retail_sale_sidegoods",
            DataEntry.source.in_(("edge", "oneC")),
        )
    )).scalars().all()
    for meta in entries:
        day = _day((meta or {}).get("Смена") or {})
        if not day or day < since:
            continue
        k = _month_key(day[:7])
        b = buckets.get(k)
        if b is None:
            continue
        sec = (meta or {}).get("Секции") or {}
        b.storeShifts += 1
        b.soputka += float((sec.get("продажа_сопутка") or {}).get("сумма") or 0)
        b.obshepit += float((sec.get("продажа_общепит") or {}).get("сумма") or 0)

    # Выражение группировки — ОДИН объект: два одинаковых с виду `func.substring`
    # несут разные bindparam, и Postgres не признаёт их за одно и то же поле
    # («must appear in the GROUP BY clause»).
    doc_month = func.substring(AccountingDoc.date, 1, 7)
    doc_rows = (await db.execute(
        select(doc_month, func.count(AccountingDoc.id),
               func.count(AccountingDoc.id).filter(AccountingDoc.status_1c != "Проведён"))
        .where(AccountingDoc.company_id == cid, AccountingDoc.date >= since)
        .group_by(doc_month)
    )).all()
    for key, cnt, unposted in doc_rows:
        k = _month_key(key)
        if k in buckets:
            buckets[k].docs1c = int(cnt or 0)
            buckets[k].unposted = int(unposted or 0)

    out = [buckets[k] for k in keys]
    for b in out:
        b.soputka = round(b.soputka, 2)
        b.obshepit = round(b.obshepit, 2)
    return out


def _month_key(value: str | None) -> tuple[int, int]:
    """«2026-08» → (2026, 8); мусор → (0, 0), такой ключ просто не найдётся."""
    try:
        y, m = str(value).split("-")[:2]
        return int(y), int(m)
    except (AttributeError, ValueError):
        return (0, 0)


# ─── POST /periods/toggle ────────────────────────────────────

@router.post("/toggle", response_model=PeriodRow)
async def toggle_period(
    body: PeriodToggleRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Открыть или закрыть период вручную (closure_source='manual').

    В производстве закрытие должно прилетать из БП ГИГ; этот эндпоинт —
    оперативный инструмент пока репликация ДатыЗапретаИзменения
    не реализована.
    """
    cid = await assert_company_member(body.company_id, current_user, db)
    if not (1 <= body.month <= 12):
        raise HTTPException(400, "month must be 1..12")

    existing = (await db.execute(
        select(Period).where(
            Period.company_id == cid,
            Period.year == body.year,
            Period.month == body.month,
        )
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is None:
        period = Period(
            company_id=cid,
            year=body.year,
            month=body.month,
            status="closed" if body.closed else "open",
            closed_at=now if body.closed else None,
            closed_by=current_user.email,
            closure_source="manual",
        )
        db.add(period)
        await db.flush()
    else:
        existing.status = "closed" if body.closed else "open"
        existing.closed_at = now if body.closed else None
        existing.closed_by = current_user.email if body.closed else None
        existing.closure_source = "manual"
        period = existing
        await db.flush()

    # docsCount считаем отдельно
    docs_count = (await db.execute(
        select(func.count(AccountingDoc.id)).where(
            AccountingDoc.company_id == cid,
            func.substring(AccountingDoc.date, 1, 4) == str(body.year),
            func.substring(AccountingDoc.date, 6, 2) == f"{body.month:02d}",
        )
    )).scalar_one()

    return PeriodRow(
        id=str(period.id),
        year=period.year,
        month=period.month,
        status=period.status,
        closedAt=_ts(period.closed_at),
        closureSource=period.closure_source,
        docsCount=int(docs_count or 0),
    )
