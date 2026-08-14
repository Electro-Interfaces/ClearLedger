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
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_product, get_current_user
from app.database import get_db
from app.models import (
    Counterparty, OffLedgerCash, OffLedgerPerson, OffLedgerRecord, User,
)

router = APIRouter(prefix="/perimeter", tags=["Периметр"])


async def ensure_perimeter_schema(db: AsyncSession) -> None:
    """Дотянуть колонки, появившиеся после создания таблиц на стенде.

    `create_all` создаёт таблицы, но НЕ добавляет колонки в уже существующие: стенд,
    где «Периметр» встал раньше, получил бы `UndefinedColumnError` на первой же записи.
    Тот же приём применён к каталогу приложений (`app_registry.seed_apps`).
    """
    stmts = [
        "ALTER TABLE off_ledger_cash ADD COLUMN IF NOT EXISTS "
        "person_kind VARCHAR(20) NOT NULL DEFAULT 'individual'",
        "ALTER TABLE off_ledger_cash ADD COLUMN IF NOT EXISTS "
        "formalized BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE off_ledger_cash ADD COLUMN IF NOT EXISTS formalized_on DATE",
        "ALTER TABLE off_ledger_cash ADD COLUMN IF NOT EXISTS formalized_by VARCHAR(300)",
        "ALTER TABLE off_ledger_cash ADD COLUMN IF NOT EXISTS person_id UUID",
    ]
    for sql in stmts:
        try:
            await db.execute(text(sql))
            await db.commit()
        except Exception:  # noqa: BLE001 — не валим старт из-за миграции
            await db.rollback()

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


# ── Наличные расчёты вне учёта ───────────────────────────────────────────────
# Четвёртая грань периметра и единственная, где считаются деньги. Всё остальное в
# продукте — обязательства и имущество; здесь движение наличных, которого нет в кассе
# компании: оплата работы частного лица, заём знакомому, личные средства собственника,
# вложенные в закупку, выручка, забранная на личные нужды.
#
# Главный вопрос раздела не «сколько потратили», а «кто кому остался должен». Поэтому
# возврат ссылается на свою выдачу, а не просто уменьшает общий счёт человека.

CASH_KINDS: dict[str, str] = {
    "work": "Работа и услуги",
    "advance": "Выдано под отчёт",
    "report": "Отчёт по выданному",
    "travel": "Компенсация проезда",
    "bonus": "Премия",
    "loan": "Заём",
    "repayment": "Возврат займа",
    "expense": "Расход на нужды компании",
    "owner": "Расчёт с собственником",
    "other": "Прочее",
}
PERSON_KINDS: dict[str, str] = {
    "employee": "Сотрудник",
    "individual": "Частное лицо",
    "owner": "Собственник",
    "other": "Прочее",
}
# Виды, у которых есть остаток: деньги выданы и должны чем-то закрыться. Заём —
# деньгами, подотчёт — деньгами ИЛИ документами о покупке.
OPEN_KINDS = ("loan", "advance")
# Чем закрывается выданное: возврат наличными и отчёт документами.
CLOSING_KINDS = ("repayment", "report")
# Что бухгалтерия обычно проводит документами. Оплата частнику наличными и заём
# знакомому в учёт не попадут; выдача сотруднику, премия и проезд — попадут, и до
# этого момента операция живёт только здесь.
# Отчёт по выданному сюда НЕ входит: он сам и есть документальное закрытие. Иначе
# одна выдача считается дважды — и как ожидающая оформления, и как отчёт по ней.
FORMALIZABLE = ("advance", "travel", "bonus")
CASH_PROOF: dict[str, str] = {
    "none": "Ничем",
    "receipt": "Расписка",
    "contract": "Договор ГПХ",
    "act": "Акт или наряд",
}
CASH_PURSE: dict[str, str] = {
    "owner": "Личные средства",
    "company": "Наличные компании",
}
CASH_DIRECTIONS: dict[str, str] = {"out": "Выдали", "in": "Получили"}


