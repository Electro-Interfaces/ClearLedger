"""Отчёты сети на журнале движений станций (`store_stock_moves`).

До 07.10.2026 центр знал только последний снимок остатков станции и не мог
ответить, сколько лежало на конец прошлого периода; оборотка начинала и
кончалась «снимком не позже даты», которого для прошлого не было. Станция шлёт
журнал движений по дням (`edge_moves`), и отчёты повторяют станционные:
остатки на дату — по местам, оборотка — по товару, с листом движений.

Время — по событию (event_time), сутки — московские, как на станции.
"""
from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_МСК = ZoneInfo("Europe/Moscow")


def _граница(date_to: str | None) -> tuple[date, datetime]:
    """День отчёта и его конец: первая секунда следующих суток (не включая)."""
    д = date.fromisoformat(date_to) if date_to else datetime.now(_МСК).date()
    return д, datetime.combine(д + timedelta(days=1), time.min, tzinfo=_МСК)


def _станции(stations: list[int] | None, p: dict) -> str:
    if stations:
        p["st"] = stations
        return " AND m.station_id = ANY(:st)"
    return ""


async def _загружено(db: AsyncSession, cid, stations: list[int] | None) -> dict[int, str]:
    """По какой день журнал станции уже лежит в центре. Отчёт за более поздний
    день считается по неполным данным — это говорится словами, а не молчанием."""
    p = {"cid": cid}
    ф = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    return {r[0]: r[1].strftime("%d.%m.%Y") for r in (await db.execute(text(f"""
        SELECT station_id, max(day) FROM store_stock_move_days
         WHERE company_id = :cid{ф} GROUP BY station_id
    """), p)).all()}


# Карточка, место, код кассы и цена — к строке остатка. Код кассы — активный
# на станции по штрихкоду; цена — действующая на станции на конец дня, иначе
# сетевая.
_СПРАВКА = """
    LEFT JOIN edge.item i ON i.external_uuid::text = q.item_uuid
    LEFT JOIN edge.item_group g ON g.id = i.group_id
    LEFT JOIN edge.place pl ON pl.station_id = q.station_id AND pl.code = q.place
    LEFT JOIN LATERAL (
        SELECT n.ns_code FROM edge.barcode b
          JOIN edge.ns_code n ON n.barcode_id = b.id AND n.station_id = q.station_id
                             AND n.status = 'active'
         WHERE b.code = q.barcode LIMIT 1) ns ON true
    LEFT JOIN LATERAL (
        SELECT pr.price FROM edge.price pr
         WHERE pr.item_id = i.id AND (pr.station_id = q.station_id OR pr.station_id IS NULL)
           AND pr.valid_from < :end AND (pr.valid_to IS NULL OR pr.valid_to >= :end)
         ORDER BY pr.station_id NULLS LAST, pr.valid_from DESC LIMIT 1) pr ON true
"""


async def stock_on_date(db: AsyncSession, cid, date_from, date_to,
                        stations: list[int] | None = None) -> dict:
    """Остатки на конец дня `date_to` (23:59:59 МСК) по станции, месту и штрихкоду."""
    день, конец = _граница(date_to)
    p = {"cid": cid, "end": конец}
    ф = _станции(stations, p)
    rows = (await db.execute(text(f"""
        WITH q AS (
            SELECT m.station_id, m.place, m.item_uuid, m.barcode, sum(m.quantity) AS qty
              FROM store_stock_moves m
             WHERE m.company_id = :cid{ф} AND m.event_time < :end
             GROUP BY 1, 2, 3, 4
            HAVING abs(sum(m.quantity)) > 0.0005
        )
        SELECT q.station_id, q.place, coalesce(pl.name, q.place) AS place_name,
               coalesce(pl.is_sales_floor, q.place = q.station_id::text) AS hall,
               coalesce(i.name, 'без карточки в каталоге') AS name,
               coalesce(g.path, g.name, '') AS grp, q.barcode, ns.ns_code,
               coalesce(nullif(i.unit, ''), 'шт') AS unit, q.qty, pr.price
          FROM q {_СПРАВКА}
         ORDER BY q.station_id, hall DESC, q.place, grp, name, q.barcode
    """), p)).mappings().all()
    строки = []
    for r in rows:
        кол = float(r["qty"])
        цена = float(r["price"]) if r["price"] is not None else None
        строки.append({
            "station_id": r["station_id"], "place": r["place_name"],
            "place_kind": "Торговый зал" if r["hall"] else "Склад",
            "name": r["name"], "group": r["grp"], "ns_code": r["ns_code"],
            "barcode": r["barcode"], "unit": r["unit"], "quantity": round(кол, 3),
            "price": цена, "amount": round(кол * цена, 2) if цена is not None else None,
        })
    загружено = await _загружено(db, cid, stations)
    листы = []
    for вид in ("Торговый зал", "Склад"):
        свои = [s for s in строки if s["place_kind"] == вид]
        if not свои:
            continue
        итог = {"name": f"Итого: {вид.lower()} на конец {день:%d.%m.%Y} (23:59:59)",
                "quantity": round(sum(s["quantity"] for s in свои), 3),
                "amount": round(sum(s["amount"] or 0 for s in свои), 2)}
        листы.append({"title": вид, "rows": свои + [итог]})
    return {
        "rows": строки, "total": len(строки),
        "amount": round(sum(s["amount"] or 0 for s in строки), 2),
        "as_of": f"{день:%d.%m.%Y} 23:59:59",
        "loaded_through": загружено,
        "sheets": листы,
    }


