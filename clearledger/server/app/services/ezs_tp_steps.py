"""Ход техприсоединения по шагам — порядок энергетика (блок-схема от 07.10.2026).

Статус присоединения отвечал «где мы», но не «что дальше и к какому числу»:
между «заявка подана» и «исполнено» у сетевой семь шагов со своими сроками по
Правилам ТП (ПП РФ №861), и просрочка любого из них была видна только тому, кто
помнил её сам.

Это НЕ маршрут и не движок процессов: шаг — факт с датой, закрывается человеком.
Ход проекта по-прежнему ведёт служба процессов (`docs/PROCESS.md`).

Способ присоединения определяет набор шагов:
  • `direct`   — прямое подключение к сетевой организации;
  • `indirect` — опосредованное, через сети арендодателя: добавляется соглашение;
  • `landlord` — электроэнергия оплачивается арендодателю, присоединения нет.

Три шага живут в уже существующих графах (`field`): дата заявки, договора и
исполнения вводились и раньше, второе место правды для них не заводим.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

METHODS: list[dict[str, str]] = [
    {"key": "direct", "label": "Прямое подключение к сетевой организации"},
    {"key": "indirect", "label": "Опосредованное — через сети арендодателя"},
    {"key": "landlord", "label": "Оплата электроэнергии арендодателю — присоединение не требуется"},
]
METHOD_LABELS = {m["key"]: m["label"] for m in METHODS}

# `no` — номер блока на схеме энергетика: по нему сверяются с бумагой.
# `after` + `norm` — срок по Правилам: дней от даты шага `after`.
# `status` — в какой статус присоединения переводит закрытый шаг.
# `branch: supply` — договор электроснабжения: идёт своей веткой, статус не двигает.
STEPS: list[dict[str, Any]] = [
    {"key": "indirect_agreement", "no": "2.1", "only": "indirect",
     "label": "Получено соглашение об опосредованном присоединении (перераспределении мощности)"},
    {"key": "docs_ready", "no": "2.2", "label": "Комплект документов для заявки собран"},
    {"key": "applied", "no": "3.2", "field": "application_date", "status": "applied",
     "label": "Заявка на ТП направлена в сетевую организацию"},
    {"key": "accepted", "no": "3.3", "after": "applied", "norm": 3, "status": "applied",
     "label": "Заявка принята сетевой: замечаний нет или они сняты",
     "hint": "О недостающих документах сетевая сообщает за 3 дня; на досылку — 20 дней."},
    {"key": "contract", "no": "4.2", "field": "contract_date", "after": "accepted", "norm": 30,
     "status": "contract", "label": "Получены договор ТП и технические условия"},
    {"key": "works_done", "no": "5.2", "status": "in_progress",
     "label": "ТУ выполнены — полностью или этап"},
    {"key": "notified", "no": "6.2", "status": "in_progress",
     "label": "Сетевая уведомлена о выполнении ТУ"},
    {"key": "checked", "no": "7.2", "status": "in_progress",
     "label": "Проверка сетевой пройдена, напряжение подано"},
    {"key": "avtu", "no": "8.2", "status": "in_progress",
     "label": "Получены АВТУ и акт допуска узлов учёта"},
    {"key": "atp", "no": "9.2", "field": "done_date", "after": "checked", "norm": 5,
     "status": "done", "label": "Получен акт о техприсоединении, договор ТП закрыт"},
    {"key": "supply_applied", "no": "8.3", "branch": "supply",
     "label": "Заявка на договор электроснабжения направлена в сбытовую организацию"},
    {"key": "supply_contract", "no": "9.3", "branch": "supply",
     "label": "Договор электроснабжения заключён"},
]
STEP_BY_KEY = {s["key"]: s for s in STEPS}


def steps_for(method: str | None) -> list[dict[str, Any]]:
    if method not in ("direct", "indirect"):
        return []
    return [s for s in STEPS if s.get("only") in (None, method)]


def step_date(tc: Any, step: dict[str, Any]) -> str | None:
    if step.get("field"):
        return getattr(tc, step["field"], None) or None
    return ((getattr(tc, "steps", None) or {}).get(step["key"]) or {}).get("date") or None


def _iso(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def steps_out(tc: Any, today: date | None = None) -> list[dict[str, Any]]:
    """Шаги выбранного способа: дата факта, срок по Правилам и просрочка."""
    today = today or date.today()
    out = []
    for s in steps_for(getattr(tc, "method", None)):
        done = step_date(tc, s)
        base = _iso(step_date(tc, STEP_BY_KEY[s["after"]])) if s.get("after") else None
        planned = (base + timedelta(days=s["norm"])).isoformat() if base else None
        out.append({
            "key": s["key"], "no": s["no"], "label": s["label"], "hint": s.get("hint"),
            "branch": s.get("branch", "main"), "date": done, "plannedDate": planned,
            "normDays": s.get("norm"),
            "overdue": bool(planned and not done and planned < today.isoformat()),
        })
    return out


def derived_status(tc: Any) -> str | None:
    """Статус по самому дальнему закрытому шагу основной ветки; None — шагов нет."""
    status = None
    for s in steps_for(getattr(tc, "method", None)):
        if s.get("status") and step_date(tc, s):
            status = s["status"]
    return status
