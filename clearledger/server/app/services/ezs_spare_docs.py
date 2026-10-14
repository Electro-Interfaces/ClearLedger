"""Документы ЗИП: приход, отпуск на станцию, перемещение, списание, инвентаризация.

До 13.10.2026 запчасти двигались одиночными строками журнала: без номера, даты
документа, контрагента, договора и ответственных; корректировка затирала остаток,
не сохраняя прежнего, и из журнала не собиралась оборотка. Теперь операция — это
документ на несколько строк, проводимый атомарно, как у единиц оборудования
(`ezs_equipment_docs.py`): номер, дата, контрагент и договор из справочников
пространства, «сдал / принял», основание.

Проведённый документ не правится. Ошибку исправляет отмена: сторнирующие движения
возвращают остаток, номер остаётся занят. Инвентаризация пишет по строке с
расхождением движение `correction` с `delta = факт − учёт`; сторно — тоже
`correction` с `delta`, поэтому оборотка собирается из журнала одним правилом.

Приход по поставке сюда не входит: там документом служит сама поставка
(`ezs_supply.py`).

С 14.10.2026 остаток ведётся в количестве и сумме: приход — по цене строки, расход,
перемещение и недостача — по средней стоимости остатка склада, излишек — по средней
(на пустом складе — по цене строки описи). Сумма каждой строки сохраняется в
документе, и отмена возвращает ровно её. Документ бывает черновиком (`draft`).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contract, Counterparty, EzsEquipmentDocument, EzsEquipmentUnit, EzsSpareDocument, EzsSparePart,
    EzsSparePartMovement, EzsSparePartStock, ServiceLocation, User,
)
from app.services.ezs_accounting import avg_cost, cost_details, money
from app.services.ezs_equipment import _stock_row, check_period, value_delta
from app.services.ezs_equipment_docs import (
    _locs, _primary, _responsible, check_contract, check_counterparty, contract_label, next_number,
)

# Префикс номера и название документа по операции.
SPARE_DOC_KINDS: dict[str, tuple[str, str]] = {
    "receipt": ("ПЗ", "Приходный ордер (М-4)"),
    "issue": ("РЗП", "Требование-накладная на отпуск (М-11)"),
    "transfer": ("ПЗП", "Накладная на перемещение"),
    "write_off": ("СЗП", "Акт на списание"),
    "inventory": ("ИНВ", "Инвентаризационная опись (ИНВ-3)"),
}
SPARE_DOC_LABELS = {"receipt": "Приход", "issue": "Отпуск на станцию", "transfer": "Перемещение",
                    "write_off": "Списание", "inventory": "Инвентаризация"}
_FROM_OPS = ("issue", "write_off", "transfer")
_TO_OPS = ("receipt", "transfer", "inventory")


def fmt(d: Decimal) -> str:
    """Количество без экспоненты и хвостовых нулей (1E+2 → 100)."""
    s = f"{d:f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def norm_lines(op: str, raw: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Строки документа: номенклатура и количество; у описи — фактическое, ноль допустим."""
    if not raw:
        raise HTTPException(400, "Добавьте в документ хотя бы одну строку")
    if len(raw) > 500:
        raise HTTPException(400, "Не больше 500 строк в одном документе")
    key = "fact" if op == "inventory" else "qty"
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for ln in raw:
        pid = str(ln.get("partId") or "")
        try:
            pid = str(uuid.UUID(pid))
            q = Decimal(str(ln.get(key))).quantize(Decimal("0.001")) + 0  # −0 → 0
            if not q.is_finite():
                raise ValueError(q)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "В строке документа не указана номенклатура или количество")
        if pid in seen:
            raise HTTPException(400, "Номенклатура указана в документе дважды — объедините строки")
        seen.add(pid)
        if op == "inventory" and q < 0:
            raise HTTPException(400, "Фактическое количество не может быть отрицательным")
        if op != "inventory" and q <= 0:
            raise HTTPException(400, "Количество должно быть больше нуля")
        row = {"partId": pid, key: fmt(q)}
        # Цена за единицу без НДС: у прихода — стоимость поступления, у описи — оценка
        # излишка на пустом складе. У расхода цены нет: он идёт по средней.
        if op in ("receipt", "inventory") and ln.get("price") not in (None, ""):
            try:
                price = money(ln["price"])
            except Exception:  # noqa: BLE001
                raise HTTPException(400, "Цена в строке документа — число")
            if price < 0:
                raise HTTPException(400, "Цена не может быть отрицательной")
            row["price"] = f"{price:f}"
        out.append(row)
    return out