async def turnover(db: AsyncSession, cid, date_from, date_to,
                   stations: list[int] | None = None) -> dict:
    """Оборотно-сальдовая по товарам на журнале движений: начало, приход,
    расход, конец. Приход — все плюсовые движения периода, расход — все
    минусовые, как на станции; строка сходится по построению."""
    д1 = date.fromisoformat(date_from) if date_from else date(2000, 1, 1)
    д2, конец = _граница(date_to)
    начало = datetime.combine(д1, time.min, tzinfo=_МСК)
    p = {"cid": cid, "d1": начало, "end": конец}
    ф = _станции(stations, p)
    rows = (await db.execute(text(f"""
        SELECT m.station_id, m.item_uuid,
               coalesce(max(i.name), 'без карточки в каталоге') AS name,
               coalesce(max(g.path), max(g.name), '') AS grp,
               sum(m.quantity) FILTER (WHERE m.event_time < :d1) AS opening,
               sum(m.quantity) FILTER (WHERE m.event_time >= :d1 AND m.quantity > 0) AS inc,
               -sum(m.quantity) FILTER (WHERE m.event_time >= :d1 AND m.quantity < 0) AS outc
          FROM store_stock_moves m
          LEFT JOIN edge.item i ON i.external_uuid::text = m.item_uuid
          LEFT JOIN edge.item_group g ON g.id = i.group_id
         WHERE m.company_id = :cid{ф} AND m.event_time < :end
         GROUP BY m.station_id, m.item_uuid
    """), p)).mappings().all()
    строки = []
    for r in rows:
        н, вх, рх = (float(r["opening"] or 0), float(r["inc"] or 0), float(r["outc"] or 0))
        if abs(н) < 0.0005 and вх < 0.0005 and рх < 0.0005:
            continue
        строки.append({"station_id": r["station_id"], "item_uuid": r["item_uuid"],
                       "name": r["name"], "group": r["grp"], "opening": round(н, 3),
                       "in": round(вх, 3), "out": round(рх, 3),
                       "closing": round(н + вх - рх, 3)})
    строки.sort(key=lambda s: (s["station_id"], s["group"], s["name"]))

    # Лист «Движения» — что, когда, каким документом: минус в ведомости
    # разбирают по документам, как на станции (06.10.2026).
    движения = (await db.execute(text(f"""
        SELECT m.station_id, m.event_time, coalesce(i.name, m.item_uuid) AS name,
               m.barcode, coalesce(pl.name, m.place) AS place, m.doc_kind,
               m.doc_number, m.quantity, m.note
          FROM store_stock_moves m
          LEFT JOIN edge.item i ON i.external_uuid::text = m.item_uuid
          LEFT JOIN edge.place pl ON pl.station_id = m.station_id AND pl.code = m.place
         WHERE m.company_id = :cid{ф} AND m.event_time >= :d1 AND m.event_time < :end
         ORDER BY m.station_id, name, m.event_time, m.move_id
    """), p)).mappings().all()
    лист = [{"station_id": r["station_id"],
             "at": r["event_time"].astimezone(_МСК).strftime("%d.%m.%Y %H:%M"),
             "name": r["name"], "barcode": r["barcode"], "place": r["place"],
             "doc_kind": ВИДЫ.get(r["doc_kind"], r["doc_kind"]),
             "doc_number": r["doc_number"], "quantity": float(r["quantity"]),
             "note": r["note"]} for r in движения]
    return {"rows": строки, "total": len(строки),
            "loaded_through": await _загружено(db, cid, stations),
            "sheets": [{"title": "Движения", "columns": ДВИЖЕНИЯ_КОЛОНКИ,
                        "fields": ДВИЖЕНИЯ_ПОЛЯ, "rows": лист}]}


