"""Заявки сети глазами эксплуатации: срез «Поддержки» в пространстве.

ЗАЧЕМ. Инженер живёт в пространстве, а заявки — в «Поддержке». Вопрос «что
сейчас с работами по сети, где сорваны сроки, чьё железо чаще ломается» он задаёт
из своего рабочего места, и ходить за ним в другое приложение не станет. Копию
заявок в Ядре при этом держать нельзя: мастер хода работы один (docs/PROCESS.md),
поэтому разрез спрашивается в момент показа.

РАЗДЕЛЕНИЕ ТРУДА. «Поддержка» считает свои измерения: статус, вид работ, стадия
маршрута, источник, приоритет, сроки. Ядро добавляет то, чего у заявки нет и быть
не должно, — **марку станции, регион, владельца и её состояние**: это реестр
объектов, а не свойство заявки. Соединение идёт по `ecoObjectId`, той самой общей
оси объектов.

ЧЕСТНО О ПУСТОМ. На пилоте (20.09.2026) из 13 172 заявок 12 808 приехали из
HubEx — у них нет ни вида работ, ни стадии, ни исполнителя; собственных заявок с
маршрутом всего 364. Поля `origin_channel` у всех одно («web»), `responsibility`,
`dev_status` и `vendor_id` не заполнены вовсе. Поэтому разрезы «контакт-центр»,
«ответственность» и «программное обеспечение» не выдумываются: они появятся,
когда появятся данные, а пока экран показывает то, что есть, и говорит, чего нет.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Region, ServiceLocation
from app.services import space_projection
from app.services.station_owner import owner_canon
from app.services.station_scope import в_сети, обслуживаем
from app.services.ops_monitor_context import MSK, region_matches

# Статусы, при которых заявка считается живой. Список «Поддержки»; здесь он
# нужен для разрезов, которые Ядро считает само.
ОТКРЫТЫЕ = {"new", "open", "in_progress", "waiting_customer", "waiting_partner",
            "escalated", "handed_over", "ezs_survey", "ezs_hold"}

СТАТУСЫ: dict[str, str] = {
    "new": "Новая", "open": "Открыта", "in_progress": "В работе",
    "waiting_customer": "Ждём заказчика", "waiting_partner": "Ждём подрядчика",
    "escalated": "Эскалация", "handed_over": "Передана",
    "resolved": "Решена", "closed": "Закрыта", "cancelled": "Отменена",
    "ezs_survey": "Обследование", "ezs_hold": "Удержание", "ezs_rejected": "Отказ",
}

ВАЖНОСТЬ: dict[str, str] = {
    "low": "низкая", "medium": "обычная", "high": "высокая", "critical": "критичная",
}


def _разрез(строки: list[dict[str, Any]], ключ: str) -> list[dict[str, Any]]:
    """Свести строки по признаку: всего, открытых, со срывом срока."""
    счёт: dict[str, dict[str, int]] = defaultdict(
        lambda: {"count": 0, "open": 0, "breached": 0})
    for r in строки:
        k = r.get(ключ) or "— не указано"
        счёт[k]["count"] += 1
        if r.get("isOpen"):
            счёт[k]["open"] += 1
        if r.get("slaBreached"):
            счёт[k]["breached"] += 1
    return sorted(
        ({"key": k, **v} for k, v in счёт.items()),
        key=lambda x: -x["count"])


def _итоги(строки: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводка списка: историю считаем по окну, работу — по всем открытым.

    Окно («за 90 дней») отвечает на вопрос «сколько пришло и как закрывали» —
    туда идут срывы срока, среднее время закрытия и помесячная динамика. Вопрос
    «что делать сейчас» окна не имеет: заявка, заведённая год назад и до сих пор
    открытая, — это работа сегодня. Пока оба вопроса считались по окну, экран
    «Заявки» показывал 1 открытую, а очередь «На сегодня» вела 78 по 30
    станциям, и человек видел противоречие (проверка 21.09.2026).
    """
    открыты = [r for r in строки if r["isOpen"]]
    в_окне = [r for r in строки if r["inWindow"]]
    часы = [(datetime.fromisoformat(r["closedAt"].replace("Z", "+00:00"))
             - datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))).total_seconds() / 3600
            for r in в_окне if r["closedAt"] and r["status"] != "cancelled"]
    return {
        "total": len(строки), "inWindow": len(в_окне), "open": len(открыты),
        # Открытые, заведённые ДО окна: та самая работа, которую экран прятал.
        "openBeforeWindow": sum(1 for r in открыты if not r["inWindow"]),
        "breached": sum(r["slaBreached"] for r in в_окне),
        "urgentOpen": sum(r["priority"] in ("high", "critical") for r in открыты),
        "staleOpen": sum((r["ageDays"] or 0) > 30 for r in открыты),
        "objects": len({r["locationId"] for r in строки}),
        # Станции с открытой работой — ровно то, что очередь считает «взятым».
        "openObjects": len({r["locationId"] for r in открыты if r["locationId"]}),
        "avgHours": round(sum(часы) / len(часы), 1) if часы else None,
    }


