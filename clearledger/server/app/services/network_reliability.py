"""Надёжность сети: где станции отказывают и как часто.

«Состояние сети» отвечает, работает ли станция вообще. Этот расчёт — про другое:
станция в сети, сессии идут, а клиент уезжает ни с чем. Худшие станции пилота
отдают 0,1 кВт·ч на попытку при полусотне попыток за квартал — люди подъезжают,
подключаются и не заряжаются.

Материал берём из журнала сессий: исход («Complete» / «CompleteError»), энергия,
длительность, клиент. Витрина своих показателей качества не наполняет — графы
«процент успеха» и «готовность» приходят пустыми во всех строках.

**Главная мера — визит, а не сессия.** CPO пишет каждую попытку подключения
отдельной строкой: человек, у которого разъём схватился с третьего раза, даёт три
сессии — две с ошибкой и одну рабочую. По сессиям это «67 % брака», по факту он
зарядился. Визит = один приезд одного клиента на одну станцию (`visit_key`), и
он считается удавшимся, если энергия пошла хоть по одной его попытке
(`visit_charged`). По сети успех визитами — около 90 % против 73 % сессиями.

Поэтому три разных беды, которые нельзя смешивать в один «процент»:

- **неудавшиеся визиты** — человек приехал и уехал ни с чем. Это и есть отказ
  станции глазами клиента;
- **попытки на визит** — сколько раз пришлось воткнуть разъём. Визит удался, но
  с третьего раза — станция работает, а впечатление испорчено;
- **уходящие клиенты** — сколько людей столкнулось с этим на станции; станция с
  двумя недовольными в месяц и станция с полусотней — разные разговоры.

Сорванные сессии и пустые зарядки остаются рядом: по ним видно, ЧТО именно
происходит с железом, когда визиты не удаются.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession, Region, ServiceLocation
from app.services.ops_monitor_context import monitor_context, region_matches, visit_summary, decimal_round
from app.services.station_scope import в_сети, обслуживаем

# Окно наблюдения по умолчанию: квартал сглаживает разовые сбои и даёт
# достаточную выборку даже малозагруженным станциям.
ОКНО_ДНЕЙ = 90

# Меньше этого числа попыток — не статистика, а случай: две ошибки из трёх дают
# «67 % срывов» и вытесняют из списка станцию с сотней реальных отказов.
МИНИМУМ_ПОПЫТОК = 10

# Порог разговора: каждый десятый приезд, кончившийся ничем. По сети таких около
# 10 %, поэтому станция вдвое хуже средней — уже повод ехать.
ПОРОГ_ОТКАЗОВ = 20.0


def _проц(часть: int, целое: int) -> float:
    return round(100.0 * часть / целое, 1) if целое else 0.0


async def network_reliability(
    db: AsyncSession, company_id: uuid.UUID, *,
    days: int = ОКНО_ДНЕЙ,
    region: str | None = None,
    min_sessions: int = МИНИМУМ_ПОПЫТОК,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Надёжность станций за окно: срывы, пустые зарядки, задетые клиенты.

    `as_of` сдвигает конец окна на выбранный день: «как станция работала в
    августе» — это то же окно, но закончившееся тогда, а не сегодня.
    """
    граница = (await db.execute(
        select(func.max(ChargeSession.started_at))
        .where(ChargeSession.company_id == company_id))).scalar()
    сейчас, контекст = monitor_context(граница, as_of)
    с_даты = сейчас - timedelta(days=days)

    сорвана = ChargeSession.result.ilike("%error%") | ChargeSession.result.ilike("%ошиб%")
    пустая = ChargeSession.energy_kwh <= 0

    строки_бд = (await db.execute(
        select(ChargeSession.location_id,
               func.count(),
               func.sum(case((сорвана, 1), else_=0)),
               func.sum(case((пустая, 1), else_=0)),
               func.count(func.distinct(ChargeSession.user_id)),
               func.count(func.distinct(case((сорвана, ChargeSession.user_id)))),
               func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
               func.coalesce(func.sum(func.coalesce(
                   ChargeSession.client_amount, ChargeSession.amount)), 0),
               func.max(ChargeSession.started_at),
               # Визиты: приездов всего и сколько из них кончились зарядкой.
               func.count(func.distinct(ChargeSession.visit_key)),
               func.count(func.distinct(case(
                   (ChargeSession.visit_charged.is_(True), ChargeSession.visit_key)))),
               # Клиенты, чей приезд кончился ничем: их и «потеряли» на станции.
               func.count(func.distinct(case(
                   (ChargeSession.visit_charged.is_(False), ChargeSession.user_id)))))
        .where(ChargeSession.company_id == company_id,
               ChargeSession.location_id.is_not(None),
               ChargeSession.started_at >= с_даты,
               ChargeSession.started_at <= сейчас)
        .group_by(ChargeSession.location_id))).all()

    визиты_окна = await visit_summary(db, company_id, с_даты, сейчас)

    имена_регионов = dict((rid, name) for rid, name in (await db.execute(
        select(Region.id, Region.name).where(Region.company_id == company_id))).all())
    объекты = {
        str(l.id): l for l in (await db.execute(
            select(ServiceLocation).where(
                ServiceLocation.company_id == company_id,
                *в_сети()))).scalars().all()
    }

    строки: list[dict[str, Any]] = []
    for (loc, всего, срывов, пустых, клиентов, задетых,
         энергия, деньги, последняя, визитов, визитов_ок, клиентов_без_зарядки) in строки_бд:
        объект = объекты.get(str(loc))
        if объект is None:
            continue
        if not обслуживаем(объект.owner):
            continue
        рег = имена_регионов.get(объект.region_id) or (
            (объект.extra_metadata or {}).get("federalSubject") if объект.extra_metadata else None)
        if not region_matches(рег, region):
            continue
        итог_визитов = визиты_окна.get(str(loc), {})
        визитов, визитов_ок, клиентов_без_зарядки = (итог_визитов.get("visits", 0), итог_визитов.get("ok", 0), итог_визитов.get("lost", 0))
        всего = int(всего or 0)
        срывов = int(срывов or 0)
        пустых = int(пустых or 0)
        визитов = int(визитов or 0)
        визитов_ок = int(визитов_ок or 0)
        неудачных = max(0, визитов - визитов_ок)
        строки.append({
            "locationId": str(loc),
            "code": объект.code,
            "number": str((объект.extra_metadata or {}).get("number") or "") or None,
            "name": объект.name,
            "region": рег,
            "city": объект.city,
            "status": объект.operational_status or "unknown",
            # Марка и модель — чтобы отказы можно было свести не только по
            # площадкам, но и по железу: «Надёжность» и «Производители» должны
            # называть виноватым одно и то же.
            "brand": (объект.brand or "").strip() or None,
            "model": объект.model or None,
            # Визит — приезд клиента. Главная мера: удался или нет.
            "visits": визитов,
            "visitsOk": визитов_ок,
            "visitsFailed": неудачных,
            "failedVisitsPct": _проц(неудачных, визитов),
            # Сколько раз пришлось воткнуть разъём за один приезд.
            "attemptsPerVisit": round(всего / визитов, 2) if визитов else 0.0,
            "clientsLost": int(клиентов_без_зарядки or 0),
            "sessions": всего,
            "failed": срывов,
            "failedPct": _проц(срывов, всего),
            # Пустая зарядка — отдельная беда: исход «успех», энергии ноль.
            # Оборудование считает такую попытку нормальной, клиент — нет.
            "empty": пустых,
            "emptyPct": _проц(пустых, всего),
            "clients": int(клиентов or 0),
            "clientsAffected": int(задетых or 0),
            "energyKwh": decimal_round(энергия, 1),
            "revenue": round(float(деньги or 0), 2),
            # Сколько энергии приходится на попытку: у станции, которая «работает»,
            # но отдаёт 0,1 кВт·ч на подъезд, беда не в проценте, а в железе.
            "kwhPerSession": round(float(энергия or 0) / всего, 2) if всего else 0.0,
            "lastSessionAt": последняя.isoformat() if последняя else None,
            "connectors": объект.connectors_count,
        })

    текущая_неделя = await visit_summary(db, company_id, сейчас - timedelta(days=7), сейчас)
    прошлая_неделя = await visit_summary(db, company_id, сейчас - timedelta(days=14), сейчас - timedelta(days=7, microseconds=1))
    ids = {r["locationId"] for r in строки}
    def неделя(данные):
        visits = sum(r["visits"] for k, r in данные.items() if k in ids)
        failed = sum(r["visits"] - r["ok"] for k, r in данные.items() if k in ids)
        return {"visits": visits, "failed": failed, "failedPct": _проц(failed, visits)}
    trend = {"current": неделя(текущая_неделя), "previous": неделя(прошлая_неделя)}
    trend["deltaPp"] = round(trend["current"]["failedPct"] - trend["previous"]["failedPct"], 1)

    значимые = [r for r in строки if r["visits"] >= min_sessions]
    плохие = [r for r in значимые if r["failedVisitsPct"] >= ПОРОГ_ОТКАЗОВ]
    плохие.sort(key=lambda r: (-r["failedVisitsPct"], -r["visitsFailed"]))
    # Сверху — станции, где приездов «ни с чем» больше всего: процент без числа
    # людей уводит наверх точку с тремя визитами, а не ту, где ушли полсотни.
    значимые.sort(key=lambda r: (-r["failedVisitsPct"], -r["visitsFailed"]))

    всего_сессий = sum(r["sessions"] for r in строки)
    всего_срывов = sum(r["failed"] for r in строки)
    всего_пустых = sum(r["empty"] for r in строки)
    всего_визитов = sum(r["visits"] for r in строки)
    визитов_ок = sum(r["visitsOk"] for r in строки)

    # ── регионы: где отказывает чаще ──
    регионы: dict[str, dict[str, Any]] = {}
    for r in значимые:
        имя = r["region"] or "регион не указан"
        g = регионы.setdefault(имя, {
            "region": имя, "stations": 0, "sessions": 0, "failed": 0, "bad": 0,
            "visits": 0, "visitsFailed": 0,
        })
        g["stations"] += 1
        g["sessions"] += r["sessions"]
        g["failed"] += r["failed"]
        g["visits"] += r["visits"]
        g["visitsFailed"] += r["visitsFailed"]
        if r["failedVisitsPct"] >= ПОРОГ_ОТКАЗОВ:
            g["bad"] += 1
    for g in регионы.values():
        g["failedPct"] = _проц(g["failed"], g["sessions"])
        g["failedVisitsPct"] = _проц(g["visitsFailed"], g["visits"])

    return {
        **контекст,
        "days": days,
        "trend": trend,
        "minSessions": min_sessions,
        "threshold": ПОРОГ_ОТКАЗОВ,
        "totals": {
            "populationStations": sum(1 for s in объекты.values() if обслуживаем(s.owner) and region_matches(имена_регионов.get(s.region_id) or (s.extra_metadata or {}).get("federalSubject"), region)),
            "stations": len(строки),
            "stationsCounted": len(значимые),
            # Визиты — главный счёт: приездов всего, удалось, ушли ни с чем.
            "visits": всего_визитов,
            "visitsOk": визитов_ок,
            "visitsFailed": max(0, всего_визитов - визитов_ок),
            "failedVisitsPct": _проц(max(0, всего_визитов - визитов_ок), всего_визитов),
            "attemptsPerVisit": round(всего_сессий / всего_визитов, 2) if всего_визитов else 0.0,
            "sessions": всего_сессий,
            "failed": всего_срывов,
            "failedPct": _проц(всего_срывов, всего_сессий),
            "empty": всего_пустых,
            "emptyPct": _проц(всего_пустых, всего_сессий),
            "badStations": len(плохие),
            # Клиенты, которым станция отказала. Считается по станциям, поэтому
            # один и тот же человек на двух станциях учтён дважды — это оценка
            # задетых визитов, а не уникальных людей по сети.
            "clientsAffected": sum(r["clientsAffected"] for r in значимые),
        },
        "regions": sorted(регионы.values(), key=lambda g: -g["failedVisitsPct"]),
        "stations": значимые,
        "scope": {"scope": "operated", "label": "Наши ЭЗС",
                  "note": "без партнёрских: станции СНК обслуживаем не мы"},
        "note": (f"окно {days} дней, только свои станции, с {min_sessions}+ визитами; "
                 f"порог разговора — {ПОРОГ_ОТКАЗОВ} % приездов без зарядки; "
                 "визит = один приезд клиента (несколько попыток подряд — один "
                 "визит), поэтому успех считается по визитам, а не по сессиям"),
    }
