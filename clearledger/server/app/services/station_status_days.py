"""Ряд статусов станций по дням из книги витрины АСУиМ и сигналы «Первого окна».

Витрина приходит раз в сутки и отдаёт только текущий статус станции и её
разъёмов. Сигналы руководителя — «отключена больше суток», «коннектор не
работает», «доступность ниже 50%» — требуют истории, поэтому каждая книга
оставляет срез в `station_status_days` (см. модель).

Точность — сутки: «больше суток» значит «так же в двух книгах подряд».
Статус разъёма верен только у станции на связи: у станции «Нет связи» он
застывает на последнем значении (29.09: 456 из 475 разъёмов «Зарядка» в двух
книгах подряд стояли на станциях без связи, отключённых или выведенных), поэтому
неисправность разъёма ищется только у активных.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StationStatusDay

# Витрина пишет «дата_выгрузки» в UTC (22:00 = 01:00 МСК следующего дня, книга
# так и называется — 30.09 при выгрузке 29.09 22:00).
МСК = timedelta(hours=3)
РАЗЪЁМ_НЕИСПРАВЕН = ("Ошибка", "Недоступен")
ОКНО_ДОСТУПНОСТИ = 30
МИН_СРЕЗОВ = 7          # меньше срезов — долю доступности не считаем
СВЕЖЕСТЬ_ДНЕЙ = 3       # последняя книга старше — сигналы не показываем


def book_day(value: Any) -> date | None:
    """«дата_выгрузки» витрины → день среза по Москве."""
    if isinstance(value, datetime):
        return (value + МСК).date()
    if isinstance(value, date):
        return value
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return (datetime.fromisoformat(s[:19]) + МСК).date()
    except ValueError:
        return None


def build_day_rows(stations: list[dict[str, Any]], connectors: list[dict[str, Any]],
                   index: dict[str, Any]) -> tuple[date | None, dict[str, dict[str, Any]]]:
    """Строки листов «станции» и «коннекторы» → {id станции Учёта: срез}.

    `index` — ключ витрины → объект (`asuim_normalize._station_index`). Станция,
    которую не опознали, в ряд не попадает: писать срез некуда."""
    from app.services.stations_normalize import _oper_status

    by_ext: dict[str, dict[str, Any]] = {}
    day: date | None = None
    for r in stations:
        ext = str(r.get("id_станции") or "").strip()
        loc = index.get(ext) if ext else None
        if loc is None:
            continue
        day = day or book_day(r.get("дата_выгрузки"))
        status = (str(r.get("статус")).strip() or None) if r.get("статус") is not None else None
        by_ext[ext] = {"location_id": loc.id, "status_dev": status,
                       "operational_status": _oper_status(status), "connectors": {}}
    for r in connectors:
        cur = by_ext.get(str(r.get("id_станции") or "").strip())
        no = r.get("номер_коннектора")
        if cur is None or no is None or r.get("статус") is None:
            continue
        cur["connectors"][str(no)] = str(r["статус"]).strip()
    return day, {v["location_id"]: v for v in by_ext.values()}


async def record_book_day(db: AsyncSession, company_id, stations: list[dict[str, Any]],
                          connectors: list[dict[str, Any]]) -> dict[str, Any]:
    """Срез книги → `station_status_days` (идемпотентно по станции и дню)."""
    from app.services.asuim_normalize import _station_index

    day, rows = build_day_rows(stations, connectors, await _station_index(db, company_id))
    if day is None or not rows:
        return {"day": None, "stations": 0}
    cid = uuid.UUID(str(company_id))
    stmt = insert(StationStatusDay).values([
        {"id": uuid.uuid4(), "company_id": cid, "day": day, **v} for v in rows.values()])
    stmt = stmt.on_conflict_do_update(
        index_elements=["company_id", "location_id", "day"],
        set_={"status_dev": stmt.excluded.status_dev,
              "operational_status": stmt.excluded.operational_status,
              "connectors": stmt.excluded.connectors})
    await db.execute(stmt)
    return {"day": day.isoformat(), "stations": len(rows)}


def status_signals_from(days: list[date], series: dict[str, dict[date, tuple[str, dict]]],
                        avail_pct: float) -> dict[str, Any]:
    """Сигналы по ряду срезов. Чистая функция — считается и в тесте.

    `days` — даты срезов по возрастанию; `series` — станция → {день: (статус, разъёмы)}.
    Для каждой станции в ответе «с какого дня» — первый срез непрерывной серии
    того же статуса, чтобы в карточке было «без связи с 14.09», а не просто счёт."""
    if not days:
        return {}
    last = days[-1]
    prev = days[-2] if len(days) > 1 else None
    since_window = last - timedelta(days=ОКНО_ДОСТУПНОСТИ - 1)

    def since(s: dict[date, tuple[str, dict]], status: str) -> tuple[date, bool]:
        """Первый день серии и признак «серия идёт с первого среза» — тогда
        настоящее начало раньше, чем мы видим."""
        first = last
        for d in reversed(days):
            if d not in s or s[d][0] != status:
                break
            first = d
        return first, first == days[0]

    no_link, disabled, conn_fault, avail_low = [], [], [], []
    for lid, s in series.items():
        cur = s.get(last)
        if cur is None or cur[0] == "decommissioned":
            continue
        before = s.get(prev) if prev else None
        if cur[0] == "no_link":
            no_link.append((lid, since(s, "no_link")))
        if cur[0] == "disabled" and before and before[0] == "disabled":
            disabled.append((lid, since(s, "disabled")))
        if cur[0] == "working" and before and before[0] == "working":
            bad = [no for no, st in cur[1].items()
                   if st in РАЗЪЁМ_НЕИСПРАВЕН and before[1].get(no) in РАЗЪЁМ_НЕИСПРАВЕН]
            if bad:
                conn_fault.append((lid, len(bad)))
        # Доступность — только у станций, которые сейчас «Активные»: остальные уже
        # в «без связи» и «отключена», и карточка посчитала бы их дважды (30.09:
        # 110 из 119 с долей ниже 50% стояли без связи или отключёнными сейчас).
        window = [v for d, v in s.items() if d >= since_window]
        if cur[0] == "working" and len(window) >= МИН_СРЕЗОВ:
            share = 100 * sum(1 for v in window if v[0] == "working") / len(window)
            if share < avail_pct:
                avail_low.append((lid, round(share)))

    return {
        "status_day": last.isoformat(),
        # Первыми — те, что стоят дольше: их и разбирать первыми.
        "no_link": sorted(no_link, key=lambda x: x[1][0]),
        "disabled": sorted(disabled, key=lambda x: x[1][0]),
        "conn_fault": sorted(conn_fault, key=lambda x: -x[1]),
        "avail_low": sorted(avail_low, key=lambda x: x[1]),
    }


async def status_signals(db: AsyncSession, company_id, avail_pct: float,
                         today: date | None = None) -> dict[str, Any]:
    """Сигналы по статусам витрины на последний срез компании."""
    rows = (await db.execute(text("""
        select d.location_id, d.day, d.operational_status, d.connectors
        from station_status_days d
        join service_locations sl on sl.id = d.location_id
        where d.company_id = :cid and not coalesce(sl.is_test, false)
          and d.day > (select max(day) from station_status_days where company_id = :cid)
                      - make_interval(days => :win)
    """), {"cid": str(company_id), "win": ОКНО_ДОСТУПНОСТИ})).all()
    if not rows:
        return {}
    days = sorted({r.day for r in rows})
    if days[-1] < (today or date.today()) - timedelta(days=СВЕЖЕСТЬ_ДНЕЙ):
        return {}
    series: dict[str, dict[date, tuple[str, dict]]] = {}
    for r in rows:
        series.setdefault(r.location_id, {})[r.day] = (r.operational_status, r.connectors or {})
    return status_signals_from(days, series, avail_pct)


def status_now_from(days: list[date], series: dict[str, dict[date, tuple[str, dict]]]
                    ) -> dict[str, dict[str, Any]]:
    """Станция → статус на последний срез, с какого дня он держится и какие
    разъёмы неисправны две книги подряд (только у станции на связи)."""
    if not days:
        return {}
    last = days[-1]
    prev = days[-2] if len(days) > 1 else None
    out: dict[str, dict[str, Any]] = {}
    for lid, s in series.items():
        cur = s.get(last)
        if cur is None:
            continue
        first = last
        for d in reversed(days):
            if d not in s or s[d][0] != cur[0]:
                break
            first = d
        faults = []
        before = s.get(prev) if prev else None
        if cur[0] == "working" and before and before[0] == "working":
            for no, st in sorted(cur[1].items(), key=lambda x: str(x[0]).zfill(3)):
                if st not in РАЗЪЁМ_НЕИСПРАВЕН or before[1].get(no) not in РАЗЪЁМ_НЕИСПРАВЕН:
                    continue
                since = prev
                for d in reversed(days[:-1]):
                    if d not in s or s[d][1].get(no) not in РАЗЪЁМ_НЕИСПРАВЕН:
                        break
                    since = d
                faults.append({"no": str(no), "status": st, "since": since.isoformat(),
                               "openStart": since == days[0]})
        out[lid] = {"status": cur[0], "since": first.isoformat(),
                    "openStart": first == days[0], "faults": faults}
    return out


async def status_now(db: AsyncSession, company_id, as_of: date | None = None
                     ) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """(день среза, {станция: состояние}) на последнюю книгу не позже `as_of`."""
    rows = (await db.execute(text("""
        with top as (select max(day) as d from station_status_days
                     where company_id = :cid and (CAST(:as_of AS date) is null or day <= CAST(:as_of AS date)))
        select location_id, day, operational_status, connectors from station_status_days, top
        where company_id = :cid and day <= top.d and day > top.d - make_interval(days => :win)
    """), {"cid": str(company_id), "as_of": as_of, "win": ОКНО_ДОСТУПНОСТИ})).all()
    if not rows:
        return None, {}
    days = sorted({r.day for r in rows})
    if days[-1] < (as_of or date.today()) - timedelta(days=СВЕЖЕСТЬ_ДНЕЙ):
        return None, {}
    series: dict[str, dict[date, tuple[str, dict]]] = {}
    for r in rows:
        series.setdefault(r.location_id, {})[r.day] = (r.operational_status, r.connectors or {})
    return days[-1].isoformat(), status_now_from(days, series)
