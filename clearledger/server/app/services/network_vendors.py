"""Сеть глазами производителя: чьё железо держит нагрузку, а чьё стоит.

Инженер смотрит на сеть не только станциями, но и марками: если у одного вендора
из четырнадцати станций работают две, дело не в конкретной площадке. Разрез
отвечает на вопрос закупки и сервиса — что брать дальше и к кому ехать с
рекламацией.

Три меры рядом, и каждая о своём:

- **живость** — сколько станций марки на связи и сколько реально отпускали
  энергию за последние сутки. «Активная» в выгрузке и «заряжает» — разные вещи;
- **надёжность** — доля приездов, кончившихся ничем, и попытки на приезд. Это
  качество железа глазами клиента, а не паспортная характеристика;
- **вес** — сколько приездов и энергии приходится на марку. Марка с двумя
  станциями и марка со ста тридцатью требуют разного разговора при одинаковом
  проценте отказов.

Мощность и модели берём из паспорта: у одного вендора это может быть и медленная
стенка, и быстрая колонка, и смешивать их надёжность нельзя — поэтому список
моделей показан рядом.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession, Region, ServiceLocation
from app.services.ops_monitor_context import monitor_context, region_matches, visit_summary, decimal_round
from app.services.station_scope import в_сети, обслуживаем

ОКНО_ДНЕЙ = 90
СВЕЖО_ДНЕЙ = 2
НЕДЕЛЯ = 7

# Порог разговора о марке: каждый пятый приезд впустую. Тот же, что в
# «Надёжности», — иначе два экрана назовут плохими разные станции.
ПОРОГ_ОТКАЗОВ = 20.0

БЕЗ_МАРКИ = "марка не указана"


def _проц(часть: int, целое: int) -> float:
    return round(100.0 * часть / целое, 1) if целое else 0.0


async def network_vendors(
    db: AsyncSession, company_id: uuid.UUID, *,
    days: int = ОКНО_ДНЕЙ,
    region: str | None = None,
    vendor: str | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Сводка по производителям; с `vendor` — ещё и станции этой марки.

    `as_of` сдвигает конец окна на выбранный день: «как марка держалась весной»
    — то же окно, только закончившееся тогда. Без даты считаем от границы данных.
    """
    граница = (await db.execute(
        select(func.max(ChargeSession.started_at))
        .where(ChargeSession.company_id == company_id))).scalar()
    сейчас, контекст = monitor_context(граница, as_of)
    с_даты = сейчас - timedelta(days=days)

    сорвана = ChargeSession.result.ilike("%error%") | ChargeSession.result.ilike("%ошиб%")
    работа = {
        str(loc): {
            "визитов": int(визитов or 0),
            "визитов_ок": int(визитов_ок or 0),
            "попыток": int(попыток or 0),
            "энергия": энергия or Decimal(0),
            "деньги": float(деньги or 0),
            "срывов": int(срывов or 0),
        }
        for loc, визитов, визитов_ок, попыток, энергия, деньги, срывов in (await db.execute(
            select(ChargeSession.location_id,
                   func.count(func.distinct(ChargeSession.visit_key)),
                   func.count(func.distinct(case(
                       (ChargeSession.visit_charged.is_(True), ChargeSession.visit_key)))),
                   func.count(),
                   func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
                   func.coalesce(func.sum(func.coalesce(
                       ChargeSession.client_amount, ChargeSession.amount)), 0),
                   func.sum(case((сорвана, 1), else_=0)))
            .where(ChargeSession.company_id == company_id,
                   ChargeSession.location_id.is_not(None),
                   ChargeSession.started_at >= с_даты,
                   ChargeSession.started_at <= сейчас)
            .group_by(ChargeSession.location_id))).all()
    }
    последние = {
        str(loc): последняя
        for loc, последняя in (await db.execute(
            select(ChargeSession.location_id, func.max(ChargeSession.started_at))
            .where(ChargeSession.company_id == company_id,
                   ChargeSession.location_id.is_not(None),
                   ChargeSession.started_at <= сейчас,
                   ChargeSession.energy_kwh > 0)
            .group_by(ChargeSession.location_id))).all()
    }

    визиты_окна = await visit_summary(db, company_id, с_даты, сейчас)

    имена_регионов = dict((rid, name) for rid, name in (await db.execute(
        select(Region.id, Region.name).where(Region.company_id == company_id))).all())

    станции = (await db.execute(
        select(ServiceLocation).where(
            ServiceLocation.company_id == company_id,
            *в_сети()))).scalars().all()

    марки: dict[str, dict[str, Any]] = {}
    станции_марки: list[dict[str, Any]] = []
    # Регионы выборки — чтобы экран мог предложить отбор, не заводя у себя
    # справочник: перечень регионов меняется вместе с сетью.
    регионы_выборки: set[str] = set()

    for s in станции:
        рег = имена_регионов.get(s.region_id) or (
            (s.extra_metadata or {}).get("federalSubject") if s.extra_metadata else None)
        # Перечень регионов собираем ДО отбора: иначе выбранный на экране регион
        # остался бы в списке один, и вернуться к «всем» было бы нечем.
        if not обслуживаем(s.owner):
            continue
        if рег:
            регионы_выборки.add(рег)
        if not region_matches(рег, region):
            continue
        # Железо партнёра — его зона ответственности: рекламацию по нему пишем
        # не мы, и в разрезе марок нашего парка его быть не должно.
        if not обслуживаем(s.owner):
            continue
        марка = (s.brand or "").strip() or БЕЗ_МАРКИ
        w = работа.get(str(s.id), {})
        последняя = последние.get(str(s.id))
        дней = (сейчас.date() - последняя.date()).days if последняя else None
        итог_визитов = визиты_окна.get(str(s.id), {})
        визитов = итог_визитов.get("visits", 0)
        неудачных = max(0, визитов - итог_визитов.get("ok", 0))
        мощность = float(s.power_kwt) if getattr(s, "power_kwt", None) else None

        g = марки.setdefault(марка, {
            "vendor": марка, "stations": 0, "active": 0, "working": 0, "noLink": 0,
            "decommissioned": 0, "charging2d": 0, "silentWeek": 0, "neverCharged": 0,
            "visits": 0, "visitsFailed": 0, "attempts": 0, "failedSessions": 0,
            "energyKwh": Decimal(0), "revenue": 0.0, "badStations": 0,
            "models": set(), "powerSum": 0.0, "powerCount": 0,
        })
        g["stations"] += 1
        if s.status != "closed":
            g["active"] += 1
        статус = s.operational_status or "unknown"
        if статус == "working":
            g["working"] += 1
        elif статус == "no_link":
            g["noLink"] += 1
        elif статус == "decommissioned":
            g["decommissioned"] += 1
        if дней is None:
            g["neverCharged"] += 1
            g["silentWeek"] += 1
        else:
            if дней <= СВЕЖО_ДНЕЙ:
                g["charging2d"] += 1
            if дней > НЕДЕЛЯ:
                g["silentWeek"] += 1
        g["visits"] += визитов
        g["visitsFailed"] += неудачных
        g["attempts"] += w.get("попыток", 0)
        g["failedSessions"] += w.get("срывов", 0)
        g["energyKwh"] += w.get("энергия", Decimal(0))
        g["revenue"] += w.get("деньги", 0.0)
        if s.model:
            g["models"].add(s.model)
        if мощность:
            g["powerSum"] += мощность
            g["powerCount"] += 1
        # Станция «плохая», если приездов достаточно и пятая часть — впустую.
        if визитов >= 10 and _проц(неудачных, визитов) >= ПОРОГ_ОТКАЗОВ:
            g["badStations"] += 1

        if vendor and (vendor == "*" or марка == vendor):
            станции_марки.append({
                "locationId": str(s.id),
                "code": s.code,
                "number": str((s.extra_metadata or {}).get("number") or "") or None,
                "name": s.name,
                "region": рег,
                "city": s.city,
                "status": статус,
                "model": s.model,
                "powerKwt": мощность,
                    "connectors": s.connectors_count,
                "vendor": марка,
                "silentDays": дней,
                "visits": визитов,
                "visitsFailed": неудачных,
                "failedVisitsPct": _проц(неудачных, визитов),
                "attemptsPerVisit": round(w.get("попыток", 0) / визитов, 2) if визитов else 0.0,
                "energyKwh": decimal_round(w.get("энергия", 0), 1),
                "revenue": round(w.get("деньги", 0.0), 2),
            })

    строки: list[dict[str, Any]] = []
    for g in марки.values():
        визитов = g["visits"]
        строки.append({
            "vendor": g["vendor"],
            "stations": g["stations"],
            "active": g["active"],
            "working": g["working"],
            "noLink": g["noLink"],
            "decommissioned": g["decommissioned"],
            # Доля марки, которая реально отпускала энергию за последние сутки.
            "charging2d": g["charging2d"],
            "livePct": _проц(g["charging2d"], g["active"]),
            "silentWeek": g["silentWeek"],
            "neverCharged": g["neverCharged"],
            "visits": визитов,
            "visitsFailed": g["visitsFailed"],
            "failedVisitsPct": _проц(g["visitsFailed"], визитов),
            "attemptsPerVisit": round(g["attempts"] / визитов, 2) if визитов else 0.0,
            "failedSessionsPct": _проц(g["failedSessions"], g["attempts"]),
            "energyKwh": decimal_round(g["energyKwh"], 1),
            "revenue": round(g["revenue"], 2),
            "badStations": g["badStations"],
            "models": sorted(g["models"])[:12],
            "modelsCount": len(g["models"]),
            "avgPowerKwt": (round(g["powerSum"] / g["powerCount"], 1)
                            if g["powerCount"] else None),
            # Энергия на станцию в сутки — сравнимая мера отдачи для марок
            # разного размера.
            "kwhPerStationDay": (decimal_round(g["energyKwh"] / g["active"] / days, 1)
                                 if g["active"] and days else 0.0),
        })

    # Сверху — марки с наибольшим числом приездов впустую: процент без объёма
    # поднял бы наверх вендора с одной станцией и тремя визитами.
    строки.sort(key=lambda r: (-r["visitsFailed"], -r["visits"]))
    станции_марки.sort(key=lambda r: (-r["failedVisitsPct"], -r["visits"]))

    всего_визитов = sum(r["visits"] for r in строки)
    всего_неудач = sum(r["visitsFailed"] for r in строки)

    return {
        **контекст,
        "days": days,
        "threshold": ПОРОГ_ОТКАЗОВ,
        "totals": {
            "vendors": len(строки),
            "stations": sum(r["stations"] for r in строки),
            "visits": всего_визитов,
            "visitsFailed": всего_неудач,
            "failedVisitsPct": _проц(всего_неудач, всего_визитов),
            "badStations": sum(r["badStations"] for r in строки),
        },
        "regions": sorted(регионы_выборки, key=lambda r: r.lower()),
        "vendors": строки,
        "vendor": vendor,
        "stations": станции_марки,
        "scope": {"scope": "operated", "label": "Наши ЭЗС",
                  "note": "без партнёрских: их железо — зона ответственности партнёра"},
        "note": ("только своё железо, без партнёрских станций; "
                 "надёжность считается приездами клиентов (несколько попыток "
                 "подряд — один приезд); «живых» считаем по станциям, отпускавшим "
                 "энергию за двое суток от последней загрузки"),
    }
