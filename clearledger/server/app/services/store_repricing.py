"""Массовая переоценка по сети: отбор → правило → предпросмотр → применение.

Станция умеет менять цены у себя (agent/internal/store/repricing.go). Центру
нужно то же самое, но в другом масштабе и с другим смыслом: не «поднять кофе на
своей АЗС», а «вывести табак по сети к наценке 12 %» — и увидеть, что при этом
случится на каждой станции отдельно.

Правила и ограничители те же, что у станции, слово в слово. Это не экономия
кода, а требование: если центр считает наценку иначе, чем АЗС, спор о цене
превращается в спор о методике, и договориться нельзя.

В политике v1 центр только считает предложение по каждой АЗС. Применение
заблокировано на уровне API: цену утверждает администратор станции. Поэтому
предпросмотр обязан считать и станционные карточки — иначе после назначения
всего ассортимента АЗС аналитический экран стал бы пустым.

Применение идёт двумя записями: цена в edge.price (история центра) и задание
станции nsi_delta (её локальная карточка). Одного мало — центр без станции даёт
цену, которой нет на кассе, станция без центра теряет историю.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EdgeDownlink
from app.services import store_costs
from app.services.store_reports import (_документы, _имя, _ключ_строки,
                                        _период, _строка)

# Причины, по которым правило не трогает позицию. Совпадают со станционными:
# один и тот же отказ обязан называться одинаково в центре и на АЗС.
НЕТ_ЦЕНЫ = "нет текущей цены"
НЕТ_СЕБЕС = "нет себестоимости"
БЕЗ_ИЗМЕНЕНИЙ = "цена не меняется"
ПОЛ_МАРЖИ = "ниже пола маржи"
ПОТОЛОК = "больше потолка шага"
KVI = "ключевая позиция — только вручную"

ЧТО_ДЕЛАТЬ = {
    НЕТ_ЦЕНЫ: "назначьте цену вручную — правилу не от чего считать",
    НЕТ_СЕБЕС: "закупочная цена появится после первой приёмки этой карточки",
    БЕЗ_ИЗМЕНЕНИЙ: "правило даёт ту же цену, что и сейчас",
    ПОЛ_МАРЖИ: "правило увело бы позицию в убыток — опустите пол или смените способ",
    ПОТОЛОК: "разовый скачок больше допустимого — поднимите потолок или сделайте в два захода",
    KVI: "по этим позициям покупатель судит об уровне цен; включите «трогать ключевые», если решение осознанное",
}


def округлить(цена: float, как: str) -> float:
    """Привести цену к принятому на полке виду."""
    if как == "0.1":
        return round(цена, 1)
    if как == "1":
        return float(round(цена))
    if как == "5":
        return float(round(цена / 5) * 5)
    if как in ("0.9", "0.99"):
        хвост = 0.9 if как == "0.9" else 0.99
        целых = int(цена)
        вниз, вверх = max(хвост, целых - 1 + хвост), целых + хвост
        return вверх if abs(цена - вверх) <= abs(цена - вниз) else вниз
    return round(цена, 2)


def _новая_цена(старая: float, себес: float, правило: dict) -> tuple[float, str]:
    """Цена по правилу и причина отказа (пустая строка — позиция едет)."""
    способ = правило.get("mode") or "процент"
    значение = float(правило.get("value") or 0)

    if способ in ("наценка", "маржа") and себес <= 0:
        return старая, НЕТ_СЕБЕС
    if способ not in ("наценка", "маржа", "цена") and старая <= 0:
        return старая, НЕТ_ЦЕНЫ

    if способ == "процент":
        цена = старая * (1 + значение / 100)
    elif способ == "рубли":
        цена = старая + значение
    elif способ == "наценка":
        цена = себес * (1 + значение / 100)
    elif способ == "маржа":
        if значение >= 100:
            return старая, "маржа 100 % недостижима"
        цена = себес / (1 - значение / 100)
    elif способ == "цена":
        цена = значение
    else:
        return старая, "правило не выбрано"

    if цена <= 0:
        return старая, "правило даёт нулевую цену"
    цена = округлить(цена, правило.get("round") or "")
    if abs(цена - старая) < 0.005:
        return старая, БЕЗ_ИЗМЕНЕНИЙ

    пол = float(правило.get("floor") or 0)
    if пол > 0 and себес > 0 and (цена - себес) / цена * 100 < пол:
        return старая, ПОЛ_МАРЖИ
    шаг = float(правило.get("step") or 0)
    if шаг > 0 and старая > 0 and abs(цена - старая) / старая * 100 > шаг + 0.001:
        return старая, ПОТОЛОК
    return цена, ""


async def _цены_станций(db: AsyncSession, stations: list[int] | None) -> dict[tuple, dict]:
    """(станция, uuid) → действующая цена и служебные поля карточки."""
    p: dict = {}
    ф = " AND p.station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    rows = (await db.execute(text(f"""
        SELECT p.station_id, p.price, p.item_id,
               i.external_uuid AS uuid, i.name, i.price_owner,
               g.path AS group_path
        FROM edge.price p
        JOIN edge.item i ON i.id = p.item_id
        LEFT JOIN edge.item_group g ON g.id = i.group_id
        WHERE p.valid_to IS NULL{ф}
    """), p)).mappings().all()
    return {(r["station_id"], str(r["uuid"])): dict(r) for r in rows}


async def _продажи(db: AsyncSession, cid, d1, d2, stations) -> dict[tuple, dict]:
    """(станция, uuid) → сколько продано и на сколько за период."""
    доки = await _документы(db, cid, d1, d2, ["retail_sale_sidegoods"], stations)
    свод: dict[tuple, dict] = {}
    for d in доки:
        for l in d["lines"] or []:
            uuid_ = _ключ_строки(l)
            if not uuid_:
                continue
            у = свод.setdefault((d["station_id"], uuid_), {"qty": 0.0, "revenue": 0.0})
            у["qty"] += _строка(l, "Количество", "qty")
            у["revenue"] += _строка(l, "Сумма", "amount")
    return свод


async def preview(db: AsyncSession, cid, правило: dict, отбор: dict,
                  stations: list[int] | None = None) -> dict:
    """Что станет с ценами сети. Ничего не меняет и не сохраняет."""
    d1, d2 = _период(отбор.get("date_from"), отбор.get("date_to"))
    цены = await _цены_станций(db, stations)
    продажи = await _продажи(db, cid, d1, d2, stations)
    себестоимости = {u: float(о["cost"])
                     for u, о in (await store_costs.ориентиры(db, cid, stations)).items()}

    # Класс A — позиции, которые делают выручку сети. По ним покупатель и судит
    # об уровне цен, поэтому правило их не двигает без явного разрешения.
    по_выручке = sorted(((k, v["revenue"]) for k, v in продажи.items()), key=lambda x: -x[1])
    всего_выручки = sum(v for _, v in по_выручке) or 1.0
    ключевые: set = set()
    накоплено = 0.0
    for ключ, выр in по_выручке:
        накоплено += выр
        ключевые.add(ключ)
        if накоплено / всего_выручки >= 0.8:
            break

    группа = (отбор.get("group") or "").strip()
    запрос = (отбор.get("q") or "").strip().lower()
    только_продаваемые = bool(отбор.get("sold"))
    трогать_kvi = bool(правило.get("kvi"))

    строки: list[dict] = []
    итог = {"selected": 0, "changed": 0, "rejected": 0,
            "effect": 0.0, "avg_growth": 0.0}
    причины: dict[str, int] = {}
    вес_роста = вес_выручки = 0.0

    for (sid, uuid_), c in цены.items():
        имя = c["name"] or ""
        путь = c["group_path"] or ""
        if группа and not путь.startswith(группа):
            continue
        if запрос and запрос not in имя.lower():
            continue
        прод = продажи.get((sid, uuid_), {"qty": 0.0, "revenue": 0.0})
        if только_продаваемые and прод["qty"] <= 0:
            continue
        итог["selected"] += 1

        старая = float(c["price"] or 0)
        себес = себестоимости.get(uuid_, 0.0)
        kvi = (sid, uuid_) in ключевые
        if kvi and not трогать_kvi:
            новая, отказ = старая, KVI
        else:
            новая, отказ = _новая_цена(старая, себес, правило)

        строка = {
            "station_id": sid, "item_uuid": uuid_, "name": имя, "group_path": путь,
            "price": round(старая, 2), "new_price": round(новая, 2),
            "cost": round(себес, 2), "qty": round(прод["qty"], 3),
            "revenue": round(прод["revenue"], 2), "kvi": kvi, "reject": отказ,
            "delta": round(новая - старая, 2),
            "delta_pct": round((новая - старая) / старая * 100, 2) if старая else 0.0,
            "margin": round((старая - себес) / старая * 100, 1) if старая and себес else None,
            "new_margin": round((новая - себес) / новая * 100, 1) if новая and себес else None,
            "effect": round((новая - старая) * прод["qty"], 2),
        }
        if отказ:
            итог["rejected"] += 1
            причины[отказ] = причины.get(отказ, 0) + 1
        else:
            итог["changed"] += 1
            итог["effect"] += строка["effect"]
            вес = max(прод["revenue"], 1.0)
            вес_роста += строка["delta_pct"] * вес
            вес_выручки += вес
        строки.append(строка)

    if вес_выручки:
        итог["avg_growth"] = round(вес_роста / вес_выручки, 2)
    итог["effect"] = round(итог["effect"], 2)
    строки.sort(key=lambda x: (x["reject"] != "", -abs(x["effect"])))

    по_станциям: dict[int, dict] = {}
    for r in строки:
        с = по_станциям.setdefault(r["station_id"], {
            "station_id": r["station_id"], "changed": 0, "rejected": 0, "effect": 0.0})
        if r["reject"]:
            с["rejected"] += 1
        else:
            с["changed"] += 1
            с["effect"] = round(с["effect"] + r["effect"], 2)

    return {
        "total": итог,
        "reasons": [{"reason": k, "count": v, "what": ЧТО_ДЕЛАТЬ.get(k, "")}
                    for k, v in sorted(причины.items(), key=lambda x: -x[1])],
        "by_station": sorted(по_станциям.values(), key=lambda x: x["station_id"]),
        "rows": строки,
        "shown": len(строки),
        "total_rows": len(строки),
    }


async def apply(db: AsyncSession, cid, правило: dict, отбор: dict, автор: str,
                stations: list[int] | None = None,
                только: list[str] | None = None) -> dict:
    """Применить правило: история цен центра + задания станциям.

    Пересчёт делается заново, а не берётся из присланной таблицы: цена могла
    уехать, пока человек смотрел предпросмотр, и в кассу должно уехать то, что
    верно сейчас.
    """
    расчёт = await preview(db, cid, правило, отбор, stations)
    отмечены = set(только or [])
    поедут = [r for r in расчёт["rows"]
              if not r["reject"] and (not отмечены or r["item_uuid"] in отмечены)]
    if not поедут:
        return {"applied": 0, "stations": 0,
                "note": "по этому правилу менять нечего — посмотрите причины отказов"}

    затронуто: set = set()
    for r in поедут:
        sid, uuid_ = r["station_id"], r["item_uuid"]
        карточка = (await db.execute(text("""
            SELECT i.id, i.external_uuid, i.name, i.unit, i.vat_rate, i.price_owner,
                   i.sku_class, i.marked, i.mark_group, i.adult_only, i.mrc,
                   i.brand, i.photo_url, i.deleted, g.path AS group_path,
                   coalesce(array_agg(b.barcode) FILTER (WHERE b.barcode IS NOT NULL), '{}') AS codes
            FROM edge.item i
            LEFT JOIN edge.item_group g ON g.id = i.group_id
            LEFT JOIN edge.barcode b ON b.item_id = i.id
            WHERE i.external_uuid = :u
            GROUP BY i.id, g.path
        """), {"u": uuid_})).mappings().first()
        if карточка is None:
            continue

        # История: прежняя запись закрывается, новая открывается. Перезаписью
        # цены на месте станция лишилась бы ответа на «почему было столько».
        await db.execute(text("""
            UPDATE edge.price SET valid_to = now()
            WHERE item_id = :id AND station_id = :s AND valid_to IS NULL
        """), {"id": карточка["id"], "s": sid})
        await db.execute(text("""
            INSERT INTO edge.price (item_id, station_id, price, valid_from, author)
            VALUES (:id, :s, :p, now(), :a)
        """), {"id": карточка["id"], "s": sid, "p": r["new_price"], "a": автор})

        db.add(EdgeDownlink(
            company_id=cid, station_id=sid, kind="nsi_delta",
            payload={"uuid": uuid_, "name": карточка["name"], "unit": карточка["unit"],
                     "vat_rate": карточка["vat_rate"], "deleted": bool(карточка["deleted"]),
                     "barcodes": list(карточка["codes"] or []),
                     "price": r["new_price"], "price_owner": карточка["price_owner"],
                     "group_path": карточка["group_path"], "sku_class": карточка["sku_class"],
                     "marked": bool(карточка["marked"]), "mark_group": карточка["mark_group"],
                     "adult_only": bool(карточка["adult_only"]),
                     "mrc": float(карточка["mrc"]) if карточка["mrc"] is not None else None,
                     "brand": карточка["brand"], "photo_url": карточка["photo_url"]},
            note=f"переоценка: {карточка['name'][:50]} {r['price']} → {r['new_price']}",
        ))
        затронуто.add(sid)

    await db.commit()
    return {"applied": len(поедут), "stations": len(затронуто),
            "effect": round(sum(r["effect"] for r in поедут), 2),
            "note": "цены записаны в историю центра и уехали заданиями на станции"}
