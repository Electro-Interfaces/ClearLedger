"""Закрытие месяца по затратам эксплуатации: расчётные суммы и корректировки.

ЗАЧЕМ. Месяц кончился, часть документов не пришла. Ждать их бесконечно нельзя —
затраты периода нужны бухгалтерии в срок. Поэтому период закрывается тем, что
есть: где документ пришёл — его суммой, где нет — расчётной, с явной пометкой
метода. Так закрытый месяц перестаёт быть ложью двух видов: «ноль, потому что
не прислали» и «неизвестно, откуда эта цифра».

ГЛАВНОЕ ПРАВИЛО: ЗАКРЫТЫЙ МЕСЯЦ НЕ ПЕРЕПИСЫВАЕТСЯ. Документ, пришедший позже,
не меняет сумму закрытого периода — он рождает корректировку в текущем
открытом. Иначе цифра, уже отданная в бухгалтерию, поедет задним числом, и
никто не узнает, когда именно.

Корректировку создаёт ЧЕЛОВЕК кнопкой, а не система молча. Разница между
«показать расхождение и предложить» и «провести самому» — это разница между
инструментом и сюрпризом в отчётности.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OpsCounterpartyDoc, OpsPeriodCharge, OpsPeriodClose
from app.services.ops_expectations import (
    build_ctx,
    estimate,
    expand,
    month_bounds,
    month_range,
    shift_month,
)

# Пороги расхождения. Слова те же, что у AccountingDoc.discrepancy_status:
# расхождение в двух контурах обязано называться одинаково, иначе «material»
# на одном экране и «критично» на другом окажутся разными шкалами.
ROUNDING_ABS_RUB = 1.0    # копеечная разница округления — не повод для корректировки
MINOR_REL_PCT = 2.0       # до 2% — заметно, но в рабочем порядке
# Через сколько дней после срока сбора период уходит на разбор.
REVIEW_GRACE_DAYS = 3

CLOSED_STATUSES = ("closed",)
# Статусы строки, которые считаются «закрытыми» при подсчёте готовности месяца.
SETTLED_STATUSES = ("matched", "accrued", "corrected", "waived")


# ── Классификация расхождения ──────────────────────────────────────────────

def classify_variance(expected: float | None, actual: float | None) -> tuple[float, str]:
    """Разница «факт − ожидание» и её класс.

    Пустое ожидание при пришедшем документе — это не «расхождение на всю сумму»,
    а `material` по определению: мы не ждали ничего и получили счёт. Обратное
    (ждали, документа нет) сюда не попадает — там работает расчётный метод.
    """
    if actual is None:
        return 0.0, "none"
    exp = float(expected or 0)
    variance = round(float(actual) - exp, 2)
    if variance == 0:
        return 0.0, "none"
    if abs(variance) <= ROUNDING_ABS_RUB:
        return variance, "rounding"
    if exp and abs(variance) / abs(exp) * 100 <= MINOR_REL_PCT:
        return variance, "minor"
    return variance, "material"


def needs_correction(variance_class: str) -> bool:
    """Стоит ли предлагать корректировку. Округление её не заслуживает."""
    return variance_class in ("minor", "material")


# ── Состояние периода ──────────────────────────────────────────────────────

def auto_status(period: str, today: str, max_due_day: int | None = None) -> str:
    """Куда период дошёл сам по календарю, если человек его ещё не закрыл.

    Отдельного воркера для этого нет: статус вычисляется лениво при чтении
    экрана. Плодить фоновую задачу ради трёх сравнений дат незачем.
    """
    _, last = month_bounds(period)
    if today <= last:
        return "open"
    due = shift_month(period, 1)
    y, m = int(due[0:4]), int(due[5:7])
    day = min(int(max_due_day or 10), 28) + REVIEW_GRACE_DAYS
    return "review" if today > f"{y:04d}-{m:02d}-{day:02d}" else "collecting"


async def get_or_create(db: AsyncSession, company_id: uuid.UUID,
                        period: str) -> OpsPeriodClose:
    row = (await db.execute(select(OpsPeriodClose).where(
        OpsPeriodClose.company_id == company_id,
        OpsPeriodClose.period == period,
    ))).scalar_one_or_none()
    if row is None:
        row = OpsPeriodClose(company_id=company_id, period=period, status="open")
        db.add(row)
        await db.flush()
    return row


async def counters(db: AsyncSession, company_id: uuid.UUID,
                   period: str) -> dict[str, Any]:
    """Четыре цифры шапки: ждём · получили · закрыли расчётом · расхождения."""
    rows = (await db.execute(select(OpsPeriodCharge).where(
        OpsPeriodCharge.company_id == company_id,
        OpsPeriodCharge.period == period,
    ))).scalars().all()

    def money(items) -> float:
        total = 0.0
        for r in items:
            value = r.actual_gross if r.actual_gross is not None else r.expected_gross
            total += float(value or 0)
        return round(total, 2)

    with_doc = [r for r in rows if r.doc_id is not None]
    estimated = [r for r in rows if r.doc_id is None and r.status == "accrued"]
    waiting = [r for r in rows if r.doc_id is None and r.status == "expected"]
    variances = [r for r in rows if needs_correction(r.variance_class or "none")]
    no_basis = [r for r in rows if (r.expected_basis or "none") == "none"
                and r.doc_id is None]

    return {
        "total": len(rows), "totalGross": money(rows),
        "expected": {"count": len(waiting), "gross": money(waiting)},
        "received": {"count": len(with_doc), "gross": money(with_doc)},
        "estimated": {"count": len(estimated), "gross": money(estimated)},
        "variance": {"count": len(variances),
                     "gross": round(sum(
                         float(r.actual_gross or 0) - float(r.expected_gross or 0)
                         for r in variances), 2)},
        "noBasis": len(no_basis),
    }


# ── Привязка документа ─────────────────────────────────────────────────────

async def attach_doc(db: AsyncSession, company_id: uuid.UUID, charge_id: uuid.UUID,
                     doc_id: uuid.UUID, amount_gross: float | None = None,
                     amount_net: float | None = None, qty: float | None = None,
                     user_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Привязать документ к ожиданию и посчитать расхождение.

    Сумму можно передать явно: один документ закрывает несколько объектов, и
    доля объекта в нём — не сумма всего документа.

    Если период уже закрыт, ожидание НЕ переписывается: остаётся расчётная
    сумма, а рядом появляется факт и класс расхождения. Что с этим делать —
    решает человек кнопкой корректировки.
    """
    charge = await _charge(db, company_id, charge_id)
    doc = (await db.execute(select(OpsCounterpartyDoc).where(
        OpsCounterpartyDoc.company_id == company_id,
        OpsCounterpartyDoc.id == doc_id,
    ))).scalar_one_or_none()
    if doc is None:
        raise ValueError("Документ не найден")

    charge.doc_id = doc.id
    charge.actual_gross = amount_gross if amount_gross is not None else doc.amount_gross
    charge.actual_net = amount_net if amount_net is not None else doc.amount_net
    charge.actual_qty = qty if qty is not None else doc.qty

    variance, klass = classify_variance(charge.expected_gross, charge.actual_gross)
    charge.variance_class = klass
    period_row = await get_or_create(db, company_id, charge.period)
    # В открытом периоде документ и есть истина: ожидание подтягивается к факту,
    # чтобы итог месяца не зависел от того, в какой день его закрыли.
    if period_row.status not in CLOSED_STATUSES:
        charge.expected_gross = charge.actual_gross
        charge.expected_net = charge.actual_net
        charge.expected_qty = charge.actual_qty
        charge.expected_basis = "document"
        charge.variance_class = "none"
        variance = 0.0
    charge.status = "matched"

    doc.match_status = "manual" if user_id else "auto"
    doc.matched_by = user_id
    doc.matched_at = datetime.now(timezone.utc)
    await db.flush()

    return {"chargeId": str(charge.id), "variance": variance,
            "varianceClass": charge.variance_class,
            "periodClosed": period_row.status in CLOSED_STATUSES,
            "correctionOffered": (period_row.status in CLOSED_STATUSES
                                  and needs_correction(charge.variance_class or "none"))}