class CashIn(BaseModel):
    """Движение наличных. Обязательны трое: с кем, сколько и когда."""

    personName: str = Field(min_length=1, max_length=300)
    amount: float = Field(gt=0)
    happenedOn: str
    direction: str = "out"
    kind: str = "work"
    personKind: str = "individual"
    formalized: bool = False
    formalizedOn: str | None = None
    formalizedBy: str | None = None
    purpose: str | None = None
    proof: str = "none"
    purse: str = "owner"
    parentId: str | None = None
    recordId: str | None = None
    dueOn: str | None = None
    note: str | None = None
    counterpartyId: str | None = None


def _cash_row(c: OffLedgerCash, repaid: float = 0.0) -> dict[str, Any]:
    today = date.today()
    rest = round(float(c.amount) - repaid, 2) if c.kind in OPEN_KINDS else None
    return {
        "id": str(c.id),
        "direction": c.direction,
        "directionLabel": CASH_DIRECTIONS.get(c.direction, c.direction),
        "kind": c.kind, "kindLabel": CASH_KINDS.get(c.kind, c.kind),
        "happenedOn": c.happened_on.isoformat(),
        "amount": float(c.amount),
        "person": c.person_name,
        "counterpartyId": str(c.counterparty_id) if c.counterparty_id else None,
        "purpose": c.purpose,
        "proof": c.proof, "proofLabel": CASH_PROOF.get(c.proof, c.proof),
        "purse": c.purse, "purseLabel": CASH_PURSE.get(c.purse, c.purse),
        "parentId": str(c.parent_id) if c.parent_id else None,
        "recordId": str(c.record_id) if c.record_id else None,
        "dueOn": c.due_on.isoformat() if c.due_on else None,
        "overdue": bool(c.kind in OPEN_KINDS and c.due_on and c.due_on < today
                        and (rest or 0) > 0.01),
        "note": c.note,
        "personKind": c.person_kind,
        "personKindLabel": PERSON_KINDS.get(c.person_kind, c.person_kind),
        "formalized": bool(c.formalized),
        "formalizedOn": c.formalized_on.isoformat() if c.formalized_on else None,
        "formalizedBy": c.formalized_by,
        # Ждёт бухгалтерию: операция из тех, что проводят документами, но не проведена.
        "awaitsPapers": bool(c.kind in FORMALIZABLE and not c.formalized),
        # Возвращено и остаток — у займа и подотчёта: у премии или оплаты работы
        # остатка не бывает по природе.
        "repaid": round(repaid, 2) if c.kind in OPEN_KINDS else None,
        "rest": rest,
        "createdAt": c.created_at.isoformat() if c.created_at else None,
    }


async def _repaid_map(cid: uuid.UUID, db: AsyncSession) -> dict[uuid.UUID, float]:
    """Сколько возвращено по каждому займу — одним запросом на весь список."""
    rows = (await db.execute(
        select(OffLedgerCash.parent_id, func.sum(OffLedgerCash.amount))
        .where(OffLedgerCash.company_id == cid,
               OffLedgerCash.kind.in_(CLOSING_KINDS),
               OffLedgerCash.parent_id.isnot(None))
        .group_by(OffLedgerCash.parent_id)
    )).all()
    return {r[0]: float(r[1] or 0) for r in rows}


def _validate_cash(body: CashIn) -> None:
    if body.direction not in CASH_DIRECTIONS:
        raise HTTPException(422, f"Неизвестное направление: {body.direction}")
    if body.kind not in CASH_KINDS:
        raise HTTPException(422, f"Неизвестный вид: {body.kind}")
    if body.proof not in CASH_PROOF:
        raise HTTPException(422, f"Неизвестное подтверждение: {body.proof}")
    if body.purse not in CASH_PURSE:
        raise HTTPException(422, f"Неизвестный источник средств: {body.purse}")
    if body.personKind not in PERSON_KINDS:
        raise HTTPException(422, f"Неизвестная сторона: {body.personKind}")
    # Закрывающая операция без ссылки оставила бы выданное непогашенным навсегда:
    # остаток считается по цепочке, а не вычитанием всех возвратов человека из всех
    # его выдач.
    if body.kind in CLOSING_KINDS and not body.parentId:
        raise HTTPException(422, "Возврат и отчёт нужно привязать к выдаче")
    if body.kind not in OPEN_KINDS and body.dueOn:
        raise HTTPException(422, "Срок бывает у займа и выдачи под отчёт")


