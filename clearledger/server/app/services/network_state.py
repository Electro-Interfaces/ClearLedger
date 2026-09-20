"""Состояние сети ЭЗС: что со станциями на самом деле.

Два источника, и по отдельности оба врут.

**Статус из выгрузки** говорит, что думает витрина: «Активная», «Нет связи»,
«Отключена», «Выведена». Он приходит раз в сутки снимком и расходится с
действительностью: на пилоте 34 станции числятся активными, а последняя зарядка
на них была больше месяца назад — одна молчит 271 день.

**Журнал сессий** говорит, что станция делала: отпускала энергию или нет. Это
проверка статуса делом. Обратный случай тоже есть: 13 станций «без связи»
заряжали на этой неделе — связь с витриной потеряна, а станция работает.

Поэтому экран строится на ПЕРЕСЕЧЕНИИ: статус рядом с днями молчания. Расхождение
между ними — не погрешность, а рабочий список: именно там либо станция стоит и
об этом никто не знает, либо данные о ней не доезжают.

Деньги считаются по её же прошлой выручке: «молчит 40 дней» — повод посмотреть,
«молчит 40 дней и это 12 тыс. ₽ в месяц» — повод поехать.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession, Region, ServiceLocation
from app.services.ops_monitor_context import monitor_context, region_matches

# Станцией сети считаем зарядную точку; тестовые стенды в картину не идут.
# Что считается парком — одно определение на все экраны (station_scope).
from app.services.station_scope import (  # noqa: E402
    ВИДЫ_СТАНЦИЙ, в_сети, обслуживаем, подпись as подпись_охвата,
)

# Пороги давности: сутки — норма даже у загруженной станции (ночь без клиентов),
# двое — уже наблюдение, неделя — разговор, месяц — потеря.
СВЕЖО_ДНЕЙ = 2
НЕДЕЛЯ = 7
МЕСЯЦ = 30

# Окно, по которому считаем деньги станции: 90 дней сглаживают сезон и разовые
# всплески, месячная оценка получается делением.
ОКНО_ДЕНЕГ = 90

# Со скольких дней тишина у ЗАРАБАТЫВАВШЕЙ станции перестаёт быть ночным затишьем.
# Два дня терпим: выходные и будни без клиентов бывают у любой точки.
ПОТЕРЯ_С_ДНЯ = 3

СОСТОЯНИЯ = {
    "working": "Работает",
    "no_link": "Нет связи",
    "disabled": "Отключена",
    "decommissioned": "Выведена",
    "on_repair": "В ремонте",
    "maintenance": "Обслуживание",
    "not_working": "Не работает",
    "unknown": "Нет данных",
}


def _возраст(последняя: datetime | None, сейчас: datetime) -> int | None:
    """Сколько дней станция не отпускала энергию. None — не заряжала никогда."""
    if последняя is None:
        return None
    return max(0, (сейчас.date() - последняя.date()).days)


async def network_state(
    db: AsyncSession, company_id: uuid.UUID, *,
    region: str | None = None,
    only_problems: bool = False,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Состояние сети: сводка, разрез по регионам и строки по станциям.

    `as_of` — день, НА КОТОРЫЙ смотрим. Без него отсчёт идёт от границы данных;
    с ним — от конца указанного дня, и всё, что случилось позже, в расчёт не
    берётся. Это не украшение: «почему 3 сентября сеть встала» разбирается
    только так, а по сегодняшнему срезу тот день уже не виден.
    """
    # Отсчёт ведём не от «сейчас», а от границы данных — самой поздней сессии в
    # базе. Выгрузка приходит раз в сутки и обрывается на вечере предыдущего дня,
    # поэтому «сегодня» и «вчера» в журнале пусты ВСЕГДА. Считая от текущего
    # момента, экран объявил бы молчащей всю сеть и показал бы 888 тыс. ₽ мнимых
    # потерь (проверка 19.09.2026).
    граница = (await db.execute(
        select(func.max(ChargeSession.started_at))
        .where(ChargeSession.company_id == company_id))).scalar()
    сейчас, контекст = monitor_context(граница, as_of)
    окно = сейчас - timedelta(days=ОКНО_ДЕНЕГ)

    # ── работа станции за окно: последняя сессия, сколько их и сколько денег ──
    работа = {
        str(loc): {
            "последняя": последняя,
            "сессий": int(сессий or 0),
            "деньги": float(деньги or 0),
            "сессий_7д": int(сессий_7 or 0),
        }
        for loc, последняя, сессий, деньги, сессий_7 in (await db.execute(
            select(ChargeSession.location_id,
                   func.max(ChargeSession.started_at),
                   func.count(),
                   func.coalesce(func.sum(func.coalesce(
                       ChargeSession.client_amount, ChargeSession.amount)), 0),
                   func.sum(case((ChargeSession.started_at
                                  >= сейчас - timedelta(days=НЕДЕЛЯ), 1),
                                 else_=0)))
            .where(ChargeSession.company_id == company_id,
                   ChargeSession.location_id.is_not(None),
                   ChargeSession.started_at >= окно,
                   ChargeSession.started_at <= сейчас)
            .group_by(ChargeSession.location_id))).all()
    }

    # Последняя сессия ЗА ВСЮ историю, а не только за окно: станция, молчащая
    # полгода, иначе выглядела бы как «не заряжала никогда», и разобрать её было
    # бы нечем — а это разные случаи.
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

    попытки = dict((str(loc), (last, int(total))) for loc, last, total in (await db.execute(
        select(ChargeSession.location_id, func.max(ChargeSession.started_at), func.count())
        .where(ChargeSession.company_id == company_id, ChargeSession.started_at <= сейчас)
        .group_by(ChargeSession.location_id))).all())

    имена_регионов = dict((rid, name) for rid, name in (await db.execute(
        select(Region.id, Region.name).where(Region.company_id == company_id))).all())

    станции = (await db.execute(
        select(ServiceLocation).where(
            ServiceLocation.company_id == company_id,
            *в_сети()))).scalars().all()

    строки: list[dict[str, Any]] = []
    for s in станции:
        # Партнёрские станции (СНК) мы не обслуживаем: их простой — не наша
        # работа и не наш недобор. В продажах и деньгах они остаются.
        if not обслуживаем(s.owner):
            continue
        рег = имена_регионов.get(s.region_id) or (
            (s.extra_metadata or {}).get("federalSubject") if s.extra_metadata else None)
        if not region_matches(рег, region):
            continue
        w = работа.get(str(s.id), {})
        последняя = последние.get(str(s.id))
        дней = _возраст(последняя, сейчас)
        деньги_в_месяц = round(w.get("деньги", 0) / ОКНО_ДЕНЕГ * 30, 2)
        статус = s.operational_status or "unknown"
        строки.append({
            "locationId": str(s.id),
            "code": s.code,
            "number": str((s.extra_metadata or {}).get("number") or "") or None,
            "name": s.name,
            "region": рег,
            "city": s.city,
            "status": статус,
            "statusLabel": СОСТОЯНИЯ.get(статус, статус),
            # Что витрина написала своими словами: «Нажата аварийная кнопка» в наш
            # справочник состояний не укладывается, но инженеру это важно.
            "statusRaw": (s.extra_metadata or {}).get("statusDev"),
            "lastSessionAt": последняя.isoformat() if последняя else None,
            "lastAttemptAt": попытки[str(s.id)][0].isoformat() if str(s.id) in попытки else None,
            "attemptsEver": попытки.get(str(s.id), (None, 0))[1],
            "silentDays": дней,
            "sessions90d": w.get("сессий", 0),
            "sessions7d": w.get("сессий_7д", 0),
            "revenuePerMonth": деньги_в_месяц,
            "connectors": s.connectors_count,
            # Расхождение: витрина считает станцию рабочей, а энергии нет неделю.
            # Ради этого списка экран и заводится.
            "mismatch": статус == "working" and (дней is None or дней > НЕДЕЛЯ),
            "lifeStatus": s.status,
        })

    # Станция, которая зарабатывала и перестала, — это потеря независимо от того,
    # что написала витрина. «Гоголя 1» честно помечена «нет связи» и потому не
    # расхождение, но 158 тыс. ₽ в месяц она приносить перестала — и в списке
    # должна стоять выше сотни мелких расхождений (МАГ, 19.09.2026).
    for r in строки:
        замолчала = r["silentDays"] is None or r["silentDays"] >= ПОТЕРЯ_С_ДНЯ
        r["loss"] = round(r["revenuePerMonth"], 2) if (
            замолчала and r["revenuePerMonth"] > 0 and r["lifeStatus"] != "closed"
            and r["status"] != "decommissioned") else 0.0
        r["attention"] = bool(r["mismatch"] or r["loss"])

    def свежая(r: dict[str, Any]) -> bool:
        return r["silentDays"] is not None and r["silentDays"] <= СВЕЖО_ДНЕЙ

    живые = [r for r in строки if r["lifeStatus"] != "closed"]
    расхождения = [r for r in строки if r["mismatch"]]

    по_состоянию: dict[str, int] = {}
    for r in строки:
        по_состоянию[r["status"]] = по_состоянию.get(r["status"], 0) + 1

    # ── разрез по регионам: где сеть сыпется ──
    регионы: dict[str, dict[str, Any]] = {}
    for r in строки:
        имя = r["region"] or "регион не указан"
        g = регионы.setdefault(имя, {
            "region": имя, "stations": 0, "working": 0, "noLink": 0,
            "silentWeek": 0, "mismatch": 0, "revenuePerMonth": 0.0,
        })
        g["stations"] += 1
        if r["status"] == "working":
            g["working"] += 1
        if r["status"] == "no_link":
            g["noLink"] += 1
        if r["silentDays"] is None or r["silentDays"] > НЕДЕЛЯ:
            g["silentWeek"] += 1
        if r["mismatch"]:
            g["mismatch"] += 1
        g["revenuePerMonth"] += r["loss"]
    for g in регионы.values():
        g["revenuePerMonth"] = round(g["revenuePerMonth"], 2)

    видимые = [r for r in строки if r["attention"]] if only_problems else строки
    # Сверху — потери в рублях, затем расхождения статуса, затем всё остальное по
    # выручке. Инженер открывает экран ради первой строки, а не ради полноты.
    видимые.sort(key=lambda r: (-(r["loss"] or 0), not r["mismatch"],
                                -(r["revenuePerMonth"] or 0)))

    return {
        # Момент, по который есть данные: всё на экране — про него, а не про сейчас.
        **контекст,

        "totals": {
            "stations": len(строки),
            "active": len(живые),
            # Живая сеть — та, что отпускала энергию за последние двое суток.
            # Это и есть ответ на «сколько станций реально работает».
            "charging2d": sum(1 for r in строки if свежая(r)),
            "chargingWeek": sum(1 for r in строки
                                if r["silentDays"] is not None and r["silentDays"] <= НЕДЕЛЯ),
            "silentWeek": sum(1 for r in строки
                              if r["silentDays"] is None or r["silentDays"] > НЕДЕЛЯ),
            "silentMonth": sum(1 for r in строки
                               if r["silentDays"] is None or r["silentDays"] > МЕСЯЦ),
            "neverCharged": sum(1 for r in строки if r["silentDays"] is None),
            "mismatch": len(расхождения),
            # Цена молчания: месячная выручка станций, которые числятся рабочими,
            # но энергии не дают.
            "mismatchRevenue": round(sum(r["revenuePerMonth"] for r in расхождения), 2),
            # Главная цифра экрана: сколько сеть недобирает в месяц из-за станций,
            # которые зарабатывали и замолчали, — независимо от их статуса.
            "attention": sum(1 for r in строки if r["attention"]),
            "lossPerMonth": round(sum(r["loss"] for r in строки), 2),
            "byStatus": по_состоянию,
        },
        "statusLabels": СОСТОЯНИЯ,
        "regions": sorted(регионы.values(), key=lambda g: -g["mismatch"]),
        "stations": видимые,
        "scope": подпись_охвата("operated"),
        "note": ("считаем только свои станции: партнёрские (СНК) мы не "
                 "обслуживаем и в списки эксплуатации не берём. "
                 "Статус приходит из суточной выгрузки витрины (снимок на вечер), "
                 "дни молчания считаются по журналу сессий — это проверка статуса делом; "
                 "отсчёт ведётся от последней загруженной сессии, а не от текущего часа. "
                 "В «Продажах» те же станции считаются иначе: там «без зарядок» — "
                 "ни одной сессии за ВЕСЬ выбранный период, а здесь «молчит» — "
                 "нет зарядок больше недели на выбранный день, и выведенные из "
                 "эксплуатации в парк не входят"),
    }