def line_amounts(op: str, lines: list[dict[str, str]], stock: dict[tuple[str, str], Decimal],
                 sums: dict[tuple[str, str], Decimal], from_id: str | None, to_id: str | None) -> None:
    """Сумма каждой строки (`amount`) по остатку до проведения: приход — по цене,
    расход и перемещение — по средней склада-отправителя, опись — стоимость отклонения."""
    for ln in lines:
        pid = ln["partId"]
        if op == "receipt":
            ln["amount"] = f"{money(Decimal(ln.get('price') or 0) * Decimal(ln['qty'])):f}"
        elif op == "inventory":
            have = stock.get((pid, to_id), Decimal(0))
            ln["amount"] = f"{value_delta(have, sums.get((pid, to_id)), Decimal(ln['fact']) - Decimal(ln['book']), ln.get('price')):f}"
        else:
            ln["amount"] = f"{avg_cost(stock.get((pid, from_id), Decimal(0)), sums.get((pid, from_id)), Decimal(ln['qty'])):f}"


def amount_effects(op: str, lines: list[dict[str, str]], from_id: str | None,
                   to_id: str | None) -> list[tuple[str, str, Decimal]]:
    """Что документ делает с суммой остатка: (номенклатура, склад, знаковая сумма)."""
    out: list[tuple[str, str, Decimal]] = []
    for ln in lines:
        a = money(ln.get("amount"))
        if op == "inventory":
            out.append((ln["partId"], to_id, a))
            continue
        if op in _FROM_OPS:
            out.append((ln["partId"], from_id, -a))
        if op in ("receipt", "transfer"):
            out.append((ln["partId"], to_id, a))
    return out


def doc_effects(op: str, lines: list[dict[str, str]], from_id: str | None,
                to_id: str | None) -> list[tuple[str, str, Decimal]]:
    """Что документ делает с остатками: (номенклатура, склад, знаковое количество)."""
    out: list[tuple[str, str, Decimal]] = []
    for ln in lines:
        if op == "inventory":
            out.append((ln["partId"], to_id, Decimal(ln["fact"]) - Decimal(ln["book"])))
            continue
        q = Decimal(ln["qty"])
        if op in _FROM_OPS:
            out.append((ln["partId"], from_id, -q))
        if op in ("receipt", "transfer"):
            out.append((ln["partId"], to_id, q))
    return out


def apply_effects(stock: dict[tuple[str, str], Decimal], effects: list[tuple[str, str, Decimal]],
                  names: dict[str, str] | None = None, cancel: bool = False) -> dict[tuple[str, str], Decimal]:
    """Новые остатки после изменений; минус запрещён — ни проведением, ни отменой."""
    new = dict(stock)
    for pid, loc, d in effects:
        new[(pid, loc)] = new.get((pid, loc), Decimal(0)) + d
    for (pid, loc), q in new.items():
        if q < 0:
            have = stock.get((pid, loc), Decimal(0))
            name = (names or {}).get(pid, pid)
            if cancel:
                raise HTTPException(409, f"Отмена увела бы остаток «{name}» в минус: на складе {fmt(have)}, "
                                         f"документ вернул бы {fmt(have - q)}. Сначала отмените более поздние расходы")
            raise HTTPException(409, f"Недостаточно остатка «{name}»: есть {fmt(have)}, нужно {fmt(have - q)}")
    return new


