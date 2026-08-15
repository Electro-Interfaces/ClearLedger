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
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_product, get_current_user
from app.database import get_db
# Календарная арифметика периодов живёт отдельным модулем: её гоняет
# проверка `scripts/perimeter-periods-check.py` без базы и FastAPI.
from app.services.perimeter_periods import (
    PERIODICITY, _next_period, _period_label, _period_start, _periods,
)
from app.models import (
    Counterparty, OffLedgerCash, OffLedgerCommitment, OffLedgerCommitmentMark,
    OffLedgerPerson, OffLedgerRecord, OffLedgerReminder, OffLedgerReview,
    OffLedgerSettings, User,
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
        "ALTER TABLE off_ledger_cash ADD COLUMN IF NOT EXISTS commitment_id UUID",
        "ALTER TABLE off_ledger_cash ADD COLUMN IF NOT EXISTS commitment_period DATE",
        "ALTER TABLE off_ledger_commitments ADD COLUMN IF NOT EXISTS paused_on DATE",
        # Уникальность отметки за период и имени человека — на них стоит весь расчёт:
        # две отметки за август означали бы, что обязательство выполнено дважды.
        # `create_all` в существующей таблице индексы не создаёт.
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_off_mark_period "
        "ON off_ledger_commitment_marks (commitment_id, period_start)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_off_person_name "
        "ON off_ledger_people (company_id, name)",
        "ALTER TABLE off_ledger_cash ADD COLUMN IF NOT EXISTS acknowledged_on DATE",
        "ALTER TABLE off_ledger_cash ADD COLUMN IF NOT EXISTS acknowledged_by "
        "VARCHAR(200)",
        "ALTER TABLE off_ledger_cash ADD COLUMN IF NOT EXISTS "
        "writeoff_reason VARCHAR(20)",
        "ALTER TABLE off_ledger_people ADD COLUMN IF NOT EXISTS "
        "payout_phone VARCHAR(50)",
        "ALTER TABLE off_ledger_people ADD COLUMN IF NOT EXISTS "
        "payout_bank VARCHAR(100)",
        "ALTER TABLE off_ledger_people ADD COLUMN IF NOT EXISTS "
        "payout_note VARCHAR(300)",
        "ALTER TABLE off_ledger_records ADD COLUMN IF NOT EXISTS likelihood VARCHAR(20)",
        "ALTER TABLE off_ledger_records ADD COLUMN IF NOT EXISTS "
        "amount_min NUMERIC(18,2)",
        "ALTER TABLE off_ledger_records ADD COLUMN IF NOT EXISTS "
        "amount_max NUMERIC(18,2)",
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
# Насколько вероятно, что обязательство сработает. Градация из практики условных
# обязательств: «вероятно» — кандидат в резерв бухгалтерии, «возможно» — раскрытие,
# «маловероятно» — держим в виду. Без этой оси гарантия с шансом три процента
# складывается с почти верной претензией.
LIKELIHOOD: dict[str, str] = {
    "probable": "Вероятно",
    "possible": "Возможно",
    "remote": "Маловероятно",
}
# Виды, у которых вероятность осмысленна: у обещания или решения её не спрашивают.
LIKELIHOOD_KINDS = ("guarantee", "claim")


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
    amount: float | None = Field(default=None, ge=0)
    startedOn: str | None = None
    dueOn: str | None = None
    status: str = "active"
    confidence: str = "spoken"
    source: str | None = Field(default=None, max_length=200)
    evidence: str | None = Field(default=None, max_length=500)
    consequence: str | None = Field(default=None, max_length=4000)
    account: str | None = Field(default=None, max_length=20)
    likelihood: str | None = None
    amountMin: float | None = Field(default=None, ge=0)
    amountMax: float | None = Field(default=None, ge=0)
    closedNote: str | None = None


def _day(iso: str | None) -> date | None:
    """ISO-строка → дата. Мусор во входных данных — ошибка запроса, а не сбой сервера."""
    if not iso:
        return None
    try:
        return date.fromisoformat(iso)
    except ValueError:
        raise HTTPException(422, f"Неверная дата: {iso}") from None


def _uuid(value: str | None, what: str = "идентификатор"):
    """UUID из строки; кривая строка — 422, а не 500 из недр драйвера."""
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(422, f"Неверный {what}: {value}") from None


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
        "likelihood": r.likelihood,
        "likelihoodLabel": LIKELIHOOD.get(r.likelihood or "", None),
        "amountMin": float(r.amount_min) if r.amount_min is not None else None,
        "amountMax": float(r.amount_max) if r.amount_max is not None else None,
        # Ожидаемая величина: у «вероятно» это сумма целиком, у «возможно» — половина,
        # у «маловероятного» — ноль. Грубая шкала намеренно: точность здесь мнимая, а
        # порядок величины рабочий, и он не даёт сложить несравнимое.
        "expected": (round(float(r.amount) * {"probable": 1.0, "possible": 0.5,
                                              "remote": 0.0}[r.likelihood], 2)
                     if r.amount is not None and r.likelihood in LIKELIHOOD else None),
        "createdAt": r.created_at.isoformat() if r.created_at else None,
        "closedAt": r.closed_at.isoformat() if r.closed_at else None,
        "closedNote": r.closed_note,
    }


async def _with_names(rows: list[OffLedgerRecord], db: AsyncSession,
                      cid=None) -> list[dict[str, Any]]:
    """Имена контрагентов одним запросом: список записей читается пачкой.

    Фильтр по компании обязателен: без него ссылка на чужого контрагента вернула бы
    его наименование пользователю другой компании.
    """
    ids = {r.counterparty_id for r in rows if r.counterparty_id}
    names: dict[uuid.UUID, str] = {}
    if ids:
        sel = select(Counterparty.id, Counterparty.name).where(Counterparty.id.in_(ids))
        if cid is not None:
            sel = sel.where(Counterparty.company_id == cid)
        for cid_, name in (await db.execute(sel)).all():
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
    return {"rows": await _with_names(rows, db, cid), "count": len(rows)}


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
        counterparty_id=_uuid(body.counterpartyId, "контрагент"),
        counterparty_name=(body.counterpartyName or None),
        amount=body.amount,
        started_on=_day(body.startedOn), due_on=_day(body.dueOn),
        status=body.status, confidence=body.confidence,
        source=body.source, evidence=body.evidence,
        consequence=body.consequence, account=body.account,
        likelihood=body.likelihood, amount_min=body.amountMin,
        amount_max=body.amountMax, created_by=current_user.id,
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
    rec = await db.get(OffLedgerRecord, _uuid(record_id, "идентификатор записи"))
    if rec is None or rec.company_id != cid:
        raise HTTPException(404, "Запись не найдена")
    was = rec.status
    rec.kind, rec.direction = body.kind, body.direction
    rec.title, rec.details = body.title.strip(), body.details
    rec.counterparty_id = _uuid(body.counterpartyId, "контрагент")
    rec.counterparty_name = body.counterpartyName or None
    rec.amount = body.amount
    rec.started_on, rec.due_on = _day(body.startedOn), _day(body.dueOn)
    rec.status, rec.confidence = body.status, body.confidence
    rec.source, rec.evidence = body.source, body.evidence
    rec.consequence, rec.account = body.consequence, body.account
    rec.likelihood = body.likelihood
    rec.amount_min, rec.amount_max = body.amountMin, body.amountMax
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
    rec = await db.get(OffLedgerRecord, _uuid(record_id, "идентификатор записи"))
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
    if body.likelihood and body.likelihood not in LIKELIHOOD:
        raise HTTPException(422, f"Неизвестная вероятность: {body.likelihood}")
    if (body.amountMin is not None and body.amountMax is not None
            and body.amountMax < body.amountMin):
        raise HTTPException(422, "Верх вилки ниже низа")


@router.get("/overview")
async def overview(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Картина периметра: все грани рядом, но не смешанные.

    Три слоя обязательств плюс деньги, идущие мимо кассы, и регулярные обязательства.
    Экран открывают, чтобы одним взглядом понять, что просрочено и что ждёт действия, —
    поэтому здесь же собраны все хвосты: пропущенные периоды, незакрытый подотчёт,
    очередь на оформление в бухгалтерии.

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

    # Наличные и регулярные обязательства: те же ручки, что рисуют свои экраны.
    cash = await list_cash(str(cid), None, None, None, None, db, current_user)
    papers = await cash_papers(str(cid), db, current_user)
    loans = await cash_loans(str(cid), db, current_user)
    commitments = await list_commitments(str(cid), db, current_user)
    missed = [c for c in commitments["rows"]
              if c["status"] == "active" and c["missedCount"]]

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
        # Деньги и регулярные обязательства — не четвёртый и пятый слои, а другой срез
        # того же периметра: слои отвечают «что у нас есть и что мы должны», эти два —
        # «что происходит и что надо сделать». Поэтому отдельным блоком, не в ряду слоёв.
        "cash": {
            "out": cash["out"], "in": cash["in"],
            "ownerOut": cash["ownerOut"],
            "count": cash["count"],
            "noProof": cash["noProof"],
            "awaitsPapers": papers["waitingAmount"],
            "awaitsPapersCount": len(papers["waiting"]),
            "openAdvances": len(papers["openAdvances"]),
            "loanGiven": loans["givenRest"],
            "loanTaken": loans["takenRest"],
            "loanOverdue": loans["overdue"],
        },
        "commitments": {
            "active": commitments["activeCount"],
            "people": commitments["peopleCount"],
            "monthlyMoney": commitments["monthlyMoney"],
            "missedTotal": commitments["missedTotal"],
            # Кого именно подводим: без имён цифра «пропущено 7» ничего не меняет.
            "missed": [{
                "id": c["id"], "person": c["person"], "title": c["title"],
                "missedCount": c["missedCount"],
                "missedPeriods": c["missedPeriods"],
                "missedAmount": c["missedAmount"],
            } for c in sorted(missed, key=lambda c: -c["missedCount"])[:10]],
        },
        "byKind": [k for k in by_kind if k["count"]],
        "byConfidence": [c for c in by_confidence if c["count"]],
        "overdue": await _with_names(sorted(overdue, key=lambda r: r.due_on or today), db, cid),
        "soon": await _with_names(sorted(soon, key=lambda r: r.due_on or today), db, cid),
        "toFormalize": await _with_names(to_formalize, db, cid),
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
    items = await _with_names(rows, db, cid)
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
    # Выплата работнику помимо расчётного листка, из средств собственника. Вид скрыт,
    # пока компания не включит его в настройках: у того, кто так не работает, его в
    # списке быть не должно. Название нейтральное намеренно — ярлык, поставленный
    # системой, потом читается как признание, а решать это не программе.
    "extra_pay": "Доплата сверх ведомости",
    # Взаимозачёт: у человека и выданный ему заём, и наш долг перед ним. Деньги при
    # этом не движутся, поэтому в приход-расход операция не попадает — она закрывает
    # обе стороны разом.
    "offset": "Взаимозачёт",
    # Списание долга: простили, признали безнадёжным или истёк срок давности. Долг не
    # исчезает бесследно — он меняет природу и уходит на забалансовый счёт 007, где
    # числится ещё пять лет. Деньгами эта операция тоже не движется.
    "writeoff": "Списание долга",
    # Расхождение, найденное пересчётом кошелька: деньги ушли или пришли мимо записи.
    # Отдельным видом, а не правкой остатка: важно видеть масштаб незаписанного.
    "adjust": "Пересчёт наличных",
    "other": "Прочее",
}
# Виды, доступные только при включённой настройке.
GATED_KINDS = {"extra_pay": "allow_extra_pay"}
PERSON_KINDS: dict[str, str] = {
    "employee": "Сотрудник",
    "individual": "Частное лицо",
    "owner": "Собственник",
    "other": "Прочее",
}
# Виды, у которых есть остаток: деньги выданы и должны чем-то закрыться. Заём —
# деньгами, подотчёт — деньгами ИЛИ документами о покупке.
OPEN_KINDS = ("loan", "advance")
# Чем закрывается выданное: возврат наличными, отчёт документами и взаимозачёт
# встречного долга. Последний денег не двигает, но выдачу гасит так же.
CLOSING_KINDS = ("repayment", "report", "offset", "writeoff")
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
# Почему списали долг. Причина решает судьбу записи в учёте: прощённый долг это
# расход, безнадёжный уходит на 007 и числится пять лет, истёкший срок — тоже 007,
# но по другому основанию.
WRITEOFF_REASONS: dict[str, str] = {
    "forgiven": "Простили",
    "hopeless": "Взыскать не с кого",
    "expired": "Истёк срок давности",
}
# Как напоминали и чем это кончилось.
REMINDER_CHANNELS: dict[str, str] = {
    "talk": "Разговор", "call": "Звонок", "chat": "Сообщение",
    "mail": "Письмо", "other": "Иначе",
}
REMINDER_OUTCOMES: dict[str, str] = {
    "promised": "Обещал вернуть",
    "paid": "Рассчитался сразу",
    "refused": "Отказал",
    "silent": "Не ответил",
}


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
    formalizedBy: str | None = Field(default=None, max_length=300)
    purpose: str | None = Field(default=None, max_length=4000)
    proof: str = "none"
    purse: str = "owner"
    parentId: str | None = None
    recordId: str | None = None
    # Регулярное обязательство, по которому платят: отметка за период поставится сама.
    commitmentId: str | None = None
    # За какой период платим. Пусто — период даты операции, но чаще платят за
    # прошедший: доплату за август выдают в сентябре, и отметка должна лечь на август.
    commitmentPeriod: str | None = None
    # Действие должника, из которого видно, что он признаёт долг: оно ПРЕРЫВАЕТ срок
    # исковой давности, и тот начинает течь заново.
    acknowledgedOn: str | None = None
    acknowledgedBy: str | None = Field(default=None, max_length=200)
    # Почему списали: forgiven — простили, hopeless — взыскать не с кого,
    # expired — истёк срок давности.
    writeoffReason: str | None = None
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
        "commitmentId": str(c.commitment_id) if c.commitment_id else None,
        "dueOn": c.due_on.isoformat() if c.due_on else None,
        "overdue": bool(c.kind in OPEN_KINDS and c.due_on and c.due_on < today
                        and (rest or 0) > 0.01),
        "note": c.note,
        "writeoffReason": c.writeoff_reason,
        "writeoffReasonLabel": WRITEOFF_REASONS.get(c.writeoff_reason or "", None),
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


