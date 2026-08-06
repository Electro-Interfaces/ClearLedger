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
    },
}

BUILDERS = {
    "documents": documents,
    "purchase-diff": purchase_diff,
    "vat-book": vat_book,
    "turnover": turnover,
    "abc": abc,
}
