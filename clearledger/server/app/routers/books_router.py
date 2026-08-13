"""/api/books — бухгалтерия-эталон офисного пространства и её разрезы.

Первоисток концепции: у компании без объектов главный источник данных — её
БУХГАЛТЕРИЯ. Закрытый период в ней неизменяем и служит эталоном, с которым
сверяется всё остальное; открытый период — оперативные данные, которые ещё
поедут. Отсюда и разрезы: «Продажи» и «Услуги» не заводят своих чисел, а
читают тот же регистр под своим углом.

Один роутер на три приложения сознательно: данные одни (`gl_entries`,
`accounting_docs`), разные только вопросы к ним. Отдельные файлы означали бы
три копии одних и тех же выборок.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import (
    AccountingDoc, Counterparty, GlAccount, GlBalance, GlEntry, GlReference,
    GlTurnover, InvoicePayment, NomenclatureItem, Period, User, ReferenceSnapshot,
    SourceFile, VatEntry,
)

router = APIRouter(prefix="/books", tags=["Бухгалтерия пространства"])

# Счета выручки, НДС с продаж и себестоимости. Вынесены константами: у другой
# организации пространства план счетов тот же типовой, но если разойдётся —
# правится здесь, а не в пяти выборках.
REVENUE_KT = "90.01.1"
VAT_DT, VAT_KT = "90.03", "68.02"
COST_DT = "90.02.1"

# Имена видов документов и справочников для витрины «Данные». Держим на сервере: тот
# же словарь нужен и выгрузкам, а дублировать его во фронте — расходиться при первом
# же новом виде.
DOC_LABELS = {
    "sale": "Реализация (товары и услуги)",
    "purchase": "Поступление товаров и услуг",
    "invoice_out": "Счёт покупателю",
    "vat_invoice_out": "Счёт-фактура выданный",
    "vat_invoice_in": "Счёт-фактура полученный",
    "closing_op": "Регламентная операция закрытия",
    "manual_entry": "Операция вручную",
    "invoice_in": "Счёт от поставщика",
    "act_recon": "Акт сверки взаиморасчётов",
    "bank_in": "Поступление на расчётный счёт",
    "bank_out": "Списание с расчётного счёта",
    "payment_order": "Платёжное поручение",
    "cash_in": "Приходный кассовый ордер",
    "cash_out": "Расходный кассовый ордер",
    "advance_report": "Авансовый отчёт",
    "demand_note": "Требование-накладная",
    "proxy": "Доверенность",
    "purchase_correction": "Корректировка поступления",
}

# Папки реестра — УЧАСТКИ УЧЁТА, а не виды документов: счёт, накладная и
# счёт-фактура по одной сделке лежат в одной папке, потому что вопрос к ним общий
# («чем закрыт этот счёт»), а не «где хранятся счета-фактуры».
DOC_SECTIONS = [
    ("sales", "Продажи", ["invoice_out", "sale", "vat_invoice_out"]),
    ("purchases", "Закупки", ["purchase", "invoice_in", "vat_invoice_in",
                              "purchase_correction", "proxy"]),
    ("money", "Деньги", ["bank_in", "bank_out", "payment_order",
                         "cash_in", "cash_out", "advance_report"]),
    ("warehouse", "Склад", ["demand_note"]),
    ("recon", "Сверка", ["act_recon"]),
    # Служебные документы отдельно: пять сотен регламентных операций в общем списке
    # хоронят первичку, ради которой реестр и открывают.
    ("closing", "Закрытие периода", ["closing_op", "manual_entry"]),
]
SECTION_OF = {code: sec for sec, _, codes in DOC_SECTIONS for code in codes}

REF_LABELS = {
    "warehouses": "Склады",
    "subdivisions": "Подразделения",
    "cost_items": "Статьи затрат",
    "cashflow_items": "Статьи движения денежных средств",
    "nomenclature_kinds": "Виды номенклатуры",
    "persons": "Физические лица",
    "banks": "Банки",
    "bank_accounts": "Банковские счета",
    "period_locks": "Даты запрета изменения",
    "accounting_policy": "Учётная политика",
    "org_contacts": "Контакты организации",
    "units": "Единицы измерения",
    "organizations": "Организация",
    "users": "Пользователи базы",
    "signers": "Подписанты",
    "doc_status": "Статусы документов",
    "pay_terms": "Сроки оплаты",
    "payment_split": "Расшифровки платежей",
    "vat_sales": "Книга продаж (НДС)",
    "vat_purchases": "Книга покупок (НДС)",
    "balances": "Остатки по счетам",
    "contact_persons": "Контактные лица контрагентов",
    "nom_accounts": "Счета учёта номенклатуры",
}


def _num(v: Any) -> float:
    return float(v or 0)


async def _turnover(db: AsyncSession, cid, dt: str | None = None, kt: str | None = None,
                    year: int | None = None) -> float:
    q = select(func.coalesce(func.sum(GlEntry.amount), 0)).where(GlEntry.company_id == cid)
    if dt:
        q = q.where(GlEntry.account_dt == dt)
    if kt:
        q = q.where(GlEntry.account_kt == kt)
    if year:
        q = q.where(GlEntry.period_year == year)
    return _num((await db.execute(q)).scalar_one())


@router.get("/overview")
async def overview(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сводка бухгалтерии: выручка, НДС, себестоимость, прибыль и годы."""
    cid = await assert_company_member(company_id, current_user, db)

    revenue = await _turnover(db, cid, kt=REVENUE_KT)
    vat = await _turnover(db, cid, dt=VAT_DT, kt=VAT_KT)
    cost = await _turnover(db, cid, dt=COST_DT)

    years = [
        {"year": y, "revenue": _num(a)}
        for y, a in (await db.execute(
            select(GlEntry.period_year, func.sum(GlEntry.amount))
            .where(GlEntry.company_id == cid, GlEntry.account_kt == REVENUE_KT)
            .group_by(GlEntry.period_year).order_by(GlEntry.period_year)
        )).all()
    ]

    entries, first, last = (await db.execute(
        select(func.count(), func.min(GlEntry.entry_date), func.max(GlEntry.entry_date))
        .where(GlEntry.company_id == cid)
    )).one()

    periods_total, periods_closed = (await db.execute(
        select(func.count(),
               func.count().filter(Period.status == "closed"))
        .where(Period.company_id == cid)
    )).one()

    return {
        "revenue": revenue,
        "vat": vat,
        "revenueNet": revenue - vat,
        "cost": cost,
        "grossProfit": revenue - vat - cost,
        "entries": entries,
        "firstEntry": first.isoformat() if first else None,
        "lastEntry": last.isoformat() if last else None,
        "periodsTotal": periods_total,
        "periodsClosed": periods_closed,
        "years": years,
    }


