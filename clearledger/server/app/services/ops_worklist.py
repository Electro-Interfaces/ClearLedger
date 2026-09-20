"""Рабочий лист инженера: что делать сегодня, одним списком.

Раздел «Мониторинг» отвечает на разные вопросы разными экранами — состояние
сети, надёжность, производители, деньги. Это правильно для разбора и неудобно
для утра: чтобы понять, чем заняться, инженер обходит шесть экранов и складывает
их в голове.

Здесь обратный порядок: сначала строки работы, потом уже разрезы. Каждая строка —
станция, причина и цена вопроса. Порядок задаёт не тяжесть беды, а **сколько
стоит бездействие**: «молчит 16 дней» — повод посмотреть, «молчит 16 дней, это
22 тыс. ₽ в месяц и по ней никто не заводил заявку» — повод ехать.

Четыре причины, и это не список всех бед сети, а список того, что решается
выездом или звонком сегодня:

- **молчит** — станция числится рабочей, энергии нет дольше недели;
- **отказывает** — станция на связи, но каждый пятый приезд кончается ничем;
- **не взята в работу** — беду видно, а заявки по ней нет. Это не отдельная
  беда, а признак первых двух, и поэтому он не строка, а пометка на строке;
- **просрочена заявка** — работа заведена, срок сорван, станция всё ещё стоит;
- **поверка счётчика** — истекла или истекает в ближайший месяц. Беда тихая:
  станция работает, ток идёт, а показания её счётчика уже недействительны для
  расчётов (ФЗ-102), и спор о киловаттах она проигрывает заранее;
- **просрочено ТО** — обслуживание по графику модели не проводилось дольше
  своего интервала;
- **нарушение по осмотру** — инженер был и увидел беду: нет цены до оплаты,
  сорвана оклейка, открыт щит. Это уже найденный факт, а не подозрение.

Последние три — не отказы, и в тяжёлые причины они не поднимаются сами. Но в
одну очередь с отказами они попадают намеренно: выезд на станцию стоит дороже
самой работы, и раз уж машина едет, везти надо всё, что по ней накопилось.

ПОРЯДОК. Деньги, люди, **загруженность площадки**, давность. Загруженность —
третьим ключом, а не первым: у профилактических причин денег потерь нет вовсе,
и без неё поверка на станции с полусотней приездов в неделю встала бы в очередь
вровень с той, куда заезжают дважды в месяц.

Чего здесь намеренно нет: полноты документов, небаланса, тарифов. Это работа
экономиста, и в утреннем списке инженера она сделала бы главным то, что он не
может исправить. Нет и пунктов «никогда не осматривали»: на старте это весь
парк, и очередь работы превратилась бы в список станций.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Region, ServiceLocation, StationCheck
from app.services.network_reliability import network_reliability
from app.services.network_state import network_state
from app.services.station_checklist import ITEM_BY_KEY
from app.services.station_scope import обслуживаем
from app.services.ops_monitor_context import region_matches
from app.services.station_upkeep import network_upkeep

# Окно надёжности для утреннего списка: квартал сглаживает разовые сбои, но
# уже показывает станцию, которая портит впечатление постоянно.
ОКНО_ОТКАЗОВ = 90

# Молчание, после которого это не «выходные», а работа.
МОЛЧИТ_ДНЕЙ = 7

# Цена вопроса, ниже которой строка не поднимается наверх сама. Ноль не
# отбрасываем: станция, которая никогда не зарабатывала, тоже может стоять из-за
# того, что её не запустили.
ДЕНЬГИ_ЗАМЕТНЫЕ = 5_000.0


def _вес(строка: dict[str, Any]) -> tuple:
    """Порядок списка: деньги, люди, давность. Именно в этом порядке.

    Сортировать по тяжести беды бессмысленно: «не работает» у станции с двумя
    приездами в квартал и у станции с полусотней — разные задачи одного дня.
    """
    return (
        -(строка.get("lossPerMonth") or 0),
        -(строка.get("clientsLost") or 0),
        # Загруженность площадки: при равных деньгах вперёд идёт та, где больше
        # людей. Для профилактики (поверка, ТО) это вообще единственный разумный
        # порядок — потерь там пока нет.
        -(строка.get("visits") or 0),
        -(строка.get("silentDays") or 0),
    )


async def ops_worklist(
    db: AsyncSession, company_id: uuid.UUID, *,
    region: str | None = None,
    open_work: dict[str, dict[str, Any]] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Список работы на сегодня.

    `open_work` — свёртка открытых заявок по объектам (`ecoObjectId` → сводка).
    Ход работы ведёт «Поддержка» (docs/PROCESS.md), поэтому сюда он приходит
    параметром, а не запрашивается отсюда: расчёт остаётся про данные Ядра и
    считается, даже когда приложение недоступно.
    """
    работа = (open_work or {}) if as_of is None else {}

    состояние = await network_state(db, company_id, region=region,
                                    only_problems=False, as_of=as_of)
    надёжность = await network_reliability(db, company_id, days=ОКНО_ОТКАЗОВ,
                                           region=region, min_sessions=0, as_of=as_of)

    парк = {r["locationId"]: r for r in состояние["stations"]}
    строки: dict[str, dict[str, Any]] = {}

    def строка(loc_id: str, источник: dict[str, Any]) -> dict[str, Any]:
        s = строки.get(loc_id)
        if s is None:
            w = работа.get(loc_id) or {}
            s = {
                "locationId": loc_id,
                "code": источник.get("code"),
                "number": источник.get("number"),
                "name": источник.get("name"),
                "region": источник.get("region"),
                "city": источник.get("city"),
                "status": источник.get("status"),
                "statusLabel": источник.get("statusLabel"),
                "visitsPerDay": None,
                "reasons": [],
                "silentDays": None,
                "lossPerMonth": 0.0,
                "clientsLost": 0,
                "failedVisitsPct": None,
                "visits": 0,
                # Ход работы: сколько открытых заявок и есть ли сорванный срок.
                "openTickets": int(w.get("open") or 0),
                "breachedTickets": int(w.get("breached") or 0),
                "lastTicketId": w.get("lastId"),
                "lastTicketNumber": w.get("lastNumber"),
            }
            строки[loc_id] = s
        return s

    # ── молчит ──
    for r in состояние.get("stations", []):
        дней = r.get("silentDays")
        молчит = дней is None or дней > МОЛЧИТ_ДНЕЙ
        if not молчит and not r.get("loss"):
            continue
        s = строка(r["locationId"], r)
        s["silentDays"] = дней
        s["lossPerMonth"] = float(r.get("loss") or 0)
        s["reasons"].append({
            "kind": "silent",
            "label": (("нет сессий в загруженной истории" if not r.get("attemptsEver") else "попытки есть, энергии не было") if дней is None
                      else f"молчит {дней} дн"),
            # Расхождение витрины и факта называем словами: инженеру важно не
            # «жёлтая строка», а что именно не сходится.
            "note": r.get("statusRaw") or ("числится рабочей" if r.get("mismatch") else None),
        })

    # ── отказывает ──
    порог = надёжность.get("threshold", 20.0)
    # Приезды за окно — по ВСЕМ станциям, а не только по проблемным: это и есть
    # загруженность площадки, по которой выстраивается очередь профилактики.
    трафик = {r["locationId"]: (r.get("visits") or 0)
              for r in надёжность.get("stations", [])}
    for r in надёжность.get("stations", []):
        if (r.get("visits") or 0) < 10 or (r.get("failedVisitsPct") or 0) < порог:
            continue
        s = строка(r["locationId"], r)
        s["failedVisitsPct"] = r.get("failedVisitsPct")
        s["visits"] = r.get("visits") or 0
        s["clientsLost"] = r.get("clientsLost") or 0
        s["reasons"].append({
            "kind": "failing",
            "label": f"{r.get('failedVisitsPct')} % приездов впустую",
            "note": (f"{r.get('attemptsPerVisit')} попыток на приезд"
                     if (r.get("attemptsPerVisit") or 0) >= 2 else None),
        })

    # ── поверка счётчика и ТО ──
    # Источник — поля единицы оборудования, а не наблюдение инженера: срок надо
    # считать по всей сети сразу, а не перечитывать примечания осмотров.
    сроки = await network_upkeep(db, company_id, as_of=as_of)
    сроки["rows"] = [r for r in сроки.get("rows", []) if r.get("locationId") in парк]
    for r in сроки.get("rows", []):
        loc_id = r.get("locationId")
        if not loc_id:
            continue
        м, т = r["meter"], r["service"]
        если_надо = (м["state"] in ("overdue", "soon") or т["state"] == "overdue")
        if not если_надо:
            continue
        s = строка(loc_id, {})
        if м["state"] == "overdue":
            s["reasons"].append({
                "kind": "meter",
                "label": f"поверка счётчика истекла {abs(м['daysLeft'])} дн. назад",
                "note": "показания недействительны для расчётов (ФЗ-102)"})
        elif м["state"] == "soon":
            s["reasons"].append({
                "kind": "meter",
                "label": f"поверка счётчика кончается через {м['daysLeft']} дн.",
                "note": м["verifyUntil"]})
        if т["state"] == "overdue":
            s["reasons"].append({
                "kind": "service",
                "label": f"ТО просрочено на {abs(т['daysLeft'])} дн.",
                "note": (f"по графику раз в {т['intervalDays']} дн."
                         + (" (норматив типа)" if т["intervalDefault"] else ""))})

    # ── нарушения по осмотру ──
    # Последняя отметка по каждому пункту: нарушение не гаснет по времени и
    # висит, пока не появится отметка «в порядке».
    последние = (
        select(StationCheck.location_id.label("loc"),
               StationCheck.item_key.label("item"),
               func.max(StationCheck.checked_on).label("d"))
        .where(StationCheck.company_id == company_id,
               StationCheck.checked_on <= as_of if as_of else True)
        .group_by(StationCheck.location_id, StationCheck.item_key).subquery())
    нарушения = (await db.execute(
        select(StationCheck.location_id, StationCheck.item_key)
        .join(последние,
              (StationCheck.location_id == последние.c.loc)
              & (StationCheck.item_key == последние.c.item)
              & (StationCheck.checked_on == последние.c.d))
        .where(StationCheck.company_id == company_id,
               StationCheck.state == "fail"))).all()
    беды: dict[str, list[str]] = {}
    for loc_id, item in нарушения:
        беды.setdefault(loc_id, []).append(item)
    for loc_id, пункты in беды.items():
        if loc_id not in парк:
            continue
        s = строка(loc_id, {})
        первый = ITEM_BY_KEY.get(пункты[0], {})
        s["reasons"].append({
            "kind": "check",
            "label": (f"нарушений по осмотру: {len(пункты)}" if len(пункты) > 1
                      else "нарушение по осмотру"),
            "note": первый.get("label"),
        })

    # ── имена станций, попавших сюда только по срокам и осмотру ──
    # Состояние и надёжность их не отдали (станция работает хорошо), а строка
    # без названия и номера — это строка, по которой нельзя выехать. Здесь же
    # действуют оба правила охвата: партнёрские станции СНК обслуживаем не мы, и
    # фильтр по региону обязан работать одинаково для всех причин, иначе выбор
    # «Москва» приносит поверку из Сибири.
    безымянные = [k for k, v in строки.items() if not v.get("name")]
    if безымянные:
        имена_регионов = dict((rid, name) for rid, name in (await db.execute(
            select(Region.id, Region.name)
            .where(Region.company_id == company_id))).all())
        найдены = (await db.execute(select(ServiceLocation).where(
            ServiceLocation.company_id == company_id,
            ServiceLocation.id.in_(безымянные)))).scalars().all()
        по_id = {str(l.id): l for l in найдены}
        for loc_id in безымянные:
            l = по_id.get(loc_id)
            рег = None if l is None else (
                имена_регионов.get(l.region_id)
                or ((l.extra_metadata or {}).get("federalSubject") if l.extra_metadata else None))
            # Станции нет в реестре, она партнёрская или из другого региона —
            # строке в этом списке не место.
            if loc_id not in парк or l is None or not обслуживаем(l.owner) or not region_matches(рег, region):
                строки.pop(loc_id, None)
                continue
            s = строки[loc_id]
            s["name"] = l.name
            s["number"] = str((l.extra_metadata or {}).get("number") or "") or l.station_number
            s["code"] = l.code
            s["region"] = рег
            s["city"] = l.city

    # ── просрочена заявка ──
    # Отдельной строкой не заводим: станция уже в списке по своей беде, а срыв
    # срока — это про то, что заведённая работа не движется.
    for s in строки.values():
        if s["breachedTickets"]:
            s["reasons"].append({
                "kind": "breached",
                "label": f"срок заявки сорван ({s['breachedTickets']})",
                "note": s["lastTicketNumber"],
            })

    for loc_id, s in строки.items():
        if not s["visits"]:
            s["visits"] = трафик.get(loc_id, 0)
        s["visitsPerDay"] = round(s["visits"] / ОКНО_ОТКАЗОВ, 1) if s["visits"] else 0.0

    пробелы = {}
    for r in сроки["rows"]:
        if r["meter"]["state"] != "unknown" and r["service"]["state"] != "unknown":
            continue
        loc_id = r["locationId"]
        g = пробелы.setdefault(loc_id, {**парк[loc_id], "units": 0, "meterUnknown": 0, "serviceUnknown": 0})
        g["units"] += 1
        g["meterUnknown"] += r["meter"]["state"] == "unknown"
        g["serviceUnknown"] += r["service"]["state"] == "unknown"
    список = sorted(строки.values(), key=_вес)
    не_взяты = [s for s in список if not s["openTickets"]]

    return {
        "asOf": состояние.get("asOf"),
        "dataLagHours": состояние.get("dataLagHours"),
        "dataThrough": состояние.get("dataThrough"),
        "requestedDate": состояние.get("requestedDate"),
        "snapshotNote": состояние.get("snapshotNote"),
        "dataGaps": sorted(пробелы.values(), key=lambda r: -(r.get("sessions90d") or 0)),
        "threshold": порог,
        "totals": {
            "rows": len(список),
            "silent": sum(1 for s in список if any(r["kind"] == "silent" for r in s["reasons"])),
            "failing": sum(1 for s in список if any(r["kind"] == "failing" for r in s["reasons"])),
            "breached": sum(1 for s in список if s["breachedTickets"]),
            "meter": sum(1 for s in список if any(r["kind"] == "meter" for r in s["reasons"])),
            "service": sum(1 for s in список if any(r["kind"] == "service" for r in s["reasons"])),
            "check": sum(1 for s in список if any(r["kind"] == "check" for r in s["reasons"])),
            # Станции, у которых сроки не заполнены вовсе — хоть поверка, хоть
            # ТО. Считаем СТАНЦИИ, а не пропуски: сумма двух незаполненных полей
            # давала 1072 при 537 станциях и читалась как размер беды вдвое.
            "upkeepUnknown": len(пробелы),
            "notTaken": len(не_взяты) if open_work is not None and as_of is None else None,
            "lossPerMonth": round(sum(s["lossPerMonth"] for s in список), 2),
            # Деньги именно того, что никто не взял: это и есть цена
            # неорганизованности, а не поломок.
            "lossNotTaken": round(sum(s["lossPerMonth"] for s in не_взяты), 2) if open_work is not None and as_of is None else None,
            "clientsLost": sum(s["clientsLost"] for s in список),
        },
        "rows": список,
        "workKnown": open_work is not None and as_of is None,
        "note": (f"молчание дольше {МОЛЧИТ_ДНЕЙ} дней либо недобор с третьего дня, и доля приездов впустую от "
                 f"{порог} % за {ОКНО_ОТКАЗОВ} дней, плюс поверка счётчика, "
                 "просроченное ТО и нарушения осмотра; порядок — по деньгам, "
                 "затем по ушедшим клиентам, загруженности площадки и давности"),
    }