ВИДЫ = {
    "sale": "продажа", "receipt": "приёмка", "baseline": "стартовый остаток",
    "inventory": "инвентаризация", "writeoff": "списание", "gain": "оприходование",
    "transfer": "перемещение", "barcode-qty": "разводка по штрихкодам",
    "return_sale": "возврат покупателя", "return_purchase": "возврат поставщику",
    "production": "выпуск", "draft_cleanup": "поглощение черновика",
}
ДВИЖЕНИЯ_КОЛОНКИ = ["АЗС", "Когда", "Товар", "Штрихкод", "Место", "Вид", "Документ",
                    "Количество", "Пояснение"]
ДВИЖЕНИЯ_ПОЛЯ = ["station_id", "at", "name", "barcode", "place", "doc_kind",
                 "doc_number", "quantity", "note"]


def лист_остатков(данные: dict, *, организация: str) -> str:
    """Печатная ведомость остатков: место — страница, внизу итог и подписи.
    PDF — через печать браузера («Сохранить как PDF»)."""
    e = html.escape
    колонки = [("№", None), ("Товар", "name"), ("Код кассы", "ns_code"),
               ("Штрихкод", "barcode"), ("Ед.", "unit"), ("Остаток", "quantity"),
               ("Цена", "price"), ("Сумма", "amount")]

    def ч(v, деньги=False):
        if v is None or v == "":
            return ""
        if isinstance(v, (int, float)):
            s = f"{v:,.2f}" if деньги else (f"{v:,.3f}".rstrip("0").rstrip("."))
            return s.replace(",", " ").replace(".", ",")
        return e(str(v))

    страницы = []
    группы: dict[tuple, list] = {}
    for s in данные["rows"]:
        группы.setdefault((s["station_id"], s["place"]), []).append(s)
    for (станция, место), строки in группы.items():
        тело = "".join(
            "<tr><td class=n>{}</td>{}</tr>".format(
                i + 1, "".join(
                    f"<td{' class=n' if к in ('quantity', 'price', 'amount') else ''}>"
                    f"{ч(s.get(к), к in ('price', 'amount'))}</td>"
                    for _, к in колонки[1:]))
            for i, s in enumerate(строки))
        итог_кол = sum(s["quantity"] for s in строки)
        итог_сумма = sum(s["amount"] or 0 for s in строки)
        страницы.append(
            f"<div class=лист><h1>Остатки товаров АЗС №{станция} на {e(данные['as_of'])}</h1>"
            f"<h2>{e(str(место))}</h2>"
            f"<table><thead><tr>{''.join(f'<th>{e(к)}</th>' for к, _ in колонки)}</tr></thead>"
            f"<tbody>{тело}</tbody><tfoot><tr><td></td><td colspan=4>Итого</td>"
            f"<td class=n>{ч(итог_кол)}</td><td></td><td class=n>{ч(итог_сумма, True)}</td>"
            f"</tr></tfoot></table>"
            f"<div class=подписи><div>Материально ответственное лицо</div><div>Проверил</div></div></div>")
    if not страницы:
        страницы = ["<p>Остатков по отбору нет.</p>"]
    return f"""<!doctype html><html lang=ru><head><meta charset=utf-8>
<title>Остатки на {e(данные['as_of'])}</title><style>
body{{font:12px/1.4 Arial,sans-serif;color:#000;background:#fff;margin:20px}}
h1{{font-size:16px;margin:0 0 4px}} h2{{font-size:14px;margin:6px 0}}
.орг{{color:#333;margin:0 0 10px}}
.лист+.лист{{break-before:page;page-break-before:always}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #000;padding:3px 5px;text-align:left;vertical-align:top}}
th{{background:#f0f0f0}} td.n{{text-align:right;white-space:nowrap}}
tfoot td{{font-weight:bold;background:#f6f6f6}}
.подписи{{margin-top:24px;display:flex;gap:40px}}
.подписи div{{flex:1;border-bottom:1px solid #000;padding-top:18px;font-size:10px;color:#333}}
.печать{{margin:0 0 14px}} .печать button{{font:13px Arial;padding:7px 16px;cursor:pointer}}
@page{{size:A4 landscape;margin:8mm}}
@media print{{body{{margin:0;font-size:9.5px}}.noprint{{display:none}}
 th,tfoot td{{background:#fff}}thead{{display:table-header-group}}
 tr{{break-inside:avoid;page-break-inside:avoid}}}}
</style></head><body>
<div class="печать noprint"><button onclick="window.print()">Печать / Сохранить как PDF</button></div>
<p class=орг>{e(организация)}</p>
{''.join(страницы)}
</body></html>"""


