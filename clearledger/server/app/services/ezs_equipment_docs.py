"""Документы движения оборудования и карточка склада.

Складской учёт держится на бумаге: перемещение — накладная, монтаж и ввод — акт,
ремонт — акт передачи и приёма, списание — акт списания. До 04.10.2026 движение
было строкой журнала с контрагентом свободным текстом, без номера, договора и
ответственных; склад — одним названием. Учёт жил разовым импортом: 88 движений,
все «Поступление» (анализ `docs/rushydro-equipment-analysis-20261004.md`).

Документ проводит операцию сразу по нескольким единицам: переходы проверяет тот
же `apply_movement`, документ добавляет номер, дату, контрагента и договор из
справочников пространства, ответственных (кто сдал, кто принял) и основание.
Договор проверяется: этой компании, этого контрагента, не закрыт; истёкший срок —
предупреждение в ответе, а не отказ (договоры продлевают задним числом).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contract, Counterparty, EzsEquipmentDocument, EzsEquipmentMovement, EzsEquipmentUnit,
    ServiceLocation, User,
)
from app.services.ezs_equipment import OP_LABELS, STATE_LABELS, TRANSITIONS, apply_movement

# Префикс номера и название документа по операции.
DOC_KINDS: dict[str, tuple[str, str]] = {
    "transfer": ("ПМ", "Накладная на внутреннее перемещение (М-11)"),
    "reserve": ("РЗ", "Распоряжение о резервировании"),
    "unreserve": ("СР", "Распоряжение о снятии резерва"),
    "to_installation": ("МН", "Акт передачи оборудования в монтаж"),
    "commissioning": ("ВВ", "Акт о вводе в эксплуатацию (ОС-1)"),
    "dismantle": ("ДМ", "Акт демонтажа оборудования"),
    "to_repair": ("РМ", "Акт передачи оборудования в ремонт"),
    "from_repair": ("ИР", "Акт приёма оборудования из ремонта"),
    "to_vendor": ("ВП", "Акт возврата оборудования поставщику"),
    "write_off": ("СП", "Акт о списании (ОС-4)"),
    "correction": ("КР", "Акт корректировки учёта"),
}
# Какой договор подходит операции — по типу договора справочника. Подсказка для
# выбора, не запрет: тип в справочнике пишут по-разному.
CONTRACT_TYPES: dict[str, tuple[str, ...]] = {
    "to_installation": ("Монтаж/Подряд",), "commissioning": ("Монтаж/Подряд",), "dismantle": ("Монтаж/Подряд",),
    "to_repair": ("Сервисное обслуживание", "Сервис", "Техническое обслуживание ЭЗС", "Поставка ЭЗС"),
    "from_repair": ("Сервисное обслуживание", "Сервис", "Техническое обслуживание ЭЗС", "Поставка ЭЗС"),
    "to_vendor": ("Поставка ЭЗС",), "transfer": ("Аренда", "Хранение", "Ответственное хранение"),
}
# Без контрагента не бывает: железо уходит из наших рук.
COUNTERPARTY_REQUIRED = {"to_repair", "from_repair", "to_vendor"}
OWNERSHIP = {"own": "Собственный", "rent": "Арендованный", "custody": "Ответственное хранение у контрагента"}
REPAIR_KINDS = {"warranty": "Гарантийный", "paid": "Платный"}
REPAIR_RESULTS = {"repaired": "Отремонтировано", "unrepairable": "Ремонту не подлежит"}


def repair_details(op: str, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ремонт как заказ: заявка Поддержки, вид, плановый возврат, стоимость, результат."""
    if op not in ("to_repair", "from_repair") or not raw:
        return None
    out: dict[str, Any] = {}
    ticket = str(raw.get("ticketRef") or "").strip()[:60]
    if ticket:
        out["ticketRef"] = ticket
    if op == "to_repair":
        kind = raw.get("repairKind") or ""
        if kind and kind not in REPAIR_KINDS:
            raise HTTPException(400, "Неизвестный вид ремонта")
        if kind:
            out["repairKind"] = kind
        planned = str(raw.get("plannedReturn") or "")
        if planned:
            try:
                date.fromisoformat(planned)
            except ValueError:
                raise HTTPException(400, "Плановая дата возврата из ремонта указана неверно")
            out["plannedReturn"] = planned
    else:
        result = raw.get("result") or ""
        if result and result not in REPAIR_RESULTS:
            raise HTTPException(400, "Неизвестный результат ремонта")
        if result:
            out["result"] = result
    for key in ("costEstimate", "costActual"):
        if raw.get(key) not in (None, ""):
            try:
                value = round(float(raw[key]), 2)
            except (TypeError, ValueError):
                raise HTTPException(400, "Стоимость ремонта — число")
            if value < 0:
                raise HTTPException(400, "Стоимость ремонта не может быть отрицательной")
            out[key] = value
    return out or None


