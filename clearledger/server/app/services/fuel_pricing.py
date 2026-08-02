"""Ценообразование топливной сети: цена как решение, а не как атрибут продажи.

Общие разрезы (`fuel_sales_analytics`) отвечают «по какой цене продали». Здесь —
«кто, когда и на сколько цену ДВИНУЛ, и что из этого вышло»:

  • changes  — журнал событий смены цены (было → стало, шаг, сколько держалась
               прежняя, объём до/после) + волны по сети;
  • calendar — матрица станция × день по одному виду топлива: видно, как волна
               прокатывается по сети и кто отстаёт;
  • spread   — разброс цен по сети на конец периода: размах, ранг станции,
               возраст текущей цены.

Все три выводятся из ОДНОГО суточного среза (`_daily`): станция × топливо × день →
доминирующая цена дня + объём. Отдельных запросов на событие нет — 14 станций × 6
топлив × год это ~26 тыс. строк, свернуть их в Python дешевле, чем гонять оконные
функции тремя разными способами.

Почему «доминирующая цена дня», а не средняя: цена стеллы — ступенька, а не
среднее. В день перехода в базе стоят обе цены; среднее даёт третье число,
которого на стелле не было ни минуты. Берём цену с наибольшим объёмом, а факт
перехода внутри дня помечаем флагом `varies`.

Окна: слева ряд берётся с запасом `_LOOKBACK_DAYS` (иначе у события в первый день
периода нет ни прежней цены, ни объёма «до»), справа — на `_WINDOW_DAYS` (окно
реакции спроса). События отдаются только внутри запрошенного периода.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelStation, FuelTransaction as T
from app.services.analytics_cache import cached_report
from app.utils import msk_day_end, msk_day_start

_LOOKBACK_DAYS = 30   # запас слева: прежняя цена и объём «до» для события в первый день
_WINDOW_DAYS = 7      # окно реакции спроса: среднесуточный объём до/после
_WAVE_GAP_DAYS = 3    # события одного топлива в пределах трёх суток — одна волна сети
_EPS = 0.005          # цены хранятся с тремя знаками; ниже полкопейки — не изменение
_TRADING_DAY_SHARE = 0.02  # день с объёмом < 2% медианы — не торговый (техпролив, простой)
_TRADING_DAY_MIN = 5.0     # л: и не меньше пяти литров в абсолюте
_JUMP_PCT = 12.0      # шаг больше 12% — станция стояла и пропустила ступени, не одно решение
_RESPONSE_MIN_BASE = 100.0   # л/сут: ниже этой базы процент реакции не считается
_WAVE_STEP_TOL = 0.6  # ₽/л: в одну волну идут события с близким шагом


@dataclass(slots=True)
class Day:
    """Сутки одной пары станция × топливо."""
    day: date
    price: float
    liters: float
    amount: float
    fills: int
    varies: bool          # цена менялась внутри дня
    price_low: float
    price_high: float


def trading_days(days: list[Day], share: float = _TRADING_DAY_SHARE) -> list[Day]:
    """Только торговые сутки: где объём хотя бы `share` от медианы по этой паре.

    В ряду попадаются дни-огрызки — 1,3 литра за сутки: техпролив, авария на ТРК,
    остановленная колонка. Цена в такой день формально есть, и без отсечения
    происходит двойной вред: огрызок с прежней ценой даёт лишнее событие, а попав в
    окно реакции — обнуляет её («объём упал на 99%», хотя станция просто не торговала).

    Порог намеренно низкий (проценты от медианы, не десятки). При доле в 10% ряд с
    большим разбросом — позиция вышла в продажу и объём вырос на порядок — терял
    нижнюю половину дней ЦЕЛИКОМ, а вместе с ними и саму смену цены. Отсекать надо
    мусор, а не малые продажи: слабый день торговли — это факт, а не сбой.
    """
    if len(days) < 3:
        return days
    med = median([d.liters for d in days]) or 0.0
    floor = max(_TRADING_DAY_MIN, med * share)
    kept = [d for d in days if d.liters >= floor]
    return kept if len(kept) >= 2 else days


def price_events(days: list[Day], window: int = _WINDOW_DAYS) -> list[dict[str, Any]]:
    """Суточный ряд одной пары станция × топливо → события смены цены.

    Чистая логика без БД: сравнивается цена дня с ценой предыдущего ТОРГОВОГО дня.
    Дни простоя в ряду отсутствуют и разрыв не создают — иначе каждая пауза читалась
    бы как смена цены.

    `held_days` — сколько календарных дней держалась прежняя цена (от прошлого
    события, а не от прошлого дня с продажами). `liters_before/after` — МЕДИАННЫЙ
    суточный объём за `window` дней до дня события и с дня события включительно;
    медиана, а не среднее, потому что один аномальный день (после праздника, слив
    в бак корпоративного клиента) иначе задаёт всю реакцию. День перехода отнесён к
    «после»: новая цена действует уже в нём.

    `jump` — шаг больше `_JUMP_PCT`: между наблюдениями станция стояла и ступени
    прошли мимо. Такой шаг реален, но это не одно решение о цене, и в статистику
    среднего шага он мешаться не должен.
    """
    events: list[dict[str, Any]] = []
    row = trading_days(days)
    if len(row) < 2:
        return events
    # База реакции должна быть содержательной: на позиции, где до смены цены брали
    # 28 литров в сутки, любая заправка даёт «+3600% объёма». Это не реакция на цену,
    # а появление позиции в продаже — процент по такой базе не считаем вовсе.
    row_med = median([d.liters for d in row])
    min_base = max(_RESPONSE_MIN_BASE, row_med * 0.2)
    since = row[0].day           # с какого дня стоит текущая цена
    for i in range(1, len(row)):
        prev, cur = row[i - 1], row[i]
        if abs(cur.price - prev.price) <= _EPS:
            continue
        before = [d.liters for d in row[:i] if 0 < (cur.day - d.day).days <= window]
        after = [d.liters for d in row[i:] if 0 <= (d.day - cur.day).days < window]
        lit_b = median(before) if before else None
        lit_a = median(after) if after else None
        step_pct = (cur.price - prev.price) / prev.price * 100 if prev.price else 0.0
        events.append({
            "day": cur.day,
            "was": round(prev.price, 2),
            "became": round(cur.price, 2),
            "step": round(cur.price - prev.price, 2),
            "step_pct": round(step_pct, 2),
            "held_days": (cur.day - since).days,
            "liters_before": round(lit_b, 1) if lit_b is not None else None,
            "liters_after": round(lit_a, 1) if lit_a is not None else None,
            "response_pct": (round((lit_a - lit_b) / lit_b * 100, 1)
                             if lit_b is not None and lit_a is not None and lit_b >= min_base else None),
            # Окно справа неполное — реакцию ещё не видно, а не «реакции нет».
            "window_full": bool(after) and (row[-1].day - cur.day).days >= window - 1,
            "jump": abs(step_pct) > _JUMP_PCT,
        })
        since = cur.day
    return events


def group_waves(events: list[dict[str, Any]], gap_days: int = _WAVE_GAP_DAYS,
                step_tol: float = _WAVE_STEP_TOL) -> list[dict[str, Any]]:
    """События одного вида топлива с БЛИЗКИМ шагом, идущие подряд, — одна волна
    пересмотра цены по сети.

    Сеть двигает цену не одномоментно: решение принимается одно, а до станций
    доезжает за двое-трое суток. Без склейки журнал показывает четырнадцать
    «независимых» событий вместо одного решения, и вопрос «кто отстал» не задать.

    Близость шага — обязательное условие, а не украшение. При склейке «любой рост
    подряд» две недели ежедневного роста по разным станциям слипались в одну волну на
    18 дней с шагом от 1,5 до 25,9 ₽/л — то есть в отчёт попадало «одно решение»,
    которого не было. Догоняющие скачки (`jump`: станция стояла и пропустила
    ступени) в волны не входят вовсе — они и есть источник ложных склеек.
    """
    waves: list[dict[str, Any]] = []
    by_fuel: dict[int, list[dict[str, Any]]] = {}
    for e in events:
        if e.get("jump"):
            continue
        by_fuel.setdefault(e["fuel_code"], []).append(e)
    for fuel_code, evs in by_fuel.items():
        evs = sorted(evs, key=lambda x: (x["day"], x["station_code"]))
        cur: list[dict[str, Any]] = []
        for e in evs:
            fits = cur and (
                (e["step"] > 0) == (cur[-1]["step"] > 0)
                and (e["day"] - cur[-1]["day"]).days <= gap_days
                and abs(e["step"] - median([x["step"] for x in cur])) <= step_tol
            )
            if cur and not fits:
                waves.append(_wave(fuel_code, cur))
                cur = []
            cur.append(e)
        if cur:
            waves.append(_wave(fuel_code, cur))
    waves.sort(key=lambda w: w["to"], reverse=True)
    return waves


def _wave(fuel_code: int, evs: list[dict[str, Any]]) -> dict[str, Any]:
    steps = [e["step"] for e in evs]
    first_day = evs[0]["day"]
    return {
        "fuel_code": fuel_code,
        "fuel_name": evs[0]["fuel_name"],
        "from": evs[0]["day"].isoformat(),
        "to": evs[-1]["day"].isoformat(),
        "days": (evs[-1]["day"] - first_day).days + 1,
        "stations": len({e["station_code"] for e in evs}),
        "step_avg": round(sum(steps) / len(steps), 2),
        "step_min": round(min(steps), 2),
        "step_max": round(max(steps), 2),
        "first": [e["station"] for e in evs if e["day"] == first_day][:3],
        "last": [e["station"] for e in evs if e["day"] == evs[-1]["day"]][:3],
        "events": len(evs),
    }


class FuelPricing:
    """Проекции ценовых решений сети. Кешируются версионным кешем компании."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._fuel_names: dict[int, str] = {}

    async def _station_names(self, company_id) -> dict[int, str]:
        return {int(s.code): s.name for s in (await self.db.execute(
            select(FuelStation).where(FuelStation.company_id == company_id)
        )).scalars().all()}

    async def _daily(self, company_id, date_from: date, date_to: date,
                     fuel_codes: tuple[int, ...] = (),
                     station_codes: tuple[int, ...] = ()) -> dict[tuple[int, int], list[Day]]:
        """Суточный срез станция × топливо × день → доминирующая цена и объём.

        Один запрос группирует по (станция, топливо, день, цена) — цена в ключе, чтобы
        отличить сутки перехода от суток с одной ценой; свёртка по дню идёт в Python.
        """
        # Окно берём московскими сутками — как весь топливный контур, иначе край
        # окна режется по UTC и цена последнего дня считается по неполным суткам.
        lo = msk_day_start(date_from - timedelta(days=_LOOKBACK_DAYS))
        hi = msk_day_end(date_to + timedelta(days=_WINDOW_DAYS))
        conds = [T.company_id == company_id, T.dt >= lo, T.dt <= hi,
                 T.price.is_not(None), T.price > 0]
        if fuel_codes:
            conds.append(T.fuel_code.in_(fuel_codes))
        if station_codes:
            conds.append(T.station_code.in_(station_codes))
        day_col = func.date(T.dt).label("day")
        rows = (await self.db.execute(
            select(
                T.station_code, T.fuel_code, day_col, T.price,
                func.max(T.fuel_name).label("fuel_name"),
                func.count().label("fills"),
                func.coalesce(func.sum(T.liters), 0).label("liters"),
                func.coalesce(func.sum(T.amount), 0).label("amount"),
            ).where(*conds).group_by(T.station_code, T.fuel_code, day_col, T.price)
        )).all()

        # (станция, топливо, день) → варианты цены за день
        buckets: dict[tuple[int, int, date], list] = {}
        self._fuel_names: dict[int, str] = {}
        for r in rows:
            if r.station_code is None or r.fuel_code is None:
                continue
            key = (int(r.station_code), int(r.fuel_code), r.day)
            buckets.setdefault(key, []).append(r)
            self._fuel_names.setdefault(int(r.fuel_code), r.fuel_name or f"Топливо {r.fuel_code}")


        series: dict[tuple[int, int], list[Day]] = {}
        for (st, fu, day), variants in buckets.items():
            liters = sum(float(v.liters) for v in variants)
            top = max(variants, key=lambda v: float(v.liters))
            prices = [float(v.price) for v in variants]
            series.setdefault((st, fu), []).append(Day(
                day=day,
                price=float(top.price),
                liters=liters,
                amount=sum(float(v.amount) for v in variants),
                fills=sum(int(v.fills) for v in variants),
                varies=(max(prices) - min(prices)) > _EPS,
                price_low=min(prices),
                price_high=max(prices),
            ))
        for days in series.values():
            days.sort(key=lambda d: d.day)
        return series

    # ─── Журнал изменений ───────────────────────────────────────────────

    @cached_report("fuel:price_changes")
    async def changes(self, company_id, date_from: date, date_to: date,
                      fuel_codes: tuple[int, ...] = ()) -> dict[str, Any]:
        """События смены цены за период + волны сети + сводка по шагам."""
        series = await self._daily(company_id, date_from, date_to, fuel_codes)
        names = await self._station_names(company_id)

        events: list[dict[str, Any]] = []
        for (st, fu), days in series.items():
            for e in price_events(days):
                if not (date_from <= e["day"] <= date_to):
                    continue
                events.append({
                    **e,
                    "station_code": st,
                    "station": names.get(st) or f"АЗС {st}",
                    "fuel_code": fu,
                    "fuel_name": self._fuel_names.get(fu, f"Топливо {fu}"),
                })
        waves = group_waves(events)
        events.sort(key=lambda e: (e["day"], e["station_code"]), reverse=True)

        # Догоняющие скачки в статистику шага не входят: это пропущенные ступени, а не
        # решение о цене — иначе «средний шаг» уходит втрое выше любого реального.
        plain = [e for e in events if not e["jump"]]
        ups = [e for e in plain if e["step"] > 0]
        downs = [e for e in plain if e["step"] < 0]
        responded = [e for e in plain if e["response_pct"] is not None and e["window_full"]]
        held = [e["held_days"] for e in plain if e["held_days"] > 0]
        totals = {
            "events": len(events),
            "jumps": len(events) - len(plain),
            "ups": len(ups),
            "downs": len(downs),
            "step_up_avg": round(median([e["step"] for e in ups]), 2) if ups else 0.0,
            "step_down_avg": round(median([e["step"] for e in downs]), 2) if downs else 0.0,
            "held_median": round(median(held), 1) if held else 0.0,
            "waves": len(waves),
            # Медиана, а не среднее: события с малым объёмом «до» дают проценты в тысячах
            # и среднее становится бессмысленным. Только с полным окном справа.
            "response_median": (round(median([e["response_pct"] for e in responded]), 1)
                                if responded else None),
            "responded": len(responded),
        }
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "window_days": _WINDOW_DAYS,
            "events": [{**e, "day": e["day"].isoformat()} for e in events],
            "waves": waves,
            "totals": totals,
        }

    # ─── Календарь волн ─────────────────────────────────────────────────

    @cached_report("fuel:price_calendar")
    async def calendar(self, company_id, date_from: date, date_to: date,
                       fuel_code: int) -> dict[str, Any]:
        """Матрица станция × день по одному виду топлива: цена дня и факт перехода.

        Один вид топлива, а не все сразу: у разных топлив разные уровни цены, и в
        общей матрице соседние строки нельзя было бы сравнивать взглядом.
        """
        series = await self._daily(company_id, date_from, date_to, (fuel_code,))
        names = await self._station_names(company_id)
        days_all = sorted({d.day for days in series.values() for d in days
                           if date_from <= d.day <= date_to})
        rows: list[dict[str, Any]] = []
        for (st, _fu), days in series.items():
            in_period = [d for d in days if date_from <= d.day <= date_to]
            if not in_period:
                continue
            changed = {e["day"] for e in price_events(days)}
            rows.append({
                "station_code": st,
                "station": names.get(st) or f"АЗС {st}",
                "liters": round(sum(d.liters for d in in_period), 1),
                "cells": [{
                    "day": d.day.isoformat(),
                    "price": round(d.price, 2),
                    "liters": round(d.liters, 1),
                    "changed": d.day in changed,
                    "varies": d.varies,
                } for d in in_period],
            })
        rows.sort(key=lambda r: -r["liters"])
        prices = sorted(c["price"] for r in rows for c in r["cells"])
        # Шкала цвета — по 5-му и 95-му процентилю, а не по крайним значениям: за
        # полгода цена вырастает на треть, и при шкале «мин…макс» весь недавний период
        # схлопывается в один оттенок, где как раз и надо различать станции между собой.
        scale = (prices[int(len(prices) * 0.05)], prices[int(len(prices) * 0.95) - 1]) if len(prices) > 20 else (
            (prices[0], prices[-1]) if prices else (None, None))
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "fuel_code": fuel_code,
            "fuel_name": self._fuel_names.get(fuel_code, f"Топливо {fuel_code}"),
            "days": [d.isoformat() for d in days_all],
            "rows": rows,
            "scale_low": scale[0],
            "scale_high": scale[1],
            "price_min": round(min(prices), 2) if prices else None,
            "price_max": round(max(prices), 2) if prices else None,
        }

    # ─── Разброс по сети ────────────────────────────────────────────────

    @cached_report("fuel:price_spread")
    async def spread(self, company_id, date_from: date, date_to: date,
                     fuel_codes: tuple[int, ...] = ()) -> dict[str, Any]:
        """Цена каждой станции на конец периода: размах по сети, ранг, возраст цены.

        «Возраст» — сколько дней стоит текущая цена. Он и отвечает на вопрос, кого
        забыли пересмотреть: станция с ценой месячной давности при недельном шаге
        сети торгует по чужому решению.
        """
        series = await self._daily(company_id, date_from, date_to, fuel_codes)
        names = await self._station_names(company_id)
        edge = date_to

        lines: list[dict[str, Any]] = []
        for (st, fu), days in series.items():
            actual = [d for d in days if d.day <= edge]
            if not actual:
                continue
            last = actual[-1]
            evs = price_events(actual)
            since = evs[-1]["day"] if evs else actual[0].day
            in_period = [d for d in days if date_from <= d.day <= date_to]
            lines.append({
                "station_code": st,
                "station": names.get(st) or f"АЗС {st}",
                "fuel_code": fu,
                "fuel_name": self._fuel_names.get(fu, f"Топливо {fu}"),
                "price": round(last.price, 2),
                "priced_on": last.day.isoformat(),
                "age_days": (edge - since).days,
                "changes": len([e for e in evs if date_from <= e["day"] <= date_to]),
                "liters": round(sum(d.liters for d in in_period), 1),
            })

        by_fuel: dict[int, list[dict[str, Any]]] = {}
        for ln in lines:
            by_fuel.setdefault(ln["fuel_code"], []).append(ln)
        fuels: list[dict[str, Any]] = []
        for fu, group in by_fuel.items():
            prices = sorted(ln["price"] for ln in group)
            med = median(prices)
            lit = sum(ln["liters"] for ln in group)
            wavg = (sum(ln["price"] * ln["liters"] for ln in group) / lit) if lit else med
            for rank, ln in enumerate(sorted(group, key=lambda x: -x["price"]), start=1):
                ln["delta_median"] = round(ln["price"] - med, 2)
                ln["rank"] = rank
            fuels.append({
                "fuel_code": fu,
                "fuel_name": self._fuel_names.get(fu, f"Топливо {fu}"),
                "stations": len(group),
                "price_min": prices[0],
                "price_max": prices[-1],
                "price_median": round(med, 2),
                "price_wavg": round(wavg, 2),
                "spread": round(prices[-1] - prices[0], 2),
                "spread_pct": round((prices[-1] - prices[0]) / prices[0] * 100, 2) if prices[0] else 0.0,
                "age_max": max(ln["age_days"] for ln in group),
                "liters": round(lit, 1),
            })
        fuels.sort(key=lambda f: -f["liters"])
        lines.sort(key=lambda ln: (ln["fuel_name"], -ln["price"]))
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "as_of": edge.isoformat(),
            "fuels": fuels,
            "lines": lines,
        }