async def ops_tickets(
    db: AsyncSession, company_id: uuid.UUID, *,
    days: int = 90, limit: int = 2000, app_code: str = "support",
    region: str | None = None, as_of: date | None = None,
) -> dict[str, Any]:
    """Срез заявок с привязкой к реестру объектов."""

    # Реестр станций: марка, регион, владелец, состояние — по оси объекта.
    имена_регионов = dict((rid, name) for rid, name in (await db.execute(
        select(Region.id, Region.name).where(Region.company_id == company_id))).all())
    парк = {
        str(s.id): s for s in (await db.execute(select(ServiceLocation).where(
            ServiceLocation.company_id == company_id,
            *в_сети()))).scalars().all()
        if обслуживаем(s.owner)
    }
    станции = {
        oid: s for oid, s in парк.items()
        if region_matches(
            имена_регионов.get(s.region_id) or (s.extra_metadata or {}).get("federalSubject"), region)
    }

    сырьё = await space_projection.monitoring_tickets(
        db, company_id, object_ids=list(станции), days=days, as_of=as_of)
    сейчас = datetime.now(timezone.utc)

    def возраст(iso: str | None) -> int | None:
        """Сколько дней заявке. Считает сервер: в рендере время брать нельзя."""
        if not iso:
            return None
        try:
            d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        except ValueError:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return max(0, (сейчас - d).days)

    строки: list[dict[str, Any]] = []
    for r in сырьё.get("rows", []):
        oid = str(r.get("ecoObjectId") or "")
        s = станции.get(oid)
        рег = None
        if s is not None:
            рег = имена_регионов.get(s.region_id) or (
                (s.extra_metadata or {}).get("federalSubject") if s.extra_metadata else None)
        владелец, класс_владельца = owner_canon(s.owner if s else None)
        строки.append({
            "id": r.get("id"),
            "number": r.get("display_number") or r.get("number"),
            "title": r.get("title"),
            "status": r.get("status"),
            "isOpen": bool(r.get("is_open")),
            # Заявка попала в список по окну или потому, что открыта до сих пор.
            # Разделять обязательно: динамика месяцев и среднее время закрытия
            # считаются по окну, а работа — по всем открытым.
            "inWindow": bool(r.get("in_window", True)),
            # Подпись берём у «Поддержки» (имя стадии маршрута); свой словарь —
            # только запасной вариант для кодов, которых нет в справочнике.
            "statusLabel": (r.get("status_label")
                            or СТАТУСЫ.get(r.get("status") or "", r.get("status"))),
            "priority": r.get("priority"),
            "priorityLabel": ВАЖНОСТЬ.get(r.get("priority") or "", r.get("priority")),
            "kind": r.get("kind") or "— вид не указан",
            "stage": r.get("stage"),
            "source": r.get("source") or "— источник не указан",
            "createdAt": r.get("created_at"),
            "closedAt": r.get("closed_at") or r.get("resolved_at"),
            "ageDays": возраст(r.get("created_at")),
            "slaBreached": bool(r.get("sla_breached")),
            "assignee": r.get("assignee_name"),
            # ── из реестра объектов ──
            "locationId": oid or None,
            "station": s.name if s else None,
            "stationNumber": (str((s.extra_metadata or {}).get("number") or s.station_number or "") or None) if s else None,
            "brand": (s.brand or "").strip() if s and s.brand else "— марка не указана",
            "region": рег or "— регион не указан",
            "city": s.city if s else None,
            "ownerClass": класс_владельца,
            "owner": владелец,
            "stationStatus": (s.operational_status or "unknown") if s else None,
        })

    # Разрезы, которых у заявки нет: их считает Ядро по реестру.
    свои_разрезы = {
        "brand": _разрез(строки, "brand"),
        "region": _разрез(строки, "region"),
        "owner": _разрез(строки, "owner"),
        "station": _разрез([r for r in строки if r["station"]], "station")[:30],
    }

    # Чего в данных нет — говорим прямо, а не рисуем пустой разрез.
    пусто: list[str] = []
    без_станции = sum(1 for r in строки if not r["locationId"])
    if без_станции:
        # Главный пробел этого экрана: заявка висит на объекте «Поддержки»,
        # который никто не сопоставил с объектом пространства. Из-за него разрез
        # по маркам и регионам считается лишь по части заявок — и молча.
        пусто.append(
            f"у {без_станции} заявок из {len(строки)} станции нет: они заведены на "
            "карточки подразделений («ПО РусГидро», «АО ЭЗС РусГидро») либо на "
            "объекты, оставшиеся без связи с реестром — по ним разрез по марке и "
            "региону не считается")
    источники = {r["source"] for r in строки}
    if источники <= {"web", "— источник не указан"}:
        пусто.append("обращения контакт-центра не различаются: у всех заявок "
                     "источник «web»")
    if all(r["kind"] == "— вид не указан" for r in строки[:200]):
        пусто.append("вид работ не проставлен у заявок из внешней системы")
    if not any(r["assignee"] for r in строки):
        пусто.append("исполнитель в заявках не заполнен")

    в_окне = [r for r in строки if r["inWindow"]]
    for key, field in [("status", "statusLabel"), ("kind", "kind"), ("stage", "stage"),
                       ("source", "source"), ("priority", "priority")]:
        свои_разрезы[key] = _разрез(строки, field)
    месяцы = {}
    for r in в_окне:
        month = datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")).astimezone(MSK).strftime("%Y-%m")
        m = месяцы.setdefault(month, {"key": month, "count": 0, "closed": 0})
        m["count"] += 1
        m["closed"] += bool(r["closedAt"]) and r["status"] != "cancelled"
    свои_разрезы["month"] = sorted(месяцы.values(), key=lambda r: r["key"])
    # Работа, которой здесь не видно: свёртка «Поддержки» идёт по всем объектам,
    # а экран — только по обслуживаемому парку. Открытые заявки по выведенным из
    # эксплуатации и партнёрским станциям не попадают ни сюда, ни в очередь «На
    # сегодня» (там строки тоже из парка) — и висят годами. Молчать нельзя:
    # на пилоте это 29 станций и 67 заявок (21.09.2026).
    try:
        свёртка = await space_projection.network_open_tickets(db, company_id, app_code)
        вне = [o for o in свёртка.get("objects", []) or []
               if str(o.get("ecoObjectId")) not in парк]
        if вне:
            пусто.append(
                f"по {len(вне)} станциям вне обслуживаемого парка (выведенные из "
                f"эксплуатации и партнёрские) в «Поддержке» осталось "
                f"{sum(int(o.get('open') or 0) for o in вне)} открытых заявок — "
                "в показателях эксплуатации их нет")
    except space_projection.ProjectionError:
        pass

    coverage = сырьё.get("coverage", {})
    if coverage.get("unmapped"):
        пусто.append(f"{coverage['unmapped']} заявок среза не связаны с объектом пространства и не входят в показатели своего парка")
    return {
        "days": days,
        "asOf": сырьё["asOf"], "dataThrough": сейчас.isoformat(), "dataLagHours": None,
        "snapshotNote": "В срезе — заявки выбранного окна и ВСЕ открытые, включая заведённые раньше: открытая работа из окна не выпадает. Статусы заявок и состав парка — текущие. История статусов на день не восстановлена. Время чтения Поддержки не подтверждает свежесть внешней выгрузки.",
        "coverage": coverage,
        "totals": _итоги(строки),
        "by": свои_разрезы,
        "rows": строки, "shown": len(строки), "withoutStation": без_станции,
        "gaps": пусто,
        "note": "Только обслуживаемые ЭЗС. Окно задаёт историю (сколько пришло и как закрывали); открытые заявки показаны все, поэтому «Открыто сейчас» здесь совпадает с очередью «На сегодня». Итоги и разрезы посчитаны по полной выборке Поддержки, включая все страницы.",
    }


