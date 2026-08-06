"""Отчёты «Магазина» по сети станций.

На станции такой раздел уже есть: рабочее место агента считает всё по своему
локальному учёту и отдаёт CSV. Здесь те же вопросы, но заданные сети: не «что
на моей полке», а «что по всем АЗС, и чем одна отличается от другой».

Отсюда две особенности, которых у станции нет и быть не может:

1. Разрез по станциям. Любой отчёт умеет отвечать сводно и построчно по АЗС —
   иначе сеть выглядит как одна большая станция, и провал на одной точке
   растворяется в средних.
2. Единый источник. Часть данных приходит от агентов (остатки, документы,
   чеки), часть — из 1С, пока она ещё ведёт станции. Отчёт обязан говорить,
   откуда цифра, иначе сверять его будет не с чем.

CSV отдаётся с точкой с запятой и BOM: Excel открывает такой файл двойным
кликом и не ломает кириллицу — это единственный формат, который на станции и в
офисе открывают одинаково.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import store_costs


def csv_bytes(header: list[str], rows: list[list]) -> bytes:
    """Собрать CSV, который Excel откроет двойным кликом.

    Разделитель — точка с запятой (русская локаль Excel), кодировка UTF-8 с
    BOM. Числа с запятой в дробной части: без этого Excel читает 1234.5 как
    дату и молча портит отчёт.
    """
    буфер = io.StringIO()
    писатель = csv.writer(буфер, delimiter=";", lineterminator="\r\n")
    писатель.writerow(header)
    for r in rows:
        писатель.writerow([
            (f"{v:.2f}".replace(".", ",") if isinstance(v, float) else
             "" if v is None else str(v))
            for v in r
        ])
    return ("﻿" + буфер.getvalue()).encode("utf-8")


def _период(date_from: str | None, date_to: str | None) -> tuple[datetime, datetime]:
    d1 = date.fromisoformat(date_from) if date_from else date(2000, 1, 1)
    d2 = date.fromisoformat(date_to) if date_to else date.today()
    return (datetime.combine(d1, time.min, tzinfo=timezone.utc),
            datetime.combine(d2, time.max, tzinfo=timezone.utc))


async def documents(db: AsyncSession, cid, date_from, date_to,
                    stations: list[int] | None = None) -> dict:
    """Единый журнал документов сети: всё, чем двигался товар.

    Документы приходят из двух контуров сразу — станции и 1С, — и сводить их в
    одну строку нельзя: у них разные номера и разная природа. Поэтому источник
    стоит колонкой, а не прячется.
    """
    d1, d2 = _период(date_from, date_to)
    p = {"cid": cid, "d1": d1, "d2": d2}
    фильтр = ""
    if stations:
        p["st"] = stations
        фильтр = " AND p.station_id = ANY(:st)"

    станционные = [dict(r) for r in (await db.execute(text(f"""
        SELECT p.station_id, d->>'Тип' AS kind, d->>'Номер' AS number,
               coalesce((d->>'Дата')::timestamptz, p.received_at) AS doc_date,
               coalesce((d->>'СуммаДокумента')::numeric, 0) AS amount,
               coalesce(jsonb_array_length(d->'Товары'), 0) AS positions,
               'станция' AS source
        FROM edge_packets p,
             LATERAL jsonb_array_elements(coalesce(p.payload->'Документы','[]'::jsonb)) d
        WHERE p.company_id = :cid{фильтр}
          AND d->>'Тип' IN ('purchase','writeoff','transfer','inventory',
                            'return_supplier','return_sale','production_release','revaluation')
          AND coalesce((d->>'Дата')::timestamptz, p.received_at) BETWEEN :d1 AND :d2
    """), p)).mappings().all()]

    фильтр2 = " AND station_id = ANY(:st)" if stations else ""
    приёмки = [dict(r) for r in (await db.execute(text(f"""
        SELECT station_id, 'purchase' AS kind, number, doc_date,
               total_amount AS amount, jsonb_array_length(lines) AS positions,
               'реестр приёмок' AS source
        FROM store_receipts
        WHERE company_id = :cid{фильтр2} AND doc_date BETWEEN :d1 AND :d2
    """), p)).mappings().all()]

    ВИДЫ = {"purchase": "Приёмка", "writeoff": "Списание", "transfer": "Перемещение",
            "inventory": "Инвентаризация", "return_supplier": "Возврат поставщику",
            "return_sale": "Возврат покупателя", "production_release": "Производство",
            "revaluation": "Переоценка"}
    строки = []
    for r in станционные + приёмки:
        строки.append({
            "station_id": r["station_id"],
            "kind": r["kind"], "label": ВИДЫ.get(r["kind"], r["kind"]),
            "number": r["number"], "doc_date": r["doc_date"],
            "amount": float(r["amount"] or 0), "positions": int(r["positions"] or 0),
            "source": r["source"],
        })
    строки.sort(key=lambda x: x["doc_date"], reverse=True)

    по_видам: dict[str, dict] = {}
    по_станциям: dict[int, dict] = {}
    for s in строки:
        v = по_видам.setdefault(s["label"], {"label": s["label"], "docs": 0, "amount": 0.0})
        v["docs"] += 1
        v["amount"] += s["amount"]
        st = по_станциям.setdefault(s["station_id"], {"station_id": s["station_id"],
                                                      "docs": 0, "amount": 0.0})
        st["docs"] += 1
        st["amount"] += s["amount"]
    return {
        "rows": строки, "total": len(строки),
        "by_kind": sorted(по_видам.values(), key=lambda x: -x["docs"]),
        "by_station": sorted(по_станциям.values(), key=lambda x: x["station_id"]),
    }


async def purchase_diff(db: AsyncSession, cid, date_from, date_to,
                        stations: list[int] | None = None) -> dict:
    """Расхождения приёмки: где факт разошёлся с накладной поставщика.

    Это предмет разговора с поставщиком (акт ТОРГ-2), а не ошибка приёмщика:
    недовоз оплачивать не за что, перевоз — принять и оприходовать.
    """
    d1, d2 = _период(date_from, date_to)
    p = {"cid": cid, "d1": d1, "d2": d2}
    фильтр = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    rows = (await db.execute(text(f"""
        SELECT station_id, number, doc_date, supplier, lines
        FROM store_receipts
        WHERE company_id = :cid{фильтр} AND doc_date BETWEEN :d1 AND :d2
        ORDER BY doc_date DESC
    """), p)).mappings().all()

    строки, недовоз, перевоз = [], 0.0, 0.0
    for r in rows:
        for l in r["lines"] or []:
            заявлено = float(l.get("qty_expected") or 0)
            факт = float(l.get("qty_fact") or 0)
            if заявлено == 0 or abs(факт - заявлено) < 1e-6:
                continue
            разница = round(факт - заявлено, 3)
            цена = float(l.get("price") or 0)
            деньги = round(разница * цена, 2)
            if разница < 0:
                недовоз += -деньги
            else:
                перевоз += деньги
            строки.append({
                "station_id": r["station_id"], "number": r["number"],
                "doc_date": r["doc_date"], "supplier": r["supplier"],
                "name": l.get("name"), "expected": заявлено, "fact": факт,
                "diff": разница, "price": цена, "diff_amount": деньги,
            })
    return {"rows": строки, "total": len(строки),
            "shortfall": round(недовоз, 2), "surplus": round(перевоз, 2)}


async def vat_book(db: AsyncSession, cid, date_from, date_to,
                   stations: list[int] | None = None) -> dict:
    """Книга покупок: по каким поставкам можно заявить вычет НДС.

    Вычет подтверждается счётом-фактурой или УПД; приёмка без такого документа
    в книгу не идёт, сколько бы товара ни привезли. Строка «нет документа» —
    не украшение отчёта, а сумма, которую бухгалтерия не сможет зачесть.
    """
    d1, d2 = _период(date_from, date_to)
    p = {"cid": cid, "d1": d1, "d2": d2}
    фильтр = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    rows = (await db.execute(text(f"""
        SELECT station_id, number, doc_date, supplier, incoming_number,
               total_amount, vat_amount, signature_status, status
        FROM store_receipts
        WHERE company_id = :cid{фильтр} AND doc_date BETWEEN :d1 AND :d2
        ORDER BY doc_date
    """), p)).mappings().all()

    строки, к_вычету, без_документа = [], 0.0, 0.0
    for r in rows:
        ндс = float(r["vat_amount"] or 0)
        есть_основание = bool(r["incoming_number"])
        if есть_основание:
            к_вычету += ндс
        else:
            без_документа += ндс
        строки.append({
            "station_id": r["station_id"], "number": r["number"],
            "doc_date": r["doc_date"], "supplier": r["supplier"],
            "incoming_number": r["incoming_number"],
            "amount": float(r["total_amount"] or 0), "vat": ндс,
            "deductible": есть_основание,
            "problem": None if есть_основание else "нет входящего документа — вычет не подтвердить",
        })
    return {"rows": строки, "total": len(строки),
            "vat_deductible": round(к_вычету, 2),
            "vat_unconfirmed": round(без_документа, 2)}


async def turnover(db: AsyncSession, cid, date_from, date_to,
                   stations: list[int] | None = None) -> dict:
    """Оборотно-сальдовая по товарам: остаток на начало, приход, расход, конец.

    Остаток на начало берётся из снимка, ближайшего к началу периода: это
    единственная точка, где остаток зафиксирован целиком. Приход — из приёмок,
    расход — из продаж по чекам и списаний. Строка сходится не всегда, и это
    видно: разница показана колонкой, а не спрятана в «конец».
    """
    d1, d2 = _период(date_from, date_to)
    p = {"cid": cid, "d1": d1, "d2": d2}
    ф_ст = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations

    начало = {(r["station_id"], r["item_uuid"]): float(r["quantity"] or 0)
              for r in (await db.execute(text(f"""
        SELECT DISTINCT ON (station_id, item_uuid)
               station_id, item_uuid, quantity
        FROM store_stock_balances
        WHERE company_id = :cid{ф_ст} AND snapshot_at <= :d1
        ORDER BY station_id, item_uuid, snapshot_at DESC
    """), p)).mappings().all()}

    конец = {(r["station_id"], r["item_uuid"]): (float(r["quantity"] or 0), r["name"])
             for r in (await db.execute(text(f"""
        SELECT DISTINCT ON (station_id, item_uuid)
               station_id, item_uuid, quantity, name
        FROM store_stock_balances
        WHERE company_id = :cid{ф_ст} AND snapshot_at <= :d2
        ORDER BY station_id, item_uuid, snapshot_at DESC
    """), p)).mappings().all()}

    приход: dict[tuple, float] = {}
    for r in (await db.execute(text(f"""
        SELECT station_id, lines FROM store_receipts
        WHERE company_id = :cid{ф_ст} AND doc_date BETWEEN :d1 AND :d2
    """), p)).mappings().all():
        for l in r["lines"] or []:
            ключ = (r["station_id"], str(l.get("nomenclature_ref") or ""))
            приход[ключ] = приход.get(ключ, 0) + float(l.get("qty_fact") or 0)

    расход: dict[tuple, float] = {}
    for r in (await db.execute(text(f"""
        SELECT station_id, lines FROM store_cheques
        WHERE company_id = :cid{ф_ст} AND at BETWEEN :d1 AND :d2
    """), p)).mappings().all():
        for l in r["lines"] or []:
            ключ = (r["station_id"], str(l.get("item_uuid") or ""))
            расход[ключ] = расход.get(ключ, 0) + float(l.get("qty") or 0)

    ключи = set(начало) | set(конец) | set(приход) | set(расход)
    строки = []
    for k in ключи:
        станция, товар = k
        н = начало.get(k, 0.0)
        к, имя = конец.get(k, (0.0, None))
        вх = приход.get(k, 0.0)
        рх = расход.get(k, 0.0)
        расчётный = н + вх - рх
        строки.append({
            "station_id": станция, "item_uuid": товар, "name": имя or товар[:8],
            "opening": round(н, 3), "in": round(вх, 3), "out": round(рх, 3),
            "closing": round(к, 3),
            # Разница между «сколько должно остаться» и «сколько лежит»: она и
            # есть предмет инвентаризации, прятать её внутри итога нельзя.
            "unexplained": round(к - расчётный, 3),
        })
    строки.sort(key=lambda x: (x["station_id"], -abs(x["unexplained"])))
    return {"rows": строки, "total": len(строки),
            "unexplained_total": round(sum(abs(s["unexplained"]) for s in строки), 3)}


async def abc(db: AsyncSession, cid, date_from, date_to,
              stations: list[int] | None = None) -> dict:
    """ABC по выручке: что даёт основную выручку сети.

    Считается по чекам — это факт продажи, а не оценка. A — первые 80 %
    выручки, B — до 95 %, C — хвост. Порог именно по деньгам, а не по числу
    позиций: сеть живёт с выручки, а не с ассортимента.
    """
    d1, d2 = _период(date_from, date_to)
    p = {"cid": cid, "d1": d1, "d2": d2}
    ф_ст = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations

    свод: dict[str, dict] = {}
    for r in (await db.execute(text(f"""
        SELECT station_id, lines FROM store_cheques
        WHERE company_id = :cid{ф_ст} AND at BETWEEN :d1 AND :d2
    """), p)).mappings().all():
        for l in r["lines"] or []:
            имя = l.get("name") or ""
            узел = свод.setdefault(имя, {"name": имя, "qty": 0.0, "revenue": 0.0,
                                         "stations": set()})
            узел["qty"] += float(l.get("qty") or 0)
            узел["revenue"] += float(l.get("amount") or 0)
            узел["stations"].add(r["station_id"])

    строки = sorted(свод.values(), key=lambda x: -x["revenue"])
    всего = sum(s["revenue"] for s in строки) or 1.0
    накопленно = 0.0
    for s in строки:
        накопленно += s["revenue"]
        доля = накопленно / всего
        s["class"] = "A" if доля <= 0.8 else ("B" if доля <= 0.95 else "C")
        s["share"] = round(s["revenue"] / всего * 100, 2)
        s["cum_share"] = round(доля * 100, 2)
        s["stations"] = sorted(s["stations"])
        s["revenue"] = round(s["revenue"], 2)
        s["qty"] = round(s["qty"], 3)
    классы = {"A": 0, "B": 0, "C": 0}
    for s in строки:
        классы[s["class"]] += 1
    return {"rows": строки, "total": len(строки), "revenue": round(всего, 2),
            "by_class": классы}


# Витрина: что за отчёт, о чём он и какие колонки уходят в CSV.
# ── Документы станций: один разбор на все отчёты ────────────────────────────
#
# Половина отчётов читает одно и то же — документы из пакетов агентов. Писать
# каждому свой запрос значит каждый раз заново решать, где у документа дата и
# как считать сумму; один разбор держит ответы согласованными.
async def _документы(db: AsyncSession, cid, d1, d2, виды: list[str],
                     stations: list[int] | None,
                     строки_поле: str = "Товары") -> list[dict]:
    # Выпуск общепита держит строки в «ВыпускБлюд», остальные документы — в
    # «Товары». Поле называет вызывающий: молча брать «Товары» значит вернуть
    # пустой выпуск и решить, что блюда не готовят.
    p = {"cid": cid, "d1": d1, "d2": d2, "kinds": виды, "lines_key": строки_поле}
    фильтр = ""
    if stations:
        p["st"] = stations
        фильтр = " AND p.station_id = ANY(:st)"
    return [dict(r) for r in (await db.execute(text(f"""
        SELECT p.station_id, d->>'Тип' AS kind, d->>'Номер' AS number,
               coalesce((d->>'Дата')::timestamptz, p.received_at) AS doc_date,
               coalesce((d->>'СуммаДокумента')::numeric, 0) AS amount,
               d->>'Комментарий' AS note, d->>'Причина' AS reason,
               d->>'Склад' AS place, d->>'СкладПолучатель' AS place_to,
               coalesce(d->(:lines_key), '[]'::jsonb) AS lines
        FROM edge_packets p,
             LATERAL jsonb_array_elements(coalesce(p.payload->'Документы','[]'::jsonb)) d
        WHERE p.company_id = :cid{фильтр}
          AND d->>'Тип' = ANY(:kinds)
          AND coalesce((d->>'Дата')::timestamptz, p.received_at) BETWEEN :d1 AND :d2
    """), p)).mappings().all()]


def _строка(l: dict, *ключи: str) -> float:
    """Число из строки документа: русский ключ пакета или латинский из реестра."""
    for k in ключи:
        if l.get(k) not in (None, ""):
            try:
                return float(l[k])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _имя(l: dict) -> str:
    return l.get("Наименование") or l.get("name") or "—"


async def _справочник(db: AsyncSession) -> dict[str, str]:
    """UUID → название товара.

    Строки документов станции несут только `Номенклатура` — UUID карточки, без
    названия: имя живёт в справочнике сети, и дублировать его в каждом пакете
    незачем. Отчёту оно нужно, иначе таблица получается из UUID-ов.
    """
    return {str(r["uuid"]): r["name"] for r in (await db.execute(text("""
        SELECT external_uuid AS uuid, name FROM edge.item WHERE name IS NOT NULL
    """))).mappings().all()}


def _ключ_строки(l: dict) -> str:
    """UUID номенклатуры строки — в разных пакетах поле называется по-своему."""
    return str(l.get("Номенклатура") or l.get("item_uuid") or l.get("nomenclature_ref") or "")


def _по_станциям(строки: list[dict], сумма: str = "amount") -> list[dict]:
    """Свод по АЗС: сеть одной цифрой прячет провал отдельной точки."""
    свод: dict[int, dict] = {}
    for r in строки:
        у = свод.setdefault(r["station_id"], {"station_id": r["station_id"],
                                              "docs": 0, "amount": 0.0})
        у["docs"] += 1
        у["amount"] += float(r.get(сумма) or 0)
    for у in свод.values():
        у["amount"] = round(у["amount"], 2)
    return sorted(свод.values(), key=lambda x: x["station_id"])


async def sales(db: AsyncSession, cid, date_from, date_to,
                stations: list[int] | None = None) -> dict:
    """Продажи сети по товарам: что продаётся и сколько это приносит.

    Считается по документам продаж (смена целиком), а не по чекам: чеки
    приезжают с версии агента 0.87 и покрывают последние дни, а продажи смен
    лежат с апреля. По чекам отчёт врал бы «до августа не продавали».
    """
    d1, d2 = _период(date_from, date_to)
    доки = await _документы(db, cid, d1, d2, ["retail_sale_sidegoods"], stations)
    имена = await _справочник(db)
    свод: dict[tuple, dict] = {}
    for d in доки:
        for l in d["lines"] or []:
            uuid_ = _ключ_строки(l)
            имя = имена.get(uuid_) or _имя(l)
            ключ = (d["station_id"], uuid_ or имя)
            у = свод.setdefault(ключ, {"station_id": d["station_id"], "name": имя,
                                       "qty": 0.0, "revenue": 0.0, "docs": 0})
            у["qty"] += _строка(l, "Количество", "qty")
            у["revenue"] += _строка(l, "Сумма", "amount")
            у["docs"] += 1
    строки = sorted(свод.values(), key=lambda x: -x["revenue"])
    for у in строки:
        у["avg_price"] = round(у["revenue"] / у["qty"], 2) if у["qty"] else 0.0
        у["qty"] = round(у["qty"], 3)
        у["revenue"] = round(у["revenue"], 2)
    return {"rows": строки, "total": len(строки),
            "revenue": round(sum(s["revenue"] for s in строки), 2),
            "by_station": _по_станциям(строки, "revenue")}


async def stock(db: AsyncSession, cid, date_from, date_to,
                stations: list[int] | None = None) -> dict:
    """Ведомость остатков сети: что и сколько лежит, где и почём.

    Берётся последний снимок каждой станции, а не «остаток на дату»: снимки
    приходят пакетами и по датам не выровнены. Момент снимка стоит колонкой —
    иначе две станции молча сравнивались бы на разные сутки.
    """
    p = {"cid": cid}
    ф = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    rows = (await db.execute(text(f"""
        SELECT DISTINCT ON (station_id, place, item_uuid)
               station_id, place, place_name, name, barcode, quantity, item_uuid,
               retail_price, cost_unit, snapshot_at
        FROM store_stock_balances
        WHERE company_id = :cid{ф}
        ORDER BY station_id, place, item_uuid, snapshot_at DESC
    """), p)).mappings().all()
    # Станция знает себестоимость только по тому, что приняла сама. Остальное
    # оценивается по последней закупке — с пометкой, откуда взялась цена: без
    # этого «стоимость запаса» превращается в число без происхождения.
    оценки = await store_costs.ориентиры(db, cid, stations)
    строки = []
    for r in rows:
        кол = float(r["quantity"] or 0)
        цена = float(r["retail_price"] or 0)
        себе = float(r["cost_unit"] or 0)
        источник = "приход станции" if себе > 0 else ""
        if себе <= 0:
            о = оценки.get(str(r["item_uuid"] or ""))
            if о:
                себе, источник = о["cost"], о["source"]
        строки.append({
            "station_id": r["station_id"], "place": r["place_name"] or r["place"],
            "name": r["name"], "barcode": r["barcode"],
            "quantity": round(кол, 3), "price": цена,
            "amount": round(кол * цена, 2), "cost": round(себе, 2),
            "cost_amount": round(кол * себе, 2), "cost_source": источник or "нет данных",
            "snapshot_at": r["snapshot_at"],
        })
    строки.sort(key=lambda x: (x["station_id"], -x["amount"]))
    с_ценой = [s for s in строки if s["cost_amount"] > 0]
    return {"rows": строки, "total": len(строки),
            "stock_amount": round(sum(s["amount"] for s in строки), 2),
            "cost_amount": round(sum(s["cost_amount"] for s in строки), 2),
            # Покрытие себестоимостью — предмет отдельного разговора: пока часть
            # ассортимента живёт со снимка 1С, оценка есть не у всего.
            "cost_known": len(с_ценой),
            "by_station": _по_станциям(строки)}


def _реестр(доки: list[dict]) -> dict:
    """Реестр документов одного вида: строка на документ, свод по станциям."""
    строки = [{
        "station_id": d["station_id"], "number": d["number"],
        "doc_date": d["doc_date"], "amount": float(d["amount"] or 0),
        "positions": len(d["lines"] or []),
        "reason": d.get("reason") or d.get("note") or "",
        "place": d.get("place") or "", "place_to": d.get("place_to") or "",
    } for d in доки]
    строки.sort(key=lambda x: x["doc_date"], reverse=True)
    return {"rows": строки, "total": len(строки),
            "amount": round(sum(s["amount"] for s in строки), 2),
            "by_station": _по_станциям(строки)}


async def writeoffs(db: AsyncSession, cid, date_from, date_to,
                    stations: list[int] | None = None) -> dict:
    """Списания сети: бой, срок, порча, недостача — с основанием и суммой."""
    d1, d2 = _период(date_from, date_to)
    return _реестр(await _документы(db, cid, d1, d2, ["writeoff"], stations))


async def gains(db: AsyncSession, cid, date_from, date_to,
                stations: list[int] | None = None) -> dict:
    """Оприходования сети: товар нашёлся — по какой причине и на сколько."""
    d1, d2 = _период(date_from, date_to)
    return _реестр(await _документы(db, cid, d1, d2, ["gain"], stations))


async def transfers(db: AsyncSession, cid, date_from, date_to,
                    stations: list[int] | None = None) -> dict:
    """Перемещения: склад↔зал внутри станции и передачи между АЗС.

    Для сети это важнее, чем для станции: передачу между АЗС целиком видно
    только здесь — у станции есть лишь своя половина документа.
    """
    d1, d2 = _период(date_from, date_to)
    return _реестр(await _документы(db, cid, d1, d2, ["transfer"], stations))


async def inventories(db: AsyncSession, cid, date_from, date_to,
                      stations: list[int] | None = None) -> dict:
    """Инвентаризации: недостачи и излишки в штуках и деньгах.

    Инвентаризация — единственный законный способ привести учёт к факту, и её
    итог показывает, сколько сеть теряет по-настоящему.
    """
    d1, d2 = _период(date_from, date_to)
    доки = await _документы(db, cid, d1, d2, ["inventory"], stations)
    строки, всего_недостача, всего_излишек = [], 0.0, 0.0
    for d in доки:
        недостача = излишек = 0.0
        for l in d["lines"] or []:
            # В документе станции «Количество» — это факт пересчёта, а
            # «КоличествоУчет» — то, что числилось. Разница между ними и есть
            # недостача или излишек; отдельного поля «Отклонение» там нет.
            деньги = _строка(l, "Сумма", "amount") - _строка(l, "СуммаУчет", "amount_book")
            if деньги == 0:
                разница = _строка(l, "Количество", "qty_fact") - \
                          _строка(l, "КоличествоУчет", "qty_book")
                деньги = разница * _строка(l, "Цена", "price")
            if деньги < 0:
                недостача += abs(деньги)
            else:
                излишек += деньги
        всего_недостача += недостача
        всего_излишек += излишек
        строки.append({
            "station_id": d["station_id"], "number": d["number"],
            "doc_date": d["doc_date"], "positions": len(d["lines"] or []),
            "shortage": round(недостача, 2), "surplus": round(излишек, 2),
            "amount": round(излишек - недостача, 2),
        })
    строки.sort(key=lambda x: x["doc_date"], reverse=True)
    return {"rows": строки, "total": len(строки),
            "shortfall": round(всего_недостача, 2), "surplus": round(всего_излишек, 2),
            "by_station": _по_станциям(строки)}


async def production(db: AsyncSession, cid, date_from, date_to,
                     stations: list[int] | None = None) -> dict:
    """Выпуск общепита: что приготовили на каждой АЗС.

    Разрез сети, а не станции: рецептура едина, и разброс выпуска между
    точками сразу показывает, где техкартой не пользуются.
    """
    d1, d2 = _период(date_from, date_to)
    доки = await _документы(db, cid, d1, d2, ["production_release"], stations,
                            строки_поле="ВыпускБлюд")
    свод: dict[tuple, dict] = {}
    for d in доки:
        for l in d["lines"] or []:
            ключ = (d["station_id"], _имя(l))
            у = свод.setdefault(ключ, {"station_id": d["station_id"], "name": _имя(l),
                                       "qty": 0.0, "amount": 0.0, "docs": 0})
            у["qty"] += _строка(l, "Количество", "qty")
            у["amount"] += _строка(l, "Сумма", "amount")
            у["docs"] += 1
    строки = sorted(свод.values(), key=lambda x: -x["qty"])
    for у in строки:
        у["qty"] = round(у["qty"], 3)
        у["amount"] = round(у["amount"], 2)
    return {"rows": строки, "total": len(строки), "by_station": _по_станциям(строки)}


async def shifts(db: AsyncSession, cid, date_from, date_to,
                 stations: list[int] | None = None) -> dict:
    """Смены сети: выручка сопутки по сменам каждой АЗС.

    Смена — единица ответственности: за неё отвечает конкретный человек и по
    ней сходится касса. Сеть смотрит смены рядом, чтобы видеть провал точки в
    конкретный день, а не усреднённый месяц.
    """
    d1, d2 = _период(date_from, date_to)
    p = {"cid": cid, "d1": d1, "d2": d2}
    ф_p = " AND p.station_id = ANY(:st)" if stations else ""
    ф = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    # Смена приезжает пакетом kind='shift': её паспорт (номер, оператор, время
    # открытия и закрытия) лежит в «Смена», продажи — документами внутри.
    rows = (await db.execute(text(f"""
        SELECT p.station_id,
               p.payload->'Смена'->>'НомерСмены' AS shift,
               p.payload->'Смена'->>'НомерСменыВнутр' AS shift_inner,
               coalesce((p.payload->'Смена'->>'Закрытие')::timestamptz,
                        (p.payload->'Смена'->>'Открытие')::timestamptz,
                        p.received_at) AS shift_date,
               coalesce(p.payload->'Смена'->>'Оператор', '') AS operator,
               coalesce((
                 SELECT sum(coalesce((l->>'Сумма')::numeric, 0))
                 FROM jsonb_array_elements(coalesce(p.payload->'Документы','[]'::jsonb)) d,
                      jsonb_array_elements(coalesce(d->'Товары','[]'::jsonb)) l
                 WHERE d->>'Тип' = 'retail_sale_sidegoods'), 0) AS revenue,
               coalesce((
                 SELECT count(*)
                 FROM jsonb_array_elements(coalesce(p.payload->'Документы','[]'::jsonb)) d,
                      jsonb_array_elements(coalesce(d->'Товары','[]'::jsonb)) l
                 WHERE d->>'Тип' = 'retail_sale_sidegoods'), 0) AS positions
        FROM edge_packets p
        WHERE p.company_id = :cid{ф_p} AND p.kind = 'shift'
          AND coalesce((p.payload->'Смена'->>'Закрытие')::timestamptz,
                       (p.payload->'Смена'->>'Открытие')::timestamptz,
                       p.received_at) BETWEEN :d1 AND :d2
        ORDER BY 3 DESC
    """), p)).mappings().all()

    # Чеки приезжают отдельным пакетом и есть не у всех смен: колонка честно
    # показывает ноль там, где чеков ещё нет, вместо того чтобы прятать смену.
    # Сопоставление — по ВНУТРЕННЕМУ номеру смены: касса нумерует свои смены
    # сама (7067), а в отчёте виден номер ОСЭ (2082080508202601) — тот, что
    # печатается на документах.
    чеки = {(r["station_id"], str(r["shift_number"])): int(r["n"])
            for r in (await db.execute(text(f"""
        SELECT station_id, shift_number, count(*) AS n
        FROM store_cheques
        WHERE company_id = :cid{ф} AND at BETWEEN :d1 AND :d2
        GROUP BY 1, 2
    """), p)).mappings().all()}

    строки = [{
        "station_id": r["station_id"], "shift": r["shift"],
        "shift_date": r["shift_date"], "operator": r["operator"],
        "revenue": round(float(r["revenue"] or 0), 2),
        "positions": int(r["positions"] or 0),
        "cheques": чеки.get((r["station_id"], str(r["shift_inner"])), 0),
    } for r in rows]
    return {"rows": строки, "total": len(строки),
            "revenue": round(sum(s["revenue"] for s in строки), 2),
            "by_station": _по_станциям(строки, "revenue")}


async def visits(db: AsyncSession, cid, date_from, date_to,
                 stations: list[int] | None = None) -> dict:
    """Посещения станций и конверсия магазина.

    Посетитель — это чек. Человек, заправившийся и уехавший, магазин не посетил
    как покупатель, но станцию посетил: он прошёл мимо витрины, и он в
    знаменателе. Без этого выручку магазина не с чем сравнивать — сорок тысяч
    за смену это много или мало, зависит от того, прошло мимо кассы четыреста
    человек или девяносто.

    Считается из двух контуров, потому что они и ведутся раздельно: заправки
    лежат в реестре топлива, покупки магазина — в чеках. Смешанный чек (человек
    заправился и взял кофе) в топливном контуре уже посчитан, поэтому к
    посещениям добавляются только чеки БЕЗ топлива — иначе один визит
    удвоился бы.
    """
    d1, d2 = _период(date_from, date_to)
    p = {"cid": cid, "d1": d1, "d2": d2}
    ф_т = " AND station_code = ANY(:st)" if stations else ""
    ф_ч = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations

    топливо = {(r["station"], r["shift"]): dict(r) for r in (await db.execute(text(f"""
        SELECT station_code AS station, shift_number AS shift,
               count(*) AS ops, min(dt) AS started, max(dt) AS ended,
               coalesce(sum(amount), 0) AS fuel_amount
        FROM fuel_transactions
        WHERE company_id = :cid{ф_т} AND dt BETWEEN :d1 AND :d2
        GROUP BY 1, 2
    """), p)).mappings().all()}

    чеки = {(r["station"], r["shift"]): dict(r) for r in (await db.execute(text(f"""
        SELECT station_id AS station, shift_number AS shift,
               count(*) AS cheques,
               count(*) FILTER (WHERE had_fuel) AS mixed,
               count(*) FILTER (WHERE NOT had_fuel) AS shop_only,
               coalesce(sum(total), 0) AS shop_amount,
               coalesce(sum(positions), 0) AS positions
        FROM store_cheques
        WHERE company_id = :cid{ф_ч} AND at BETWEEN :d1 AND :d2
        GROUP BY 1, 2
    """), p)).mappings().all()}

    строки = []
    for ключ in sorted(set(топливо) | set(чеки), key=lambda k: (k[0], -(k[1] or 0))):
        станция, смена = ключ
        т = топливо.get(ключ, {})
        ч = чеки.get(ключ, {})
        заправок = int(т.get("ops") or 0)
        чеков_магазина = int(ч.get("cheques") or 0)
        только_магазин = int(ч.get("shop_only") or 0)
        смешанных = int(ч.get("mixed") or 0)
        # Смешанный чек — доказательство заправки: человек взял и топливо, и
        # товар. Если топливный контур отстал (реализации приезжают позже
        # чеков), заправок в реестре может быть меньше — тогда берём то, что
        # доказано чеками, иначе конверсия уезжает за сто процентов.
        заправок_всего = max(заправок, смешанных)
        посещений = заправок_всего + только_магазин
        выручка = float(ч.get("shop_amount") or 0)
        строки.append({
            "station_id": станция, "shift": смена,
            "shift_date": т.get("started") or None,
            "visits": посещений,
            "fuel_ops": заправок,
            "shop_cheques": чеков_магазина,
            "mixed": смешанных,
            "fuel_only": max(заправок_всего - смешанных, 0),
            # Пустой топливный контур при живых чеках — не ноль заправок, а
            # «данные ещё не приехали». Молчать об этом нельзя: конверсия в
            # такой смене завышена.
            "note": "" if заправок else ("реализации топлива ещё не пришли"
                                         if чеков_магазина else ""),
            "conversion": round(чеков_магазина / посещений * 100, 1) if посещений else 0.0,
            "amount": round(выручка, 2),
            "per_visit": round(выручка / посещений, 2) if посещений else 0.0,
            "avg_cheque": round(выручка / чеков_магазина, 2) if чеков_магазина else 0.0,
        })

    всего_визитов = sum(s["visits"] for s in строки)
    всего_чеков = sum(s["shop_cheques"] for s in строки)
    выручка = sum(s["amount"] for s in строки)
    # Свод по станциям считается по своим итогам, а не усреднением средних:
    # смена с тремя посетителями иначе весила бы столько же, сколько смена с
    # четырьмя сотнями.
    по_станциям: dict[int, dict] = {}
    for s in строки:
        у = по_станциям.setdefault(s["station_id"], {"station_id": s["station_id"],
                                                     "docs": 0, "amount": 0.0})
        у["docs"] += s["visits"]
        у["amount"] += s["amount"]
    for у in по_станциям.values():
        у["amount"] = round(у["amount"], 2)
    return {
        "rows": строки, "total": len(строки),
        "visits": всего_визитов,
        "conversion": round(всего_чеков / всего_визитов * 100, 1) if всего_визитов else 0.0,
        "revenue": round(выручка, 2),
        "per_visit": round(выручка / всего_визитов, 2) if всего_визитов else 0.0,
        "by_station": sorted(по_станциям.values(), key=lambda x: x["station_id"]),
    }


async def mrc(db: AsyncSession, cid, date_from, date_to,
              stations: list[int] | None = None) -> dict:
    """Контроль МРЦ табака: где розничная цена выше максимальной.

    Продажа табака дороже МРЦ — нарушение ст. 13 ФЗ-15, и отвечает за него
    юрлицо, а не станция. Поэтому смотреть обязан центр: цену на такие позиции
    задаёт он.
    """
    p = {"cid": cid}
    ф = " AND b.station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    rows = (await db.execute(text(f"""
        SELECT DISTINCT ON (b.station_id, b.item_uuid)
               b.station_id, b.name, b.barcode, b.retail_price, i.mrc, b.quantity
        FROM store_stock_balances b
        JOIN edge.item i ON i.external_uuid::text = b.item_uuid
        WHERE b.company_id = :cid{ф} AND i.mrc IS NOT NULL AND i.mrc > 0
        ORDER BY b.station_id, b.item_uuid, b.snapshot_at DESC
    """), p)).mappings().all()
    строки = []
    for r in rows:
        цена = float(r["retail_price"] or 0)
        предел = float(r["mrc"] or 0)
        строки.append({
            "station_id": r["station_id"], "name": r["name"], "barcode": r["barcode"],
            "price": цена, "mrc": предел, "over": round(цена - предел, 2),
            "quantity": round(float(r["quantity"] or 0), 3),
            "problem": "цена выше МРЦ" if цена > предел else "",
        })
    нарушения = [s for s in строки if s["over"] > 0]
    строки.sort(key=lambda x: -x["over"])
    return {"rows": строки, "total": len(строки), "violations": len(нарушения),
            "by_station": _по_станциям(нарушения)}


async def suppliers(db: AsyncSession, cid, date_from, date_to,
                    stations: list[int] | None = None) -> dict:
    """Поставщики сети: оборот, число поставок, последняя дата.

    Разрез, которого у станции нет по определению: договариваться об условиях
    можно, только зная, сколько сеть берёт у поставщика целиком.
    """
    d1, d2 = _период(date_from, date_to)
    p = {"cid": cid, "d1": d1, "d2": d2}
    ф = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    rows = (await db.execute(text(f"""
        SELECT coalesce(nullif(supplier, ''), '— не указан') AS supplier,
               count(*) AS docs, sum(coalesce(total_amount, 0)) AS amount,
               sum(coalesce(vat_amount, 0)) AS vat, max(doc_date) AS last_date,
               array_agg(DISTINCT station_id) AS stations,
               count(*) FILTER (WHERE incoming_number IS NULL) AS no_doc
        FROM store_receipts
        WHERE company_id = :cid{ф} AND doc_date BETWEEN :d1 AND :d2
        GROUP BY 1 ORDER BY 3 DESC
    """), p)).mappings().all()
    строки = [{
        "supplier": r["supplier"], "docs": int(r["docs"]),
        "amount": round(float(r["amount"] or 0), 2),
        "vat": round(float(r["vat"] or 0), 2),
        "last_date": r["last_date"], "stations": sorted(r["stations"] or []),
        "no_doc": int(r["no_doc"] or 0),
    } for r in rows]
    return {"rows": строки, "total": len(строки),
            "amount": round(sum(s["amount"] for s in строки), 2)}


REPORTS = {
    "documents": {
        "title": "Единый журнал документов",
        "about": "Всё, чем двигался товар: приёмки, списания, перемещения, инвентаризации, "
                 "возвраты, производство. Источник указан колонкой — станция и 1С ведут "
                 "свои номера, и сводить их в одну строку нельзя.",
        "columns": ["АЗС", "Вид", "Номер", "Дата", "Позиций", "Сумма", "Источник"],
        "fields": ["station_id", "label", "number", "doc_date", "positions", "amount", "source"],
    },
    "purchase-diff": {
        "title": "Расхождения приёмки",
        "about": "Где факт разошёлся с накладной поставщика. Предмет разговора с поставщиком "
                 "(акт ТОРГ-2), а не ошибка приёмщика: недовоз оплачивать не за что.",
        "columns": ["АЗС", "Документ", "Дата", "Поставщик", "Позиция", "Заявлено", "Факт",
                    "Расхождение", "Цена", "Сумма расхождения"],
        "fields": ["station_id", "number", "doc_date", "supplier", "name", "expected", "fact",
                   "diff", "price", "diff_amount"],
    },
    "vat-book": {
        "title": "Книга покупок (НДС к вычету)",
        "about": "По каким поставкам можно заявить вычет. Приёмка без входящего документа "
                 "в книгу не идёт: это сумма, которую бухгалтерия не сможет зачесть.",
        "columns": ["АЗС", "Документ", "Дата", "Поставщик", "Входящий №", "Сумма", "НДС",
                    "К вычету", "Проблема"],
        "fields": ["station_id", "number", "doc_date", "supplier", "incoming_number",
                   "amount", "vat", "deductible", "problem"],
    },
    "turnover": {
        "title": "Оборотно-сальдовая по товарам",
        "about": "Остаток на начало, приход, расход и остаток на конец периода. Необъяснённая "
                 "разница показана колонкой — это и есть предмет инвентаризации.",
        "columns": ["АЗС", "Товар", "Остаток на начало", "Приход", "Расход",
                    "Остаток на конец", "Необъяснено"],
        "fields": ["station_id", "name", "opening", "in", "out", "closing", "unexplained"],
    },
    "abc": {
        "title": "ABC-анализ по выручке",
        "about": "Что даёт основную выручку сети: A — первые 80 % денег, B — до 95 %, C — хвост. "
                 "Считается по чекам, то есть по факту продажи.",
        "columns": ["Товар", "Класс", "Продано", "Выручка", "Доля, %", "Накопленно, %", "АЗС"],
        "fields": ["name", "class", "qty", "revenue", "share", "cum_share", "stations"],
        "group": "torg",
    },
    "sales": {
        "title": "Продажи по товарам",
        "about": "Что продаётся в сети и сколько это приносит. Считается по документам продаж "
                 "смен — они лежат с апреля, тогда как чеки приезжают только с версии "
                 "агента 0.87.",
        "columns": ["АЗС", "Товар", "Продано", "Выручка", "Средняя цена", "Смен"],
        "fields": ["station_id", "name", "qty", "revenue", "avg_price", "docs"],
        "group": "torg",
    },
    "stock": {
        "title": "Ведомость остатков",
        "about": "Что и сколько лежит на каждой АЗС, где и почём. Берётся последний снимок "
                 "станции: снимки приходят пакетами и по датам не выровнены, поэтому момент "
                 "снимка стоит колонкой. Себестоимость — факт прихода станции, а где его нет "
                 "(товар со старта, из снимка 1С) — цена последней закупки; источник указан "
                 "колонкой, оценку и факт смешивать нельзя.",
        "columns": ["АЗС", "Место", "Товар", "Штрихкод", "Количество", "Цена", "Сумма",
                    "Себестоимость", "В себестоимости", "Источник цены", "Снимок"],
        "fields": ["station_id", "place", "name", "barcode", "quantity", "price", "amount",
                   "cost", "cost_amount", "cost_source", "snapshot_at"],
        "group": "sklad",
    },
    "writeoffs": {
        "title": "Списания",
        "about": "Бой, срок, порча, недостача — с основанием и суммой. Списание уменьшает "
                 "валовую прибыль магазина, поэтому причина здесь важнее суммы.",
        "columns": ["АЗС", "Документ", "Дата", "Причина", "Позиций", "Сумма"],
        "fields": ["station_id", "number", "doc_date", "reason", "positions", "amount"],
        "group": "sklad",
    },
    "gains": {
        "title": "Оприходования",
        "about": "Товар нашёлся: излишек по пересчёту, возврат в оборот, разбор комплекта. "
                 "К закупкам отношения не имеет — поставщику деньги не идут.",
        "columns": ["АЗС", "Документ", "Дата", "Причина", "Позиций", "Сумма"],
        "fields": ["station_id", "number", "doc_date", "reason", "positions", "amount"],
        "group": "sklad",
    },
    "transfers": {
        "title": "Перемещения",
        "about": "Склад ↔ зал внутри станции и передачи между АЗС. Передачу между станциями "
                 "целиком видно только здесь: у станции есть лишь своя половина документа.",
        "columns": ["АЗС", "Документ", "Дата", "Откуда", "Куда", "Позиций", "Сумма"],
        "fields": ["station_id", "number", "doc_date", "place", "place_to", "positions",
                   "amount"],
        "group": "sklad",
    },
    "inventories": {
        "title": "Инвентаризации",
        "about": "Недостачи и излишки в деньгах по каждому пересчёту. Инвентаризация — "
                 "единственный законный способ привести учёт к факту, и её итог показывает, "
                 "сколько сеть теряет по-настоящему.",
        "columns": ["АЗС", "Документ", "Дата", "Позиций", "Недостача", "Излишек", "Итог"],
        "fields": ["station_id", "number", "doc_date", "positions", "shortage", "surplus",
                   "amount"],
        "group": "sklad",
    },
    "production": {
        "title": "Выпуск общепита",
        "about": "Что приготовили на каждой АЗС. Рецептура в сети едина, поэтому разброс "
                 "выпуска между точками сразу показывает, где техкартой не пользуются.",
        "columns": ["АЗС", "Блюдо", "Выпущено", "Сумма", "Документов"],
        "fields": ["station_id", "name", "qty", "amount", "docs"],
        "group": "torg",
    },
    "visits": {
        "title": "Посещения и конверсия",
        "about": "Сколько человек побывало на станции за смену и какая часть из них купила в "
                 "магазине. Посетитель — это чек: заправился и уехал — станцию посетил, "
                 "магазин нет. Выручку магазина не с чем сравнивать без этой цифры.",
        "columns": ["АЗС", "Смена", "Дата", "Посещений", "Заправок", "Чеков магазина",
                    "И то, и другое", "Только заправка", "Конверсия, %", "Выручка магазина",
                    "На посетителя", "Средний чек", "Замечание"],
        "fields": ["station_id", "shift", "shift_date", "visits", "fuel_ops", "shop_cheques",
                   "mixed", "fuel_only", "conversion", "amount", "per_visit", "avg_cheque",
                   "note"],
        "group": "torg",
    },
    "shifts": {
        "title": "Смены",
        "about": "Выручка сопутки по сменам каждой АЗС. Смена — единица ответственности: за "
                 "неё отвечает конкретный человек и по ней сходится касса.",
        "columns": ["АЗС", "Смена", "Дата", "Оператор", "Позиций", "Чеков", "Выручка"],
        "fields": ["station_id", "shift", "shift_date", "operator", "positions", "cheques",
                   "revenue"],
        "group": "close",
    },
    "mrc": {
        "title": "Контроль МРЦ табака",
        "about": "Где розничная цена выше максимальной. Продажа табака дороже МРЦ — нарушение "
                 "ст. 13 ФЗ-15, отвечает за него юрлицо, а не станция. МРЦ берётся из "
                 "карточки сети: пустой отчёт значит не «нарушений нет», а «МРЦ в справочник "
                 "ещё не занесены».",
        "columns": ["АЗС", "Товар", "Штрихкод", "Цена", "МРЦ", "Превышение", "Остаток",
                    "Проблема"],
        "fields": ["station_id", "name", "barcode", "price", "mrc", "over", "quantity",
                   "problem"],
        "group": "mark",
    },
    "suppliers": {
        "title": "Поставщики",
        "about": "Оборот, число поставок и последняя дата по каждому поставщику сети. "
                 "Договариваться об условиях можно, только зная объём целиком.",
        "columns": ["Поставщик", "Поставок", "Сумма", "НДС", "Последняя", "АЗС",
                    "Без документа"],
        "fields": ["supplier", "docs", "amount", "vat", "last_date", "stations", "no_doc"],
        "group": "priem",
    },
}

# Разделы каталога — те же, что в меню и в каталоге отчётов станции. Человек
# ищет отчёт там же, где работает: «списания» в Складе, а не в общем списке из
# пятнадцати названий.
GROUPS = [
    {"key": "torg", "label": "Торговля", "hint": "продажи, ассортимент, цены и маржа"},
    {"key": "priem", "label": "Приёмка", "hint": "поставки и расчёты с поставщиком"},
    {"key": "sklad", "label": "Склад", "hint": "остатки и движение товара"},
    {"key": "mark", "label": "Маркировка", "hint": "«Честный знак» и МРЦ"},
    {"key": "close", "label": "Закрытие", "hint": "смены"},
    {"key": "skvoz", "label": "Сквозные", "hint": "бухгалтерия и весь документооборот"},
]

# Группа по умолчанию для отчётов, заведённых до появления разделов.
_ГРУППА_ПО_УМОЛЧАНИЮ = {
    "documents": "skvoz", "purchase-diff": "priem", "vat-book": "priem",
    "turnover": "sklad",
}
for _ключ, _отчёт in REPORTS.items():
    _отчёт.setdefault("group", _ГРУППА_ПО_УМОЛЧАНИЮ.get(_ключ, "skvoz"))

BUILDERS = {
    "documents": documents,
    "purchase-diff": purchase_diff,
    "vat-book": vat_book,
    "turnover": turnover,
    "abc": abc,
    "sales": sales,
    "stock": stock,
    "writeoffs": writeoffs,
    "gains": gains,
    "transfers": transfers,
    "inventories": inventories,
    "production": production,
    "shifts": shifts,
    "visits": visits,
    "mrc": mrc,
    "suppliers": suppliers,
}
