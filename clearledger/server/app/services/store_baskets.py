"""Разбор корзины по сети: как покупают, а не сколько продали.

Экран «Продажи» отвечает на вопрос про товар, этот — про покупателя: что он
берёт за один подход, берёт ли что-то вообще и что с чем сочетает. Действия
отсюда другие: не «заказать больше», а «переложить полку», «поставить у кассы»,
«предложить вторую позицию».

Метрики и пороги — те же, что считает станция у себя
(`agent/internal/store/basket_analysis.go`). Центр и АЗС обязаны называть одну и
ту же корзину одинаково: иначе разговор о выкладке превращается в спор двух
методик. Разница только в масштабе — здесь добавлен разрез по станциям, ради
которого в центр и приходят.

Топливо здесь — не предмет учёта, а измерение покупателя (канон `edge/CLAUDE.md`,
пункт 7a: read-only метрики топлива для анализа поведения). На АЗС у человека уже
есть повод подойти к кассе, и первый вопрос эффективности магазина звучит так:
из заправившихся сколько дополнили заправку товаром, а сколько уехали ни с чем —
и различается ли это по марке и объёму залива. Дизель на сорок литров и десять
литров 95-го — разные люди с разной корзиной.

Связка контуров: товарный чек лежит в `store_cheques`, заправка — в
`fuel_transactions` (station_code, shift_number, receipt). Смешанный чек виден с
обеих сторон, поэтому:

* заправки берутся ТОЛЬКО по сменам, чеки которых уже приехали, — иначе
  знаменатель считает станции без агента и конверсия падает в пол (та же
  оговорка, что в `goods_dashboard._visits`);
* если топливный контур отстал, заправок в реестре меньше, чем смешанных чеков;
  тогда заправками считаем сами смешанные чеки — иначе прицеп уходит за 100 %;
* марка и литры известны там, где чек сошёлся с заправкой по номеру. Доля
  сошедшихся показывается прямо на экране: разрез по марке — это подсказка, а не
  бухгалтерия.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.store_documents import (cheque_lines_from_catalog,
                                          goods_only_cheque_totals,
                                          load_item_catalog)
from app.services.store_reports import _BUSINESS_TZ, _период

# Пара реже пяти чеков — совпадение, а не привычка покупателя. Порог тот же,
# что у станции: иначе одна и та же полка получает два разных совета.
МИН_ПАР = 5
# Сколько пар и позиций отдаём на экран. Дальше идёт хвост случайных сочетаний,
# который всё равно никто не читает.
ПРЕДЕЛ = 60
# Диапазоны залива — как на станции: объём говорит о машине, а через неё о том,
# кто за рулём и зачем заехал.
ЗАЛИВЫ = [("до 10 л", 0.0, 10.0), ("10–20 л", 10.0, 20.0),
          ("20–40 л", 20.0, 40.0), ("40 л и больше", 40.0, float("inf"))]


def _размер(позиций: int) -> int:
    """Корзины крупнее четырёх позиций считаем одной группой «четыре и больше»."""
    return 4 if позиций > 4 else позиций


def _подпись_размера(позиций: int) -> str:
    return {1: "одна позиция", 2: "две позиции",
            3: "три позиции"}.get(позиций, "четыре и больше")


def вывод(итоги: dict) -> str:
    """Что делать, словами. Пороги — из практики c-store, как на станции."""
    if not итоги["cheques"]:
        return "За период не было ни одного чека с товаром — считать нечего."
    if итоги["fuel_ops"] and итоги["attach_pct"] < 30:
        return ("Заправился — и уехал: товар берёт меньше трети заправляющихся. "
                "Это самый дешёвый резерв станции: человек уже стоит у кассы.")
    if итоги["single_pct"] > 55:
        return ("Больше половины товарных чеков — одна позиция. Вторая позиция в "
                "чеке даёт выручку без нового покупателя: работает выкладка у кассы "
                "и предложение кассира.")
    if итоги["depth"] > 2:
        return ("Корзина глубокая: в среднем больше двух позиций на чек. Дальше "
                "растить лучше ценой и составом ассортимента, а не глубиной.")
    return ("Корзина обычная для АЗС. Смотрите связки ниже: пара с высоким "
            "подъёмом — готовая подсказка для выкладки и предложения на кассе.")


async def _заправки(db: AsyncSession, cid, d1, d2,
                    stations: list[int] | None) -> list[dict]:
    """Заправки тех смен, чеки которых у нас есть: ключ, марка, литры, сумма.

    Одна заправка — это один топливный чек, а не строка реализации: за раз можно
    налить в два пистолета, и по строкам такой визит посчитался бы дважды.
    """
    p: dict = {"cid": str(cid), "d1": d1, "d2": d2}
    ф = ""
    if stations:
        ф = " AND station_id = ANY(:st)"
        p["st"] = stations
    return [dict(r) for r in (await db.execute(text(f"""
        WITH базис AS (
            SELECT DISTINCT station_id, shift_number
              FROM store_cheques
             WHERE company_id = :cid AND at BETWEEN :d1 AND :d2{ф}
        )
        SELECT f.station_code, f.shift_number, f.receipt,
               max(f.fuel_name) AS fuel_name,
               sum(f.liters) AS liters,
               sum(f.amount) AS amount
          FROM fuel_transactions f
          JOIN базис b ON b.station_id = f.station_code
                      AND b.shift_number = f.shift_number
         WHERE f.company_id = :cid
         GROUP BY f.station_code, f.shift_number, f.receipt
    """), p)).mappings().all()]


async def по_товару(db: AsyncSession, cid, date_from, date_to, товар: str,
                    stations: list[int] | None = None) -> dict:
    """«Взяли кофе — что ещё положат в корзину»: разбор вокруг одной позиции.

    Общая таблица связок отвечает на вопрос «какие пары вообще есть в сети», а
    этот разбор — на вопрос конкретной полки: с чем берут ИМЕННО эту позицию, в
    какие часы её берут и берут ли её вместе с заправкой. Из первого делают
    выкладку по сети, из второго — перестановку у кассы.
    """
    имя = (товар or "").strip()
    if not имя:
        return {"item": "", "cheques": 0, "neighbours": [], "hours": [], "share": 0.0}

    d1, d2 = _период(date_from, date_to)
    p: dict = {"cid": str(cid), "d1": d1, "d2": d2}
    ф = ""
    if stations:
        ф = " AND station_id = ANY(:st)"
        p["st"] = stations
    строки = (await db.execute(text(f"""
        SELECT station_id, at, had_fuel, lines
        FROM store_cheques
        WHERE company_id = :cid AND at BETWEEN :d1 AND :d2{ф}
          AND is_return = false
    """), p)).mappings().all()

    каталог = await load_item_catalog(db)
    всего_чеков = 0          # товарных чеков периода — знаменатель подъёма
    с_товаром = 0            # чеков, где есть наша позиция
    с_топливом = 0
    выручка = 0.0
    количество = 0.0
    часы = [0] * 24
    соседи: dict[str, dict] = {}
    поодиночке: dict[str, int] = defaultdict(int)

    for r in строки:
        товарные = goods_only_cheque_totals(
            cheque_lines_from_catalog(
                [l for l in (r["lines"] or []) if isinstance(l, dict)], каталог),
            bool(r["had_fuel"]), require_vat=False)["lines"]
        if not товарные:
            continue
        всего_чеков += 1
        имена = {str(l.get("name") or "").strip() for l in товарные}
        имена.discard("")
        for n in имена:
            поодиночке[n] += 1
        if имя not in имена:
            continue
        с_товаром += 1
        if r["had_fuel"]:
            с_топливом += 1
        часы[r["at"].astimezone(_BUSINESS_TZ).hour] += 1
        for l in товарные:
            if str(l.get("name") or "").strip() == имя:
                выручка += float(l.get("amount") or 0)
                количество += float(l.get("qty") or 0)
        for сосед in имена - {имя}:
            с = соседи.setdefault(сосед, {"name": сосед, "together": 0, "revenue": 0.0})
            с["together"] += 1
        for l in товарные:
            n = str(l.get("name") or "").strip()
            if n in соседи and n != имя:
                соседи[n]["revenue"] += float(l.get("amount") or 0)

    список = []
    for с in соседи.values():
        if с["together"] < МИН_ПАР:
            continue
        доля_в_чеках = с["together"] / с_товаром if с_товаром else 0
        ожидание = поодиночке[с["name"]] / всего_чеков if всего_чеков else 0
        список.append({
            "name": с["name"], "together": с["together"],
            "confidence": round(доля_в_чеках * 100, 1),
            "lift": round(доля_в_чеках / ожидание, 2) if ожидание else 0.0,
            "revenue": round(с["revenue"], 2),
        })
    список.sort(key=lambda с: (-с["lift"], -с["together"]))

    макс = max(часы) or 0
    return {
        "item": имя,
        "cheques": с_товаром,
        "share": round(с_товаром / всего_чеков * 100, 1) if всего_чеков else 0.0,
        "qty": round(количество, 3),
        "revenue": round(выручка, 2),
        "avg_price": round(выручка / количество, 2) if количество else 0.0,
        "with_fuel": с_топливом,
        "with_fuel_pct": round(с_топливом / с_товаром * 100, 1) if с_товаром else 0.0,
        "neighbours": список[:ПРЕДЕЛ],
        "hours": [{"hour": ч, "cheques": n,
                   "bar": round(n / макс * 100, 1) if макс else 0.0}
                  for ч, n in enumerate(часы)],
    }


async def analyze(db: AsyncSession, cid, date_from, date_to,
                  stations: list[int] | None = None) -> dict:
    """Корзина сети за период: итоги, топливо, размеры, часы, оплаты, связки."""
    d1, d2 = _период(date_from, date_to)
    p: dict = {"cid": str(cid), "d1": d1, "d2": d2}
    ф = ""
    if stations:
        ф = " AND station_id = ANY(:st)"
        p["st"] = stations

    # ponytail: разбор идёт в памяти одним проходом по выборке периода. Пары
    # товаров в SQL стоили бы самосоединения по JSONB, а экран смотрят за месяц
    # (208 — около тысячи чеков в неделю). Упрётся в объём — считать пары
    # запросом через jsonb_array_elements.
    строки = (await db.execute(text(f"""
        SELECT station_id, shift_number, number, at, is_return, had_fuel,
               pay_name, lines
        FROM store_cheques
        WHERE company_id = :cid AND at BETWEEN :d1 AND :d2{ф}
    """), p)).mappings().all()

    каталог = await load_item_catalog(db)

    итоги = {"cheques": 0, "positions": 0, "revenue": 0.0,
             "single": 0, "mixed": 0, "returns": 0, "returns_amount": 0.0}
    суммы: list[float] = []
    размеры: dict[int, dict] = {}
    часы: dict[int, dict] = {}
    оплаты: dict[str, dict] = {}
    по_станциям: dict[int, dict] = {}
    вместе: dict[tuple[str, str], int] = defaultdict(int)
    поодиночке: dict[str, int] = defaultdict(int)
    топ: dict[str, dict] = {}
    # Товарная часть смешанных чеков по ключу заправки — из неё считаются
    # разрезы по марке и объёму залива.
    товар_по_чеку: dict[tuple, dict] = {}

    for r in строки:
        разбор = goods_only_cheque_totals(
            cheque_lines_from_catalog(
                [l for l in (r["lines"] or []) if isinstance(l, dict)], каталог),
            bool(r["had_fuel"]), require_vat=False)
        товарные = разбор["lines"]
        if not товарные:
            continue
        сумма = float(разбор["amount"] or 0)

        if r["is_return"]:
            # Возврат — не покупка: в корзине он занизил бы и средний чек, и
            # глубину. Показываем его отдельной цифрой, а не растворяем в среднем.
            итоги["returns"] += 1
            итоги["returns_amount"] += сумма
            continue

        позиций = len(товарные)
        итоги["cheques"] += 1
        итоги["positions"] += позиций
        итоги["revenue"] += сумма
        суммы.append(сумма)
        if позиций == 1:
            итоги["single"] += 1
        if r["had_fuel"]:
            итоги["mixed"] += 1
            товар_по_чеку[(int(r["station_id"]), int(r["shift_number"] or 0),
                           int(r["number"] or 0))] = {"amount": сумма, "positions": позиций}

        группа = _размер(позиций)
        размер = размеры.setdefault(группа, {
            "positions": группа, "label": _подпись_размера(группа),
            "cheques": 0, "amount": 0.0})
        размер["cheques"] += 1
        размер["amount"] += сумма

        час = r["at"].astimezone(_BUSINESS_TZ).hour
        ч = часы.setdefault(час, {"hour": час, "cheques": 0, "positions": 0,
                                  "revenue": 0.0, "mixed": 0})
        ч["cheques"] += 1
        ч["positions"] += позиций
        ч["revenue"] += сумма
        if r["had_fuel"]:
            ч["mixed"] += 1

        способ = (r["pay_name"] or "").strip() or "не указан"
        о = оплаты.setdefault(способ, {"name": способ, "cheques": 0,
                                       "revenue": 0.0, "positions": 0})
        о["cheques"] += 1
        о["revenue"] += сумма
        о["positions"] += позиций

        код = int(r["station_id"])
        с = по_станциям.setdefault(код, {
            "station_id": код, "cheques": 0, "positions": 0, "revenue": 0.0,
            "single": 0, "mixed": 0, "fuel_ops": 0})
        с["cheques"] += 1
        с["positions"] += позиций
        с["revenue"] += сумма
        if позиций == 1:
            с["single"] += 1
        if r["had_fuel"]:
            с["mixed"] += 1

        # Пары считаем по РАЗНЫМ названиям в одном чеке: две пачки одного товара
        # — это количество, а не связка. Имя, а не UUID: карточка станции может
        # родиться черновиком без общего идентификатора, а на полке это тот же
        # товар.
        имена = sorted({str(l.get("name") or "").strip()
                        for l in товарные if str(l.get("name") or "").strip()})
        for имя in имена:
            поодиночке[имя] += 1
            т = топ.setdefault(имя, {"name": имя, "cheques": 0, "qty": 0.0,
                                     "revenue": 0.0})
            т["cheques"] += 1
        for l in товарные:
            имя = str(l.get("name") or "").strip()
            if имя in топ:
                топ[имя]["qty"] += float(l.get("qty") or 0)
                топ[имя]["revenue"] += float(l.get("amount") or 0)
        for i, а in enumerate(имена):
            for б in имена[i + 1:]:
                вместе[(а, б)] += 1

    # ── Топливо как измерение покупателя ───────────────────────────────────
    заправки = await _заправки(db, cid, d1, d2, stations)
    по_марке: dict[str, dict] = {}
    заливы = [{"label": имя, "from": от, "to": до, "ops": 0, "with_goods": 0,
               "liters": 0.0, "goods_revenue": 0.0} for имя, от, до in ЗАЛИВЫ]
    сошлось = 0
    for з in заправки:
        ключ = (int(з["station_code"]), int(з["shift_number"] or 0),
                int(з["receipt"] or 0))
        товар = товар_по_чеку.get(ключ)
        if товар:
            сошлось += 1
        литров = float(з["liters"] or 0)
        марка = (з["fuel_name"] or "").strip() or "марка не указана"
        м = по_марке.setdefault(марка, {"fuel": марка, "ops": 0, "with_goods": 0,
                                        "liters": 0.0, "fuel_amount": 0.0,
                                        "goods_revenue": 0.0})
        м["ops"] += 1
        м["liters"] += литров
        м["fuel_amount"] += float(з["amount"] or 0)
        if товар:
            м["with_goods"] += 1
            м["goods_revenue"] += товар["amount"]
        for д in заливы:
            if д["from"] < литров <= д["to"]:
                д["ops"] += 1
                д["liters"] += литров
                if товар:
                    д["with_goods"] += 1
                    д["goods_revenue"] += товар["amount"]
                break
        станция = по_станциям.get(int(з["station_code"]))
        if станция is not None:
            станция["fuel_ops"] += 1

    # Топливный контур приезжает позже чеков: если реализаций меньше, чем
    # смешанных чеков, заправками считаем сами смешанные чеки — иначе прицеп
    # уходит за 100 %. Та же поправка, что в обзоре сети.
    заправок = max(len(заправки), итоги["mixed"])
    литров = sum(float(з["liters"] or 0) for з in заправки)
    выручка_смешанных = sum(т["amount"] for т in товар_по_чеку.values())

    всего = итоги["cheques"]
    итоги["avg_check"] = round(итоги["revenue"] / всего, 2) if всего else 0.0
    итоги["median_check"] = round(median(суммы), 2) if суммы else 0.0
    итоги["depth"] = round(итоги["positions"] / всего, 2) if всего else 0.0
    итоги["single_pct"] = round(итоги["single"] / всего * 100, 1) if всего else 0.0
    итоги["fuel_ops"] = заправок
    итоги["fuel_only"] = max(заправок - итоги["mixed"], 0)
    итоги["attach_pct"] = round(итоги["mixed"] / заправок * 100, 1) if заправок else 0.0
    итоги["avg_fill"] = round(литров / len(заправки), 2) if заправки else 0.0
    итоги["goods_per_fill"] = round(выручка_смешанных / заправок, 2) if заправок else 0.0
    итоги["revenue"] = round(итоги["revenue"], 2)
    итоги["returns_amount"] = round(итоги["returns_amount"], 2)

    for размер in размеры.values():
        размер["share"] = round(размер["cheques"] / всего * 100, 1) if всего else 0.0
        размер["amount"] = round(размер["amount"], 2)
    макс_час = max((ч["cheques"] for ч in часы.values()), default=0)
    for ч in часы.values():
        ч["avg_check"] = round(ч["revenue"] / ч["cheques"], 2) if ч["cheques"] else 0.0
        ч["bar"] = round(ч["cheques"] / макс_час * 100, 1) if макс_час else 0.0
        ч["revenue"] = round(ч["revenue"], 2)
    for о in оплаты.values():
        о["avg_check"] = round(о["revenue"] / о["cheques"], 2) if о["cheques"] else 0.0
        о["share"] = round(о["cheques"] / всего * 100, 1) if всего else 0.0
        о["revenue"] = round(о["revenue"], 2)
    for с in по_станциям.values():
        n = с["cheques"]
        заправок_с = max(с["fuel_ops"], с["mixed"])
        с["avg_check"] = round(с["revenue"] / n, 2) if n else 0.0
        с["depth"] = round(с["positions"] / n, 2) if n else 0.0
        с["single_pct"] = round(с["single"] / n * 100, 1) if n else 0.0
        с["fuel_ops"] = заправок_с
        с["attach_pct"] = round(с["mixed"] / заправок_с * 100, 1) if заправок_с else 0.0
        с["revenue"] = round(с["revenue"], 2)
    for м in по_марке.values():
        м["attach_pct"] = round(м["with_goods"] / м["ops"] * 100, 1) if м["ops"] else 0.0
        м["avg_fill"] = round(м["liters"] / м["ops"], 2) if м["ops"] else 0.0
        # На заправку, а не на покупателя: знаменатель — все заправившиеся этой
        # маркой, включая уехавших ни с чем. Это и есть цена вопроса в деньгах.
        м["goods_per_fill"] = round(м["goods_revenue"] / м["ops"], 2) if м["ops"] else 0.0
        м["avg_goods_check"] = (round(м["goods_revenue"] / м["with_goods"], 2)
                                if м["with_goods"] else 0.0)
        м["liters"] = round(м["liters"], 1)
        м["fuel_amount"] = round(м["fuel_amount"], 2)
        м["goods_revenue"] = round(м["goods_revenue"], 2)
    for д in заливы:
        д["attach_pct"] = round(д["with_goods"] / д["ops"] * 100, 1) if д["ops"] else 0.0
        д["goods_per_fill"] = round(д["goods_revenue"] / д["ops"], 2) if д["ops"] else 0.0
        д["liters"] = round(д["liters"], 1)
        д["goods_revenue"] = round(д["goods_revenue"], 2)
        д.pop("from"), д.pop("to")

    связки = []
    for (а, б), n in вместе.items():
        if n < МИН_ПАР or not всего:
            continue
        поддержка = n / всего
        ожидание = (поодиночке[а] / всего) * (поодиночке[б] / всего)
        связки.append({
            "a": а, "b": б, "together": n,
            "support": round(поддержка * 100, 2),
            "confidence": round(n / поодиночке[а] * 100, 1) if поодиночке[а] else 0.0,
            "lift": round(поддержка / ожидание, 2) if ожидание else 0.0,
        })
    # Сверху — привычка покупателя, а не популярность: сортируем по подъёму, при
    # равном подъёме — по числу чеков.
    связки.sort(key=lambda с: (-с["lift"], -с["together"]))

    товары = sorted(топ.values(), key=lambda т: -т["cheques"])[:ПРЕДЕЛ]
    for т in товары:
        т["share"] = round(т["cheques"] / всего * 100, 1) if всего else 0.0
        т["revenue"] = round(т["revenue"], 2)
        т["qty"] = round(т["qty"], 3)

    return {
        "period": {"from": d1.date().isoformat(), "to": d2.date().isoformat()},
        "totals": итоги,
        "fuel": {
            # Сколько смешанных чеков сошлось с заправкой по номеру: разрезы по
            # марке и заливу опираются только на них, и молчать об этом нельзя.
            "ops": len(заправки),
            "matched": сошлось,
            "matched_pct": (round(сошлось / итоги["mixed"] * 100, 1)
                            if итоги["mixed"] else 0.0),
            "by_fuel": sorted(по_марке.values(), key=lambda м: -м["ops"]),
            "by_volume": [д for д in заливы if д["ops"]],
        },
        "sizes": sorted(размеры.values(), key=lambda р: р["positions"]),
        "hours": sorted(часы.values(), key=lambda ч: ч["hour"]),
        "payments": sorted(оплаты.values(), key=lambda о: -о["cheques"]),
        "stations": sorted(по_станциям.values(), key=lambda с: -с["revenue"]),
        "pairs": связки[:ПРЕДЕЛ],
        "pairs_total": len(связки),
        "top": товары,
        "verdict": вывод(итоги),
    }
