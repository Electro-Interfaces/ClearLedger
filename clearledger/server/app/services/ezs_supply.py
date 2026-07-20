"""
Документы поставки/возврата оборудования ЭЗС — слой оснований поверх движений.

Документ НЕ заменяет поток движений железа: единицы по-прежнему рождаются
`_create_receipt_unit` (receipt), ЗИП — `spare_apply_movement` (receipt), возврат —
`apply_movement` (to_vendor). Документ ГРУППИРУЕТ и ОБОСНОВЫВАЕТ эти движения и
хранит план (спецификацию), против которого сверяется ФАКТ. Факт (принято) —
производное от привязанных единиц/движений (по supply_line_id), не хранимое поле.

Статусы: draft → ordered (провести) → partially_received/received (производные,
пересчёт приёмкой) → closed | cancelled (ручные; cancel запрещён при наличии прихода).

Транзакционность как в ezs_equipment: методы НЕ коммитят (общий commit из get_db),
документ/строка блокируются with_for_update на время приёмки.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Counterparty, EzsEquipmentMovement, EzsEquipmentUnit, EzsSparePartMovement,
    EzsSupplyDocument, EzsSupplyLine, ServiceLocation, User,
)
from app.services.ezs_equipment import (
    _create_receipt_unit, _get_location, _serial_conflict,
    apply_movement, canon_vendor, spare_apply_movement,
)

DOC_TYPES = ("supply", "return")
LINE_KINDS = ("station", "spare")
_STATION_TEMPLATE = ("vendor", "model", "station_type", "power_kwt",
                     "connectors_count", "connector_types")


def _f(x: Any) -> float | None:
    """NUMERIC/Decimal → float для JSON (иначе dict(row) отдаёт строки)."""
    return float(x) if x is not None else None


def _dec(x: Any) -> Decimal:
    try:
        return Decimal(str(x if x is not None else 0))
    except Exception:  # noqa: BLE001
        return Decimal(0)


# ─── роллап факта (принято) ─────────────────────────────────────────────────

async def received_by_lines(db: AsyncSession, company_id, doc_type: str,
                            lines: list[EzsSupplyLine]) -> dict[Any, Decimal]:
    """{line_id: принято}. Станция/поставка = COUNT единиц; станция/возврат =
    COUNT движений to_vendor; ЗИП = SUM(qty) привязанных движений."""
    res: dict[Any, Decimal] = {}
    station_ids = [ln.id for ln in lines if ln.line_kind == "station"]
    spare_ids = [ln.id for ln in lines if ln.line_kind == "spare"]

    if station_ids:
        if doc_type == "return":
            rows = (await db.execute(
                select(EzsEquipmentMovement.supply_line_id, func.count()).where(
                    EzsEquipmentMovement.company_id == company_id,
                    EzsEquipmentMovement.op == "to_vendor",
                    EzsEquipmentMovement.supply_line_id.in_(station_ids),
                ).group_by(EzsEquipmentMovement.supply_line_id))).all()
        else:
            rows = (await db.execute(
                select(EzsEquipmentUnit.supply_line_id, func.count()).where(
                    EzsEquipmentUnit.company_id == company_id,
                    EzsEquipmentUnit.supply_line_id.in_(station_ids),
                ).group_by(EzsEquipmentUnit.supply_line_id))).all()
        for lid, cnt in rows:
            res[lid] = Decimal(cnt or 0)

    if spare_ids:
        rows = (await db.execute(
            select(EzsSparePartMovement.supply_line_id, func.sum(EzsSparePartMovement.qty)).where(
                EzsSparePartMovement.company_id == company_id,
                EzsSparePartMovement.supply_line_id.in_(spare_ids),
            ).group_by(EzsSparePartMovement.supply_line_id))).all()
        for lid, s in rows:
            res[lid] = _dec(s)
    return res


def compute_receipt_status(lines: list[EzsSupplyLine],
                           received: dict[Any, Decimal]) -> str | None:
    """'received'|'partially_received' если есть приёмка, иначе None (не трогать)."""
    if not lines:
        return None
    total_recv = sum((received.get(ln.id, Decimal(0)) for ln in lines), Decimal(0))
    if total_recv <= 0:
        return None
    fully = all(received.get(ln.id, Decimal(0)) >= _dec(ln.qty_planned) for ln in lines)
    return "received" if fully else "partially_received"


# ─── доступ к документам/строкам (company-scoped) ───────────────────────────

async def _get_doc(db: AsyncSession, company_id, supply_id, *, lock=False) -> EzsSupplyDocument:
    q = select(EzsSupplyDocument).where(
        EzsSupplyDocument.id == supply_id,
        EzsSupplyDocument.company_id == company_id)
    if lock:
        q = q.with_for_update()
    doc = (await db.execute(q)).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    return doc


async def _get_line(db: AsyncSession, company_id, supply_id, line_id, *, lock=False) -> EzsSupplyLine:
    q = select(EzsSupplyLine).where(
        EzsSupplyLine.id == line_id,
        EzsSupplyLine.company_id == company_id,
        EzsSupplyLine.supply_id == supply_id)
    if lock:
        q = q.with_for_update()
    ln = (await db.execute(q)).scalar_one_or_none()
    if ln is None:
        raise HTTPException(404, "Строка спецификации не найдена")
    return ln


async def _lines_of(db: AsyncSession, company_id, supply_id) -> list[EzsSupplyLine]:
    return list((await db.execute(
        select(EzsSupplyLine).where(
            EzsSupplyLine.company_id == company_id,
            EzsSupplyLine.supply_id == supply_id,
        ).order_by(EzsSupplyLine.created_at))).scalars().all())


async def _has_receipts(db: AsyncSession, company_id, supply_id, *, line_id=None) -> bool:
    """Есть ли привязанные к документу (или строке) единицы/движения."""
    for model, col, extra in (
        (EzsEquipmentUnit, EzsEquipmentUnit.supply_id, EzsEquipmentUnit.supply_line_id),
        (EzsEquipmentMovement, EzsEquipmentMovement.supply_id, EzsEquipmentMovement.supply_line_id),
        (EzsSparePartMovement, EzsSparePartMovement.supply_id, EzsSparePartMovement.supply_line_id),
    ):
        conds = [model.company_id == company_id]
        conds.append(extra == line_id if line_id is not None else col == supply_id)
        hit = (await db.execute(select(model.id).where(*conds).limit(1))).first()
        if hit:
            return True
    return False


# ─── суммы и строки ─────────────────────────────────────────────────────────

def _recompute_amount(doc: EzsSupplyDocument, lines: list[EzsSupplyLine]) -> None:
    """amount_total = Σ(qty_planned · unit_price) по строкам с ценой."""
    total = Decimal(0)
    for ln in lines:
        if ln.unit_price is not None:
            total += _dec(ln.qty_planned) * _dec(ln.unit_price)
    doc.amount_total = total if total > 0 else None


def _line_fields(company_id, supply_id, payload: dict[str, Any]) -> dict[str, Any]:
    line_kind = payload.get("line_kind") or "station"
    if line_kind not in LINE_KINDS:
        raise HTTPException(400, f"Недопустимый тип строки: {line_kind}")
    qty = _dec(payload.get("qty_planned"))
    if qty <= 0:
        raise HTTPException(400, "Количество по строке должно быть больше нуля")
    fields: dict[str, Any] = {
        "company_id": company_id, "supply_id": supply_id, "line_kind": line_kind,
        "name": (payload.get("name") or "").strip() or None,
        "qty_planned": qty,
        "unit_price": payload.get("unit_price"),
        "vat_rate": payload.get("vat_rate"),
        "note": payload.get("note"),
    }
    if line_kind == "spare":
        if not payload.get("part_id"):
            raise HTTPException(400, "Для строки ЗИП укажите номенклатуру (part_id)")
        fields["part_id"] = payload.get("part_id")
    else:  # station — шаблон единицы
        fields["vendor"] = canon_vendor(payload.get("vendor"))
        for k in ("model", "station_type", "connector_types"):
            fields[k] = payload.get(k)
        fields["power_kwt"] = payload.get("power_kwt")
        fields["connectors_count"] = payload.get("connectors_count")
    return fields


# ─── CRUD документов ────────────────────────────────────────────────────────

async def create_supply(db: AsyncSession, company_id, user: User | None,
                        payload: dict[str, Any]) -> EzsSupplyDocument:
    doc_type = payload.get("doc_type") or "supply"
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, f"Недопустимый тип документа: {doc_type}")
    number = (payload.get("number") or "").strip()
    if not number:
        raise HTTPException(400, "Укажите номер документа")
    doc_date = (payload.get("doc_date") or "").strip() or date.today().isoformat()

    cp_id = payload.get("counterparty_id")
    cp_name = (payload.get("counterparty_name") or "").strip() or None
    if cp_id:
        cp = await db.get(Counterparty, cp_id)
        if cp is None or cp.company_id != company_id:
            raise HTTPException(404, "Поставщик не найден")
        cp_name = cp_name or cp.short_name or cp.name

    wh_id = payload.get("warehouse_id")
    if wh_id:
        await _get_location(db, company_id, wh_id, want_type="warehouse")

    doc = EzsSupplyDocument(
        company_id=company_id, doc_type=doc_type, number=number, doc_date=doc_date,
        counterparty_id=cp_id, counterparty_name=cp_name,
        contract_id=payload.get("contract_id"), warehouse_id=wh_id,
        currency=(payload.get("currency") or "RUB"),
        vat_total=payload.get("vat_total"), note=payload.get("note"),
        created_by_id=str(user.id) if user else None,
        created_by_name=(user.name or user.email) if user else None,
    )
    db.add(doc)
    await db.flush()

    lines: list[EzsSupplyLine] = []
    for ln in (payload.get("lines") or []):
        obj = EzsSupplyLine(**_line_fields(company_id, doc.id, ln))
        db.add(obj)
        lines.append(obj)
    await db.flush()
    _recompute_amount(doc, lines)
    return doc


async def update_supply(db: AsyncSession, company_id, user: User | None,
                        supply_id, payload: dict[str, Any]) -> EzsSupplyDocument:
    doc = await _get_doc(db, company_id, supply_id, lock=True)
    if doc.status in ("closed", "cancelled"):
        raise HTTPException(400, "Документ закрыт/отменён — правка недоступна")
    if "number" in payload:
        n = (payload.get("number") or "").strip()
        if not n:
            raise HTTPException(400, "Номер не может быть пустым")
        doc.number = n
    if payload.get("doc_date"):
        doc.doc_date = payload["doc_date"].strip()
    if "counterparty_id" in payload:
        cp_id = payload.get("counterparty_id")
        if cp_id:
            cp = await db.get(Counterparty, cp_id)
            if cp is None or cp.company_id != company_id:
                raise HTTPException(404, "Поставщик не найден")
            doc.counterparty_id = cp_id
            doc.counterparty_name = (payload.get("counterparty_name") or "").strip() \
                or cp.short_name or cp.name
        else:
            doc.counterparty_id = None
            doc.counterparty_name = (payload.get("counterparty_name") or "").strip() or None
    if "contract_id" in payload:
        doc.contract_id = payload.get("contract_id")
    if "warehouse_id" in payload:
        wh_id = payload.get("warehouse_id")
        if wh_id:
            await _get_location(db, company_id, wh_id, want_type="warehouse")
        doc.warehouse_id = wh_id
    for k in ("currency", "note", "vat_total"):
        if k in payload:
            setattr(doc, k, payload.get(k))
    return doc


async def delete_supply(db: AsyncSession, company_id, supply_id) -> None:
    doc = await _get_doc(db, company_id, supply_id, lock=True)
    if await _has_receipts(db, company_id, supply_id):
        raise HTTPException(409, "К документу есть приход — удаление запрещено "
                                 "(сначала спишите/верните единицы или отмените)")
    for ln in await _lines_of(db, company_id, supply_id):
        await db.delete(ln)
    await db.delete(doc)


async def set_status(db: AsyncSession, company_id, user: User | None,
                     supply_id, action: str) -> EzsSupplyDocument:
    doc = await _get_doc(db, company_id, supply_id, lock=True)
    if action == "confirm":
        if doc.status != "draft":
            raise HTTPException(400, "Провести можно только черновик")
        doc.status = "ordered"
    elif action == "close":
        if doc.status not in ("ordered", "partially_received", "received"):
            raise HTTPException(400, "Закрыть можно проведённый документ")
        doc.status = "closed"
    elif action == "cancel":
        if doc.status == "cancelled":
            return doc
        if await _has_receipts(db, company_id, supply_id):
            raise HTTPException(409, "К документу есть приход — сначала спишите/верните "
                                     "единицы, затем отменяйте")
        doc.status = "cancelled"
    else:
        raise HTTPException(400, f"Неизвестное действие: {action}")
    return doc


# ─── CRUD строк ─────────────────────────────────────────────────────────────

async def add_line(db: AsyncSession, company_id, supply_id, payload: dict[str, Any]) -> EzsSupplyLine:
    doc = await _get_doc(db, company_id, supply_id, lock=True)
    _assert_editable(doc)
    obj = EzsSupplyLine(**_line_fields(company_id, supply_id, payload))
    db.add(obj)
    await db.flush()
    _recompute_amount(doc, await _lines_of(db, company_id, supply_id))
    return obj


async def update_line(db: AsyncSession, company_id, supply_id, line_id,
                      payload: dict[str, Any]) -> EzsSupplyLine:
    doc = await _get_doc(db, company_id, supply_id, lock=True)
    _assert_editable(doc)
    ln = await _get_line(db, company_id, supply_id, line_id, lock=True)
    if await _has_receipts(db, company_id, supply_id, line_id=line_id):
        raise HTTPException(409, "По строке уже есть приёмка — правка запрещена")
    fields = _line_fields(company_id, supply_id, {**_line_as_payload(ln), **payload})
    for k, v in fields.items():
        if k not in ("company_id", "supply_id"):
            setattr(ln, k, v)
    await db.flush()
    _recompute_amount(doc, await _lines_of(db, company_id, supply_id))
    return ln


async def delete_line(db: AsyncSession, company_id, supply_id, line_id) -> None:
    doc = await _get_doc(db, company_id, supply_id, lock=True)
    _assert_editable(doc)
    ln = await _get_line(db, company_id, supply_id, line_id, lock=True)
    if await _has_receipts(db, company_id, supply_id, line_id=line_id):
        raise HTTPException(409, "По строке уже есть приёмка — удаление запрещено")
    await db.delete(ln)
    await db.flush()
    _recompute_amount(doc, await _lines_of(db, company_id, supply_id))


def _assert_editable(doc: EzsSupplyDocument) -> None:
    if doc.status not in ("draft", "ordered"):
        raise HTTPException(400, "Спецификацию можно менять только в черновике "
                                 "или проведённом документе до приёмки")


def _line_as_payload(ln: EzsSupplyLine) -> dict[str, Any]:
    return {
        "line_kind": ln.line_kind, "part_id": ln.part_id, "name": ln.name,
        "qty_planned": ln.qty_planned, "unit_price": ln.unit_price, "vat_rate": ln.vat_rate,
        "note": ln.note, "vendor": ln.vendor, "model": ln.model,
        "station_type": ln.station_type, "power_kwt": ln.power_kwt,
        "connectors_count": ln.connectors_count, "connector_types": ln.connector_types,
    }


# ─── приёмка ────────────────────────────────────────────────────────────────

async def receive_line(db: AsyncSession, company_id, user: User | None,
                       supply_id, line_id, payload: dict[str, Any]) -> EzsSupplyDocument:
    doc = await _get_doc(db, company_id, supply_id, lock=True)
    if doc.status == "draft":
        raise HTTPException(400, "Сначала проведите документ (кнопка «Провести»)")
    if doc.status in ("closed", "cancelled"):
        raise HTTPException(400, "Документ закрыт/отменён — приёмка недоступна")
    line = await _get_line(db, company_id, supply_id, line_id, lock=True)

    recv = (await received_by_lines(db, company_id, doc.doc_type, [line])).get(line.id, Decimal(0))
    planned = _dec(line.qty_planned)
    allow_overage = bool(payload.get("allow_overage"))
    occurred_on = (payload.get("occurred_on") or "").strip() or doc.doc_date
    prefix = "Возврат" if doc.doc_type == "return" else "Поставка"
    basis = (payload.get("basis") or "").strip() or f"{prefix} №{doc.number} от {doc.doc_date}"
    comment = payload.get("comment")

    def _guard(add: Decimal) -> None:
        if not allow_overage and recv + add > planned:
            raise HTTPException(409, f"Переприёмка: план {planned}, уже принято {recv}, "
                                     f"добавляется {add}. Разрешить сверх плана — allow_overage")

    if doc.doc_type == "supply":
        wh_id = payload.get("warehouse_id") or doc.warehouse_id
        if not wh_id:
            raise HTTPException(400, "Укажите склад-получатель")
        wh = await _get_location(db, company_id, wh_id, want_type="warehouse")

        if line.line_kind == "station":
            units_in = list(payload.get("units") or [])
            if not units_in:
                qn = int(payload.get("qty") or 0)
                units_in = [{} for _ in range(qn)]
            if not units_in:
                raise HTTPException(400, "Укажите единицы (units) или количество (qty) к приёмке")
            _guard(Decimal(len(units_in)))
            # предвалидация серийников: дубли в батче + коллизии в БД
            serials = [(u.get("serial") or "").strip() for u in units_in]
            nonempty = [s for s in serials if s]
            if len(set(s.lower() for s in nonempty)) != len(nonempty):
                raise HTTPException(400, "Повторяющиеся серийные номера в приёмке")
            for s in nonempty:
                if await _serial_conflict(db, company_id, s):
                    raise HTTPException(409, f"Серийный номер «{s}» уже есть в системе")
            for u in units_in:
                serial = (u.get("serial") or "").strip() or None
                fields = {k: getattr(line, k) for k in _STATION_TEMPLATE if getattr(line, k) is not None}
                fields["supplier"] = doc.counterparty_name
                fields["purchase_doc"] = f"Поставка №{doc.number}"
                fields["purchase_date"] = doc.doc_date
                if (u.get("inventory_number") or "").strip():
                    fields["inventory_number"] = u["inventory_number"].strip()
                if (u.get("warranty_until") or "").strip():
                    fields["warranty_until"] = u["warranty_until"].strip()
                await _create_receipt_unit(
                    db, company_id, user, warehouse=wh, serial=serial, is_used=False,
                    fields=fields, supply_id=doc.id, supply_line_id=line.id,
                    purchase_amount=line.unit_price, occurred_on=occurred_on,
                    basis=basis, comment=comment)
        else:  # spare
            qty = _dec(payload.get("qty"))
            if qty <= 0:
                raise HTTPException(400, "Укажите количество ЗИП (qty)")
            _guard(qty)
            await spare_apply_movement(db, company_id, user, line.part_id, {
                "op": "receipt", "to_location_id": wh_id, "qty": str(qty),
                "supply_id": doc.id, "supply_line_id": line.id,
                "occurred_on": occurred_on, "basis": basis, "comment": comment})

    else:  # return
        if line.line_kind == "station":
            unit_ids = list(payload.get("unit_ids") or [])
            if not unit_ids:
                raise HTTPException(400, "Выберите единицы к возврату (unit_ids)")
            _guard(Decimal(len(unit_ids)))
            for uid in unit_ids:
                await apply_movement(db, company_id, user, uid, {
                    "op": "to_vendor", "counterparty": doc.counterparty_name,
                    "supply_id": doc.id, "supply_line_id": line.id,
                    "occurred_on": occurred_on, "basis": basis, "comment": comment})
        else:  # spare return — фаза 1: списание со склада с основанием возврата
            qty = _dec(payload.get("qty"))
            wh_id = payload.get("warehouse_id") or doc.warehouse_id
            if qty <= 0:
                raise HTTPException(400, "Укажите количество ЗИП (qty)")
            if not wh_id:
                raise HTTPException(400, "Укажите склад списания")
            _guard(qty)
            await spare_apply_movement(db, company_id, user, line.part_id, {
                "op": "write_off", "from_location_id": wh_id, "qty": str(qty),
                "supply_id": doc.id, "supply_line_id": line.id,
                "occurred_on": occurred_on, "basis": basis, "comment": comment})

    await _recompute_and_set_status(db, company_id, doc)
    return doc


async def _recompute_and_set_status(db: AsyncSession, company_id, doc: EzsSupplyDocument) -> None:
    lines = await _lines_of(db, company_id, doc.id)
    received = await received_by_lines(db, company_id, doc.doc_type, lines)
    st = compute_receipt_status(lines, received)
    if st and doc.status not in ("closed", "cancelled"):
        doc.status = st


# ─── сериализация (dict, готовый к JSON) ────────────────────────────────────

def line_out(ln: EzsSupplyLine, received: Decimal) -> dict[str, Any]:
    return {
        "id": str(ln.id), "lineKind": ln.line_kind,
        "partId": str(ln.part_id) if ln.part_id else None,
        "name": ln.name, "vendor": ln.vendor, "model": ln.model,
        "stationType": ln.station_type, "powerKwt": _f(ln.power_kwt),
        "connectorsCount": ln.connectors_count, "connectorTypes": ln.connector_types,
        "qtyPlanned": _f(ln.qty_planned), "qtyReceived": _f(received),
        "unitPrice": _f(ln.unit_price), "vatRate": ln.vat_rate, "note": ln.note,
    }


def doc_head(doc: EzsSupplyDocument) -> dict[str, Any]:
    return {
        "id": str(doc.id), "docType": doc.doc_type, "number": doc.number,
        "docDate": doc.doc_date, "status": doc.status,
        "counterpartyId": str(doc.counterparty_id) if doc.counterparty_id else None,
        "counterpartyName": doc.counterparty_name,
        "contractId": str(doc.contract_id) if doc.contract_id else None,
        "warehouseId": doc.warehouse_id, "currency": doc.currency,
        "amountTotal": _f(doc.amount_total), "vatTotal": _f(doc.vat_total),
        "note": doc.note, "createdByName": doc.created_by_name,
    }


async def get_supply(db: AsyncSession, company_id, supply_id) -> dict[str, Any]:
    doc = await _get_doc(db, company_id, supply_id)
    lines = await _lines_of(db, company_id, supply_id)
    received = await received_by_lines(db, company_id, doc.doc_type, lines)
    out = doc_head(doc)
    out["lines"] = [line_out(ln, received.get(ln.id, Decimal(0))) for ln in lines]
    out["qtyPlanned"] = _f(sum((_dec(ln.qty_planned) for ln in lines), Decimal(0)))
    out["qtyReceived"] = _f(sum((received.get(ln.id, Decimal(0)) for ln in lines), Decimal(0)))
    return out


async def list_supplies(db: AsyncSession, company_id, *, doc_type=None, status=None,
                        counterparty_id=None, date_from=None, date_to=None, q=None,
                        page=1, page_size=100) -> dict[str, Any]:
    conds = [EzsSupplyDocument.company_id == company_id]
    if doc_type:
        conds.append(EzsSupplyDocument.doc_type == doc_type)
    if status:
        conds.append(EzsSupplyDocument.status == status)
    if counterparty_id:
        conds.append(EzsSupplyDocument.counterparty_id == counterparty_id)
    if date_from:
        conds.append(EzsSupplyDocument.doc_date >= date_from)
    if date_to:
        conds.append(EzsSupplyDocument.doc_date <= date_to)
    if q:
        conds.append(EzsSupplyDocument.number.ilike(f"%{q.strip()}%"))

    total = (await db.execute(select(func.count()).select_from(
        select(EzsSupplyDocument.id).where(*conds).subquery()))).scalar_one()
    docs = list((await db.execute(
        select(EzsSupplyDocument).where(*conds)
        .order_by(EzsSupplyDocument.doc_date.desc(), EzsSupplyDocument.created_at.desc())
        .offset((max(page, 1) - 1) * page_size).limit(page_size))).scalars().all())

    doc_ids = [d.id for d in docs]
    lines_by_doc: dict[Any, list[EzsSupplyLine]] = {d.id: [] for d in docs}
    all_lines: list[EzsSupplyLine] = []
    if doc_ids:
        for ln in (await db.execute(select(EzsSupplyLine).where(
                EzsSupplyLine.company_id == company_id,
                EzsSupplyLine.supply_id.in_(doc_ids)))).scalars().all():
            lines_by_doc[ln.supply_id].append(ln)
            all_lines.append(ln)
    # роллап факта — по типам документов (station/return считается иначе)
    received: dict[Any, Decimal] = {}
    for dt in DOC_TYPES:
        dt_lines = [ln for d in docs if d.doc_type == dt for ln in lines_by_doc[d.id]]
        if dt_lines:
            received.update(await received_by_lines(db, company_id, dt, dt_lines))

    items = []
    for d in docs:
        dl = lines_by_doc[d.id]
        row = doc_head(d)
        row["linesCount"] = len(dl)
        row["qtyPlanned"] = _f(sum((_dec(ln.qty_planned) for ln in dl), Decimal(0)))
        row["qtyReceived"] = _f(sum((received.get(ln.id, Decimal(0)) for ln in dl), Decimal(0)))
        items.append(row)
    return {"items": items, "total": total}


async def list_suppliers(db: AsyncSession, company_id) -> list[dict[str, Any]]:
    """Поставщики = контрагенты компании kind='external' (для пикеров)."""
    rows = (await db.execute(
        select(Counterparty).where(
            Counterparty.company_id == company_id,
            Counterparty.kind == "external",
        ).order_by(Counterparty.name).limit(2000))).scalars().all()
    return [{"id": str(c.id), "name": c.name, "shortName": c.short_name, "inn": c.inn}
            for c in rows]