async def _warehouse(db: AsyncSession, company_id, loc_id, what: str) -> ServiceLocation:
    if not loc_id:
        raise HTTPException(400, f"Укажите {what}")
    loc = await db.get(ServiceLocation, str(loc_id))
    if loc is None or loc.company_id != company_id or loc.type != "warehouse":
        raise HTTPException(400, f"Не найден среди складов пространства: {what}")
    if loc.status == "closed":
        raise HTTPException(400, f"Склад «{loc.name}» закрыт — откройте его в карточке склада")
    return loc


def _uuid(value, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise HTTPException(400, f"{what}: неверная ссылка")


async def _lock_stock(db: AsyncSession, company_id, part_ids, loc_ids) -> dict[tuple[str, str], EzsSparePartStock]:
    """Строки остатка под блокировкой, в одном порядке — встречные документы не клинят друг друга."""
    return {(pid, loc): await _stock_row(db, company_id, uuid.UUID(pid), loc, create=True)
            for pid in sorted(set(part_ids)) for loc in sorted(set(loc_ids))}


def _move(doc: EzsSpareDocument, user: User | None, part_id: str, op: str, qty: Decimal, **kw) -> EzsSparePartMovement:
    return EzsSparePartMovement(
        company_id=doc.company_id, part_id=uuid.UUID(part_id), op=op, qty=qty, document_id=doc.id,
        created_by_id=str(user.id) if user else None,
        created_by_name=(user.name or user.email) if user else None, **kw)


def _title(d: EzsSpareDocument) -> str:
    return f"{SPARE_DOC_KINDS[d.op][1]} № {d.number} от {d.doc_date}"


async def _draft_doc(db: AsyncSession, company_id, doc_id) -> EzsSpareDocument:
    d = await db.get(EzsSpareDocument, uuid.UUID(str(doc_id)), with_for_update=True)
    if d is None or d.company_id != company_id:
        raise HTTPException(404, "Документ не найден")
    if d.status != "draft":
        raise HTTPException(409, f"Документ № {d.number} уже проведён — исправляется отменой")
    return d


async def save_draft(db: AsyncSession, company_id, user: User | None, p: dict[str, Any], doc_id=None) -> dict[str, Any]:
    """Черновик: номер занят, строки сохранены, остатки не тронуты."""
    op = p.get("op")
    if op not in SPARE_DOC_KINDS:
        raise HTTPException(400, f"Неизвестный вид документа: {op}")
    try:
        doc_date = date.fromisoformat((p.get("doc_date") or "").strip()).isoformat()
    except ValueError:
        raise HTTPException(400, "Укажите дату документа")
    lines = norm_lines(op, p.get("lines")) if p.get("lines") else []
    cost = cost_details(op, p)
    for ln in lines:
        ln.update(cost)
    cp = await check_counterparty(db, company_id, p.get("counterparty_id"))
    fields = dict(
        op=op, doc_date=doc_date, status="draft", lines=lines,
        counterparty_id=cp.id if cp else None, counterparty_name=cp.name if cp else None,
        contract_id=_uuid(p["contract_id"], "Договор") if p.get("contract_id") else None,
        from_location_id=p.get("from_location_id") or None, to_location_id=p.get("to_location_id") or None,
        target_unit_id=_uuid(p["target_unit_id"], "Станция-получатель") if p.get("target_unit_id") else None,
        target_location_id=p.get("target_location_id") or None,
        target_note=(p.get("target_note") or "").strip()[:300] or None,
        repair_document_id=_uuid(p["repair_document_id"], "Акт ремонта") if p.get("repair_document_id") else None,
        responsible_from=(p.get("responsible_from") or "").strip()[:200] or None,
        responsible_to=(p.get("responsible_to") or "").strip()[:200] or None,
        basis=(p.get("basis") or "").strip()[:500] or None, comment=(p.get("comment") or "").strip()[:2000] or None,
        **_primary(p))
    if doc_id is not None:
        d = await _draft_doc(db, company_id, doc_id)
        for k, v in fields.items():
            setattr(d, k, v)
    else:
        number = (p.get("number") or "").strip() or await next_number(
            db, company_id, SPARE_DOC_KINDS[op][0], doc_date, model=EzsSpareDocument)
        if (await db.execute(select(EzsSpareDocument.id).where(
                EzsSpareDocument.company_id == company_id, EzsSpareDocument.number == number))).first():
            raise HTTPException(409, f"Документ № {number} уже есть")
        d = EzsSpareDocument(company_id=company_id, number=number, created_by_id=str(user.id) if user else None,
                             created_by_name=(user.name or user.email) if user else None, **fields)
        db.add(d)
    await db.flush()
    return await get_document(db, company_id, d.id)


async def post_draft(db: AsyncSession, company_id, user: User | None, doc_id) -> dict[str, Any]:
    d = await _draft_doc(db, company_id, doc_id)
    p = {"op": d.op, "doc_date": d.doc_date, "lines": [dict(ln) for ln in d.lines or []],
         "counterparty_id": d.counterparty_id, "contract_id": d.contract_id,
         "from_location_id": d.from_location_id, "to_location_id": d.to_location_id,
         "target_unit_id": d.target_unit_id, "target_location_id": d.target_location_id,
         "target_note": d.target_note, "repair_document_id": d.repair_document_id,
         "responsible_from": d.responsible_from, "responsible_to": d.responsible_to,
         "basis": d.basis, "comment": d.comment, "primary_number": d.primary_number, "primary_date": d.primary_date,
         **{k: (d.lines or [{}])[0].get(k) for k in ("costAccount", "costItem")}}
    return await post_document(db, company_id, user, p, into=d)


async def delete_draft(db: AsyncSession, company_id, doc_id) -> dict[str, Any]:
    d = await _draft_doc(db, company_id, doc_id)
    await db.delete(d)
    return {"deleted": str(d.id), "number": d.number}


async def post_document(db: AsyncSession, company_id, user: User | None, p: dict[str, Any],
                        into: EzsSpareDocument | None = None) -> dict[str, Any]:
    op = p.get("op")
    if op not in SPARE_DOC_KINDS:
        raise HTTPException(400, f"Неизвестный вид документа: {op}")
    # Повторная отправка той же формы (двойной щелчок, обрыв связи) возвращает уже
    # проведённый документ, а не удваивает приход: ключ документа выдаёт форма.
    doc_id = _uuid(p["id"], "Документ") if p.get("id") else None
    if doc_id is not None and into is None:
        old = await db.get(EzsSpareDocument, doc_id)
        if old is not None:
            return await get_document(db, company_id, doc_id)
    try:
        doc_date = date.fromisoformat((p.get("doc_date") or "").strip()).isoformat()
    except ValueError:
        raise HTTPException(400, "Укажите дату документа")
    await check_period(db, company_id, doc_date)
    lines = norm_lines(op, p.get("lines"))
    # Счёт затрат — в каждой строке, как в табличной части «Требования-накладной» БП.
    cost = cost_details(op, p)
    for ln in lines:
        ln.update(cost)
    ids = [ln["partId"] for ln in lines]
    parts = (await db.execute(select(EzsSparePart).where(
        EzsSparePart.company_id == company_id, EzsSparePart.id.in_([uuid.UUID(i) for i in ids])))).scalars().all()
    if len(parts) != len(ids):
        raise HTTPException(400, "Номенклатура из документа не найдена в справочнике пространства")
    names = {str(x.id): x.name for x in parts}

    src = await _warehouse(db, company_id, p.get("from_location_id"), "склад, с которого выдаётся") if op in _FROM_OPS else None
    dst = await _warehouse(db, company_id, p.get("to_location_id"),
                           "склад инвентаризации" if op == "inventory" else "склад-получатель") if op in _TO_OPS else None
    if src is not None and dst is not None and src.id == dst.id:
        raise HTTPException(400, "Укажите разные склады: откуда и куда")
    unit = site = repair = note = None
    if op == "issue":
        if p.get("target_unit_id"):
            unit = await db.get(EzsEquipmentUnit, _uuid(p["target_unit_id"], "Станция-получатель"))
            if unit is None or unit.company_id != company_id:
                raise HTTPException(400, "Станция-получатель не найдена")
        if p.get("target_location_id"):
            site = await db.get(ServiceLocation, str(p["target_location_id"]))
            if site is None or site.company_id != company_id:
                raise HTTPException(400, "Объект-получатель не найден")
        note = (p.get("target_note") or "").strip()[:300] or None
        if unit is None and site is None and note is None:
            raise HTTPException(400, "Укажите, куда уходит расход: станцию или объект без привязки к станции")
        if p.get("repair_document_id"):
            repair = await db.get(EzsEquipmentDocument, _uuid(p["repair_document_id"], "Акт ремонта"))
            if repair is None or repair.company_id != company_id or repair.op not in ("to_repair", "from_repair"):
                raise HTTPException(400, "Акт ремонта не найден")

    cp_id, contract_id = p.get("counterparty_id"), p.get("contract_id")
    if op == "transfer":
        # Чужой склад (аренда, ответственное хранение): контрагент и договор — из его
        # карточки, другого контрагента в документе быть не может.
        w = (dst.extra_metadata or {}).get("warehouse") or {}
        if w.get("ownership") in ("rent", "custody"):
            if cp_id and w.get("counterpartyId") and str(cp_id) != w["counterpartyId"]:
                raise HTTPException(400, "Склад принадлежит другому контрагенту: в документе должен быть владелец склада")
            cp_id = cp_id or w.get("counterpartyId")
            if not contract_id and w.get("contractId"):
                wc = await db.get(Contract, uuid.UUID(w["contractId"]))
                if wc is not None and wc.company_id == company_id and not wc.is_closed:
                    contract_id = wc.id
    cp = await check_counterparty(db, company_id, cp_id)
    contract, warnings = await check_contract(db, company_id, contract_id, cp.id if cp else None, doc_date)
    if contract is not None and cp is None:
        cp = await db.get(Counterparty, contract.counterparty_id)

    if into is not None:
        number = into.number
    else:
        number = (p.get("number") or "").strip() or await next_number(
            db, company_id, SPARE_DOC_KINDS[op][0], doc_date, model=EzsSpareDocument)
        clash = (await db.execute(select(EzsSpareDocument.id).where(
            EzsSpareDocument.company_id == company_id, EzsSpareDocument.number == number))).first()
        if clash:
            raise HTTPException(409, f"Документ № {number} уже есть")

    from_id, to_id = (src.id if src else None), (dst.id if dst else None)
    # Документ раньше уже проведённого по тем же позициям склада ломает остатки на
    # дату: количество проверяется и опись сверяется только с текущим остатком.
    M, places = EzsSparePartMovement, [i for i in (from_id, to_id) if i]
    last = (await db.execute(select(func.max(M.occurred_on)).where(
        M.company_id == company_id, M.part_id.in_([uuid.UUID(i) for i in ids]),
        or_(M.from_location_id.in_(places), M.to_location_id.in_(places))))).scalar()
    if last and doc_date < last:
        raise HTTPException(409, f"По этим позициям склада уже проведён документ от {last} — дата не может быть раньше")
    rows = await _lock_stock(db, company_id, ids, [i for i in (from_id, to_id) if i])
    stock = {k: Decimal(str(r.qty)) for k, r in rows.items()}
    sums = {k: money(r.amount) for k, r in rows.items()}
    if op == "inventory":
        for ln in lines:  # учётное количество — остаток в момент проведения
            ln["book"] = fmt(stock[(ln["partId"], to_id)])
    new = apply_effects(stock, doc_effects(op, lines, from_id, to_id), names)
    line_amounts(op, lines, stock, sums, from_id, to_id)
    for pid, loc, a in amount_effects(op, lines, from_id, to_id):
        sums[(pid, loc)] = sums.get((pid, loc), Decimal(0)) + a
    for k, r in rows.items():
        r.qty = new[k]
        # Нулевой остаток не держит суммы: копейки округления средней уходят с последним расходом.
        r.amount = sums[k] if new[k] else Decimal("0.00")

    head = dict(
        op=op, number=number, doc_date=doc_date, status="posted", posted_at=datetime.now(timezone.utc),
        counterparty_id=cp.id if cp else None, counterparty_name=cp.name if cp else None,
        contract_id=contract.id if contract else None, contract_label=contract_label(contract),
        from_location_id=from_id, to_location_id=to_id,
        target_unit_id=unit.id if unit else None, target_location_id=site.id if site else None, target_note=note,
        repair_document_id=repair.id if repair else None,
        # «Сдал» и «принял» по умолчанию — МОЛ складов из их карточек.
        responsible_from=(p.get("responsible_from") or "").strip()[:200] or await _responsible(db, from_id),
        responsible_to=(p.get("responsible_to") or "").strip()[:200] or await _responsible(db, to_id),
        basis=(p.get("basis") or "").strip()[:500] or None, comment=(p.get("comment") or "").strip()[:2000] or None,
        lines=lines, **_primary(p),
    )
    if into is not None:
        doc = into
        for k, v in head.items():
            setattr(doc, k, v)
    else:
        doc = EzsSpareDocument(
            id=doc_id or uuid.uuid4(), company_id=company_id, **head,
            created_by_id=str(user.id) if user else None,
            created_by_name=(user.name or user.email) if user else None,
        )
        db.add(doc)
    basis = (_title(doc) + (f"; {doc.basis}" if doc.basis else ""))[:300]
    for ln in lines:
        amount = money(ln.get("amount"))
        if op == "inventory":
            delta = Decimal(ln["fact"]) - Decimal(ln["book"])
            if delta:
                db.add(_move(doc, user, ln["partId"], "correction", abs(delta), delta=delta, amount=amount,
                             to_location_id=to_id, occurred_on=doc_date, basis=basis, comment=doc.comment))
            continue
        db.add(_move(doc, user, ln["partId"], op, Decimal(ln["qty"]), from_location_id=from_id, to_location_id=to_id,
                     target_unit_id=doc.target_unit_id, target_location_id=doc.target_location_id, amount=amount,
                     occurred_on=doc_date, basis=basis, comment=doc.comment))
    await db.flush()
    out = await get_document(db, company_id, doc.id)
    out["warnings"] = warnings
    return out


async def cancel_document(db: AsyncSession, company_id, user: User | None, doc_id, reason: str | None) -> dict[str, Any]:
    """Отмена: сторнирующие движения возвращают остаток, документ остаётся в реестре."""
    d = await db.get(EzsSpareDocument, uuid.UUID(str(doc_id)), with_for_update=True)
    if d is None or d.company_id != company_id:
        raise HTTPException(404, "Документ не найден")
    if d.status == "cancelled":
        raise HTTPException(409, f"Документ № {d.number} уже отменён")
    if d.status == "draft":
        raise HTTPException(409, f"Документ № {d.number} — черновик: его удаляют, а не отменяют")
    await check_period(db, company_id, d.doc_date, "Отменяемый документ")
    reason = (reason or "").strip()[:500]
    if not reason:
        raise HTTPException(400, "Укажите причину отмены")
    effects = [(pid, loc, -x) for pid, loc, x in doc_effects(d.op, d.lines, d.from_location_id, d.to_location_id) if x]
    money_back: dict[tuple[str, str], Decimal] = {}
    for pid, loc, a in amount_effects(d.op, d.lines, d.from_location_id, d.to_location_id):
        money_back[(pid, loc)] = money_back.get((pid, loc), Decimal(0)) - a
    ids = [ln["partId"] for ln in d.lines]
    names = dict((str(i), n) for i, n in (await db.execute(select(EzsSparePart.id, EzsSparePart.name).where(
        EzsSparePart.id.in_([uuid.UUID(i) for i in ids])))).all())
    rows = await _lock_stock(db, company_id, [e[0] for e in effects], [e[1] for e in effects])
    new = apply_effects({k: Decimal(str(r.qty)) for k, r in rows.items()}, effects, names, cancel=True)
    for k, r in rows.items():
        r.qty = new[k]
        r.amount = money(r.amount) + money_back.get(k, Decimal(0)) if new[k] else Decimal("0.00")
    # Сторно той же датой, что документ: остатки на прошлую дату считаются так, будто его не было.
    for pid, loc, x in effects:
        db.add(_move(d, user, pid, "correction", abs(x), delta=x, amount=money_back.get((pid, loc), Decimal(0)),
                     to_location_id=loc, occurred_on=d.doc_date, basis=f"Отмена: {_title(d)}"[:300], comment=reason))
        money_back.pop((pid, loc), None)  # сумма сторно — одна на пару, даже если строк было две
    d.status = "cancelled"
    d.cancelled_at = datetime.now(timezone.utc)
    d.cancelled_by_name = (user.name or user.email) if user else None
    d.cancel_reason = reason
    await db.flush()
    return await get_document(db, company_id, d.id)


async def _heads(db: AsyncSession, company_id, docs: list[EzsSpareDocument]) -> list[dict[str, Any]]:
    locs = await _locs(db, company_id)
    unit_ids = [d.target_unit_id for d in docs if d.target_unit_id]
    units = {u.id: u for u in (await db.execute(select(EzsEquipmentUnit).where(
        EzsEquipmentUnit.id.in_(unit_ids)))).scalars().all()} if unit_ids else {}
    repair_ids = [d.repair_document_id for d in docs if d.repair_document_id]
    repairs = dict((await db.execute(select(EzsEquipmentDocument.id, EzsEquipmentDocument.number).where(
        EzsEquipmentDocument.id.in_(repair_ids)))).all()) if repair_ids else {}
    name = lambda i: locs[i].name if i and i in locs else None  # noqa: E731
    out = []
    for d in docs:
        u = units.get(d.target_unit_id)
        out.append({
            "id": str(d.id), "op": d.op, "opLabel": SPARE_DOC_LABELS[d.op], "title": SPARE_DOC_KINDS[d.op][1],
            "number": d.number, "docDate": d.doc_date, "status": d.status,
            "counterpartyId": str(d.counterparty_id) if d.counterparty_id else None, "counterpartyName": d.counterparty_name,
            "contractId": str(d.contract_id) if d.contract_id else None, "contractLabel": d.contract_label,
            "fromLocationId": d.from_location_id, "fromLocation": name(d.from_location_id),
            "toLocationId": d.to_location_id, "toLocation": name(d.to_location_id),
            # Станция в эксплуатации показывается названием станции, прочая — моделью.
            "targetUnit": {"id": str(u.id), "serialNumber": u.serial_number,
                           "name": (name(u.current_location_id) if u.state == "in_operation" else None)
                           or " ".join(x for x in (u.vendor or u.brand, u.model) if x)} if u else None,
            "targetLocation": name(d.target_location_id), "targetNote": d.target_note,
            "repairDocument": {"id": str(d.repair_document_id), "number": repairs.get(d.repair_document_id)}
            if d.repair_document_id else None,
            "responsibleFrom": d.responsible_from, "responsibleTo": d.responsible_to,
            "basis": d.basis, "comment": d.comment, "createdBy": d.created_by_name,
            "createdAt": d.created_at.isoformat() if d.created_at else None,
            "cancelledAt": d.cancelled_at.isoformat() if d.cancelled_at else None,
            "cancelledBy": d.cancelled_by_name, "cancelReason": d.cancel_reason,
            "positions": len(d.lines or []),
            "amount": float(sum(money(ln.get("amount")) for ln in d.lines or [])),
            "primaryNumber": d.primary_number, "primaryDate": d.primary_date,
            "bpRef": d.bp_ref, "bpExportedAt": d.bp_exported_at.isoformat() if d.bp_exported_at else None,
            "postedAt": d.posted_at.isoformat() if d.posted_at else None,
        })
    return out


async def get_document(db: AsyncSession, company_id, doc_id) -> dict[str, Any]:
    d = await db.get(EzsSpareDocument, uuid.UUID(str(doc_id)))
    if d is None or d.company_id != company_id:
        raise HTTPException(404, "Документ не найден")
    parts = {str(x.id): x for x in (await db.execute(select(EzsSparePart).where(
        EzsSparePart.id.in_([uuid.UUID(ln["partId"]) for ln in d.lines])))).scalars().all()}
    lines = []
    for ln in d.lines:
        x = parts.get(ln["partId"])
        row: dict[str, Any] = {"partId": ln["partId"], "name": x.name if x else "—", "article": x.article if x else None,
                               "category": x.category if x else None, "unitLabel": x.unit_label if x else ""}
        if d.op == "inventory":
            fact = Decimal(ln["fact"])
            # У черновика описи учётного количества ещё нет — оно берётся при проведении.
            book = Decimal(ln["book"]) if ln.get("book") is not None else None
            row.update(book=float(book) if book is not None else None, fact=float(fact),
                       delta=float(fact - book) if book is not None else None)
        else:
            row["qty"] = float(ln["qty"])
        row["price"] = float(ln["price"]) if ln.get("price") is not None else None
        row["amount"] = float(ln["amount"]) if ln.get("amount") is not None else None
        lines.append(row)
    lines.sort(key=lambda r: r["name"].lower())
    first = (d.lines or [{}])[0]
    return {**(await _heads(db, company_id, [d]))[0], "lines": lines,
            "costAccount": first.get("costAccount"), "costItem": first.get("costItem")}


async def list_documents(db: AsyncSession, company_id, *, op=None, status=None, location_id=None,
                         counterparty_id=None, contract_id=None, part_id=None, q=None,
                         date_from=None, date_to=None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    D = EzsSpareDocument
    where = [D.company_id == company_id]
    if op:
        where.append(D.op == op)
    if status:
        where.append(D.status == status)
    if location_id:
        where.append((D.from_location_id == location_id) | (D.to_location_id == location_id))
    if counterparty_id:
        where.append(D.counterparty_id == counterparty_id)
    if contract_id:
        where.append(D.contract_id == contract_id)
    if part_id:
        where.append(D.lines.contains([{"partId": str(part_id)}]))
    if date_from:
        where.append(D.doc_date >= date_from)
    if date_to:
        where.append(D.doc_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        where.append(D.number.ilike(like) | D.counterparty_name.ilike(like) | D.contract_label.ilike(like)
                     | D.responsible_from.ilike(like) | D.responsible_to.ilike(like) | D.basis.ilike(like))
    total = (await db.execute(select(func.count()).select_from(D).where(*where))).scalar_one()
    docs = (await db.execute(select(D).where(*where).order_by(D.doc_date.desc(), D.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return {"items": await _heads(db, company_id, list(docs)), "total": int(total)}


async def count_sheet(db: AsyncSession, company_id, location_id: str) -> dict[str, Any]:
    """Лист пересчёта: что числится на складе сейчас — заготовка строк описи."""
    loc = await _warehouse(db, company_id, location_id, "склад инвентаризации")
    rows = (await db.execute(select(EzsSparePartStock, EzsSparePart).join(
        EzsSparePart, EzsSparePart.id == EzsSparePartStock.part_id).where(
        EzsSparePartStock.company_id == company_id, EzsSparePartStock.location_id == loc.id,
        EzsSparePartStock.qty != 0).order_by(func.lower(EzsSparePart.name)))).all()
    return {"location": {"id": loc.id, "name": loc.name},
            "lines": [{"partId": str(x.id), "name": x.name, "article": x.article, "category": x.category,
                       "unitLabel": x.unit_label, "book": float(s.qty)} for s, x in rows]}