async def make_correction(db: AsyncSession, company_id: uuid.UUID, charge_id: uuid.UUID,
                          target_period: str | None = None, reason: str | None = None,
                          user_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Провести расхождение закрытого месяца корректировкой в открытом.

    Исходная строка остаётся как была — это её месяц и её цифра. Новая строка
    несёт только разницу и ссылку на источник, поэтому в реестре видно не
    «сумма вдруг выросла», а «корректировка за июнь».
    """
    charge = await _charge(db, company_id, charge_id)
    if charge.actual_gross is None:
        raise ValueError("Нечем корректировать: у строки нет фактической суммы")

    variance, klass = classify_variance(charge.expected_gross, charge.actual_gross)
    if not needs_correction(klass):
        raise ValueError("Расхождение в пределах округления — корректировка не нужна")

    period = target_period or await _current_open_period(db, company_id, charge.period)
    seq = int((await db.execute(select(func.coalesce(func.max(OpsPeriodCharge.seq), 0)).where(
        OpsPeriodCharge.company_id == company_id,
        OpsPeriodCharge.period == period,
        OpsPeriodCharge.term_id == charge.term_id,
    ))).scalar() or 0) + 1

    row = OpsPeriodCharge(
        company_id=company_id, period=period, cost_item=charge.cost_item,
        term_id=charge.term_id, contract_id=charge.contract_id,
        counterparty_id=charge.counterparty_id, location_id=charge.location_id,
        seq=seq,
        # Знак сохраняем: недоначислили — в плюс, переначислили — в минус.
        expected_gross=variance, expected_net=None, vat_pct=charge.vat_pct,
        expected_basis="correction", status="expected",
        corrects_charge_id=charge.id,
        correction_reason=reason or f"Документ за {charge.period[:7]} пришёл после закрытия",
    )
    db.add(row)
    charge.status = "corrected"
    await db.flush()
    return {"correctionId": str(row.id), "period": period, "amount": variance}


async def _current_open_period(db: AsyncSession, company_id: uuid.UUID,
                               after: str) -> str:
    """Ближайший незакрытый месяц, куда ляжет корректировка.

    Идём от месяца-источника вперёд, но не дальше текущего: провести
    корректировку в будущее нельзя — этого месяца ещё не было.
    """
    today = date.today().isoformat()[:7] + "-01"
    period = shift_month(after, 1)
    while period < today:
        row = (await db.execute(select(OpsPeriodClose).where(
            OpsPeriodClose.company_id == company_id,
            OpsPeriodClose.period == period,
        ))).scalar_one_or_none()
        if row is None or row.status not in CLOSED_STATUSES:
            return period
        period = shift_month(period, 1)
    return today


async def _charge(db: AsyncSession, company_id: uuid.UUID,
                  charge_id: uuid.UUID) -> OpsPeriodCharge:
    row = (await db.execute(select(OpsPeriodCharge).where(
        OpsPeriodCharge.company_id == company_id,
        OpsPeriodCharge.id == charge_id,
    ))).scalar_one_or_none()
    if row is None:
        raise ValueError("Строка начисления не найдена")
    return row


# ── Закрытие ───────────────────────────────────────────────────────────────

async def close_period(db: AsyncSession, company_id: uuid.UUID, period: str,
                       user_id: uuid.UUID | None = None,
                       force: bool = False) -> dict[str, Any]:
    """Закрыть месяц: незакрытое доводится расчётом, итоги замораживаются.

    `force` нужен для строк, у которых нет ни договорной суммы, ни истории.
    Закрывать их нулём молча нельзя: ноль в отчёте неотличим от «платили ноль».
    Без `force` закрытие останавливается и называет, сколько таких строк; с
    `force` они уходят в `waived` — «за месяц не начисляем», а не «начисляем 0».
    """
    period_row = await get_or_create(db, company_id, period)
    if period_row.status in CLOSED_STATUSES:
        raise ValueError(f"Период {period[:7]} уже закрыт")

    # Условия могли завести по ходу месяца — разворачиваем ещё раз, иначе они
    # никогда не попадут в реестр: следующий разворот будет уже другого месяца.
    await expand(db, company_id, period)

    rows = (await db.execute(select(OpsPeriodCharge).where(
        OpsPeriodCharge.company_id == company_id,
        OpsPeriodCharge.period == period,
        OpsPeriodCharge.status == "expected",
    ))).scalars().all()

    # Первый проход — только пересчёт сумм и сбор того, что закрыть нечем.
    # Статусы не трогаем: иначе отказ от закрытия пришлось бы откатывать
    # rollback'ом, а транзакцией управляет роутер, а не сервис.
    pending: list[OpsPeriodCharge] = []
    blocking: list[dict[str, Any]] = []
    ctx = await build_ctx(db, company_id)
    for row in rows:
        if row.doc_id is not None:
            continue
        # Корректировка уже несёт готовую сумму — пересчитывать её нечем и незачем.
        if row.seq == 0 and row.term_id is not None:
            term = await _term(db, row.term_id)
            if term is not None:
                est = estimate(ctx, term, period, row.location_id)
                if est["basis"] != "none":
                    row.expected_gross = est["gross"]
                    row.expected_net = est["net"]
                    row.expected_qty = est["qty"]
                    row.expected_basis = est["basis"]
        pending.append(row)
        if row.expected_gross is None:
            blocking.append({"chargeId": str(row.id), "locationId": row.location_id,
                             "costItem": row.cost_item,
                             "reason": "нет ни договорной суммы, ни истории для расчёта"})

    if blocking and not force:
        await db.flush()   # пересчёт сумм полезен и остаётся, статусы нетронуты
        return {"ok": False, "period": period, "blocking": blocking,
                "message": f"{len(blocking)} строк нечем закрыть: "
                           f"нет ни суммы в договоре, ни истории для расчёта"}

    accrued = waived = 0
    for row in pending:
        row.closed_in_period = period
        if row.expected_gross is None:
            # Не ноль: ноль в отчёте неотличим от «платили ноль».
            row.status = "waived"
            waived += 1
        else:
            row.status = "accrued"
            accrued += 1

    stats = await counters(db, company_id, period)
    period_row.status = "closed"
    period_row.closed_at = datetime.now(timezone.utc)
    period_row.closed_by = user_id
    period_row.expected_count = stats["total"]
    period_row.received_count = stats["received"]["count"]
    period_row.estimated_count = stats["estimated"]["count"]
    period_row.total_expected_gross = stats["totalGross"]
    period_row.total_actual_gross = stats["received"]["gross"]
    # Снимок нужен, чтобы «как было при закрытии» пережило любые последующие
    # правки справочников, условий и самих строк.
    period_row.summary = {"counters": stats, "accrued": accrued, "waived": waived,
                          "byBasis": await _by_basis(db, company_id, period)}
    await db.flush()

    return {"ok": True, "period": period, "accrued": accrued, "waived": waived,
            "counters": stats, "blocking": blocking}


async def reopen_period(db: AsyncSession, company_id: uuid.UUID, period: str,
                        reason: str, user_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Открыть закрытый месяц заново. Только с причиной — она остаётся навсегда."""
    if not (reason or "").strip():
        raise ValueError("Открытие закрытого периода требует причины")
    period_row = await get_or_create(db, company_id, period)
    if period_row.status not in CLOSED_STATUSES:
        raise ValueError(f"Период {period[:7]} и так не закрыт")
    period_row.status = "reopened"
    period_row.reopened_at = datetime.now(timezone.utc)
    period_row.reopen_reason = reason.strip()
    await db.flush()
    return {"ok": True, "period": period, "status": "reopened"}


async def _by_basis(db: AsyncSession, company_id: uuid.UUID,
                    period: str) -> dict[str, int]:
    """Чем закрыт месяц: сколько строк документом, сколько каким расчётом."""
    rows = (await db.execute(
        select(OpsPeriodCharge.expected_basis, func.count())
        .where(OpsPeriodCharge.company_id == company_id,
               OpsPeriodCharge.period == period)
        .group_by(OpsPeriodCharge.expected_basis))).all()
    return {(basis or "none"): int(count) for basis, count in rows}


async def _term(db: AsyncSession, term_id: uuid.UUID):
    from app.models import OpsContractTerm
    return (await db.execute(select(OpsContractTerm).where(
        OpsContractTerm.id == term_id))).scalar_one_or_none()


# ── Шкала периодов ─────────────────────────────────────────────────────────

async def periods_scale(db: AsyncSession, company_id: uuid.UUID,
                        date_from: str, date_to: str) -> dict[str, Any]:
    """Состояние КАЖДОГО отчётного периода: сколько ждали и сколько закрыли.

    Главный экран владельца. Одна цифра «сколько мы потратили» ничего не стоит,
    если неизвестно, на чём она держится: месяц, закрытый документами на 90%, и
    месяц, где документов нет вовсе, дают одинаково выглядящую сумму.

    Процент считаем ПО ДОКУМЕНТАМ, а не по «как-нибудь закрытым строкам»: цель —
    идеально закрытый период, а расчётная сумма это временная подпорка, а не
    достижение.
    """
    periods = month_range(date_from, date_to)
    if not periods:
        return {"periods": []}

    rows = (await db.execute(select(OpsPeriodCharge).where(
        OpsPeriodCharge.company_id == company_id,
        OpsPeriodCharge.period >= periods[0],
        OpsPeriodCharge.period <= periods[-1],
    ))).scalars().all()

    closes = {
        c.period: c for c in (await db.execute(select(OpsPeriodClose).where(
            OpsPeriodClose.company_id == company_id,
            OpsPeriodClose.period >= periods[0],
            OpsPeriodClose.period <= periods[-1],
        ))).scalars().all()
    }

    by_period: dict[str, list[OpsPeriodCharge]] = {p: [] for p in periods}
    for r in rows:
        by_period.setdefault(r.period, []).append(r)

    today = date.today().isoformat()
    out: list[dict[str, Any]] = []
    for p in periods:
        items = by_period.get(p, [])
        with_doc = [r for r in items if r.doc_id is not None]
        accrued = [r for r in items if r.doc_id is None and r.status == "accrued"]
        waiting = [r for r in items if r.doc_id is None and r.status == "expected"]
        overdue = [r for r in waiting if r.doc_due_on and r.doc_due_on < today]
        no_basis = [r for r in items if (r.expected_basis or "none") == "none"
                    and r.doc_id is None]
        total_gross = round(sum(
            float((r.actual_gross if r.actual_gross is not None else r.expected_gross) or 0)
            for r in items), 2)
        doc_gross = round(sum(float(r.actual_gross or 0) for r in with_doc), 2)
        close = closes.get(p)
        out.append({
            "period": p,
            "status": (close.status if close and close.status != "open"
                       else auto_status(p, today)),
            "closedAt": close.closed_at.isoformat() if close and close.closed_at else None,
            "total": len(items),
            "withDoc": len(with_doc),
            "accrued": len(accrued),
            "waiting": len(waiting),
            "overdue": len(overdue),
            "noBasis": len(no_basis),
            # Доля строк, закрытых документом. Это и есть «процент выполнения».
            "docPct": round(len(with_doc) / len(items) * 100) if items else None,
            # Доля денег, подтверждённая документом: строк может быть закрыто
            # много, но мелких, а крупная аренда как раз и не пришла.
            "docMoneyPct": round(doc_gross / total_gross * 100) if total_gross else None,
            "totalGross": total_gross,
            "docGross": doc_gross,
        })

    done = [p for p in out if p["docPct"] is not None]
    return {
        "from": periods[0], "to": periods[-1], "periods": out,
        "avgDocPct": round(sum(p["docPct"] for p in done) / len(done)) if done else None,
        "worst": sorted(done, key=lambda x: x["docPct"])[:3],
    }


# ── Дисциплина контрагентов ────────────────────────────────────────────────

async def counterparty_discipline(db: AsyncSession, company_id: uuid.UUID,
                                  date_from: str, date_to: str) -> dict[str, Any]:
    """Кто как с нами работает: вовремя, с опозданием или молча.

    Без этой таблицы «контрагент не присылает документы» остаётся ощущением.
    С ней это список из десяти имён с телефонами, по которому можно звонить.

    Опоздание считаем от `doc_due_on` — срока из условия договора, а не от
    даты документа: контрагент может выписать акт первым числом и прислать его
    через два месяца.
    """
    from app.models import Counterparty, OpsContractTerm

    periods = month_range(date_from, date_to)
    rows = (await db.execute(select(OpsPeriodCharge).where(
        OpsPeriodCharge.company_id == company_id,
        OpsPeriodCharge.period >= periods[0],
        OpsPeriodCharge.period <= periods[-1],
    ))).scalars().all()

    docs = {
        d.id: d for d in (await db.execute(select(OpsCounterpartyDoc).where(
            OpsCounterpartyDoc.company_id == company_id))).scalars().all()
    }

    # Контакты: карточка контрагента плюс адрес, указанный прямо в условии —
    # у крупного поставщика бухгалтерия часто пишет с другого ящика.
    cps = (await db.execute(select(Counterparty).where(
        Counterparty.company_id == company_id))).scalars().all()
    by_ref: dict[str, Counterparty] = {}
    for cp in cps:
        for key in (cp.external_ref, str(cp.id)):
            if key:
                by_ref[key] = cp
    term_email: dict[str, str] = {}
    for cid, email in (await db.execute(
        select(OpsContractTerm.contract_id, OpsContractTerm.counterparty_email)
        .where(OpsContractTerm.company_id == company_id,
               OpsContractTerm.counterparty_email.isnot(None)))).all():
        term_email[str(cid)] = email

    today = date.today().isoformat()
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = r.counterparty_id or "—"
        a = agg.setdefault(key, {
            "counterpartyId": r.counterparty_id, "expected": 0, "onTime": 0,
            "late": 0, "missing": 0, "lateDays": [], "gross": 0.0, "docGross": 0.0,
            "periods": set(), "objects": set(), "costItems": set(),
        })
        a["expected"] += 1
        a["periods"].add(r.period)
        if r.location_id:
            a["objects"].add(r.location_id)
        a["costItems"].add(r.cost_item)
        a["gross"] += float((r.actual_gross if r.actual_gross is not None
                             else r.expected_gross) or 0)
        if r.doc_id is not None:
            a["docGross"] += float(r.actual_gross or 0)
            doc = docs.get(r.doc_id)
            received = (doc.received_at.date().isoformat()
                        if doc is not None and doc.received_at is not None else None)
            if received and r.doc_due_on and received > r.doc_due_on:
                a["late"] += 1
                a["lateDays"].append(_days_between(r.doc_due_on, received))
            else:
                a["onTime"] += 1
        elif r.doc_due_on and r.doc_due_on < today:
            a["missing"] += 1

    out: list[dict[str, Any]] = []
    for key, a in agg.items():
        cp = by_ref.get(key)
        delivered = a["onTime"] + a["late"]
        out.append({
            "counterpartyId": a["counterpartyId"],
            "name": (cp.short_name or cp.name) if cp else "не сопоставлен",
            "inn": cp.inn if cp else None,
            "email": (cp.email if cp else None) or term_email.get(key),
            "phone": cp.phone if cp else None,
            "director": cp.director_name if cp else None,
            "expected": a["expected"], "delivered": delivered,
            "onTime": a["onTime"], "late": a["late"], "missing": a["missing"],
            # Дисциплина: доля ожиданий, закрытых документом вовремя. Не «сколько
            # прислал вообще» — присланное на два месяца позже закрытия периода
            # уже стоило нам корректировки.
            "onTimePct": round(a["onTime"] / a["expected"] * 100) if a["expected"] else None,
            "deliveredPct": round(delivered / a["expected"] * 100) if a["expected"] else None,
            "avgLateDays": (round(sum(a["lateDays"]) / len(a["lateDays"]))
                            if a["lateDays"] else None),
            "gross": round(a["gross"], 2), "docGross": round(a["docGross"], 2),
            "periods": len(a["periods"]), "objects": len(a["objects"]),
            "costItems": sorted(a["costItems"]),
        })

    # Сортировка по деньгам, а не по проценту: молчащий контрагент на 200 тыс ₽
    # важнее аккуратного на пятьсот рублей.
    out.sort(key=lambda x: -x["gross"])
    return {
        "from": periods[0], "to": periods[-1], "rows": out,
        "totals": {
            "counterparties": len(out),
            "expected": sum(r["expected"] for r in out),
            "delivered": sum(r["delivered"] for r in out),
            "missing": sum(r["missing"] for r in out),
            "gross": round(sum(r["gross"] for r in out), 2),
            "noContact": sum(1 for r in out if not r["email"] and not r["phone"]),
        },
    }


def _days_between(a: str, b: str) -> int:
    """Разница дат в днях по ISO-строкам."""
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days


# ── Календарь сбора ────────────────────────────────────────────────────────

async def calendar(db: AsyncSession, company_id: uuid.UUID,
                   horizon_days: int = 45) -> dict[str, Any]:
    """Что и от кого ждём в ближайшие недели, и что уже просрочено.

    Договоры переходящие, поэтому сроки известны заранее — их не надо угадывать
    в конце месяца. Просроченное идёт первым и отдельной группой: это уже не
    план работы, а долг.
    """
    from app.models import Counterparty, ServiceLocation

    today = date.today()
    horizon = (today + timedelta(days=horizon_days)).isoformat()
    rows = (await db.execute(select(OpsPeriodCharge).where(
        OpsPeriodCharge.company_id == company_id,
        OpsPeriodCharge.status.in_(("expected", "disputed")),
        OpsPeriodCharge.doc_id.is_(None),
        OpsPeriodCharge.doc_due_on.isnot(None),
        OpsPeriodCharge.doc_due_on <= horizon,
    ).order_by(OpsPeriodCharge.doc_due_on))).scalars().all()

    names = await counterparty_names(db, company_id, {r.counterparty_id for r in rows})
    loc_ids = {r.location_id for r in rows if r.location_id}
    locations = {
        l.id: l.name for l in (await db.execute(select(ServiceLocation).where(
            ServiceLocation.company_id == company_id,
            ServiceLocation.id.in_(loc_ids)))).scalars().all()
    } if loc_ids else {}

    iso = today.isoformat()
    buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        overdue = r.doc_due_on < iso
        key = "overdue" if overdue else r.doc_due_on
        b = buckets.setdefault(key, {
            "due": None if overdue else r.doc_due_on, "overdue": overdue,
            "count": 0, "gross": 0.0, "byCounterparty": {},
        })
        b["count"] += 1
        b["gross"] += float(r.expected_gross or 0)
        cp = names.get(r.counterparty_id or "") or "контрагент не сопоставлен"
        c = b["byCounterparty"].setdefault(cp, {"count": 0, "gross": 0.0, "objects": []})
        c["count"] += 1
        c["gross"] += float(r.expected_gross or 0)
        if r.location_id and len(c["objects"]) < 5:
            c["objects"].append(locations.get(r.location_id) or r.location_id)

    out = []
    for key in sorted(buckets, key=lambda k: ("" if k == "overdue" else k)):
        b = buckets[key]
        b["gross"] = round(b["gross"], 2)
        b["byCounterparty"] = sorted(
            ({"name": n, **v} for n, v in b["byCounterparty"].items()),
            key=lambda x: -x["gross"])[:20]
        out.append(b)
    return {"today": iso, "horizonDays": horizon_days, "buckets": out}


# ── Чтение реестра ─────────────────────────────────────────────────────────

async def counterparty_names(db: AsyncSession, company_id: uuid.UUID,
                             refs: set[str]) -> dict[str, str]:
    """Имена контрагентов по мягкой ссылке.

    ЕДИНСТВЕННОЕ место, где расшивается двусмысленность `counterparty_id`: в
    договорах и реестре там лежит то GUID из 1С (`Counterparty.external_ref`),
    то наш UUID. Чинить сами данные — отдельная работа на 883 договора; пока
    держим резолв в одной функции, чтобы потом чинить в одном месте.
    """
    from app.models import Counterparty
    refs = {r for r in refs if r}
    if not refs:
        return {}
    rows = (await db.execute(select(Counterparty).where(
        Counterparty.company_id == company_id))).scalars().all()
    out: dict[str, str] = {}
    for cp in rows:
        name = cp.short_name or cp.name
        for key in (cp.external_ref, str(cp.id)):
            if key and key in refs:
                out[key] = name
    return out


async def matrix(db: AsyncSession, company_id: uuid.UUID,
                 date_from: str, date_to: str,
                 scope: str = "location") -> dict[str, Any]:
    """Затраты за диапазон месяцев: объект × месяц × статья.

    Отвечает на вопрос владельца «что и как мы собрали по всем разрезам» за
    квартал и год. Квартал и год своего закрытия не имеют — это свёртка
    закрытых месяцев, поэтому считается на чтении, а не хранится.

    Метка источника (`byBasis`) идёт вместе с суммой: месяц, где половина строк
    закрыта расчётом, и месяц, где всё подтверждено документами, — это разные
    по достоверности цифры, и в отчёте они обязаны различаться.
    """
    from app.models import OpsCostItem, ServiceLocation

    q = select(OpsPeriodCharge).where(
        OpsPeriodCharge.company_id == company_id,
        OpsPeriodCharge.period >= date_from,
        OpsPeriodCharge.period <= date_to,
        OpsPeriodCharge.status != "waived",
    )
    if scope == "company":
        q = q.where(OpsPeriodCharge.location_id.is_(None))
    elif scope == "location":
        q = q.where(OpsPeriodCharge.location_id.isnot(None))
    rows = (await db.execute(q)).scalars().all()

    items = [(c.code, c.label) for c in (await db.execute(
        select(OpsCostItem).where(OpsCostItem.is_active.is_(True))
        .order_by(OpsCostItem.sort_order))).scalars().all()]
    loc_ids = {r.location_id for r in rows if r.location_id}
    locations = {
        l.id: l for l in (await db.execute(select(ServiceLocation).where(
            ServiceLocation.company_id == company_id,
            ServiceLocation.id.in_(loc_ids)))).scalars().all()
    } if loc_ids else {}

    periods = sorted({r.period for r in rows})
    cells: dict[tuple[str, str, str], float] = {}
    basis: dict[str, dict[str, int]] = {}
    for r in rows:
        value = r.actual_gross if r.actual_gross is not None else r.expected_gross
        if value is None:
            continue
        key = (r.location_id or "", r.period, r.cost_item)
        cells[key] = round(cells.get(key, 0.0) + float(value), 2)
        bucket = basis.setdefault(r.period, {})
        code = r.expected_basis or "none"
        bucket[code] = bucket.get(code, 0) + 1

    out_rows: list[dict[str, Any]] = []
    for loc in sorted({k[0] for k in cells},
                      key=lambda x: (locations[x].name if x in locations else "￿")):
        by_period = {p: {c: cells.get((loc, p, c), 0.0) for c, _ in items} for p in periods}
        total = round(sum(sum(v.values()) for v in by_period.values()), 2)
        out_rows.append({
            "locationId": loc or None,
            "locationName": (locations[loc].name if loc in locations
                             else "Общие затраты компании"),
            "locationType": locations[loc].type if loc in locations else None,
            "byPeriod": by_period,
            "total": total,
        })

    return {
        "from": date_from, "to": date_to, "periods": periods,
        "costItems": [{"code": c, "label": l} for c, l in items],
        "rows": out_rows,
        "totalsByPeriod": {p: round(sum(v for (_, pp, _), v in cells.items() if pp == p), 2)
                           for p in periods},
        "byBasis": basis,
    }


async def charges(db: AsyncSession, company_id: uuid.UUID, period: str,
                  scope: str = "location", status: str | None = None,
                  location_id: str | None = None) -> list[dict[str, Any]]:
    """Строки реестра за месяц для рабочего стола закрытия.

    `scope='company'` — только общие затраты (без объекта), `scope='location'` —
    только объектные, `scope='all'` — всё вместе. Разрез не фильтр ради удобства:
    общие затраты, показанные вперемешку с объектными, ломают итог по объектам.
    """
    from app.models import OpsCostItem, ServiceLocation

    q = select(OpsPeriodCharge).where(
        OpsPeriodCharge.company_id == company_id,
        OpsPeriodCharge.period == period,
    )
    if scope == "company":
        q = q.where(OpsPeriodCharge.location_id.is_(None))
    elif scope == "location":
        q = q.where(OpsPeriodCharge.location_id.isnot(None))
    if status:
        q = q.where(OpsPeriodCharge.status == status)
    if location_id:
        q = q.where(OpsPeriodCharge.location_id == location_id)
    rows = (await db.execute(q.order_by(OpsPeriodCharge.cost_item,
                                        OpsPeriodCharge.location_id))).scalars().all()

    items = {c.code: c.label for c in (await db.execute(select(OpsCostItem))).scalars().all()}
    loc_ids = {r.location_id for r in rows if r.location_id}
    locations = {
        l.id: l for l in (await db.execute(select(ServiceLocation).where(
            ServiceLocation.company_id == company_id,
            ServiceLocation.id.in_(loc_ids)))).scalars().all()
    } if loc_ids else {}
    names = await counterparty_names(db, company_id, {r.counterparty_id for r in rows})

    today = date.today().isoformat()
    out: list[dict[str, Any]] = []
    for r in rows:
        variance, klass = classify_variance(r.expected_gross, r.actual_gross)
        out.append({
            "id": str(r.id),
            "costItem": r.cost_item, "costItemLabel": items.get(r.cost_item, r.cost_item),
            "locationId": r.location_id,
            "locationName": (locations[r.location_id].name
                             if r.location_id in locations else None),
            # Тип объекта: офис и станция — разные предметы учёта, и смешивать
            # их в одном списке затрат нельзя (общеофисные расходы это своя статья).
            "locationType": (locations[r.location_id].type
                             if r.location_id in locations else None),
            "counterpartyId": r.counterparty_id,
            "counterpartyName": names.get(r.counterparty_id or ""),
            "contractId": str(r.contract_id) if r.contract_id else None,
            "termId": str(r.term_id) if r.term_id else None,
            "seq": r.seq,
            "correctsChargeId": str(r.corrects_charge_id) if r.corrects_charge_id else None,
            "correctionReason": r.correction_reason,
            "expectedGross": float(r.expected_gross) if r.expected_gross is not None else None,
            "expectedNet": float(r.expected_net) if r.expected_net is not None else None,
            "expectedQty": float(r.expected_qty) if r.expected_qty is not None else None,
            "expectedBasis": r.expected_basis,
            "actualGross": float(r.actual_gross) if r.actual_gross is not None else None,
            "actualQty": float(r.actual_qty) if r.actual_qty is not None else None,
            "vatPct": float(r.vat_pct) if r.vat_pct is not None else None,
            "docId": str(r.doc_id) if r.doc_id else None,
            "docDueOn": r.doc_due_on,
            # Просрочка — только пока документа нет: пришедший позже срока
            # документ красным гореть не должен, вопрос уже закрыт.
            "overdue": bool(r.doc_id is None and r.doc_due_on and r.doc_due_on < today
                            and r.status in ("expected", "disputed")),
            "status": r.status,
            "variance": variance, "varianceClass": klass,
            "reminders": len(((r.extra or {}).get("reminders")) or []),
            "note": r.note,
        })
    return out