@router.get("/turnover")
async def turnover(
    company_id: str,
    year: int | None = None,
    limit: int = Query(60, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Оборотка: обороты по счетам (дебет и кредит отдельно)."""
    cid = await assert_company_member(company_id, current_user, db)

    names = {a.code: a.name for a in (await db.execute(
        select(GlAccount).where(GlAccount.company_id == cid))).scalars()}

    acc: dict[str, dict[str, float]] = {}
    for field, side in ((GlEntry.account_dt, "debit"), (GlEntry.account_kt, "credit")):
        q = (select(field, func.sum(GlEntry.amount), func.count())
             .where(GlEntry.company_id == cid, field.is_not(None))
             .group_by(field))
        if year:
            q = q.where(GlEntry.period_year == year)
        for code, amount, n in (await db.execute(q)).all():
            row = acc.setdefault(code, {"debit": 0.0, "credit": 0.0, "entries": 0})
            row[side] = _num(amount)
            row["entries"] += n

    rows = [{"code": c, "name": names.get(c, ""), **v} for c, v in acc.items()]
    rows.sort(key=lambda r: -(r["debit"] + r["credit"]))
    return {"rows": rows[:limit], "total": len(rows)}


# ── Оборотно-сальдовая ведомость ─────────────────────────────────────────────
# Главный экран бухгалтера. Обороты без сальдо отвечают только на «сколько прошло
# через счёт», а вопрос «сколько на нём лежит» остаётся без ответа — с этого и
# начинается любая проверка.
#
# Сальдо считается НАРАСТАЮЩИМ ИТОГОМ от первой проводки, а не берётся из 1С:
# входящих остатков в выгрузке нет, зато есть весь регистр с первого дня
# организации (30.06.2021). Проверка честности одна и жёсткая: сумма сальдо по
# всем счетам = 0, то есть актив равен пассиву.
#
# ⚠ Сальдо СВЁРНУТОЕ. Развёрнутое по активно-пассивным счетам (62, 60, 76)
# требует субконто, а субконто регистра через COM недоступно (см. docs/REVENUE.md):
# по 62.01 видно чистую разницу, а не «дебиторка столько, авансы столько».

def _saldo_side(net: float) -> tuple[float, float]:
    """Разложить чистое сальдо на дебетовую и кредитовую колонки по его знаку."""
    if abs(net) < 0.005:
        return 0.0, 0.0
    return (net, 0.0) if net > 0 else (0.0, -net)


def _day(iso: str | None) -> date | None:
    """ISO-строка периода → `date`.

    ⚠ `gl_entries.entry_date` — настоящая ДАТА, в отличие от `accounting_docs.date`,
    где дата хранится строкой. Сравнение колонки-даты со строкой Postgres не делает
    вовсе: «operator does not exist: date < character varying».
    """
    return date.fromisoformat(iso) if iso else None


@router.get("/balance")
async def balance(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    hide_empty: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """ОСВ: сальдо на начало, обороты за период, сальдо на конец — с иерархией."""
    cid = await assert_company_member(company_id, current_user, db)
    day_from, day_to = _day(date_from), _day(date_to)

    accounts = {a.code: a for a in (await db.execute(
        select(GlAccount).where(GlAccount.company_id == cid))).scalars()}

    # Три выборки вместо одной: «до начала периода» и «внутри периода» — разные
    # вопросы, а группировка по дебету и кредиту в SQL всё равно раздельная.
    own: dict[str, dict[str, float]] = {}

    def cell(code: str) -> dict[str, float]:
        return own.setdefault(code, {"inDt": 0.0, "inKt": 0.0, "dt": 0.0, "kt": 0.0,
                                     "entries": 0.0})

    for field, key_before, key_period in (
        (GlEntry.account_dt, "inDt", "dt"), (GlEntry.account_kt, "inKt", "kt"),
    ):
        if day_from:
            q = (select(field, func.sum(GlEntry.amount))
                 .where(GlEntry.company_id == cid, field.is_not(None),
                        GlEntry.entry_date < day_from)
                 .group_by(field))
            for code, amount in (await db.execute(q)).all():
                cell(code)[key_before] = _num(amount)

        q = (select(field, func.sum(GlEntry.amount), func.count())
             .where(GlEntry.company_id == cid, field.is_not(None))
             .group_by(field))
        if day_from:
            q = q.where(GlEntry.entry_date >= day_from)
        if day_to:
            q = q.where(GlEntry.entry_date <= day_to)
        for code, amount, n in (await db.execute(q)).all():
            c = cell(code)
            c[key_period] = _num(amount)
            c["entries"] += n

    # Проводки идут по конечным субсчетам (90.01.1), а бухгалтер читает ведомость
    # сверху («что на 90-м») — поэтому цифры детей поднимаются к родителям по
    # цепочке parent_code. Свой оборот родителя (если проводки шли прямо на него)
    # при этом сохраняется: складываем, а не замещаем.
    totals: dict[str, dict[str, float]] = {}
    children: dict[str, set[str]] = {}
    for code, v in own.items():
        node = code
        seen = set()
        while node and node not in seen:
            seen.add(node)
            t = totals.setdefault(node, {"inDt": 0.0, "inKt": 0.0, "dt": 0.0, "kt": 0.0,
                                         "entries": 0.0})
            for k in t:
                t[k] += v[k]
            parent = accounts[node].parent_code if node in accounts else None
            if parent:
                children.setdefault(parent, set()).add(node)
            node = parent

    rows = []
    for code, t in totals.items():
        acc = accounts.get(code)
        net_in = t["inDt"] - t["inKt"]
        net_out = net_in + t["dt"] - t["kt"]
        in_dt, in_kt = _saldo_side(net_in)
        out_dt, out_kt = _saldo_side(net_out)
        if hide_empty and not any((in_dt, in_kt, t["dt"], t["kt"], out_dt, out_kt)):
            continue
        rows.append({
            "code": code,
            "name": acc.name if acc else "",
            "kind": acc.kind if acc else None,
            "offBalance": bool(acc.off_balance) if acc else False,
            "parent": acc.parent_code if acc else None,
            "level": code.count("."),
            "hasChildren": code in children,
            "saldoInDt": round(in_dt, 2), "saldoInKt": round(in_kt, 2),
            "turnoverDt": round(t["dt"], 2), "turnoverKt": round(t["kt"], 2),
            "saldoOutDt": round(out_dt, 2), "saldoOutKt": round(out_kt, 2),
            "entries": int(t["entries"]),
        })
    rows.sort(key=lambda r: r["code"])

    # Итог считается по КОРНЕВЫМ счетам: сложить все строки подряд значило бы
    # посчитать субсчета дважды. Забалансовые в баланс не входят — у них своя
    # строка, и без разделения итог никогда не сойдётся.
    def summed(pred) -> dict[str, float]:
        out = {"saldoInDt": 0.0, "saldoInKt": 0.0, "turnoverDt": 0.0,
               "turnoverKt": 0.0, "saldoOutDt": 0.0, "saldoOutKt": 0.0}
        for r in rows:
            if r["parent"] or not pred(r):
                continue
            for k in out:
                out[k] += r[k]
        return {k: round(v, 2) for k, v in out.items()}

    return {
        "rows": rows,
        "totals": summed(lambda r: not r["offBalance"]),
        "offBalanceTotals": summed(lambda r: r["offBalance"]),
        "periodFrom": date_from, "periodTo": date_to,
    }


@router.get("/account")
async def account_card(
    company_id: str,
    code: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(300, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Карточка счёта: проводки с корреспонденцией, сальдо нарастающим итогом,
    корреспондирующие счета и помесячная динамика.

    Субсчета включаются в карточку родителя (`code=90` показывает и 90.01.1):
    иначе клик по свёрнутой строке ведомости открывал бы пустую карточку.
    """
    cid = await assert_company_member(company_id, current_user, db)

    acc = (await db.execute(select(GlAccount).where(
        GlAccount.company_id == cid, GlAccount.code == code))).scalar_one_or_none()
    like = f"{code}.%"
    is_own = lambda f: (f == code) | f.like(like)  # noqa: E731

    async def side_sum(field, *conds) -> float:
        return _num((await db.execute(
            select(func.coalesce(func.sum(GlEntry.amount), 0))
            .where(GlEntry.company_id == cid, is_own(field), *conds))).scalar_one())

    day_from, day_to = _day(date_from), _day(date_to)
    before = ([GlEntry.entry_date < day_from] if day_from else None)
    opening = 0.0
    if before:
        opening = (await side_sum(GlEntry.account_dt, *before)
                   - await side_sum(GlEntry.account_kt, *before))

    period = []
    if day_from:
        period.append(GlEntry.entry_date >= day_from)
    if day_to:
        period.append(GlEntry.entry_date <= day_to)
    turn_dt = await side_sum(GlEntry.account_dt, *period)
    turn_kt = await side_sum(GlEntry.account_kt, *period)

    q = (select(GlEntry)
         .where(GlEntry.company_id == cid,
                is_own(GlEntry.account_dt) | is_own(GlEntry.account_kt), *period)
         .order_by(GlEntry.entry_date, GlEntry.id))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    entries = (await db.execute(q.limit(limit))).scalars().all()

    running = opening
    rows = []
    for e in entries:
        dt_own = e.account_dt == code or (e.account_dt or "").startswith(f"{code}.")
        amount = _num(e.amount)
        running += amount if dt_own else -amount
        rows.append({
            "date": e.entry_date.isoformat(),
            "docKind": e.doc_kind, "docTitle": e.doc_title,
            "account": e.account_dt if dt_own else e.account_kt,
            "corr": e.account_kt if dt_own else e.account_dt,
            "debit": amount if dt_own else 0.0,
            "credit": 0.0 if dt_own else amount,
            "saldo": round(running, 2),
            "content": e.content,
        })

    # Корреспонденция: с кем счёт работает и на сколько. Это ответ на вопрос
    # «откуда на счёте деньги» без чтения всех проводок подряд.
    corr: dict[str, dict[str, float]] = {}
    for e in entries:
        dt_own = e.account_dt == code or (e.account_dt or "").startswith(f"{code}.")
        other = e.account_kt if dt_own else e.account_dt
        if not other:
            continue
        c = corr.setdefault(other, {"debit": 0.0, "credit": 0.0, "entries": 0})
        c["debit" if dt_own else "credit"] += _num(e.amount)
        c["entries"] += 1

    months: dict[str, dict[str, float]] = {}
    mq = (select(GlEntry.period_year, GlEntry.period_month,
                 func.sum(GlEntry.amount).filter(is_own(GlEntry.account_dt)),
                 func.sum(GlEntry.amount).filter(is_own(GlEntry.account_kt)))
          .where(GlEntry.company_id == cid,
                 is_own(GlEntry.account_dt) | is_own(GlEntry.account_kt), *period)
          .group_by(GlEntry.period_year, GlEntry.period_month)
          .order_by(GlEntry.period_year, GlEntry.period_month))
    for y, m, dt, kt in (await db.execute(mq)).all():
        months[f"{y}-{m:02d}"] = {"debit": _num(dt), "credit": _num(kt)}

    closing = opening + turn_dt - turn_kt
    in_dt, in_kt = _saldo_side(opening)
    out_dt, out_kt = _saldo_side(closing)
    return {
        "code": code,
        "name": acc.name if acc else "",
        "kind": acc.kind if acc else None,
        "saldoInDt": round(in_dt, 2), "saldoInKt": round(in_kt, 2),
        "turnoverDt": round(turn_dt, 2), "turnoverKt": round(turn_kt, 2),
        "saldoOutDt": round(out_dt, 2), "saldoOutKt": round(out_kt, 2),
        "total": total, "shown": len(rows),
        "rows": rows,
        "corr": [{"code": k, **v} for k, v in sorted(
            corr.items(), key=lambda kv: -(kv[1]["debit"] + kv[1]["credit"]))],
        "months": [{"month": k, **v} for k, v in sorted(months.items())],
    }


@router.get("/entries")
async def entries(
    company_id: str,
    year: int | None = None,
    account: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Журнал проводок с фильтрами по году и счёту (в дебете или кредите)."""
    cid = await assert_company_member(company_id, current_user, db)

    q = select(GlEntry).where(GlEntry.company_id == cid)
    if year:
        q = q.where(GlEntry.period_year == year)
    if account:
        q = q.where((GlEntry.account_dt == account) | (GlEntry.account_kt == account))

    total = (await db.execute(
        select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(
        q.order_by(GlEntry.entry_date.desc()).limit(limit).offset(offset))).scalars().all()

    return {
        "total": total,
        "rows": [{
            "date": e.entry_date.isoformat(),
            "docKind": e.doc_kind,
            "docTitle": e.doc_title,
            "accountDt": e.account_dt,
            "accountKt": e.account_kt,
            "amount": _num(e.amount),
            "content": e.content,
        } for e in rows],
    }


@router.get("/periods")
async def periods(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Периоды: закрытый месяц — эталон, открытый ещё поедет.

    Обороты по месяцу считаются здесь же: закрытие без цифры ничего не говорит.
    """
    cid = await assert_company_member(company_id, current_user, db)

    by_month = {
        (y, m): {"entries": n, "revenue": 0.0}
        for y, m, n in (await db.execute(
            select(GlEntry.period_year, GlEntry.period_month, func.count())
            .where(GlEntry.company_id == cid)
            .group_by(GlEntry.period_year, GlEntry.period_month))).all()
    }
    for y, m, amount in (await db.execute(
        select(GlEntry.period_year, GlEntry.period_month, func.sum(GlEntry.amount))
        .where(GlEntry.company_id == cid, GlEntry.account_kt == REVENUE_KT)
        .group_by(GlEntry.period_year, GlEntry.period_month))).all():
        if (y, m) in by_month:
            by_month[(y, m)]["revenue"] = _num(amount)

    rows = []
    for p in (await db.execute(
        select(Period).where(Period.company_id == cid)
        .order_by(Period.year.desc(), Period.month.desc()))).scalars():
        cell = by_month.get((p.year, p.month), {"entries": 0, "revenue": 0.0})
        rows.append({"year": p.year, "month": p.month, "status": p.status,
                     "source": p.closure_source, **cell})
    return {"rows": rows}


@router.get("/docs")
async def docs(
    company_id: str,
    doc_type: str | None = None,
    section: str | None = Query(None, description="участок учёта: sales, purchases, money…"),
    line_kind: str | None = Query(None, description="разрез по типу строки: goods | service"),
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Первичные документы, приехавшие из бухгалтерии."""
    cid = await assert_company_member(company_id, current_user, db)

    q = select(AccountingDoc).where(AccountingDoc.company_id == cid)
    if doc_type:
        q = q.where(AccountingDoc.doc_type == doc_type)
    elif section:
        codes = [c for c, s in SECTION_OF.items() if s == section]
        q = q.where(AccountingDoc.doc_type.in_(codes))
    # Тот же период, что и у разрезов реализации: реестр под графиком обязан
    # показывать те же документы, из которых посчитаны цифры сверху.
    if date_from:
        q = q.where(AccountingDoc.date >= date_from)
    if date_to:
        q = q.where(AccountingDoc.date <= date_to)

    if line_kind:
        picked = [d for d in (await db.execute(
            q.order_by(AccountingDoc.date.desc()))).scalars()
            if any((l.get("kind") or "goods") == line_kind for l in (d.lines or []))]
        total = len(picked)
        rows = picked[offset:offset + limit]
    else:
        total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await db.execute(
            q.order_by(AccountingDoc.date.desc()).limit(limit).offset(offset))).scalars().all()

    # Счётчики видов — по ТОМУ ЖЕ периоду, что и список: иначе кнопка «Реализация
    # товаров · 431» стоит рядом с реестром на десяток строк, и человек считает,
    # что реестр обрезан ошибкой.
    kinds_q = (select(AccountingDoc.doc_type, func.count(), func.sum(AccountingDoc.amount))
               .where(AccountingDoc.company_id == cid).group_by(AccountingDoc.doc_type))
    if date_from:
        kinds_q = kinds_q.where(AccountingDoc.date >= date_from)
    if date_to:
        kinds_q = kinds_q.where(AccountingDoc.date <= date_to)
    counts = [(t, n, _num(a)) for t, n, a in (await db.execute(kinds_q)).all()]
    kinds = [{"type": t, "label": DOC_LABELS.get(t, t), "section": SECTION_OF.get(t),
              "count": n, "amount": a} for t, n, a in counts]

    # Папки реестра. Отдаём ВСЕ участки, включая пустые: пустая «Касса» — это ответ
    # («наличных операций нет»), а исчезнувшая папка читается как потерянные данные.
    sections = [{
        "code": code, "title": title,
        "count": sum(n for t, n, _ in counts if t in codes),
        "amount": sum(a for t, _, a in counts if t in codes),
        "kinds": [k for k in kinds if k["type"] in codes],
    } for code, title, codes in DOC_SECTIONS]

    # Оплата счёта — из регистра «Оплата счетов»: в самой первичке связи «счёт ↔
    # платёж» нет, реквизиты документов её не несут. Спрашиваем только по
    # показанным строкам, иначе тянули бы весь регистр ради страницы реестра.
    paid: dict[uuid.UUID, float] = {}
    doc_ids = [d.id for d in rows if d.doc_type == "invoice_out"]
    if doc_ids:
        paid = {r[0]: _num(r[1]) for r in (await db.execute(
            select(InvoicePayment.invoice_doc_id, func.sum(InvoicePayment.amount))
            .where(InvoicePayment.company_id == cid,
                   InvoicePayment.invoice_doc_id.in_(doc_ids))
            .group_by(InvoicePayment.invoice_doc_id))).all()}

    return {
        "total": total,
        "kinds": kinds,
        "sections": sections,
        "rows": [{
            "date": d.date, "number": d.number, "type": d.doc_type,
            "label": DOC_LABELS.get(d.doc_type, d.doc_type),
            "section": SECTION_OF.get(d.doc_type),
            "counterparty": d.counterparty_name, "inn": d.counterparty_inn,
            "amount": _num(d.amount), "vat": _num(d.vat_amount),
            # Назначение платежа и вид операции: без них банковская строка — только сумма.
            "operation": d.operation_type,
            "status": d.status_1c,
            # Закрытый период — половина ответа аудитору: документ уже не переписать.
            "periodStatus": d.period_status,
            "lines": len(d.lines or []),
            # Только у счетов покупателям: null — вопрос неприменим, 0 — не оплачен.
            "paid": (paid.get(d.id) or 0.0) if d.doc_type == "invoice_out" else None,
        } for d in rows],
    }


# ── Разрезы: продажи и услуги ────────────────────────────────────────────────
# Своих чисел не заводят: тот же `accounting_docs`, только вопрос другой —
# кто покупает, что покупает и как это менялось по месяцам.

async def _slice(db: AsyncSession, cid, doc_type: str, top: int,
                 date_from: str | None = None, date_to: str | None = None, *, line_kind: str | None = None) -> dict[str, Any]:
    docs_q = select(AccountingDoc).where(
        AccountingDoc.company_id == cid, AccountingDoc.doc_type == doc_type)
    # Период приходит из общего фильтра рабочей области. Дата документа хранится
    # строкой ISO (`YYYY-MM-DD`), поэтому сравнение лексикографическое — оно же
    # хронологическое; приводить к date незачем.
    if date_from:
        docs_q = docs_q.where(AccountingDoc.date >= date_from)
    if date_to:
        docs_q = docs_q.where(AccountingDoc.date <= date_to)
    rows = (await db.execute(docs_q)).scalars().all()

    by_month: dict[str, dict[str, float]] = {}
    by_client: dict[str, dict[str, Any]] = {}
    by_item: dict[str, dict[str, float]] = {}
    total = vat = 0.0
    picked_docs = 0

    for d in rows:
        if line_kind:
            picked = [l for l in (d.lines or []) if (l.get('kind') or 'goods') == line_kind]
            if not picked:
                continue
            amount = sum(_num(l.get('amount')) for l in picked)
            dvat = sum(_num(l.get('vat')) for l in picked)
        else:
            amount, dvat = _num(d.amount), _num(d.vat_amount)
        total += amount
        vat += dvat
        picked_docs += 1
        month = (d.date or "")[:7]
        m = by_month.setdefault(month, {"amount": 0.0, "docs": 0})
        m["amount"] += amount
        m["docs"] += 1

        # Ключ покупателя — ССЫЛКА на карточку, а не имя: одно юрлицо приезжает в
        # документах в разном написании и по имени разваливалось на две строки
        # разреза. Имя остаётся подписью, id — тем, по чему открывается карточка.
        ckey = str(d.counterparty_id) if d.counterparty_id else (d.counterparty_name or "—")
        c = by_client.setdefault(ckey,
                                 {"id": str(d.counterparty_id) if d.counterparty_id else None,
                                  "name": d.counterparty_name or "—", "inn": d.counterparty_inn,
                                  "amount": 0.0, "docs": 0})
        c["amount"] += amount
        c["docs"] += 1

        for ln in (d.lines or []):
            # Разрез по типу строки: один документ несёт и товары, и услуги.
            if line_kind and (ln.get('kind') or 'goods') != line_kind:
                continue
            # Позиция — по КОДУ номенклатуры: имя в строке документа пишется как
            # угодно, а код тот же, что в справочнике, и по нему открывается карточка.
            ikey = ln.get("code") or ln.get("name") or "—"
            it = by_item.setdefault(ikey,
                                    {"code": ln.get("code"),
                                     "name": ln.get("name") or "—", "amount": 0.0, "qty": 0.0})
            it["amount"] += _num(ln.get("amount"))
            it["qty"] += _num(ln.get("qty"))

    clients = sorted(by_client.values(), key=lambda x: -x["amount"])
    items = sorted(by_item.values(), key=lambda x: -x["amount"])
    return {
        "total": total,
        "vat": vat,
        "net": total - vat,
        "docs": picked_docs,
        "clients": len(clients),
        "months": [{"month": k, **v} for k, v in sorted(by_month.items())],
        "topClients": clients[:top],
        "topItems": items[:top],
    }


@router.get("/sales")
async def sales(
    company_id: str,
    top: int = Query(15, ge=1, le=500),
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Продажи товаров: динамика, покупатели, товары."""
    cid = await assert_company_member(company_id, current_user, db)
    return await _slice(db, cid, "sale", top, date_from, date_to, line_kind="goods")


@router.get("/services")
async def services(
    company_id: str,
    top: int = Query(15, ge=1, le=500),
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Услуги: динамика, заказчики, виды услуг."""
    cid = await assert_company_member(company_id, current_user, db)
    return await _slice(db, cid, "sale", top, date_from, date_to, line_kind="service")


# ── Нормализованный слой: карточка контрагента ───────────────────────────────
# Разрезы отвечают «сколько всего». Работа же идёт вокруг КЛИЕНТА: с ним говорят,
# ему выставляют, от него ждут денег. Карточка собирает всё, что о нём знает
# пространство, — из справочника, документов, договоров и регистра сразу.
#
# Ключ — ссылка (`counterparty_id`), а не имя: пока сводили по строке, у одного и
# того же юрлица «его документы» и «его долг» считались по разным множествам.

@router.post("/relink")
async def relink_docs(
    company_id: str,
    reset: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Свести документы со справочниками (контрагент, договор). Идемпотентно."""
    cid = await assert_company_member(company_id, current_user, db)
    from app.services.books_links import relink
    return await relink(db, cid, reset=reset)


@router.get("/counterparties")
async def counterparties(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Контрагенты пространства с их оборотами и долгом за период.

    Долг берётся ИЗ САЛЬДО источника (`gl_balances`), а не выводится из наших
    проводок. Считать его по проводкам нельзя дважды: остаток накоплен всей
    историей регистра, включая периоды до выгрузки, а проводка не знает, чей это
    долг — субконто через COM недоступно, и привязка шла через документ. Разница
    не теоретическая: расчёт по проводкам показывал аванс Полякова −196 540 ₽ и
    Сферы −21 182,40 ₽, которых в сальдо нет вовсе, и терял двух контрагентов,
    у кого долг и аванс лежат на разных субсчетах.
    """
    cid = await assert_company_member(company_id, current_user, db)
    params: dict[str, Any] = {"cid": str(cid), "df": date_from, "dt": date_to,
                              "q": f"%{q.lower()}%" if q else None, "lim": limit}
    rows = (await db.execute(text("""
        WITH doc AS (
          SELECT d.id, d.counterparty_id, d.doc_type, d.amount, d.date
            FROM accounting_docs d
           WHERE d.company_id = :cid AND d.counterparty_id IS NOT NULL
             AND (CAST(:df AS text) IS NULL OR d.date >= :df)
             AND (CAST(:dt AS text) IS NULL OR d.date <= :dt)
        ), agg AS (
          SELECT counterparty_id,
                 sum(amount) FILTER (WHERE doc_type = 'sale')     AS sales,
                 sum(amount) FILTER (WHERE doc_type = 'purchase') AS purchases,
                 sum(amount) FILTER (WHERE doc_type = 'bank_in')  AS paid_in,
                 sum(amount) FILTER (WHERE doc_type = 'bank_out') AS paid_out,
                 count(*)                                          AS docs,
                 max(date)                                         AS last_doc
            FROM doc GROUP BY 1
        ), debt AS (
          -- Сальдо последнего среза: дебет 62 — нам должны, кредит 60 — должны мы.
          SELECT b.counterparty_id,
                 sum(CASE WHEN b.account LIKE '62%' THEN b.debit - b.credit ELSE 0 END) AS ar,
                 sum(CASE WHEN b.account LIKE '60%' THEN b.credit - b.debit ELSE 0 END) AS ap
            FROM gl_balances b
           WHERE b.company_id = :cid AND b.counterparty_id IS NOT NULL
             AND b.as_of = (SELECT max(as_of) FROM gl_balances WHERE company_id = :cid)
             AND (b.account LIKE '62%' OR b.account LIKE '60%')
           GROUP BY 1
        )
        SELECT k.id, k.name, k.inn, k.kind,
               coalesce(a.sales, 0), coalesce(a.purchases, 0),
               coalesce(a.paid_in, 0), coalesce(a.paid_out, 0),
               coalesce(a.docs, 0), a.last_doc,
               coalesce(b.ar, 0), coalesce(b.ap, 0),
               (SELECT count(*) FROM contracts c
                 WHERE c.company_id = :cid AND c.counterparty_id::text = k.id::text)
          FROM counterparties k
          LEFT JOIN agg  a ON a.counterparty_id = k.id
          LEFT JOIN debt b ON b.counterparty_id = k.id
         WHERE k.company_id = :cid
           AND (CAST(:q AS text) IS NULL OR lower(k.name) LIKE :q OR coalesce(k.inn,'') LIKE :q)
           AND (a.docs IS NOT NULL OR b.ar IS NOT NULL)
         ORDER BY coalesce(a.sales, 0) + coalesce(a.purchases, 0) DESC
         LIMIT :lim
    """), params)).all()

    return {"rows": [{
        "id": str(r[0]), "name": r[1], "inn": r[2], "kind": r[3],
        "sales": _num(r[4]), "purchases": _num(r[5]),
        "paidIn": _num(r[6]), "paidOut": _num(r[7]),
        "docs": r[8], "lastDoc": r[9],
        "receivable": _num(r[10]), "payable": _num(r[11]),
        "contracts": r[12],
    } for r in rows]}


@router.get("/counterparty")
async def counterparty_card(
    company_id: str,
    counterparty_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Карточка контрагента: реквизиты, договоры, документы, долг, помесячно."""
    cid = await assert_company_member(company_id, current_user, db)
    params = {"cid": str(cid), "kid": counterparty_id}

    k = (await db.execute(select(Counterparty).where(
        Counterparty.company_id == cid,
        Counterparty.id == counterparty_id))).scalar_one_or_none()
    if k is None:
        return {"error": "not_found"}

    docs = [{
        "id": str(r[0]), "date": r[1], "type": r[2], "label": DOC_LABELS.get(r[2], r[2]),
        "number": r[3], "amount": _num(r[4]), "vat": _num(r[5]),
        "contract": r[6], "periodStatus": r[7],
    } for r in (await db.execute(text("""
        SELECT d.id, d.date, d.doc_type, d.number, d.amount, d.vat_amount,
               c.type, d.period_status
          FROM accounting_docs d
          LEFT JOIN contracts c ON c.id = d.contract_id
         WHERE d.company_id = :cid AND d.counterparty_id::text = :kid
         ORDER BY d.date DESC LIMIT 300
    """), params)).all()]

    by_type = {r[0]: {"docs": r[1], "amount": _num(r[2])} for r in (await db.execute(text("""
        SELECT doc_type, count(*), sum(amount) FROM accounting_docs
         WHERE company_id = :cid AND counterparty_id::text = :kid GROUP BY 1
    """), params)).all()}

    months = [{"month": r[0], "sales": _num(r[1]), "purchases": _num(r[2]),
               "paid": _num(r[3])} for r in (await db.execute(text("""
        SELECT substr(date, 1, 7) m,
               sum(amount) FILTER (WHERE doc_type = 'sale'),
               sum(amount) FILTER (WHERE doc_type = 'purchase'),
               sum(amount) FILTER (WHERE doc_type IN ('bank_in', 'bank_out'))
          FROM accounting_docs
         WHERE company_id = :cid AND counterparty_id::text = :kid
         GROUP BY 1 ORDER BY 1
    """), params)).all()]

    # Что покупает (или что покупаем у него) — по строкам его документов реализации
    # и поступления. Позиция берётся из строки; справочник номенклатуры даёт единицу.
    items = [{"code": r[0], "name": r[1], "qty": _num(r[2]), "amount": _num(r[3]),
              "docs": r[4], "unit": r[5]} for r in (await db.execute(text("""
        WITH l AS (
          SELECT d.id doc, jsonb_array_elements(d.lines) ln
            FROM accounting_docs d
           WHERE d.company_id = :cid AND d.counterparty_id::text = :kid
             AND d.doc_type IN ('sale', 'purchase')
        ), x AS (
          -- Разворачивать JSONB и агрегировать в одном запросе Postgres не даёт:
          -- «subquery uses ungrouped column». Строки сначала становятся колонками,
          -- и лишь потом группируются; единица приезжает джойном справочника.
          SELECT doc, ln->>'code' code, ln->>'name' name,
                 (ln->>'qty')::numeric qty, (ln->>'amount')::numeric amount
            FROM l
        )
        SELECT x.code, max(x.name), sum(x.qty), sum(x.amount), count(DISTINCT x.doc),
               max(n.unit_label)
          FROM x LEFT JOIN nomenclature n
            ON n.company_id = :cid AND n.code = x.code
         GROUP BY x.code ORDER BY 4 DESC LIMIT 50
    """), params)).all()]

    debt = (await db.execute(text("""
        SELECT sum(CASE WHEN e.account_dt LIKE '62%' THEN e.amount ELSE 0 END)
             - sum(CASE WHEN e.account_kt LIKE '62%' THEN e.amount ELSE 0 END),
               sum(CASE WHEN e.account_kt LIKE '60%' THEN e.amount ELSE 0 END)
             - sum(CASE WHEN e.account_dt LIKE '60%' THEN e.amount ELSE 0 END)
          FROM gl_entries e JOIN accounting_docs d ON d.id = e.doc_id
         WHERE e.company_id = :cid AND d.counterparty_id::text = :kid
    """), params)).one()

    contracts = [{"id": str(r[0]), "number": r[1], "date": r[2], "type": r[3],
                  "kind": r[4], "closed": r[5], "docs": r[6]} for r in (await db.execute(text("""
        SELECT c.id, c.number, c.date, c.type, c.kind, c.is_closed,
               (SELECT count(*) FROM accounting_docs d WHERE d.contract_id = c.id)
          FROM contracts c
         WHERE c.company_id = :cid AND c.counterparty_id::text = :kid
         ORDER BY c.date DESC NULLS LAST
    """), params)).all()]

    return {
        "id": str(k.id), "name": k.name, "inn": k.inn, "kpp": k.kpp, "ogrn": k.ogrn,
        "kind": k.kind, "fullName": k.full_name, "address": k.legal_address,
        "phone": k.phone, "email": k.email, "director": k.director_name,
        "bankAccount": k.bank_account, "bankName": k.bank_name, "okved": k.okved,
        "receivable": _num(debt[0]), "payable": _num(debt[1]),
        "byType": by_type, "months": months, "items": items,
        "contracts": contracts, "docs": docs,
    }


# ── «Данные»: источники и качество ───────────────────────────────────────────
# Данные — первый слой, с которого всё начинается: пока не видно, ОТКУДА цифры и
# сходятся ли они между собой, доверять витринам нельзя. У компании без объектов
# источник один — бухгалтерия клиента, поэтому и проверки идут по ней.

@router.get("/sources")
async def sources(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Что и когда приехало в пространство: наборы данных с объёмом и периодом."""
    cid = await assert_company_member(company_id, current_user, db)

    async def stat(model, date_col=None):
        q = select(func.count()).select_from(model).where(model.company_id == cid)
        n = (await db.execute(q)).scalar_one()
        first = last = None
        if date_col is not None and n:
            first, last = (await db.execute(
                select(func.min(date_col), func.max(date_col))
                .where(model.company_id == cid))).one()
        return n, first, last

    entries_n, first, last = await stat(GlEntry, GlEntry.entry_date)
    accounts_n, _, _ = await stat(GlAccount)
    periods_n, _, _ = await stat(Period)

    # Документы — ПО ВИДАМ: «1500 документов» ничего не говорит, а «390 счетов
    # покупателю и 485 регламентных операций» сразу показывает, какой срез приехал.
    docs_by_kind = {
        t: n for t, n in (await db.execute(
            select(AccountingDoc.doc_type, func.count())
            .where(AccountingDoc.company_id == cid)
            .group_by(AccountingDoc.doc_type))).all()
    }
    refs_by_kind = {
        k: n for k, n in (await db.execute(
            select(GlReference.kind, func.count())
            .where(GlReference.company_id == cid)
            .group_by(GlReference.kind))).all()
    }

    loaded = (await db.execute(
        select(func.max(GlEntry.created_at)).where(GlEntry.company_id == cid))).scalar_one()

    async def count_of(model) -> int:
        return (await db.execute(select(func.count()).select_from(model)
                                 .where(model.company_id == cid))).scalar_one()

    turnovers_n = await count_of(GlTurnover)
    balances_n = await count_of(GlBalance)
    vat_n = await count_of(VatEntry)
    payments_n = await count_of(InvoicePayment)

    return {
        # Источник пока один — разовая выгрузка бухгалтерии. Дальше здесь появится
        # коннектор к живой базе, и признак `kind` станет различать их.
        "sources": [{
            "kind": "1c_dt",
            "name": "Бухгалтерия клиента (выгрузка .dt)",
            "loadedAt": loaded.isoformat() if loaded else None,
            "periodFrom": first.isoformat() if first else None,
            "periodTo": last.isoformat() if last else None,
            "datasets": [
                {"key": "gl_accounts", "label": "План счетов", "records": accounts_n},
                {"key": "gl_entries", "label": "Проводки", "records": entries_n},
                {"key": "periods", "label": "Периоды", "records": periods_n},
                # Аналитика: приезжает виртуальными таблицами регистра, поэтому
                # отдельными наборами, а не колонками проводки.
                {"key": "gl_turnovers", "label": "Обороты с аналитикой", "records": turnovers_n},
                {"key": "gl_balances", "label": "Сальдо счетов", "records": balances_n},
                {"key": "vat_entries", "label": "Счета-фактуры и НДС", "records": vat_n},
                {"key": "invoice_payments", "label": "Оплата счетов", "records": payments_n},
            ],
            "documents": [
                {"key": k, "label": DOC_LABELS.get(k, k), "records": n}
                for k, n in sorted(docs_by_kind.items(), key=lambda kv: -kv[1])
            ],
            "references": [
                {"key": k, "label": REF_LABELS.get(k, k), "records": n}
                for k, n in sorted(refs_by_kind.items(), key=lambda kv: -kv[1])
            ],
        }],
    }


@router.get("/quality")
async def quality(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Проверки данных: сходимость с регистром и находки, требующие решения.

    Главная проверка — выручка документов против оборота 90.01.1: именно на ней
    ловится, что часть документов посчитана без НДС «сверху» (при загрузке это уже
    учтено, но живой коннектор может привезти иное).
    """
    cid = await assert_company_member(company_id, current_user, db)
    checks: list[dict[str, Any]] = []

    def add(key, label, status, value, hint, detail=None):
        checks.append({"key": key, "label": label, "status": status,
                       "value": value, "hint": hint, "detail": detail})

    revenue = await _turnover(db, cid, kt=REVENUE_KT)
    sales_total = _num((await db.execute(
        select(func.coalesce(func.sum(AccountingDoc.amount), 0))
        .where(AccountingDoc.company_id == cid,
               AccountingDoc.doc_type == "sale"))).scalar_one())
    diff = round(revenue - sales_total, 2)
    add("revenue_match", "Выручка документов = оборот 90.01.1",
        "ok" if abs(diff) < 0.02 else "error",
        "%.2f ₽" % diff if diff else "сходится",
        "Расхождение означает, что часть документов посчитана по другому правилу НДС")

    # Считаем только те виды, у которых контрагент есть по природе: у регламентной
    # операции закрытия и операции вручную его не бывает вовсе, и без этого условия
    # проверка показывала полтысячи «нарушений», которых нет.
    # Набор тот же, что у «Базы пространства» (space_data_model): один показатель на
    # двух экранах обязан считаться по одному правилу, иначе продукт спорит сам с собой.
    WITH_COUNTERPARTY = ("sale", "purchase", "invoice_out", "invoice_in",
                         "vat_invoice_out", "vat_invoice_in", "act_recon",
                         "bank_in", "bank_out")
    no_inn = (await db.execute(
        select(func.count()).select_from(AccountingDoc)
        .where(AccountingDoc.company_id == cid,
               AccountingDoc.doc_type.in_(WITH_COUNTERPARTY),
               (AccountingDoc.counterparty_inn.is_(None))
               | (AccountingDoc.counterparty_inn == "")))).scalar_one()
    add("docs_without_inn", "Документы без ИНН контрагента",
        "ok" if not no_inn else "warn", no_inn,
        "Без ИНН документ нельзя связать с карточкой контрагента")

    # Дубли «номер + дата»: в бухгалтерии номер НЕ уникален (два документа №1-2212
    # от 22.12.2023 на разных контрагентов), и ключ по номеру склеил бы их.
    dup = (await db.execute(
        select(func.count()).select_from(
            select(AccountingDoc.doc_type, AccountingDoc.number, AccountingDoc.date)
            .where(AccountingDoc.company_id == cid)
            .group_by(AccountingDoc.doc_type, AccountingDoc.number, AccountingDoc.date)
            .having(func.count() > 1).subquery()))).scalar_one()
    add("duplicate_numbers", "Номер+дата дважды в одном виде",
        "ok" if not dup else "warn", dup,
        "Нормально для бухгалтерии: ключ документа включает ещё и контрагента")

    open_periods = (await db.execute(
        select(func.count()).select_from(Period)
        .where(Period.company_id == cid, Period.status == "open"))).scalar_one()
    add("open_periods", "Незакрытые периоды",
        "ok" if not open_periods else "warn", open_periods,
        "Цифры открытого месяца ещё поедут: эталоном считается только закрытый")

    headless = (await db.execute(
        select(func.count()).select_from(GlEntry)
        .where(GlEntry.company_id == cid,
               GlEntry.account_dt.is_(None), GlEntry.account_kt.is_(None)))).scalar_one()
    add("entries_no_accounts", "Проводки без корреспонденции",
        "ok" if not headless else "error", headless,
        "Проводка без счетов не попадёт ни в один оборот")

    # Связь проводки с документом — то, чем оборот разворачивается до первички и
    # чем проводка получает контрагента. Показываем долю, а не факт наличия текста:
    # текст есть у всех 4950, а полезна именно ссылка.
    total_e, linked_e = (await db.execute(
        select(func.count(), func.count(GlEntry.doc_id))
        .where(GlEntry.company_id == cid))).one()
    add("entries_linked", "Проводка связана с документом",
        "ok" if linked_e >= total_e * 0.9 else "warn",
        "%d из %d" % (linked_e, total_e),
        "Несвязанные — зарплатный контур и виды документов, которых нет в срезе")

    lock = (await db.execute(
        select(func.max(GlReference.code))
        .where(GlReference.company_id == cid, GlReference.kind == "period_locks"))).scalar_one()
    if lock:
        # Месяцы, закрытые у нас позже даты запрета: в бухгалтерии их ещё могут править,
        # значит эталоном они пока не являются.
        y, m = int(lock[:4]), int(lock[5:7])
        late = (await db.execute(
            select(func.count()).select_from(Period).where(
                Period.company_id == cid, Period.status == "closed",
                (Period.year > y) | ((Period.year == y) & (Period.month > m)))))            .scalar_one()
        add("lock_vs_closed", "Закрыто регламентно, но запрет не двинут",
            "ok" if not late else "info", late,
            "Месяц закрыт операциями закрытия, а запрет стоит на %s: до него бухгалтерия ещё принимает правки" % lock)

    errors = sum(1 for c in checks if c["status"] == "error")
    warns = sum(1 for c in checks if c["status"] == "warn")
    return {"checks": checks, "errors": errors, "warnings": warns,
            "ok": sum(1 for c in checks if c["status"] == "ok")}


@router.get("/model")
async def model(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Модель данных бухгалтерии: слои, звёздная схема, качество полей.

    Подача та же, что у сетевых профилей («Нормализация» РусГидро и ГИГ): слои
    приёма L1→L4, факт с мерами, измерения с кардинальностью и заполнением. Отличается
    только предметная область: там факт — зарядная сессия, здесь — проводка регистра.
    """
    cid = await assert_company_member(company_id, current_user, db)

    entries = (await db.execute(select(func.count()).select_from(GlEntry)
                                .where(GlEntry.company_id == cid))).scalar_one()
    docs = (await db.execute(select(func.count()).select_from(AccountingDoc)
                             .where(AccountingDoc.company_id == cid))).scalar_one()
    accounts = (await db.execute(select(func.count()).select_from(GlAccount)
                                 .where(GlAccount.company_id == cid))).scalar_one()
    refs = (await db.execute(select(func.count()).select_from(GlReference)
                             .where(GlReference.company_id == cid))).scalar_one()
    closed = (await db.execute(select(func.count()).select_from(Period)
                               .where(Period.company_id == cid,
                                      Period.status == "closed"))).scalar_one()
    first, last = (await db.execute(
        select(func.min(GlEntry.entry_date), func.max(GlEntry.entry_date))
        .where(GlEntry.company_id == cid))).one()

    # L1 и L4 материальны: приём выгрузки и снимок эталона закрытого месяца.
    intakes = (await db.execute(select(func.count()).select_from(SourceFile)
                                .where(SourceFile.company_id == cid))).scalar_one()
    snapshots = (await db.execute(select(func.count()).select_from(ReferenceSnapshot)
                                  .where(ReferenceSnapshot.company_id == cid))).scalar_one()
    analytics = 0
    for m in (GlTurnover, GlBalance, VatEntry, InvoicePayment):
        analytics += (await db.execute(select(func.count()).select_from(m)
                                       .where(m.company_id == cid))).scalar_one()

    layers = [
        # L1 у офиса ПОКА НЕ МАТЕРИАЛИЗОВАН: данные залиты скриптом снаружи, записи о
        # приёме (SourceFile / RawBatchRecord) в базе нет. Рисовать здесь «1 выгрузку»
        # значило бы показывать то, чего нет: сетевые в такой ситуации честно ставят
        # `status: direct` (см. analytics_service.charge_model).
        {"key": "l1", "code": "L1 · RAW", "title": "Приём выгрузки",
         "desc": "файл бухгалтерии с отпечатком: что и когда приняли",
         "records": intakes, "unit": "приёмов", "tone": "raw",
         **({"status": "direct"} if not intakes else {})},
        {"key": "l2", "code": "L2 · CLEAN", "title": "Нормализованный слой",
         "desc": "проводки, документы, справочники",
         "records": entries + docs + accounts + refs, "unit": "записей", "tone": "clean"},
        # Аналитика — свой слой: гранулярность у неё не проводки, а месяц и субконто,
        # и приезжает она отдельными наборами (виртуальные таблицы регистра).
        {"key": "l2a", "code": "L2 · ANALYTIC", "title": "Аналитика расчётов и налога",
         "desc": "обороты с субконто, сальдо счетов, счета-фактуры, оплата счетов",
         "records": analytics, "unit": "записей", "tone": "clean",
         **({"status": "planned"} if not analytics else {})},
        {"key": "l3", "code": "L3 · EXPORT", "title": "Обороты и разрезы",
         "desc": "оборотка, продажи, услуги, периоды, взаиморасчёты",
         "records": None, "unit": "", "tone": "export"},
        {"key": "l4", "code": "L4 · 1C_REF", "title": "Снимки закрытых периодов",
         "desc": "состав и контрольная сумма месяца, который бухгалтерия не меняет",
         "records": snapshots, "unit": "снимков", "tone": "ref",
         **({"status": "planned"} if not snapshots else {})},
    ]

    async def dimension(key, label, field, column, canonical, grain=None):
        rows = (await db.execute(
            select(column, func.count()).where(GlEntry.company_id == cid, column.is_not(None))
            .group_by(column).order_by(func.count().desc()).limit(5))).all()
        card = (await db.execute(
            select(func.count(func.distinct(column))).where(GlEntry.company_id == cid))).scalar_one()
        filled = (await db.execute(
            select(func.count()).select_from(GlEntry)
            .where(GlEntry.company_id == cid, column.is_not(None)))).scalar_one()
        return {
            "key": key, "label": label, "field": field, "cardinality": card,
            "fill_pct": round(filled * 100 / entries, 1) if entries else 0,
            "canonical": canonical, "grain": grain,
            "members": [{"label": str(v), "count": n} for v, n in rows],
        }

    dimensions = [
        await dimension("account_dt", "Счёт дебета", "gl_entries.account_dt",
                        GlEntry.account_dt, True, "код счёта"),
        await dimension("account_kt", "Счёт кредита", "gl_entries.account_kt",
                        GlEntry.account_kt, True, "код счёта"),
        await dimension("doc_kind", "Вид документа", "gl_entries.doc_kind",
                        GlEntry.doc_kind, False, "регистратор проводки"),
        await dimension("period_year", "Год периода", "gl_entries.period_year",
                        GlEntry.period_year, True, "год"),
        await dimension("period_month", "Месяц периода", "gl_entries.period_month",
                        GlEntry.period_month, True, "месяц"),
    ]

    # Контрагент — измерение ЧЕРЕЗ ДОКУМЕНТ: в самом регистре его нет (субконто
    # недоступно), но проводка теперь знает свой документ, а документ — контрагента.
    linked = (await db.execute(
        select(func.count()).select_from(GlEntry)
        .where(GlEntry.company_id == cid, GlEntry.doc_id.is_not(None)))).scalar_one()
    if linked:
        top_cp = (await db.execute(
            select(AccountingDoc.counterparty_name, func.count())
            .join(GlEntry, GlEntry.doc_id == AccountingDoc.id)
            .where(GlEntry.company_id == cid, AccountingDoc.counterparty_name != "")
            .group_by(AccountingDoc.counterparty_name)
            .order_by(func.count().desc()).limit(5))).all()
        cp_card = (await db.execute(
            select(func.count(func.distinct(AccountingDoc.counterparty_inn)))
            .join(GlEntry, GlEntry.doc_id == AccountingDoc.id)
            .where(GlEntry.company_id == cid))).scalar_one()
        cp_filled = (await db.execute(
            select(func.count()).select_from(GlEntry)
            .join(AccountingDoc, GlEntry.doc_id == AccountingDoc.id)
            .where(GlEntry.company_id == cid,
                   AccountingDoc.counterparty_inn.is_not(None),
                   AccountingDoc.counterparty_inn != ""))).scalar_one()
        dimensions.append({
            "key": "counterparty", "label": "Контрагент",
            "field": "accounting_docs.counterparty_inn", "cardinality": cp_card,
            "fill_pct": round(cp_filled * 100 / entries, 1) if entries else 0,
            "canonical": True, "grain": "через документ проводки",
            "members": [{"label": v, "count": n} for v, n in top_cp]})

    total = await _turnover(db, cid)
    revenue = await _turnover(db, cid, kt=REVENUE_KT)
    fact = {
        "table": "gl_entries", "name": "Проводка регистра бухгалтерии",
        "grain": "одна проводка: дата + корреспонденция счетов + сумма",
        "rows": entries,
        "period": {"from": first.isoformat() if first else None,
                   "to": last.isoformat() if last else None},
        "measures": [
            {"key": "amount", "label": "Оборот всего", "value": round(total, 2),
             "unit": "₽", "agg": "SUM"},
            {"key": "revenue", "label": "Выручка (Кт 90.01.1)", "value": round(revenue, 2),
             "unit": "₽", "agg": "SUM"},
            {"key": "count", "label": "Проводок", "value": entries, "unit": "", "agg": "COUNT"},
        ],
    }

    # Доля проводок, чей счёт дебета реально нашёлся в плане счетов.
    known = (await db.execute(
        select(func.count()).select_from(GlEntry)
        .where(GlEntry.company_id == cid, GlEntry.account_dt.is_not(None),
               GlEntry.account_dt.in_(select(GlAccount.code)
                                      .where(GlAccount.company_id == cid))))).scalar_one()
    with_dt = (await db.execute(
        select(func.count()).select_from(GlEntry)
        .where(GlEntry.company_id == cid, GlEntry.account_dt.is_not(None)))).scalar_one()
    account_coverage = round(known * 100 / with_dt, 1) if with_dt else 0.0

    # Качество полей: заполненность там, где пустое значение осмысленно проверять.
    async def fill(model_cls, column, label, role):
        total_n = (await db.execute(select(func.count()).select_from(model_cls)
                                    .where(model_cls.company_id == cid))).scalar_one()
        ok = (await db.execute(select(func.count()).select_from(model_cls)
                               .where(model_cls.company_id == cid, column.is_not(None),
                                      column != ""))).scalar_one()
        return {"field": str(column).split(".")[-1], "label": label, "role": role,
                "fill_pct": round(ok * 100 / total_n, 1) if total_n else 0}

    quality = {
        "fields": [
            await fill(GlEntry, GlEntry.account_dt, "Счёт дебета", "измерение"),
            await fill(GlEntry, GlEntry.account_kt, "Счёт кредита", "измерение"),
            await fill(GlEntry, GlEntry.content, "Содержание", "атрибут"),
            await fill(AccountingDoc, AccountingDoc.counterparty_inn, "ИНН контрагента", "ключ связи"),
            await fill(AccountingDoc, AccountingDoc.number, "Номер документа", "атрибут"),
        ],
        # «Канонизация» здесь — сведение к справочнику: счёт к плану счетов,
        # контрагент к карточке по ИНН, номенклатура к своему справочнику.
        "canonicalization": [
            # Покрытие СЧИТАЕТСЯ, а не объявляется: раньше здесь стояло 100 % константой,
            # и проверка не заметила бы счёта, которого нет в плане счетов.
            {"name": "Счёт → план счетов", "from": "код счёта", "to": "gl_accounts",
             "members": accounts, "coverage_pct": account_coverage},
            {"name": "Контрагент → карточка", "from": "ИНН документа", "to": "counterparties",
             "members": (await db.execute(select(func.count()).select_from(Counterparty)
                                          .where(Counterparty.company_id == cid))).scalar_one(),
             "coverage_pct": None},
            {"name": "Справочники учёта", "from": "склады, статьи, банки, лица",
             "to": "gl_references", "members": refs, "coverage_pct": None},
        ],
    }

    return {"rows": entries, "l1_files": intakes, "layers": layers, "fact": fact,
            "dimensions": dimensions, "quality": quality}


# Наборы данных нормализованного слоя: у сетевых профилей пункт меню на канал приёма,
# у офиса — на набор, приехавший из бухгалтерии. Для каждого витрина одинаковая:
# объём, период, ключ связи, заполнение полей, топ-значения.
DATASETS = {
    "entries": ("Проводки", GlEntry, "дата + корреспонденция счетов"),
    "docs": ("Документы", AccountingDoc, "вид + номер + дата + контрагент"),
    "counterparties": ("Контрагенты", Counterparty, "ИНН"),
    "nomenclature": ("Номенклатура", NomenclatureItem, "код номенклатуры"),
    "refs": ("Справочники учёта", GlReference, "вид + наименование"),
}


@router.get("/dataset")
async def dataset(
    company_id: str,
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Витрина одного набора данных: сколько, за какой период, чем связан, чем полон."""
    cid = await assert_company_member(company_id, current_user, db)
    if key not in DATASETS:
        return {"error": "неизвестный набор"}
    label, model, link = DATASETS[key]

    total = (await db.execute(select(func.count()).select_from(model)
                              .where(model.company_id == cid))).scalar_one()

    # Поля, по которым осмысленно смотреть заполнение и разброс значений.
    FIELDS: dict[str, list[tuple]] = {
        "entries": [(GlEntry.account_dt, "Счёт дебета"), (GlEntry.account_kt, "Счёт кредита"),
                    (GlEntry.doc_kind, "Вид документа"), (GlEntry.content, "Содержание")],
        "docs": [(AccountingDoc.doc_type, "Вид документа"),
                 (AccountingDoc.counterparty_inn, "ИНН контрагента"),
                 (AccountingDoc.number, "Номер"), (AccountingDoc.date, "Дата")],
        "counterparties": [(Counterparty.inn, "ИНН"), (Counterparty.kpp, "КПП"),
                           (Counterparty.legal_address, "Юридический адрес"),
                           (Counterparty.phone, "Телефон"), (Counterparty.email, "Почта")],
        "nomenclature": [(NomenclatureItem.code, "Код"), (NomenclatureItem.unit, "Единица"),
                         (NomenclatureItem.unit_label, "Вид номенклатуры")],
        "refs": [(GlReference.kind, "Вид справочника"), (GlReference.code, "Код")],
    }

    fields = []
    for column, flabel in FIELDS[key]:
        filled = (await db.execute(
            select(func.count()).select_from(model)
            .where(model.company_id == cid, column.is_not(None), column != ""))).scalar_one()
        distinct = (await db.execute(
            select(func.count(func.distinct(column))).where(model.company_id == cid))).scalar_one()
        fields.append({
            "field": str(column).split(".")[-1], "label": flabel,
            "fill_pct": round(filled * 100 / total, 1) if total else 0,
            "distinct": distinct,
        })

    # Разбивка: по чему набор делится в первую очередь.
    GROUP = {"entries": GlEntry.doc_kind, "docs": AccountingDoc.doc_type,
             "counterparties": Counterparty.type, "nomenclature": NomenclatureItem.unit_label,
             "refs": GlReference.kind}
    top = [
        {"label": DOC_LABELS.get(str(v), REF_LABELS.get(str(v), str(v) if v else "—")),
         "count": n}
        for v, n in (await db.execute(
            select(GROUP[key], func.count()).where(model.company_id == cid)
            .group_by(GROUP[key]).order_by(func.count().desc()).limit(12))).all()
    ]

    period = {"from": None, "to": None}
    if key == "entries":
        f, t = (await db.execute(select(func.min(GlEntry.entry_date), func.max(GlEntry.entry_date))
                                 .where(GlEntry.company_id == cid))).one()
        period = {"from": f.isoformat() if f else None, "to": t.isoformat() if t else None}
    elif key == "docs":
        f, t = (await db.execute(select(func.min(AccountingDoc.date), func.max(AccountingDoc.date))
                                 .where(AccountingDoc.company_id == cid))).one()
        period = {"from": f, "to": t}

    return {"key": key, "label": label, "table": model.__tablename__, "records": total,
            "link": link, "period": period, "fields": fields, "top": top}


# ── Взаиморасчёты и налог: аналитический слой ────────────────────────────────
# Проводка не знает, ЧЕЙ долг: субконто в основной таблице регистра через COM
# недоступно. Аналитика приезжает отдельными наборами — сальдо счёта с субконто
# (`gl_balances`) и обороты Дт-Кт с субконто помесячно (`gl_turnovers`), — и
# отвечает на вопросы, которых у слоя раньше не было вовсе.


@router.get("/settlements")
async def settlements(
    company_id: str,
    kind: str = Query("receivable", pattern="^(receivable|payable|other)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Кто сколько должен: сальдо расчётов по контрагентам и договорам.

    Берётся ИЗ САЛЬДО источника, а не считается из наших проводок: остаток
    накоплен всей историей регистра, включая периоды до выгрузки, и зачёты
    авансов живут только там.
    """
    cid = await assert_company_member(company_id, current_user, db)
    prefix = {"receivable": "62", "payable": "60", "other": "76"}[kind]

    as_of = (await db.execute(
        select(func.max(GlBalance.as_of)).where(GlBalance.company_id == cid))).scalar_one_or_none()
    if as_of is None:
        return {"asOf": None, "rows": [], "totals": {"debit": 0, "credit": 0}, "months": []}

    rows = (await db.execute(
        select(GlBalance.account, GlBalance.account_name, GlBalance.sub1, GlBalance.sub2,
               GlBalance.debit, GlBalance.credit)
        .where(GlBalance.company_id == cid, GlBalance.as_of == as_of,
               GlBalance.account.like(f"{prefix}%"))
        .order_by((GlBalance.debit + GlBalance.credit).desc()))).all()

    # Динамика расчётов помесячно: обе стороны корреспонденции, потому что долг
    # растёт по дебету счёта расчётов и гасится по кредиту.
    months = (await db.execute(text("""
        SELECT period_year, period_month,
               sum(amount) FILTER (WHERE account_dt LIKE :p) AS grew,
               sum(amount) FILTER (WHERE account_kt LIKE :p) AS closed
          FROM gl_turnovers
         WHERE company_id = :cid AND (account_dt LIKE :p OR account_kt LIKE :p)
         GROUP BY 1, 2 ORDER BY 1, 2
    """), {"cid": str(cid), "p": f"{prefix}%"})).all()

    return {
        "asOf": as_of.isoformat(),
        "rows": [{
            "account": r[0], "accountName": r[1],
            "counterparty": r[2], "contract": r[3],
            "debit": _num(r[4]), "credit": _num(r[5]),
            "net": _num(r[4]) - _num(r[5]),
        } for r in rows],
        "totals": {"debit": sum(_num(r[4]) for r in rows),
                   "credit": sum(_num(r[5]) for r in rows)},
        "months": [{"month": f"{m[0]}-{m[1]:02d}", "grew": _num(m[2]), "closed": _num(m[3])}
                   for m in months],
    }


@router.get("/vat")
async def vat(
    company_id: str,
    kind: str = Query("issued", pattern="^(issued|received|claimed)$"),
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Книга продаж, книга покупок и предъявленный НДС.

    Три набора одной таблицы: счета-фактуры выданные и полученные — журнал учёта,
    `claimed` — движение налога, предъявленного поставщиком. Суммы журнала ВЫШЕ
    выручки продаж: туда входят авансовые счета-фактуры, у которых отгрузки ещё нет.
    """
    cid = await assert_company_member(company_id, current_user, db)

    q = select(VatEntry).where(VatEntry.company_id == cid, VatEntry.kind == kind)
    if date_from:
        q = q.where(VatEntry.doc_date >= date_from)
    if date_to:
        q = q.where(VatEntry.doc_date <= date_to)

    # Считаем по колонкам ПОДЗАПРОСА: суммы по самой таблице тянут её в FROM рядом
    # с подзапросом, и вместо 295 счетов-фактур приезжает их произведение на 1429.
    sub = q.subquery()
    total, amount, tax = (await db.execute(
        select(func.count(), func.sum(sub.c.amount), func.sum(sub.c.vat))
        .select_from(sub))).one()

    rows = (await db.execute(q.order_by(VatEntry.doc_date.desc()).limit(limit))).scalars().all()

    # Помесячно — как в декларации: налог по периодам, а не одной цифрой за всё.
    # Группировка по позиции, а не по выражению: аргументы substr едут параметрами,
    # и Postgres не признаёт GROUP BY substr($5,$6) тем же выражением, что в SELECT.
    months = (await db.execute(
        select(func.substr(VatEntry.doc_date, 1, 7), func.count(),
               func.sum(VatEntry.amount), func.sum(VatEntry.vat))
        .where(VatEntry.company_id == cid, VatEntry.kind == kind,
               VatEntry.doc_date.isnot(None))
        .group_by(text("1")).order_by(text("1")))).all()

    kinds = dict((k, (n, _num(a), _num(v))) for k, n, a, v in (await db.execute(
        select(VatEntry.kind, func.count(), func.sum(VatEntry.amount), func.sum(VatEntry.vat))
        .where(VatEntry.company_id == cid).group_by(VatEntry.kind))).all())

    return {
        "total": total, "amount": _num(amount), "vat": _num(tax),
        "kinds": [{"kind": k, "count": v[0], "amount": v[1], "vat": v[2]}
                  for k, v in sorted(kinds.items())],
        "months": [{"month": m[0], "count": m[1], "amount": _num(m[2]), "vat": _num(m[3])}
                   for m in months],
        "rows": [{
            "date": e.doc_date, "number": e.number,
            "counterparty": e.counterparty_name, "inn": e.counterparty_inn,
            "kpp": e.counterparty_kpp, "amount": _num(e.amount), "vat": _num(e.vat),
            "rate": e.rate, "invoice": e.invoice_title, "registrar": e.registrar,
            "operationCode": e.operation_code,
        } for e in rows],
    }
