"""«Периметр» — всё, чем компания владеет и что должна, но чего нет в балансе.

Три слоя, и различать их обязательно.

* **Слой 1 — забалансовый учёт.** Счета 001–012 и МЦ.\\*: арендованное имущество,
  принятое на хранение, комиссия, выданные обеспечения, списанный в убыток долг.
  Официальная бухгалтерия, просто вне баланса.
* **Слой 2 — невидимое в балансе.** Самортизированное до нуля, малоценка, списанная в
  затраты, долг с истёкшим сроком давности. Тоже официально, но видно только
  сопоставлением счетов.
* **Слой 3 — то, чего в учёте нет вовсе.** Устные договорённости, обещания, решения
  собственника, поручительства без бумаги, претензии, о которых пока не написали.
  Источник один — человек, который это помнит.

Первые два слоя живут и в «Бухгалтерии» (раздел «За балансом»): это учётный вопрос, и
бухгалтеру он нужен там, где он работает. Здесь они собраны вместе с третьим, чтобы у
руководителя была одна картина обязательств компании. Считает их тот же код
(`books_router.off_balance*`) — второй реализации у цифры быть не должно.

Третий слой считается только здесь и хранится отдельной таблицей: смешивать
документально подтверждённое с записанным со слов нельзя ни в отчёте, ни на экране.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_product, get_current_user
from app.database import get_db
from app.models import Counterparty, OffLedgerRecord, User

router = APIRouter(prefix="/perimeter", tags=["Периметр"])

PRODUCT = "perimeter"

# Словари продукта. Держатся здесь, а не на фронте: их же читают выгрузка в Excel и
# сводка, и разъехавшийся перевод «guarantee» дал бы два разных названия одному виду.
KINDS: dict[str, str] = {
    "agreement": "Договорённость",
    "promise": "Обещание",
    "guarantee": "Гарантия и поручительство",
    "decision": "Решение",
    "property": "Имущество без документа",
    "claim": "Претензия и спор",
    "other": "Прочее",
}
DIRECTIONS: dict[str, str] = {
    "we_owe": "Должны мы",
    "owed_to_us": "Должны нам",
    "property": "Про имущество",
    "info": "Важно знать",
}
STATUSES: dict[str, str] = {
    "active": "Действует",
    "done": "Исполнено",
    "cancelled": "Снято",
    "formalized": "Оформлено документом",
}
# Чем подтверждено. Порядок значим: он же задаёт «твёрдость» записи в сводке.
CONFIDENCE: dict[str, str] = {
    "spoken": "Со слов",
    "correspondence": "Переписка",
    "signed": "Есть подпись",
}


class RecordIn(BaseModel):
    """Запись периметра с человеческого ввода.

    Обязательно только название: договорённость записывают на ходу, и форма, которая
    требует шесть полей, приводит к тому, что не записывают вовсе.
    """

    title: str = Field(min_length=1, max_length=300)
    kind: str = "agreement"
    direction: str = "we_owe"
    details: str | None = None
    counterpartyId: str | None = None
    counterpartyName: str | None = None
    amount: float | None = None
    startedOn: str | None = None
    dueOn: str | None = None
    status: str = "active"
    confidence: str = "spoken"
    source: str | None = None
    evidence: str | None = None
    consequence: str | None = None
    account: str | None = None
    closedNote: str | None = None


def _day(iso: str | None) -> date | None:
    return date.fromisoformat(iso) if iso else None


def _row(r: OffLedgerRecord, cp_name: str | None = None) -> dict[str, Any]:
    today = date.today()
    overdue = bool(r.status == "active" and r.due_on and r.due_on < today)
    return {
        "id": str(r.id),
        "kind": r.kind, "kindLabel": KINDS.get(r.kind, r.kind),
        "direction": r.direction,
        "directionLabel": DIRECTIONS.get(r.direction, r.direction),
        "title": r.title, "details": r.details,
        "counterpartyId": str(r.counterparty_id) if r.counterparty_id else None,
        "counterparty": cp_name or r.counterparty_name,
        "amount": float(r.amount) if r.amount is not None else None,
        "startedOn": r.started_on.isoformat() if r.started_on else None,
        "dueOn": r.due_on.isoformat() if r.due_on else None,
        # Дней до срока: отрицательное — просрочено. Считается на бэкенде, чтобы
        # «просрочено» не зависело от часового пояса браузера.
        "daysLeft": (r.due_on - today).days if r.due_on else None,
        "overdue": overdue,
        "status": r.status, "statusLabel": STATUSES.get(r.status, r.status),
        "confidence": r.confidence,
        "confidenceLabel": CONFIDENCE.get(r.confidence, r.confidence),
        "source": r.source, "evidence": r.evidence,
        "consequence": r.consequence, "account": r.account,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
        "closedAt": r.closed_at.isoformat() if r.closed_at else None,
        "closedNote": r.closed_note,
    }


async def _with_names(rows: list[OffLedgerRecord], db: AsyncSession) -> list[dict[str, Any]]:
    """Имена контрагентов одним запросом: список записей читается пачкой."""
    ids = {r.counterparty_id for r in rows if r.counterparty_id}
    names: dict[uuid.UUID, str] = {}
    if ids:
        for cid_, name in (await db.execute(
            select(Counterparty.id, Counterparty.name).where(Counterparty.id.in_(ids))
        )).all():
            names[cid_] = name
    return [_row(r, names.get(r.counterparty_id) if r.counterparty_id else None)
            for r in rows]


@router.get("/dictionaries")
async def dictionaries(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Словари продукта — чтобы фронт не держал вторую копию названий."""
    await assert_company_product(company_id, current_user, db, PRODUCT)
    return {
        "kinds": [{"key": k, "label": v} for k, v in KINDS.items()],
        "directions": [{"key": k, "label": v} for k, v in DIRECTIONS.items()],
        "statuses": [{"key": k, "label": v} for k, v in STATUSES.items()],
        "confidence": [{"key": k, "label": v} for k, v in CONFIDENCE.items()],
    }


