"""Ведение условий начисления и ручной ввод документов контрагента.

ЗАЧЕМ. Бэкфилл из реестра поднял контур на реальных данных, но реестр покрывает
не всё: на пилоте 141 действующий договор аренды и энергоснабжения не имеет ни
одного условия, и завести его было нечем — система молчала о них вдвойне.

ВЕРСИОННОСТЬ ВМЕСТО ПРАВКИ НА МЕСТЕ. Ставка выросла с июля — это не «исправить
цифру», а закрыть старую версию и завести новую с `valid_from`. Правка на месте
переписала бы уже закрытые месяцы задним числом: сумма в отчёте, отданном
бухгалтерии, поехала бы молча.

Документы вводятся руками и после подключения почты: бумажный оригинал,
привезённый курьером, ниоткуда сам не появится.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contract,
    OpsContractTerm,
    OpsCostItem,
    OpsCounterpartyDoc,
    OpsPeriodCharge,
)
from app.services.ops_expectations import shift_month

# Поля, которые человек правит в форме. Белый список: `company_id`, `contract_id`
# и горизонт версии меняются только через свои операции, иначе условие можно
# было бы незаметно перевесить на чужой договор.
EDITABLE = (
    "cost_item", "scope_type", "location_id", "periodicity",
    "amount_gross", "amount_net", "vat_pct", "variable_kind", "tariff_rub",
    "pct_of_revenue", "expected_docs", "doc_due_day", "pay_due_day",
    "estimate_basis", "index_kind", "index_pct", "index_month",
    "doc_channel", "counterparty_email", "owner_user_id", "note",
)
PERIODICITY = ("monthly", "quarterly", "annual", "one_time")
SCOPE_TYPES = ("location", "company")


def _as_dict(t: OpsContractTerm) -> dict[str, Any]:
    return {
        "id": str(t.id), "contractId": str(t.contract_id), "costItem": t.cost_item,
        "scopeType": t.scope_type, "locationId": t.location_id,
        "periodicity": t.periodicity,
        "amountGross": float(t.amount_gross) if t.amount_gross is not None else None,
        "amountNet": float(t.amount_net) if t.amount_net is not None else None,
        "vatPct": float(t.vat_pct) if t.vat_pct is not None else None,
        "variableKind": t.variable_kind,
        "tariffRub": float(t.tariff_rub) if t.tariff_rub is not None else None,
        "pctOfRevenue": float(t.pct_of_revenue) if t.pct_of_revenue is not None else None,
        "expectedDocs": t.expected_docs, "docDueDay": t.doc_due_day,
        "payDueDay": t.pay_due_day, "estimateBasis": t.estimate_basis,
        "indexKind": t.index_kind,
        "indexPct": float(t.index_pct) if t.index_pct is not None else None,
        "indexMonth": t.index_month,
        "validFrom": t.valid_from, "validTo": t.valid_to,
        "docChannel": t.doc_channel, "counterpartyEmail": t.counterparty_email,
        "ownerUserId": str(t.owner_user_id) if t.owner_user_id else None,
        "source": t.source, "note": t.note,
        # Действует ли версия сегодня — то, что человек ищет глазами в списке.
        "current": (t.valid_to is None or t.valid_to >= date.today().isoformat()),
    }


async def list_terms(db: AsyncSession, company_id: uuid.UUID,
                     contract_id: str | None = None) -> dict[str, Any]:
    q = select(OpsContractTerm).where(OpsContractTerm.company_id == company_id)
    if contract_id:
        q = q.where(OpsContractTerm.contract_id == uuid.UUID(str(contract_id)))
    rows = (await db.execute(q.order_by(OpsContractTerm.cost_item,
                                        OpsContractTerm.valid_from.desc()))).scalars().all()
    items = [{"code": c.code, "label": c.label, "measure": c.measure,
              "settlementRole": c.settlement_role}
             for c in (await db.execute(select(OpsCostItem).where(
                 OpsCostItem.is_active.is_(True)).order_by(OpsCostItem.sort_order))).scalars().all()]
    return {"terms": [_as_dict(t) for t in rows], "costItems": items}


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    """Привести поля формы к колонкам, отбросив чужое и пустое."""
    alias = {
        "costItem": "cost_item", "scopeType": "scope_type", "locationId": "location_id",
        "amountGross": "amount_gross", "amountNet": "amount_net", "vatPct": "vat_pct",
        "variableKind": "variable_kind", "tariffRub": "tariff_rub",
        "pctOfRevenue": "pct_of_revenue", "expectedDocs": "expected_docs",
        "docDueDay": "doc_due_day", "payDueDay": "pay_due_day",
        "estimateBasis": "estimate_basis", "indexKind": "index_kind",
        "indexPct": "index_pct", "indexMonth": "index_month",
        "docChannel": "doc_channel", "counterpartyEmail": "counterparty_email",
        "ownerUserId": "owner_user_id",
    }
    out: dict[str, Any] = {}
    for key, value in payload.items():
        col = alias.get(key, key)
        if col in EDITABLE:
            out[col] = value if value != "" else None
    return out


def _validate(data: dict[str, Any]) -> None:
    if data.get("periodicity") and data["periodicity"] not in PERIODICITY:
        raise ValueError(f"Неизвестная периодичность: {data['periodicity']}")
    if data.get("scope_type") and data["scope_type"] not in SCOPE_TYPES:
        raise ValueError(f"Неизвестный охват: {data['scope_type']}")
    for field in ("doc_due_day", "pay_due_day"):
        day = data.get(field)
        if day is not None and not (1 <= int(day) <= 31):
            raise ValueError("Число месяца должно быть от 1 до 31")
    # Сумма и «по счётчику» вместе — противоречие: непонятно, чем считать.
    if data.get("variable_kind") == "metered_kwh" and data.get("amount_gross"):
        raise ValueError("Переменная часть по счётчику не сочетается с фиксированной суммой")


async def create_term(db: AsyncSession, company_id: uuid.UUID,
                      payload: dict[str, Any]) -> dict[str, Any]:
    contract_id = payload.get("contractId") or payload.get("contract_id")
    if not contract_id:
        raise ValueError("Не указан договор")
    contract = (await db.execute(select(Contract).where(
        Contract.company_id == company_id,
        Contract.id == uuid.UUID(str(contract_id)),
    ))).scalar_one_or_none()
    if contract is None:
        raise ValueError("Договор не найден")

    data = _clean(payload)
    if not data.get("cost_item"):
        raise ValueError("Не выбрана статья затрат")
    _validate(data)

    # Горизонт версии: начало — от договора, если человек не указал явно. Так
    # условие покрывает историю, а не только будущее.
    valid_from = (payload.get("validFrom") or payload.get("valid_from")
                  or contract.date or date.today().isoformat())[:10]
    valid_to = (payload.get("validTo") or payload.get("valid_to")
                or contract.valid_until or None)

    row = OpsContractTerm(
        company_id=company_id, contract_id=contract.id,
        valid_from=valid_from, valid_to=(valid_to[:10] if valid_to else None),
        scope_type=data.pop("scope_type", None) or "location",
        periodicity=data.pop("periodicity", None) or "monthly",
        source="manual", **data)
    db.add(row)
    await db.flush()
    return _as_dict(row)


async def update_term(db: AsyncSession, company_id: uuid.UUID, term_id: uuid.UUID,
                      payload: dict[str, Any], new_version: bool = False) -> dict[str, Any]:
    """Изменить условие или завести новую его версию.

    Новая версия — правильный способ поднять ставку: старая закрывается днём
    раньше начала новой, и суммы уже закрытых месяцев остаются как были.
    """
    term = (await db.execute(select(OpsContractTerm).where(
        OpsContractTerm.company_id == company_id,
        OpsContractTerm.id == term_id,
    ))).scalar_one_or_none()
    if term is None:
        raise ValueError("Условие не найдено")

    data = _clean(payload)
    _validate({**{k: getattr(term, k) for k in EDITABLE if hasattr(term, k)}, **data})

    if not new_version:
        for col, value in data.items():
            setattr(term, col, value)
        for key, col in (("validFrom", "valid_from"), ("validTo", "valid_to")):
            if payload.get(key):
                setattr(term, col, str(payload[key])[:10])
        await db.flush()
        return _as_dict(term)

    valid_from = str(payload.get("validFrom") or payload.get("valid_from")
                     or shift_month(date.today().isoformat()[:7] + "-01", 1))[:10]
    if valid_from <= term.valid_from:
        raise ValueError("Новая версия должна начинаться позже текущей")
    # Старая версия действует по день перед началом новой. Пересечения быть не
    # должно: иначе месяц развернулся бы дважды, по обеим версиям.
    prev_day = date.fromisoformat(valid_from).toordinal() - 1
    term.valid_to = date.fromordinal(prev_day).isoformat()

    fields = {col: getattr(term, col) for col in EDITABLE if hasattr(term, col)}
    fields.update(data)
    row = OpsContractTerm(
        company_id=company_id, contract_id=term.contract_id,
        valid_from=valid_from,
        valid_to=(str(payload.get("validTo"))[:10] if payload.get("validTo") else None),
        source="manual", **fields)
    db.add(row)
    await db.flush()
    return _as_dict(row)


async def delete_term(db: AsyncSession, company_id: uuid.UUID,
                      term_id: uuid.UUID) -> dict[str, Any]:
    """Удалить условие.

    Начисления закрытых периодов не трогаем: это уже свершившийся учёт, и
    исчезновение условия не отменяет того, что месяц был закрыт этой суммой.
    Удаляем только ожидания, которых ещё никто не касался.
    """
    term = (await db.execute(select(OpsContractTerm).where(
        OpsContractTerm.company_id == company_id,
        OpsContractTerm.id == term_id,
    ))).scalar_one_or_none()
    if term is None:
        raise ValueError("Условие не найдено")

    open_rows = (await db.execute(select(OpsPeriodCharge).where(
        OpsPeriodCharge.company_id == company_id,
        OpsPeriodCharge.term_id == term_id,
        OpsPeriodCharge.status == "expected",
        OpsPeriodCharge.doc_id.is_(None),
    ))).scalars().all()
    for row in open_rows:
        await db.delete(row)
    # У остальных строк связь обнулится каскадом (SET NULL) — история цела.
    await db.delete(term)
    await db.flush()
    return {"ok": True, "removedCharges": len(open_rows)}


# ── Документы ──────────────────────────────────────────────────────────────

DOC_TYPES = ("act", "upd", "invoice", "sf", "torg12", "report", "other")


async def list_docs(db: AsyncSession, company_id: uuid.UUID,
                    match_status: str | None = None,
                    counterparty_id: str | None = None,
                    limit: int = 200) -> dict[str, Any]:
    from app.services.ops_closing import counterparty_names

    q = select(OpsCounterpartyDoc).where(OpsCounterpartyDoc.company_id == company_id)
    if match_status:
        q = q.where(OpsCounterpartyDoc.match_status == match_status)
    if counterparty_id:
        q = q.where(OpsCounterpartyDoc.counterparty_id == counterparty_id)
    rows = (await db.execute(
        q.order_by(OpsCounterpartyDoc.created_at.desc()).limit(limit))).scalars().all()

    names = await counterparty_names(db, company_id, {r.counterparty_id for r in rows})
    # Сколько ожиданий уже закрыто этим документом — по нему видно, разобран он
    # до конца или лежит привязанным к одной строке из десяти.
    used: dict[uuid.UUID, int] = {}
    for doc_id, in (await db.execute(
        select(OpsPeriodCharge.doc_id).where(
            OpsPeriodCharge.company_id == company_id,
            OpsPeriodCharge.doc_id.isnot(None)))).all():
        used[doc_id] = used.get(doc_id, 0) + 1

    return {"docs": [{
        "id": str(d.id), "docType": d.doc_type, "number": d.number, "docDate": d.doc_date,
        "counterpartyId": d.counterparty_id,
        "counterpartyName": names.get(d.counterparty_id or ""),
        "contractId": str(d.contract_id) if d.contract_id else None,
        "period": d.period, "periodFrom": d.period_from, "periodTo": d.period_to,
        "amountGross": float(d.amount_gross) if d.amount_gross is not None else None,
        "amountNet": float(d.amount_net) if d.amount_net is not None else None,
        "qty": float(d.qty) if d.qty is not None else None,
        "channel": d.channel, "parseStatus": d.parse_status,
        "matchStatus": d.match_status, "fileId": str(d.file_id) if d.file_id else None,
        "linkedCharges": used.get(d.id, 0),
        "createdAt": d.created_at.isoformat() if d.created_at else None,
        "note": d.note,
    } for d in rows]}


async def store_file(db: AsyncSession, company_id: uuid.UUID, filename: str | None,
                     mime: str | None, content: bytes) -> uuid.UUID:
    """Положить скан в общее хранилище файлов пространства.

    Тот же `source_files`, что и у документов проектов: скачивание берёт готовая
    ручка `/api/files/{id}` со своей проверкой владельца. Своё файловое
    хранилище контур затрат не заводит — второй способ хранить одно и то же
    расходится с первым на первой же правке.

    Отпечаток считаем всегда: по нему видно, что один и тот же скан приложили к
    двум документам, — обычная история, когда акт и счёт лежат в одном PDF.
    """
    import hashlib
    import os
    from pathlib import Path

    from app.models import SourceFile

    file_id = uuid.uuid4()
    upload_dir = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename or "file").suffix
    path = upload_dir / f"{file_id}{ext}"
    with open(path, "wb") as fh:
        fh.write(content)
    db.add(SourceFile(
        id=file_id, company_id=company_id, file_name=filename or "документ",
        mime_type=mime or "application/octet-stream", size=len(content),
        storage_path=str(path), fingerprint=hashlib.sha256(content).hexdigest()))
    await db.flush()
    return file_id


async def attach_file(db: AsyncSession, company_id: uuid.UUID, doc_id: uuid.UUID,
                      filename: str | None, mime: str | None,
                      content: bytes) -> dict[str, Any]:
    """Прикрепить скан к уже заведённому документу."""
    doc = (await db.execute(select(OpsCounterpartyDoc).where(
        OpsCounterpartyDoc.company_id == company_id,
        OpsCounterpartyDoc.id == doc_id,
    ))).scalar_one_or_none()
    if doc is None:
        raise ValueError("Документ не найден")
    doc.file_id = await store_file(db, company_id, filename, mime, content)
    await db.flush()
    return {"id": str(doc.id), "fileId": str(doc.file_id), "fileName": filename}


async def create_doc(db: AsyncSession, company_id: uuid.UUID, payload: dict[str, Any],
                     user_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Завести документ руками.

    Сумма и период обязательны: документ без них не закрывает ожидание, а
    только создаёт видимость работы — строка получит привязку, но проверить по
    ней будет нечего.
    """
    doc_type = (payload.get("docType") or payload.get("doc_type") or "act").strip()
    if doc_type not in DOC_TYPES:
        raise ValueError(f"Неизвестный вид документа: {doc_type}")
    amount = payload.get("amountGross", payload.get("amount_gross"))
    if amount in (None, ""):
        raise ValueError("Не указана сумма документа")
    period = payload.get("period")
    period_from = payload.get("periodFrom") or payload.get("period_from")
    if not period and not period_from:
        raise ValueError("Не указан период, за который выставлен документ")

    row = OpsCounterpartyDoc(
        company_id=company_id, doc_type=doc_type,
        number=(payload.get("number") or None),
        doc_date=(str(payload.get("docDate") or payload.get("doc_date") or "")[:10] or None),
        counterparty_id=(payload.get("counterpartyId") or payload.get("counterparty_id")),
        contract_id=(uuid.UUID(str(payload["contractId"]))
                     if payload.get("contractId") else None),
        period=(f"{str(period)[:7]}-01" if period else None),
        period_from=(str(period_from)[:10] if period_from else None),
        period_to=(str(payload.get("periodTo") or payload.get("period_to") or "")[:10] or None),
        amount_gross=float(amount),
        amount_net=(float(payload["amountNet"]) if payload.get("amountNet") not in (None, "") else None),
        vat_amount=(float(payload["vatAmount"]) if payload.get("vatAmount") not in (None, "") else None),
        qty=(float(payload["qty"]) if payload.get("qty") not in (None, "") else None),
        channel=(payload.get("channel") or "manual"),
        file_id=(uuid.UUID(str(payload["fileId"])) if payload.get("fileId") else None),
        parse_status="manual", match_status="unmatched",
        note=(payload.get("note") or None),
        matched_by=user_id, matched_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return {"id": str(row.id), "docType": row.doc_type, "number": row.number,
            "amountGross": float(row.amount_gross) if row.amount_gross else None,
            "period": row.period, "matchStatus": row.match_status}
