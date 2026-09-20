"""История одной станции: что с ней происходило и почему она так работает.

Инженер приходит к станции с вопросом «что тут было». Ответ раньше собирался по
кускам: журнал статусов в одной вкладке, заявки в другой, сессии в третьей, а
«когда она замолчала» не отвечал никто — статус перезаписывался молча.

Здесь три слоя, которые вместе дают связную картину:

- **работа** — надёжность и нагрузка за окно: попытки, срывы, пустые зарядки,
  клиенты, энергия, средний чек. Инженеру важно не «станция работает», а «из ста
  подъездов восемьдесят кончились ничем»;
- **перерывы** — промежутки, когда станция не отпускала энергию дольше суток.
  Это то, что человек называет «она стояла»: с какого дня, сколько длилось,
  сколько подобных случаев за окно;
- **события** — смены состояния из журнала (кто и когда перевёл станцию в «нет
  связи»), рядом с перерывами по времени.

Заявки и работы «Поддержки» сюда не копируются: они спрашиваются у неё в момент
показа через мост объектов, иначе в пространстве появилась бы вторая правда о
заявках (docs/SPACE.md).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, ChargeSession, ServiceLocation

ОКНО_ДНЕЙ = 90

# С какой паузы считаем, что станция стояла. Сутки — не простой: ночь и будний
# день без клиентов бывают у любой точки, особенно у малозагруженной.
ПЕРЕРЫВ_С_ЧАСОВ = 24

СОСТОЯНИЯ = {
    "working": "Работает", "no_link": "Нет связи", "disabled": "Отключена",
    "decommissioned": "Выведена", "on_repair": "В ремонте",
    "maintenance": "Обслуживание", "not_working": "Не работает",
    "unknown": "Нет данных",
}


async def station_history(
    db: AsyncSession, company_id: uuid.UUID, location_id: str, *,
    days: int = ОКНО_ДНЕЙ,
) -> dict[str, Any]:
    """Работа, перерывы и события станции за окно."""
    loc = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.id == location_id,
        ServiceLocation.company_id == company_id))).scalar_one_or_none()
    if loc is None:
        raise ValueError("Станция не найдена")

    граница = (await db.execute(
        select(func.max(ChargeSession.started_at))
        .where(ChargeSession.company_id == company_id))).scalar()
    сейчас = граница or datetime.now(timezone.utc).replace(tzinfo=None)
    с_даты = сейчас - timedelta(days=days)

    сорвана = ChargeSession.result.ilike("%error%")
    итог = (await db.execute(
        select(func.count(),
               func.sum(case((сорвана, 1), else_=0)),
               func.sum(case((ChargeSession.energy_kwh <= 0, 1), else_=0)),
               func.count(func.distinct(ChargeSession.user_id)),
               func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
               func.coalesce(func.sum(func.coalesce(
                   ChargeSession.client_amount, ChargeSession.amount)), 0),
               func.avg(ChargeSession.duration_min))
        .where(ChargeSession.company_id == company_id,
               ChargeSession.location_id == location_id,
               ChargeSession.started_at >= с_даты))).one()
    всего, срывов, пустых, клиентов, энергия, деньги, длит = итог
    всего = int(всего or 0)

    # ── дни: нагрузка и качество по суткам ──
    дни = [
        {"day": д.isoformat(), "sessions": int(с), "failed": int(ош or 0),
         "energyKwh": round(float(э or 0), 1),
         "revenue": round(float(р or 0), 2)}
        for д, с, ош, э, р in (await db.execute(
            select(func.date(ChargeSession.started_at),
                   func.count(),
                   func.sum(case((сорвана, 1), else_=0)),
                   func.coalesce(func.sum(ChargeSession.energy_kwh), 0),
                   func.coalesce(func.sum(func.coalesce(
                       ChargeSession.client_amount, ChargeSession.amount)), 0))
            .where(ChargeSession.company_id == company_id,
                   ChargeSession.location_id == location_id,
                   ChargeSession.started_at >= с_даты)
            .group_by(func.date(ChargeSession.started_at))
            .order_by(func.date(ChargeSession.started_at)))).all()
    ]

    # ── перерывы: когда станция стояла ──
    # Считаем по успешным зарядкам: серия сорванных попыток простоем не является,
    # но энергии за неё тоже нет — такой случай ловит надёжность, а не этот список.
    моменты = [
        м for (м,) in (await db.execute(
            select(ChargeSession.started_at)
            .where(ChargeSession.company_id == company_id,
                   ChargeSession.location_id == location_id,
                   ChargeSession.started_at >= с_даты,
                   ChargeSession.energy_kwh > 0)
            .order_by(ChargeSession.started_at))).all()
    ]
    перерывы: list[dict[str, Any]] = []
    предыдущий = None
    for м in моменты:
        if предыдущий is not None:
            пауза = (м - предыдущий).total_seconds() / 3600
            if пауза >= ПЕРЕРЫВ_С_ЧАСОВ:
                перерывы.append({
                    "from": предыдущий.isoformat(), "to": м.isoformat(),
                    "hours": round(пауза, 1), "days": round(пауза / 24, 1),
                    "ongoing": False,
                })
        предыдущий = м
    # Открытый перерыв: станция молчит прямо сейчас — его в списке быть обязано,
    # иначе самая тяжёлая пауза окажется единственной невидимой.
    if предыдущий is not None:
        пауза = (сейчас - предыдущий).total_seconds() / 3600
        if пауза >= ПЕРЕРЫВ_С_ЧАСОВ:
            перерывы.append({
                "from": предыдущий.isoformat(), "to": None,
                "hours": round(пауза, 1), "days": round(пауза / 24, 1),
                "ongoing": True,
            })
    перерывы.sort(key=lambda p: -p["hours"])

    # ── события: смены состояния ──
    записи = (await db.execute(
        select(AuditEvent)
        .where(AuditEvent.company_id == company_id,
               AuditEvent.action == "location_op_status",
               AuditEvent.details.like(f'%"location_id":"{loc.id}"%'))
        .order_by(AuditEvent.timestamp.desc()).limit(100))).scalars().all()
    события: list[dict[str, Any]] = []
    for e in записи:
        try:
            d = json.loads(e.details or "{}")
        except ValueError:
            d = {}
        события.append({
            "at": e.timestamp.isoformat() if e.timestamp else None,
            "kind": "status",
            "from": СОСТОЯНИЯ.get(d.get("from") or "", d.get("from")),
            "to": СОСТОЯНИЯ.get(d.get("to") or "", d.get("to")),
            "reason": d.get("reason") or None,
            "author": e.user_name,
        })

    последняя = (await db.execute(
        select(func.max(ChargeSession.started_at))
        .where(ChargeSession.company_id == company_id,
               ChargeSession.location_id == location_id))).scalar()

    порты = loc.connectors_count or 0
    return {
        "asOf": сейчас.isoformat(),
        "days": days,
        "station": {
            "locationId": str(loc.id),
            "code": loc.code,
            "number": str((loc.extra_metadata or {}).get("number") or "") or None,
            "name": loc.name,
            "city": loc.city,
            "status": loc.operational_status or "unknown",
            "statusLabel": СОСТОЯНИЯ.get(loc.operational_status or "unknown",
                                         loc.operational_status),
            "statusRaw": (loc.extra_metadata or {}).get("statusDev"),
            "connectors": loc.connectors_count,
            "powerKwt": float(loc.power_kwt) if getattr(loc, "power_kwt", None) else None,
            "lastSessionAt": последняя.isoformat() if последняя else None,
            "silentDays": (сейчас.date() - последняя.date()).days if последняя else None,
        },
        "work": {
            "sessions": всего,
            "failed": int(срывов or 0),
            "failedPct": round(100.0 * int(срывов or 0) / всего, 1) if всего else 0.0,
            "empty": int(пустых or 0),
            "clients": int(клиентов or 0),
            "energyKwh": round(float(энергия or 0), 1),
            "revenue": round(float(деньги or 0), 2),
            "avgMinutes": round(float(длит), 1) if длит is not None else None,
            # Нагрузка на порт в сутки — то, чем инженер меряет занятость станции
            # и чем объясняет износ. Без числа портов считать нечего.
            "sessionsPerPortDay": (round(всего / порты / days, 2) if порты and days else None),
        },
        "days_series": дни,
        "breaks": перерывы[:20],
        "breaksTotal": len(перерывы),
        "events": события,
        "note": ("перерыв — пауза между зарядками дольше суток; срывы и пустые "
                 "зарядки считаются по журналу сессий; заявки и работы живут в "
                 "«Поддержке» и показываются рядом, а не копируются сюда"),
    }
