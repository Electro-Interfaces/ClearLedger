"""Цены, продиктованные маркой: где наша цена отстала от того, что на пачке.

У маркированного табака цену задаёт не справочник, а сама пачка: МРЦ напечатана
на ней, касса читает её из кода и пробивает по ней — продать дороже нельзя,
дешевле незачем. Партия с новой МРЦ приезжает без предупреждения, и наша цена
отстаёт: торговле это не мешает, но выручка и себестоимость по таким позициям
считаются по старой цене, то есть занижаются.

Станция видит это по своей АЗС (`agent/internal/web/price_mrc.go`), центр — по
сети сразу: подорожание приходит ко всем точкам одной волной, и разбирать его по
одной станции значит делать одну работу пять раз. Признак «объясняется маркой» и
формула недоучёта — те же, что на станции: одно расхождение обязано называться
одинаково в обоих местах.

Промежуточного черновика здесь нет намеренно: цена уже действует на полке, мы её
не назначаем, а догоняем учётом. Приём цены пишется тем же путём, что и массовая
переоценка (`store_repricing.записать_цену`) — история центра плюс задание вниз.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.store_repricing import записать_цену
from app.services.store_reports import _период

# Допуск сравнения цен: копейка. Меньше — уже дробь округления, а не разница.
ДОПУСК = 0.005


def _близко(a: float, b: float) -> bool:
    return abs(a - b) < ДОПУСК


async def rows(db: AsyncSession, cid, date_from, date_to,
               stations: list[int] | None = None) -> dict:
    """Маркированные позиции, проданные дороже нашей цены, по каждой АЗС.

    Цена продажи берётся из чеков (сумма строки на количество) — это то, по чему
    покупатель действительно заплатил. Максимум за период, а не среднее: в одной
    партии пачка одна, а продажи по прежней МРЦ размыли бы новую цену.
    """
    d1, d2 = _период(date_from, date_to)
    p: dict = {"cid": str(cid), "d1": d1, "d2": d2}
    ф = ""
    if stations:
        ф = " AND c.station_id = ANY(:st)"
        p["st"] = stations

    факты = (await db.execute(text(f"""
        SELECT c.station_id,
               поз->>'item_uuid' AS item_uuid,
               max(поз->>'name') AS name,
               max(round(((поз->>'amount')::numeric) / NULLIF((поз->>'qty')::numeric, 0), 2))
                   AS cash_price,
               sum((поз->>'qty')::numeric) AS qty,
               sum((поз->>'amount')::numeric) AS amount,
               max(c.at) AS last_at
          FROM store_cheques c,
               LATERAL jsonb_array_elements(c.lines) AS поз
         WHERE c.company_id = :cid AND c.at BETWEEN :d1 AND :d2{ф}
           AND c.is_return = false
           AND (поз->>'qty')::numeric > 0
           AND coalesce(поз->>'item_uuid', '') <> ''
         GROUP BY c.station_id, поз->>'item_uuid'
    """), p)).mappings().all()
    if not факты:
        return {"period": {"from": d1.date().isoformat(), "to": d2.date().isoformat()},
                "rows": [], "by_mark": 0, "other": 0,
                "loss_mark": 0.0, "loss_other": 0.0, "by_station": []}

    карточки = {str(r["uuid"]): r for r in (await db.execute(text("""
        SELECT i.external_uuid AS uuid, i.name, i.mrc, i.marked, i.price_owner,
               (SELECT b.code FROM edge.barcode b
                 WHERE b.item_id = i.id AND b.status = 'active'
                 ORDER BY b.code LIMIT 1) AS barcode
          FROM edge.item i
         WHERE i.marked = true
    """))).mappings().all()}
    if not карточки:
        return {"period": {"from": d1.date().isoformat(), "to": d2.date().isoformat()},
                "rows": [], "by_mark": 0, "other": 0,
                "loss_mark": 0.0, "loss_other": 0.0, "by_station": [],
                "note": "в справочнике сети нет ни одной маркированной карточки"}

    цены = {(r["station_id"], str(r["uuid"])): float(r["price"] or 0)
            for r in (await db.execute(text("""
                SELECT p.station_id, p.price, i.external_uuid AS uuid
                  FROM edge.price p
                  JOIN edge.item i ON i.id = p.item_id
                 WHERE p.valid_to IS NULL AND i.marked = true
            """))).mappings().all()}

    строки: list[dict] = []
    по_станциям: dict[int, dict] = {}
    for ф_строка in факты:
        uuid_ = str(ф_строка["item_uuid"])
        карточка = карточки.get(uuid_)
        if карточка is None:               # немаркированный товар нас здесь не интересует
            continue
        станция = int(ф_строка["station_id"])
        наша = цены.get((станция, uuid_), 0.0)
        касса = float(ф_строка["cash_price"] or 0)
        if наша <= 0 or касса - наша <= ДОПУСК:
            continue
        мрц = float(карточка["mrc"] or 0)
        # Те же два признака марки, что у станции: касса пробила ровно по МРЦ
        # карточки либо наша цена стоит ровно на прежней МРЦ.
        по_марке = мрц > 0 and (_близко(мрц, касса) or _близко(мрц, наша))
        продано = float(ф_строка["qty"] or 0)
        недоучёт = round((касса - наша) * продано, 2)
        строки.append({
            "station_id": станция, "item_uuid": uuid_,
            "name": карточка["name"] or ф_строка["name"] or "",
            "barcode": карточка["barcode"] or "",
            "price": round(наша, 2), "cash_price": round(касса, 2),
            "mrc": round(мрц, 2) if мрц else None,
            "qty": round(продано, 3), "amount": round(float(ф_строка["amount"] or 0), 2),
            "last_at": ф_строка["last_at"],
            "by_mark": по_марке,
            "price_owner": карточка["price_owner"],
            "loss": недоучёт,
        })
        с = по_станциям.setdefault(станция, {"station_id": станция, "rows": 0,
                                             "by_mark": 0, "loss": 0.0})
        с["rows"] += 1
        с["loss"] += недоучёт
        if по_марке:
            с["by_mark"] += 1

    строки.sort(key=lambda r: (not r["by_mark"], -r["loss"]))
    for с in по_станциям.values():
        с["loss"] = round(с["loss"], 2)
    марка = [r for r in строки if r["by_mark"]]
    прочие = [r for r in строки if not r["by_mark"]]
    return {
        "period": {"from": d1.date().isoformat(), "to": d2.date().isoformat()},
        "rows": строки,
        "by_mark": len(марка),
        "other": len(прочие),
        "loss_mark": round(sum(r["loss"] for r in марка), 2),
        "loss_other": round(sum(r["loss"] for r in прочие), 2),
        "by_station": sorted(по_станциям.values(), key=lambda с: -с["loss"]),
    }


async def accept(db: AsyncSession, cid, автор: str, date_from, date_to,
                 stations: list[int] | None = None,
                 только: list[str] | None = None) -> dict:
    """Принять цену марки: наша цена догоняет ту, по которой пробила касса.

    Принимаются только строки, объяснённые маркой. Остальные расхождения цены
    разбираются по позиции: списывать их на марку нельзя — за ними может стоять
    что угодно, от ошибки кассира до чужого штрихкода.

    Ключ выбора — «станция:карточка»: одна и та же пачка на двух АЗС может
    отставать по-разному, и принять цену на одной, не тронув вторую, — обычное
    дело. Пустой выбор означает «все объяснённые маркой».
    """
    расчёт = await rows(db, cid, date_from, date_to, stations)
    отмечены = set(только or [])
    поедут = [r for r in расчёт["rows"] if r["by_mark"]
              and (not отмечены or f"{r['station_id']}:{r['item_uuid']}" in отмечены)]
    if not поедут:
        return {"accepted": 0, "stations": 0,
                "note": "принимать нечего: расхождений, объяснённых маркой, не осталось"}

    затронуто: set = set()
    принято = 0
    for r in поедут:
        причина = (f"цена по МРЦ марки: касса пробивала по {r['cash_price']:.2f} "
                   f"при нашей {r['price']:.2f}")
        if await записать_цену(db, cid, r["station_id"], r["item_uuid"],
                               r["cash_price"], автор,
                               note=f"{r['name'][:50]} — {причина}"):
            затронуто.add(r["station_id"])
            принято += 1
    await db.commit()
    return {"accepted": принято, "stations": len(затронуто),
            "recovered": round(sum(r["loss"] for r in поедут), 2),
            "note": "цены записаны в историю центра и уехали заданиями на станции"}
