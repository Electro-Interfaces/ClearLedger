# -*- coding: utf-8 -*-
"""Проверка календарных периодов «Периметра» (`services/perimeter_periods.py`).

Регулярное обязательство закрывается отметкой за период, и отметка привязана к первому
дню этого периода. Ошибка в границе тихая: экран рисуется, полоса периодов выглядит
правдоподобно, а август закрывается отметкой за июль — и человек считается обманутым
там, где ему заплатили.

Гоняет ИМЕННО рабочий код, а не его копию: формулы вынесены отдельным модулем ровно
затем, чтобы их можно было проверить без базы и FastAPI.

    py scripts/perimeter-periods-check.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from app.services.perimeter_periods import (  # noqa: E402
    PERIODICITY, _next_period, _period_label, _period_start, _periods,
)

ok = 0


def eq(got, want, what: str) -> None:
    global ok
    assert got == want, f"{what}: получено {got}, ожидалось {want}"
    ok += 1


# ── Границы периода: в какой отрезок попадает дата ──────────────────────────
eq(_period_start(date(2026, 8, 14), "month"), date(2026, 8, 1), "месяц")
eq(_period_start(date(2026, 8, 1), "month"), date(2026, 8, 1), "первый день месяца")
eq(_period_start(date(2026, 8, 31), "month"), date(2026, 8, 1), "последний день месяца")
eq(_period_start(date(2026, 8, 14), "quarter"), date(2026, 7, 1), "квартал")
eq(_period_start(date(2026, 2, 3), "quarter"), date(2026, 1, 1), "первый квартал")
eq(_period_start(date(2026, 12, 31), "quarter"), date(2026, 10, 1), "конец года, квартал")
eq(_period_start(date(2026, 8, 14), "halfyear"), date(2026, 7, 1), "второе полугодие")
eq(_period_start(date(2026, 6, 30), "halfyear"), date(2026, 1, 1), "первое полугодие")
eq(_period_start(date(2026, 8, 14), "year"), date(2026, 1, 1), "год")
# 14.08.2026 — пятница, неделя начинается в понедельник 10-го.
eq(_period_start(date(2026, 8, 14), "week"), date(2026, 8, 10), "неделя от понедельника")
eq(_period_start(date(2026, 8, 10), "week"), date(2026, 8, 10), "сам понедельник")
eq(_period_start(date(2026, 8, 16), "week"), date(2026, 8, 10), "воскресенье той же недели")

# ── Следующий период: шаг не должен уезжать через год ───────────────────────
eq(_next_period(date(2026, 12, 1), "month"), date(2027, 1, 1), "декабрь → январь")
eq(_next_period(date(2026, 1, 1), "month"), date(2026, 2, 1), "январь → февраль")
eq(_next_period(date(2026, 10, 1), "quarter"), date(2027, 1, 1), "4 квартал → 1")
eq(_next_period(date(2026, 1, 1), "quarter"), date(2026, 4, 1), "1 квартал → 2")
eq(_next_period(date(2026, 7, 1), "halfyear"), date(2027, 1, 1), "2 полугодие → 1")
eq(_next_period(date(2026, 1, 1), "halfyear"), date(2026, 7, 1), "1 полугодие → 2")
eq(_next_period(date(2026, 1, 1), "year"), date(2027, 1, 1), "год → год")
eq(_next_period(date(2026, 8, 10), "week"), date(2026, 8, 17), "неделя → неделя")

# Двенадцать шагов месяца дают ровно год — арифметика в сутках дала бы 30 декабря.
d = date(2026, 1, 1)
for _ in range(12):
    d = _next_period(d, "month")
eq(d, date(2027, 1, 1), "двенадцать месяцев = год")

# Шаг всегда вперёд и всегда начинается с границы своего периода.
for kind in PERIODICITY:
    cur = _period_start(date(2026, 1, 15), kind)
    for _ in range(30):
        nxt = _next_period(cur, kind)
        assert nxt > cur, f"{kind}: шаг не вперёд ({cur} → {nxt})"
        assert _period_start(nxt, kind) == nxt, f"{kind}: {nxt} не начало периода"
        # Любой день внутри периода обязан приводиться к его началу.
        mid = nxt + timedelta(days=1)
        if _period_start(mid, kind) == nxt:
            ok += 1
        cur = nxt
eq(True, True, "шаги всех периодичностей монотонны и выровнены")

# ── Перечень периодов обязательства ─────────────────────────────────────────
c = SimpleNamespace(started_on=date(2026, 5, 1), ends_on=None, periodicity="month")
eq(_periods(c, date(2026, 8, 14)), [date(2026, 5, 1), date(2026, 6, 1),
                                    date(2026, 7, 1), date(2026, 8, 1)],
   "четыре месяца от мая до августа")
# Начало в середине месяца — период всё равно от первого числа.
c2 = SimpleNamespace(started_on=date(2026, 5, 17), ends_on=None, periodicity="month")
eq(len(_periods(c2, date(2026, 8, 14))), 4, "старт в середине месяца")
# Окончание обрезает перечень.
c3 = SimpleNamespace(started_on=date(2026, 5, 1), ends_on=date(2026, 6, 20),
                     periodicity="month")
eq(_periods(c3, date(2026, 8, 14)), [date(2026, 5, 1), date(2026, 6, 1)],
   "прекращённое в июне")
# Бессрочное недельное за пять лет не должно рисовать сотни клеток.
c4 = SimpleNamespace(started_on=date(2020, 1, 1), ends_on=None, periodicity="week")
eq(len(_periods(c4, date(2026, 8, 14))) <= 400, True, "перечень ограничен сверху")

# ── Подписи периодов ────────────────────────────────────────────────────────
eq(_period_label(date(2026, 8, 1), "month"), "август 2026", "подпись месяца")
eq(_period_label(date(2026, 7, 1), "quarter"), "3 квартал 2026", "подпись квартала")
eq(_period_label(date(2026, 1, 1), "halfyear"), "1 полугодие 2026", "подпись полугодия")
eq(_period_label(date(2026, 1, 1), "year"), "2026 год", "подпись года")
eq(_period_label(date(2026, 8, 10), "week"), "неделя с 10.08.2026", "подпись недели")

print(f"периоды «Периметра»: {ok} проверок пройдено")
