"""Отчёты складского учёта оборудования: остатки на дату, оборотная ведомость,
что числится за контрагентом, единицы в ремонте.

Всё считается из журнала движений, а не из текущего состояния карточки: вопрос
«что лежало у хранителя на 30 сентября» текущим состоянием не отвечается.
Положение единицы на дату — её последнее движение не позже этой даты (порядок:
дата операции, затем время записи). Отмена документа — сторнирующее движение той
же датой, поэтому правило работает и для отмен без особых случаев.

Единицы без единого движения (пришли разовым импортом) показываются по текущему
состоянию на любую дату с пометкой «без истории движений»: в оборотах они дают
только остаток.

Раздел ведёт складские предметы, а не точки: станция, введённая в эксплуатацию,
со складского учёта выбывает и возвращается только демонтажем. В остаток склада
входят состояния «на складе» и «резерв»; монтаж и ремонт — на учёте, но вне
складов; эксплуатация, возврат производителю и списание — справочно.

Расчёт — чистые функции над списками (сотни единиц и движений), загрузка из базы
отдельно внизу: так отчёты проверяются тестом без базы.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contract, Counterparty, EzsEquipmentDocument, EzsEquipmentMovement, EzsEquipmentUnit,
    EzsSparePart, EzsSparePartMovement,
)
from app.services.ezs_equipment import OP_LABELS, STATE_LABELS, STOCK_STATES
from app.services.ezs_equipment_docs import OWNERSHIP, REPAIR_KINDS, _locs

# Где единица с точки зрения склада; порядок — порядок строк сводки.
PLACES = {"unknown": "Склад не указан", "installation": "Передано в монтаж", "repair": "У подрядчика, в ремонте",
          "vendor": "Возвращено производителю", "written_off": "Списано", "operation": "Передано в эксплуатацию"}
_OFF_STOCK = {"in_installation": "installation", "in_repair": "repair", "returned_to_vendor": "vendor",
              "written_off": "written_off", "in_operation": "operation"}
# stock — складской остаток; out — на учёте, но вне складов; gone — выбыло, справочно.
SECTIONS = {"warehouse": "stock", "unknown": "stock", "installation": "out", "repair": "out",
            "vendor": "gone", "written_off": "gone", "operation": "gone"}
IN_STOCK = STOCK_STATES | {"reserved"}
# В оборотке монтаж и ввод — одно выбытие со склада, демонтаж — возврат на него.
TURNOVER_LABELS = {"to_installation": "Выбыло в монтаж / в эксплуатацию", "commissioning": "Выбыло в монтаж / в эксплуатацию",
                   "dismantle": "Возвращено из эксплуатации"}
CONTRACT_STATUS = {"active": "Действует", "expired": "Истёк", "closed": "Закрыт", "missing": "Нет договора"}
SPARE_OP_LABELS = {"receipt": "Поступление", "issue": "Расход", "transfer": "Перемещение",
                   "write_off": "Списание", "correction": "Корректировка"}


def op_label(op: str) -> str:
    return TURNOVER_LABELS.get(op) or OP_LABELS.get(op, "Отмена документа" if op == "cancel" else op)


def stock_key(state, location_id, locs) -> str | None:
    """Склад, в остатке которого числится единица; None — она не на складе."""
    loc = locs.get(location_id)
    return loc.id if loc is not None and loc.type == "warehouse" and state in IN_STOCK else None


def unit_moves(moves) -> dict[Any, list]:
    """Движения по единицам в порядке учёта: дата операции, затем время записи."""
    out: dict[Any, list] = {}
    for m in sorted(moves, key=lambda m: (m.occurred_on, m.created_at)):
        out.setdefault(m.unit_id, []).append(m)
    return out


def position(unit, own: list, day: str) -> dict[str, Any] | None:
    """Положение единицы на дату: состояние, место, с какой даты там, последнее движение.

    None — карточки на эту дату ещё не было (первое движение — поступление — позже)."""
    if not own:
        return {"state": unit.state, "location_id": unit.current_location_id, "since": None,
                "move": None, "no_history": True}
    pos = None
    for m in own:
        if m.occurred_on > day:
            break
        state = m.to_state or (pos["state"] if pos else m.from_state)
        same = pos is not None and pos["location_id"] == m.to_location_id and (m.to_location_id or pos["state"] == state)
        pos = {"state": state, "location_id": m.to_location_id, "since": pos["since"] if same else m.occurred_on,
               "move": m, "no_history": False}
    if pos is None:
        first = own[0]
        if not first.from_state:
            return None
        # До первого движения единица была там, откуда оно её забрало.
        pos = {"state": first.from_state, "location_id": first.from_location_id, "since": None,
               "move": None, "no_history": False}
    return pos


def _cancelled(m, docs) -> bool:
    d = docs.get(m.document_id) if m.document_id else None
    return d is not None and getattr(d, "status", "posted") == "cancelled"


def _doc(m, docs):
    """Документ-основание движения; отменённый документ и сама отмена основанием не считаются."""
    if m is None or m.op == "cancel" or not m.document_id or _cancelled(m, docs):
        return None
    return docs.get(m.document_id)


def wh_meta(loc) -> dict[str, Any]:
    return ((loc.extra_metadata or {}).get("warehouse") or {}) if loc is not None and loc.type == "warehouse" else {}


def unit_rows(units, moves, docs, locs, day: str) -> list[dict[str, Any]]:
    """Построчно: где и в каком состоянии каждая единица на дату."""
    by_unit = unit_moves(moves)
    rows = []
    for u in units:
        pos = position(u, by_unit.get(u.id, []), day)
        if pos is None:
            continue
        loc = locs.get(pos["location_id"])
        key = stock_key(pos["state"], pos["location_id"], locs)
        kind = "warehouse" if key else _OFF_STOCK.get(pos["state"], "unknown")
        key = key or kind
        m, d = pos["move"], _doc(pos["move"], docs)
        rows.append({
            "id": str(u.id), "serialNumber": u.serial_number, "inventoryNumber": u.inventory_number,
            "vendor": u.vendor or u.brand, "model": u.model,
            "state": pos["state"], "stateLabel": STATE_LABELS.get(pos["state"], pos["state"]),
            "placeKey": key, "placeKind": kind, "place": loc.name if loc is not None and kind in ("warehouse", "installation") else PLACES[kind],
            "since": pos["since"], "noHistory": pos["no_history"],
            "docId": str(d.id) if d else None, "docNumber": d.number if d else None,
            "basis": m.basis if m else None,
            "counterpartyId": str(d.counterparty_id) if d and d.counterparty_id else None,
            "counterpartyName": d.counterparty_name if d else m.counterparty if m else u.custodian_name if pos["no_history"] else None,
            "contractId": str(d.contract_id) if d and d.contract_id else None,
            "contractLabel": d.contract_label if d else None,
            "keeper": u.keeper,
        })
    return rows


def filter_rows(rows, locs, location_id=None, counterparty_id=None, contract_id=None) -> list[dict[str, Any]]:
    """Отбор: склад; контрагент и договор — по карточке склада либо по документу последнего движения."""
    def ok(r):
        loc = locs.get(r["placeKey"])
        w = wh_meta(loc)
        # Единица на складе числится за владельцем склада; документ последнего движения
        # говорит о держателе, только пока она вне складов (ремонт, возврат).
        doc_cp, doc_ct = (None, None) if loc is not None else (r["counterpartyId"], r["contractId"])
        return ((not location_id or r["placeKey"] == location_id)
                and (not counterparty_id or counterparty_id in (w.get("counterpartyId"), doc_cp))
                and (not contract_id or contract_id in (w.get("contractId"), doc_ct)))
    return [r for r in rows if ok(r)]


def place_groups(rows, locs) -> list[dict[str, Any]]:
    """Сводка: склады по названию, затем вне складов и выбывшее; в разрезе состояний."""
    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        g = groups.setdefault(r["placeKey"], {
            "key": r["placeKey"], "kind": r["placeKind"], "section": SECTIONS[r["placeKind"]],
            "name": r["place"] if r["placeKind"] == "warehouse" else PLACES[r["placeKind"]],
            "total": 0, "noHistory": 0, "byState": Counter()})
        g["total"] += 1
        g["noHistory"] += r["noHistory"]
        g["byState"][r["state"]] += 1
    order = list(PLACES)
    return sorted(groups.values(), key=lambda g: (g["kind"] != "warehouse", order.index(g["kind"]) if g["kind"] in order else 0, g["name"]))


# ── ЗИП: количественный учёт, остаток на дату — сумма движений ───────────────

def spare_flows(moves) -> tuple[list[tuple[str, Any, str, float, str]], int]:
    """Движения ЗИП как знаковые изменения остатка (дата, номенклатура, склад, изменение, операция).

    Второе значение — число корректировок без величины изменения: старая запись
    корректировки хранит новый остаток, а не разницу, и в обороты не ложится."""
    out, unknown = [], 0
    for m in moves:
        qty = float(m.qty)
        if m.op == "correction":
            delta = getattr(m, "delta", None)
            if delta is None:
                unknown += 1
            elif m.to_location_id:
                out.append((m.occurred_on, m.part_id, m.to_location_id, float(delta), m.op))
            continue
        if m.op != "receipt" and m.from_location_id:
            out.append((m.occurred_on, m.part_id, m.from_location_id, -qty, m.op))
        if m.op in ("receipt", "transfer") and m.to_location_id:
            out.append((m.occurred_on, m.part_id, m.to_location_id, qty, m.op))
    return out, unknown


def spare_stock(moves, day: str) -> tuple[dict[tuple[Any, str], float], int]:
    """Остаток ЗИП по паре (номенклатура, склад) на дату."""
    flows, unknown = spare_flows(moves)
    out: Counter = Counter()
    for d, part, loc, delta, _ in flows:
        if d <= day:
            out[(part, loc)] += delta
    return {k: round(v, 3) for k, v in out.items() if round(v, 3)}, unknown


def _turn() -> dict[str, Any]:
    return {"opening": 0, "closing": 0, "income": Counter(), "outcome": Counter(), "noHistory": 0}


def spare_turnover(moves, date_from: str, date_to: str) -> tuple[dict[tuple[Any, str], dict[str, Any]], int]:
    flows, unknown = spare_flows(moves)
    out: dict[tuple[Any, str], dict[str, Any]] = {}
    for d, part, loc, delta, op in flows:
        if d > date_to:
            continue
        t = out.setdefault((part, loc), _turn())
        t["closing"] += delta
        if d < date_from:
            t["opening"] += delta
        else:
            t["income" if delta > 0 else "outcome"][op] += abs(delta)
    return out, unknown


# ── Оборотная ведомость по единицам ─────────────────────────────────────────

def units_turnover(units, moves, locs, date_from: str, date_to: str) -> dict[str, dict[str, Any]]:
    """По каждому складу: начальный остаток, приход и расход по операциям, конечный остаток (шт.).

    Приход и расход — движение внутри периода, после которого единица числится на
    другом складе или не на складе вовсе (монтаж, ремонт), поэтому
    начальный + приход − расход = конечный по построению. Единица в эксплуатации
    в остаток склада не входит: её приход — только демонтаж."""
    out = {l.id: _turn() for l in locs.values() if l.type == "warehouse"}
    before = (date.fromisoformat(date_from) - timedelta(days=1)).isoformat()
    by_unit = unit_moves(moves)
    for u in units:
        own = by_unit.get(u.id, [])
        pos = position(u, own, before)
        state = pos["state"] if pos else None
        wh = stock_key(state, pos["location_id"], locs) if pos else None
        if wh:
            out[wh]["opening"] += 1
            out[wh]["noHistory"] += not own
        for m in own:
            if m.occurred_on > date_to:
                break
            state = m.to_state or state or m.from_state
            if m.occurred_on < date_from:
                continue
            to = stock_key(state, m.to_location_id, locs)
            if to != wh:
                if wh:
                    out[wh]["outcome"][m.op] += 1
                if to:
                    out[to]["income"][m.op] += 1
                wh = to
        if wh:
            out[wh]["closing"] += 1
    return out


def _turn_out(t: dict[str, Any], labels=op_label) -> dict[str, Any]:
    def by_op(c):
        merged: Counter = Counter()
        for op, n in sorted(c.items()):
            merged[labels(op)] += n
        return [{"label": label, "qty": round(n, 3)} for label, n in merged.items()]
    return {"opening": round(t["opening"], 3), "income": round(sum(t["income"].values()), 3),
            "outcome": round(sum(t["outcome"].values()), 3), "closing": round(t["closing"], 3),
            "incomeByOp": by_op(t["income"]), "outcomeByOp": by_op(t["outcome"]), "noHistory": t["noHistory"]}


# ── Что числится за контрагентом ────────────────────────────────────────────

def contract_info(c, day: str) -> dict[str, Any]:
    """Договор склада и его статус НА ДАТУ отчёта, а не на сегодня."""
    if c is None:
        return {"id": None, "number": None, "date": None, "validUntil": None,
                "status": "missing", "statusLabel": CONTRACT_STATUS["missing"]}
    status = "closed" if c.is_closed else "expired" if c.valid_until and c.valid_until[:10] < day else "active"
    return {"id": str(c.id), "number": c.number, "date": c.date, "validUntil": c.valid_until,
            "status": status, "statusLabel": CONTRACT_STATUS[status]}


def holders(rows, locs, contracts: dict[str, Any], counterparties: dict[str, Any], day: str) -> list[dict[str, Any]]:
    """Группы по контрагенту: его склады с договором и единицами, плюс единицы в ремонте
    и возвращённые ему по документам. Без ключа справочника — отдельные группы по тексту."""
    groups: dict[str, dict[str, Any]] = {}

    def group(cp_id: str | None, name: str | None) -> dict[str, Any]:
        cp = counterparties.get(cp_id) if cp_id else None
        title = (cp.name if cp is not None else name) or "Держатель не указан"
        return groups.setdefault(cp_id or f"text:{title}", {
            "key": cp_id or f"text:{title}", "counterpartyId": cp_id, "name": title, "linked": bool(cp_id),
            "warehouses": [], "units": [], "total": 0})

    wh_units: dict[str, list] = {}
    for l in sorted(locs.values(), key=lambda l: l.name or ""):
        w = wh_meta(l)
        if w.get("counterpartyId"):
            wh_units[l.id] = []
            group(w["counterpartyId"], None)["warehouses"].append({
                "id": l.id, "name": l.name, "ownership": w.get("ownership"),
                "ownershipLabel": OWNERSHIP.get(w.get("ownership") or "", ""), "responsible": w.get("responsible"),
                "contract": contract_info(contracts.get(w.get("contractId") or ""), day), "units": wh_units[l.id]})
    for r in rows:
        if r["placeKey"] in wh_units:
            wh_units[r["placeKey"]].append(r)
            g = group(wh_meta(locs[r["placeKey"]])["counterpartyId"], None)
        elif r["placeKind"] in ("repair", "vendor"):
            g = group(r["counterpartyId"], r["counterpartyName"])
            g["units"].append(r)
        elif r["placeKind"] in ("warehouse", "unknown") and (r["keeper"] or "").strip() not in ("", "Общество"):
            # Хранитель текстом в карточке: на нашем складе или без места, а отвечает другой.
            g = group(None, r["keeper"].strip())
            g["units"].append(r)
        else:
            continue
        g["total"] += 1
    return sorted(groups.values(), key=lambda g: (not g["linked"], g["name"]))


# ── Единицы в ремонте ───────────────────────────────────────────────────────

def repairs(units, moves, docs, today: str) -> list[dict[str, Any]]:
    by_unit = unit_moves(moves)
    days = lambda a, b: (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days  # noqa: E731
    out = []
    for u in units:
        own = by_unit.get(u.id, [])
        pos = position(u, own, today)
        if pos is None or pos["state"] != "in_repair":
            continue
        sent = next((m for m in reversed(own) if m.op == "to_repair" and m.occurred_on <= today
                     and not _cancelled(m, docs)), None)
        d = _doc(sent, docs)
        details = (d.details or {}) if d else {}
        planned = details.get("plannedReturn")
        out.append({
            "id": str(u.id), "serialNumber": u.serial_number, "inventoryNumber": u.inventory_number,
            "vendor": u.vendor or u.brand, "model": u.model, "noHistory": pos["no_history"],
            "holder": (d.counterparty_name if d else None) or (sent.counterparty if sent else None) or u.custodian_name,
            "counterpartyId": str(d.counterparty_id) if d and d.counterparty_id else None,
            "contractLabel": d.contract_label if d else None,
            "docId": str(d.id) if d else None, "docNumber": d.number if d else None,
            "sentOn": sent.occurred_on if sent else None, "plannedReturn": planned,
            "days": days(sent.occurred_on, today) if sent else None,
            "overdueDays": max(days(planned, today), 0) if planned else 0,
            "repairKind": REPAIR_KINDS.get(details.get("repairKind") or ""), "ticketRef": details.get("ticketRef"),
        })
    return sorted(out, key=lambda r: (-r["overdueDays"], r["sentOn"] or ""))


# ── Загрузка и сборка ответов ───────────────────────────────────────────────

async def _load(db: AsyncSession, company_id) -> tuple[list, list, dict, dict]:
    U, M, D = EzsEquipmentUnit, EzsEquipmentMovement, EzsEquipmentDocument
    units = (await db.execute(select(U).where(U.company_id == company_id).order_by(U.serial_number))).scalars().all()
    moves = (await db.execute(select(M).where(M.company_id == company_id).order_by(M.occurred_on, M.created_at))).scalars().all()
    docs = {d.id: d for d in (await db.execute(select(D).where(D.company_id == company_id))).scalars().all()}
    return list(units), list(moves), docs, await _locs(db, company_id)


async def _spares(db: AsyncSession, company_id) -> tuple[dict, list]:
    P, M = EzsSparePart, EzsSparePartMovement
    parts = {p.id: p for p in (await db.execute(select(P).where(P.company_id == company_id))).scalars().all()}
    moves = (await db.execute(select(M).where(M.company_id == company_id).order_by(M.occurred_on, M.created_at))).scalars().all()
    return parts, list(moves)


async def _by_ids(db: AsyncSession, company_id, model, ids) -> dict[str, Any]:
    keys = [uuid.UUID(i) for i in {i for i in ids if i}]
    if not keys:
        return {}
    rows = (await db.execute(select(model).where(model.company_id == company_id, model.id.in_(keys)))).scalars().all()
    return {str(r.id): r for r in rows}


def _spare_row(parts, locs, key) -> dict[str, Any]:
    p, loc = parts.get(key[0]), locs.get(key[1])
    return {"partId": str(key[0]), "name": p.name if p else "—", "article": p.article if p else None,
            "unitLabel": p.unit_label if p else "шт", "locationId": key[1], "location": loc.name if loc else "—"}


async def stock_report(db: AsyncSession, company_id, day: str, location_id=None,
                       counterparty_id=None, contract_id=None) -> dict[str, Any]:
    units, moves, docs, locs = await _load(db, company_id)
    parts, spare_moves = await _spares(db, company_id)
    all_rows = unit_rows(units, moves, docs, locs, day)
    rows = filter_rows(all_rows, locs, location_id, counterparty_id, contract_id)
    # Работающие станции живут в эксплуатации: в отчёте — одним числом, без списка.
    in_operation = sum(r["placeKind"] == "operation" for r in rows)
    rows = [r for r in rows if r["placeKind"] != "operation"]
    kept = [r for r in rows if SECTIONS[r["placeKind"]] != "gone"]
    metas = {i: wh_meta(l) for i, l in locs.items()}
    cps = await _by_ids(db, company_id, Counterparty, [w.get("counterpartyId") for w in metas.values()])
    names = {i: c.name for i, c in cps.items()} | {r["counterpartyId"]: r["counterpartyName"] for r in all_rows if r["counterpartyId"]}
    stock, unknown = spare_stock(spare_moves, day)
    spares = [{**_spare_row(parts, locs, k), "qty": q} for k, q in stock.items()
              if (not location_id or k[1] == location_id)
              and (not counterparty_id or metas.get(k[1], {}).get("counterpartyId") == counterparty_id)
              and (not contract_id or metas.get(k[1], {}).get("contractId") == contract_id)]
    return {
        "date": day, "groups": place_groups(rows, locs), "units": rows, "total": len(kept),
        "noHistory": sum(r["noHistory"] for r in kept), "inOperation": in_operation,
        "states": [{"key": s, "label": STATE_LABELS[s]} for s in STATE_LABELS if any(r["state"] == s for r in kept)],
        "spares": sorted(spares, key=lambda s: (s["location"], s["name"])), "spareCorrectionsUnknown": unknown,
        # Контрагенты, по которым отбор что-то даст: из карточек складов и документов.
        "counterparties": sorted(({"id": i, "name": n or "—"} for i, n in names.items()), key=lambda c: c["name"]),
    }


async def turnover_report(db: AsyncSession, company_id, date_from: str, date_to: str, location_id=None) -> dict[str, Any]:
    units, moves, _, locs = await _load(db, company_id)
    parts, spare_moves = await _spares(db, company_id)
    by_wh = units_turnover(units, moves, locs, date_from, date_to)
    wh_rows = [{"locationId": i, "location": locs[i].name, **_turn_out(t)}
               for i, t in sorted(by_wh.items(), key=lambda kv: locs[kv[0]].name or "") if not location_id or i == location_id]
    spare, unknown = spare_turnover(spare_moves, date_from, date_to)
    spare_rows = [{**_spare_row(parts, locs, k), **_turn_out(t, lambda op: SPARE_OP_LABELS.get(op, op))}
                  for k, t in spare.items() if not location_id or k[1] == location_id]
    return {"dateFrom": date_from, "dateTo": date_to, "warehouses": wh_rows,
            "spares": sorted(spare_rows, key=lambda s: (s["location"], s["name"])), "spareCorrectionsUnknown": unknown}


async def holders_report(db: AsyncSession, company_id, day: str) -> dict[str, Any]:
    units, moves, docs, locs = await _load(db, company_id)
    metas = [wh_meta(l) for l in locs.values()]
    contracts = await _by_ids(db, company_id, Contract, [w.get("contractId") for w in metas])
    cps = await _by_ids(db, company_id, Counterparty, [w.get("counterpartyId") for w in metas])
    return {"date": day, "holders": holders(unit_rows(units, moves, docs, locs, day), locs, contracts, cps, day)}


async def repairs_report(db: AsyncSession, company_id) -> dict[str, Any]:
    units, moves, docs, _ = await _load(db, company_id)
    today = date.today().isoformat()
    items = repairs(units, moves, docs, today)
    return {"date": today, "items": items, "overdue": sum(1 for r in items if r["overdueDays"])}
