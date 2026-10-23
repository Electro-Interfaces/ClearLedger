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

С 14.10.2026 документ бывает черновиком (`draft`): номер занят, состав лежит в
`details.draft`, движений нет — проводится отдельным действием. У документа есть
номер и дата первичного документа контрагента (УПД, акт), а дата не может
попасть в закрытый период (`check_period`, как дата запрета изменений в 1С).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    Contract, Counterparty, EzsEquipmentDocument, EzsEquipmentMovement, EzsEquipmentUnit,
    ServiceLocation, User,
)
from app.services.ezs_accounting import cost_details
from app.services.ezs_equipment import OP_LABELS, STATE_LABELS, TRANSITIONS, apply_movement, check_period

# Префикс номера и название документа по операции.
DOC_KINDS: dict[str, tuple[str, str]] = {
    "receipt": ("ПР", "Приходный ордер (М-4)"),
    "transfer":("ПМ", "Накладная на внутреннее перемещение (М-11)"),
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
# Перемещение на склад хранителя и обратно — акт приёма-передачи на хранение, а не
# внутренняя накладная: свой ряд номеров и свой заголовок (`details.form`).
STORAGE_FORMS: dict[str, tuple[str, str]] = {
    "mh1": ("ХР", "Акт о приёме-передаче оборудования на хранение (МХ-1)"),
    "mh3": ("ВХ", "Акт о возврате оборудования, сданного на хранение (МХ-3)"),
}


def doc_kind(op: str, details: dict | None = None) -> tuple[str, str]:
    """Префикс номера и название документа: по операции, для хранения — по форме."""
    return STORAGE_FORMS.get((details or {}).get("form") or "") or DOC_KINDS.get(op, ("", op))


# Какой договор подходит операции — по типу договора справочника. Подсказка для
# выбора, не запрет: тип в справочнике пишут по-разному.
CONTRACT_TYPES: dict[str, tuple[str, ...]] = {
    "to_installation": ("Монтаж/Подряд",), "commissioning": ("Монтаж/Подряд",), "dismantle": ("Монтаж/Подряд",),
    "to_repair": ("Сервисное обслуживание", "Сервис", "Техническое обслуживание ЭЗС", "Поставка ЭЗС"),
    "from_repair": ("Сервисное обслуживание", "Сервис", "Техническое обслуживание ЭЗС", "Поставка ЭЗС"),
    "to_vendor": ("Поставка ЭЗС",), "receipt": ("Поставка ЭЗС",),
    "transfer": ("Аренда", "Хранение", "Ответственное хранение"),
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


async def check_contract(db: AsyncSession, company_id, contract_id, counterparty_id=None,
                         on_date: str | None = None) -> tuple[Contract | None, list[str]]:
    """Договор этой компании и этого контрагента, не закрыт. Возвращает предупреждения.

    Срок сверяется с датой документа (`on_date`), а не с сегодняшним днём: акт
    задним числом по действовавшему тогда договору — не «истёкший договор»."""
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
    day = (on_date or _today())[:10]
    if c.valid_until and c.valid_until[:10] < day:
        warnings.append(f"Срок договора № {c.number} истёк {c.valid_until[:10]} — раньше даты документа {day}")
    if c.date and c.date[:10] > day:
        warnings.append(f"Договор № {c.number} заключён {c.date[:10]} — позже даты документа {day}")
    return c, warnings


def contract_label(c: Contract | None) -> str | None:
    return f"№ {c.number} от {c.date}" + (f" ({c.type})" if c.type else "") if c else None


def _next_after(numbers: list[str], stem: str) -> str:
    """Следующий номер ряда `stem`NNNN: наибольший числовой хвост + 1. Счёт по
    количеству ломался о номер, введённый руками впереди счётчика."""
    tails = [int(n[len(stem):]) for n in numbers if n[len(stem):].isdigit()]
    return f"{stem}{max(tails, default=0) + 1:04d}"


async def next_number(db: AsyncSession, company_id, prefix: str, doc_date: str, model=EzsEquipmentDocument) -> str:
    """Номер `ПРЕФИКС-ГГГГ-NNNN` в ряду документов `model` (у модели — company_id и number)."""
    stem = f"{prefix}-{doc_date[:4]}-"
    numbers = (await db.execute(select(model.number).where(
        model.company_id == company_id, model.number.like(stem + "%")))).scalars().all()
    return _next_after(list(numbers), stem)


def _uuids(ids: list[str]) -> list[uuid.UUID]:
    try:
        return [uuid.UUID(i) for i in ids]
    except ValueError:
        raise HTTPException(400, "Единица оборудования не найдена")


def _wh(loc: ServiceLocation | None) -> dict[str, Any]:
    return dict((loc.extra_metadata or {}).get("warehouse") or {}) if loc is not None else {}


async def _storage(db: AsyncSession, company_id, unit_ids: list[str], to_location_id, cp_id, contract_id):
    """Чужой склад в перемещении: форма документа, контрагент и договор из карточки склада.

    На склад арендованный или ответственного хранения единицы уходят к его владельцу:
    положить их туда документом с другим контрагентом нельзя, а без контрагента он
    берётся из карточки. Договора у склада может не быть — это предупреждение, не
    отказ: договоры хранения подписывают и продлевают задним числом.
    """
    to = await db.get(ServiceLocation, to_location_id) if to_location_id else None
    card, form = _wh(to if to is not None and to.company_id == company_id else None), None
    if card.get("ownership") == "custody":
        form = "mh1"
    elif card.get("ownership") != "rent":
        # Возврат с хранения: все единицы лежат на складах хранения одного контрагента.
        loc_ids = set((await db.execute(select(EzsEquipmentUnit.current_location_id).where(
            EzsEquipmentUnit.company_id == company_id,
            EzsEquipmentUnit.id.in_(_uuids(unit_ids))))).scalars().all())
        cards = [_wh(await db.get(ServiceLocation, i)) if i else {} for i in loc_ids]
        if not cards or any(c.get("ownership") != "custody" for c in cards) \
                or len({c.get("counterpartyId") for c in cards}) != 1:
            return None, cp_id, contract_id, []
        card, form = cards[0], "mh3"
    if cp_id and card.get("counterpartyId") and str(cp_id) != card["counterpartyId"]:
        raise HTTPException(400, "Склад принадлежит другому контрагенту: в документе должен быть владелец склада")
    cp_id = cp_id or card.get("counterpartyId")
    warnings: list[str] = []
    if not contract_id and card.get("contractId"):
        c = await db.get(Contract, uuid.UUID(card["contractId"]))
        if c is not None and c.company_id == company_id and not c.is_closed:
            contract_id = c.id
    if not contract_id:
        warnings.append("У склада нет действующего договора — документ проведён без договора")
    return form, cp_id, contract_id, warnings


async def _head(db: AsyncSession, company_id, user: User | None, op: str, doc_date: str, *,
                number: str | None = None, details: dict | None = None, into: EzsEquipmentDocument | None = None,
                **fields) -> EzsEquipmentDocument:
    """Шапка документа с номером: своим или следующим в ряду вида. `into` — черновик,
    который проводится: номер и id остаются его."""
    if into is not None:
        into.op, into.doc_date, into.details = op, doc_date, details
        for k, v in fields.items():
            setattr(into, k, v)
        await db.flush()
        return into
    number = (number or "").strip() or await next_number(db, company_id, doc_kind(op, details)[0], doc_date)
    clash = (await db.execute(select(EzsEquipmentDocument.id).where(
        EzsEquipmentDocument.company_id == company_id, EzsEquipmentDocument.number == number))).first()
    if clash:
        raise HTTPException(409, f"Документ № {number} уже есть")
    doc = EzsEquipmentDocument(
        company_id=company_id, op=op, number=number, doc_date=doc_date, details=details,
        created_by_id=str(user.id) if user else None,
        created_by_name=(user.name or user.email) if user else None, **fields)
    db.add(doc)
    await db.flush()
    return doc


def _primary(p: dict[str, Any]) -> dict[str, Any]:
    """Номер и дата первичного документа контрагента (УПД, акт, накладная)."""
    day = (p.get("primary_date") or "").strip() or None
    if day:
        try:
            day = date.fromisoformat(day).isoformat()
        except ValueError:
            raise HTTPException(400, "Дата первичного документа указана неверно")
    return {"primary_number": (p.get("primary_number") or "").strip()[:100] or None, "primary_date": day}


async def _responsible(db: AsyncSession, loc_id: str | None) -> str | None:
    """МОЛ склада из его карточки — подставляется в «сдал» / «принял»."""
    loc = await db.get(ServiceLocation, loc_id) if loc_id else None
    return _wh(loc).get("responsible") if loc is not None and loc.type == "warehouse" else None


def _basis(doc: EzsEquipmentDocument) -> str:
    # Основание движения — 300 знаков: длинное основание документа в него целиком не входит.
    return (f"{doc_kind(doc.op, doc.details)[1]} № {doc.number} от {doc.doc_date}"
            + (f"; {doc.basis}" if doc.basis else ""))[:300]


async def document_for(db: AsyncSession, company_id, user: User | None, op: str,
                       moves: list[EzsEquipmentMovement], *, doc_date: str | None = None,
                       basis: str | None = None, comment: str | None = None) -> EzsEquipmentDocument:
    """Документ с автономером для движений, проведённых прежними формами (ручной
    приход единицы, демонтаж с площадки): движения без документа больше не возникают."""
    try:
        doc_date = date.fromisoformat((doc_date or "").strip() or _today()).isoformat()
    except ValueError:
        raise HTTPException(400, "Дата операции указана неверно")
    locs = {m.to_location_id for m in moves}
    doc = await _head(db, company_id, user, op, doc_date,
                      to_location_id=locs.pop() if len(locs) == 1 else None,
                      basis=(basis or "").strip()[:500] or None, comment=(comment or "").strip()[:2000] or None)
    for m in moves:
        m.document_id, m.basis, m.occurred_on = doc.id, _basis(doc), doc_date
    await db.flush()
    return doc


# Поля формы, которые черновик хранит как есть, чтобы провести их позже.
_DRAFT_KEYS = ("unit_ids", "to_location_id", "counterparty_id", "contract_id", "responsible_from",
               "responsible_to", "basis", "comment", "custodian", "reserved_for_location_id", "to_state",
               "sync_passport", "details", "primary_number", "primary_date")


def _draft_payload(p: dict[str, Any]) -> dict[str, Any]:
    out = {k: p.get(k) for k in _DRAFT_KEYS if p.get(k) not in (None, "", [])}
    out["unit_ids"] = list(dict.fromkeys(str(u) for u in (p.get("unit_ids") or [])))[:500]
    for k in ("counterparty_id", "contract_id"):
        if out.get(k):
            out[k] = str(out[k])
    return out


async def save_draft(db: AsyncSession, company_id, user: User | None, p: dict[str, Any],
                     doc_id=None) -> dict[str, Any]:
    """Черновик: номер занят, состав сохранён, движений нет. Проверки — при проведении."""
    op = p.get("op")
    if op not in DOC_KINDS or op not in TRANSITIONS or op == "receipt":
        raise HTTPException(400, f"Неизвестная операция: {op}")
    try:
        doc_date = date.fromisoformat((p.get("doc_date") or "").strip()).isoformat()
    except ValueError:
        raise HTTPException(400, "Укажите дату документа")
    cp = await check_counterparty(db, company_id, p.get("counterparty_id"))
    draft = _draft_payload(p)
    fields = dict(status="draft", counterparty_id=cp.id if cp else None, counterparty_name=cp.name if cp else None,
                  to_location_id=p.get("to_location_id") or None, **_primary(p),
                  basis=(p.get("basis") or "").strip()[:500] or None, comment=(p.get("comment") or "").strip()[:2000] or None)
    if doc_id is None:
        doc = await _head(db, company_id, user, op, doc_date, number=p.get("number"), details={"draft": draft}, **fields)
    else:
        doc = await _draft_doc(db, company_id, doc_id)
        doc = await _head(db, company_id, user, op, doc_date, details={"draft": draft}, into=doc, **fields)
    return await get_document(db, company_id, doc.id)


async def _draft_doc(db: AsyncSession, company_id, doc_id) -> EzsEquipmentDocument:
    d = (await db.execute(select(EzsEquipmentDocument).where(
        EzsEquipmentDocument.id == uuid.UUID(str(doc_id)), EzsEquipmentDocument.company_id == company_id)
        .with_for_update())).scalar_one_or_none()
    if d is None:
        raise HTTPException(404, "Документ не найден")
    if d.status != "draft":
        raise HTTPException(409, f"Документ № {d.number} уже проведён — исправляется отменой")
    return d


async def post_draft(db: AsyncSession, company_id, user: User | None, doc_id) -> dict[str, Any]:
    d = await _draft_doc(db, company_id, doc_id)
    payload = {**((d.details or {}).get("draft") or {}), "op": d.op, "doc_date": d.doc_date,
               "primary_number": d.primary_number, "primary_date": d.primary_date}
    return await post_document(db, company_id, user, payload, into=d)


async def delete_draft(db: AsyncSession, company_id, doc_id) -> dict[str, Any]:
    d = await _draft_doc(db, company_id, doc_id)
    await db.delete(d)
    return {"deleted": str(d.id), "number": d.number}


async def post_document(db: AsyncSession, company_id, user: User | None, p: dict[str, Any],
                        into: EzsEquipmentDocument | None = None) -> dict[str, Any]:
    op = p.get("op")
    if op not in DOC_KINDS or op not in TRANSITIONS or op == "receipt":
        raise HTTPException(400, f"Неизвестная операция: {op}")
    unit_ids = list(dict.fromkeys(str(u) for u in (p.get("unit_ids") or [])))
    if not unit_ids:
        raise HTTPException(400, "Выберите единицы оборудования")
    if len(unit_ids) > 500:
        raise HTTPException(400, "Не больше 500 единиц в одном документе")
    try:
        doc_date = date.fromisoformat((p.get("doc_date") or "").strip()).isoformat()
    except ValueError:
        raise HTTPException(400, "Укажите дату документа")
    await check_period(db, company_id, doc_date)
    cp_id, contract_id, details, warnings = p.get("counterparty_id"), p.get("contract_id"), None, []
    if op == "transfer":
        form, cp_id, contract_id, warnings = await _storage(
            db, company_id, unit_ids, p.get("to_location_id"), cp_id, contract_id)
        details = {"form": form} if form else None
    cp = await check_counterparty(db, company_id, cp_id)
    if op in COUNTERPARTY_REQUIRED and cp is None:
        raise HTTPException(400, "Укажите контрагента из справочника: оборудование передаётся из наших рук")
    contract, more = await check_contract(db, company_id, contract_id, cp.id if cp else None, doc_date)
    warnings = warnings + more
    if contract is not None and cp is None:
        cp = await db.get(Counterparty, contract.counterparty_id)
    doc = await _head(
        db, company_id, user, op, doc_date, number=p.get("number"), into=into,
        details=details or repair_details(op, p.get("details")) or cost_details(op, p.get("details")) or None,
        counterparty_id=cp.id if cp else None, counterparty_name=cp.name if cp else None,
        contract_id=contract.id if contract else None, contract_label=contract_label(contract),
        to_location_id=p.get("to_location_id") or None,
        responsible_from=(p.get("responsible_from") or "").strip()[:200] or None,
        responsible_to=(p.get("responsible_to") or "").strip()[:200] or None,
        basis=(p.get("basis") or "").strip()[:500] or None, comment=(p.get("comment") or "").strip()[:2000] or None,
        status="posted", posted_at=datetime.now(timezone.utc), **_primary(p),
    )
    basis = _basis(doc)
    froms = set()
    for uid in unit_ids:
        unit, move = await apply_movement(db, company_id, user, _uuids([uid])[0], {
            "op": op, "to_location_id": doc.to_location_id, "occurred_on": doc_date,
            # Текст держателя приходит только из прежней формы корректировки.
            "counterparty": cp.name if cp else p.get("counterparty_text"), "basis": basis, "comment": doc.comment,
            "custodian": p.get("custodian"), "reserved_for_location_id": p.get("reserved_for_location_id"),
            "to_state": p.get("to_state"), "sync_passport": bool(p.get("sync_passport")),
            "keep_location": op == "correction" and not doc.to_location_id,
        })
        move.document_id = doc.id
        move.counterparty_id = cp.id if cp else None
        froms.add(move.from_location_id)
    if len(froms) == 1:
        doc.from_location_id = froms.pop()
    # «Сдал» и «принял» по умолчанию — МОЛ складов из их карточек.
    doc.responsible_from = doc.responsible_from or await _responsible(db, doc.from_location_id)
    doc.responsible_to = doc.responsible_to or await _responsible(db, doc.to_location_id)
    await db.flush()
    out = await get_document(db, company_id, doc.id)
    out["warnings"] = warnings
    return out


def _doc_head(d: EzsEquipmentDocument, locs: dict[str, ServiceLocation], units: int | None = None) -> dict[str, Any]:
    name = lambda i: locs[i].name if i and i in locs else None  # noqa: E731
    return {
        "id": str(d.id), "op": d.op, "opLabel": OP_LABELS.get(d.op, d.op), "title": doc_kind(d.op, d.details)[1],
        "number": d.number, "docDate": d.doc_date,
        "status": d.status or "posted", "cancelledBy": d.cancelled_by_name, "cancelReason": d.cancel_reason,
        "cancelledAt": d.cancelled_at.isoformat() if d.cancelled_at else None,
        "fromLocationId": d.from_location_id, "toLocationId": d.to_location_id,
        "counterpartyId": str(d.counterparty_id) if d.counterparty_id else None, "counterpartyName": d.counterparty_name,
        "contractId": str(d.contract_id) if d.contract_id else None, "contractLabel": d.contract_label,
        "fromLocation": name(d.from_location_id), "toLocation": name(d.to_location_id),
        "responsibleFrom": d.responsible_from, "responsibleTo": d.responsible_to,
        "basis": d.basis, "comment": d.comment, "createdBy": d.created_by_name,
        "details": {k: v for k, v in (d.details or {}).items() if k != "draft"},
        "draft": (d.details or {}).get("draft") if d.status == "draft" else None,
        "primaryNumber": d.primary_number, "primaryDate": d.primary_date,
        "bpRef": d.bp_ref, "bpExportedAt": d.bp_exported_at.isoformat() if d.bp_exported_at else None,
        "postedAt": d.posted_at.isoformat() if d.posted_at else None,
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
        EzsEquipmentMovement.document_id == d.id, EzsEquipmentMovement.op != "cancel")
        .order_by(EzsEquipmentUnit.serial_number))).all()
    name = lambda i: locs[i].name if i and i in locs else None  # noqa: E731
    lines = [{
        "unitId": str(u.id), "serialNumber": u.serial_number, "inventoryNumber": u.inventory_number,
        "vendor": u.vendor or u.brand, "model": u.model, "powerKwt": float(u.power_kwt) if u.power_kwt is not None else None,
        "purchaseAmount": float(u.purchase_amount) if u.purchase_amount is not None else None,
        "from": name(m.from_location_id), "to": name(m.to_location_id),
        "fromState": STATE_LABELS.get(m.from_state or "", m.from_state), "toState": STATE_LABELS.get(m.to_state or "", m.to_state),
        "accountFrom": m.account_from, "accountTo": m.account_to,
        "amount": float(m.amount) if m.amount is not None else None,
    } for m, u in rows]
    if d.status == "draft":
        # Черновик: движений нет, строки — единицы из состава в их нынешнем положении.
        ids = _uuids(((d.details or {}).get("draft") or {}).get("unit_ids") or [])
        units = (await db.execute(select(EzsEquipmentUnit).where(
            EzsEquipmentUnit.company_id == company_id, EzsEquipmentUnit.id.in_(ids or [uuid.uuid4()]))
            .order_by(EzsEquipmentUnit.serial_number))).scalars().all()
        lines = [{
            "unitId": str(u.id), "serialNumber": u.serial_number, "inventoryNumber": u.inventory_number,
            "vendor": u.vendor or u.brand, "model": u.model,
            "powerKwt": float(u.power_kwt) if u.power_kwt is not None else None,
            "purchaseAmount": float(u.purchase_amount) if u.purchase_amount is not None else None,
            "from": name(u.current_location_id), "to": name(d.to_location_id),
            "fromState": STATE_LABELS.get(u.state, u.state), "toState": None,
        } for u in units]
    # Отменённый приход: карточек уже нет, строки — из снимка в документе.
    lines = lines or list((d.details or {}).get("cancelledUnits") or [])
    return {**_doc_head(d, locs, len(lines)), "lines": lines}