@router.get("/records")
async def list_records(
    company_id: str,
    status_: str | None = Query(None, alias="status"),
    kind: str | None = None,
    direction: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Реестр третьего слоя."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    sel = select(OffLedgerRecord).where(OffLedgerRecord.company_id == cid)
    if status_:
        sel = sel.where(OffLedgerRecord.status == status_)
    if kind:
        sel = sel.where(OffLedgerRecord.kind == kind)
    if direction:
        sel = sel.where(OffLedgerRecord.direction == direction)
    if q:
        like = f"%{q.strip()}%"
        sel = sel.where(OffLedgerRecord.title.ilike(like)
                        | OffLedgerRecord.details.ilike(like)
                        | OffLedgerRecord.counterparty_name.ilike(like))
    # Действующие впереди и по сроку: реестр открывают, чтобы увидеть ближайшее, а не
    # историю. Записи без срока идут после срочных, но раньше закрытых.
    sel = sel.order_by(
        (OffLedgerRecord.status != "active"),
        OffLedgerRecord.due_on.asc().nulls_last(),
        OffLedgerRecord.created_at.desc(),
    ).limit(500)
    rows = list((await db.execute(sel)).scalars().all())
    return {"rows": await _with_names(rows, db), "count": len(rows)}


@router.post("/records")
async def create_record(
    company_id: str,
    body: RecordIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    _validate(body)
    rec = OffLedgerRecord(
        company_id=cid,
        kind=body.kind, direction=body.direction,
        title=body.title.strip(), details=body.details,
        counterparty_id=uuid.UUID(body.counterpartyId) if body.counterpartyId else None,
        counterparty_name=(body.counterpartyName or None),
        amount=body.amount,
        started_on=_day(body.startedOn), due_on=_day(body.dueOn),
        status=body.status, confidence=body.confidence,
        source=body.source, evidence=body.evidence,
        consequence=body.consequence, account=body.account,
        created_by=current_user.id,
    )
    db.add(rec)
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.record.create", target=str(rec.id),
                    details={"title": rec.title, "kind": rec.kind})
    await db.commit()
    await db.refresh(rec)
    return _row(rec)


@router.put("/records/{record_id}")
async def update_record(
    company_id: str,
    record_id: str,
    body: RecordIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    _validate(body)
    rec = await db.get(OffLedgerRecord, uuid.UUID(record_id))
    if rec is None or rec.company_id != cid:
        raise HTTPException(404, "Запись не найдена")
    was = rec.status
    rec.kind, rec.direction = body.kind, body.direction
    rec.title, rec.details = body.title.strip(), body.details
    rec.counterparty_id = uuid.UUID(body.counterpartyId) if body.counterpartyId else None
    rec.counterparty_name = body.counterpartyName or None
    rec.amount = body.amount
    rec.started_on, rec.due_on = _day(body.startedOn), _day(body.dueOn)
    rec.status, rec.confidence = body.status, body.confidence
    rec.source, rec.evidence = body.source, body.evidence
    rec.consequence, rec.account = body.consequence, body.account
    rec.closed_note = body.closedNote
    # Отметка о закрытии ставится один раз — при уходе из «действует»; возврат в
    # работу её снимает, иначе в реестре останется дата закрытия у живой записи.
    if was == "active" and body.status != "active":
        rec.closed_at = datetime.now(timezone.utc)
    elif body.status == "active":
        rec.closed_at = None
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.record.update", target=str(rec.id),
                    details={"title": rec.title, "status": rec.status})
    await db.commit()
    await db.refresh(rec)
    return _row(rec)


@router.delete("/records/{record_id}")
async def delete_record(
    company_id: str,
    record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Удаление — для ошибочно заведённых. Отработавшую запись закрывают статусом."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    rec = await db.get(OffLedgerRecord, uuid.UUID(record_id))
    if rec is None or rec.company_id != cid:
        raise HTTPException(404, "Запись не найдена")
    title = rec.title
    await db.delete(rec)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.record.delete", target=record_id,
                    details={"title": title})
    await db.commit()
    return {"deleted": True}


def _validate(body: RecordIn) -> None:
    if body.kind not in KINDS:
        raise HTTPException(422, f"Неизвестный вид записи: {body.kind}")
    if body.direction not in DIRECTIONS:
        raise HTTPException(422, f"Неизвестная сторона: {body.direction}")
    if body.status not in STATUSES:
        raise HTTPException(422, f"Неизвестный статус: {body.status}")
    if body.confidence not in CONFIDENCE:
        raise HTTPException(422, f"Неизвестное подтверждение: {body.confidence}")
    if body.startedOn and body.dueOn and body.dueOn < body.startedOn:
        raise HTTPException(422, "Срок раньше даты возникновения")


@router.get("/overview")
async def overview(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Картина периметра: три слоя рядом, но не смешанные.

    Первые два слоя считает «Бухгалтерия» — здесь только берётся её результат. Своей
    арифметики у сводки нет намеренно: две реализации одной цифры расходятся молча.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    from app.routers import books_router as books

    off = await books.off_balance(str(cid), None, None, db, current_user)
    hidden = await books.off_balance_hidden(str(cid), db, current_user)

    rows = list((await db.execute(
        select(OffLedgerRecord).where(OffLedgerRecord.company_id == cid)
    )).scalars().all())
    today = date.today()
    active = [r for r in rows if r.status == "active"]
    overdue = [r for r in active if r.due_on and r.due_on < today]
    # Ближайшее — горизонт месяца: срок дальше него в работу сегодня не берут.
    soon = [r for r in active if r.due_on and 0 <= (r.due_on - today).days <= 30]

    def money(rs: list[OffLedgerRecord]) -> float:
        return round(sum(float(r.amount) for r in rs if r.amount is not None), 2)

    by_kind = [{
        "key": k, "label": v,
        "count": sum(1 for r in active if r.kind == k),
        "amount": money([r for r in active if r.kind == k]),
    } for k, v in KINDS.items()]
    by_confidence = [{
        "key": k, "label": v,
        "count": sum(1 for r in active if r.confidence == k),
        "amount": money([r for r in active if r.confidence == k]),
    } for k, v in CONFIDENCE.items()]

    # Записи, которым место в учёте: у них проставлен забалансовый счёт, а движения по
    # нему нет. Это и есть мост «третий слой → первый»: договорились устно, пора
    # оформлять. Сравниваем со счетами, по которым в учёте что-то происходило.
    used_accounts = {a["code"] for a in off["accounts"]}
    to_formalize = [r for r in active if r.account and r.account not in used_accounts]

    return {
        "layers": [
            {
                "key": "accounts", "no": 1, "title": "Забалансовый учёт",
                "hint": "счета 001–012 и МЦ: официально, но вне баланса",
                "official": True,
                "count": off["propertyEntries"], "amount": off["propertyRest"],
                "empty": not off["propertyEntries"] and not off["propertyRest"],
                "note": f'{off["planCount"]} счетов в плане',
            },
            {
                "key": "hidden", "no": 2, "title": "Не видно в балансе",
                "hint": "самортизированное, списанное в затраты, просроченный долг",
                "official": True,
                "count": len(hidden["stale"]) + len(hidden["lowValue"]),
                "amount": round(hidden["lowValueTotal"] + hidden["staleTotal"]
                                + hidden["fixedRest"], 2),
                "empty": not (hidden["lowValueTotal"] or hidden["staleTotal"]
                              or hidden["fixedCost"]),
                "note": "малоценка, долг старше трёх лет, остаточная стоимость",
            },
            {
                "key": "records", "no": 3, "title": "Договорённости",
                "hint": "устно, письмом, решением: в учёте этого нет вовсе",
                "official": False,
                "count": len(active), "amount": money(active),
                "empty": not active,
                "note": f"{len(rows) - len(active)} закрыто" if rows else "записей нет",
            },
        ],
        "byKind": [k for k in by_kind if k["count"]],
        "byConfidence": [c for c in by_confidence if c["count"]],
        "overdue": await _with_names(sorted(overdue, key=lambda r: r.due_on or today), db),
        "soon": await _with_names(sorted(soon, key=lambda r: r.due_on or today), db),
        "toFormalize": await _with_names(to_formalize, db),
        # Суммы третьего слоя знают не все записи: обещание «починим бесплатно»
        # деньгами не меряется, и делать вид, что оно стоит ноль, нельзя.
        "withoutAmount": sum(1 for r in active if r.amount is None),
        "activeCount": len(active),
        "totalCount": len(rows),
    }


@router.get("/by-counterparty")
async def by_counterparty(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Третий слой в разрезе второй стороны: с кем и о чём договорились."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    rows = list((await db.execute(
        select(OffLedgerRecord).where(OffLedgerRecord.company_id == cid)
    )).scalars().all())
    items = await _with_names(rows, db)
    by: dict[str, dict[str, Any]] = {}
    for r in items:
        key = r["counterparty"] or "Без второй стороны"
        c = by.setdefault(key, {
            "counterparty": key, "counterpartyId": r["counterpartyId"],
            "active": 0, "closed": 0, "amount": 0.0, "overdue": 0,
            "nearest": None, "kinds": set(),
        })
        if r["status"] == "active":
            c["active"] += 1
            if r["amount"]:
                c["amount"] += r["amount"]
            if r["overdue"]:
                c["overdue"] += 1
            if r["dueOn"] and (c["nearest"] is None or r["dueOn"] < c["nearest"]):
                c["nearest"] = r["dueOn"]
        else:
            c["closed"] += 1
        c["kinds"].add(r["kindLabel"])
    out = [{**c, "amount": round(c["amount"], 2), "kinds": sorted(c["kinds"])}
           for c in by.values()]
    out.sort(key=lambda c: (-c["active"], -c["amount"]))
    return {"rows": out}
