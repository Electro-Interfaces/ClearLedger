"""Календарные периоды регулярных обязательств «Периметра».

Вынесено из роутера, чтобы арифметику можно было проверить без базы и FastAPI:
`scripts/perimeter-periods-check.py` гоняет ИМЕННО этот код, а не его копию. Дублировать
формулы в проверке нельзя — разойдутся молча, и полоса периодов начнёт врать.

Шаг календарный, а не «каждые N дней»: «каждый месяц» это месяц. Арифметика в сутках к
декабрю уводит период почти на неделю, и отметки перестают попадать в свой месяц.
"""
from __future__ import annotations

from datetime import date, timedelta

PERIODICITY: dict[str, str] = {
    "week": "Каждую неделю",
    "month": "Каждый месяц",
    "quarter": "Каждый квартал",
    "halfyear": "Раз в полгода",
    "year": "Раз в год",
}

MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль",
          "август", "сентябрь", "октябрь", "ноябрь", "декабрь")


def _period_start(day: date, periodicity: str) -> date:
    """Первый день периода, в который попадает дата.

    Календарный шаг, а не арифметика в днях: «каждый месяц» это месяц, а не 30 суток,
    иначе к декабрю период уезжает на неделю и отметки перестают попадать в свой месяц.
    """
    if periodicity == "week":
        return day - timedelta(days=day.weekday())
    if periodicity == "month":
        return day.replace(day=1)
    if periodicity == "quarter":
        return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
    if periodicity == "halfyear":
        return date(day.year, 1 if day.month <= 6 else 7, 1)
    return date(day.year, 1, 1)


def _next_period(start: date, periodicity: str) -> date:
    if periodicity == "week":
        return start + timedelta(days=7)
    if periodicity == "month":
        return date(start.year + start.month // 12, start.month % 12 + 1, 1)
    if periodicity == "quarter":
        m = start.month + 3
        return date(start.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
    if periodicity == "halfyear":
        return date(start.year + 1, 1, 1) if start.month == 7 else date(start.year, 7, 1)
    return date(start.year + 1, 1, 1)


def _period_label(start: date, periodicity: str) -> str:
    months = MONTHS
    if periodicity == "week":
        return f"неделя с {start.strftime('%d.%m.%Y')}"
    if periodicity == "month":
        return f"{months[start.month - 1]} {start.year}"
    if periodicity == "quarter":
        return f"{(start.month - 1) // 3 + 1} квартал {start.year}"
    if periodicity == "halfyear":
        return f"{'1' if start.month == 1 else '2'} полугодие {start.year}"
    return f"{start.year} год"


def _periods(c, until: date) -> list[date]:
    """Все периоды обязательства от начала до указанной даты.

    Ограничение сверху намеренное: у бессрочного обязательства с недельным шагом за
    пять лет накопится 260 периодов, и показывать их целиком незачем.
    """
    out: list[date] = []
    cur = _period_start(c.started_on, c.periodicity)
    end = min(until, c.ends_on) if c.ends_on else until
    while cur <= end and len(out) < 400:
        out.append(cur)
        cur = _next_period(cur, c.periodicity)
    return out