async def cancel_document(db: AsyncSession, company_id, user: User | None, doc_id, reason: str | None) -> dict[str, Any]:
    """Отмена проведённого документа: единицы возвращаются в прежнее состояние.

    Журнал не переписывается — на каждое движение документа ложится сторнирующее
    (`cancel`) той же датой. Отменить можно только последнее движение единицы: если
    после документа по ней проведён другой, сначала отменяют тот. Документ, который
    завёл карточку (приход, карточка по паспорту станции), при отмене её убирает.
    """
    from app.models import EzsSpareDocument, ObjectLink
    from app.services.ezs_equipment import _PREV_FIELDS, _movement, live_moves, sync_placement
    reason = (reason or "").strip()[:500]
    if not reason:
        raise HTTPException(400, "Укажите причину отмены")
    M, U = EzsEquipmentMovement, EzsEquipmentUnit
    d = (await db.execute(select(EzsEquipmentDocument).where(
        EzsEquipmentDocument.id == uuid.UUID(str(doc_id)), EzsEquipmentDocument.company_id == company_id)
        .with_for_update())).scalar_one_or_none()
    if d is None:
        raise HTTPException(404, "Документ не найден")
    if d.status == "cancelled":
        raise HTTPException(409, f"Документ № {d.number} уже отменён")
    if d.status == "draft":
        raise HTTPException(409, f"Документ № {d.number} — черновик: его удаляют, а не отменяют")
    await check_period(db, company_id, d.doc_date, "Отменяемый документ")
    rows = (await db.execute(select(M, U).join(U, U.id == M.unit_id).where(
        M.document_id == d.id, M.op != "cancel").with_for_update())).all()
    # Позже документа — только движения в силе: отменённый документ и его сторно не мешают.
    own = aliased(M)
    later = set((await db.execute(select(M.unit_id).join(own, own.unit_id == M.unit_id).where(
        own.document_id == d.id, M.created_at > own.created_at,
        or_(M.document_id.is_(None), M.document_id != d.id), *live_moves()))).scalars().all())
    busy = [u.serial_number or str(u.id)[:8] for m, u in rows if u.id in later]
    if busy:
        raise HTTPException(409, "После этого документа по единицам проведены другие — сначала отмените их: "
                            + ", ".join(busy[:10]) + ("…" if len(busy) > 10 else ""))
    if any(m.prev is None and m.from_state is not None for m, _ in rows):
        raise HTTPException(409, "Документ проведён до появления отмены — исправьте его актом корректировки учёта")
    basis = f"Отмена: {_basis(d)} — {reason}"[:300]
    gone = []
    for m, u in rows:
        if m.from_state is None:
            used = (await db.execute(select(EzsSpareDocument.number).where(
                EzsSpareDocument.target_unit_id == u.id, EzsSpareDocument.status == "posted").limit(1))).first()
            if used:
                raise HTTPException(409, f"На единицу {u.serial_number or ''} отпущены материалы по документу "
                                         f"№ {used[0]} — сначала отмените его")
            gone.append({"serialNumber": u.serial_number, "inventoryNumber": u.inventory_number,
                         "vendor": u.vendor or u.brand, "model": u.model, "to": None,
                         "toState": STATE_LABELS.get(m.to_state or "", m.to_state)})
            await db.execute(delete(ObjectLink).where(
                ObjectLink.company_id == company_id, ObjectLink.child_type == "station",
                ObjectLink.child_id == str(u.id), ObjectLink.relation == "placed_at"))
            await db.delete(u)
            continue
        for f in _PREV_FIELDS:
            setattr(u, f, m.prev.get(f))
        back = _movement(company_id, u, "cancel", user=user, from_location_id=m.to_location_id,
                         to_location_id=u.current_location_id, from_state=m.to_state, to_state=u.state,
                         occurred_on=m.occurred_on, basis=basis)
        back.document_id = d.id
        db.add(back)
        if (m.to_state, m.to_location_id) != (u.state, u.current_location_id):
            await sync_placement(db, company_id, user, u, m.occurred_on, basis)
    if gone:
        d.details = {**(d.details or {}), "cancelledUnits": gone}
    d.status, d.cancel_reason, d.cancelled_at = "cancelled", reason, datetime.now(timezone.utc)
    d.cancelled_by_name = (user.name or user.email) if user else None
    await db.flush()
    out = await get_document(db, company_id, d.id)
    # Паспорт и статус станции меняет не складской учёт: отмена их не возвращает.
    out["warnings"] = ["Паспорт и статус станции отмена не меняет — проверьте карточку станции"] \
        if d.op in ("commissioning", "dismantle") else []
    return out


