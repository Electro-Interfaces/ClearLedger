"""
Штатная загрузка ВИТРИННЫХ снимков ЦБ ЭЛСИ.АЗК через канал (F3): остатки +
инвентаризация/списание/перемещение/переоценка → StockOnHand / CbInventoryDoc /
CbMovementDoc. Раньше это делали ТОЛЬКО разовые dev-скрипты (pull_cb_*_dev.py)
с хардкод-секретами и вне оркестратора → снимки молча протухали.

Логика портирована из dev-скриптов 1:1 (те же fetch-вызовы, агрегаты, upsert по
натуральному ключу — WIPE-фикс). Период-агностично: как dev-скрипты, берём top-N
новейших документов (снимок движения) + баланс остатка. Read-only к 1С.

Вызывается из channel_orchestrator._run_cb внутри уже открытой COM-сессии.
Чистая персистенция (commit — на оркестраторе).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import CbInventoryDoc, CbMovementDoc, CbNomenclature, StockOnHand

STORE_WAREHOUSES = {"208", "20800002"}   # Торговый зал + Склад АЗС №208
_NULL_GUID = "00000000-0000-0000-0000-000000000000"


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso_or_none(v: Any) -> str | None:
    s = str(v or "")
    return None if (not s or s.startswith("0001")) else s[:19]


async def _wh_map(client) -> dict:
    """GUID склада → (код, имя). Код 1С — фикс-ширина → strip."""
    skl = await client.fetch_entity("Catalog_Склады", select=["Ref_Key", "Code", "Description"], top=500)
    return {r.get("Ref_Key"): (str(r.get("Code") or "").strip(), str(r.get("Description") or "")) for r in skl}


async def _names(db, cid) -> dict:
    return {n.external_ref: n.name for n in (await db.execute(
        select(CbNomenclature).where(CbNomenclature.company_id == cid))).scalars().all()}


# asyncpg держит ≤ 32767 параметров на запрос (N строк × M колонок). Батчим по 400
# строк — с запасом под любую таблицу (напр. revaluation: 6000×11 > лимит без батча).
_BATCH = 400


async def _upsert(db, model, rows: list[dict], index_elements: list[str], upd_cols: list[str]) -> None:
    for i in range(0, len(rows), _BATCH):
        chunk = rows[i:i + _BATCH]
        stmt = pg_insert(model).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=index_elements,
            set_={**{c: getattr(stmt.excluded, c) for c in upd_cols}, "snapshot_at": func.now()},
        )
        await db.execute(stmt)


async def _upsert_movement(db, rows: list[dict], upd_cols: list[str]) -> None:
    await _upsert(db, CbMovementDoc, rows, ["company_id", "kind", "external_ref"], upd_cols)


# ---------------------------------------------------------------------------
# Списания (CbMovementDoc kind='writeoff')
# ---------------------------------------------------------------------------
def _writeoff_reason(from_inv: bool, comment: str | None) -> str:
    c = (comment or "").lower()
    if "передача дня" in c or "день x" in c or "день икс" in c:
        return "Передача Дня X"
    if from_inv:
        return "Инвентаризация (недостача)"
    if "брак" in c:
        return "Брак"
    if "пересорт" in c or "перессорт" in c:
        return "Пересортица"
    if "срок" in c or "просроч" in c:
        return "Срок годности"
    if "порч" in c:
        return "Порча"
    if "приказ" in c:
        return "Приказ"
    return "Прочее"


async def ingest_writeoff(db, cid, client, names: dict, wh: dict) -> int:
    DOC = "СписаниеТоваров"
    hdr = await client.fetch_entity(
        f"Document_{DOC}",
        select=["Ref_Key", "Number", "Date", "Posted", "DeletionMark", "Склад_Key",
                "Комментарий", "ИнвентаризацияТоваровНаСкладе", "СуммаДокумента"],
        orderby="Date УБЫВ", top=2000,
    )
    lines = await client.query_tabular(
        DOC, "Товары",
        select=["Ссылка", "Ссылка.Склад", "НомерСтроки", "Номенклатура", "Количество", "Сумма", "Цена"],
        top=200000,
    )
    by_doc: dict[str, dict] = defaultdict(lambda: {"pos": 0, "qty": 0.0, "amt": 0.0, "lines": []})
    for r in lines:
        code = wh.get(r.get("Ссылка.Склад"), ("?", ""))[0]
        if code not in STORE_WAREHOUSES:
            continue
        ref = str(r.get("Ссылка") or "")
        nom = str(r.get("Номенклатура") or "")
        qty = _num(r.get("Количество")); amt = _num(r.get("Сумма"))
        a = by_doc[ref]
        a["pos"] += 1; a["qty"] += qty; a["amt"] += amt
        if len(a["lines"]) < 500:
            a["lines"].append({
                "n": int(_num(r.get("НомерСтроки"))) or (len(a["lines"]) + 1),
                "ref": nom, "name": names.get(nom, nom[:8]),
                "qty": round(qty, 3), "amount": round(amt, 2), "price": _num(r.get("Цена")),
            })
    rows = []
    for h in hdr:
        code = wh.get(h.get("Склад_Key"), ("?", ""))[0]
        if code not in STORE_WAREHOUSES:
            continue
        ref = str(h.get("Ref_Key") or "")
        inv = h.get("ИнвентаризацияТоваровНаСкладе")
        from_inv = bool(inv and str(inv) != _NULL_GUID)
        comment = (str(h.get("Комментарий")) or None) if h.get("Комментарий") else None
        a = by_doc.get(ref, {"pos": 0, "qty": 0.0, "amt": 0.0, "lines": []})
        rows.append(dict(
            company_id=cid, kind="writeoff", external_ref=ref,
            number=(str(h.get("Number")) if h.get("Number") else None),
            doc_date=(str(h.get("Date"))[:10] if h.get("Date") else None),
            posted=bool(h.get("Posted")), deleted=bool(h.get("DeletionMark")),
            inventory_ref=(str(inv) if from_inv else None),
            warehouse_code=code, warehouse_name=wh.get(h.get("Склад_Key"), ("?", ""))[1],
            comment=comment, reason=_writeoff_reason(from_inv, comment), from_inventory=from_inv,
            positions=a["pos"], total_qty=round(a["qty"], 3),
            total_amount=round(a["amt"], 2) if a["amt"] else _num(h.get("СуммаДокумента")),
            lines=(sorted(a["lines"], key=lambda x: x["n"]) or None),
        ))
    await _upsert_movement(db, rows, [
        "number", "doc_date", "posted", "deleted", "inventory_ref", "warehouse_code",
        "warehouse_name", "comment", "reason", "from_inventory", "positions",
        "total_qty", "total_amount", "lines"])
    return len(rows)


# ---------------------------------------------------------------------------
# Перемещения (CbMovementDoc kind='transfer')
# ---------------------------------------------------------------------------
def _transfer_direction(src: str, dst: str) -> str:
    si, di = src in STORE_WAREHOUSES, dst in STORE_WAREHOUSES
    if si and di:
        return "Внутреннее (склад↔зал)"
    if di:
        return "Приход (на 208)"
    if si:
        return "Расход (с 208)"
    return "Прочее"


async def ingest_transfer(db, cid, client, names: dict, wh: dict) -> int:
    DOC = "ПеремещениеТоваров"
    hdr = await client.fetch_entity(
        f"Document_{DOC}",
        select=["Ref_Key", "Number", "Date", "Posted", "DeletionMark",
                "СкладОтправитель_Key", "СкладПолучатель_Key", "Комментарий"],
        orderby="Date УБЫВ", top=2000,
    )
    lines = await client.query_tabular(
        DOC, "Товары",
        select=["Ссылка", "Ссылка.СкладОтправитель", "Ссылка.СкладПолучатель",
                "НомерСтроки", "Номенклатура", "Количество", "Цена", "Себестоимость"],
        top=200000,
    )

    def _involved(src_g, dst_g) -> bool:
        return wh.get(src_g, ("?", ""))[0] in STORE_WAREHOUSES or wh.get(dst_g, ("?", ""))[0] in STORE_WAREHOUSES

    by_doc: dict[str, dict] = defaultdict(lambda: {"pos": 0, "qty": 0.0, "amt": 0.0, "lines": []})
    for r in lines:
        if not _involved(r.get("Ссылка.СкладОтправитель"), r.get("Ссылка.СкладПолучатель")):
            continue
        ref = str(r.get("Ссылка") or "")
        nom = str(r.get("Номенклатура") or "")
        qty = _num(r.get("Количество")); price = _num(r.get("Цена"))
        amt = qty * price
        a = by_doc[ref]
        a["pos"] += 1; a["qty"] += qty; a["amt"] += amt
        if len(a["lines"]) < 500:
            a["lines"].append({
                "n": int(_num(r.get("НомерСтроки"))) or (len(a["lines"]) + 1),
                "ref": nom, "name": names.get(nom, nom[:8]),
                "qty": round(qty, 3), "price": round(price, 2), "amount": round(amt, 2),
                "cost": round(_num(r.get("Себестоимость")), 2),
            })
    rows = []
    for h in hdr:
        src_g, dst_g = h.get("СкладОтправитель_Key"), h.get("СкладПолучатель_Key")
        if not _involved(src_g, dst_g):
            continue
        src = wh.get(src_g, ("?", "")); dst = wh.get(dst_g, ("?", ""))
        ref = str(h.get("Ref_Key") or "")
        a = by_doc.get(ref, {"pos": 0, "qty": 0.0, "amt": 0.0, "lines": []})
        rows.append(dict(
            company_id=cid, kind="transfer", external_ref=ref,
            number=(str(h.get("Number")) if h.get("Number") else None),
            doc_date=(str(h.get("Date"))[:10] if h.get("Date") else None),
            posted=bool(h.get("Posted")), deleted=bool(h.get("DeletionMark")),
            warehouse_code=src[0], warehouse_name=src[1],
            warehouse_to_code=dst[0], warehouse_to_name=dst[1],
            comment=((str(h.get("Комментарий")) or None) if h.get("Комментарий") else None),
            reason=_transfer_direction(src[0], dst[0]), from_inventory=False,
            positions=a["pos"], total_qty=round(a["qty"], 3), total_amount=round(a["amt"], 2),
            lines=(sorted(a["lines"], key=lambda x: x["n"]) or None),
        ))
    await _upsert_movement(db, rows, [
        "number", "doc_date", "posted", "deleted", "warehouse_code", "warehouse_name",
        "warehouse_to_code", "warehouse_to_name", "comment", "reason", "from_inventory",
        "positions", "total_qty", "total_amount", "lines"])
    return len(rows)


# ---------------------------------------------------------------------------
# Переоценка (CbMovementDoc kind='revaluation')
# ---------------------------------------------------------------------------
def _reval_reason(up: int, down: int) -> str:
    if up and not down:
        return "Подорожание"
    if down and not up:
        return "Удешевление"
    if up and down:
        return "Смешанная"
    return "Без изменений"


async def ingest_revaluation(db, cid, client, names: dict, wh: dict) -> int:
    DOC = "ПереоценкаТоваровАЗК"
    hdr = await client.fetch_entity(
        f"Document_{DOC}",
        select=["Ref_Key", "Number", "Date", "Склад_Key", "Комментарий"],
        orderby="Date УБЫВ", top=6000,
    )
    lines = await client.query_tabular(
        DOC, "Товары",
        select=["Ссылка", "Ссылка.Склад", "Номенклатура", "ЦенаВРозницеСтарая", "ЦенаВРознице", "Количество"],
        where="Т.ЦенаВРознице <> Т.ЦенаВРозницеСтарая", top=200000,
    )
    by_doc: dict[str, dict] = defaultdict(lambda: {"pos": 0, "up": 0, "down": 0, "impact": 0.0, "lines": []})
    for r in lines:
        code = wh.get(r.get("Ссылка.Склад"), ("?", ""))[0]
        if code not in STORE_WAREHOUSES:
            continue
        ref = str(r.get("Ссылка") or "")
        nom = str(r.get("Номенклатура") or "")
        old = _num(r.get("ЦенаВРозницеСтарая")); new = _num(r.get("ЦенаВРознице"))
        qty = _num(r.get("Количество"))
        delta = new - old
        pct = (100.0 * delta / old) if old else None
        a = by_doc[ref]
        a["pos"] += 1
        if delta > 0:
            a["up"] += 1
        elif delta < 0:
            a["down"] += 1
        a["impact"] += delta * qty
        if len(a["lines"]) < 500:
            a["lines"].append({
                "ref": nom, "name": names.get(nom, nom[:8]),
                "old": round(old, 2), "new": round(new, 2), "delta": round(delta, 2),
                "pct": (round(pct, 1) if pct is not None else None), "qty": round(qty, 3),
            })
    rows = []
    for h in hdr:
        code = wh.get(h.get("Склад_Key"), ("?", ""))[0]
        if code not in STORE_WAREHOUSES:
            continue
        ref = str(h.get("Ref_Key") or "")
        a = by_doc.get(ref)
        if not a:   # переоценка без фактических изменений цены — пропускаем
            continue
        rows.append(dict(
            company_id=cid, kind="revaluation", external_ref=ref,
            number=(str(h.get("Number")) if h.get("Number") else None),
            doc_date=(str(h.get("Date"))[:10] if h.get("Date") else None),
            warehouse_code=code, warehouse_name=wh.get(h.get("Склад_Key"), ("?", ""))[1],
            comment=((str(h.get("Комментарий")) or None) if h.get("Комментарий") else None),
            reason=_reval_reason(a["up"], a["down"]), from_inventory=False,
            positions=a["pos"], total_qty=a["up"], total_amount=round(a["impact"], 2),
            lines=(sorted(a["lines"], key=lambda x: (x["pct"] if x["pct"] is not None else 0)) or None),
        ))
    await _upsert_movement(db, rows, [
        "number", "doc_date", "warehouse_code", "warehouse_name", "comment", "reason",
        "from_inventory", "positions", "total_qty", "total_amount", "lines"])
    return len(rows)


# ---------------------------------------------------------------------------
# Инвентаризация (CbInventoryDoc)
# ---------------------------------------------------------------------------
async def ingest_inventory(db, cid, client, names: dict, wh: dict) -> int:
    DOC = "ИнвентаризацияТоваровНаСкладе"
    LINES_WHERE = 'СокрЛП(Т.Ссылка.Склад.Код) В ("208", "20800002")'
    hdr = await client.fetch_entity(
        f"Document_{DOC}",
        select=["Ref_Key", "Number", "Date", "Posted", "DeletionMark",
                "Склад_Key", "Комментарий", "ДатаЗаполнения"],
        orderby="Date УБЫВ", top=1600,
    )
    rows_tc = await client.query_tabular(
        DOC, "Товары",
        select=["Ссылка", "НомерСтроки", "Номенклатура",
                "Количество", "КоличествоУчет", "Цена", "Сумма", "СуммаУчет"],
        where=LINES_WHERE, top=300000,
    )
    agg: dict[str, dict] = defaultdict(lambda: {
        "dev_pos": 0, "sh_qty": 0.0, "sh_amt": 0.0, "su_qty": 0.0, "su_amt": 0.0, "lines": []})
    for r in rows_tc:
        ref = str(r.get("Ссылка") or "")
        nom = str(r.get("Номенклатура") or "")
        fact = _num(r.get("Количество")); uch = _num(r.get("КоличествоУчет"))
        amt = _num(r.get("Сумма")); amt_uch = _num(r.get("СуммаУчет"))
        d_qty = fact - uch
        d_amt = amt - amt_uch
        a = agg[ref]
        if abs(d_qty) > 1e-9:
            a["dev_pos"] += 1
            if d_qty < 0:
                a["sh_qty"] += d_qty; a["sh_amt"] += d_amt
            else:
                a["su_qty"] += d_qty; a["su_amt"] += d_amt
        a["lines"].append({
            "n": int(_num(r.get("НомерСтроки"))) or (len(a["lines"]) + 1),
            "ref": nom, "name": names.get(nom, nom[:8]),
            "fact": round(fact, 3), "uchet": round(uch, 3),
            "price": round(_num(r.get("Цена")), 2),
            "amount": round(amt, 2), "amount_uchet": round(amt_uch, 2),
            "dev": round(d_qty, 3), "amount_dev": round(d_amt, 2),
        })
    rows = []
    for h in hdr:
        code = wh.get(h.get("Склад_Key"), ("?", ""))[0]
        if code not in STORE_WAREHOUSES:
            continue
        ref = str(h.get("Ref_Key") or "")
        a = agg.get(ref, {"dev_pos": 0, "sh_qty": 0.0, "sh_amt": 0.0, "su_qty": 0.0, "su_amt": 0.0, "lines": []})
        rows.append(dict(
            company_id=cid, external_ref=ref,
            number=(str(h.get("Number")) if h.get("Number") else None),
            doc_date=(str(h.get("Date"))[:10] if h.get("Date") else None),
            posted=bool(h.get("Posted")), deleted=bool(h.get("DeletionMark")),
            fill_date=_iso_or_none(h.get("ДатаЗаполнения")),
            warehouse_code=code, warehouse_name=wh.get(h.get("Склад_Key"), ("?", ""))[1],
            comment=((str(h.get("Комментарий")) or None) if h.get("Комментарий") else None),
            dev_positions=a["dev_pos"],
            shortage_qty=round(a["sh_qty"], 3), shortage_amount=round(a["sh_amt"], 2),
            surplus_qty=round(a["su_qty"], 3), surplus_amount=round(a["su_amt"], 2),
            net_amount=round(a["sh_amt"] + a["su_amt"], 2),
            lines=(sorted(a["lines"], key=lambda x: x["n"]) or None),
        ))
    await _upsert(db, CbInventoryDoc, rows, ["company_id", "external_ref"], [
        "number", "doc_date", "posted", "deleted", "fill_date", "warehouse_code",
        "warehouse_name", "comment", "dev_positions", "shortage_qty", "shortage_amount",
        "surplus_qty", "surplus_amount", "net_amount", "lines"])
    return len(rows)


# ---------------------------------------------------------------------------
# Остатки (StockOnHand) — полный снимок баланса (не за период)
# ---------------------------------------------------------------------------
async def ingest_stock(db, cid, client, wh: dict) -> int:
    azk = await client.fetch_register_balance(
        "AccumulationRegister_ТоварыНаАЗК",
        dimensions=["Номенклатура", "Склад", "ЦенаВРознице", "ШтрихКод"],
        resources=["Количество"],
    )
    parts = await client.fetch_register_balance(
        "AccumulationRegister_ПартииТоваровНаСкладах",
        dimensions=["Номенклатура", "Склад"],
        resources=["Количество", "Стоимость"],
    )
    onhand: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"qty": 0.0, "pos_value": 0.0, "pos_qty": 0.0, "barcode": None})
    for r in azk:
        nom = str(r.get("Номенклатура") or "")
        whg = str(r.get("Склад") or "")
        if not nom or nom == _NULL_GUID or not whg:
            continue
        code = wh.get(whg, ("?", ""))[0]
        o = onhand[(code, nom)]
        qty = _num(r.get("Количество"))
        price_r = _num(r.get("ЦенаВРознице"))
        o["qty"] += qty
        if qty > 0:
            o["pos_value"] += qty * price_r
            o["pos_qty"] += qty
        if not o["barcode"] and r.get("ШтрихКод"):
            o["barcode"] = str(r.get("ШтрихКод"))
    pc: dict[tuple[str, str], list] = defaultdict(lambda: [0.0, 0.0])
    for r in parts:
        nom = str(r.get("Номенклатура") or "")
        whg = str(r.get("Склад") or "")
        if not nom or nom == _NULL_GUID or not whg:
            continue
        code = wh.get(whg, ("?", ""))[0]
        pc[(code, nom)][0] += _num(r.get("Количество"))
        pc[(code, nom)][1] += _num(r.get("Стоимость"))
    cost_unit = {k: (v[1] / v[0]) for k, v in pc.items()
                 if abs(v[0]) > 0.001 and (v[1] / v[0]) > 0}
    wh_name_by_code = {c: n for (c, n) in wh.values()}

    rows = []
    for (code, nom), o in onhand.items():
        qty = o["qty"]
        price = (o["pos_value"] / o["pos_qty"]) if o["pos_qty"] else None
        cu = cost_unit.get((code, nom))
        rows.append(dict(
            company_id=cid, warehouse_code=code, warehouse_name=wh_name_by_code.get(code),
            nomenclature_ref=nom, quantity=round(qty, 3),
            retail_price=(round(price, 2) if price is not None else None),
            cost_amount=None, cost_unit=(round(cu, 4) if cu is not None else None),
            barcode=o["barcode"],
        ))
    await _upsert(db, StockOnHand, rows, ["company_id", "warehouse_code", "nomenclature_ref"],
                  ["warehouse_name", "quantity", "retail_price", "cost_amount", "cost_unit", "barcode"])
    return len(rows)


# ---------------------------------------------------------------------------
# Оркестрация всех витринных типов (одна COM-сессия)
# ---------------------------------------------------------------------------
async def ingest_cb_vitrine(db, cid, client) -> dict[str, int]:
    """Обновить витринные снимки ЦБ (остатки + движение) через канал. Каждый тип
    изолирован try/except: сбой одного не валит остальные и прогон смен."""
    wh = await _wh_map(client)
    names = await _names(db, cid)
    out: dict[str, int] = {}
    for name, fn in (
        ("inventory", lambda: ingest_inventory(db, cid, client, names, wh)),
        ("writeoff", lambda: ingest_writeoff(db, cid, client, names, wh)),
        ("transfer", lambda: ingest_transfer(db, cid, client, names, wh)),
        ("revaluation", lambda: ingest_revaluation(db, cid, client, names, wh)),
        ("stock", lambda: ingest_stock(db, cid, client, wh)),
    ):
        try:
            out[name] = await fn()
        except Exception as e:
            out[name] = 0
            out[f"{name}_error"] = str(e)[:120]  # type: ignore[assignment]
    return out
