"""Корзина цен: копим изменения, применяем сразу или к нужному времени.

Между правилом и боевой ценой стоит черновик, и это не лишний шаг. Массовая
переоценка — самая опасная операция сети: одна опечатка в поле «процент»
переписывает весь прайс, а цена уезжает на кассы всех станций. Корзина даёт
остановиться и посмотреть глазами, отложенное применение — сменить цены к
открытию смены, а не посреди неё, когда у колонки стоит очередь.

Устройство повторяет станцию (`agent/internal/web/priceplan.go`): отбор → правило
→ предпросмотр → корзина → применение. Одинаковое действие обязано называться и
работать одинаково в обоих местах, иначе спор о цене превращается в спор о том,
чья кнопка что делает.

Применение — общий путь `store_repricing.записать_цену`: история центра плюс
задание станции. Запланированное исполняет фоновый воркер
(`store_price_scheduler`), а не открытый экран: «цена сменится завтра в шесть
утра» не должна зависеть от того, что кто-то в этот момент смотрит в браузер.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StorePricePlan
from app.services.store_repricing import записать_цену

АКТИВНЫЕ = ("draft", "scheduled")


def _строка(p: StorePricePlan) -> dict:
    старая = float(p.old_price) if p.old_price is not None else None
    новая = float(p.new_price)
    return {
        "id": str(p.id), "station_id": p.station_id, "item_uuid": p.item_uuid,
        "name": p.name, "price": старая, "new_price": новая,
        "delta": round(новая - старая, 2) if старая is not None else None,
        "delta_pct": (round((новая - старая) / старая * 100, 1)
                      if старая else None),
        "author": p.author, "reason": p.reason, "status": p.status,
        "effective_at": p.effective_at, "created_at": p.created_at,
        "applied_at": p.applied_at, "error": p.error,
    }


async def список(db: AsyncSession, cid, stations: list[int] | None = None,
                 limit: int = 500) -> dict:
    """Что лежит в корзине: черновики, запланированное и последние применённые."""
    условия = [StorePricePlan.company_id == cid]
    if stations:
        условия.append(StorePricePlan.station_id.in_(stations))
    строки = (await db.execute(
        select(StorePricePlan).where(*условия)
        .order_by(StorePricePlan.created_at.desc()).limit(limit)
    )).scalars().all()

    корзина = [_строка(p) for p in строки if p.status in АКТИВНЫЕ]
    история = [_строка(p) for p in строки if p.status not in АКТИВНЫЕ][:100]
    черновиков = sum(1 for p in корзина if p["status"] == "draft")
    запланировано = len(корзина) - черновиков
    # Эффект считаем только по тому, что реально поедет: отменённое и уже
    # применённое к решению «применять или нет» отношения не имеет.
    сдвиг = sum((с["delta"] or 0) for с in корзина)
    ближайшее = min((с["effective_at"] for с in корзина
                     if с["status"] == "scheduled" and с["effective_at"]), default=None)
    return {
        "rows": корзина, "history": история,
        "drafts": черновиков, "scheduled": запланировано,
        "stations": len({с["station_id"] for с in корзина}),
        "delta_sum": round(сдвиг, 2),
        "next_at": ближайшее,
    }


async def положить(db: AsyncSession, cid, строки: list[dict], автор: str,
                   reason: str = "") -> dict:
    """Положить рассчитанные строки в корзину. Рабочая цена не меняется.

    Повтор по той же позиции заменяет прежнюю строку: корзина отвечает на вопрос
    «что делаем сейчас», а не «что придумывали за день».
    """
    добавлено, обновлено = 0, 0
    for r in строки:
        станция, товар = int(r["station_id"]), str(r["item_uuid"])
        существующая = (await db.execute(select(StorePricePlan).where(
            StorePricePlan.company_id == cid,
            StorePricePlan.station_id == станция,
            StorePricePlan.item_uuid == товар,
            StorePricePlan.status.in_(АКТИВНЫЕ),
        ))).scalars().first()
        цена = float(r["new_price"])
        старая = r.get("price")
        if существующая is not None:
            существующая.new_price = цена
            существующая.old_price = старая
            существующая.name = r.get("name") or существующая.name
            существующая.author = автор
            существующая.reason = reason or существующая.reason
            существующая.status = "draft"
            существующая.effective_at = None
            обновлено += 1
            continue
        db.add(StorePricePlan(
            company_id=cid, station_id=станция, item_uuid=товар,
            name=(r.get("name") or "")[:300], old_price=старая, new_price=цена,
            author=автор, reason=reason[:300], status="draft"))
        добавлено += 1
    await db.commit()
    return {"added": добавлено, "updated": обновлено,
            "note": "изменения в корзине — рабочая цена не менялась"}


async def править(db: AsyncSession, cid, plan_id, цена: float, автор: str) -> dict:
    """Исправить цену строки прямо в корзине."""
    if цена < 0:
        raise ValueError("цена не может быть отрицательной")
    p = await db.get(StorePricePlan, _uuid.UUID(str(plan_id)))
    if p is None or p.company_id != cid:
        raise LookupError("строка корзины не найдена")
    if p.status not in АКТИВНЫЕ:
        raise ValueError("строка уже применена или отменена")
    p.new_price = цена
    p.author = автор
    await db.commit()
    return {"ok": True, "note": "исправленная цена сохранена в корзине"}


async def снять(db: AsyncSession, cid, plan_id) -> dict:
    """Убрать позицию из корзины или отменить запланированное до применения."""
    p = await db.get(StorePricePlan, _uuid.UUID(str(plan_id)))
    if p is None or p.company_id != cid:
        raise LookupError("строка корзины не найдена")
    if p.status not in АКТИВНЫЕ:
        raise ValueError("строка уже применена")
    p.status = "cancelled"
    await db.commit()
    return {"ok": True, "note": "позиция снята — рабочая цена не изменилась"}


def _когда(mode: str, delay: int | None, effective: str | None) -> datetime | None:
    """Во сколько применять: сейчас · через N минут · к указанному времени."""
    if mode == "delay":
        минут = int(delay or 0)
        if not 1 <= минут <= 24 * 60:
            raise ValueError("укажите интервал от одной минуты до суток")
        return datetime.now(timezone.utc) + timedelta(minutes=минут)
    if mode == "scheduled":
        if not effective:
            raise ValueError("укажите дату и время применения")
        когда = datetime.fromisoformat(effective)
        if когда.tzinfo is None:
            # Товаровед указывает местное «завтра 15:00», а не UTC. Пояс сети —
            # московский, как и вся отчётность.
            from app.services.store_reports import _BUSINESS_TZ
            когда = когда.replace(tzinfo=_BUSINESS_TZ)
        if когда <= datetime.now(timezone.utc):
            raise ValueError("указанное время уже прошло")
        return когда
    return None


async def применить(db: AsyncSession, cid, автор: str, *, mode: str = "now",
                    delay: int | None = None, effective: str | None = None,
                    только: list[str] | None = None) -> dict:
    """Применить корзину: сразу или отложенно.

    Отложенное не пишет цену — только проставляет время. Применит его воркер:
    иначе «сменить к открытию смены» работало бы, только пока открыт браузер.
    """
    когда = _когда(mode, delay, effective)
    отмечены = {str(x) for x in (только or [])}
    условия = [StorePricePlan.company_id == cid,
               StorePricePlan.status.in_(АКТИВНЫЕ)]
    строки = [p for p in (await db.execute(select(StorePricePlan).where(*условия))).scalars().all()
              if not отмечены or str(p.id) in отмечены]
    if not строки:
        return {"applied": 0, "scheduled": 0, "stations": 0,
                "note": "в корзине нечего применять"}

    if когда is not None:
        for p in строки:
            p.status = "scheduled"
            p.effective_at = когда
        await db.commit()
        return {"applied": 0, "scheduled": len(строки),
                "stations": len({p.station_id for p in строки}),
                "effective_at": когда,
                "note": "изменения запланированы: до указанного времени всё работает "
                        "по прежней цене"}

    применено = await исполнить(db, строки, cid, автор)
    return {"applied": применено["ok"], "scheduled": 0,
            "failed": применено["failed"],
            "stations": применено["stations"],
            "note": "цены записаны в историю центра и уехали заданиями на станции"}


async def исполнить(db: AsyncSession, строки: list[StorePricePlan], cid,
                    автор: str) -> dict:
    """Записать цены строк и закрыть их как применённые. Общая точка для воркера.

    Ошибка одной позиции не отменяет остальные: карточка могла уехать из
    справочника, пока план лежал в корзине, и это повод разобрать одну строку, а
    не потерять всю переоценку. Причина остаётся в самой строке.
    """
    ок, сбоев = 0, 0
    станции: set[int] = set()
    момент = datetime.now(timezone.utc)
    for p in строки:
        подпись = автор or p.author or "центр"
        причина = p.reason or "переоценка из корзины центра"
        записано = await записать_цену(
            db, cid, p.station_id, p.item_uuid, float(p.new_price), подпись,
            note=f"{(p.name or p.item_uuid)[:50]} → {float(p.new_price):.2f} · {причина}")
        if not записано:
            p.error = "карточки нет в справочнике сети — цена не записана"
            сбоев += 1
            continue
        p.status = "applied"
        p.applied_at = момент
        p.error = None
        станции.add(p.station_id)
        ок += 1
    await db.commit()
    return {"ok": ок, "failed": сбоев, "stations": len(станции)}


async def созревшие(db: AsyncSession, до: datetime | None = None
                    ) -> dict[_uuid.UUID, list[StorePricePlan]]:
    """Запланированные, чьё время пришло, по компаниям. Для воркера."""
    момент = до or datetime.now(timezone.utc)
    строки = (await db.execute(select(StorePricePlan).where(
        StorePricePlan.status == "scheduled",
        StorePricePlan.effective_at.isnot(None),
        StorePricePlan.effective_at <= момент,
    ).order_by(StorePricePlan.effective_at))).scalars().all()
    по_компаниям: dict[_uuid.UUID, list[StorePricePlan]] = {}
    for p in строки:
        по_компаниям.setdefault(p.company_id, []).append(p)
    return по_компаниям


async def очистить_историю(db: AsyncSession, cid, дней: int = 90) -> int:
    """Убрать применённые и отменённые старше указанного срока.

    Корзина — рабочий стол, а не архив: история цены живёт в `edge.price`, и
    держать здесь второй её экземпляр незачем.
    """
    res = await db.execute(text("""
        DELETE FROM store_price_plans
         WHERE company_id = :cid AND status IN ('applied','cancelled')
           AND created_at < now() - make_interval(days => :d)
    """), {"cid": str(cid), "d": int(дней)})
    await db.commit()
    return res.rowcount or 0