def _today() -> str:
    return date.today().isoformat()


async def check_counterparty(db: AsyncSession, company_id, counterparty_id) -> Counterparty | None:
    if not counterparty_id:
        return None
    cp = await db.get(Counterparty, uuid.UUID(str(counterparty_id)))
    if cp is None or cp.company_id != company_id:
        raise HTTPException(400, "Контрагент не найден в справочнике пространства")
    return cp


async def check_contract(db: AsyncSession, company_id, contract_id, counterparty_id=None) -> tuple[Contract | None, list[str]]:
    """Договор этой компании и этого контрагента, не закрыт. Возвращает предупреждения."""
    if not contract_id:
        return None, []
    c = await db.get(Contract, uuid.UUID(str(contract_id)))
    if c is None or c.company_id != company_id:
        raise HTTPException(400, "Договор не найден в справочнике пространства")
    if counterparty_id and str(c.counterparty_id) != str(counterparty_id):
        raise HTTPException(400, f"Договор № {c.number} заключён с другим контрагентом")
    if c.is_closed:
        raise HTTPException(400, f"Договор № {c.number} закрыт")
    warnings = []
    if c.valid_until and c.valid_until[:10] < _today():
        warnings.append(f"Срок договора № {c.number} истёк {c.valid_until[:10]}")
    return c, warnings


def contract_label(c: Contract | None) -> str | None:
    return f"№ {c.number} от {c.date}" + (f" ({c.type})" if c.type else "") if c else None


async def next_number(db: AsyncSession, company_id, op: str, doc_date: str) -> str:
    prefix = DOC_KINDS[op][0]
    year = doc_date[:4]
    like = f"{prefix}-{year}-%"
    n = (await db.execute(select(func.count()).select_from(EzsEquipmentDocument).where(
        EzsEquipmentDocument.company_id == company_id, EzsEquipmentDocument.number.like(like)))).scalar_one()
    return f"{prefix}-{year}-{int(n) + 1:04d}"