def demo() -> None:
    """Проверка деления «история по окну / работа по всем открытым»."""
    def з(**kw: Any) -> dict[str, Any]:
        строка = {"isOpen": False, "inWindow": True, "slaBreached": False,
                  "priority": "medium", "ageDays": 1, "locationId": "loc-1",
                  "status": "closed", "createdAt": "2026-09-01T00:00:00+00:00",
                  "closedAt": "2026-09-01T10:00:00+00:00"}
        строка.update(kw)
        return строка

    t = _итоги([
        з(),                                                    # закрыта в окне
        з(isOpen=True, status="new", closedAt=None, ageDays=40),  # открыта в окне
        з(isOpen=True, inWindow=False, status="open", closedAt=None,
          ageDays=400, priority="high", locationId="loc-2"),    # открыта до окна
        з(inWindow=False, slaBreached=True, locationId="loc-3"),  # закрыта до окна
    ])
    assert t["total"] == 4 and t["inWindow"] == 2, t
    # Открытая с прошлого года — работа сегодня, а не история.
    assert t["open"] == 2 and t["openBeforeWindow"] == 1, t
    # Срыв срока у заявки вне окна в показатель окна не попадает.
    assert t["breached"] == 0, t
    assert t["urgentOpen"] == 1 and t["staleOpen"] == 2, t
    # Среднее время закрытия — только по окну: 10 часов одной закрытой заявки.
    assert t["avgHours"] == 10.0, t
    assert t["objects"] == 3 and t["openObjects"] == 2, t
    print("· ops_tickets: окно считает историю, открытые — работу")


if __name__ == "__main__":
    demo()