async def list_documents(db: AsyncSession, company_id, *, op=None, q=None, date_from=None, date_to=None,
                         status=None, counterparty_id=None, contract_id=None, location_id=None, unit_id=None,
                         limit: int = 50, offset: int = 0) -> dict[str, Any]:
    D = EzsEquipmentDocument
    where = [D.company_id == company_id]
    if op:
        where.append(D.op == op)
    if status:
        where.append(D.status == status)
    if counterparty_id:
        where.append(D.counterparty_id == counterparty_id)
    if contract_id:
        where.append(D.contract_id == contract_id)
    if location_id:
        where.append((D.from_location_id == location_id) | (D.to_location_id == location_id))
    if unit_id:
        where.append(D.id.in_(select(EzsEquipmentMovement.document_id).where(EzsEquipmentMovement.unit_id == unit_id)))
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
        EzsEquipmentMovement.document_id.in_([d.id for d in docs] or [None]), EzsEquipmentMovement.op != "cancel")
        .group_by(EzsEquipmentMovement.document_id))).all())
    locs = await _locs(db, company_id)
    def units(d):
        if d.status == "draft":
            return len(((d.details or {}).get("draft") or {}).get("unit_ids") or [])
        return int(counts.get(d.id) or len((d.details or {}).get("cancelledUnits") or []))
    return {"items": [_doc_head(d, locs, units(d)) for d in docs], "total": int(total)}


