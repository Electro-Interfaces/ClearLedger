"""Визиты станции: как прошёл каждый приезд и почему он таким получился.

Визит — это один приезд одного клиента: он втыкает разъём, станция может не
схватить с первого раза, и человек пробует ещё. CPO пишет каждую попытку отдельной
строкой, поэтому «сессия» и «приезд» — разные вещи: у худших станций пилота на
один приезд приходится до шести втыканий.

Инженеру нужен не итог, а ход: во сколько приехал, сколько раз пробовал, на каком
коннекторе, чем кончилась каждая попытка, сколько энергии дала, сколько человек
провозился в сумме. По этому ряду видно, что именно происходит с железом:

- **все попытки пустые** — станция не отдаёт ток вовсе;
- **первые с ошибкой, последняя рабочая** — разъём или замок схватывается не сразу;
- **одна попытка, ошибка, и человек уехал** — отказ с первого раза, самый дорогой
  случай: клиент не стал разбираться;
- **энергия есть, но капли** — зарядка обрывается на старте.

Эти четыре случая теперь не только видны в ленте, но и посчитаны: блок `patterns`
раскладывает приезды по картинам, а `empty` показывает, как долго длились попытки
без энергии. Разница принципиальная — мгновенный обрыв (медиана ошибочной попытки
1,3 мин, 14 тыс. попыток короче минуты) означает, что станция не дошла до отпуска
тока: не схватился замок, не прошла авторизация, машина не договорилась по
рукопожатию. Долгая пустая попытка — другое: станция приняла машину, держала её и
тока не дала. Первое чинится на месте, второе — претензия производителю.

Процент качества по-прежнему не считаем: он прячет ровно то, ради чего инженер
сюда пришёл. Картина — это раскладка, а не одна цифра.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession, ServiceLocation

ОКНО_ДНЕЙ = 30
ПРЕДЕЛ_ВИЗИТОВ = 200


def _исход(result: str | None, энергия: float) -> str:
    """Короткое слово о попытке — то, что инженер читает глазами."""
    ошибка = "error" in (result or "").lower()
    if энергия > 0:
        return "зарядка с ошибкой" if ошибка else "зарядка"
    return "ошибка" if ошибка else "без энергии"


# Картины визита. Ключ → подпись и объяснение, что это значит для железа.
# Порядок — от благополучного к худшему: так их и показываем.
КАРТИНЫ: list[tuple[str, str, str]] = [
    ("ok", "Зарядился сразу",
     "одна попытка, ток пошёл — как и должно быть"),
    ("retry_same", "Схватилось не с первого раза",
     "тот же коннектор, но человеку пришлось втыкать снова: замок, "
     "рукопожатие или авторизация срабатывают через раз"),
    ("retry_other", "Помог другой коннектор",
     "на первом ток не пошёл, зарядился на соседнем — беда в конкретном разъёме"),
    ("left_after_tries", "Пробовал и уехал ни с чем",
     "несколько попыток подряд, энергии нет нигде: станция не отдаёт ток"),
    ("left_first", "Уехал после первой же неудачи",
     "самый дорогой случай: клиент не стал разбираться и просто уехал"),
]


def _картина(попытки: list[ChargeSession], удался: bool) -> str:
    """К какой картине относится приезд — по числу попыток и смене коннектора."""
    if удался:
        if len(попытки) == 1:
            return "ok"
        коннекторы = {str(s.connector_no or "") for s in попытки}
        return "retry_other" if len(коннекторы) > 1 else "retry_same"
    return "left_first" if len(попытки) == 1 else "left_after_tries"


async def station_visits(
    db: AsyncSession, company_id: uuid.UUID, location_id: str, *,
    days: int = ОКНО_ДНЕЙ,
    only_failed: bool = False,
    limit: int = ПРЕДЕЛ_ВИЗИТОВ,
) -> dict[str, Any]:
    """Приезды на станцию за окно, каждый — с попытками внутри."""
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

    сессии = (await db.execute(
        select(ChargeSession)
        .where(ChargeSession.company_id == company_id,
               ChargeSession.location_id == location_id,
               ChargeSession.started_at >= с_даты)
        .order_by(ChargeSession.started_at))).scalars().all()

    # Группируем по ключу визита. У старых строк его может не быть (ключи
    # проставляет пересчёт после загрузки) — такую попытку показываем отдельным
    # визитом, а не теряем: пропуск в ленте хуже одинокой строки.
    визиты: dict[str, list[ChargeSession]] = {}
    for s in сессии:
        ключ = s.visit_key or f"одиночная:{s.session_ext_id}"
        визиты.setdefault(ключ, []).append(s)

    собранные: list[dict[str, Any]] = []
    for ключ, попытки in визиты.items():
        попытки.sort(key=lambda s: (s.visit_seq or 0, s.started_at))
        первая, последняя = попытки[0], попытки[-1]
        энергия = sum(float(s.energy_kwh or 0) for s in попытки)
        деньги = sum(float(s.client_amount or s.amount or 0) for s in попытки)
        удался = any(float(s.energy_kwh or 0) > 0 for s in попытки)
        конец = последняя.finished_at or последняя.started_at
        # Сколько человек провозился: от первого втыкания до конца последней
        # попытки. Это и есть «время у станции», а не сумма длительностей.
        всего_минут = round((конец - первая.started_at).total_seconds() / 60, 1) if конец else None

        if only_failed and удался:
            continue

        собранные.append({
            "visitKey": ключ,
            "pattern": _картина(попытки, удался),
            "startedAt": первая.started_at.isoformat(),
            "endedAt": конец.isoformat() if конец else None,
            "minutesAtStation": всего_минут,
            "attempts": len(попытки),
            "charged": удался,
            "energyKwh": round(энергия, 2),
            "revenue": round(деньги, 2),
            "client": первая.user_id,
            "clientType": первая.user_type,
            "clientName": первая.client_name,
            "card": первая.rfid or первая.card_number,
            # Ход визита: по этим строкам инженер и читает, что было с железом.
            "steps": [{
                "seq": s.visit_seq or i + 1,
                "at": s.started_at.isoformat(),
                "minutes": float(s.duration_min) if s.duration_min is not None else None,
                "connector": s.connector_no,
                "connectorType": s.connector_type,
                "result": s.result,
                "outcome": _исход(s.result, float(s.energy_kwh or 0)),
                "energyKwh": round(float(s.energy_kwh or 0), 2),
                "amount": round(float(s.client_amount or s.amount or 0), 2),
                "tariff": float(s.tariff) if s.tariff is not None else None,
                "sessionId": s.session_ext_id,
            } for i, s in enumerate(попытки)],
        })

    собранные.sort(key=lambda v: v["startedAt"], reverse=True)
    всего_визитов = len(визиты)
    неудачных = sum(1 for v in собранные if not v["charged"]) if only_failed else sum(
        1 for ключ, п in визиты.items() if not any(float(s.energy_kwh or 0) > 0 for s in п))

    # ── что именно ломается: сводка по коннекторам ──
    по_коннекторам: dict[str, dict[str, Any]] = {}
    for s in сессии:
        имя = str(s.connector_no or "—")
        g = по_коннекторам.setdefault(имя, {
            "connector": имя, "type": s.connector_type,
            "attempts": 0, "failed": 0, "energyKwh": 0.0,
        })
        g["attempts"] += 1
        if "error" in (s.result or "").lower():
            g["failed"] += 1
        g["energyKwh"] += float(s.energy_kwh or 0)
    for g in по_коннекторам.values():
        g["failedPct"] = round(100.0 * g["failed"] / g["attempts"], 1) if g["attempts"] else 0.0
        g["energyKwh"] = round(g["energyKwh"], 1)

    # ── почему приходится пробовать снова ──
    # Считаем по ВСЕМ визитам окна, а не по показанным: `only_failed` режет
    # ленту, но раскладка должна остаться честной.
    счёт: dict[str, int] = {}
    for ключ, попытки in визиты.items():
        к = _картина(попытки, any(float(s.energy_kwh or 0) > 0 for s in попытки))
        счёт[к] = счёт.get(к, 0) + 1
    картины = [{
        "key": k, "label": подпись, "hint": пояснение,
        "visits": счёт.get(k, 0),
        "pct": round(100.0 * счёт.get(k, 0) / всего_визитов, 1) if всего_визитов else 0.0,
    } for k, подпись, пояснение in КАРТИНЫ]

    # Пустые попытки по длительности: мгновенные — станция не дошла до тока,
    # долгие — держала машину и тока не дала.
    пустые = [s for s in сессии if float(s.energy_kwh or 0) <= 0]
    мгновенных = sum(1 for s in пустые if float(s.duration_min or 0) < 1)
    затяжных = sum(1 for s in пустые if float(s.duration_min or 0) >= 5)

    return {
        "asOf": сейчас.isoformat(),
        "days": days,
        "station": {
            "locationId": str(loc.id),
            "name": loc.name,
            "number": str((loc.extra_metadata or {}).get("number") or "") or None,
            "status": loc.operational_status or "unknown",
        },
        "totals": {
            "visits": всего_визитов,
            "failed": неудачных,
            "failedPct": round(100.0 * неудачных / всего_визитов, 1) if всего_визитов else 0.0,
            "attempts": len(сессии),
            "attemptsPerVisit": round(len(сессии) / всего_визитов, 2) if всего_визитов else 0.0,
        },
        "patterns": картины,
        "empty": {
            "attempts": len(пустые),
            "instant": мгновенных,
            "stuck": затяжных,
            "hint": ("попытка короче минуты — станция не дошла до отпуска тока "
                     "(замок, авторизация, рукопожатие с машиной); попытка "
                     "дольше пяти минут без энергии — станция держала машину и "
                     "тока не дала"),
        },
        "connectors": sorted(по_коннекторам.values(), key=lambda g: -g["failedPct"]),
        "visits": собранные[:limit],
        "returned": min(len(собранные), limit),
        "note": ("визит — один приезд клиента; несколько попыток подряд входят в "
                 "него и показаны шагами. «Без энергии» — попытка завершилась "
                 "штатно, но ток не пошёл"),
    }
