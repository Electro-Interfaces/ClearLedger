"""Состояние станции по чек-листу осмотра: что проверено, что просрочено, что нарушено.

Регламент — `station_checklist.py` (пункты и основания), отметки — `StationCheck`
(история осмотров). Здесь их соединяют в то, что видит инженер: по каждому пункту
последняя отметка, её возраст и вывод «надо ехать или нет».

Три состояния, которые важно различать:

  • **никогда не проверяли** — отметки нет вовсе. Для парка в 400 станций это
    основная масса на старте, и выдавать её за нарушение нечестно: мы не знаем,
    что там. Но и за «в порядке» выдавать нельзя — отсюда отдельное состояние;
  • **просрочено** — отметка есть, но старше срока пункта. Оклейку смотрят раз
    в полгода, разъёмы — раз в квартал, поверку счётчика — раз в год;
  • **нарушение** — инженер был и увидел беду. Такой пункт не гаснет по времени
    и остаётся красным, пока не появится новая отметка «в порядке».

Готовность станции считаем ДОЛЕЙ пунктов в порядке, а не средним баллом: «85 %
качества» ничего не говорит, а «14 из 18 пунктов в порядке, 3 не проверяли
никогда, по 1 нарушение» — говорит ровно то, из чего складывается выезд.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ServiceLocation, SourceFile, StationCheck
from app.services.station_checklist import (
    GROUPS, GROUP_LABELS, ITEM_BY_KEY, ITEMS, STATES,
)


def _вывод(отметка: StationCheck | None, дней_срок: int, сегодня: date) -> tuple[str, int | None]:
    """Состояние пункта и возраст последней отметки в днях."""
    if отметка is None:
        return "never", None
    возраст = (сегодня - отметка.checked_on).days
    if отметка.state == "fail":
        return "fail", возраст
    if отметка.state == "na":
        return "na", возраст
    return ("stale" if возраст > дней_срок else "ok"), возраст


async def station_check(
    db: AsyncSession, company_id: uuid.UUID, location_id: str,
) -> dict[str, Any]:
    """Чек-лист станции с последней отметкой по каждому пункту."""
    loc = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.id == location_id,
        ServiceLocation.company_id == company_id))).scalar_one_or_none()
    if loc is None:
        raise ValueError("Станция не найдена")

    # Вся история осмотров станции: пунктов два десятка, выездов немного —
    # выбирать последнюю отметку отдельным запросом на пункт незачем.
    строки = (await db.execute(
        select(StationCheck).where(
            StationCheck.company_id == company_id,
            StationCheck.location_id == location_id)
        .order_by(StationCheck.checked_on, StationCheck.created_at))).scalars().all()

    последняя: dict[str, StationCheck] = {}
    for r in строки:
        последняя[r.item_key] = r  # порядок по дате — остаётся самая свежая

    имена_файлов = {}
    файлы = [r.file_id for r in последняя.values() if r.file_id]
    if файлы:
        имена_файлов = {f.id: f.file_name for f in (await db.execute(
            select(SourceFile).where(SourceFile.id.in_(файлы)))).scalars().all()}

    сегодня = datetime.now(timezone.utc).date()
    пункты: list[dict[str, Any]] = []
    for i in ITEMS:
        о = последняя.get(i["key"])
        вывод, возраст = _вывод(о, i["days"], сегодня)
        пункты.append({
            **i,
            "group_label": GROUP_LABELS.get(i["group"], i["group"]),
            "verdict": вывод,
            "state": о.state if о else None,
            "stateLabel": STATES.get(о.state, о.state) if о else None,
            "checkedOn": о.checked_on.isoformat() if о else None,
            "ageDays": возраст,
            "note": о.note if о else None,
            "checkedBy": (о.checked_by_name if о else None),
            "fileId": str(о.file_id) if о and о.file_id else None,
            "fileName": имена_файлов.get(о.file_id) if о and о.file_id else None,
            # Пункт требует снимка, а снимка нет: отметка есть, но подтвердить
            # её нечем. Не нарушение, но и не закрытый пункт.
            "unconfirmed": bool(о and i["photo"] and not о.file_id and о.state == "ok"),
        })

    счёт = {k: sum(1 for p in пункты if p["verdict"] == k)
            for k in ("ok", "stale", "fail", "never", "na")}
    учитываем = len(ITEMS) - счёт["na"]
    даты = [p["checkedOn"] for p in пункты if p["checkedOn"]]

    return {
        "station": {"locationId": str(loc.id), "name": loc.name,
                    "number": loc.station_number,
                    "brand": loc.brand, "model": loc.model,
                    "serial": loc.serial_number},
        "totals": {
            **счёт,
            "items": len(ITEMS),
            "counted": учитываем,
            "okPct": round(100.0 * счёт["ok"] / учитываем, 1) if учитываем else 0.0,
            "unconfirmed": sum(1 for p in пункты if p["unconfirmed"]),
            "lastCheck": max(даты) if даты else None,
        },
        "groups": [{"code": g["code"], "label": g["label"],
                    "items": [p for p in пункты if p["group"] == g["code"]]}
                   for g in GROUPS],
        "note": ("пункты и основания — регламент осмотра сети; отметка хранится "
                 "историей, в карточке показана последняя по каждому пункту"),
    }


async def add_check(
    db: AsyncSession, company_id: uuid.UUID, location_id: str, *,
    item_key: str, state: str, note: str | None = None,
    checked_on: str | None = None, file_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None, user_name: str | None = None,
) -> dict[str, Any]:
    """Записать отметку осмотра. Прежние не трогаем — они история."""
    if item_key not in ITEM_BY_KEY:
        raise ValueError(f"Неизвестный пункт осмотра: {item_key}")
    if state not in STATES:
        raise ValueError(f"Неизвестное состояние: {state}")
    loc = (await db.execute(select(ServiceLocation.id).where(
        ServiceLocation.id == location_id,
        ServiceLocation.company_id == company_id))).scalar_one_or_none()
    if loc is None:
        raise ValueError("Станция не найдена")

    день = date.fromisoformat(checked_on) if checked_on else datetime.now(timezone.utc).date()
    if день > datetime.now(timezone.utc).date():
        raise ValueError("Осмотр не может быть датирован будущим")

    отметка = StationCheck(
        company_id=company_id, location_id=location_id, item_key=item_key,
        state=state, checked_on=день, note=(note or None), file_id=file_id,
        checked_by=user_id, checked_by_name=user_name)
    db.add(отметка)
    await db.flush()
    return {"id": str(отметка.id), "itemKey": item_key, "state": state,
            "checkedOn": день.isoformat()}


async def check_history(
    db: AsyncSession, company_id: uuid.UUID, location_id: str, *,
    item_key: str | None = None, limit: int = 100,
) -> list[dict[str, Any]]:
    """История осмотров станции — чем и отвечаем на «а когда было в порядке»."""
    q = select(StationCheck).where(
        StationCheck.company_id == company_id,
        StationCheck.location_id == location_id)
    if item_key:
        q = q.where(StationCheck.item_key == item_key)
    строки = (await db.execute(q.order_by(
        StationCheck.checked_on.desc(), StationCheck.created_at.desc())
        .limit(limit))).scalars().all()
    return [{
        "id": str(r.id), "itemKey": r.item_key,
        "itemLabel": ITEM_BY_KEY.get(r.item_key, {}).get("label", r.item_key),
        "state": r.state, "stateLabel": STATES.get(r.state, r.state),
        "checkedOn": r.checked_on.isoformat(), "note": r.note,
        "checkedBy": r.checked_by_name,
        "fileId": str(r.file_id) if r.file_id else None,
    } for r in строки]