async def _repaid_map(cid: uuid.UUID, db: AsyncSession,
                      exclude_id: uuid.UUID | None = None) -> dict[uuid.UUID, float]:
    """Сколько закрыто по каждой выдаче — одним запросом на весь список.

    `exclude_id` исключает правимую операцию: без этого её прежняя сумма считалась бы
    вместе с новой, и правка «в ту же сумму» выглядела бы переплатой.
    """
    sel = (select(OffLedgerCash.parent_id, func.sum(OffLedgerCash.amount))
           .where(OffLedgerCash.company_id == cid,
                  OffLedgerCash.kind.in_(CLOSING_KINDS),
                  OffLedgerCash.parent_id.isnot(None)))
    if exclude_id is not None:
        sel = sel.where(OffLedgerCash.id != exclude_id)
    rows = (await db.execute(sel.group_by(OffLedgerCash.parent_id))).all()
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
    if body.kind == "writeoff" and body.writeoffReason not in WRITEOFF_REASONS:
        raise HTTPException(422, "У списания долга нужна причина")


async def _check_parent(cid, body: CashIn, db: AsyncSession,
                        exclude_id: uuid.UUID | None = None) -> None:
    """Проверить выдачу, к которой привязывают возврат или отчёт.

    Одна функция на создание и правку: раньше правка не проверяла ничего, и остаток
    уводили в минус — раздутым возвратом или уменьшением суммы самой выдачи.
    `exclude_id` нужен при правке, чтобы операция не считала саму себя погашением.
    """
    if not body.parentId:
        return
    parent = await db.get(OffLedgerCash, _uuid(body.parentId, "документ-основание"))
    if parent is None or parent.company_id != cid:
        raise HTTPException(404, "Выдача не найдена")
    if parent.kind not in OPEN_KINDS:
        raise HTTPException(422, "Привязать можно только к займу или выдаче под отчёт")
    if exclude_id is not None and parent.id == exclude_id:
        raise HTTPException(422, "Операция не может закрывать сама себя")
    # Возврат идёт навстречу выдаче: «возврат» в ту же сторону означал бы, что деньги
    # ушли дважды, а долг при этом уменьшился.
    if body.kind == "repayment" and body.direction == parent.direction:
        raise HTTPException(
            422, "Возврат идёт навстречу выдаче: "
                 + ("выдали — значит получаем обратно"
                    if parent.direction == "out" else "получали — значит отдаём"))
    # Переплата означает ошибку ввода, а не щедрость: остаток ушёл бы в минус и тихо
    # исказил расчёты с человеком. Перерасход по подотчёту оформляют отдельной выдачей.
    repaid = (await _repaid_map(cid, db, exclude_id=exclude_id)).get(parent.id, 0.0)
    if repaid + body.amount > float(parent.amount) + 0.01:
        raise HTTPException(
            422, "Больше остатка: не закрыто "
                 f"{round(float(parent.amount) - repaid, 2)} руб.")


