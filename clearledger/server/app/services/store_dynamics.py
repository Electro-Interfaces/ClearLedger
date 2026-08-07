"""Динамика сети: что изменилось между периодами и за счёт чего.

Отчёты «Магазина» отвечают на «как сейчас». Этот сервис отвечает на другой
вопрос — «что изменилось», и он же самый частый на разборе месяца. «Маржа сети
упала на двести тысяч» само по себе не действие: упала от цен, от спроса, от
подорожавшей закупки, от того что одна станция стояла две недели, или просто
потому что перестали возить половину ассортимента.

Раскладка — стандартный для торговли мост price-volume-mix, тот же, что считает
станция у себя (agent/internal/store/compare.go). Это принципиально: центр и
станция обязаны объяснять одну и ту же разницу одинаково, иначе разговор
«у тебя в отчёте другое» съест весь смысл.

    Цена          (p₁ − p₀) × q₁
    Себестоимость −(c₁ − c₀) × q₁
    Объём         (q₁ − q₀) × (p₀ − c₀)
    Новинки       маржа₁ позиций, которых в прошлом периоде не продавали
    Выбывшие      −маржа₀ позиций, которые продавать перестали

Сумма пяти факторов равна разнице маржи. Если не сходится — ошибка в расчёте,
и это видно сразу, а не «примерно так».

Себестоимость центр знает не как факт станции, а как ориентир: последняя
закупка карточки ДО конца периода. Поэтому у периодов она разная — ровно тогда,
когда закупка действительно менялась.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import store_costs
from app.services.store_reports import (_документы, _имя, _ключ_строки,
                                        _период, _справочник, _строка)


async def _продажи(db: AsyncSession, cid, d1, d2,
                   stations: list[int] | None) -> dict[tuple, dict]:
    """Продажи периода, сведённые к (станция, карточка).

    Источник — документы продаж смены, как в отчёте `sales`: чеки покрывают
    только последние недели, и на них сравнение периодов врало бы «до августа
    не продавали».
    """
    доки = await _документы(db, cid, d1, d2, ["retail_sale_sidegoods"], stations)
    имена = await _справочник(db)
    свод: dict[tuple, dict] = {}
    for d in доки:
        for l in d["lines"] or []:
            uuid_ = _ключ_строки(l)
            ключ = (d["station_id"], uuid_ or _имя(l))
            у = свод.setdefault(ключ, {
                "station_id": d["station_id"], "item_uuid": uuid_,
                "name": имена.get(uuid_) or _имя(l), "qty": 0.0, "revenue": 0.0})
            у["qty"] += _строка(l, "Количество", "qty")
            у["revenue"] += _строка(l, "Сумма", "amount")
    return свод


async def _себестоимости(db: AsyncSession, cid, stations, на_дату) -> dict[str, float]:
    """UUID → закупочная цена единицы, известная на указанный момент."""
    оценки = await store_costs.ориентиры(db, cid, stations, на_дату=на_дату)
    return {u: float(о["cost"]) for u, о in оценки.items()}


async def compare(db: AsyncSession, cid, date_from, date_to,
                  stations: list[int] | None = None) -> dict:
    """Текущий период против равного предыдущего с раскладкой изменения маржи."""
    d1, d2 = _период(date_from, date_to)
    длина = d2 - d1
    п1, п2 = d1 - длина - timedelta(microseconds=1), d1 - timedelta(microseconds=1)

    сейчас = await _продажи(db, cid, d1, d2, stations)
    раньше = await _продажи(db, cid, п1, п2, stations)
    цены_сейчас = await _себестоимости(db, cid, stations, d2)
    цены_раньше = await _себестоимости(db, cid, stations, п2)

    факторы = {"price": 0.0, "cost": 0.0, "volume": 0.0, "new": 0.0, "gone": 0.0}
    # Покрытие себестоимостью: какая доля выручки посчитана с известной закупкой.
    # Без этой цифры сравнение врёт в самом опасном месте: там, где закупку
    # узнали только в новом периоде, маржа прошлого выглядит завышенной, и
    # «маржа упала» читается как провал торговли, а не как появление данных.
    покрытие = {"now": [0.0, 0.0], "prev": [0.0, 0.0]}  # [с себестоимостью, всего]
    вклады: list[dict] = []
    по_станциям: dict[int, dict] = {}

    def станция(sid: int) -> dict:
        return по_станциям.setdefault(sid, {
            "station_id": sid, "revenue": 0.0, "revenue_prev": 0.0,
            "margin": 0.0, "margin_prev": 0.0})

    for ключ, r in сейчас.items():
        sid, uuid_ = ключ[0], r["item_uuid"]
        c1 = цены_сейчас.get(uuid_, 0.0)
        q1, v1 = r["qty"], r["revenue"]
        p1 = v1 / q1 if q1 else 0.0
        м1 = v1 - c1 * q1
        с = станция(sid)
        с["revenue"] += v1
        с["margin"] += м1
        покрытие["now"][1] += v1
        if c1 > 0:
            покрытие["now"][0] += v1

        было = раньше.get(ключ)
        строка = {"station_id": sid, "item_uuid": uuid_, "name": r["name"],
                  "qty": round(q1, 3), "qty_prev": 0.0,
                  "revenue": round(v1, 2), "revenue_prev": 0.0,
                  "margin": round(м1, 2), "margin_prev": 0.0,
                  "price": round(p1, 2), "price_prev": 0.0, "fate": "новинка"}
        if not было:
            факторы["new"] += м1
            строка["delta_margin"] = round(м1, 2)
            вклады.append(строка)
            continue

        c0 = цены_раньше.get(uuid_, c1)
        q0, v0 = было["qty"], было["revenue"]
        p0 = v0 / q0 if q0 else 0.0
        м0 = v0 - c0 * q0
        с["revenue_prev"] += v0
        с["margin_prev"] += м0
        покрытие["prev"][1] += v0
        if c0 > 0:
            покрытие["prev"][0] += v0

        факторы["price"] += (p1 - p0) * q1
        факторы["cost"] += -(c1 - c0) * q1
        факторы["volume"] += (q1 - q0) * (p0 - c0)
        строка.update({"qty_prev": round(q0, 3), "revenue_prev": round(v0, 2),
                       "margin_prev": round(м0, 2), "price_prev": round(p0, 2),
                       "fate": "", "delta_margin": round(м1 - м0, 2)})
        вклады.append(строка)

    for ключ, было in раньше.items():
        if ключ in сейчас:
            continue
        sid, uuid_ = ключ[0], было["item_uuid"]
        # Если закупки до конца прошлого периода не было, берём нынешнюю оценку:
        # ноль здесь означал бы «товар достался даром», и маржа выбывшей позиции
        # раздувалась до всей её выручки — фактор «выбывшие» уходил в минус на
        # сумму, которой не было.
        c0 = цены_раньше.get(uuid_) or цены_сейчас.get(uuid_, 0.0)
        q0, v0 = было["qty"], было["revenue"]
        м0 = v0 - c0 * q0
        факторы["gone"] += -м0
        с = станция(sid)
        с["revenue_prev"] += v0
        с["margin_prev"] += м0
        покрытие["prev"][1] += v0
        if c0 > 0:
            покрытие["prev"][0] += v0
        вклады.append({"station_id": sid, "item_uuid": uuid_, "name": было["name"],
                       "qty": 0.0, "qty_prev": round(q0, 3),
                       "revenue": 0.0, "revenue_prev": round(v0, 2),
                       "margin": 0.0, "margin_prev": round(м0, 2),
                       "price": 0.0, "price_prev": round(v0 / q0, 2) if q0 else 0.0,
                       "fate": "выбыла", "delta_margin": round(-м0, 2)})

    вклады.sort(key=lambda x: -abs(x["delta_margin"]))
    итог = {
        "revenue": round(sum(с["revenue"] for с in по_станциям.values()), 2),
        "revenue_prev": round(sum(с["revenue_prev"] for с in по_станциям.values()), 2),
        "margin": round(sum(с["margin"] for с in по_станциям.values()), 2),
        "margin_prev": round(sum(с["margin_prev"] for с in по_станциям.values()), 2),
    }
    итог["delta_revenue"] = round(итог["revenue"] - итог["revenue_prev"], 2)
    итог["delta_margin"] = round(итог["margin"] - итог["margin_prev"], 2)
    итог["margin_pct"] = round(итог["margin"] / итог["revenue"] * 100, 2) if итог["revenue"] else 0.0
    итог["margin_pct_prev"] = (round(итог["margin_prev"] / итог["revenue_prev"] * 100, 2)
                               if итог["revenue_prev"] else 0.0)
    доля = lambda пара: round(пара[0] / пара[1] * 100, 1) if пара[1] else 0.0
    итог["cost_known_pct"] = доля(покрытие["now"])
    итог["cost_known_pct_prev"] = доля(покрытие["prev"])

    for с in по_станциям.values():
        for k in ("revenue", "revenue_prev", "margin", "margin_prev"):
            с[k] = round(с[k], 2)
        с["delta_margin"] = round(с["margin"] - с["margin_prev"], 2)
        с["delta_revenue"] = round(с["revenue"] - с["revenue_prev"], 2)

    return {
        "period": {"from": d1.date().isoformat(), "to": d2.date().isoformat()},
        "period_prev": {"from": п1.date().isoformat(), "to": п2.date().isoformat()},
        "total": итог,
        "factors": {k: round(v, 2) for k, v in факторы.items()},
        "factors_sum": round(sum(факторы.values()), 2),
        "by_station": sorted(по_станциям.values(), key=lambda x: x["station_id"]),
        "up": [в for в in вклады if в["delta_margin"] > 0][:20],
        "down": [в for в in вклады if в["delta_margin"] < 0][:20],
        "has_prev": bool(раньше),
    }


async def price_log(db: AsyncSession, cid, date_from, date_to,
                    stations: list[int] | None = None) -> dict:
    """Журнал цен сети: кто и когда двигал цену, было → стало.

    История лежит в `edge.price`: приёмник закрывает прежнюю запись и заводит
    новую, поэтому «было» — это цена, действовавшая до момента записи.
    """
    d1, d2 = _период(date_from, date_to)
    # Компания в edge.item не хранится: справочник номенклатуры общий, а
    # принадлежность даёт станция. Поэтому отбор идёт по станциям компании.
    p = {"d1": d1, "d2": d2}
    ф = " AND p.station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    rows = (await db.execute(text(f"""
        SELECT p.station_id, p.price, p.valid_from, p.author,
               i.name, i.external_uuid AS item_uuid,
               lag(p.price) OVER (PARTITION BY p.item_id, p.station_id
                                  ORDER BY p.valid_from) AS price_prev
        FROM edge.price p
        JOIN edge.item i ON i.id = p.item_id
        WHERE p.valid_from BETWEEN :d1 AND :d2{ф}
        ORDER BY p.valid_from DESC
        LIMIT 500
    """), p)).mappings().all()
    строки = []
    for r in rows:
        было = float(r["price_prev"]) if r["price_prev"] is not None else None
        стало = float(r["price"] or 0)
        строки.append({
            "station_id": r["station_id"], "name": r["name"],
            "item_uuid": str(r["item_uuid"] or ""),
            "at": r["valid_from"].isoformat() if r["valid_from"] else None,
            "author": r["author"] or "",
            "price_prev": было, "price": стало,
            "delta": round(стало - было, 2) if было is not None else None,
            "delta_pct": round((стало - было) / было * 100, 2) if было else None,
        })
    return {"rows": строки, "total": len(строки)}