async def post_document(db: AsyncSession, company_id, user: User | None, p: dict[str, Any]) -> dict[str, Any]:
    op = p.get("op")
    if op not in DOC_KINDS or op not in TRANSITIONS:
        raise HTTPException(400, f"Неизвестная операция: {op}")
    unit_ids = list(dict.fromkeys(str(u) for u in (p.get("unit_ids") or [])))
    if not unit_ids:
        raise HTTPException(400, "Выберите единицы оборудования")
    if len(unit_ids) > 500:
        raise HTTPException(400, "Не больше 500 единиц в одном документе")
    doc_date = (p.get("doc_date") or "").strip()
    try:
        date.fromisoformat(doc_date)
    except ValueError:
        raise HTTPException(400, "Укажите дату документа")
    cp = await check_counterparty(db, company_id, p.get("counterparty_id"))
    if op in COUNTERPARTY_REQUIRED and cp is None:
        raise HTTPException(400, "Укажите контрагента из справочника: оборудование передаётся из наших рук")
    contract, warnings = await check_contract(db, company_id, p.get("contract_id"), cp.id if cp else None)
    if contract is not None and cp is None:
        cp = await db.get(Counterparty, contract.counterparty_id)
    number = (p.get("number") or "").strip() or await next_number(db, company_id, op, doc_date)
    clash = (await db.execute(select(EzsEquipmentDocument.id).where(
        EzsEquipmentDocument.company_id == company_id, EzsEquipmentDocument.number == number))).first()
    if clash:
        raise HTTPException(409, f"Документ № {number} уже есть")
    doc = EzsEquipmentDocument(
        company_id=company_id, op=op, number=number, doc_date=doc_date,
        counterparty_id=cp.id if cp else None, counterparty_name=cp.name if cp else None,
        contract_id=contract.id if contract else None, contract_label=contract_label(contract),
        to_location_id=p.get("to_location_id") or None,
        responsible_from=(p.get("responsible_from") or "").strip()[:200] or None,
        responsible_to=(p.get("responsible_to") or "").strip()[:200] or None,
        basis=(p.get("basis") or "").strip()[:500] or None, comment=(p.get("comment") or "").strip()[:2000] or None,
        details=repair_details(op, p.get("details")),
        created_by_id=str(user.id) if user else None,
        created_by_name=(user.name or user.email) if user else None,
    )
    db.add(doc)
    await db.flush()
    title = DOC_KINDS[op][1]
    basis = f"{title} № {number} от {doc_date}" + (f"; {doc.basis}" if doc.basis else "")
    froms = set()
    for uid in unit_ids:
        unit, move = await apply_movement(db, company_id, user, uuid.UUID(uid), {
            "op": op, "to_location_id": doc.to_location_id, "occurred_on": doc_date,
            "counterparty": cp.name if cp else None, "basis": basis, "comment": doc.comment,
            "custodian": p.get("custodian"), "reserved_for_location_id": p.get("reserved_for_location_id"),
            "to_state": p.get("to_state"), "sync_passport": bool(p.get("sync_passport")),
            "keep_location": op == "correction" and not doc.to_location_id,
        })
        move.document_id = doc.id
        froms.add(move.from_location_id)
    if len(froms) == 1:
        doc.from_location_id = froms.pop()
    await db.flush()
    out = await get_document(db, company_id, doc.id)
    out["warnings"] = warnings
    return out


def _doc_head(d: EzsEquipmentDocument, locs: dict[str, ServiceLocation], units: int | None = None) -> dict[str, Any]:
    name = lambda i: locs[i].name if i and i in locs else None  # noqa: E731
    return {
        "id": str(d.id), "op": d.op, "opLabel": OP_LABELS.get(d.op, d.op), "title": DOC_KINDS.get(d.op, ("", d.op))[1],
        "number": d.number, "docDate": d.doc_date,
        "counterpartyId": str(d.counterparty_id) if d.counterparty_id else None, "counterpartyName": d.counterparty_name,
        "contractId": str(d.contract_id) if d.contract_id else None, "contractLabel": d.contract_label,
        "fromLocation": name(d.from_location_id), "toLocation": name(d.to_location_id),
        "responsibleFrom": d.responsible_from, "responsibleTo": d.responsible_to,
        "basis": d.basis, "comment": d.comment, "createdBy": d.created_by_name,
        "details": d.details or {},
        "createdAt": d.created_at.isoformat() if d.created_at else None, "units": units,
    }


async def _locs(db, company_id) -> dict[str, ServiceLocation]:
    rows = (await db.execute(select(ServiceLocation).where(ServiceLocation.company_id == company_id))).scalars().all()
    return {l.id: l for l in rows}


async def get_document(db: AsyncSession, company_id, doc_id) -> dict[str, Any]:
    d = await db.get(EzsEquipmentDocument, uuid.UUID(str(doc_id)))
    if d is None or d.company_id != company_id:
        raise HTTPException(404, "Документ не найден")
    locs = await _locs(db, company_id)
    rows = (await db.execute(select(EzsEquipmentMovement, EzsEquipmentUnit).join(
        EzsEquipmentUnit, EzsEquipmentUnit.id == EzsEquipmentMovement.unit_id).where(
        EzsEquipmentMovement.document_id == d.id).order_by(EzsEquipmentUnit.serial_number))).all()
    name = lambda i: locs[i].name if i and i in locs else None  # noqa: E731
    lines = [{
        "unitId": str(u.id), "serialNumber": u.serial_number, "inventoryNumber": u.inventory_number,
        "vendor": u.vendor or u.brand, "model": u.model, "powerKwt": float(u.power_kwt) if u.power_kwt is not None else None,
        "purchaseAmount": float(u.purchase_amount) if u.purchase_amount is not None else None,
        "from": name(m.from_location_id), "to": name(m.to_location_id),
        "fromState": STATE_LABELS.get(m.from_state or "", m.from_state), "toState": STATE_LABELS.get(m.to_state or "", m.to_state),
    } for m, u in rows]
    return {**_doc_head(d, locs, len(lines)), "lines": lines}