# ── Карточка склада ─────────────────────────────────────────────────────────
# Реквизиты склада живут в `extra_metadata.warehouse` точки: отдельная таблица на
# шесть складов не нужна, а точка — уже общий объект пространства.

async def warehouse_card(db: AsyncSession, company_id, loc: ServiceLocation) -> dict[str, Any]:
    w = dict((loc.extra_metadata or {}).get("warehouse") or {})
    w["status"] = "closed" if getattr(loc, "status", None) == "closed" else "active"
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
        # Склад ищется по названию: «новый» с именем существующего затёр бы его карточку.
        if (await db.execute(select(ServiceLocation.id).where(
                ServiceLocation.company_id == company_id, ServiceLocation.type == "warehouse",
                func.lower(func.btrim(ServiceLocation.name)) == name.lower()))).first():
            raise HTTPException(409, f"Склад «{name}» уже есть — откройте его карточку")
        loc = await get_or_create_warehouse(db, company_id, name)
    meta = dict(loc.extra_metadata or {})
    old = dict(meta.get("warehouse") or {})
    # Частичная правка (одно поле) не сбрасывает остальные реквизиты карточки.
    given = lambda k: p.get(k) if k in p else old.get(k)  # noqa: E731
    ownership = given("ownership") or "own"
    if ownership not in OWNERSHIP:
        raise HTTPException(400, "Неизвестный вид владения складом")
    cp = await check_counterparty(db, company_id, given("counterpartyId"))
    contract_id = given("contractId")
    contract, _ = await check_contract(db, company_id, contract_id, cp.id if cp else None) if contract_id else (None, [])
    if ownership in ("rent", "custody") and cp is None:
        raise HTTPException(400, "Для арендованного склада или ответственного хранения укажите контрагента")
    new_name = (p.get("name") or "").strip()[:300]
    if new_name and loc_id and new_name != loc.name:
        if (await db.execute(select(ServiceLocation.id).where(
                ServiceLocation.company_id == company_id, ServiceLocation.type == "warehouse",
                ServiceLocation.id != loc.id,
                func.lower(func.btrim(ServiceLocation.name)) == new_name.lower()))).first():
            raise HTTPException(409, f"Склад «{new_name}» уже есть")
        loc.name = new_name
    if "address" in p:
        loc.address = (p.get("address") or "").strip()[:500] or None
    # МОЛ — участник пространства (в 1С — физическое лицо); имя хранится снимком.
    resp_user = old.get("responsibleUserId") if "responsibleUserId" not in p else p.get("responsibleUserId")
    responsible = (p.get("responsible") if "responsible" in p else old.get("responsible")) or ""
    if resp_user:
        u = await db.get(User, uuid.UUID(str(resp_user)))
        if u is None:
            raise HTTPException(400, "МОЛ не найден среди участников пространства")
        responsible = u.name or u.email
    take = lambda k, n: ((p.get(k) if k in p else old.get(k)) or "").strip()[:n] or None  # noqa: E731
    meta["warehouse"] = {
        "ownership": ownership, "counterpartyId": str(cp.id) if cp else None,
        "contractId": str(contract.id) if contract else None,
        "responsible": responsible.strip()[:200] or None,
        "responsibleUserId": str(resp_user) if resp_user else None,
        "phone": take("phone", 60), "note": take("note", 1000),
        # Код и ссылка склада в 1С: по ним выгрузка находит склад, а сверка — остаток.
        "bpCode": take("bpCode", 30), "bpRef": take("bpRef", 60),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    loc.extra_metadata = meta
    await db.flush()
    return await warehouse_card(db, company_id, loc)


async def _warehouse_usage(db: AsyncSession, company_id, loc_id: str) -> dict[str, int]:
    """Что держит склад: единицы на нём, ненулевые остатки ЗИП, история движений и документов."""
    from app.models import (
        EzsSpareDocument, EzsSparePartMovement, EzsSparePartStock, EzsSupplyDocument,
    )
    from app.services.ezs_equipment import TERMINAL_STATES
    U, M, SM, S = EzsEquipmentUnit, EzsEquipmentMovement, EzsSparePartMovement, EzsSparePartStock
    count = lambda q: db.execute(q)  # noqa: E731
    n = lambda r: int(r.scalar_one() or 0)  # noqa: E731
    return {
        "units": n(await count(select(func.count()).select_from(U).where(
            U.company_id == company_id, U.current_location_id == loc_id, U.state.notin_(tuple(TERMINAL_STATES))))),
        "spares": n(await count(select(func.count()).select_from(S).where(
            S.company_id == company_id, S.location_id == loc_id, S.qty != 0))),
        "history": n(await count(select(func.count()).select_from(M).where(
            M.company_id == company_id, (M.from_location_id == loc_id) | (M.to_location_id == loc_id))))
        + n(await count(select(func.count()).select_from(SM).where(
            SM.company_id == company_id, (SM.from_location_id == loc_id) | (SM.to_location_id == loc_id))))
        + n(await count(select(func.count()).select_from(EzsEquipmentDocument).where(
            EzsEquipmentDocument.company_id == company_id,
            (EzsEquipmentDocument.from_location_id == loc_id) | (EzsEquipmentDocument.to_location_id == loc_id))))
        + n(await count(select(func.count()).select_from(EzsSpareDocument).where(
            EzsSpareDocument.company_id == company_id,
            (EzsSpareDocument.from_location_id == loc_id) | (EzsSpareDocument.to_location_id == loc_id))))
        + n(await count(select(func.count()).select_from(EzsSupplyDocument).where(
            EzsSupplyDocument.company_id == company_id, EzsSupplyDocument.warehouse_id == loc_id))),
    }


async def _own_warehouse(db: AsyncSession, company_id, loc_id: str) -> ServiceLocation:
    loc = await db.get(ServiceLocation, loc_id)
    if loc is None or loc.company_id != company_id or loc.type != "warehouse":
        raise HTTPException(404, "Склад не найден")
    return loc


async def set_warehouse_status(db: AsyncSession, company_id, loc_id: str, close: bool) -> dict[str, Any]:
    """Закрыть склад: он пропадает из выбора в документах, история остаётся.

    Закрыть можно только пустой склад — иначе единицы и остатки повисли бы на
    месте, куда ничего нельзя провести и откуда нельзя вывезти.
    """
    loc = await _own_warehouse(db, company_id, loc_id)
    if close:
        used = await _warehouse_usage(db, company_id, loc_id)
        if used["units"] or used["spares"]:
            raise HTTPException(409, f"На складе «{loc.name}» числится: единиц {used['units']}, позиций ЗИП "
                                     f"{used['spares']} — сначала переместите их на другой склад")
    loc.status = "closed" if close else "active"
    await db.flush()
    return await warehouse_card(db, company_id, loc)


async def delete_warehouse(db: AsyncSession, company_id, loc_id: str) -> dict[str, Any]:
    """Удалить склад, заведённый по ошибке: только без единиц, остатков и истории.

    Склад с историей не удаляется — его закрывают: иначе прошлые документы и
    остатки на дату ссылались бы в пустоту.
    """
    from app.models import EzsSparePartStock
    loc = await _own_warehouse(db, company_id, loc_id)
    used = await _warehouse_usage(db, company_id, loc_id)
    if used["units"] or used["spares"]:
        raise HTTPException(409, f"На складе «{loc.name}» числятся единицы или ЗИП — удалить нельзя")
    if used["history"]:
        raise HTTPException(409, f"По складу «{loc.name}» есть движения и документы — его можно закрыть, но не удалить")
    await db.execute(delete(EzsSparePartStock).where(EzsSparePartStock.location_id == loc.id))
    await db.delete(loc)
    return {"deleted": loc_id, "name": loc.name}


# ── Разбор данных ───────────────────────────────────────────────────────────
# Работающие станции разбор не трогает: станция в эксплуатации ведётся в приложении
# эксплуатации, а не на складе (граница учёта, МАГ 13.10.2026).
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
    # Ремонт со сроком: последний документ передачи в ремонт по единице.
    repair_due: dict[Any, EzsEquipmentDocument] = {}
    rows = (await db.execute(select(EzsEquipmentMovement.unit_id, EzsEquipmentDocument).join(
        EzsEquipmentDocument, EzsEquipmentDocument.id == EzsEquipmentMovement.document_id).where(
        EzsEquipmentMovement.company_id == company_id, EzsEquipmentMovement.op == "to_repair",
        EzsEquipmentDocument.status == "posted").order_by(EzsEquipmentDocument.doc_date))).all()
    for uid, d in rows:
        repair_due[uid] = d
    today = _today()
    # Чужие склады и состояние их договора: единицы на таком складе хранителя уже
    # знают ключом, а истёкший или отсутствующий договор — отдельный список к действию.
    foreign = {i: await warehouse_card(db, company_id, l) for i, l in locs.items()
               if l.type == "warehouse" and _wh(l).get("ownership") in ("rent", "custody")}
    keeper_units = [u for u in units if (u.keeper or "").strip() and u.state != "in_operation"
                    and (u.keeper or "").strip() != "Общество"
                    and not foreign.get(u.current_location_id or "", {}).get("counterpartyId")]
    contract_states = {"missing": "нет договора", "expired": "срок договора истёк", "closed": "договор закрыт"}
    sections = [
        {"key": "stock_no_place", "title": "На складе, но склад не указан", "action": "correction_place",
         "hint": "Укажите склад актом корректировки учёта: единица числится на складе, а на каком — неизвестно.",
         "items": [_unit_brief(u, locs) for u in units if u.state in ("in_stock_new", "in_stock_used", "reserved") and not u.current_location_id]},
        {"key": "terminal_no_doc", "title": "Списаны или возвращены без документа", "action": "correction_doc",
         "hint": "Состояние пришло из файла, документа нет: оформите акт задним числом (корректировка без смены состояния) с датой и основанием.",
         "items": [_unit_brief(u, locs) for u in units if u.state in ("written_off", "returned_to_vendor") and u.id not in documented]},
        {"key": "keeper_text", "title": "Хранитель записан текстом", "action": "transfer",
         "hint": "Хранитель и договор хранения — текстом в карточке. Заведите склад ответственного хранения у контрагента с договором и переместите единицы на него.",
         "items": [{**_unit_brief(u, locs), "group": (u.keeper or "").strip()} for u in keeper_units]},
        {"key": "warehouse_contract", "title": "На чужом складе без действующего договора", "action": "open",
         "hint": "Склад арендованный или ответственного хранения, а договора нет, он закрыт либо срок истёк: "
                 "продлите или укажите договор в карточке склада либо заберите единицы актом возврата.",
         "items": [{**_unit_brief(u, locs),
                    "group": f"{foreign[u.current_location_id]['name']} — "
                             f"{contract_states[foreign[u.current_location_id]['contractStatus']]}"}
                   for u in units if foreign.get(u.current_location_id or "", {}).get("contractStatus") in contract_states]},
        {"key": "repair_overdue", "title": "В ремонте дольше планового срока", "action": "from_repair",
         "hint": "Плановая дата возврата из ремонта прошла.",
         "items": [{**_unit_brief(u, locs), "due": (repair_due[u.id].details or {}).get("plannedReturn"),
                    "document": repair_due[u.id].number}
                   for u in units if u.state == "in_repair" and u.id in repair_due
                   and (repair_due[u.id].details or {}).get("plannedReturn", "9999") < today]},
        {"key": "unconfirmed", "title": "Данные не подтверждены поставщиком", "action": "open",
         "hint": "Количество портов или модель ждут уточнения у поставщика.",
         "items": [{**_unit_brief(u, locs), "reason": u.unconfirmed_reason} for u in units if not u.data_confirmed]},
    ]
    # Для выгрузки в 1С: номенклатура и стоимость нужны всему, что лежит на учёте склада.
    on_books = [u for u in units if u.state not in ("in_operation", "written_off", "returned_to_vendor")]
    sections += [
        {"key": "no_nomenclature", "title": "Без номенклатуры", "action": "nomenclature",
         "hint": "Модель записана текстом в карточке. Без номенклатуры (вид, единица, счёт учёта) "
                 "единица не выгружается в 1С: свяжите её с номенклатурой или заведите номенклатуру по группе.",
         "items": [{**_unit_brief(u, locs), "group": " ".join(x for x in (u.vendor or u.brand, u.model) if x) or "Модель не указана"}
                   for u in on_books if not u.nomenclature_id]},
        {"key": "no_cost", "title": "Без стоимости", "action": "open",
         "hint": "Стоимость не указана: в оборотно-сальдовой ведомости единица идёт количеством без суммы, "
                 "сверка с бухгалтерией по сумме не сойдётся. Внесите стоимость в карточке единицы.",
         "items": [_unit_brief(u, locs) for u in on_books if u.purchase_amount is None]},
    ]
    for s in sections:
        s["count"] = len(s["items"])
    no_cost = sum(1 for u in units if u.purchase_amount is None and u.state not in ("written_off", "returned_to_vendor"))
    return {"sections": sections, "units": len(units), "noCost": no_cost}