async def item_history(db: AsyncSession, cid, item_uuid: str, date_from, date_to,
                       stations: list[int] | None = None) -> dict:
    """История товара за период по журналу станций: остаток на начало, каждое
    движение с остатком после него, остаток на конец — по станции и месту.
    Тот же ответ, что «История движений» в карточке на станции."""
    д1 = date.fromisoformat(date_from) if date_from else date(2000, 1, 1)
    д2, конец = _граница(date_to)
    начало = datetime.combine(д1, time.min, tzinfo=_МСК)
    p = {"cid": cid, "u": item_uuid, "d1": начало, "end": конец}
    ф = _станции(stations, p)
    стартовые = {(r[0], r[1]): float(r[2]) for r in (await db.execute(text(f"""
        SELECT m.station_id, m.place, sum(m.quantity) FROM store_stock_moves m
         WHERE m.company_id = :cid AND m.item_uuid = :u{ф} AND m.event_time < :d1
         GROUP BY 1, 2
    """), p)).all()}
    движения = (await db.execute(text(f"""
        SELECT m.station_id, m.place, coalesce(pl.name, m.place) AS place_name,
               m.event_time, m.barcode, m.doc_kind, m.doc_number, m.quantity, m.note
          FROM store_stock_moves m
          LEFT JOIN edge.place pl ON pl.station_id = m.station_id AND pl.code = m.place
         WHERE m.company_id = :cid AND m.item_uuid = :u{ф}
           AND m.event_time >= :d1 AND m.event_time < :end
         ORDER BY m.station_id, m.place, m.event_time, m.move_id
    """), p)).mappings().all()
    имена = {(r[0], r[1]): r[2] for r in (await db.execute(text("""
        SELECT station_id, code, name FROM edge.place"""))).all()}
    остаток = dict(стартовые)
    строки = []
    for (ст, место), кол in sorted(стартовые.items()):
        строки.append({"station_id": ст, "place": имена.get((ст, место), место),
                       "at": f"{д1:%d.%m.%Y}", "doc_kind": "остаток на начало",
                       "quantity": None, "balance": round(кол, 3), "kind": "остаток"})
    for r in движения:
        k = (r["station_id"], r["place"])
        остаток[k] = остаток.get(k, 0.0) + float(r["quantity"])
        строки.append({"station_id": r["station_id"], "place": r["place_name"],
                       "at": r["event_time"].astimezone(_МСК).strftime("%d.%m.%Y %H:%M"),
                       "barcode": r["barcode"], "doc_kind": ВИДЫ.get(r["doc_kind"], r["doc_kind"]),
                       "doc_number": r["doc_number"], "quantity": float(r["quantity"]),
                       "balance": round(остаток[k], 3), "note": r["note"]})
    строки.sort(key=lambda s: (s["station_id"], str(s["place"]), s.get("kind") != "остаток"))
    for (ст, место), кол in sorted(остаток.items()):
        строки.append({"station_id": ст, "place": имена.get((ст, место), место),
                       "at": f"{д2:%d.%m.%Y}", "doc_kind": "остаток на конец",
                       "quantity": None, "balance": round(кол, 3), "kind": "итог"})
    return {"rows": строки, "moves": len(движения),
            "opening": round(sum(стартовые.values()), 3),
            "closing": round(sum(остаток.values()), 3),
            "loaded_through": await _загружено(db, cid, stations)}


ИСТОРИЯ_КОЛОНКИ = ["АЗС", "Место", "Когда", "Штрихкод", "Вид", "Документ",
                   "Количество", "Остаток после", "Пояснение"]
ИСТОРИЯ_ПОЛЯ = ["station_id", "place", "at", "barcode", "doc_kind", "doc_number",
                "quantity", "balance", "note"]