async def list_documents(db: AsyncSession, company_id, *, op=None, q=None, date_from=None, date_to=None,
                         limit: int = 50, offset: int = 0) -> dict[str, Any]:
    D = EzsEquipmentDocument
    where = [D.company_id == company_id]
    if op:
        where.append(D.op == op)
    if date_from:
        where.append(D.doc_date >= date_from)
    if date_to:
        where.append(D.doc_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        where.append(D.number.ilike(like) | D.counterparty_name.ilike(like) | D.contract_label.ilike(like)
                     | D.responsible_from.ilike(like) | D.responsible_to.ilike(like))
    total = (await db.execute(select(func.count()).select_from(D).where(*where))).scalar_one()
    docs = (await db.execute(select(D).where(*where).order_by(D.doc_date.desc(), D.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    counts = dict((await db.execute(select(EzsEquipmentMovement.document_id, func.count()).where(
        EzsEquipmentMovement.document_id.in_([d.id for d in docs] or [None])).group_by(EzsEquipmentMovement.document_id))).all())
    locs = await _locs(db, company_id)
    return {"items": [_doc_head(d, locs, int(counts.get(d.id, 0))) for d in docs], "total": int(total)}


# ── Карточка склада ─────────────────────────────────────────────────────────
# Реквизиты склада живут в `extra_metadata.warehouse` точки: отдельная таблица на
# шесть складов не нужна, а точка — уже общий объект пространства.

async def warehouse_card(db: AsyncSession, company_id, loc: ServiceLocation) -> dict[str, Any]:
    w = dict((loc.extra_metadata or {}).get("warehouse") or {})
    status = None
    if w.get("contractId"):
        c = await db.get(Contract, uuid.UUID(w["contractId"]))
        if c is not None and c.company_id == company_id:
            w["contractLabel"] = contract_label(c)
            w["contractValidUntil"] = c.valid_until
            expired = bool(c.valid_until and c.valid_until[:10] < _today())
            status = "closed" if c.is_closed else "expired" if expired else "active"
    if w.get("counterpartyId"):
        cp = await db.get(Counterparty, uuid.UUID(w["counterpartyId"]))
        if cp is not None and cp.company_id == company_id:
            w["counterpartyName"] = cp.name
    w["ownershipLabel"] = OWNERSHIP.get(w.get("ownership") or "", "")
    # Чужой склад без действующего договора — то, что сегодня лежит в «Хранителе»
    # текстом («договор хранения закончился»): подсвечивается, а не теряется.
    w["contractStatus"] = status or ("missing" if w.get("ownership") in ("rent", "custody") else None)
    return {"id": loc.id, "name": loc.name, "address": loc.address, **w}


async def save_warehouse(db: AsyncSession, company_id, loc_id: str | None, p: dict[str, Any]) -> dict[str, Any]:
    from app.services.ezs_equipment import get_or_create_warehouse
    if loc_id:
        loc = await db.get(ServiceLocation, loc_id)
        if loc is None or loc.company_id != company_id or loc.type != "warehouse":
            raise HTTPException(404, "Склад не найден")
    else:
        name = (p.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "Укажите название склада")
        loc = await get_or_create_warehouse(db, company_id, name)
    ownership = p.get("ownership") or "own"
    if ownership not in OWNERSHIP:
        raise HTTPException(400, "Неизвестный вид владения складом")
    cp = await check_counterparty(db, company_id, p.get("counterpartyId"))
    contract, _ = await check_contract(db, company_id, p.get("contractId"), cp.id if cp else None) if p.get("contractId") else (None, [])
    if ownership in ("rent", "custody") and cp is None:
        raise HTTPException(400, "Для арендованного склада или ответственного хранения укажите контрагента")
    if p.get("name") and loc_id:
        loc.name = p["name"].strip()[:300]
    if "address" in p:
        loc.address = (p.get("address") or "").strip()[:500] or None
    meta = dict(loc.extra_metadata or {})
    meta["warehouse"] = {
        "ownership": ownership, "counterpartyId": str(cp.id) if cp else None,
        "contractId": str(contract.id) if contract else None,
        "responsible": (p.get("responsible") or "").strip()[:200] or None,
        "phone": (p.get("phone") or "").strip()[:60] or None,
        "note": (p.get("note") or "").strip()[:1000] or None,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    loc.extra_metadata = meta
    await db.flush()
    return await warehouse_card(db, company_id, loc)


# ── Разбор данных ───────────────────────────────────────────────────────────
# Учёт оборудования пришёл разовым импортом (21.08.2026) и с тех пор не вёлся. Экран
# разбора показывает, что в нём не так, списками — и закрывается это документами,
# а не правкой базы: у каждой поправки остаются номер, дата, автор и основание.

def _unit_brief(u: EzsEquipmentUnit, locs: dict[str, ServiceLocation]) -> dict[str, Any]:
    loc = locs.get(u.current_location_id) if u.current_location_id else None
    return {"id": str(u.id), "serialNumber": u.serial_number, "vendor": u.vendor or u.brand, "model": u.model,
            "state": u.state, "stateLabel": STATE_LABELS.get(u.state, u.state),
            "location": {"id": loc.id, "name": loc.name, "type": loc.type, "address": loc.address} if loc else None,
            "keeper": u.keeper, "supplier": u.supplier, "region": u.region}


async def audit(db: AsyncSession, company_id) -> dict[str, Any]:
    U = EzsEquipmentUnit
    locs = await _locs(db, company_id)
    units = (await db.execute(select(U).where(U.company_id == company_id))).scalars().all()
    documented = set((await db.execute(select(EzsEquipmentMovement.unit_id).where(
        EzsEquipmentMovement.company_id == company_id,
        EzsEquipmentMovement.op.in_(("write_off", "to_vendor", "correction"))))).scalars().all())
    closed = {i for i, l in locs.items() if l.type == "ev_charging" and (l.status == "closed" or l.operational_status == "decommissioned")}
    at_site = {u.current_location_id for u in units if u.state in ("in_operation", "in_installation")}
    sites_no_card = [l for l in locs.values() if l.type == "ev_charging" and not getattr(l, "is_test", False)
                     and l.id not in closed and l.id not in at_site]
    # Ремонт со сроком: последний документ передачи в ремонт по единице.
    repair_due: dict[Any, EzsEquipmentDocument] = {}
    rows = (await db.execute(select(EzsEquipmentMovement.unit_id, EzsEquipmentDocument).join(
        EzsEquipmentDocument, EzsEquipmentDocument.id == EzsEquipmentMovement.document_id).where(
        EzsEquipmentMovement.company_id == company_id, EzsEquipmentMovement.op == "to_repair")
        .order_by(EzsEquipmentDocument.doc_date))).all()
    for uid, d in rows:
        repair_due[uid] = d
    today = _today()
    keeper_units = [u for u in units if (u.keeper or "").strip() and u.state != "in_operation"
                    and (u.keeper or "").strip() != "Общество"]
    sections = [
        {"key": "stock_no_place", "title": "На складе, но склад не указан", "action": "correction_place",
         "hint": "Укажите склад актом корректировки учёта: единица числится на складе, а на каком — неизвестно.",
         "items": [_unit_brief(u, locs) for u in units if u.state in ("in_stock_new", "in_stock_used", "reserved") and not u.current_location_id]},
        {"key": "operating_at_closed", "title": "В эксплуатации на закрытой станции", "action": "dismantle",
         "hint": "Станция закрыта или выведена из эксплуатации, а единица числится работающей: оформите демонтаж на склад или списание.",
         "items": [_unit_brief(u, locs) for u in units if u.state == "in_operation" and u.current_location_id in closed]},
        {"key": "terminal_no_doc", "title": "Списаны или возвращены без документа", "action": "correction_doc",
         "hint": "Состояние пришло из файла, документа нет: оформите акт задним числом (корректировка без смены состояния) с датой и основанием.",
         "items": [_unit_brief(u, locs) for u in units if u.state in ("written_off", "returned_to_vendor") and u.id not in documented]},
        {"key": "keeper_text", "title": "Хранитель записан текстом", "action": "transfer",
         "hint": "Хранитель и договор хранения — текстом в карточке. Заведите склад ответственного хранения у контрагента с договором и переместите единицы на него.",
         "items": [{**_unit_brief(u, locs), "group": (u.keeper or "").strip()} for u in keeper_units]},
        {"key": "repair_overdue", "title": "В ремонте дольше планового срока", "action": "from_repair",
         "hint": "Плановая дата возврата из ремонта прошла.",
         "items": [{**_unit_brief(u, locs), "due": (repair_due[u.id].details or {}).get("plannedReturn"),
                    "document": repair_due[u.id].number}
                   for u in units if u.state == "in_repair" and u.id in repair_due
                   and (repair_due[u.id].details or {}).get("plannedReturn", "9999") < today]},
        {"key": "unconfirmed", "title": "Данные не подтверждены поставщиком", "action": "open",
         "hint": "Количество портов или модель ждут уточнения у поставщика.",
         "items": [{**_unit_brief(u, locs), "reason": u.unconfirmed_reason} for u in units if not u.data_confirmed]},
        {"key": "sites_no_card", "title": "Действующие станции без карточки оборудования", "action": "create_from_site",
         "hint": "Станция работает, а единицы оборудования на ней нет: заведите карточку по паспорту станции.",
         "items": [{"id": l.id, "name": l.name, "address": l.address, "brand": l.brand, "model": l.model,
                    "serialNumber": l.serial_number} for l in sorted(sites_no_card, key=lambda x: x.name or "")]},
    ]
    for s in sections:
        s["count"] = len(s["items"])
    no_cost = sum(1 for u in units if u.purchase_amount is None and u.state not in ("written_off", "returned_to_vendor"))
    return {"sections": sections, "units": len(units), "noCost": no_cost}


async def cards_from_sites(db: AsyncSession, company_id, user: User | None, site_ids: list[str],
                           doc_date: str | None = None, basis: str | None = None) -> dict[str, Any]:
    """Карточки единиц по паспортам действующих станций — одним актом корректировки учёта."""
    from app.services.ezs_equipment import _movement, unit_from_site
    ids = list(dict.fromkeys(str(i) for i in site_ids))
    if not ids:
        raise HTTPException(400, "Выберите станции")
    doc_date = doc_date or _today()
    sites = (await db.execute(select(ServiceLocation).where(ServiceLocation.company_id == company_id,
                                                            ServiceLocation.id.in_(ids)))).scalars().all()
    if len(sites) != len(ids) or any(s.type != "ev_charging" for s in sites):
        raise HTTPException(400, "Среди выбранных есть не станции пространства")
    busy = set((await db.execute(select(EzsEquipmentUnit.current_location_id).where(
        EzsEquipmentUnit.company_id == company_id, EzsEquipmentUnit.current_location_id.in_(ids),
        EzsEquipmentUnit.state.in_(("in_operation", "in_installation"))))).scalars().all())
    if busy:
        raise HTTPException(409, f"На {len(busy)} станциях карточка уже есть — обновите разбор")
    number = await next_number(db, company_id, "correction", doc_date)
    doc = EzsEquipmentDocument(
        company_id=company_id, op="correction", number=number, doc_date=doc_date,
        basis=(basis or "Карточки заведены по паспортам станций").strip()[:500],
        created_by_id=str(user.id) if user else None,
        created_by_name=(user.name or user.email) if user else None)
    db.add(doc)
    await db.flush()
    for s in sites:
        unit = await unit_from_site(db, company_id, s)
        move = _movement(company_id, unit, "correction", user=user, to_location_id=s.id, from_state=None,
                         to_state="in_operation", occurred_on=doc_date,
                         basis=f"Акт корректировки учёта № {number} от {doc_date}; {doc.basis}")
        move.document_id = doc.id
        db.add(move)
    await db.flush()
    return await get_document(db, company_id, doc.id)