@router.get("/cash/dictionaries")
async def cash_dictionaries(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    await assert_company_product(company_id, current_user, db, PRODUCT)
    return {
        "kinds": [{"key": k, "label": v} for k, v in CASH_KINDS.items()],
        "personKinds": [{"key": k, "label": v} for k, v in PERSON_KINDS.items()],
        "proof": [{"key": k, "label": v} for k, v in CASH_PROOF.items()],
        "purse": [{"key": k, "label": v} for k, v in CASH_PURSE.items()],
        "directions": [{"key": k, "label": v} for k, v in CASH_DIRECTIONS.items()],
    }


@router.get("/cash")
async def list_cash(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    kind: str | None = None,
    person: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Журнал движений с итогами периода."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    sel = select(OffLedgerCash).where(OffLedgerCash.company_id == cid)
    if date_from:
        sel = sel.where(OffLedgerCash.happened_on >= _day(date_from))
    if date_to:
        sel = sel.where(OffLedgerCash.happened_on <= _day(date_to))
    if kind:
        sel = sel.where(OffLedgerCash.kind == kind)
    if person:
        sel = sel.where(OffLedgerCash.person_name.ilike(f"%{person.strip()}%"))
    rows = list((await db.execute(
        sel.order_by(OffLedgerCash.happened_on.desc(),
                     OffLedgerCash.created_at.desc()).limit(1000)
    )).scalars().all())
    repaid = await _repaid_map(cid, db)
    items = [_cash_row(c, repaid.get(c.id, 0.0)) for c in rows]

    out = round(sum(i["amount"] for i in items if i["direction"] == "out"), 2)
    inn = round(sum(i["amount"] for i in items if i["direction"] == "in"), 2)
    return {
        "rows": items,
        "count": len(items),
        "out": out, "in": inn, "net": round(inn - out, 2),
        "byKind": [{
            "key": k, "label": v,
            "out": round(sum(i["amount"] for i in items
                             if i["kind"] == k and i["direction"] == "out"), 2),
            "in": round(sum(i["amount"] for i in items
                            if i["kind"] == k and i["direction"] == "in"), 2),
            "count": sum(1 for i in items if i["kind"] == k),
        } for k, v in CASH_KINDS.items() if any(i["kind"] == k for i in items)],
        # Сколько прошло через личные деньги собственника: главный вопрос владельца,
        # у которого расчёты идут из своего кармана.
        "ownerOut": round(sum(i["amount"] for i in items
                              if i["purse"] == "owner" and i["direction"] == "out"), 2),
        "ownerIn": round(sum(i["amount"] for i in items
                             if i["purse"] == "owner" and i["direction"] == "in"), 2),
        # Без единой бумаги: у таких расчётов нет ни доказательства, ни защиты.
        "noProof": round(sum(i["amount"] for i in items if i["proof"] == "none"), 2),
        "noProofCount": sum(1 for i in items if i["proof"] == "none"),
        # Выдачи своим сотрудникам: подотчёт, проезд, премии. Их бухгалтерия проводит
        # документами, и до этого момента они видны только здесь.
        "employeeOut": round(sum(i["amount"] for i in items
                                 if i["personKind"] == "employee"
                                 and i["direction"] == "out"), 2),
        "awaitsPapers": round(sum(i["amount"] for i in items if i["awaitsPapers"]), 2),
        "awaitsPapersCount": sum(1 for i in items if i["awaitsPapers"]),
    }


@router.post("/cash")
async def create_cash(
    company_id: str,
    body: CashIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    _validate_cash(body)
    if body.parentId:
        parent = await db.get(OffLedgerCash, uuid.UUID(body.parentId))
        if parent is None or parent.company_id != cid:
            raise HTTPException(404, "Заём не найден")
        if parent.kind not in OPEN_KINDS:
            raise HTTPException(
                422, "Привязать можно только к займу или выдаче под отчёт")
        # Переплата означает ошибку ввода, а не щедрость: остаток ушёл бы в минус и
        # тихо исказил сальдо по человеку.
        repaid = (await _repaid_map(cid, db)).get(parent.id, 0.0)
        if repaid + body.amount > float(parent.amount) + 0.01:
            # Перерасход по подотчёту оформляют отдельной выдачей, а не отчётом на
            # большую сумму: иначе остаток уходит в минус и искажает расчёты.
            raise HTTPException(
                422, "Больше остатка: не закрыто "
                     f"{round(float(parent.amount) - repaid, 2)} руб.")
    person = await _ensure_person(cid, body.personName, body.personKind,
                                  current_user, db)
    c = OffLedgerCash(
        company_id=cid, direction=body.direction, kind=body.kind,
        person_id=person.id,
        happened_on=_day(body.happenedOn) or date.today(), amount=body.amount,
        person_name=body.personName.strip(),
        counterparty_id=uuid.UUID(body.counterpartyId) if body.counterpartyId else None,
        purpose=body.purpose, proof=body.proof, purse=body.purse,
        person_kind=body.personKind, formalized=body.formalized,
        formalized_on=_day(body.formalizedOn) if body.formalized else None,
        formalized_by=body.formalizedBy if body.formalized else None,
        parent_id=uuid.UUID(body.parentId) if body.parentId else None,
        record_id=uuid.UUID(body.recordId) if body.recordId else None,
        due_on=_day(body.dueOn), note=body.note, created_by=current_user.id,
    )
    db.add(c)
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.cash.create", target=str(c.id),
                    details={"person": c.person_name, "amount": float(c.amount),
                             "kind": c.kind})
    await db.commit()
    await db.refresh(c)
    return _cash_row(c)


@router.put("/cash/{cash_id}")
async def update_cash(
    company_id: str,
    cash_id: str,
    body: CashIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    _validate_cash(body)
    c = await db.get(OffLedgerCash, uuid.UUID(cash_id))
    if c is None or c.company_id != cid:
        raise HTTPException(404, "Движение не найдено")
    # Заём с возвратами не переводится в другой вид: возвраты остались бы висеть на
    # записи, которая больше не долг.
    if c.kind in OPEN_KINDS and body.kind not in OPEN_KINDS:
        if (await _repaid_map(cid, db)).get(c.id, 0.0) > 0:
            raise HTTPException(
                422, "По выдаче есть возвраты или отчёты — вид менять нельзя")
    c.direction, c.kind = body.direction, body.kind
    c.happened_on = _day(body.happenedOn) or c.happened_on
    c.amount = body.amount
    c.person_name = body.personName.strip()
    c.person_id = (await _ensure_person(cid, body.personName, body.personKind,
                                        current_user, db)).id
    c.counterparty_id = uuid.UUID(body.counterpartyId) if body.counterpartyId else None
    c.purpose, c.proof, c.purse = body.purpose, body.proof, body.purse
    c.person_kind = body.personKind
    # Дата оформления проставляется сама в день отметки, если её не назвали: иначе в
    # реестре стоит «проведено» без даты, и непонятно, каким периодом.
    if body.formalized:
        c.formalized = True
        c.formalized_on = _day(body.formalizedOn) or c.formalized_on or date.today()
        c.formalized_by = body.formalizedBy
    else:
        c.formalized, c.formalized_on, c.formalized_by = False, None, None
    c.parent_id = uuid.UUID(body.parentId) if body.parentId else None
    c.record_id = uuid.UUID(body.recordId) if body.recordId else None
    c.due_on, c.note = _day(body.dueOn), body.note
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.cash.update", target=str(c.id),
                    details={"person": c.person_name, "amount": float(c.amount)})
    await db.commit()
    await db.refresh(c)
    return _cash_row(c)


@router.delete("/cash/{cash_id}")
async def delete_cash(
    company_id: str,
    cash_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    c = await db.get(OffLedgerCash, uuid.UUID(cash_id))
    if c is None or c.company_id != cid:
        raise HTTPException(404, "Движение не найдено")
    if c.kind in OPEN_KINDS and (await _repaid_map(cid, db)).get(c.id, 0.0) > 0:
        raise HTTPException(
            422, "По выдаче есть возвраты или отчёты — сначала удалите их")
    person, amount = c.person_name, float(c.amount)
    await db.delete(c)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.cash.delete", target=cash_id,
                    details={"person": person, "amount": amount})
    await db.commit()
    return {"deleted": True}


@router.get("/cash/people")
async def cash_people(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Расчёты по людям: сколько выдано, сколько вернулось, что осталось.

    Долг человека — это НЕ «выдано минус получено»: оплата выполненной работы долгом
    не становится, сколько её ни выдай. Должен человек ровно на непогашенные займы.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    rows = list((await db.execute(
        select(OffLedgerCash).where(OffLedgerCash.company_id == cid)
    )).scalars().all())
    repaid = await _repaid_map(cid, db)
    today = date.today()

    people: dict[str, dict[str, Any]] = {}
    for c in rows:
        p = people.setdefault(c.person_name, {
            "person": c.person_name, "personKind": c.person_kind,
            "personKindLabel": PERSON_KINDS.get(c.person_kind, c.person_kind),
            "out": 0.0, "in": 0.0, "work": 0.0,
            "loanRest": 0.0, "operations": 0, "last": None, "overdue": 0,
            "noProof": 0, "awaits": 0, "awaitsAmount": 0.0,
        })
        amount = float(c.amount)
        p["operations"] += 1
        if c.direction == "out":
            p["out"] += amount
        else:
            p["in"] += amount
        if c.kind == "work":
            p["work"] += amount
        if c.kind in OPEN_KINDS:
            rest = amount - repaid.get(c.id, 0.0)
            # Знак сохраняем: выданное это долг перед нами, полученный заём — наш.
            p["loanRest"] += rest if c.direction == "out" else -rest
            if c.due_on and c.due_on < today and rest > 0.01:
                p["overdue"] += 1
        if c.kind in FORMALIZABLE and not c.formalized:
            p["awaits"] += 1
            p["awaitsAmount"] += amount
        if c.proof == "none":
            p["noProof"] += 1
        if p["last"] is None or c.happened_on > p["last"]:
            p["last"] = c.happened_on

    out = [{
        **p,
        "out": round(p["out"], 2), "in": round(p["in"], 2),
        "work": round(p["work"], 2), "loanRest": round(p["loanRest"], 2),
        "awaitsAmount": round(p["awaitsAmount"], 2),
        "last": p["last"].isoformat() if p["last"] else None,
    } for p in people.values()]
    out.sort(key=lambda p: (-abs(p["loanRest"]), -p["out"]))
    return {
        "rows": out,
        "peopleCount": len(out),
        "loanRestTotal": round(sum(p["loanRest"] for p in out), 2),
    }


@router.get("/cash/loans")
async def cash_loans(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Займы с историей погашения: у каждого видно, что вернулось и когда."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    loans = list((await db.execute(
        select(OffLedgerCash)
        .where(OffLedgerCash.company_id == cid, OffLedgerCash.kind.in_(OPEN_KINDS))
        .order_by(OffLedgerCash.happened_on.desc())
    )).scalars().all())
    pays = list((await db.execute(
        select(OffLedgerCash)
        .where(OffLedgerCash.company_id == cid, OffLedgerCash.kind.in_(CLOSING_KINDS))
        .order_by(OffLedgerCash.happened_on)
    )).scalars().all())
    by_parent: dict[uuid.UUID, list[OffLedgerCash]] = {}
    for p in pays:
        if p.parent_id:
            by_parent.setdefault(p.parent_id, []).append(p)
    repaid = {k: sum(float(x.amount) for x in v) for k, v in by_parent.items()}

    rows = []
    for loan in loans:
        r = _cash_row(loan, repaid.get(loan.id, 0.0))
        r["payments"] = [{
            "id": str(p.id), "happenedOn": p.happened_on.isoformat(),
            "amount": float(p.amount), "note": p.note,
            "kind": p.kind, "kindLabel": CASH_KINDS.get(p.kind, p.kind),
        } for p in by_parent.get(loan.id, [])]
        rows.append(r)

    given = [r for r in rows if r["direction"] == "out"]
    taken = [r for r in rows if r["direction"] == "in"]
    return {
        "rows": rows,
        # Выданные и полученные считаются раздельно: свернуть их в одну цифру значит
        # сказать, что долг знакомого гасит наш долг перед кем-то другим.
        "givenRest": round(sum(r["rest"] or 0 for r in given), 2),
        "takenRest": round(sum(r["rest"] or 0 for r in taken), 2),
        "overdue": sum(1 for r in rows if r["overdue"]),
    }


@router.get("/cash/papers")
async def cash_papers(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Что бухгалтерия ещё не провела документами.

    Часть наличных движений учёт принимает: выданное под отчёт закрывается авансовым
    отчётом, премия проводится ведомостью, компенсация проезда — приказом и чеками.
    Пока документов нет, операция живёт только в периметре, и владельцу нужно видеть
    список, а не вспоминать его.

    Оплата работы частному лицу и заём знакомому сюда не попадают: их учёт не примет
    в принципе, и держать их в очереди на оформление значило бы делать вид, что когда-
    нибудь примет.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    rows = list((await db.execute(
        select(OffLedgerCash)
        .where(OffLedgerCash.company_id == cid,
               OffLedgerCash.kind.in_(FORMALIZABLE))
        .order_by(OffLedgerCash.happened_on.desc())
    )).scalars().all())
    repaid = await _repaid_map(cid, db)
    items = [_cash_row(c, repaid.get(c.id, 0.0)) for c in rows]
    waiting = [i for i in items if not i["formalized"]]
    done = [i for i in items if i["formalized"]]
    return {
        "waiting": waiting,
        "done": done[:100],
        "waitingAmount": round(sum(i["amount"] for i in waiting), 2),
        "doneAmount": round(sum(i["amount"] for i in done), 2),
        "byKind": [{
            "key": k, "label": CASH_KINDS[k],
            "count": sum(1 for i in waiting if i["kind"] == k),
            "amount": round(sum(i["amount"] for i in waiting if i["kind"] == k), 2),
        } for k in FORMALIZABLE if any(i["kind"] == k for i in waiting)],
        # Подотчёт, по которому не отчитались: деньги выданы, документов нет, и с
        # точки зрения учёта это долг сотрудника.
        "openAdvances": [i for i in items
                         if i["kind"] == "advance" and (i["rest"] or 0) > 0.01],
    }


# ── Люди периметра ───────────────────────────────────────────────────────────
# Список тех, с кем компания имеет дело помимо штатного расписания и договоров:
# монтажник на разовых работах, водитель за наличные, сотрудник с подотчётом, знакомый
# с займом, представитель поставщика из устной договорённости.
#
# Это не зарплатный контур и не второй справочник контрагентов. Смысл в другом: через
# полгода «Сергей с гидравликой» не восстанавливается ничем, а расчёты с ним остались.

PEOPLE_KINDS: dict[str, str] = {
    "employee": "Сотрудник",
    "individual": "Частное лицо",
    "owner": "Собственник",
    "contractor_rep": "Представитель контрагента",
    "other": "Прочее",
}


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    kind: str = "individual"
    role: str | None = None
    phone: str | None = None
    counterpartyId: str | None = None
    note: str | None = None
    isActive: bool = True


async def _ensure_person(cid, name: str, kind: str, user: User,
                         db: AsyncSession) -> OffLedgerPerson:
    """Найти человека по имени или завести карточку.

    Заводится САМА при первом расчёте: требовать сначала карточку, а потом операцию —
    верный способ получить журнал вообще без карточек. Вид берётся из операции, но
    поверх не переписывается: в карточке его могли уточнить руками.
    """
    clean = name.strip()
    person = (await db.execute(
        select(OffLedgerPerson).where(OffLedgerPerson.company_id == cid,
                                      func.lower(OffLedgerPerson.name) == clean.lower())
    )).scalar_one_or_none()
    if person is not None:
        return person
    # Вид операции и вид человека совпадают не всегда: у расчёта есть «прочее», у
    # человека — «представитель контрагента». Несовпадающее приводим к частному лицу.
    person = OffLedgerPerson(
        company_id=cid, name=clean,
        kind=kind if kind in PEOPLE_KINDS else "individual",
        created_by=user.id,
    )
    db.add(person)
    await db.flush()
    return person


@router.get("/people")
async def list_people(
    company_id: str,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Список людей с тем, что за каждым числится."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    sel = select(OffLedgerPerson).where(OffLedgerPerson.company_id == cid)
    if q:
        like = f"%{q.strip()}%"
        sel = sel.where(OffLedgerPerson.name.ilike(like)
                        | OffLedgerPerson.role.ilike(like)
                        | OffLedgerPerson.note.ilike(like))
    people = list((await db.execute(sel.order_by(OffLedgerPerson.name)))
                  .scalars().all())

    # Что за человеком числится: операции наличных и незакрытые выдачи.
    moves = list((await db.execute(
        select(OffLedgerCash).where(OffLedgerCash.company_id == cid)
    )).scalars().all())
    repaid = await _repaid_map(cid, db)
    # Договорённости связаны с человеком именем второй стороны: у записи третьего слоя
    # ссылки на карточку нет — она про отношения, а не про расчёты.
    records = list((await db.execute(
        select(OffLedgerRecord).where(OffLedgerRecord.company_id == cid,
                                      OffLedgerRecord.status == "active")
    )).scalars().all())

    names = {}
    for c in moves:
        key = (c.person_name or "").strip().lower()
        agg = names.setdefault(key, {"ops": 0, "out": 0.0, "in": 0.0, "rest": 0.0,
                                     "last": None, "awaits": 0})
        agg["ops"] += 1
        amount = float(c.amount)
        if c.direction == "out":
            agg["out"] += amount
        else:
            agg["in"] += amount
        if c.kind in OPEN_KINDS:
            rest = amount - repaid.get(c.id, 0.0)
            agg["rest"] += rest if c.direction == "out" else -rest
        if c.kind in FORMALIZABLE and not c.formalized:
            agg["awaits"] += 1
        if agg["last"] is None or c.happened_on > agg["last"]:
            agg["last"] = c.happened_on

    rec_by_name: dict[str, int] = {}
    for r in records:
        key = (r.counterparty_name or "").strip().lower()
        if key:
            rec_by_name[key] = rec_by_name.get(key, 0) + 1

    rows = []
    for p in people:
        key = p.name.strip().lower()
        agg = names.get(key, {})
        rows.append({
            "id": str(p.id), "name": p.name,
            "kind": p.kind, "kindLabel": PEOPLE_KINDS.get(p.kind, p.kind),
            "role": p.role, "phone": p.phone,
            "counterpartyId": str(p.counterparty_id) if p.counterparty_id else None,
            "note": p.note, "isActive": bool(p.is_active),
            "operations": agg.get("ops", 0),
            "out": round(agg.get("out", 0.0), 2),
            "in": round(agg.get("in", 0.0), 2),
            "rest": round(agg.get("rest", 0.0), 2),
            "awaits": agg.get("awaits", 0),
            "records": rec_by_name.get(key, 0),
            "last": agg["last"].isoformat() if agg.get("last") else None,
        })
    rows.sort(key=lambda r: (not r["isActive"], -abs(r["rest"]), r["name"]))
    return {
        "rows": rows,
        "kinds": [{"key": k, "label": v} for k, v in PEOPLE_KINDS.items()],
        "count": len(rows),
        "byKind": [{
            "key": k, "label": v,
            "count": sum(1 for r in rows if r["kind"] == k),
        } for k, v in PEOPLE_KINDS.items() if any(r["kind"] == k for r in rows)],
        # Имена из расчётов, которым карточка так и не завелась: бывает у записей,
        # приехавших до появления справочника.
        "orphans": sorted({c.person_name for c in moves
                           if (c.person_name or "").strip().lower()
                           not in {p.name.strip().lower() for p in people}}),
    }


@router.post("/people")
async def create_person(
    company_id: str,
    body: PersonIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    if body.kind not in PEOPLE_KINDS:
        raise HTTPException(422, f"Неизвестный вид: {body.kind}")
    clean = body.name.strip()
    exists = (await db.execute(
        select(OffLedgerPerson).where(OffLedgerPerson.company_id == cid,
                                      func.lower(OffLedgerPerson.name) == clean.lower())
    )).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, "Человек с таким именем уже есть в списке")
    p = OffLedgerPerson(
        company_id=cid, name=clean, kind=body.kind, role=body.role, phone=body.phone,
        counterparty_id=uuid.UUID(body.counterpartyId) if body.counterpartyId else None,
        note=body.note, is_active=body.isActive, created_by=current_user.id,
    )
    db.add(p)
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.person.create", target=str(p.id),
                    details={"name": p.name, "kind": p.kind})
    await db.commit()
    return {"id": str(p.id), "name": p.name}


@router.put("/people/{person_id}")
async def update_person(
    company_id: str,
    person_id: str,
    body: PersonIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    if body.kind not in PEOPLE_KINDS:
        raise HTTPException(422, f"Неизвестный вид: {body.kind}")
    p = await db.get(OffLedgerPerson, uuid.UUID(person_id))
    if p is None or p.company_id != cid:
        raise HTTPException(404, "Человек не найден")
    old_name = p.name
    p.name = body.name.strip()
    p.kind, p.role, p.phone = body.kind, body.role, body.phone
    p.counterparty_id = uuid.UUID(body.counterpartyId) if body.counterpartyId else None
    p.note, p.is_active = body.note, body.isActive
    # Переименование тянет за собой расчёты: они держат имя строкой, и без обновления
    # человек раздвоится — часть операций останется под старым написанием.
    if old_name != p.name:
        await db.execute(
            update(OffLedgerCash)
            .where(OffLedgerCash.company_id == cid,
                   OffLedgerCash.person_name == old_name)
            .values(person_name=p.name, person_id=p.id)
        )
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.person.update", target=str(p.id),
                    details={"name": p.name})
    await db.commit()
    return {"id": str(p.id), "name": p.name}


@router.delete("/people/{person_id}")
async def delete_person(
    company_id: str,
    person_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Удалить можно только того, за кем нет расчётов: иначе история осиротеет.

    Ушедших не удаляют, а помечают неактивными — за ними остаются прошлые операции.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    p = await db.get(OffLedgerPerson, uuid.UUID(person_id))
    if p is None or p.company_id != cid:
        raise HTTPException(404, "Человек не найден")
    used = (await db.execute(
        select(func.count()).select_from(OffLedgerCash)
        .where(OffLedgerCash.company_id == cid,
               OffLedgerCash.person_name == p.name)
    )).scalar() or 0
    if used:
        raise HTTPException(
            422, f"За человеком {used} операций — снимите отметку «в работе» "
                 "вместо удаления")
    name = p.name
    await db.delete(p)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.person.delete", target=person_id,
                    details={"name": name})
    await db.commit()
    return {"deleted": True}