@router.get("/cash/dictionaries")
async def cash_dictionaries(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    st = await _settings(cid, db)
    out = {
        # Виды под настройкой в список не попадают: у компании, которая так не
        # работает, их быть не должно.
        "kinds": [{"key": k, "label": v} for k, v in CASH_KINDS.items()
                  if k not in GATED_KINDS or getattr(st, GATED_KINDS[k])],
        "settings": _settings_row(st),
        "personKinds": [{"key": k, "label": v} for k, v in PERSON_KINDS.items()],
        "proof": [{"key": k, "label": v} for k, v in CASH_PROOF.items()],
        "purse": [{"key": k, "label": v} for k, v in CASH_PURSE.items()],
        "directions": [{"key": k, "label": v} for k, v in CASH_DIRECTIONS.items()],
    }
    await db.commit()
    return out


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
    # Итоги считаются по ВСЕЙ выборке, показывается страница: сумма по первой тысяче
    # строк молча занижала бы плитки на компании с длинной историей.
    all_rows = list((await db.execute(
        sel.order_by(OffLedgerCash.happened_on.desc(),
                     OffLedgerCash.created_at.desc())
    )).scalars().all())
    rows = all_rows[:1000]
    repaid = await _repaid_map(cid, db)
    items = [_cash_row(c, repaid.get(c.id, 0.0)) for c in all_rows]

    # Отчёт документами деньгами не движется: сотрудник принёс чеки, наличные ушли
    # раньше — выдачей. Складывать их с выдачей значит показать двойной расход.
    cashflow = [i for i in items
                if i["kind"] not in ("report", "offset", "writeoff")]
    out = round(sum(i["amount"] for i in cashflow if i["direction"] == "out"), 2)
    inn = round(sum(i["amount"] for i in cashflow if i["direction"] == "in"), 2)
    return {
        "rows": items[:1000],
        "count": len(items),
        # Сколько строк показано: без этого обрезанный список читается как полный.
        "shown": min(len(items), 1000),
        "out": out, "in": inn, "net": round(inn - out, 2),
        "byKind": [{
            "key": k, "label": v,
            "out": round(sum(i["amount"] for i in cashflow
                             if i["kind"] == k and i["direction"] == "out"), 2),
            "in": round(sum(i["amount"] for i in cashflow
                            if i["kind"] == k and i["direction"] == "in"), 2),
            "count": sum(1 for i in items if i["kind"] == k),
        } for k, v in CASH_KINDS.items() if any(i["kind"] == k for i in items)],
        # Сколько прошло через личные деньги собственника: главный вопрос владельца,
        # у которого расчёты идут из своего кармана.
        "ownerOut": round(sum(i["amount"] for i in cashflow
                              if i["purse"] == "owner" and i["direction"] == "out"), 2),
        "ownerIn": round(sum(i["amount"] for i in cashflow
                             if i["purse"] == "owner" and i["direction"] == "in"), 2),
        # Без единой бумаги: у таких расчётов нет ни доказательства, ни защиты.
        "noProof": round(sum(i["amount"] for i in items if i["proof"] == "none"), 2),
        "noProofCount": sum(1 for i in items if i["proof"] == "none"),
        # Выдачи своим сотрудникам: подотчёт, проезд, премии. Их бухгалтерия проводит
        # документами, и до этого момента они видны только здесь.
        "employeeOut": round(sum(i["amount"] for i in cashflow
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
    await _check_gated(cid, body.kind, db)
    await _check_parent(cid, body, db)
    person = await _ensure_person(cid, body.personName, body.personKind,
                                  current_user, db)
    c = OffLedgerCash(
        company_id=cid, direction=body.direction, kind=body.kind,
        person_id=person.id,
        happened_on=_day(body.happenedOn) or date.today(), amount=body.amount,
        person_name=body.personName.strip(),
        counterparty_id=_uuid(body.counterpartyId, "контрагент"),
        purpose=body.purpose, proof=body.proof, purse=body.purse,
        person_kind=body.personKind, formalized=body.formalized,
        formalized_on=_day(body.formalizedOn) if body.formalized else None,
        formalized_by=body.formalizedBy if body.formalized else None,
        parent_id=_uuid(body.parentId, "документ-основание"),
        record_id=_uuid(body.recordId, "договорённость"),
        commitment_id=_uuid(body.commitmentId, "обязательство"),
        commitment_period=_day(body.commitmentPeriod),
        acknowledged_on=_day(body.acknowledgedOn),
        acknowledged_by=body.acknowledgedBy,
        writeoff_reason=body.writeoffReason,
        due_on=_day(body.dueOn), note=body.note, created_by=current_user.id,
    )
    db.add(c)
    await db.flush()
    # Выплата по регулярному обязательству закрывает свой период сама: вводить одно и
    # то же дважды — в журнал и в полосу периодов — человек не станет, и полоса
    # останется красной при выплаченных деньгах.
    if c.commitment_id:
        await _touch_commitment_mark(cid, c, current_user, db)
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
    await _check_gated(cid, body.kind, db)
    c = await db.get(OffLedgerCash, _uuid(cash_id, "идентификатор операции"))
    if c is None or c.company_id != cid:
        raise HTTPException(404, "Движение не найдено")
    # Те же проверки, что при создании: без них правкой можно было увести остаток в
    # минус — уменьшить сумму займа ниже возвращённого или раздуть возврат.
    await _check_parent(cid, body, db, exclude_id=c.id)
    closed = (await _repaid_map(cid, db)).get(c.id, 0.0)
    if body.kind in OPEN_KINDS and closed - body.amount > 0.01:
        raise HTTPException(
            422, f"По выдаче уже закрыто {round(closed, 2)} руб. — "
                 "сумма не может быть меньше")
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
    c.counterparty_id = _uuid(body.counterpartyId, "контрагент")
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
    c.parent_id = _uuid(body.parentId, "документ-основание")
    c.record_id = _uuid(body.recordId, "договорённость")
    c.commitment_id = _uuid(body.commitmentId, "обязательство")
    c.commitment_period = _day(body.commitmentPeriod)
    c.acknowledged_on = _day(body.acknowledgedOn)
    c.acknowledged_by = body.acknowledgedBy
    c.writeoff_reason = body.writeoffReason
    c.due_on, c.note = _day(body.dueOn), body.note
    if c.commitment_id:
        await _touch_commitment_mark(cid, c, current_user, db)
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
    c = await db.get(OffLedgerCash, _uuid(cash_id, "идентификатор операции"))
    if c is None or c.company_id != cid:
        raise HTTPException(404, "Движение не найдено")
    if c.kind in OPEN_KINDS and (await _repaid_map(cid, db)).get(c.id, 0.0) > 0:
        raise HTTPException(
            422, "По выдаче есть возвраты или отчёты — сначала удалите их")
    person, amount = c.person_name, float(c.amount)
    com = await db.get(OffLedgerCommitment, c.commitment_id) if c.commitment_id else None
    await db.delete(c)
    await db.flush()
    # Период, который держался только на этой выплате, снова становится незакрытым:
    # ошибочно введённые деньги не должны оставлять обязательство «выполненным».
    if com is not None and com.company_id == cid:
        await _drop_orphan_marks(cid, com, db)
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
        # Ключ — нормализованное имя, как в списке людей: иначе «Иван» и «иван» дают
        # две строки с разрезанным пополам сальдо на одном экране и одну на другом.
        p = people.setdefault(c.person_name.strip().lower(), {
            "person": c.person_name, "personKind": c.person_kind,
            "personKindLabel": PERSON_KINDS.get(c.person_kind, c.person_kind),
            "out": 0.0, "in": 0.0, "work": 0.0,
            "loanRest": 0.0, "operations": 0, "last": None, "overdue": 0,
            "noProof": 0, "awaits": 0, "awaitsAmount": 0.0,
            # Встречные стороны: сколько должен нам он и сколько должны мы ему.
            "owed": 0.0, "owes": 0.0,
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
            if rest > 0.01:
                if c.direction == "out":
                    p["owed"] += rest
                else:
                    p["owes"] += rest
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
        # Нетто по паре: сворачиваем только внутри одного человека и только незакрытое.
        # Переносить долг на третье лицо продукт не станет — перевод долга требует
        # согласия кредитора, и запись «Иванов должен Петрову», которой не было, не
        # имеет ни силы, ни смысла.
        "net": round(p["loanRest"], 2),
        "canOffset": bool(p["owed"] > 0.01 and p["owes"] > 0.01),
        "owed": round(p["owed"], 2), "owes": round(p["owes"], 2),
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
    role: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    # Как вернуть деньги: телефон перевода, банк, любой другой способ словами.
    payoutPhone: str | None = Field(default=None, max_length=50)
    payoutBank: str | None = Field(default=None, max_length=100)
    payoutNote: str | None = Field(default=None, max_length=300)
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
            "payoutPhone": p.payout_phone, "payoutBank": p.payout_bank,
            "payoutNote": p.payout_note,
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
    known = {p.name.strip().lower() for p in people}
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
                           if (c.person_name or "").strip().lower() not in known}),
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
        payout_phone=body.payoutPhone, payout_bank=body.payoutBank,
        payout_note=body.payoutNote,
        counterparty_id=_uuid(body.counterpartyId, "контрагент"),
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
    p = await db.get(OffLedgerPerson, _uuid(person_id, "идентификатор человека"))
    if p is None or p.company_id != cid:
        raise HTTPException(404, "Человек не найден")
    old_name = p.name
    p.name = body.name.strip()
    p.kind, p.role, p.phone = body.kind, body.role, body.phone
    p.payout_phone, p.payout_bank = body.payoutPhone, body.payoutBank
    p.payout_note = body.payoutNote
    p.counterparty_id = _uuid(body.counterpartyId, "контрагент")
    p.note, p.is_active = body.note, body.isActive
    # Переименование тянет за собой расчёты: они держат имя строкой, и без обновления
    # человек раздвоится — часть операций останется под старым написанием.
    if old_name != p.name:
        busy = (await db.execute(
            select(OffLedgerPerson).where(
                OffLedgerPerson.company_id == cid,
                OffLedgerPerson.id != p.id,
                func.lower(OffLedgerPerson.name) == p.name.lower()))).scalar_one_or_none()
        if busy is not None:
            raise HTTPException(409, "Человек с таким именем уже есть в списке")
        await db.execute(
            update(OffLedgerCash)
            .where(OffLedgerCash.company_id == cid,
                   OffLedgerCash.person_name == old_name)
            .values(person_name=p.name, person_id=p.id)
        )
        # Обязательства держат имя такой же строкой: без этого человек раздваивается,
        # и в списке людей его видно дважды.
        await db.execute(
            update(OffLedgerCommitment)
            .where(OffLedgerCommitment.company_id == cid,
                   OffLedgerCommitment.person_name == old_name)
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
    p = await db.get(OffLedgerPerson, _uuid(person_id, "идентификатор человека"))
    if p is None or p.company_id != cid:
        raise HTTPException(404, "Человек не найден")
    used = (await db.execute(
        select(func.count()).select_from(OffLedgerCash)
        .where(OffLedgerCash.company_id == cid,
               func.lower(OffLedgerCash.person_name) == p.name.lower())
    )).scalar() or 0
    used += (await db.execute(
        select(func.count()).select_from(OffLedgerCommitment)
        .where(OffLedgerCommitment.company_id == cid,
               func.lower(OffLedgerCommitment.person_name) == p.name.lower())
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


# ── Регулярные обязательства ─────────────────────────────────────────────────
# Разовую договорённость закрывают один раз, регулярную — каждый период, и вопрос к ней
# другой: за какой период рассчитались, а какой пропустили. Доплата водителю каждый
# месяц, компенсация аренды мастеру, обед бригаде по пятницам, обучение раз в квартал.
#
# Форма исполнения не обязана быть денежной, поэтому сумма может отсутствовать, а
# «выполнено» отмечается фактом, а не платежом.

COMMITMENT_FORMS: dict[str, str] = {
    "money": "Выплата наличными",
    "service": "Работа или услуга",
    "goods": "Передача вещей",
    "other": "Прочее",
}
COMMITMENT_STATUSES: dict[str, str] = {
    "active": "Действует",
    "paused": "Приостановлено",
    "ended": "Прекращено",
}
# Сколько дней в периоде — для недели и года считается точно, для месяца и квартала
# шаг календарный (см. `_period_start`), а это число нужно лишь для оценки просрочки.
PERIOD_DAYS = {"week": 7, "month": 30, "quarter": 91, "halfyear": 182, "year": 365}


class CommitmentIn(BaseModel):
    """Регулярное обязательство. Периодичность по умолчанию — месяц."""

    personName: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=300)
    startedOn: str
    form: str = "money"
    amount: float | None = Field(default=None, ge=0)
    periodicity: str = "month"
    dueDay: int | None = None
    endsOn: str | None = None
    status: str = "active"
    confidence: str = "spoken"
    details: str | None = None
    note: str | None = None
    personKind: str = "individual"


class MarkIn(BaseModel):
    """Отметка за период: выполнено или сознательно пропущено."""

    periodStart: str
    doneOn: str | None = None
    outcome: str = "done"
    amount: float | None = Field(default=None, ge=0)
    cashId: str | None = None
    note: str | None = None


def _validate_commitment(body: CommitmentIn) -> None:
    if body.periodicity not in PERIODICITY:
        raise HTTPException(422, f"Неизвестная периодичность: {body.periodicity}")
    if body.form not in COMMITMENT_FORMS:
        raise HTTPException(422, f"Неизвестная форма: {body.form}")
    if body.status not in COMMITMENT_STATUSES:
        raise HTTPException(422, f"Неизвестный статус: {body.status}")
    if body.confidence not in CONFIDENCE:
        raise HTTPException(422, f"Неизвестное подтверждение: {body.confidence}")
    if body.endsOn and body.endsOn < body.startedOn:
        raise HTTPException(422, "Окончание раньше начала")
    if body.dueDay is not None and not (1 <= body.dueDay <= 31):
        raise HTTPException(422, "День исполнения — число от 1 до 31")


def _commitment_row(c: OffLedgerCommitment, marks: list[OffLedgerCommitmentMark],
                    today: date, paid: dict[date, float] | None = None) -> dict[str, Any]:
    """Обязательство вместе с расчётом периодов: что закрыто, что пропущено.

    Суммы за периоды приходят из журнала наличных (`paid`), а не из отметок: отметка
    отвечает за факт выполнения, деньги живут в журнале. Хранить сумму в отметке значило
    бы поддерживать производную величину при каждой правке операции.
    """
    paid = paid or {}
    by_period = {m.period_start: m for m in marks}
    periods = _periods(c, today)
    current = _period_start(today, c.periodicity) if periods else None

    # Первый период считается только если обязательство действовало в нём целиком:
    # начатое 31 января не должно немедленно получить весь январь в пропущенные вместе
    # с полной месячной суммой за один день.
    partial_first = periods[0] if periods and c.started_on != periods[0] else None

    # Текущий период — долг лишь с наступлением дня исполнения; пока срок не пришёл,
    # невыполненное это ожидание. День, которого в коротком месяце нет (31-е в апреле),
    # наступает в последний день месяца — иначе период не станет просроченным никогда.
    due_now = True
    if current and c.due_day and c.periodicity == "month":
        last_day = (_next_period(current, "month") - timedelta(days=1)).day
        due_now = today.day >= min(c.due_day, last_day)

    def is_missed(p: date) -> bool:
        if p in by_period or p == partial_first:
            return False
        # Оплаченный период не пропущен, даже если отметку не ставили руками.
        if paid.get(p):
            return False
        if p == current:
            # Идущий период долгом не считается: месячное обязательство, заведённое
            # сегодня, иначе объявляется просроченным в день заведения. Исключение —
            # назначенный день исполнения внутри месяца: он уже наступил.
            if c.status != "active":
                return False
            return bool(c.due_day) and c.periodicity == "month" and due_now
        # Приостановленное обязательство не копит долги ПОСЛЕ постановки на паузу:
        # раньше исключался только текущий период, и через месяц пауза начинала
        # выглядеть как забывчивость.
        if c.status != "active" and c.paused_on:
            return p < _period_start(c.paused_on, c.periodicity)
        return c.status == "active"

    missed = [p for p in periods if is_missed(p)]

    rows = [{
        "periodStart": p.isoformat(),
        "label": _period_label(p, c.periodicity),
        "outcome": (by_period[p].outcome if p in by_period
                    else "done" if paid.get(p)
                    else "partial" if p == partial_first
                    else "missed" if p in missed
                    else "open"),
        "doneOn": by_period[p].done_on.isoformat() if p in by_period else None,
        # Сумма периода: ручная отметка плюс выплаты журнала за этот же период.
        "amount": round((float(by_period[p].amount)
                         if p in by_period and by_period[p].amount is not None else 0.0)
                        + paid.get(p, 0.0), 2) or None,
        "paid": paid.get(p) or None,
        "note": by_period[p].note if p in by_period else None,
        "markId": str(by_period[p].id) if p in by_period else None,
        "isCurrent": p == current,
    } for p in periods]

    done = [r for r in rows if r["outcome"] == "done"]
    last = max((m.period_start for m in marks), default=None)
    total_paid = round(sum(r["amount"] or 0 for r in rows), 2)
    return {
        "id": str(c.id),
        "person": c.person_name,
        "personId": str(c.person_id) if c.person_id else None,
        "title": c.title, "details": c.details,
        "form": c.form, "formLabel": COMMITMENT_FORMS.get(c.form, c.form),
        "amount": float(c.amount) if c.amount is not None else None,
        "periodicity": c.periodicity,
        "periodicityLabel": PERIODICITY.get(c.periodicity, c.periodicity),
        "dueDay": c.due_day,
        "startedOn": c.started_on.isoformat(),
        "endsOn": c.ends_on.isoformat() if c.ends_on else None,
        "pausedOn": c.paused_on.isoformat() if c.paused_on else None,
        "status": c.status,
        "statusLabel": COMMITMENT_STATUSES.get(c.status, c.status),
        "confidence": c.confidence,
        "confidenceLabel": CONFIDENCE.get(c.confidence, c.confidence),
        "note": c.note,
        "periods": rows[-24:],
        "periodsTotal": len(periods),
        "doneCount": len(done),
        "skippedCount": sum(1 for m in marks if m.outcome == "skipped"),
        "missedCount": len(missed),
        "missedPeriods": [_period_label(p, c.periodicity) for p in missed[-6:]],
        # Сколько обязательство уже стоило. Ноль остаётся нулём: у неденежной формы
        # платежей нет по природе, и «нет данных» здесь означало бы другое.
        "paidTotal": total_paid if c.form == "money" else None,
        "lastPeriod": _period_label(last, c.periodicity) if last else None,
        # Во что обошлись пропуски — только для денежной формы с названной суммой.
        "missedAmount": round(len(missed) * float(c.amount), 2)
        if c.form == "money" and c.amount is not None and missed else None,
        # Следующего периода у прекращённого обязательства не бывает — как и у того,
        # чей срок окончания уже прошёл, даже если статус остался «действует».
        "nextPeriod": _period_label(_next_period(current, c.periodicity), c.periodicity)
        if current and c.status == "active"
        and (c.ends_on is None or _next_period(current, c.periodicity) <= c.ends_on)
        else None,
    }


async def _commitments(cid, db: AsyncSession, only_active: bool = False
                       ) -> list[dict[str, Any]]:
    sel = select(OffLedgerCommitment).where(OffLedgerCommitment.company_id == cid)
    if only_active:
        sel = sel.where(OffLedgerCommitment.status == "active")
    rows = list((await db.execute(sel.order_by(OffLedgerCommitment.person_name)))
                .scalars().all())
    marks = list((await db.execute(
        select(OffLedgerCommitmentMark)
        .where(OffLedgerCommitmentMark.company_id == cid)
    )).scalars().all())
    by_c: dict[uuid.UUID, list[OffLedgerCommitmentMark]] = {}
    for m in marks:
        by_c.setdefault(m.commitment_id, []).append(m)
    # Выплаты по всем обязательствам одним запросом: иначе на каждое обязательство
    # уходил бы свой поход в базу.
    cash = list((await db.execute(
        select(OffLedgerCash).where(OffLedgerCash.company_id == cid,
                                    OffLedgerCash.commitment_id.isnot(None),
                                    OffLedgerCash.direction == "out")
    )).scalars().all())
    paid_by_c: dict[uuid.UUID, dict[date, float]] = {}
    step = {c.id: c.periodicity for c in rows}
    for r in cash:
        per_ = step.get(r.commitment_id)
        if per_ is None:
            continue
        start = _period_start(r.commitment_period or r.happened_on, per_)
        d = paid_by_c.setdefault(r.commitment_id, {})
        d[start] = round(d.get(start, 0.0) + float(r.amount), 2)
    today = date.today()
    out = [_commitment_row(c, by_c.get(c.id, []), today, paid_by_c.get(c.id))
           for c in rows]
    # Впереди то, что пропущено: экран открывают ради этого.
    out.sort(key=lambda r: (-r["missedCount"], r["person"]))
    return out


@router.get("/commitments")
async def list_commitments(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Регулярные обязательства с историей периодов."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    rows = await _commitments(cid, db)
    active = [r for r in rows if r["status"] == "active"]
    return {
        "rows": rows,
        "dictionaries": {
            "periodicity": [{"key": k, "label": v} for k, v in PERIODICITY.items()],
            "forms": [{"key": k, "label": v} for k, v in COMMITMENT_FORMS.items()],
            "statuses": [{"key": k, "label": v} for k, v in COMMITMENT_STATUSES.items()],
            "confidence": [{"key": k, "label": v} for k, v in CONFIDENCE.items()],
        },
        "activeCount": len(active),
        "missedTotal": sum(r["missedCount"] for r in active),
        # Сколько денег в месяц компания обещала регулярно. Считается только по
        # денежной форме с названной суммой и приводится к месяцу: сравнивать недельную
        # доплату с годовой премией иначе нельзя.
        "monthlyMoney": round(sum(
            # 52/12 недель в месяце, а не 4: округление до четырёх занижало
            # недельные обязательства почти на восемь процентов.
            float(r["amount"]) * {"week": 52 / 12, "month": 1.0, "quarter": 1 / 3,
                                  "halfyear": 1 / 6, "year": 1 / 12}[r["periodicity"]]
            for r in active if r["form"] == "money" and r["amount"]), 2),
        "peopleCount": len({r["person"] for r in active}),
    }


@router.post("/commitments")
async def create_commitment(
    company_id: str,
    body: CommitmentIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    _validate_commitment(body)
    person = await _ensure_person(cid, body.personName, body.personKind,
                                  current_user, db)
    c = OffLedgerCommitment(
        company_id=cid, person_name=body.personName.strip(), person_id=person.id,
        title=body.title.strip(), details=body.details, form=body.form,
        amount=body.amount, periodicity=body.periodicity, due_day=body.dueDay,
        started_on=_day(body.startedOn) or date.today(), ends_on=_day(body.endsOn),
        status=body.status, confidence=body.confidence, note=body.note,
        created_by=current_user.id,
    )
    db.add(c)
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.commitment.create", target=str(c.id),
                    details={"person": c.person_name, "title": c.title,
                             "periodicity": c.periodicity})
    await db.commit()
    await db.refresh(c)
    return _commitment_row(c, [], date.today(), await _paid_by_period(cid, c, db))


@router.put("/commitments/{commitment_id}")
async def update_commitment(
    company_id: str,
    commitment_id: str,
    body: CommitmentIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    _validate_commitment(body)
    c = await db.get(OffLedgerCommitment, _uuid(commitment_id, "идентификатор обязательства"))
    if c is None or c.company_id != cid:
        raise HTTPException(404, "Обязательство не найдено")
    # Периодичность у обязательства с отметками не меняется: отметки привязаны к первым
    # дням своих периодов, и после смены шага они попадут мимо новых границ.
    if c.periodicity != body.periodicity:
        marks = (await db.execute(
            select(func.count()).select_from(OffLedgerCommitmentMark)
            .where(OffLedgerCommitmentMark.commitment_id == c.id))).scalar() or 0
        if marks:
            raise HTTPException(
                422, "Есть отметки за периоды — периодичность менять нельзя. "
                     "Прекратите это обязательство и заведите новое")
    c.person_name = body.personName.strip()
    c.person_id = (await _ensure_person(cid, body.personName, body.personKind,
                                        current_user, db)).id
    c.title, c.details = body.title.strip(), body.details
    c.form, c.amount = body.form, body.amount
    c.periodicity, c.due_day = body.periodicity, body.dueDay
    c.started_on = _day(body.startedOn) or c.started_on
    c.ends_on = _day(body.endsOn)
    # Дата приостановки нужна расчёту пропусков: без неё пауза защищает только
    # текущий период, и через месяц выглядит как забывчивость.
    if body.status != "active" and c.status == "active":
        c.paused_on = date.today()
    elif body.status == "active":
        c.paused_on = None
    c.status, c.confidence, c.note = body.status, body.confidence, body.note
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.commitment.update", target=str(c.id),
                    details={"title": c.title, "status": c.status})
    await db.commit()
    await db.refresh(c)
    marks = list((await db.execute(
        select(OffLedgerCommitmentMark)
        .where(OffLedgerCommitmentMark.commitment_id == c.id))).scalars().all())
    return _commitment_row(c, marks, date.today(),
                           await _paid_by_period(cid, c, db))


@router.delete("/commitments/{commitment_id}")
async def delete_commitment(
    company_id: str,
    commitment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Удаление — для заведённых по ошибке. Отработавшее прекращают статусом."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    c = await db.get(OffLedgerCommitment, _uuid(commitment_id, "идентификатор обязательства"))
    if c is None or c.company_id != cid:
        raise HTTPException(404, "Обязательство не найдено")
    title = c.title
    await db.delete(c)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.commitment.delete", target=commitment_id,
                    details={"title": title})
    await db.commit()
    return {"deleted": True}


@router.post("/commitments/{commitment_id}/marks")
async def mark_commitment(
    company_id: str,
    commitment_id: str,
    body: MarkIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Отметить период выполненным или сознательно пропущенным."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    c = await db.get(OffLedgerCommitment, _uuid(commitment_id, "идентификатор обязательства"))
    if c is None or c.company_id != cid:
        raise HTTPException(404, "Обязательство не найдено")
    if body.outcome not in ("done", "skipped"):
        raise HTTPException(422, "Отметка бывает «выполнено» или «пропущено»")
    start = _day(body.periodStart)
    if start is None:
        raise HTTPException(422, "Не указан период")
    # Приводим к границе периода: с экрана приходит первый день, но руками могли
    # передать любую дату внутри него.
    start = _period_start(start, c.periodicity)
    # Период обязан принадлежать обязательству: отметка за месяц до его начала или за
    # будущий период попадала в «выполнено», не закрывая ни одного реального периода.
    if start < _period_start(c.started_on, c.periodicity):
        raise HTTPException(422, "Период раньше начала обязательства")
    if c.ends_on and start > c.ends_on:
        raise HTTPException(422, "Период позже окончания обязательства")
    if start > _period_start(date.today(), c.periodicity):
        raise HTTPException(422, "Период ещё не наступил")
    exists = (await db.execute(
        select(OffLedgerCommitmentMark).where(
            OffLedgerCommitmentMark.commitment_id == c.id,
            OffLedgerCommitmentMark.period_start == start))).scalar_one_or_none()
    if exists is not None:
        # Повторная отметка не создаёт вторую запись, а исправляет первую: иначе один
        # месяц выглядел бы выполненным дважды.
        exists.outcome = body.outcome
        exists.done_on = _day(body.doneOn) or date.today()
        exists.amount = body.amount
        exists.note = body.note
        exists.cash_id = _uuid(body.cashId, "операция")
        mark = exists
    else:
        mark = OffLedgerCommitmentMark(
            company_id=cid, commitment_id=c.id, period_start=start,
            done_on=_day(body.doneOn) or date.today(), outcome=body.outcome,
            amount=body.amount,
            cash_id=_uuid(body.cashId, "операция"),
            note=body.note, created_by=current_user.id,
        )
        db.add(mark)
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.commitment.mark", target=str(c.id),
                    details={"period": start.isoformat(), "outcome": body.outcome})
    await db.commit()
    marks = list((await db.execute(
        select(OffLedgerCommitmentMark)
        .where(OffLedgerCommitmentMark.commitment_id == c.id))).scalars().all())
    return _commitment_row(c, marks, date.today(),
                           await _paid_by_period(cid, c, db))


@router.delete("/commitments/{commitment_id}/marks/{mark_id}")
async def unmark_commitment(
    company_id: str,
    commitment_id: str,
    mark_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Снять отметку: период снова считается незакрытым."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    m = await db.get(OffLedgerCommitmentMark, _uuid(mark_id, "идентификатор отметки"))
    if m is None or m.company_id != cid or str(m.commitment_id) != commitment_id:
        raise HTTPException(404, "Отметка не найдена")
    await db.delete(m)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.commitment.unmark", target=commitment_id,
                    details={"period": m.period_start.isoformat()})
    await db.commit()
    return {"deleted": True}


async def _touch_commitment_mark(cid, c: OffLedgerCash, user: User,
                                 db: AsyncSession) -> None:
    """Отметить период регулярного обязательства выполненным по факту выплаты.

    Суммы отметка НЕ носит: сколько за период отдали, считается из самих выплат
    (`_paid_by_period`). Хранить производную величину значило бы поддерживать её при
    каждой правке и удалении операции — ровно на этом продукт трижды ошибался: сумма
    наращивалась при повторном сохранении, правка заводила вторую отметку на соседнем
    периоде, а удаление выплаты оставляло период оплаченным.

    За какой период платят, решает человек (`commitment_period`): доплату за август
    нередко выдают в сентябре. Если период не назван, берётся тот, в который попадает
    дата операции.
    """
    com = await db.get(OffLedgerCommitment, c.commitment_id)
    if com is None or com.company_id != cid:
        return
    # Обязательство — то, что должны МЫ, и закрывает его расход. Приход, привязанный к
    # обязательству (например, возврат излишне выданного), период не закрывает.
    if c.direction != "out":
        return
    start = _period_start(c.commitment_period or c.happened_on, com.periodicity)
    mark = (await db.execute(
        select(OffLedgerCommitmentMark).where(
            OffLedgerCommitmentMark.commitment_id == com.id,
            OffLedgerCommitmentMark.period_start == start))).scalar_one_or_none()
    if mark is None:
        db.add(OffLedgerCommitmentMark(
            company_id=cid, commitment_id=com.id, period_start=start,
            done_on=c.happened_on, outcome="done", cash_id=c.id, created_by=user.id,
            note="отмечено выплатой из журнала наличных",
        ))
    elif mark.outcome != "done":
        # Период считали пропущенным, а по нему заплатили: факт сильнее прежней отметки.
        mark.outcome = "done"
        mark.done_on = c.happened_on
    await db.flush()
    # Отметка, оставшаяся без выплат и без ручного следа, снимается: иначе перенос
    # операции на другой период оставил бы старый зелёным.
    await _drop_orphan_marks(cid, com, db)


async def _drop_orphan_marks(cid, com: OffLedgerCommitment, db: AsyncSession) -> None:
    """Снять отметки, которые держались только на выплатах, а выплат больше нет."""
    marks = list((await db.execute(
        select(OffLedgerCommitmentMark).where(
            OffLedgerCommitmentMark.commitment_id == com.id))).scalars().all())
    if not marks:
        return
    paid = await _paid_by_period(cid, com, db)
    for m in marks:
        # Ручную отметку не трогаем: у неё нет признака «поставлена журналом».
        if m.cash_id is None and m.note != "отмечено выплатой из журнала наличных":
            continue
        if not paid.get(m.period_start):
            await db.delete(m)
    await db.flush()


async def _paid_by_period(cid, com: OffLedgerCommitment,
                          db: AsyncSession) -> dict[date, float]:
    """Сколько денег ушло по обязательству за каждый период.

    Считается из журнала наличных, а не из отметок: журнал — источник, отметка — факт
    выполнения. Две выплаты за один период складываются сами, удаление любой из них
    само уменьшает сумму.
    """
    rows = list((await db.execute(
        select(OffLedgerCash).where(
            OffLedgerCash.company_id == cid,
            OffLedgerCash.commitment_id == com.id,
            # Обязательство исполняет РАСХОД. Приход по нему (вернули излишне
            # выданное) период не закрывает и в потраченное не идёт.
            OffLedgerCash.direction == "out"))).scalars().all())
    out: dict[date, float] = {}
    for r in rows:
        start = _period_start(r.commitment_period or r.happened_on, com.periodicity)
        out[start] = round(out.get(start, 0.0) + float(r.amount), 2)
    return out


# ── Настройки продукта ───────────────────────────────────────────────────────

class SettingsIn(BaseModel):
    allowExtraPay: bool = False
    advanceDays: int = Field(default=30, ge=1, le=365)
    cashLimit: float = Field(default=100000, ge=0)
    loanWrittenFrom: float = Field(default=10000, ge=0)
    loanInterestFrom: float = Field(default=100000, ge=0)
    limitationYears: int = Field(default=3, ge=1, le=10)
    showDisclaimer: bool = True


# Оговорка о статусе данных. Две работы сразу: не даёт принять цифры Периметра за
# учётные и снижает доказательную самостоятельность записи — это заметка руководителя,
# а не признание компании.
DISCLAIMER = ("Оперативная запись руководителя. Не является документом бухгалтерского "
              "учёта и не порождает обязательств.")


async def _settings(cid, db: AsyncSession) -> OffLedgerSettings:
    """Настройки компании; при первом обращении заводятся со значениями по умолчанию."""
    st = await db.get(OffLedgerSettings, cid)
    if st is None:
        st = OffLedgerSettings(company_id=cid)
        db.add(st)
        await db.flush()
    return st


def _settings_row(st: OffLedgerSettings) -> dict[str, Any]:
    return {
        "allowExtraPay": bool(st.allow_extra_pay),
        "advanceDays": st.advance_days,
        "cashLimit": float(st.cash_limit),
        "loanWrittenFrom": float(st.loan_written_from),
        "loanInterestFrom": float(st.loan_interest_from),
        "limitationYears": st.limitation_years,
        "showDisclaimer": bool(st.show_disclaimer),
        "disclaimer": DISCLAIMER,
        "updatedAt": st.updated_at.isoformat() if st.updated_at else None,
    }


@router.get("/settings")
async def get_settings(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    st = await _settings(cid, db)
    row = _settings_row(st)
    await db.commit()
    return row


@router.put("/settings")
async def put_settings(
    company_id: str,
    body: SettingsIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Изменить настройки. Включение спорной возможности остаётся в журнале действий."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    st = await _settings(cid, db)
    was_extra = bool(st.allow_extra_pay)
    st.allow_extra_pay = body.allowExtraPay
    st.advance_days = body.advanceDays
    st.cash_limit = body.cashLimit
    st.loan_written_from = body.loanWrittenFrom
    st.loan_interest_from = body.loanInterestFrom
    st.limitation_years = body.limitationYears
    st.show_disclaimer = body.showDisclaimer
    st.updated_by = current_user.id
    if was_extra != body.allowExtraPay:
        # Включение и выключение этой возможности фиксируется отдельным событием: это
        # решение компании, и через год должно быть видно, кто его принял.
        await log_audit(db, actor=current_user, company_id=cid,
                        action="perimeter.settings.extra_pay",
                        target=str(cid), details={"enabled": body.allowExtraPay})
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.settings.update", target=str(cid),
                    details={"advanceDays": body.advanceDays})
    row = _settings_row(st)
    await db.commit()
    return row


async def _check_gated(cid, kind: str, db: AsyncSession) -> None:
    """Вид, закрытый настройкой, нельзя записать в обход интерфейса."""
    flag = GATED_KINDS.get(kind)
    if flag and not getattr(await _settings(cid, db), flag):
        raise HTTPException(
            422, f"Вид «{CASH_KINDS[kind]}» выключен в настройках «Периметра»")


def _limitation(c: OffLedgerCash, years: int) -> dict[str, Any]:
    """Когда сгорает право требования по выданному.

    Отсчёт идёт от последнего действия должника, из которого видно, что он долг
    признаёт: частичной оплаты, подписанного акта сверки, просьбы об отсрочке. Такое
    действие прерывает срок, и он течёт заново — считать от даты выдачи значило бы
    объявлять сгоревшим живой долг.
    """
    if c.kind not in OPEN_KINDS or c.direction != "out":
        return {}
    base = c.acknowledged_on or c.due_on or c.happened_on
    expires = date(base.year + years, base.month, base.day) \
        if not (base.month == 2 and base.day == 29) else date(base.year + years, 3, 1)
    left = (expires - date.today()).days
    return {
        "limitationFrom": base.isoformat(),
        "limitationExpiresOn": expires.isoformat(),
        "limitationDaysLeft": left,
        "limitationBase": ("признание долга" if c.acknowledged_on
                           else "срок возврата" if c.due_on else "дата выдачи"),
    }


# Возрастные корзины открытых сумм: чем дольше висит невозвращённое, тем выше риск,
# что налоговая признает его доходом человека со всеми последствиями.
AGE_BUCKETS = (("d30", "до 30 дней", 0, 30), ("d60", "31–60 дней", 31, 60),
               ("d90", "61–90 дней", 61, 90), ("older", "больше 90 дней", 91, 10 ** 6))


@router.get("/cash/aging")
async def cash_aging(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Возраст незакрытых выдач: займы и подотчёт по корзинам и по людям."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    st = await _settings(cid, db)
    rows = list((await db.execute(
        select(OffLedgerCash).where(OffLedgerCash.company_id == cid,
                                    OffLedgerCash.kind.in_(OPEN_KINDS))
    )).scalars().all())
    repaid = await _repaid_map(cid, db)
    today = date.today()

    open_rows = []
    for c in rows:
        rest = round(float(c.amount) - repaid.get(c.id, 0.0), 2)
        if rest <= 0.01:
            continue
        age = (today - c.happened_on).days
        bucket = next(k for k, _l, lo, hi in AGE_BUCKETS if lo <= age <= hi)
        row = _cash_row(c, repaid.get(c.id, 0.0))
        row.update(age=age, bucket=bucket, **_limitation(c, st.limitation_years))
        # Подотчёт, не закрытый в установленный компанией срок: именно его налоговая
        # переквалифицирует в доход человека.
        row["overdueReport"] = bool(c.kind == "advance" and age > st.advance_days)
        open_rows.append(row)

    buckets = [{
        "key": k, "label": label,
        "count": sum(1 for r in open_rows if r["bucket"] == k),
        "amount": round(sum(r["rest"] for r in open_rows if r["bucket"] == k), 2),
    } for k, label, _lo, _hi in AGE_BUCKETS]

    by_purse = [{
        "key": k, "label": v,
        "amount": round(sum(r["rest"] for r in open_rows if r["purse"] == k), 2),
    } for k, v in CASH_PURSE.items()]

    return {
        "rows": sorted(open_rows, key=lambda r: -r["age"]),
        "buckets": buckets,
        "byPurse": by_purse,
        "total": round(sum(r["rest"] for r in open_rows), 2),
        "overdueReports": [r for r in open_rows if r["overdueReport"]],
        "advanceDays": st.advance_days,
        # Право требования, которое сгорит в ближайший квартал: сгоревшее взыскать
        # нельзя, а прервать срок можно актом сверки — пока он не сгорел.
        "expiring": sorted(
            [r for r in open_rows
             if r.get("limitationDaysLeft") is not None
             and r["limitationDaysLeft"] <= 90],
            key=lambda r: r["limitationDaysLeft"]),
        "disclaimer": DISCLAIMER if st.show_disclaimer else None,
    }


@router.post("/cash/check")
async def cash_check(
    company_id: str,
    body: CashIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Что стоит знать до сохранения операции.

    Не запреты, а предупреждения: продукт не решает за компанию, но и не молчит о том,
    что превышен порог, после которого закон требует бумагу.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    st = await _settings(cid, db)
    limits = (float(st.loan_written_from), float(st.loan_interest_from),
              float(st.cash_limit), st.advance_days)
    await db.commit()
    written_from, interest_from, cash_limit, advance_days = limits
    warn: list[dict[str, str]] = []
    amount = body.amount or 0

    if body.kind == "loan" and amount > written_from:
        warn.append({
            "key": "loan_written",
            "text": f"Заём свыше {int(written_from):,} руб. между гражданами "
                    "требует письменной формы. Без расписки взыскание опирается только "
                    "на письменные доказательства: свидетели в таком споре не "
                    "принимаются.".replace(",", " "),
        })
    if body.kind == "loan" and amount > interest_from:
        warn.append({
            "key": "loan_interest",
            "text": f"Заём свыше {int(interest_from):,} руб. по умолчанию "
                    "считается ПРОЦЕНТНЫМ по ключевой ставке. Если договорились без "
                    "процентов, это нужно прямо написать в расписке."
                    .replace(",", " "),
        })
    if body.personKind in ("other",) and amount > cash_limit:
        warn.append({
            "key": "cash_limit",
            "text": f"Предел наличных расчётов между организациями и ИП по одному "
                    f"договору — {int(cash_limit):,} руб.".replace(",", " "),
        })
    if body.kind == "advance" and not body.dueOn:
        warn.append({
            "key": "advance_due",
            "text": f"Срок отчёта не указан. По умолчанию в настройках — "
                    f"{advance_days} дн.; невозвращённое и неотчитанное налоговая "
                    "признаёт доходом человека с НДФЛ и взносами.",
        })
    if body.kind == "extra_pay":
        warn.append({
            "key": "extra_pay",
            "text": "Выплата помимо расчётного листка не уменьшает обязательств "
                    "компании перед работником и бюджетом. Запись нужна, чтобы знать "
                    "реальные расчёты, — она не заменяет оформление и не защищает от "
                    "последствий.",
        })
    if body.proof == "none" and amount >= 50000:
        warn.append({
            "key": "no_proof",
            "text": "Крупный расчёт без единой бумаги: доказательства не будет ни у "
                    "одной стороны.",
        })
    return {"warnings": warn}


class OffsetIn(BaseModel):
    """Взаимозачёт встречных долгов одного человека."""

    personName: str = Field(min_length=1, max_length=300)
    amount: float = Field(gt=0)
    happenedOn: str
    note: str | None = Field(default=None, max_length=2000)


@router.post("/cash/offset")
async def cash_offset(
    company_id: str,
    body: OffsetIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Зачесть встречные долги: он должен нам и мы должны ему.

    Гасятся обе стороны разом, деньги при этом не движутся. Правило заимствовано из
    практики раздела расходов между людьми и намеренно сужено: сворачиваем ТОЛЬКО
    внутри одной пары. Транзитивное упрощение («Иванов теперь должен Петрову») создало
    бы обязательство, которого не было, — перевод долга требует согласия кредитора.

    Ограничение на сумму: зачесть можно не больше меньшей из встречных сторон, иначе
    у одного из долгов остаток уйдёт в минус.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    people = await cash_people(company_id, db, current_user)
    key = body.personName.strip().lower()
    row = next((r for r in people["rows"] if r["person"].strip().lower() == key), None)
    if row is None:
        raise HTTPException(404, "С этим человеком расчётов нет")
    limit = min(row["owed"], row["owes"])
    if limit <= 0.01:
        raise HTTPException(422, "Встречных долгов нет: зачитывать нечего")
    if body.amount > limit + 0.01:
        raise HTTPException(422, f"Зачесть можно не больше {round(limit, 2)} руб. — "
                                 "это меньшая из встречных сторон")

    # Зачёт закрывает выдачи по очереди, начиная со старых: так же, как это делает
    # любой разумный человек, — сперва то, что висит дольше.
    repaid = await _repaid_map(cid, db)
    opened = sorted(
        [c for c in (await db.execute(
            select(OffLedgerCash).where(
                OffLedgerCash.company_id == cid,
                OffLedgerCash.kind.in_(OPEN_KINDS),
                func.lower(OffLedgerCash.person_name) == key))).scalars().all()
         if float(c.amount) - repaid.get(c.id, 0.0) > 0.01],
        key=lambda c: c.happened_on)

    left = body.amount
    made = []
    for side in ("out", "in"):
        rest_side = body.amount
        for c in [x for x in opened if x.direction == side]:
            if rest_side <= 0.01:
                break
            free = round(float(c.amount) - repaid.get(c.id, 0.0), 2)
            take = min(free, rest_side)
            row_ = OffLedgerCash(
                company_id=cid, direction="in" if side == "out" else "out",
                kind="offset", happened_on=_day(body.happenedOn) or date.today(),
                amount=take, person_name=body.personName.strip(),
                person_id=(await _ensure_person(cid, body.personName, "individual",
                                                current_user, db)).id,
                purpose="взаимозачёт встречных долгов", proof="none", purse="owner",
                parent_id=c.id, note=body.note, created_by=current_user.id,
            )
            db.add(row_)
            made.append(row_)
            rest_side = round(rest_side - take, 2)
        left = rest_side
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.cash.offset", target=str(cid),
                    details={"person": body.personName, "amount": body.amount})
    await db.commit()
    return {"offset": body.amount, "rows": len(made), "left": left}


@router.post("/export-log")
async def export_log(
    company_id: str,
    what: str,
    rows: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Отметить, что данные периметра выгружены.

    Выгрузка — самая чувствительная операция продукта: файл живёт дальше сам по себе.
    Экспорт без следа делает бессмысленным весь остальной контроль доступа, поэтому
    фронт сообщает о каждой выгрузке, а журнал действий хранит, кто и что забрал.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.export", target=what,
                    details={"rows": rows})
    await db.commit()
    return {"logged": True}


# ── Разбор недели ────────────────────────────────────────────────────────────
# Продукт держится не на возможностях, а на регулярности: записи заводят неделю, потом
# бросают, и реестру перестают верить. Ежедневная дисциплина здесь не нужна — событий
# мало; ежемесячная приходит поздно. Рабочий ритм — короткий еженедельный просмотр.
#
# Экран отвечает на три вопроса и ни на один сверх: что появилось за неделю, что требует
# решения сейчас, и всё ли просмотрено. Никаких стриков и баллов: соревнование за объём
# записей о неоформленных выплатах — плохая мысль и как стимул, и как факт.

class ReviewIn(BaseModel):
    weekStart: str
    note: str | None = Field(default=None, max_length=4000)


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


@router.get("/review")
async def week_review(
    company_id: str,
    week: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Что разбирать за неделю."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    st = await _settings(cid, db)
    limitation_years, advance_days = st.limitation_years, st.advance_days
    await db.commit()

    start = _week_start(_day(week) or date.today())
    end = start + timedelta(days=6)
    today = date.today()

    # ── Что появилось за неделю
    new_cash = list((await db.execute(
        select(OffLedgerCash).where(
            OffLedgerCash.company_id == cid,
            OffLedgerCash.happened_on >= start,
            OffLedgerCash.happened_on <= end).order_by(OffLedgerCash.happened_on)
    )).scalars().all())
    repaid = await _repaid_map(cid, db)
    new_records = list((await db.execute(
        select(OffLedgerRecord).where(
            OffLedgerRecord.company_id == cid,
            OffLedgerRecord.created_at >= datetime.combine(
                start, datetime.min.time(), tzinfo=timezone.utc),
            OffLedgerRecord.created_at < datetime.combine(
                end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    )).scalars().all())

    # ── Что требует решения. Список намеренно короткий: длинный не разбирают.
    todo: list[dict[str, Any]] = []

    records = list((await db.execute(
        select(OffLedgerRecord).where(OffLedgerRecord.company_id == cid,
                                      OffLedgerRecord.status == "active")
    )).scalars().all())
    overdue_records = [r for r in records if r.due_on and r.due_on < today]
    if overdue_records:
        todo.append({
            "key": "records_overdue", "title": "Договорённости с прошедшим сроком",
            "count": len(overdue_records),
            "hint": "Либо выполнено и надо закрыть запись, либо разговор откладывать нельзя",
            "mode": "per_records", "sub": "pr_registry",
            "items": [{"id": str(r.id), "text": f"{r.counterparty_name or '—'}: {r.title}",
                       "note": r.due_on.isoformat()} for r in overdue_records[:8]],
        })

    # Записанное со слов и живущее дольше квартала: либо подтвердить перепиской, либо
    # оформить. Со временем такая запись стоит ровно столько, сколько чужая память.
    old_spoken = [r for r in records
                  if r.confidence == "spoken" and r.created_at
                  and (today - r.created_at.date()).days > 90]
    if old_spoken:
        todo.append({
            "key": "still_spoken", "title": "Держится только на словах больше трёх месяцев",
            "count": len(old_spoken),
            "hint": "Подтвердить перепиской или оформить: память сторон расходится быстрее, чем кажется",
            "mode": "per_records", "sub": "pr_registry",
            "items": [{"id": str(r.id), "text": f"{r.counterparty_name or '—'}: {r.title}",
                       "note": r.created_at.date().isoformat()} for r in old_spoken[:8]],
        })

    coms = await _commitments(cid, db, only_active=True)
    missed = [c for c in coms if c["missedCount"]]
    if missed:
        todo.append({
            "key": "commitments_missed", "title": "Регулярные обязательства с пропусками",
            "count": sum(c["missedCount"] for c in missed),
            "hint": "Выполнить или отметить пропуск: неотмеченный период неотличим от забытого",
            "mode": "per_records", "sub": "pr_regular",
            "items": [{"id": c["id"], "text": f'{c["person"]}: {c["title"]}',
                       "note": ", ".join(c["missedPeriods"][-3:])} for c in missed[:8]],
        })

    opened = [c for c in (await db.execute(
        select(OffLedgerCash).where(OffLedgerCash.company_id == cid,
                                    OffLedgerCash.kind.in_(OPEN_KINDS))
    )).scalars().all() if float(c.amount) - repaid.get(c.id, 0.0) > 0.01]

    late_advances = [c for c in opened
                     if c.kind == "advance" and (today - c.happened_on).days > advance_days]
    if late_advances:
        todo.append({
            "key": "advances_late", "title": "Подотчёт не закрыт в срок",
            "count": len(late_advances),
            "hint": f"Срок отчёта — {advance_days} дн. Невозвращённое и неотчитанное "
                    "налоговая признаёт доходом человека",
            "mode": "per_cash", "sub": "pr_cash_aging",
            "items": [{"id": str(c.id),
                       "text": f"{c.person_name}: {round(float(c.amount) - repaid.get(c.id, 0.0), 2)} руб.",
                       "note": f"{(today - c.happened_on).days} дн."}
                      for c in late_advances[:8]],
        })

    expiring = []
    for c in opened:
        lim = _limitation(c, limitation_years)
        if lim and 0 <= lim["limitationDaysLeft"] <= 90:
            expiring.append((c, lim))
    if expiring:
        todo.append({
            "key": "limitation", "title": "Право требования скоро сгорит",
            "count": len(expiring),
            "hint": "Прервать срок можно актом сверки или частичной оплатой — пока он не истёк",
            "mode": "per_cash", "sub": "pr_cash_aging",
            "items": [{"id": str(c.id), "text": f"{c.person_name}: {float(c.amount)} руб.",
                       "note": lim["limitationExpiresOn"]} for c, lim in expiring[:8]],
        })

    papers = await cash_papers(company_id, db, current_user)
    if papers["waiting"]:
        todo.append({
            "key": "papers", "title": "Ждёт оформления в бухгалтерии",
            "count": len(papers["waiting"]),
            "hint": "Подотчёт, премии и компенсации учёт принимает документами",
            "mode": "per_cash", "sub": "pr_cash_papers",
            "items": [{"id": r["id"], "text": f'{r["person"]}: {r["amount"]} руб.',
                       "note": r["kindLabel"]} for r in papers["waiting"][:8]],
        })

    no_proof = [c for c in new_cash if c.proof == "none" and float(c.amount) >= 50000]
    if no_proof:
        todo.append({
            "key": "no_proof", "title": "Крупные расчёты недели без подтверждения",
            "count": len(no_proof),
            "hint": "Пока свежо — взять расписку или сохранить переписку",
            "mode": "per_cash", "sub": "pr_cash",
            "items": [{"id": str(c.id), "text": f"{c.person_name}: {float(c.amount)} руб.",
                       "note": c.happened_on.isoformat()} for c in no_proof[:8]],
        })

    review = (await db.execute(
        select(OffLedgerReview).where(OffLedgerReview.company_id == cid,
                                      OffLedgerReview.week_start == start)
    )).scalar_one_or_none()

    money_out = round(sum(float(c.amount) for c in new_cash
                          if c.direction == "out" and c.kind not in ("report", "offset")), 2)
    return {
        "weekStart": start.isoformat(),
        "weekEnd": end.isoformat(),
        "isCurrent": start == _week_start(today),
        "added": {
            "cash": len(new_cash),
            "cashOut": money_out,
            "records": len(new_records),
            "rows": [{
                "id": str(c.id), "date": c.happened_on.isoformat(),
                "person": c.person_name, "kind": CASH_KINDS.get(c.kind, c.kind),
                "amount": float(c.amount), "direction": c.direction,
                "proof": CASH_PROOF.get(c.proof, c.proof),
            } for c in new_cash],
            "recordRows": [{
                "id": str(r.id), "title": r.title,
                "counterparty": r.counterparty_name,
                "confidence": CONFIDENCE.get(r.confidence, r.confidence),
            } for r in new_records],
        },
        "todo": todo,
        "todoTotal": sum(t["count"] for t in todo),
        "reviewed": review is not None,
        "reviewedAt": review.reviewed_at.isoformat() if review else None,
        "reviewNote": review.note if review else None,
        "snapshot": review.snapshot if review else None,
    }


@router.post("/review")
async def mark_review(
    company_id: str,
    body: ReviewIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Отметить неделю разобранной.

    В отметке сохраняется снимок счётчиков: через год «разобрали пустую неделю» и
    «разобрали неделю с семью просрочками» иначе не различить.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    start = _week_start(_day(body.weekStart) or date.today())
    data = await week_review(company_id, body.weekStart, db, current_user)
    snapshot = {
        "added": {k: v for k, v in data["added"].items() if not isinstance(v, list)},
        "todo": [{"key": t["key"], "title": t["title"], "count": t["count"]}
                 for t in data["todo"]],
        "todoTotal": data["todoTotal"],
    }
    review = (await db.execute(
        select(OffLedgerReview).where(OffLedgerReview.company_id == cid,
                                      OffLedgerReview.week_start == start)
    )).scalar_one_or_none()
    if review is None:
        review = OffLedgerReview(company_id=cid, week_start=start)
        db.add(review)
    review.reviewed_by = current_user.id
    review.reviewed_at = datetime.now(timezone.utc)
    review.snapshot = snapshot
    review.note = body.note
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.review", target=start.isoformat(),
                    details={"todo": snapshot["todoTotal"]})
    await db.commit()
    return {"weekStart": start.isoformat(), "reviewed": True}


@router.get("/reviews")
async def review_history(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """История разборов: чем и подтверждается регулярность контроля."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    rows = list((await db.execute(
        select(OffLedgerReview).where(OffLedgerReview.company_id == cid)
        .order_by(OffLedgerReview.week_start.desc()).limit(52)
    )).scalars().all())
    names = {}
    ids = {r.reviewed_by for r in rows if r.reviewed_by}
    if ids:
        names = {u[0]: u[1] for u in (await db.execute(
            select(User.id, User.name).where(User.id.in_(ids)))).all()}
    today_week = _week_start(date.today())
    # Сколько недель подряд разбор не пропускали — но без счётчиков достижений на
    # экране: это справка о регулярности, а не соревнование.
    weeks = {r.week_start for r in rows}
    streak, cur = 0, today_week - timedelta(days=7)
    while cur in weeks:
        streak += 1
        cur -= timedelta(days=7)
    return {
        "rows": [{
            "weekStart": r.week_start.isoformat(),
            "reviewedAt": r.reviewed_at.isoformat() if r.reviewed_at else None,
            "by": names.get(r.reviewed_by),
            "note": r.note,
            "todoTotal": (r.snapshot or {}).get("todoTotal"),
            "added": (r.snapshot or {}).get("added"),
        } for r in rows],
        "weeksInRow": streak,
    }


# ── Напоминания ──────────────────────────────────────────────────────────────
# Для просроченной устной договорённости важнее не сумма, а то, сколько раз о ней
# напоминали и что отвечали. Фоновая рассылка этого не даёт: она не знает, дошло ли
# сообщение и что сказали в ответ. Поэтому напоминание — запись человека о состоявшемся
# разговоре, а частичная оплата после него ещё и прерывает срок исковой давности.

class ReminderIn(BaseModel):
    personName: str = Field(min_length=1, max_length=300)
    happenedOn: str
    channel: str = "talk"
    outcome: str = "promised"
    promisedOn: str | None = None
    note: str | None = Field(default=None, max_length=4000)
    cashId: str | None = None
    recordId: str | None = None
    commitmentId: str | None = None


def _reminder_row(r: OffLedgerReminder) -> dict[str, Any]:
    return {
        "id": str(r.id), "person": r.person_name,
        "happenedOn": r.happened_on.isoformat(),
        "channel": r.channel,
        "channelLabel": REMINDER_CHANNELS.get(r.channel, r.channel),
        "outcome": r.outcome,
        "outcomeLabel": REMINDER_OUTCOMES.get(r.outcome, r.outcome),
        "promisedOn": r.promised_on.isoformat() if r.promised_on else None,
        # Обещал и срок прошёл: обещание, данное дважды, стоит дешевле первого.
        "promiseBroken": bool(r.outcome == "promised" and r.promised_on
                              and r.promised_on < date.today()),
        "note": r.note,
        "cashId": str(r.cash_id) if r.cash_id else None,
        "recordId": str(r.record_id) if r.record_id else None,
        "commitmentId": str(r.commitment_id) if r.commitment_id else None,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/reminders")
async def list_reminders(
    company_id: str,
    person: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """История напоминаний: кому, как и с каким результатом."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    sel = select(OffLedgerReminder).where(OffLedgerReminder.company_id == cid)
    if person:
        sel = sel.where(func.lower(OffLedgerReminder.person_name) == person.strip().lower())
    rows = list((await db.execute(
        sel.order_by(OffLedgerReminder.happened_on.desc()).limit(500))).scalars().all())
    items = [_reminder_row(r) for r in rows]
    return {
        "rows": items,
        "count": len(items),
        "channels": [{"key": k, "label": v} for k, v in REMINDER_CHANNELS.items()],
        "outcomes": [{"key": k, "label": v} for k, v in REMINDER_OUTCOMES.items()],
        # Обещания, срок которых прошёл: разговор пора повторить, но уже иначе.
        "broken": [r for r in items if r["promiseBroken"]],
    }


@router.post("/reminders")
async def create_reminder(
    company_id: str,
    body: ReminderIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    if body.channel not in REMINDER_CHANNELS:
        raise HTTPException(422, f"Неизвестный канал: {body.channel}")
    if body.outcome not in REMINDER_OUTCOMES:
        raise HTTPException(422, f"Неизвестный результат: {body.outcome}")
    r = OffLedgerReminder(
        company_id=cid, person_name=body.personName.strip(),
        happened_on=_day(body.happenedOn) or date.today(),
        channel=body.channel, outcome=body.outcome,
        promised_on=_day(body.promisedOn), note=body.note,
        cash_id=_uuid(body.cashId, "операция"),
        record_id=_uuid(body.recordId, "договорённость"),
        commitment_id=_uuid(body.commitmentId, "обязательство"),
        created_by=current_user.id,
    )
    db.add(r)
    await db.flush()
    # Разговор, в котором человек признал долг, прерывает срок исковой давности —
    # проставляем признание у самой выдачи, чтобы срок пересчитался.
    if r.cash_id and body.outcome in ("promised", "paid"):
        c = await db.get(OffLedgerCash, r.cash_id)
        if c is not None and c.company_id == cid and (
                c.acknowledged_on is None or c.acknowledged_on < r.happened_on):
            c.acknowledged_on = r.happened_on
            c.acknowledged_by = f"разговор: {REMINDER_OUTCOMES[body.outcome].lower()}"
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.reminder", target=str(r.id),
                    details={"person": r.person_name, "outcome": r.outcome})
    await db.commit()
    await db.refresh(r)
    return _reminder_row(r)


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(
    company_id: str,
    reminder_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    r = await db.get(OffLedgerReminder, _uuid(reminder_id, "идентификатор напоминания"))
    if r is None or r.company_id != cid:
        raise HTTPException(404, "Напоминание не найдено")
    await db.delete(r)
    await db.commit()
    return {"deleted": True}


@router.get("/people/statement")
async def person_statement(
    company_id: str,
    person: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Всё, что между нами: расчёты, обязательства, договорённости и напоминания.

    Жанр акта сверки: именно этим пользуются, когда доходит до разговора. Собирается по
    имени, а не по ссылке на карточку, — записи третьего слоя держат вторую сторону
    строкой, и требовать заведённой карточки значило бы потерять часть истории.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    st = await _settings(cid, db)
    years, show_disclaimer = st.limitation_years, st.show_disclaimer
    await db.commit()
    key = person.strip().lower()

    cash = list((await db.execute(
        select(OffLedgerCash).where(
            OffLedgerCash.company_id == cid,
            func.lower(OffLedgerCash.person_name) == key)
        .order_by(OffLedgerCash.happened_on))).scalars().all())
    repaid = await _repaid_map(cid, db)
    rows = []
    for c in cash:
        row = _cash_row(c, repaid.get(c.id, 0.0))
        row.update(_limitation(c, years))
        rows.append(row)

    coms = [c for c in await _commitments(cid, db)
            if c["person"].strip().lower() == key]
    records = [r for r in (await db.execute(
        select(OffLedgerRecord).where(OffLedgerRecord.company_id == cid))).scalars().all()
        if (r.counterparty_name or "").strip().lower() == key]
    reminders = list((await db.execute(
        select(OffLedgerReminder).where(
            OffLedgerReminder.company_id == cid,
            func.lower(OffLedgerReminder.person_name) == key)
        .order_by(OffLedgerReminder.happened_on.desc()))).scalars().all())
    card = (await db.execute(
        select(OffLedgerPerson).where(
            OffLedgerPerson.company_id == cid,
            func.lower(OffLedgerPerson.name) == key))).scalar_one_or_none()

    open_rows = [r for r in rows if r["kind"] in OPEN_KINDS and (r["rest"] or 0) > 0.01]
    return {
        "person": card.name if card else person,
        "card": {
            "kind": card.kind if card else None,
            "role": card.role if card else None,
            "phone": card.phone if card else None,
            "payoutPhone": card.payout_phone if card else None,
            "payoutBank": card.payout_bank if card else None,
            "payoutNote": card.payout_note if card else None,
        } if card else None,
        "cash": rows,
        "commitments": coms,
        "records": await _with_names(records, db, cid),
        "reminders": [_reminder_row(r) for r in reminders],
        "totals": {
            "out": round(sum(r["amount"] for r in rows
                             if r["direction"] == "out"
                             and r["kind"] not in ("report", "offset", "writeoff")), 2),
            "in": round(sum(r["amount"] for r in rows
                            if r["direction"] == "in"
                            and r["kind"] not in ("report", "offset", "writeoff")), 2),
            # Не закрыто: займы и подотчёт со знаком — плюс за человеком, минус за нами.
            "open": round(sum((r["rest"] or 0) * (1 if r["direction"] == "out" else -1)
                              for r in open_rows), 2),
            "openCount": len(open_rows),
            "writtenOff": round(sum(r["amount"] for r in rows
                                    if r["kind"] == "writeoff"), 2),
        },
        "disclaimer": DISCLAIMER if show_disclaimer else None,
    }


# ── Быстрый ввод одной строкой ───────────────────────────────────────────────
# Главная причина смерти таких реестров — не нехватка возможностей, а секунды: запись,
# требующая двух минут и семи полей, не делается вовсе. Поэтому «5000 Иванову за монтаж
# наличными» разбирается в черновик операции, а человек подтверждает одним нажатием.
#
# Разбор намеренно грубый и предсказуемый: он не угадывает, а находит очевидное — сумму,
# знакомое имя, слово вида, дату. Всё, чего не нашёл, остаётся пустым — заполнить проще,
# чем вычищать неверно угаданное.

# Слова, по которым узнаётся вид операции. Порядок важен: «вернул долг» это возврат, а
# не долг, поэтому длинные и составные раньше коротких.
QUICK_KINDS: list[tuple[str, str]] = [
    ("под отчет", "advance"), ("под отчёт", "advance"), ("подотчет", "advance"),
    ("подотчёт", "advance"), ("аванс", "advance"),
    ("вернул", "repayment"), ("возврат", "repayment"), ("отдал долг", "repayment"),
    ("отчитал", "report"), ("чеки", "report"), ("отчет по", "report"),
    ("в долг", "loan"), ("займ", "loan"), ("заем", "loan"), ("одолжил", "loan"),
    ("проезд", "travel"), ("такси", "travel"), ("бензин", "travel"),
    ("прем", "bonus"),
    ("зарплат", "extra_pay"), ("сверх ведомости", "extra_pay"),
    ("работ", "work"), ("монтаж", "work"), ("ремонт", "work"), ("услуг", "work"),
]
# Слова направления: по умолчанию деньги уходят.
QUICK_IN = ("получил", "вернул", "принял", "внес", "внёс", "отдал мне")
# Чьи деньги.
QUICK_PURSE = (("из кассы", "company"), ("касс", "company"), ("своих", "owner"),
               ("личн", "owner"))


def _parse_quick(text_: str, people: list[str]) -> dict[str, Any]:
    """Разобрать строку в черновик операции.

    Возвращает то, в чём уверен, и список того, что понял, — человек видит разбор до
    сохранения. Неугаданное остаётся пустым: дозаполнить дешевле, чем спорить с
    неверной догадкой.
    """
    import re

    raw = " ".join(text_.split())
    low = raw.lower()
    got: list[str] = []

    # Сумма: первое число, допускающее пробелы-разделители и запятую.
    amount = None
    m = re.search(r"(\d[\d\s]*(?:[.,]\d{1,2})?)", raw)
    if m:
        try:
            amount = float(m.group(1).replace(" ", "").replace(",", "."))
            got.append(f"сумма {amount:g}")
        except ValueError:
            amount = None

    # Человек: сперва точное вхождение известного имени, иначе слово с заглавной буквы,
    # не являющееся первым словом-числом.
    person = None
    for name in sorted(people, key=len, reverse=True):
        if name and name.lower() in low:
            person = name
            got.append(f"человек «{name}» из списка")
            break
    if person is None:
        # «Иванову», «Петровой» — берём слово с большой буквы и отбрасываем окончание
        # дательного падежа: справочник всё равно сведёт по совпадению.
        for w in re.findall(r"\b([А-ЯЁ][а-яё]{2,})\b", raw):
            person = re.sub(r"(ову|еву|ину|ому|ой|у|е)$", "", w)
            got.append(f"человек «{person}» из текста")
            break

    kind = "work"
    for word, k in QUICK_KINDS:
        if word in low:
            kind, _ = k, got.append(f"вид по слову «{word}»")
            break

    direction = "in" if any(w in low for w in QUICK_IN) else "out"
    purse = "owner"
    for word, p_ in QUICK_PURSE:
        if word in low:
            purse = p_
            got.append("деньги компании" if p_ == "company" else "личные средства")
            break

    # Дата: «вчера», «позавчера», «12.08» или сегодня.
    happened = date.today()
    if "позавчера" in low:
        happened = date.today() - timedelta(days=2)
        got.append("позавчера")
    elif "вчера" in low:
        happened = date.today() - timedelta(days=1)
        got.append("вчера")
    else:
        md = re.search(r"\b(\d{1,2})[.](\d{1,2})(?:[.](\d{2,4}))?\b", raw)
        if md:
            d_, m_, y_ = int(md.group(1)), int(md.group(2)), md.group(3)
            year = date.today().year if not y_ else int(y_) + (2000 if len(y_) == 2 else 0)
            try:
                happened = date(year, m_, d_)
                got.append(f"дата {happened.isoformat()}")
            except ValueError:
                pass

    # Назначение: то, что осталось после числа и имени — обычно и есть «за что».
    purpose = raw
    if m:
        purpose = purpose.replace(m.group(1), " ", 1)
    if person:
        purpose = re.sub(person + r"[а-яё]*", " ", purpose, flags=re.IGNORECASE)
    purpose = " ".join(purpose.split()).strip(" ,.-—")

    return {
        "personName": person or "",
        "amount": amount,
        "happenedOn": happened.isoformat(),
        "kind": kind,
        "direction": direction,
        "purse": purse,
        "purpose": purpose or None,
        "proof": "none",
        "personKind": "individual",
        "understood": got,
        # Чего не хватает для сохранения: показываем сразу, а не после отказа.
        "missing": [w for w, ok in (("с кем", bool(person)), ("сумма", bool(amount)))
                    if not ok],
    }


@router.post("/cash/parse")
async def parse_quick(
    company_id: str,
    text_line: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Разобрать строку быстрого ввода в черновик операции."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    names = [r[0] for r in (await db.execute(
        select(OffLedgerPerson.name).where(OffLedgerPerson.company_id == cid,
                                           OffLedgerPerson.is_active.is_(True)))).all()]
    st = await _settings(cid, db)
    allowed = {k for k in CASH_KINDS if k not in GATED_KINDS or getattr(st, GATED_KINDS[k])}
    await db.commit()
    draft = _parse_quick(text_line, names)
    # Вид под выключенной настройкой не подставляем: иначе форма предложит то, чего у
    # компании нет.
    if draft["kind"] not in allowed:
        draft["kind"] = "work"
    draft["kindLabel"] = CASH_KINDS.get(draft["kind"], draft["kind"])
    return draft


# ── Сверка кошелька ──────────────────────────────────────────────────────────

class ReconcileIn(BaseModel):
    countedOn: str
    counted: float = Field(ge=0)
    purse: str = "owner"
    note: str | None = Field(default=None, max_length=2000)


@router.get("/cash/reconcile")
async def cash_reconcile_state(
    company_id: str,
    purse: str = "owner",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сколько наличных должно быть по журналу.

    Единственный способ узнать масштаб незаписанного — пересчитать деньги и сравнить.
    Расхождение закрывается ЯВНОЙ операцией с причиной, а не подгонкой остатка: подгонка
    молча уменьшает то, что было, вместо того чтобы показать, что ушло мимо записи.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    rows = list((await db.execute(
        select(OffLedgerCash).where(OffLedgerCash.company_id == cid,
                                    OffLedgerCash.purse == purse)
    )).scalars().all())
    flow = [c for c in rows if c.kind not in ("report", "offset", "writeoff")]
    out = round(sum(float(c.amount) for c in flow if c.direction == "out"), 2)
    inn = round(sum(float(c.amount) for c in flow if c.direction == "in"), 2)
    last = (await db.execute(
        select(OffLedgerCash).where(OffLedgerCash.company_id == cid,
                                    OffLedgerCash.purse == purse,
                                    OffLedgerCash.kind == "adjust")
        .order_by(OffLedgerCash.happened_on.desc()).limit(1))).scalar_one_or_none()
    return {
        "purse": purse,
        "purseLabel": CASH_PURSE.get(purse, purse),
        "out": out, "in": inn,
        # По журналу «в кошельке» столько, сколько пришло минус ушло. Отрицательное
        # значение нормально: часть расчётов ведётся из денег, не проходивших журнал.
        "byJournal": round(inn - out, 2),
        "lastCheckedOn": last.happened_on.isoformat() if last else None,
        "lastDiff": float(last.amount) if last else None,
    }


@router.post("/cash/reconcile")
async def cash_reconcile(
    company_id: str,
    body: ReconcileIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Записать пересчёт: разница становится отдельной операцией с причиной."""
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    if body.purse not in CASH_PURSE:
        raise HTTPException(422, f"Неизвестный источник средств: {body.purse}")
    state = await cash_reconcile_state(company_id, body.purse, db, current_user)
    diff = round(body.counted - state["byJournal"], 2)
    if abs(diff) < 0.01:
        return {"diff": 0.0, "created": False,
                "message": "Пересчёт сошёлся с журналом"}
    c = OffLedgerCash(
        company_id=cid,
        # Меньше, чем по журналу, — значит часть денег ушла мимо записи (расход);
        # больше — значит мимо записи пришли.
        direction="out" if diff < 0 else "in",
        kind="adjust", happened_on=_day(body.countedOn) or date.today(),
        amount=abs(diff), person_name="Пересчёт наличных",
        purpose=body.note or "расхождение при пересчёте кошелька",
        proof="none", purse=body.purse, created_by=current_user.id,
    )
    db.add(c)
    await db.flush()
    await log_audit(db, actor=current_user, company_id=cid,
                    action="perimeter.cash.reconcile", target=str(c.id),
                    details={"diff": diff, "counted": body.counted})
    await db.commit()
    await db.refresh(c)
    return {"diff": diff, "created": True, "row": _cash_row(c)}


# ── Прогноз потребности в наличных ───────────────────────────────────────────

@router.get("/cash/forecast")
async def cash_forecast(
    company_id: str,
    days: int = 60,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сколько наличных понадобится в ближайшие недели и когда.

    Прогноз строится не из тренда, а из уже известных обязательств: регулярные выплаты
    разворачиваются по своим периодам, к ним добавляются сроки возврата полученных
    займов. Каждая точка объяснима — это её главное свойство; тренд по средним такого не
    даёт и потому решений не меняет.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    horizon = date.today() + timedelta(days=max(7, min(days, 365)))
    today = date.today()

    points: list[dict[str, Any]] = []
    for c in await _commitments(cid, db, only_active=True):
        if c["form"] != "money" or not c["amount"]:
            continue
        cur = _period_start(today, c["periodicity"])
        # Незакрытый текущий период — тоже расход, который предстоит.
        closed = {p["periodStart"] for p in c["periods"] if p["outcome"] == "done"}
        while cur <= horizon:
            if cur.isoformat() not in closed:
                due = cur
                if c["dueDay"] and c["periodicity"] == "month":
                    last_day = (_next_period(cur, "month") - timedelta(days=1)).day
                    due = cur.replace(day=min(c["dueDay"], last_day))
                if due >= today:
                    points.append({
                        "date": due.isoformat(), "amount": c["amount"],
                        "what": f'{c["person"]}: {c["title"]}',
                        "kind": "commitment", "id": c["id"],
                    })
            cur = _next_period(cur, c["periodicity"])
            if c["endsOn"] and cur > _day(c["endsOn"]):
                break

    repaid = await _repaid_map(cid, db)
    for c in (await db.execute(
        select(OffLedgerCash).where(OffLedgerCash.company_id == cid,
                                    OffLedgerCash.kind.in_(OPEN_KINDS),
                                    OffLedgerCash.direction == "in")
    )).scalars().all():
        rest = round(float(c.amount) - repaid.get(c.id, 0.0), 2)
        if rest > 0.01 and c.due_on and today <= c.due_on <= horizon:
            points.append({
                "date": c.due_on.isoformat(), "amount": rest,
                "what": f"вернуть {c.person_name}", "kind": "loan", "id": str(c.id),
            })

    points.sort(key=lambda p: p["date"])
    weeks: dict[str, float] = {}
    for p_ in points:
        wk = (_day(p_["date"]) - timedelta(days=_day(p_["date"]).weekday())).isoformat()
        weeks[wk] = round(weeks.get(wk, 0.0) + p_["amount"], 2)
    return {
        "points": points,
        "total": round(sum(p_["amount"] for p_ in points), 2),
        "weeks": [{"weekStart": k, "amount": v} for k, v in sorted(weeks.items())],
        "horizon": horizon.isoformat(),
        # Ближайшие тридцать дней — то, под что деньги нужны уже сейчас.
        "next30": round(sum(p_["amount"] for p_ in points
                            if _day(p_["date"]) <= today + timedelta(days=30)), 2),
    }


# ── Как изменился долг за период ─────────────────────────────────────────────

@router.get("/cash/debt-bridge")
async def debt_bridge(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Мост: было → выдали → вернули → зачли → списали → стало.

    Возрастные корзины отвечают «сколько и как давно», но не отвечают «почему стало
    больше». Мост показывает движение целиком, и каждая ступень — сумма операций своего
    вида, а не расчётная разность.
    """
    cid = await assert_company_product(company_id, current_user, db, PRODUCT)
    df, dt = _day(date_from), _day(date_to)
    rows = list((await db.execute(
        select(OffLedgerCash).where(OffLedgerCash.company_id == cid)
    )).scalars().all())

    def rest_at(moment: date) -> float:
        """Незакрытый остаток выданного на конец дня."""
        total = 0.0
        for c in rows:
            if c.kind not in OPEN_KINDS or c.direction != "out" or c.happened_on > moment:
                continue
            closed = sum(float(x.amount) for x in rows
                         if x.parent_id == c.id and x.happened_on <= moment)
            total += max(float(c.amount) - closed, 0.0)
        return round(total, 2)

    started = rest_at(df - timedelta(days=1))
    in_period = [c for c in rows if df <= c.happened_on <= dt]

    def summa(kinds: tuple[str, ...], direction: str | None = None) -> float:
        return round(sum(float(c.amount) for c in in_period
                         if c.kind in kinds
                         and (direction is None or c.direction == direction)), 2)

    given = summa(OPEN_KINDS, "out")
    returned = summa(("repayment",), "in")
    reported = summa(("report",), "in")
    offset = summa(("offset",), "in")
    written = summa(("writeoff",), "in")
    ended = rest_at(dt)
    steps = [
        {"key": "start", "label": "Было на начало", "amount": started, "kind": "total"},
        {"key": "given", "label": "Выдали", "amount": given, "kind": "plus"},
        {"key": "returned", "label": "Вернули деньгами", "amount": -returned, "kind": "minus"},
        {"key": "reported", "label": "Закрыли отчётом", "amount": -reported, "kind": "minus"},
        {"key": "offset", "label": "Зачли встречным", "amount": -offset, "kind": "minus"},
        {"key": "written", "label": "Списали", "amount": -written, "kind": "minus"},
        {"key": "end", "label": "Стало на конец", "amount": ended, "kind": "total"},
    ]
    # Проверка сходимости: если ступени не дают конечный остаток, значит часть движения
    # прошла мимо видов — честнее показать расхождение, чем подогнать.
    calc = round(started + given - returned - reported - offset - written, 2)
    return {
        "steps": steps,
        "from": df.isoformat(), "to": dt.isoformat(),
        "checks": {"calculated": calc, "actual": ended,
                   "diff": round(ended - calc, 2)},
    }
