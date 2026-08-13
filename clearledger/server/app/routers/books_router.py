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
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import (
    AccountingDoc, Contract, Counterparty, DocRequest, ExportAdjustment, ExportRule,
    GlAccount, GlBalance, GlEntry, GlReference,
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
    "payroll_accrual": "Начисление зарплаты",
    "payroll_payment": "Ведомость на выплату",
    "vat_book_in": "Формирование записей книги покупок",
    "vat_book_out": "Формирование записей книги продаж",
    "debt_correction": "Корректировка долга",
    "goods_writeoff": "Списание товаров",
    "tax_notice": "Уведомление об исчисленных налогах",
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
    ("warehouse", "Склад", ["demand_note", "goods_writeoff"]),
    ("recon", "Сверка", ["act_recon"]),
    # Зарплата — свой участок: у него другой предмет (человек, а не сделка), другие
    # счета учёта (70, 68.01, 69) и другой режим доступа — это персональные данные.
    ("payroll", "Зарплата", ["payroll_accrual", "payroll_payment"]),
    # Служебные документы отдельно: пять сотен регламентных операций в общем списке
    # хоронят первичку, ради которой реестр и открывают.
    # Книги покупок и продаж и корректировки долга — тоже закрытие периода: они не
    # первичка, а способ, которым бухгалтерия сводит налог и расчёты.
    ("closing", "Закрытие периода", ["closing_op", "manual_entry", "vat_book_in",
                                     "vat_book_out", "debt_correction", "tax_notice"]),
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


async def _closed_months(db: AsyncSession, cid) -> set[tuple[int, int]]:
    """Закрытые месяцы компании.

    `accounting_docs.period_status` — кэш НА МОМЕНТ ЗАГРУЗКИ: месяц закрывают позже, и
    у 3143 документов пилота в колонке стояло «открыт», хотя период давно закрыт.
    Признак неизменяемости обязан считаться от реестра периодов.
    """
    rows = (await db.execute(
        select(Period.year, Period.month)
        .where(Period.company_id == cid, Period.status == "closed"))).all()
    return {(y, m) for y, m in rows}


def _period_status(date: str | None, closed: set[tuple[int, int]]) -> str:
    if not date or len(date) < 7:
        return "open"
    try:
        return "closed" if (int(date[:4]), int(date[5:7])) in closed else "open"
    except ValueError:
        return "open"


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


def _doc_amounts(doc, line_kind: str | None) -> dict[str, float]:
    """Сумма и НДС документа под выбранным разрезом строк.

    Без разреза — из шапки (она и есть выручка, сходящаяся с 90.01.1). С разрезом —
    сумма своих строк: документ несёт и товар, и услугу, и показывать его целиком в
    списке «услуги» значит завышать разрез на стоимость товара.
    """
    if not line_kind:
        return {"amount": _num(doc.amount), "vat": _num(doc.vat_amount)}
    picked = [l for l in (doc.lines or []) if (l.get("kind") or "goods") == line_kind]
    return {
        "amount": round(sum(_num(l.get("amount")) for l in picked), 2),
        "vat": round(sum(_num(l.get("vat")) for l in picked), 2),
    }


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
        # Тай-брейкер по id нужен и здесь: без него страницы разреза перекрываются
        # ровно так же, как перекрывались в основной ветке.
        picked = [d for d in (await db.execute(
            q.order_by(AccountingDoc.date.desc(), AccountingDoc.id))).scalars()
            if any((l.get("kind") or "goods") == line_kind for l in (d.lines or []))]
        total = len(picked)
        rows = picked[offset:offset + limit]
    else:
        total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        # Тай-брейкер по id обязателен: дата хранится без времени, в одном дне бывает
        # два десятка документов, и без него страницы перекрываются — на пилоте два
        # документа приезжали дважды, а два не приезжали вовсе.
        rows = (await db.execute(
            q.order_by(AccountingDoc.date.desc(), AccountingDoc.id)
            .limit(limit).offset(offset))).scalars().all()

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

    closed_months = await _closed_months(db, cid)

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
        # Сколько показанных счетов вообще имеют запись в регистре оплат: без этой
        # цифры «не оплачено» читается как факт, а это просто отсутствие данных.
        "paidKnown": len(paid),
        "paidTotal": len(doc_ids),
        "rows": [{
            # id нужен просмотрщику: по номеру с датой документ не найти —
            # пара не уникальна (два разных №1-2212 от 22.12.2023).
            "id": str(d.id),
            "date": d.date, "number": d.number, "type": d.doc_type,
            "label": DOC_LABELS.get(d.doc_type, d.doc_type),
            "section": SECTION_OF.get(d.doc_type),
            "counterparty": d.counterparty_name, "inn": d.counterparty_inn,
            # Ссылка на карточку: из реестра человек идёт к контрагенту, а не
            # выписывает его имя, чтобы найти в справочнике. null — документ ещё
            # не сведён (регламентные операции контрагента не имеют вовсе).
            "counterpartyId": str(d.counterparty_id) if d.counterparty_id else None,
            # В разрезе «товары»/«услуги» сумма считается ПО СТРОКАМ разреза, а не
            # берётся из шапки: раньше реестр показывал полную сумму документа, и
            # «Обзор» с «Документами» по одному и тому же множеству давали разные
            # цифры — завышенная уходила ещё и в Excel.
            **_doc_amounts(d, line_kind),
            # Назначение платежа и вид операции: без них банковская строка — только сумма.
            "operation": d.operation_type,
            "status": d.status_1c,
            # Закрытый период — половина ответа аудитору: документ уже не переписать.
            "periodStatus": _period_status(d.date, closed_months),
            "lines": len(d.lines or []),
            # Только у счетов покупателям. null здесь означает «оплата НЕИЗВЕСТНА»,
            # а не «не оплачен»: связь «счёт ↔ платёж» живёт в регистре «Оплата
            # счетов», и он покрывает 108 счетов из 390. Пока отсутствие записи
            # считалось нулём, витрина показывала 282 счёта как неоплаченные и
            # выводила из этого несуществующий долг в сотню миллионов.
            "paid": paid.get(d.id) if d.doc_type == "invoice_out" else None,
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
    # Товар и услуга — РАЗРЕЗ одного продукта, а не два продукта: доля услуг в выручке
    # нужна на общем обзоре, и считать её вторым запросом с `line_kind` значило бы
    # гонять ту же выборку дважды. Суммы берутся по строкам, поэтому с итогом по
    # шапкам сходятся не до копейки — у части документов шапка и состав разошлись
    # (см. НДС «сверху» в docs/REVENUE.md).
    by_kind: dict[str, float] = {"goods": 0.0, "service": 0.0}
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
                                  "amount": 0.0, "docs": 0, "first": None, "last": None})
        c["amount"] += amount
        c["docs"] += 1
        # Крайние даты покупателя: по ним видно молчащих — тех, кто из списка не
        # исчез, но последний раз покупал полгода назад. Без даты «молчащий» и
        # «активный» в реестре выглядят одинаково.
        if d.date:
            c["first"] = d.date if not c["first"] else min(c["first"], d.date)
            c["last"] = d.date if not c["last"] else max(c["last"], d.date)

        for ln in (d.lines or []):
            # Разрез по типу строки: один документ несёт и товары, и услуги.
            lkind = ln.get('kind') or 'goods'
            if line_kind and lkind != line_kind:
                continue
            by_kind[lkind if lkind in by_kind else 'goods'] += _num(ln.get('amount'))
            # Позиция — по КОДУ номенклатуры: имя в строке документа пишется как
            # угодно, а код тот же, что в справочнике, и по нему открывается карточка.
            ikey = (ln.get("code") or "").strip() or ln.get("name") or "—"
            it = by_item.setdefault(ikey,
                                    {"code": (ln.get("code") or "").strip() or None,
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
        "byKind": by_kind,
        "topClients": clients[:top],
        "topItems": items[:top],
    }


@router.get("/revenue")
async def revenue(
    company_id: str,
    kind: str = Query("all", pattern="^(all|goods|service)$"),
    top: int = Query(15, ge=1, le=500),
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Реализация: динамика, покупатели, что продаём.

    `kind` — разрез, а не отдельная витрина: `all` считает документ целиком (это и
    есть выручка, сходящаяся с 90.01.1), `goods`/`service` — только свои строки.
    Раньше на это было два маршрута (`/sales`, `/services`), и вопрос «сколько мы
    всего продали» не имел ответа ни на одном из них.
    """
    cid = await assert_company_member(company_id, current_user, db)
    return await _slice(db, cid, "sale", top, date_from, date_to,
                        line_kind=None if kind == "all" else kind)


# ── Ассортимент: маржа и стабильность спроса ─────────────────────────────────
# Разрезы отвечают «сколько продали». Следующие два вопроса коммерсанта — «сколько
# на этом заработали» и «на что можно рассчитывать»: первое требует себестоимости,
# второе — помесячного ряда, чтобы отличить ровный спрос от случайного всплеска.
#
# Себестоимость берём из строк ПОСТУПЛЕНИЙ по тому же коду номенклатуры (198 кодов
# пилота и продаются, и закупаются), а не из 90.02.1: в регистре себестоимость
# свёрнута по счёту, разложить её обратно по позициям нечем. Контроль — итог по
# 90.02.1 в ответе, чтобы расхождение было видно, а не спрятано.

@router.get("/assortment")
async def assortment(
    company_id: str,
    by: str = Query("item", pattern="^(item|client)$"),
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Ассортимент или клиентская база с помесячным рядом и (для позиций) маржой."""
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid), "limit": limit}
    where_date = ""
    if date_from:
        where_date += " AND d.date >= :df"
        p["df"] = date_from
    if date_to:
        where_date += " AND d.date <= :dt"
        p["dt"] = date_to

    if by == "client":
        # У покупателя себестоимости нет — считаем оборот и его ряд по месяцам.
        rows = [{
            "key": str(r[0]) if r[0] else r[1], "id": str(r[0]) if r[0] else None,
            "name": r[1], "amount": _num(r[2]), "docs": r[3],
            "first": r[4], "last": r[5],
            "months": [{"month": m, "amount": _num(a)} for m, a in (r[6] or [])],
        } for r in (await db.execute(text(f"""
            WITH m AS (
              SELECT coalesce(d.counterparty_id::text, d.counterparty_name) k,
                     max(d.counterparty_id::text) id, max(d.counterparty_name) name,
                     substr(d.date, 1, 7) AS month, sum(d.amount) amount, count(*) docs,
                     -- `AS` обязателен: без него `) month` разбирается как
                     -- квалификатор интервала (`'1' month`), и запрос падает.
                     min(d.date) first, max(d.date) last
                FROM accounting_docs d
               WHERE d.company_id = :cid AND d.doc_type = 'sale'{where_date}
               GROUP BY 1, 4
            )
            SELECT max(id), max(name), sum(amount), sum(docs), min(first), max(last),
                   array_agg(ARRAY[month, amount::text] ORDER BY month)
              FROM m GROUP BY k ORDER BY sum(amount) DESC LIMIT :limit
        """), p)).all()]
        return {"by": by, "rows": _with_stability(rows), "cost": None}

    # Позиции: продажи и закупки по коду номенклатуры одной выборкой.
    # Суммы берём и с НДС, и без него (`amount_raw`). Разрез и ABC живут в деньгах
    # покупателя (с НДС, как выручка на 90.01.1), а маржа обязана считаться БЕЗ
    # налога: на 90.02.1 себестоимость лежит без НДС, и сравнение с ней иначе
    # завышено на ставку. Первый прогон дал 112 % регистра именно поэтому.
    rows = [{
        "key": r[0], "code": r[0], "name": r[1],
        "soldQty": _num(r[2]), "soldAmount": _num(r[3]), "docs": r[4],
        "boughtQty": _num(r[5]), "boughtAmount": _num(r[6]),
        "first": r[7], "last": r[8],
        "months": [{"month": m, "amount": _num(a)} for m, a in (r[9] or [])],
        "soldNet": _num(r[10]), "boughtNet": _num(r[11]),
    } for r in (await db.execute(text(f"""
        WITH l AS (
          -- Период режет ПРОДАЖИ, но не закупки: товар, купленный в декабре и
          -- проданный в январе, при окне «январь» оставался без себестоимости и
          -- выпадал из маржи — чем короче период, тем меньше позиций в итоге.
          SELECT d.id doc, d.doc_type, d.date, jsonb_array_elements(d.lines) ln
            FROM accounting_docs d
           WHERE d.company_id = :cid
             AND (d.doc_type = 'purchase'
                  OR (d.doc_type = 'sale'{where_date}))
        ), x AS (
          SELECT doc, doc_type, date, btrim(ln->>'code') code, ln->>'name' name,
                 (ln->>'qty')::numeric qty, (ln->>'amount')::numeric amount,
                 -- Без НДС — это сумма МИНУС налог строки. `amount_raw` для этого не
                 -- годится: при `vat_included = true` (523 строки продаж из 530 на
                 -- пилоте) он равен `amount`, то есть содержит налог. Прошлая версия
                 -- брала его и завышала «продано без НДС» на 3,68 млн ₽, а маржу на
                 -- 4,7 п.п. Проверка методики: расчётная себестоимость даёт 101 % от
                 -- оборота 90.02.1 ↔ 41.01, то есть считаем правильно.
                 ((ln->>'amount')::numeric - coalesce((ln->>'vat')::numeric, 0)) net
            FROM l WHERE coalesce(btrim(ln->>'code'), '') <> ''
        ), m AS (
          SELECT code, max(name) name, substr(date, 1, 7) AS month,
                 sum(qty)    FILTER (WHERE doc_type = 'sale')     sold_qty,
                 sum(amount) FILTER (WHERE doc_type = 'sale')     sold_amount,
                 count(DISTINCT doc) FILTER (WHERE doc_type = 'sale') docs,
                 sum(qty)    FILTER (WHERE doc_type = 'purchase') bought_qty,
                 sum(amount) FILTER (WHERE doc_type = 'purchase') bought_amount,
                 sum(net)    FILTER (WHERE doc_type = 'sale')     sold_net,
                 sum(net)    FILTER (WHERE doc_type = 'purchase') bought_net,
                 min(date) FILTER (WHERE doc_type = 'sale') first,
                 max(date) FILTER (WHERE doc_type = 'sale') last
            FROM x GROUP BY code, 3
        )
        SELECT code, max(name), sum(sold_qty), sum(sold_amount), sum(docs),
               sum(bought_qty), sum(bought_amount), min(first), max(last),
               array_agg(ARRAY[month, coalesce(sold_amount, 0)::text] ORDER BY month),
               sum(sold_net), sum(bought_net)
          FROM m GROUP BY code
         HAVING coalesce(sum(sold_amount), 0) <> 0
         ORDER BY sum(sold_amount) DESC NULLS LAST LIMIT :limit
    """), p)).all()]

    # Эталон для маржи — ТОВАРНАЯ себестоимость: оборот 90.02.1 в корреспонденции
    # со счётом товаров (41). Полный оборот 90.02.1 включает списания с 26 счёта
    # (на пилоте 954 295 ₽ из 15 017 984 ₽), которых в позиционном расчёте нет по
    # определению, — сравнение с ним занижало сходимость. Период тот же, что у строк:
    # раньше знаменатель брался за всю историю, и при фильтре «месяц» экран показывал
    # «8 % от регистра» — катастрофу, которой нет.
    cost_sql = """
        SELECT coalesce(sum(amount), 0) FROM gl_entries
         WHERE company_id = :cid AND account_dt = :dt AND account_kt LIKE :kt
    """
    cost_p = {"cid": str(cid), "dt": COST_DT, "kt": f"{STOCK_ACCOUNT}%"}
    if date_from:
        cost_sql += " AND entry_date >= :df"
        cost_p["df"] = _day(date_from)
    if date_to:
        cost_sql += " AND entry_date <= :dt2"
        cost_p["dt2"] = _day(date_to)

    return {
        "by": by,
        "rows": _with_stability(rows),
        # Товарная себестоимость по регистру — чем проверяется маржа по позициям.
        "cost": _num((await db.execute(text(cost_sql), cost_p)).scalar_one()),
        "costBasis": "90.02.1 ↔ 41",
    }


def _with_stability(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Добавить каждой строке класс XYZ по её помесячному ряду.

    Формулу свою не пишем: стабильность считает `fuel_network_analytics._stability`,
    пороги там же (`_xyz`). Она уже прошла разбор на данных сети — разброс мерится по
    ОСТАТКАМ линейного тренда (иначе растущая позиция уезжает в «рваные»), ряд идёт от
    первой продажи (иначе нули до появления позиции раздувают CV), а короткая история
    получает честное «—», а не худший класс автоматически.
    """
    from app.services.fuel_network_analytics import _stability, _xyz

    grid = [f"{m}-01" for m in sorted({m["month"] for r in rows for m in r["months"]})]
    for r in rows:
        by_bucket = {f"{m['month']}-01": m["amount"] for m in r["months"] if m["amount"]}
        st = _stability(by_bucket, grid, "month")
        r["cv"] = st["cv"]
        r["xyz"] = _xyz(st["cv"])
        r["trend"] = st["trend"]
        r["trendPct"] = st["trend_pct"]
        r["monthsLive"] = st["life"]
        # Частота — вторая ось матрицы, и на данных офисной компании ГЛАВНАЯ.
        # Проверка на пилоте: 153 позиции из 201 продавались ровно в ОДНОМ месяце,
        # 23 покупателя из 43 покупали один раз. Это не дефект расчёта, а профиль
        # бизнеса: поставки проектные, разовые. Классический XYZ на таком ряде
        # молчит («мало данных» у 95 % строк), и матрица ABC-XYZ вырождается в
        # пустую колонку — поэтому осью стала частота, а XYZ остался колонкой там,
        # где ряд действительно есть.
        r["saleMonths"] = len(by_bucket)
        r["freq"] = ("once" if len(by_bucket) <= 1
                     else "few" if len(by_bucket) <= 5
                     else "regular")
    return rows


# ── Сверка «Реализации» с бухгалтерией ───────────────────────────────────────

@router.get("/revenue-check")
async def revenue_check(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сумма документов реализации против оборота 90.01.1 — помесячно.

    Смысл продукта — сходимость с бухгалтерией, и она обязана быть видимой: пока
    расхождение не показано на экране, «Реализация» и «Бухгалтерия» расходятся тихо
    и обнаруживаются у заказчика. Эталон здесь регистр (оборот по кредиту 90.01.1),
    документы — то, что мы показываем; разница помесячно и есть предмет разбора.
    """
    cid = await assert_company_member(company_id, current_user, db)
    p = {"cid": str(cid), "kt": REVENUE_KT}

    docs = {r[0]: (_num(r[1]), r[2]) for r in (await db.execute(text("""
        SELECT substr(date, 1, 7), sum(amount), count(*)
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type = 'sale' GROUP BY 1
    """), p)).all()}

    # Регистр даёт выручку С НДС только вместе с 90.03: по кредиту 90.01.1 лежит
    # сумма с налогом, поэтому сравнение идёт с суммой документа как есть.
    reg = {r[0]: _num(r[1]) for r in (await db.execute(text("""
        SELECT to_char(entry_date, 'YYYY-MM'), sum(amount)
          FROM gl_entries
         WHERE company_id = :cid AND account_kt = :kt GROUP BY 1
    """), p)).all()}

    status = {r[0]: r[1] for r in (await db.execute(text("""
        SELECT to_char(make_date(year, month, 1), 'YYYY-MM'), status
          FROM periods WHERE company_id = :cid
    """), {"cid": str(cid)})).all()}

    months = []
    for m in sorted(set(docs) | set(reg)):
        d_amount, d_count = docs.get(m, (0.0, 0))
        r_amount = reg.get(m, 0.0)
        months.append({
            "month": m, "docs": d_amount, "docsCount": d_count, "register": r_amount,
            "diff": round(d_amount - r_amount, 2),
            "periodStatus": status.get(m, "open"),
        })

    total_docs = sum(m["docs"] for m in months)
    total_reg = sum(m["register"] for m in months)
    return {
        "months": months,
        "totalDocs": round(total_docs, 2),
        "totalRegister": round(total_reg, 2),
        "diff": round(total_docs - total_reg, 2),
        # Месяцы, где сходимость нарушена больше рубля: округление копеек не повод
        # звать бухгалтера, расхождение в тысячу — повод.
        "broken": [m["month"] for m in months if abs(m["diff"]) > 1],
    }


# ── Долг: старение и инкассация ──────────────────────────────────────────────
# Волна 6, приёмы взяты из канона управления дебиторкой (реестр старения + кривая
# инкассации). Средний срок оплаты отвечает «как платят вообще», а работать надо с
# конкретным долгом: чей он, сколько ему дней и сколько мы соберём к концу месяца.
#
# Ограничение, которое честно выносится на экран: срока оплаты по договору в выгрузке
# НЕТ, поэтому возраст считается от даты счёта, а не от наступления срока платежа.
# По канону бакеты привязывают к условиям договора (при отсрочке 45 дней просрочка
# начинается на 46-й) — как только реквизит приедет, пороги сдвинутся здесь.

AGING_BUCKETS: list[tuple[str, str, int, int]] = [
    ("d30", "До 30 дней", 0, 30),
    ("d60", "31–60 дней", 31, 60),
    ("d90", "61–90 дней", 61, 90),
    ("d180", "91–180 дней", 91, 180),
    ("older", "Больше 180 дней", 181, 100000),
]


@router.get("/ar-aging")
async def ar_aging(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Реестр старения долга по счетам покупателям: сколько, чьё и сколько дней.

    Считается по счетам с ИЗВЕСТНОЙ оплатой (регистр «Оплата счетов»). Счета, которых
    регистр не свёл, идут отдельной строкой «оплата неизвестна» и в долг не
    записываются: ноль вместо отсутствующих данных — та ошибка, из-за которой витрина
    показывала долг в 123 млн ₽.
    """
    cid = await assert_company_member(company_id, current_user, db)
    today = date.today()

    rows = [{
        "id": str(r[0]), "number": r[1], "date": r[2],
        "counterparty": r[3], "counterpartyId": str(r[4]) if r[4] else None,
        "amount": _num(r[5]), "paid": None if r[6] is None else _num(r[6]),
        "lastPaidAt": r[7],
    } for r in (await db.execute(text(r"""
        SELECT d.id, d.number, d.date, d.counterparty_name, d.counterparty_id,
               d.amount, p.paid, p.last_paid
          FROM accounting_docs d
          LEFT JOIN (SELECT invoice_doc_id, sum(amount) paid, max(paid_at) last_paid
                       FROM invoice_payments WHERE company_id = :cid
                      GROUP BY invoice_doc_id) p ON p.invoice_doc_id = d.id
         WHERE d.company_id = :cid AND d.doc_type = 'invoice_out'
           AND d.date ~ '^\d{4}-\d{2}-\d{2}'
    """), {"cid": str(cid)})).all()]

    open_rows, unknown = [], []
    for r in rows:
        if r["paid"] is None:
            unknown.append(r)
            continue
        rest = round(r["amount"] - r["paid"], 2)
        if rest <= 0.01:
            continue
        age = (today - date.fromisoformat(r["date"])).days
        bucket = next(k for k, _, lo, hi in AGING_BUCKETS if lo <= age <= hi)
        open_rows.append({**r, "rest": rest, "age": age, "bucket": bucket})

    buckets = [{
        "key": key, "label": label,
        "count": sum(1 for r in open_rows if r["bucket"] == key),
        "amount": round(sum(r["rest"] for r in open_rows if r["bucket"] == key), 2),
    } for key, label, _, _ in AGING_BUCKETS]

    by_client: dict[str, dict[str, Any]] = {}
    for r in open_rows:
        key = r["counterpartyId"] or r["counterparty"]
        c = by_client.setdefault(key, {
            "id": r["counterpartyId"], "name": r["counterparty"],
            "invoices": 0, "rest": 0.0, "maxAge": 0, "oldest": None,
        })
        c["invoices"] += 1
        c["rest"] += r["rest"]
        if r["age"] > c["maxAge"]:
            c["maxAge"] = r["age"]
            c["oldest"] = r["date"]
    clients = sorted(by_client.values(), key=lambda c: -c["rest"])

    # Сальдо 62 из регистра — эталон рядом с нашим расчётом. Развёрнуто: долг
    # покупателя (дебет) и его аванс (кредит) — разные обязательства, свёрнутое
    # сальдо прячет и то и другое.
    saldo = (await db.execute(text("""
        SELECT coalesce(sum(debit), 0), coalesce(sum(credit), 0)
          FROM gl_balances
         WHERE company_id = :cid AND account LIKE '62%'
           AND as_of = (SELECT max(as_of) FROM gl_balances WHERE company_id = :cid)
    """), {"cid": str(cid)})).one()

    return {
        "buckets": buckets,
        "clients": clients,
        "rows": sorted(open_rows, key=lambda r: -r["rest"]),
        "openAmount": round(sum(r["rest"] for r in open_rows), 2),
        "openCount": len(open_rows),
        "unknownCount": len(unknown),
        "unknownAmount": round(sum(r["amount"] for r in unknown), 2),
        "registerDebit": _num(saldo[0]),
        "registerCredit": _num(saldo[1]),
        "asOf": today.isoformat(),
        # Срока по договору в данных нет — возраст считается от даты счёта.
        "ageBasis": "invoice_date",
    }


@router.get("/collection-curve")
async def collection_curve(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Кривая инкассации: какая доля счетов месяца собрана к дню 30/60/90/180.

    Отвечает на вопрос, на который средний срок ответить не может: «сколько денег из
    выставленного в этом месяце мы получим к концу следующего». Строки месяцев с
    малым числом счетов помечены: доля по двум счетам — не статистика.
    """
    cid = await assert_company_member(company_id, current_user, db)

    rows = [(r[0], _num(r[1]), r[2], _num(r[3]), _num(r[4]), _num(r[5]), _num(r[6]))
            for r in (await db.execute(text(r"""
        WITH inv AS (
          SELECT d.id, substr(d.date, 1, 7) AS month, d.date, d.amount
            FROM accounting_docs d
           WHERE d.company_id = :cid AND d.doc_type = 'invoice_out'
             AND d.date ~ '^\d{4}-\d{2}-\d{2}'
             AND EXISTS (SELECT 1 FROM invoice_payments p WHERE p.invoice_doc_id = d.id)
        ), pay AS (
          SELECT i.id, i.month, i.amount,
                 sum(p.amount) FILTER (WHERE p.paid_at::date - i.date::date <= 30)  d30,
                 sum(p.amount) FILTER (WHERE p.paid_at::date - i.date::date <= 60)  d60,
                 sum(p.amount) FILTER (WHERE p.paid_at::date - i.date::date <= 90)  d90,
                 sum(p.amount) FILTER (WHERE p.paid_at::date - i.date::date <= 180) d180
            FROM inv i JOIN invoice_payments p ON p.invoice_doc_id = i.id
           WHERE p.paid_at IS NOT NULL
           GROUP BY i.id, i.month, i.amount
        )
        SELECT month, sum(amount), count(*),
               coalesce(sum(d30), 0), coalesce(sum(d60), 0),
               coalesce(sum(d90), 0), coalesce(sum(d180), 0)
          FROM pay GROUP BY month ORDER BY month
    """), {"cid": str(cid)})).all()]

    months = [{
        "month": m, "billed": billed, "invoices": n,
        "d30": d30, "d60": d60, "d90": d90, "d180": d180,
        "pct30": round(d30 / billed * 100, 1) if billed else None,
        "pct60": round(d60 / billed * 100, 1) if billed else None,
        "pct90": round(d90 / billed * 100, 1) if billed else None,
        "pct180": round(d180 / billed * 100, 1) if billed else None,
        # Порог из практики статистики малых чисел: доля по двум-трём счетам
        # публикуется как абсолютное число, а не как процент.
        "thin": n < 5,
    } for m, billed, n, d30, d60, d90, d180 in rows]

    total = sum(m["billed"] for m in months) or 1.0
    return {
        "months": months,
        "avg30": round(sum(m["d30"] for m in months) / total * 100, 1),
        "avg60": round(sum(m["d60"] for m in months) / total * 100, 1),
        "avg90": round(sum(m["d90"] for m in months) / total * 100, 1),
        "avg180": round(sum(m["d180"] for m in months) / total * 100, 1),
        "billed": round(total, 2),
    }


@router.get("/cash-forecast")
async def cash_forecast(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сколько денег придёт от текущего долга и когда.

    Метод — условная вероятность досбора по исторической кривой инкассации, а не
    «всё придёт по сроку договора». Логика: по закрытым счетам известно, какая доля
    выставленного собирается к дню t (F(t)) и какая собирается вообще (F_итог). Для
    счёта, дожившего до возраста A и всё ещё открытого, ожидаемая доля досбора равна
    (F_итог − F(A)) / (1 − F(A)): деньги, которые «должны были прийти» за прошедшие
    A дней, уже не пришли, и это меняет ожидание.

    Отсюда же и разбивка по окнам: прирост кривой между A и A+Δ, отнесённый к
    непришедшей части. Счета без записи в регистре оплат в прогноз не берутся вовсе —
    у них неизвестна не дата, а сам факт оплаты.
    """
    cid = await assert_company_member(company_id, current_user, db)
    today = date.today()
    GRID = [0, 30, 60, 90, 120, 180, 270, 360, 540, 720]

    # Историческая кривая: доля выставленного, собранная к дню t. Считается по счетам,
    # которые регистр свёл с платежами, — других мы просто не видим.
    hist = (await db.execute(text(r"""
        WITH inv AS (
          SELECT d.id, d.date, d.amount
            FROM accounting_docs d
           WHERE d.company_id = :cid AND d.doc_type = 'invoice_out'
             AND d.date ~ '^\d{4}-\d{2}-\d{2}'
             AND EXISTS (SELECT 1 FROM invoice_payments p
                          WHERE p.invoice_doc_id = d.id AND p.paid_at IS NOT NULL)
        )
        SELECT coalesce(sum(i.amount), 0) AS billed,
               count(*) AS invoices,
               coalesce(sum(p.amount), 0) AS paid,
               coalesce(sum(p.amount) FILTER (WHERE p.days <= 0), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.days <= 30), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.days <= 60), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.days <= 90), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.days <= 120), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.days <= 180), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.days <= 270), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.days <= 360), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.days <= 540), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.days <= 720), 0)
          FROM inv i
          LEFT JOIN LATERAL (
            SELECT pp.amount, (pp.paid_at::date - i.date::date) AS days
              FROM invoice_payments pp
             WHERE pp.invoice_doc_id = i.id AND pp.paid_at IS NOT NULL
          ) p ON true
    """), {"cid": str(cid)})).one()

    billed = _num(hist[0])
    curve = {g: (_num(hist[3 + n]) / billed if billed else 0.0)
             for n, g in enumerate(GRID)}
    total_share = _num(hist[2]) / billed if billed else 0.0

    def f_at(days: int) -> float:
        """Кривая в произвольной точке — линейно между узлами сетки."""
        if days <= GRID[0]:
            return curve[GRID[0]]
        if days >= GRID[-1]:
            return total_share
        for a, b in zip(GRID, GRID[1:]):
            if a <= days <= b:
                if b == a:
                    return curve[a]
                k = (days - a) / (b - a)
                return curve[a] + (curve[b] - curve[a]) * k
        return total_share

    # Открытые счета с известной оплатой — то же множество, что в реестре старения.
    open_rows = [{
        "id": str(r[0]), "number": r[1], "date": r[2], "counterparty": r[3],
        "counterpartyId": str(r[4]) if r[4] else None,
        "amount": _num(r[5]), "paid": _num(r[6]),
    } for r in (await db.execute(text(r"""
        SELECT d.id, d.number, d.date, d.counterparty_name, d.counterparty_id,
               d.amount, coalesce(p.paid, 0)
          FROM accounting_docs d
          JOIN (SELECT invoice_doc_id, sum(amount) paid FROM invoice_payments
                 WHERE company_id = :cid GROUP BY invoice_doc_id) p
            ON p.invoice_doc_id = d.id
         WHERE d.company_id = :cid AND d.doc_type = 'invoice_out'
           AND d.date ~ '^\d{4}-\d{2}-\d{2}' AND d.amount - coalesce(p.paid, 0) > 0.01
    """), {"cid": str(cid)})).all()]

    WINDOWS = [(30, "30 дней"), (60, "60 дней"), (90, "90 дней"), (180, "180 дней")]
    windows = {w: 0.0 for w, _ in WINDOWS}
    expected_total = 0.0
    rows = []
    for r in open_rows:
        rest = round(r["amount"] - r["paid"], 2)
        age = (today - date.fromisoformat(r["date"])).days
        f_now = f_at(age)
        # Ниже единицы по построению: F не превышает total_share.
        left = 1.0 - f_now
        if left <= 0.0001:
            share_total = 0.0
            per_window = {w: 0.0 for w, _ in WINDOWS}
        else:
            share_total = max(0.0, (total_share - f_now) / left)
            per_window = {w: max(0.0, (f_at(age + w) - f_now) / left) for w, _ in WINDOWS}
        exp = round(rest * share_total, 2)
        expected_total += exp
        for w, _ in WINDOWS:
            windows[w] += rest * per_window[w]
        rows.append({
            **r, "rest": rest, "age": age,
            "expected": exp,
            "expectedPct": round(share_total * 100, 1),
            "in30": round(rest * per_window[30], 2),
            "in90": round(rest * per_window[90], 2),
        })
    rows.sort(key=lambda r: -r["rest"])

    unknown = (await db.execute(text("""
        SELECT count(*), coalesce(sum(d.amount), 0) FROM accounting_docs d
         WHERE d.company_id = :cid AND d.doc_type = 'invoice_out'
           AND NOT EXISTS (SELECT 1 FROM invoice_payments p WHERE p.invoice_doc_id = d.id)
    """), {"cid": str(cid)})).one()

    return {
        "rows": rows,
        "openAmount": round(sum(r["rest"] for r in rows), 2),
        "openCount": len(rows),
        "expected": round(expected_total, 2),
        "windows": [{"days": w, "label": label, "amount": round(windows[w], 2)}
                    for w, label in WINDOWS],
        # Кривая, по которой сделан прогноз, — чтобы цифра не выглядела гаданием.
        "curve": [{"days": g, "pct": round(curve[g] * 100, 1)} for g in GRID],
        "totalSharePct": round(total_share * 100, 1),
        "historyInvoices": hist[1],
        "historyBilled": round(billed, 2),
        # Счета вне прогноза: у них нет записи в регистре оплат вовсе.
        "unknownCount": unknown[0],
        "unknownAmount": _num(unknown[1]),
        "asOf": today.isoformat(),
    }


# ── Сделки и незакрытые счета ────────────────────────────────────────────────
# Канон профессиональных услуг: единица анализа — СДЕЛКА, а не позиция и не месяц.
# У компании 218 реализаций за пять лет; список сделок с маржой отвечает на вопросы,
# которых распределения не берут: какая сделка убыточна и почему.

@router.get("/deals")
async def deals(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Реализации как сделки: сумма без НДС, себестоимость по строкам, маржа."""
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid)}
    where = ""
    if date_from:
        where += " AND d.date >= :df"
        p["df"] = date_from
    if date_to:
        where += " AND d.date <= :dt"
        p["dt"] = date_to

    rows = [{
        "id": str(r[0]), "number": r[1], "date": r[2],
        "counterparty": r[3], "counterpartyId": str(r[4]) if r[4] else None,
        "amount": _num(r[5]), "net": _num(r[6]), "cost": None if r[7] is None else _num(r[7]),
        "lines": r[8], "unknownLines": r[9],
    } for r in (await db.execute(text(f"""
        WITH buy AS (
          -- Средняя цена закупки по коду за всю историю: себестоимость сделки не
          -- зависит от того, каким окном человек смотрит на продажи.
          SELECT btrim(ln->>'code') code,
                 sum((ln->>'amount')::numeric - coalesce((ln->>'vat')::numeric, 0))
                   / nullif(sum((ln->>'qty')::numeric), 0) price
            FROM accounting_docs d, jsonb_array_elements(d.lines) ln
           WHERE d.company_id = :cid AND d.doc_type = 'purchase'
             AND coalesce(btrim(ln->>'code'), '') <> ''
           GROUP BY 1
        ), sale AS (
          SELECT d.id, d.number, d.date, d.counterparty_name, d.counterparty_id, d.amount,
                 jsonb_array_elements(d.lines) ln
            FROM accounting_docs d
           WHERE d.company_id = :cid AND d.doc_type = 'sale'
             AND jsonb_typeof(d.lines) = 'array'{where}
        )
        SELECT s.id, max(s.number), max(s.date), max(s.counterparty_name),
               max(s.counterparty_id::text), max(s.amount),
               sum((s.ln->>'amount')::numeric - coalesce((s.ln->>'vat')::numeric, 0)),
               sum(buy.price * (s.ln->>'qty')::numeric),
               count(*),
               count(*) FILTER (WHERE buy.price IS NULL)
          FROM sale s
          LEFT JOIN buy ON buy.code = btrim(s.ln->>'code')
         GROUP BY s.id
         ORDER BY max(s.date) DESC
    """), p)).all()]

    for r in rows:
        # Маржа считается только когда себестоимость известна ПО ВСЕМ строкам сделки:
        # частичная себестоимость даёт завышенную маржу, а выглядит как настоящая.
        full = r["cost"] is not None and r["unknownLines"] == 0
        r["margin"] = round(r["net"] - r["cost"], 2) if full else None
        r["marginPct"] = (round((r["net"] - r["cost"]) / r["net"] * 100, 1)
                          if full and r["net"] else None)

    known = [r for r in rows if r["margin"] is not None]
    return {
        "rows": rows,
        "count": len(rows),
        "net": round(sum(r["net"] for r in rows), 2),
        "withMargin": len(known),
        "marginTotal": round(sum(r["margin"] for r in known), 2),
        "netWithMargin": round(sum(r["net"] for r in known), 2),
        # Порог тревоги из практики проектных поставок: сделка ниже 30 % маржи —
        # повод проверить цену и объём работ, а не статистическая аномалия.
        "lowMargin": sum(1 for r in known if (r["marginPct"] or 0) < 30),
    }


@router.get("/backlog")
async def backlog(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Счета, за которыми не пошла отгрузка: возраст, клиент, сумма.

    Ссылки «счёт → реализация» в выгрузке нет, поэтому сопоставление идёт по
    КОНТРАГЕНТУ: клиент, у которого есть счета и ни одной реализации, — это либо
    незакрытая сделка, либо мусор в базе. И то и другое требует ответа заказчика.
    """
    cid = await assert_company_member(company_id, current_user, db)
    today = date.today()

    rows = [{
        "counterparty": r[0], "counterpartyId": str(r[1]) if r[1] else None,
        "invoices": r[2], "invoiced": _num(r[3]),
        "sales": r[4], "shipped": _num(r[5]),
        "firstInvoice": r[6], "lastInvoice": r[7],
    } for r in (await db.execute(text("""
        SELECT coalesce(counterparty_name, '—'), max(counterparty_id::text),
               count(*) FILTER (WHERE doc_type = 'invoice_out'),
               coalesce(sum(amount) FILTER (WHERE doc_type = 'invoice_out'), 0),
               count(*) FILTER (WHERE doc_type = 'sale'),
               coalesce(sum(amount) FILTER (WHERE doc_type = 'sale'), 0),
               min(date) FILTER (WHERE doc_type = 'invoice_out'),
               max(date) FILTER (WHERE doc_type = 'invoice_out')
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type IN ('invoice_out', 'sale')
         GROUP BY 1 HAVING count(*) FILTER (WHERE doc_type = 'invoice_out') > 0
         ORDER BY 4 DESC
    """), {"cid": str(cid)})).all()]

    for r in rows:
        r["gap"] = round(r["invoiced"] - r["shipped"], 2)
        r["shippedPct"] = round(r["shipped"] / r["invoiced"] * 100, 1) if r["invoiced"] else None
        r["daysSinceLast"] = ((today - date.fromisoformat(r["lastInvoice"])).days
                              if r["lastInvoice"] and len(r["lastInvoice"]) == 10 else None)

    silent = [r for r in rows if not r["sales"]]
    return {
        "rows": rows,
        "invoiced": round(sum(r["invoiced"] for r in rows), 2),
        "shipped": round(sum(r["shipped"] for r in rows), 2),
        "silentCount": len(silent),
        "silentAmount": round(sum(r["invoiced"] for r in silent), 2),
    }


@router.get("/concentration")
async def concentration(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Насколько выручка держится на нескольких клиентах: HHI и доли лидеров по годам.

    HHI — сумма квадратов долей в процентах (0–10 000). Пороги антимонопольной
    практики: до 1000 — низкая концентрация, 1000–2000 — умеренная, выше 2000 —
    высокая. Для поставщика это зеркало: высокий HHI значит, что уход одного
    покупателя уносит заметную часть выручки.
    """
    cid = await assert_company_member(company_id, current_user, db)

    raw = [(r[0], r[1], _num(r[2])) for r in (await db.execute(text(r"""
        SELECT substr(date, 1, 4) AS year,
               coalesce(counterparty_id::text, counterparty_name) AS client,
               sum(amount)
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type = 'sale' AND date ~ '^\d{4}'
         GROUP BY 1, 2
    """), {"cid": str(cid)})).all()]

    def stats(pairs: list[tuple[str, float]]) -> dict[str, Any]:
        total = sum(a for _, a in pairs)
        if total <= 0:
            return {"clients": 0, "hhi": None, "cr1": None, "cr3": None, "cr5": None}
        shares = sorted((a / total * 100 for _, a in pairs), reverse=True)
        return {
            "clients": len(shares),
            "hhi": round(sum(x * x for x in shares)),
            "cr1": round(shares[0], 1),
            "cr3": round(sum(shares[:3]), 1),
            "cr5": round(sum(shares[:5]), 1),
            "amount": round(total, 2),
        }

    years = sorted({y for y, _, _ in raw})
    by_year = [{"year": y, **stats([(c, a) for yy, c, a in raw if yy == y])} for y in years]
    return {
        "total": stats([(c, a) for _, c, a in raw]),
        "years": by_year,
        # Границы, по которым читается число: без них HHI это просто «2731».
        "levels": {"low": 1000, "high": 2000},
    }


# ── Склад и закупки ──────────────────────────────────────────────────────────
# Волна 4. Складского учёта в выгрузке нет: остатки считаются как приход минус
# расход по строкам документов. Способ грубый (партий и себестоимости списания в
# данных нет), поэтому итог в деньгах сверяется с сальдо 41 — расхождение видно на
# самом экране, а не всплывает у заказчика.

STOCK_ACCOUNT = "41"


@router.get("/stock")
async def stock(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Остатки по номенклатуре: приход − расход, запас в днях, неликвиды."""
    cid = await assert_company_member(company_id, current_user, db)
    p = {"cid": str(cid)}

    # Ключ — код И наименование: в выгрузке код переиспользован (у пилота два кода
    # несут разные товары), и по одному коду остаток складывал бы несравнимое.
    # Оценка идёт по суммам БЕЗ НДС (`amount_raw`): на счёте 41 товар лежит без
    # налога, и с оценкой по суммам с НДС сверка расходилась на ставку.
    rows = [{
        "code": r[0], "name": r[1],
        "boughtQty": _num(r[2]), "boughtAmount": _num(r[3]),
        "soldQty": _num(r[4]), "soldAmount": _num(r[5]),
        "firstBuy": r[6], "lastBuy": r[7], "lastSale": r[8],
        "saleMonths": r[9],
    } for r in (await db.execute(text("""
        WITH l AS (
          SELECT d.doc_type, d.date, jsonb_array_elements(d.lines) ln
            FROM accounting_docs d
           WHERE d.company_id = :cid AND d.doc_type IN ('sale', 'purchase')
        ), x AS (
          SELECT doc_type, date, btrim(ln->>'code') code, ln->>'name' name,
                 (ln->>'qty')::numeric qty,
                 -- Оценка остатка — по суммам БЕЗ НДС (сумма минус налог строки):
                 -- на счёте 41 товар лежит без налога.
                 ((ln->>'amount')::numeric - coalesce((ln->>'vat')::numeric, 0)) amount
            FROM l
           WHERE coalesce(btrim(ln->>'code'), '') <> ''
             -- Только товарные строки: у услуги остатка не бывает по природе.
             -- Без этого фильтра в «остаток» попадали консультации, аренда и
             -- транспорт — 2,37 млн ₽ из 2,54 млн на пилоте, то есть экран про
             -- склад показывал почти целиком услуги.
             AND coalesce(ln->>'kind', 'goods') = 'goods'
        )
        SELECT code, name,
               sum(qty)    FILTER (WHERE doc_type = 'purchase'),
               sum(amount) FILTER (WHERE doc_type = 'purchase'),
               sum(qty)    FILTER (WHERE doc_type = 'sale'),
               sum(amount) FILTER (WHERE doc_type = 'sale'),
               min(date)   FILTER (WHERE doc_type = 'purchase'),
               max(date)   FILTER (WHERE doc_type = 'purchase'),
               max(date)   FILTER (WHERE doc_type = 'sale'),
               count(DISTINCT substr(date, 1, 7)) FILTER (WHERE doc_type = 'sale')
          FROM x GROUP BY code, name
    """), p)).all()]

    today = date.today()
    out = []
    for r in rows:
        rest_qty = r["boughtQty"] - r["soldQty"]
        # Средняя цена закупки — по ней и оценивается остаток: себестоимости
        # списания в данных нет, партий тоже.
        avg_buy = r["boughtAmount"] / r["boughtQty"] if r["boughtQty"] else 0.0
        # Расход в месяц — по месяцам, в которых были продажи, а не по всей истории:
        # позиция, проданная раз в 2022-м, иначе получает «запас на 40 лет» и уезжает
        # в неликвиды формально, хотя её просто больше не возят.
        per_month = r["soldQty"] / r["saleMonths"] if r["saleMonths"] else 0.0
        days = None
        if per_month > 0 and rest_qty > 0:
            days = round(rest_qty / per_month * 30)
        last_move = max([d for d in (r["lastBuy"], r["lastSale"]) if d], default=None)
        idle = (today - date.fromisoformat(last_move)).days if last_move else None
        out.append({
            **r,
            "restQty": round(rest_qty, 3),
            "restAmount": round(rest_qty * avg_buy, 2) if rest_qty > 0 else 0.0,
            "avgBuy": round(avg_buy, 2),
            "daysOfSupply": days,
            "lastMove": last_move,
            "idleDays": idle,
            # Продавалась ли позиция хоть раз — этим товар отличается от того, что
            # компания купила себе: ноутбук, канцелярия, материалы для работ. Второе
            # списано в затраты, а не лежит на складе, и в товарный остаток не идёт.
            "everSold": r["soldQty"] > 0,
        })
    out.sort(key=lambda r: -r["restAmount"])
    # Приход по строкам против прихода на 41: разница — это то, что закуплено, но на
    # товарный счёт не легло (материалы, услуги, ОС). Без этой цифры расхождение
    # расчётного остатка с сальдо выглядит ошибкой витрины, а это состав закупки.

    positive = [r for r in out if r["restQty"] > 0.0001]
    negative = [r for r in out if r["restQty"] < -0.0001]
    # Товарный остаток — только то, что компания ПРОДАЁТ. Разница с общим счётом это
    # закупки для себя (техника, канцелярия, материалы под работы): они списаны в
    # затраты, а не лежат товаром, и попадать в оценку склада не должны.
    goods = [r for r in positive if r["everSold"]]
    # Неликвид — товар, который продавали, но давно не двигали. Позиция, купленная
    # для себя, «неликвидом» не бывает: её и не собирались продавать.
    idle = [r for r in goods if (r["idleDays"] or 0) > 180]

    # Сальдо счёта: если в снимке есть субсчета (41.01, 41.04), берём ТОЛЬКО их —
    # иначе свёрнутая строка «41» сложится со своими же субсчетами и удвоит контроль.
    balance = (await db.execute(text("""
        WITH snap AS (
          SELECT account, debit, credit FROM gl_balances
           WHERE company_id = :cid AND account LIKE :acc
             AND as_of = (SELECT max(as_of) FROM gl_balances WHERE company_id = :cid)
        )
        SELECT coalesce(sum(debit - credit), 0) FROM snap
         WHERE CASE WHEN EXISTS (SELECT 1 FROM snap WHERE account LIKE :sub)
                    THEN account LIKE :sub ELSE true END
    """), {"cid": str(cid), "acc": f"{STOCK_ACCOUNT}%",
            "sub": f"{STOCK_ACCOUNT}.%"})).scalar_one_or_none()

    intake = (await db.execute(text("""
        SELECT sum(amount) FROM gl_entries
         WHERE company_id = :cid AND account_dt LIKE :acc
    """), {"cid": str(cid), "acc": f"{STOCK_ACCOUNT}%"})).scalar_one_or_none()

    return {
        "rows": out,
        # «Закуплено и не продано» — всё, включая закупки для себя.
        "restAmount": round(sum(r["restAmount"] for r in positive), 2),
        "positions": len(positive),
        # Товарная часть того же: только позиции, которые компания продаёт.
        "goodsAmount": round(sum(r["restAmount"] for r in goods), 2),
        "goodsPositions": len(goods),
        # Сколько всего закуплено по строкам и сколько из этого попало на 41.
        "boughtTotal": round(sum(r["boughtAmount"] for r in out), 2),
        "registerIntake": _num(intake),
        # Отрицательный остаток — не «минус на складе», а признак данных: продали
        # то, чего в выгрузке не покупали (старые остатки до периода выгрузки).
        "negative": len(negative),
        "negativeQty": round(sum(r["restQty"] for r in negative), 3),
        "idle": len(idle),
        "idleAmount": round(sum(r["restAmount"] for r in idle), 2),
        "register": _num(balance),
    }


@router.get("/suppliers")
async def suppliers(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Поставщики: объём закупок, зависимость и разброс цен на одну позицию."""
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid)}
    # Два условия периода: внутри CTE документов алиаса `d` ещё нет (ссылка на него
    # даёт «missing FROM entry for table d»), а в запросе спреда он есть.
    where_bare, where = "", ""
    if date_from:
        where_bare += " AND date >= :df"
        where += " AND d.date >= :df"
        p["df"] = date_from
    if date_to:
        where_bare += " AND date <= :dt"
        where += " AND d.date <= :dt"
        p["dt"] = date_to

    # Суммы и число документов считаются ДО разворота строк. Раньше здесь стоял
    # `LEFT JOIN LATERAL jsonb_array_elements(d.lines)`, и `sum(d.amount)` складывал
    # сумму шапки столько раз, сколько в документе позиций: закупки показывались как
    # 44,8 млн вместо 19,9 млн, доля крупнейшего поставщика — 42,9 % вместо 34,6 %,
    # причём завышение неравномерное (сильнее у тех, кто возит многострочные накладные).
    rows = [{
        "id": r[0], "name": r[1], "inn": r[2], "amount": _num(r[3]), "docs": r[4],
        "positions": r[5], "first": r[6], "last": r[7],
    } for r in (await db.execute(text(f"""
        WITH d AS (
          SELECT id, counterparty_id, counterparty_name, counterparty_inn, amount, date, lines
            FROM accounting_docs
           WHERE company_id = :cid AND doc_type = 'purchase'{where_bare}
        ), agg AS (
          SELECT coalesce(counterparty_name, '—') nm,
                 max(counterparty_id::text) id, max(counterparty_inn) inn,
                 sum(amount) amount, count(*) docs, min(date) first, max(date) last
            FROM d GROUP BY 1
        ), pos AS (
          SELECT coalesce(d.counterparty_name, '—') nm,
                 count(DISTINCT btrim(ln.value->>'code')) positions
            FROM d, jsonb_array_elements(d.lines) ln
           WHERE coalesce(btrim(ln.value->>'code'), '') <> ''
           GROUP BY 1
        )
        SELECT agg.id, agg.nm, agg.inn, agg.amount, agg.docs,
               coalesce(pos.positions, 0), agg.first, agg.last
          FROM agg LEFT JOIN pos ON pos.nm = agg.nm
         ORDER BY agg.amount DESC
    """), p)).all()]

    # Разброс цены на одну позицию у разных поставщиков — то, ради чего экран и
    # открывают: где мы платим больше, чем могли бы. Берём только позиции, которые
    # покупали минимум у двоих.
    # Ключ сравнения — код И наименование, а не код: в выгрузке код переиспользован
    # (у пилота два кода из 204 несут разные товары — «Вилатерм» по 7,66 ₽ и «Сальник»
    # по 1580 ₽ под одним кодом). По коду такие строки сравнивались между собой и
    # выдавали разрыв цены в 32 664 %, то есть первое место в списке занимал мусор.
    spread = [{
        "code": r[0], "name": r[1], "suppliers": r[2],
        "minPrice": _num(r[3]), "maxPrice": _num(r[4]), "avgPrice": _num(r[5]),
        "qty": _num(r[6]),
        "minName": r[7], "maxName": r[8],
        # Разрыв больше пятикратного почти всегда означает разные единицы измерения
        # (штука против упаковки) или ошибку в документе. Не прячем, но помечаем:
        # у пилота так вскрылись лопаты по 1 ₽ против 150 ₽ при том же количестве.
        "suspicious": _num(r[3]) > 0 and _num(r[4]) / _num(r[3]) > 5,
    } for r in (await db.execute(text(f"""
        WITH x AS (
          SELECT coalesce(d.counterparty_name, '—') supplier,
                 btrim(ln.value->>'code') code, ln.value->>'name' name,
                 sum((ln.value->>'qty')::numeric) qty,
                 sum((ln.value->>'amount')::numeric) amount
            FROM accounting_docs d, jsonb_array_elements(d.lines) ln
           WHERE d.company_id = :cid AND d.doc_type = 'purchase'
             AND coalesce(btrim(ln.value->>'code'), '') <> ''
             -- Только товар: «цена за единицу» у консультации или рейса не имеет
             -- смысла, а список «где мы переплачиваем» такие строки возглавляли.
             AND coalesce(ln.value->>'kind', 'goods') = 'goods'{where}
           GROUP BY 1, 2, 3
          HAVING sum((ln.value->>'qty')::numeric) > 0
        ), pr AS (
          SELECT code, name, supplier, qty, amount, amount / qty price FROM x
        )
        SELECT code, name, count(*), min(price), max(price),
               sum(amount) / sum(qty), sum(qty),
               (array_agg(supplier ORDER BY price))[1],
               (array_agg(supplier ORDER BY price DESC))[1]
          FROM pr GROUP BY code, name HAVING count(*) > 1
         ORDER BY (max(price) - min(price)) * sum(qty) DESC
         LIMIT 100
    """), p)).all()]

    total = sum(r["amount"] for r in rows) or 1.0
    return {
        "rows": rows,
        "spread": spread,
        "total": round(total, 2),
        # Зависимость от одного поставщика: доля крупнейшего и первых трёх.
        "topShare": round(rows[0]["amount"] / total * 100, 1) if rows else 0.0,
        "top3Share": round(sum(r["amount"] for r in rows[:3]) / total * 100, 1) if rows else 0.0,
    }


# ── «Экономика»: результат, расходы, налоги ─────────────────────────────────
# Пространство до сих пор показывало правую половину отчёта: сколько продали и когда
# заплатят. Куда компания тратит и сколько зарабатывает, не отвечал никто, хотя
# проводки для этого лежат с первой выгрузки.
#
# Три вещи, которые здесь сделаны иначе, чем «сложить обороты счетов»:
#
# 1. СЕБЕСТОИМОСТЬ РАЗЛОЖЕНА ПО ИСТОЧНИКУ. Учётная политика решает, куда закрывается
#    счёт 26: при директ-костинге на 90.08 («управленческие»), без него — на 90.02
#    («себестоимость»). У пилота директ-костинг выключен, и отчёт по счетам показывал
#    управленческие расходы нулём, а себестоимость раздутой на 954 295 ₽. Поэтому
#    дебет 90.02 разбирается по КРЕДИТУ: товар (41/43/45/20) — это себестоимость,
#    25/26 — управленческие, 44 — коммерческие. Форма перестаёт зависеть от политики.
#
# 2. ОБОРОТ ДВУСТОРОННИЙ. Возврат покупателю, оформленный обратной записью
#    (Дт 90.01 Кт 62), а не сторно, раньше не вычитался — выручка завышалась на всю
#    сумму возврата. Теперь каждая строка считается как «своя сторона минус обратная».
#
# 3. НАЛОГ БЕЗ ПРИВЯЗКИ К ОДНОМУ СУБСЧЁТУ. Ловим любой Дт 99 → Кт 68 (прибыль, УСН,
#    ЕСХН, штрафы в бюджет) минус обратную ногу Кт 99 ← Дт 68 (условный доход при
#    убытке, корректировки ПБУ 18/02). Привязка к 68.04 давала компании на УСН строку
#    «Налог» всегда нулём.

# Счета результата. Сравнение идёт по префиксу с точкой ИЛИ точным равенством:
# «90.01.1» и «90.01» ловятся, а «901» из самописного плана — нет, и это честнее
# молчаливого нуля (см. `_pnl_plan_ok`).
SALES_ACC = "90"            # продажи: 90.01 выручка, 90.02 себестоимость, 90.03 НДС…
OTHER_ACC = "91"            # прочие доходы и расходы
RESULT_ACC = "99"           # прибыли и убытки
GOODS_ACCS = ("41", "43", "45", "20", "21", "23")   # товар, продукция, производство
INDIRECT_ACCS = ("25", "26")                        # управленческие
SELLING_ACCS = ("44",)                              # коммерческие
BUDGET_ACCS = ("68", "69")                          # расчёты с бюджетом и фондами
LOAN_ACCS = ("66", "67")                            # кредиты и займы — проценты


def _acc(col: str, prefix: str) -> str:
    """Условие «счёт равен префиксу или начинается с него через точку»."""
    return f"({col} = '{prefix}' OR {col} LIKE '{prefix}.%')"


def _acc_any(col: str, prefixes: tuple[str, ...]) -> str:
    return "(" + " OR ".join(_acc(col, p) for p in prefixes) + ")"


async def _pnl_rows(db: AsyncSession, cid, date_from: str | None, date_to: str | None
                    ) -> list[dict[str, Any]]:
    """Помесячные обороты счетов результата — основа отчёта.

    Даты приводятся объектом `date` (утилита `_day`): `gl_entries.entry_date` — колонка
    типа date, а период приезжает строкой, и драйвер сравнивать их отказывается. В
    `accounting_docs` дата хранится строкой, поэтому там та же запись работает.
    """
    p: dict[str, Any] = {"cid": str(cid)}
    where = ""
    if date_from:
        where += " AND entry_date >= :df"
        p["df"] = _day(date_from)
    if date_to:
        where += " AND entry_date <= :dt"
        p["dt"] = _day(date_to)

    sales_dt, sales_kt = _acc("account_dt", SALES_ACC), _acc("account_kt", SALES_ACC)
    other_dt, other_kt = _acc("account_dt", OTHER_ACC), _acc("account_kt", OTHER_ACC)
    res_dt, res_kt = _acc("account_dt", RESULT_ACC), _acc("account_kt", RESULT_ACC)
    budget_kt, budget_dt = _acc_any("account_kt", BUDGET_ACCS), _acc_any("account_dt", BUDGET_ACCS)

    def pair(side_dt: str, side_kt: str) -> str:
        """Оборот «прямой минус обратный» одной строкой SQL."""
        return (f"coalesce(sum(amount) FILTER (WHERE {side_dt}), 0)"
                f" - coalesce(sum(amount) FILTER (WHERE {side_kt}), 0)")

    sql = f"""
        SELECT to_char(entry_date, 'YYYY-MM') AS month,
               -- Выручка: кредит 90.01 минус обратные записи (возвраты), закрытие
               -- на 90.09 не в счёт.
               {pair(f"{_acc('account_kt', '90.01')} AND NOT {sales_dt}",
                     f"{_acc('account_dt', '90.01')} AND NOT {sales_kt}")},
               {pair(f"{_acc('account_dt', '90.03')} AND NOT {sales_kt}",
                     f"{_acc('account_kt', '90.03')} AND NOT {sales_dt}")},
               -- Акцизы и экспортные пошлины — тоже вычет из выручки.
               {pair(f"({_acc('account_dt', '90.04')} OR {_acc('account_dt', '90.05')}) AND NOT {sales_kt}",
                     f"({_acc('account_kt', '90.04')} OR {_acc('account_kt', '90.05')}) AND NOT {sales_dt}")},
               -- Себестоимость ТОВАРНАЯ: 90.02 с кредита запасов и производства.
               {pair(f"{_acc('account_dt', '90.02')} AND {_acc_any('account_kt', GOODS_ACCS)}",
                     f"{_acc('account_kt', '90.02')} AND {_acc_any('account_dt', GOODS_ACCS)}")},
               -- Коммерческие: 90.07 и та часть 90.02, что пришла с 44.
               {pair(f"({_acc('account_dt', '90.07')} OR ({_acc('account_dt', '90.02')} AND {_acc_any('account_kt', SELLING_ACCS)})) AND NOT {sales_kt}",
                     f"({_acc('account_kt', '90.07')}) AND NOT {sales_dt}")},
               -- Управленческие: 90.08 и та часть 90.02, что пришла с 25/26 (у
               -- компании без директ-костинга это единственный путь).
               {pair(f"({_acc('account_dt', '90.08')} OR ({_acc('account_dt', '90.02')} AND {_acc_any('account_kt', INDIRECT_ACCS)})) AND NOT {sales_kt}",
                     f"({_acc('account_kt', '90.08')}) AND NOT {sales_dt}")},
               -- Прочие доходы и расходы; проценты по займам выделяются отдельно.
               {pair(f"{_acc('account_kt', '91.01')} AND NOT {other_dt}",
                     f"{_acc('account_dt', '91.01')} AND NOT {other_kt}")},
               {pair(f"{_acc('account_dt', '91.02')} AND NOT {other_kt} AND NOT {_acc_any('account_kt', LOAN_ACCS)}",
                     f"{_acc('account_kt', '91.02')} AND NOT {other_dt} AND NOT {_acc_any('account_dt', LOAN_ACCS)}")},
               {pair(f"{_acc('account_dt', '91.02')} AND {_acc_any('account_kt', LOAN_ACCS)}",
                     f"{_acc('account_kt', '91.02')} AND {_acc_any('account_dt', LOAN_ACCS)}")},
               -- Налог: любой Дт 99 → Кт 68 минус обратная нога.
               {pair(f"{res_dt} AND {budget_kt}", f"{res_kt} AND {budget_dt}")},
               -- Себестоимость, у которой источник не опознан: услуги, списанные
               -- сразу на 90.02 минуя запасы и затратные счета.
               {pair(f"{_acc('account_dt', '90.02')} AND NOT {_acc_any('account_kt', GOODS_ACCS)}"
                     f" AND NOT {_acc_any('account_kt', INDIRECT_ACCS)}"
                     f" AND NOT {_acc_any('account_kt', SELLING_ACCS)} AND NOT {sales_kt}",
                     f"{_acc('account_kt', '90.02')} AND NOT {_acc_any('account_dt', GOODS_ACCS)}"
                     f" AND NOT {_acc_any('account_dt', INDIRECT_ACCS)}"
                     f" AND NOT {_acc_any('account_dt', SELLING_ACCS)} AND NOT {sales_dt}")}
          FROM gl_entries
         WHERE company_id = :cid{where}
         GROUP BY 1 ORDER BY 1
    """
    return [{
        "month": r[0],
        "revenue": _num(r[1]), "vat": _num(r[2]), "excise": _num(r[3]),
        "cogs": _num(r[4]), "commercial": _num(r[5]), "admin": _num(r[6]),
        "otherIncome": _num(r[7]), "otherExpense": _num(r[8]), "interest": _num(r[9]),
        "tax": _num(r[10]), "cogsOther": _num(r[11]),
    } for r in (await db.execute(text(sql), p)).all()]


def _pnl_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Свод отчёта: от выручки до чистой прибыли."""
    keys = ("revenue", "vat", "excise", "cogs", "cogsOther", "commercial", "admin",
            "otherIncome", "otherExpense", "interest", "tax")
    t: dict[str, Any] = {k: round(sum(r[k] for r in rows), 2) for k in keys}
    t["net"] = round(t["revenue"] - t["vat"] - t["excise"], 2)
    t["cogsTotal"] = round(t["cogs"] + t["cogsOther"], 2)
    t["gross"] = round(t["net"] - t["cogsTotal"], 2)
    t["operating"] = round(t["gross"] - t["commercial"] - t["admin"], 2)
    t["beforeTax"] = round(
        t["operating"] + t["otherIncome"] - t["otherExpense"] - t["interest"], 2)
    t["profit"] = round(t["beforeTax"] - t["tax"], 2)
    # Рентабельность считаем от выручки БЕЗ НДС: налог собирается в пользу бюджета и
    # доходом компании не является.
    for name, val in (("grossPct", t["gross"]), ("operatingPct", t["operating"]),
                      ("profitPct", t["profit"])):
        t[name] = round(val / t["net"] * 100, 1) if t["net"] else None
    return t


async def _pnl_light(db: AsyncSession, cid, date_from: str | None, date_to: str | None
                     ) -> dict[str, Any]:
    """Только те итоги отчёта, что нужны налоговым экранам: выручка и прибыль.

    Отдельная функция, а не полный `_pnl_rows`: тот разворачивает помесячный ряд по
    всем строкам формы, и «Налоги» сканировали регистр вторым разом за один запрос
    ради двух чисел.
    """
    rows = await _pnl_rows(db, cid, date_from, date_to)
    return _pnl_totals(rows)


@router.get("/pnl")
async def pnl(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Отчёт о финансовых результатах: от выручки до чистой прибыли, помесячно.

    Сверка честная: рядом с расчётной прибылью стоит то, что бухгалтерия закрыла на
    84 счёт (реформация баланса), и перечислены три причины расхождения — незакрытый
    период, обороты 99 мимо наших строк, нетиповой план счетов.
    """
    cid = await assert_company_member(company_id, current_user, db)
    rows = await _pnl_rows(db, cid, date_from, date_to)

    for r in rows:
        t = _pnl_totals([r])
        r.update({k: t[k] for k in ("net", "cogsTotal", "gross", "operating",
                                    "beforeTax", "profit")})

    years: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        years.setdefault(r["month"][:4], []).append(r)

    p: dict[str, Any] = {"cid": str(cid)}
    where = ""
    if date_from:
        where += " AND entry_date >= :df"
        p["df"] = _day(date_from)
    if date_to:
        where += " AND entry_date <= :dt"
        p["dt"] = _day(date_to)
    closed = (await db.execute(text(f"""
        SELECT coalesce(sum(amount) FILTER (
                 WHERE {_acc('account_dt', '99')} AND {_acc('account_kt', '84')}), 0)
             - coalesce(sum(amount) FILTER (
                 WHERE {_acc('account_dt', '84')} AND {_acc('account_kt', '99')}), 0)
          FROM gl_entries WHERE company_id = :cid{where}
    """), p)).scalar_one()

    # Признак «план счетов опознан»: если оборотов по 90 нет вовсе, отчёт покажет
    # нули — и это должно читаться как «счета другие», а не «продаж не было».
    plan_ok = (await db.execute(text(f"""
        SELECT count(*) FROM gl_entries
         WHERE company_id = :cid
           AND ({_acc('account_dt', '90')} OR {_acc('account_kt', '90')}){where}
    """), p)).scalar_one()

    totals = _pnl_totals(rows)
    return {
        "months": rows,
        "totals": totals,
        "years": [{"year": y, **_pnl_totals(rs)} for y, rs in sorted(years.items())],
        "closedToRetained": _num(closed),
        "salesEntries": plan_ok,
        # Директ-костинг: закрывается ли 26 напрямую на 90.08. Экран поясняет, почему
        # управленческие расходы могли «сидеть» в себестоимости.
        "adminInCogs": totals["admin"] > 0 and (await db.execute(text(f"""
            SELECT count(*) FROM gl_entries
             WHERE company_id = :cid AND {_acc('account_dt', '90.02')}
               AND {_acc_any('account_kt', INDIRECT_ACCS)}{where}
        """), p)).scalar_one() > 0,
    }


@router.get("/expenses")
async def expenses(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Из чего сложились затраты: статья, счёт и источник.

    Статья берётся из СУБКОНТО оборотов (`gl_turnovers`), а не из имени
    корреспондирующего счёта: по счёту ответ на «за что платим» звучит как «поставщику»,
    и аренда, связь, реклама и ГСМ не различаются. Гранулярность субконто — месяц,
    для этого экрана достаточно.

    Из выборки исключены взаимные закрытия затратных счетов (Дт 44 Кт 26, Дт 20 Кт 25):
    иначе одна и та же затрата считается дважды — сперва при начислении, потом при
    переносе. Списание на 90/91 тоже не в счёт — это уже признание расхода.
    """
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid)}
    where = ""
    if date_from:
        where += " AND e.entry_date >= :df"
        p["df"] = _day(date_from)
    if date_to:
        where += " AND e.entry_date <= :dt"
        p["dt"] = _day(date_to)

    COST_ACCS = INDIRECT_ACCS + SELLING_ACCS + ("20", "23", "28", "29")
    cost_dt = _acc_any("e.account_dt", COST_ACCS)
    cost_kt = _acc_any("e.account_kt", COST_ACCS)
    # Расход, признанный сразу на 90.02/91.02 минуя затратные счета, тоже затрата.
    direct_dt = f"({_acc('e.account_dt', '91.02')})"
    outer_kt = (f"NOT {cost_kt} AND NOT {_acc('e.account_kt', '90')}"
                f" AND NOT {_acc('e.account_kt', '91')}")

    rows = [{
        "account": r[0], "accountName": r[1], "source": r[2], "sourceName": r[3],
        "amount": _num(r[4]), "entries": r[5],
    } for r in (await db.execute(text(f"""
        SELECT e.account_dt, max(ad.name), e.account_kt, max(ak.name),
               sum(e.amount), count(*)
          FROM gl_entries e
          LEFT JOIN gl_accounts ad ON ad.company_id = e.company_id AND ad.code = e.account_dt
          LEFT JOIN gl_accounts ak ON ak.company_id = e.company_id AND ak.code = e.account_kt
         WHERE e.company_id = :cid AND ({cost_dt} OR {direct_dt}) AND {outer_kt}{where}
         GROUP BY e.account_dt, e.account_kt
         ORDER BY sum(e.amount) DESC
    """), p)).all()]

    months = [{
        "month": r[0], "amount": _num(r[1]),
    } for r in (await db.execute(text(f"""
        SELECT to_char(e.entry_date, 'YYYY-MM'), sum(e.amount)
          FROM gl_entries e
         WHERE e.company_id = :cid AND ({cost_dt} OR {direct_dt}) AND {outer_kt}{where}
         GROUP BY 1 ORDER BY 1
    """), p)).all()]

    # Статьи затрат из субконто. `dt1` у затратных счетов и есть статья, `dt2` пуст.
    # Период у оборотов — год и месяц числами, а не датой: сравниваем по паре.
    pt: dict[str, Any] = {"cid": str(cid)}
    twhere = ""
    if date_from:
        twhere += " AND (t.period_year, t.period_month) >= (:fy, :fm)"
        pt["fy"], pt["fm"] = int(date_from[:4]), int(date_from[5:7])
    if date_to:
        twhere += " AND (t.period_year, t.period_month) <= (:ty, :tm)"
        pt["ty"], pt["tm"] = int(date_to[:4]), int(date_to[5:7])
    items = [{
        "item": r[0] or "Без статьи", "account": r[1],
        "amount": _num(r[2]), "months": r[3],
    } for r in (await db.execute(text(f"""
        SELECT t.dt1, t.account_dt, sum(t.amount),
               count(DISTINCT (t.period_year, t.period_month))
          FROM gl_turnovers t
         WHERE t.company_id = :cid
           AND {_acc_any('t.account_dt', COST_ACCS)}
           AND NOT {_acc_any('t.account_kt', COST_ACCS)}
           AND NOT {_acc('t.account_kt', '90')} AND NOT {_acc('t.account_kt', '91')}{twhere}
         GROUP BY 1, 2 ORDER BY 3 DESC
    """), pt)).all()]

    by_account: dict[str, dict[str, Any]] = {}
    for r in rows:
        a = by_account.setdefault(r["account"], {
            "account": r["account"], "name": r["accountName"], "amount": 0.0, "sources": [],
        })
        a["amount"] += r["amount"]
        a["sources"].append(r)
    accounts = sorted(by_account.values(), key=lambda a: -a["amount"])

    return {
        "accounts": accounts,
        "rows": rows,
        "items": items,
        "months": months,
        "total": round(sum(r["amount"] for r in rows), 2),
        "itemsTotal": round(sum(i["amount"] for i in items), 2),
    }


@router.get("/taxes")
async def taxes(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Налоги и взносы: начислено, уплачено, нагрузка.

    Три ловушки единого налогового счёта, из-за которых прежний расчёт врал:

    1. Перенос на ЕНС (Дт 68.02 Кт 68.90) — это тоже кредит 68, и суммирование всего
       кредита считало начисление дважды. Внутренние переносы 68↔68 и 69→68 исключены.
    2. С 2023 года ВСЕ платежи идут Дт 68.90 Кт 51, поэтому «уплачено» по конкретному
       налогу нулевое, а разница показывала всю начисленную сумму как долг. Уплату
       считаем по ЕНС отдельной строкой, а не размазываем по видам налогов.
    3. Возврат из бюджета (Дт 51 Кт 68) — не начисление, поэтому оборот двусторонний.
    """
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid)}
    where = ""
    if date_from:
        where += " AND e.entry_date >= :df"
        p["df"] = _day(date_from)
    if date_to:
        where += " AND e.entry_date <= :dt"
        p["dt"] = _day(date_to)

    budget_kt = _acc_any("e.account_kt", BUDGET_ACCS)
    budget_dt = _acc_any("e.account_dt", BUDGET_ACCS)
    money_kt = "(" + " OR ".join(_acc("e.account_kt", a) for a in ("50", "51", "52", "55")) + ")"

    rows = [{
        "account": r[0], "name": r[1] or r[0], "accrued": _num(r[2]), "entries": r[3],
    } for r in (await db.execute(text(f"""
        SELECT e.account_kt, max(a.name),
               sum(e.amount) - coalesce((
                 SELECT sum(x.amount) FROM gl_entries x
                  WHERE x.company_id = e.company_id AND x.account_dt = e.account_kt
                    AND {_acc_any('x.account_kt', BUDGET_ACCS)}), 0),
               count(*)
          FROM gl_entries e
          LEFT JOIN gl_accounts a ON a.company_id = e.company_id AND a.code = e.account_kt
         WHERE e.company_id = :cid AND {budget_kt} AND NOT {budget_dt}{where}
         GROUP BY e.account_kt, e.company_id ORDER BY 3 DESC
    """), p)).all()]

    paid = _num((await db.execute(text(f"""
        SELECT coalesce(sum(e.amount), 0) - coalesce((
                 SELECT sum(x.amount) FROM gl_entries x
                  WHERE x.company_id = :cid AND {_acc_any('x.account_kt', BUDGET_ACCS)}
                    AND ({_acc('x.account_dt', '51')} OR {_acc('x.account_dt', '50')})), 0)
          FROM gl_entries e
         WHERE e.company_id = :cid AND {budget_dt} AND {money_kt}{where}
    """), p)).scalar_one())

    months = [{
        "month": r[0], "accrued": _num(r[1]), "paid": _num(r[2]),
    } for r in (await db.execute(text(f"""
        SELECT to_char(e.entry_date, 'YYYY-MM'),
               coalesce(sum(e.amount) FILTER (WHERE {budget_kt} AND NOT {budget_dt}), 0),
               coalesce(sum(e.amount) FILTER (WHERE {budget_dt} AND {money_kt}), 0)
          FROM gl_entries e
         WHERE e.company_id = :cid
           AND ({budget_kt} OR {budget_dt}){where}
         GROUP BY 1 ORDER BY 1
    """), p)).all()]

    # Отчёт целиком здесь не нужен: нагрузке хватает выручки без НДС, а эффективной
    # ставке — налога и прибыли до него. Полный `_pnl_rows` разворачивал весь регистр
    # вторым разом за один запрос.
    totals = await _pnl_light(db, cid, date_from, date_to)
    accrued = round(sum(r["accrued"] for r in rows), 2)

    # Раскладка по смыслу: что в отчёте о результате, что транзит, что удержание.
    def match(prefixes: tuple[str, ...]) -> float:
        return round(sum(r["accrued"] for r in rows
                         if any(r["account"] == a or r["account"].startswith(a + ".")
                                for a in prefixes)), 2)

    vat = match(("68.02",))
    ndfl = match(("68.01",))
    contributions = match(("69",))
    profit_tax = totals["tax"]
    return {
        "rows": rows,
        "months": months,
        "accrued": accrued,
        "paid": paid,
        "revenueNet": totals["net"],
        # Нагрузка по методике ФНС: уплаченные налоги (с НДФЛ агента, без страховых
        # взносов) к выручке без НДС.
        "loadPct": round(paid / totals["net"] * 100, 1) if totals["net"] else None,
        "groups": {
            "profitTax": profit_tax,     # строка отчёта о результате
            "vat": vat,                  # транзитный: не расход компании
            "ndfl": ndfl,                # удержание у работника
            "contributions": contributions,  # часть затрат на персонал
        },
        # Эффективная ставка имеет смысл только на ОСНО и при положительной прибыли.
        "etrPct": (round(profit_tax / totals["beforeTax"] * 100, 1)
                   if totals["beforeTax"] > 0 else None),
    }


# ── Провал из строки отчёта в проводки ───────────────────────────────────────
# «Себестоимость 15 млн» — это ответ, из которого нельзя проверить. Экран обязан
# доводить до проводок, иначе цифре верят или не верят, но не разбирают.

# Что стоит за строкой отчёта: пара «дебет / кредит» в терминах префиксов счетов.
PNL_DRILL: dict[str, dict[str, Any]] = {
    "revenue":      {"kt": ("90.01",), "not_dt": ("90",), "label": "Выручка"},
    "vat":          {"dt": ("90.03",), "not_kt": ("90",), "label": "НДС с продаж"},
    "cogs":         {"dt": ("90.02",), "kt": ("41", "43", "45", "20", "21", "23"),
                     "label": "Себестоимость товаров и продукции"},
    "cogsOther":    {"dt": ("90.02",), "not_kt": ("41", "43", "45", "20", "21", "23",
                                                  "25", "26", "44", "90"),
                     "label": "Прочая себестоимость"},
    "commercial":   {"dt": ("90.07",), "not_kt": ("90",), "label": "Коммерческие расходы"},
    "admin":        {"dt": ("90.08", "90.02"), "kt": ("25", "26"),
                     "label": "Управленческие расходы"},
    "otherIncome":  {"kt": ("91.01",), "not_dt": ("91",), "label": "Прочие доходы"},
    "otherExpense": {"dt": ("91.02",), "not_kt": ("91", "66", "67"), "label": "Прочие расходы"},
    "interest":     {"dt": ("91.02",), "kt": ("66", "67"), "label": "Проценты к уплате"},
    "tax":          {"dt": ("99",), "kt": ("68",), "label": "Налог"},
}


@router.get("/pnl-entries")
async def pnl_entries(
    company_id: str,
    line: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Проводки, из которых сложилась строка отчёта о результате."""
    cid = await assert_company_member(company_id, current_user, db)
    rule = PNL_DRILL.get(line)
    if rule is None:
        raise HTTPException(404, f"Строка отчёта «{line}» не раскрывается")

    conds = []
    if rule.get("dt"):
        conds.append(_acc_any("e.account_dt", rule["dt"]))
    if rule.get("kt"):
        conds.append(_acc_any("e.account_kt", rule["kt"]))
    if rule.get("not_dt"):
        conds.append("NOT " + _acc_any("e.account_dt", rule["not_dt"]))
    if rule.get("not_kt"):
        conds.append("NOT " + _acc_any("e.account_kt", rule["not_kt"]))
    where = " AND ".join(conds)

    p: dict[str, Any] = {"cid": str(cid), "lim": limit}
    if date_from:
        where += " AND e.entry_date >= :df"
        p["df"] = _day(date_from)
    if date_to:
        where += " AND e.entry_date <= :dt"
        p["dt"] = _day(date_to)

    total, count = (await db.execute(text(f"""
        SELECT coalesce(sum(e.amount), 0), count(*)
          FROM gl_entries e WHERE e.company_id = :cid AND {where}
    """), p)).one()

    rows = [{
        "date": r[0].isoformat() if r[0] else None,
        "accountDt": r[1], "accountKt": r[2], "amount": _num(r[3]),
        "docKind": r[4], "docTitle": r[5], "content": r[6],
    } for r in (await db.execute(text(f"""
        SELECT e.entry_date, e.account_dt, e.account_kt, e.amount,
               e.doc_kind, e.doc_title, e.content
          FROM gl_entries e WHERE e.company_id = :cid AND {where}
         ORDER BY e.entry_date DESC, e.id LIMIT :lim
    """), p)).all()]

    return {
        "line": line, "label": rule["label"],
        "rows": rows, "total": _num(total), "count": count, "shown": len(rows),
    }


# ── Мост «затраты → отчёт» ───────────────────────────────────────────────────
# Раздел «Расходы» показывает затраты в момент НАЧИСЛЕНИЯ на счетах учёта, отчёт —
# в момент СПИСАНИЯ на 90 и 91. Это две разные цифры по построению, и без моста между
# ними человек считает, что одна из них ошибка.

@router.get("/cost-bridge")
async def cost_bridge(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сколько затрат начислено, сколько списано в результат и что осталось."""
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid)}
    where = ""
    if date_from:
        where += " AND e.entry_date >= :df"
        p["df"] = _day(date_from)
    if date_to:
        where += " AND e.entry_date <= :dt"
        p["dt"] = _day(date_to)

    COST_ACCS = INDIRECT_ACCS + SELLING_ACCS + ("20", "23", "28", "29")
    cost_dt = _acc_any("e.account_dt", COST_ACCS)
    cost_kt = _acc_any("e.account_kt", COST_ACCS)
    result_kt = f"({_acc('e.account_kt', '90')} OR {_acc('e.account_kt', '91')})"
    result_dt = f"({_acc('e.account_dt', '90')} OR {_acc('e.account_dt', '91')})"

    rows = [{
        "account": r[0], "name": r[1],
        "accrued": _num(r[2]), "written": _num(r[3]), "moved": _num(r[4]),
    } for r in (await db.execute(text(f"""
        SELECT acc.code, max(acc.name),
               -- начислено: пришло на затратный счёт извне контура
               coalesce(sum(e.amount) FILTER (
                 WHERE e.account_dt = acc.code AND NOT {cost_kt} AND NOT {result_kt}), 0),
               -- списано в результат: ушло на 90 или 91
               coalesce(sum(e.amount) FILTER (
                 WHERE e.account_kt = acc.code AND {result_dt}), 0),
               -- перенесено внутри контура затрат (26 → 44 и подобное)
               coalesce(sum(e.amount) FILTER (
                 WHERE e.account_kt = acc.code AND {cost_dt}), 0)
          FROM gl_accounts acc
          LEFT JOIN gl_entries e ON e.company_id = acc.company_id
               AND (e.account_dt = acc.code OR e.account_kt = acc.code){where}
         WHERE acc.company_id = :cid AND {_acc_any('acc.code', COST_ACCS)}
         GROUP BY acc.code
        HAVING coalesce(sum(e.amount), 0) <> 0
         ORDER BY 3 DESC
    """), p)).all()]

    for r in rows:
        # Остаток на счёте: начислено минус списанное и перенесённое. У 44 и 26 он
        # обычно нулевой (закрываются каждый месяц), у 20 — это незавершёнка.
        r["rest"] = round(r["accrued"] - r["written"] - r["moved"], 2)

    pnl_rows = await _pnl_rows(db, cid, date_from, date_to)
    t = _pnl_totals(pnl_rows)
    return {
        "rows": rows,
        "accrued": round(sum(r["accrued"] for r in rows), 2),
        "written": round(sum(r["written"] for r in rows), 2),
        "rest": round(sum(r["rest"] for r in rows), 2),
        # Что из этого попало в отчёт: коммерческие плюс управленческие.
        "inPnl": round(t["commercial"] + t["admin"], 2),
    }


# ── Качество данных продукта ─────────────────────────────────────────────────
# Волна 5. Отдельно от «Данных» пространства: там качество слоя целиком, здесь —
# ровно то, что портит цифры «Реализации». Проверка = вопрос заказчику, поэтому
# рядом с числом лежит объяснение, чем это грозит.

@router.get("/revenue-quality")
async def revenue_quality(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Проверки, от которых зависят цифры продукта: что и почему может врать."""
    cid = await assert_company_member(company_id, current_user, db)
    p = {"cid": str(cid)}

    async def one(sql: str) -> int:
        return int((await db.execute(text(sql), p)).scalar_one() or 0)

    checks = [
        {
            "key": "no_lines", "title": "Реализации без строк",
            "why": "сумма документа есть, а что продано — неизвестно: позиция не попадёт "
                   "ни в номенклатуру, ни в маржу",
            # jsonb_array_length падает, если `lines` приехал не массивом, — проверка
            # качества данных обязана переживать плохие данные, ради которых она и есть.
            "count": await one("""SELECT count(*) FROM accounting_docs
                                   WHERE company_id = :cid AND doc_type = 'sale'
                                     AND coalesce(CASE WHEN jsonb_typeof(lines) = 'array'
                                                       THEN jsonb_array_length(lines) END, 0) = 0"""),
        },
        {
            "key": "no_counterparty", "title": "Реализации без контрагента",
            "why": "документ не попадёт ни в одного покупателя, разрез по клиентам занижен",
            "count": await one("""SELECT count(*) FROM accounting_docs
                                   WHERE company_id = :cid AND doc_type = 'sale'
                                     AND counterparty_id IS NULL"""),
        },
        {
            "key": "no_contract", "title": "Реализации без договора",
            "why": "не попадут в разрез по договорам; в 1С основание не заполнено",
            "count": await one("""SELECT count(*) FROM accounting_docs
                                   WHERE company_id = :cid AND doc_type = 'sale'
                                     AND contract_id IS NULL"""),
        },
        {
            "key": "no_code", "title": "Строки без кода номенклатуры",
            "why": "позиция не сводится со справочником и с закупкой: ни ABC, ни маржи",
            "count": await one("""SELECT count(*) FROM accounting_docs d,
                                       jsonb_array_elements(d.lines) ln
                                   WHERE d.company_id = :cid AND d.doc_type = 'sale'
                                     AND coalesce(btrim(ln->>'code'), '') = ''"""),
        },
        {
            "key": "no_price", "title": "Строки без цены",
            "why": "нет цены — нет истории цены и наценки по позиции",
            "count": await one("""SELECT count(*) FROM accounting_docs d,
                                       jsonb_array_elements(d.lines) ln
                                   WHERE d.company_id = :cid AND d.doc_type = 'sale'
                                     AND ln->>'price' IS NULL"""),
        },
        {
            "key": "negative", "title": "Реализации с отрицательной суммой",
            "why": "скорее всего возврат, проведённый реализацией: выручка занижена или задвоена",
            "count": await one("""SELECT count(*) FROM accounting_docs
                                   WHERE company_id = :cid AND doc_type = 'sale'
                                     AND amount < 0"""),
        },
        {
            "key": "open_period", "title": "Реализации в незакрытом периоде",
            "why": "период ещё может измениться в 1С — цифры этих месяцев не окончательные",
            # Статус берём из РЕГИСТРА периодов, а не из поля документа: у пилота
            # `period_status` заполнен у 99 документов из 3256, и проверка по нему
            # объявляла незакрытыми все 218 реализаций при 61 закрытом месяце.
            "count": await one("""
                SELECT count(*) FROM accounting_docs d
                 LEFT JOIN periods p ON p.company_id = d.company_id
                       -- Каст только там, где дата похожа на дату: пустая строка в
                       -- `date` роняла весь экран качества с 500-й ошибкой.
                       AND d.date ~ '^\\d{4}-\\d{2}'
                       AND p.year = substr(d.date, 1, 4)::int
                       AND p.month = substr(d.date, 6, 2)::int
                 WHERE d.company_id = :cid AND d.doc_type = 'sale'
                   AND coalesce(p.status, 'open') <> 'closed'"""),
        },
        {
            "key": "code_reuse", "title": "Коды номенклатуры с разными наименованиями",
            "why": "под одним кодом лежат разные товары: остатки, маржа и сравнение цен "
                   "по такому коду складывают несравнимое",
            "count": await one("""
                SELECT count(*) FROM (
                  SELECT btrim(ln->>'code') code
                    FROM accounting_docs d, jsonb_array_elements(d.lines) ln
                   WHERE d.company_id = :cid AND d.doc_type IN ('sale', 'purchase')
                     AND coalesce(btrim(ln->>'code'), '') <> ''
                   GROUP BY 1 HAVING count(DISTINCT ln->>'name') > 1) z"""),
        },
        {
            "key": "no_purchase", "title": "Проданные позиции без закупки",
            "why": "себестоимость неизвестна, маржа по ним не считается",
            "count": await one("""
                WITH l AS (
                  SELECT d.doc_type, jsonb_array_elements(d.lines) ln
                    FROM accounting_docs d
                   WHERE d.company_id = :cid AND d.doc_type IN ('sale', 'purchase')
                ), x AS (
                  SELECT doc_type, btrim(ln->>'code') code FROM l
                   WHERE coalesce(btrim(ln->>'code'), '') <> ''
                )
                SELECT count(*) FROM (
                  SELECT code FROM x GROUP BY code
                   HAVING count(*) FILTER (WHERE doc_type = 'sale') > 0
                      AND count(*) FILTER (WHERE doc_type = 'purchase') = 0) z"""),
        },
        {
            "key": "invoice_unpaid_old", "title": "Счета старше года без оплаты",
            "why": "либо деньги не пришли, либо оплата не сведена регистром — воронка врёт",
            "count": await one("""
                SELECT count(*) FROM accounting_docs d
                 WHERE d.company_id = :cid AND d.doc_type = 'invoice_out'
                   AND d.date < to_char(now() - interval '1 year', 'YYYY-MM-DD')
                   AND NOT EXISTS (SELECT 1 FROM invoice_payments p
                                    WHERE p.invoice_doc_id = d.id)"""),
        },
    ]

    total_sales = await one("""SELECT count(*) FROM accounting_docs
                                WHERE company_id = :cid AND doc_type = 'sale'""")
    return {
        "checks": checks,
        "salesDocs": total_sales,
        "problems": sum(1 for c in checks if c["count"] > 0),
    }


# ── Деньги: сроки оплаты, поток и договоры ───────────────────────────────────
# Волна 3. Выручка отвечает «сколько продали», деньги — «когда за это заплатили».
# Дебиторку заново не считаем: сальдо расчётов уже отдаёт `/settlements` (оно взято
# из регистра источника, а не выведено из наших проводок — зачёты авансов живут
# только там). Здесь то, чего в пространстве нет: срок оплаты, движение по счёту и
# разрез по договорам.

# Корзины срока оплаты. Границы выбраны по обороту документов: аванс и оплата в
# течение недели — «сразу», месяц — типовая отсрочка, дальше начинается разговор
# с покупателем. Пороги стоят одним списком: сдвинуть их — здесь, а не в трёх
# выборках.
PAY_BUCKETS: list[tuple[str, str, int, int]] = [
    ("advance", "Аванс (до отгрузки)", -100000, -1),
    ("week", "До 7 дней", 0, 7),
    ("month", "8–30 дней", 8, 30),
    ("q", "31–60 дней", 31, 60),
    ("late", "61–90 дней", 61, 90),
    ("overdue", "Больше 90 дней", 91, 100000),
]


@router.get("/payment-terms")
async def payment_terms(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Через сколько дней платят по счетам: распределение, средний срок, покупатели.

    Связь «счёт ↔ платёж» есть только в регистре «Оплата счетов» (`invoice_payments`):
    по суммам и датам её не восстановить — один платёж закрывает несколько счетов и
    наоборот. Отсюда и ограничение экрана: он видит ровно те счета, что регистр свёл.
    """
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid)}
    where = ""
    if date_from:
        where += " AND d.date >= :df"
        p["df"] = date_from
    if date_to:
        where += " AND d.date <= :dt"
        p["dt"] = date_to

    # Единица счёта — СЧЁТ, а не платёж. Раньше запрос шёл от `invoice_payments`, и
    # счёт, закрытый тремя траншами, давал три строки: три попадания в корзины, тройной
    # вес клиента и срок, посчитанный по частичным платежам. На пилоте 113 платежей
    # приходятся на 108 счетов, а плитка называлась «Счетов с оплатой».
    #
    # Срок считаем по ПОСЛЕДНЕМУ платежу: счёт закрыт тогда, когда пришли все деньги.
    rows = [{
        "id": str(r[0]), "number": r[1], "date": r[2], "paidAt": r[3],
        "counterparty": r[4], "counterpartyId": str(r[5]) if r[5] else None,
        "amount": _num(r[6]), "days": int(r[7]), "payments": r[8],
        # Корзину считает сервер: пороги живут здесь (PAY_BUCKETS), и вторая их копия
        # на клиенте разъехалась бы при первом же сдвиге границы — молча.
        "bucket": next((k for k, _, lo, hi in PAY_BUCKETS if lo <= int(r[7]) <= hi),
                       PAY_BUCKETS[-1][0]),
    } for r in (await db.execute(text(f"""
        SELECT d.id, max(d.number), max(d.date), max(p.paid_at),
               max(d.counterparty_name), max(d.counterparty_id::text),
               sum(p.amount), (max(p.paid_at)::date - max(d.date)::date) AS days,
               count(*)
          FROM invoice_payments p
          JOIN accounting_docs d ON d.id = p.invoice_doc_id
         WHERE p.company_id = :cid AND p.paid_at IS NOT NULL
           AND coalesce(d.date, '') <> ''{where}
         GROUP BY d.id
         ORDER BY days DESC
    """), p)).all()]

    # Платежи, ссылающиеся на документ, которого в выгрузке нет: молча выпадают из
    # всех расчётов, поэтому их число возвращаем отдельно (на пилоте 2 на 345 758 ₽).
    orphans = (await db.execute(text("""
        SELECT count(*), coalesce(sum(amount), 0) FROM invoice_payments p
         WHERE p.company_id = :cid
           AND (p.invoice_doc_id IS NULL
                OR NOT EXISTS (SELECT 1 FROM accounting_docs d WHERE d.id = p.invoice_doc_id))
    """), {"cid": str(cid)})).one()

    buckets = [{
        "key": key, "label": label,
        "count": sum(1 for r in rows if lo <= r["days"] <= hi),
        "amount": round(sum(r["amount"] for r in rows if lo <= r["days"] <= hi), 2),
    } for key, label, lo, hi in PAY_BUCKETS]

    # Медиана рядом со средним не для красоты: у пилота средний срок 160 дней при
    # медиане втрое меньше — среднее тянут единичные счета, висящие больше года, и
    # по нему нельзя договариваться об отсрочке.
    days = sorted(r["days"] for r in rows)
    median = 0.0
    if days:
        mid = len(days) // 2
        median = float(days[mid]) if len(days) % 2 else (days[mid - 1] + days[mid]) / 2

    by_client: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = r["counterpartyId"] or r["counterparty"]
        c = by_client.setdefault(key, {
            "id": r["counterpartyId"], "name": r["counterparty"],
            "invoices": 0, "amount": 0.0, "sumDays": 0, "maxDays": r["days"],
        })
        c["invoices"] += 1
        c["amount"] += r["amount"]
        c["sumDays"] += r["days"]
        c["maxDays"] = max(c["maxDays"], r["days"])
    clients = sorted(
        ({**c, "avgDays": round(c["sumDays"] / c["invoices"], 1)} for c in by_client.values()),
        key=lambda c: -c["avgDays"])

    return {
        # Строки отдаём все: корзины считаются по этому же множеству, и обрезание
        # рассыпало бы отбор по клику (в полосе «55», в таблице «3»).
        "rows": rows,
        "buckets": buckets,
        "clients": clients,
        "total": len(rows),
        "payments": sum(r["payments"] for r in rows),
        "orphanPayments": orphans[0],
        "orphanAmount": _num(orphans[1]),
        "avgDays": round(sum(r["days"] for r in rows) / len(rows), 1) if rows else None,
        "medianDays": median,
        "amount": round(sum(r["amount"] for r in rows), 2),
    }


@router.get("/cashflow")
async def cashflow(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Движение денег помесячно: пришло, ушло, накопленный остаток.

    Считается по банковским ДОКУМЕНТАМ (`bank_in`/`bank_out`), а не по обороту 51
    счёта: у документа есть контрагент, и рядом с суммой сразу видно, кто заплатил и
    кому ушло. Оборот по 51 идёт контролем — расхождение означает движение без
    документа (перевод между своими счетами, эквайринг, инкассация).
    """
    cid = await assert_company_member(company_id, current_user, db)
    p = {"cid": str(cid)}

    months = [{
        "month": r[0], "inflow": _num(r[1]), "outflow": _num(r[2]),
        "inDocs": r[3], "outDocs": r[4],
    } for r in (await db.execute(text("""
        SELECT substr(date, 1, 7) AS month,
               sum(amount) FILTER (WHERE doc_type = 'bank_in')  inflow,
               sum(amount) FILTER (WHERE doc_type = 'bank_out') outflow,
               count(*)    FILTER (WHERE doc_type = 'bank_in')  in_docs,
               count(*)    FILTER (WHERE doc_type = 'bank_out') out_docs
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type IN ('bank_in', 'bank_out')
         GROUP BY 1 ORDER BY 1
    """), p)).all()]

    balance = 0.0
    for m in months:
        balance += m["inflow"] - m["outflow"]
        m["net"] = round(m["inflow"] - m["outflow"], 2)
        m["balance"] = round(balance, 2)

    payers = [{
        "name": r[0], "id": r[1], "inflow": _num(r[2]), "docs": r[3], "last": r[4],
    } for r in (await db.execute(text("""
        SELECT coalesce(counterparty_name, '—'), max(counterparty_id::text), sum(amount),
               count(*), max(date)
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type = 'bank_in'
         GROUP BY 1 ORDER BY 3 DESC LIMIT 50
    """), p)).all()]

    payees = [{
        "name": r[0], "id": r[1], "outflow": _num(r[2]), "docs": r[3], "last": r[4],
    } for r in (await db.execute(text("""
        SELECT coalesce(counterparty_name, '—'), max(counterparty_id::text), sum(amount),
               count(*), max(date)
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type = 'bank_out'
         GROUP BY 1 ORDER BY 3 DESC LIMIT 50
    """), p)).all()]

    return {
        "months": months,
        "payers": payers,
        "payees": payees,
        "inflow": round(sum(m["inflow"] for m in months), 2),
        "outflow": round(sum(m["outflow"] for m in months), 2),
        # Контроль по регистру: обороты счёта 51 за всю историю.
        # LIKE, а не равенство: появится 51.01 в плане счетов — точное сравнение
        # молча покажет ноль и «расхождение на весь оборот».
        "registerIn": _num((await db.execute(text(
            "SELECT coalesce(sum(amount), 0) FROM gl_entries "
            "WHERE company_id = :cid AND (account_dt = '51' OR account_dt LIKE '51.%')"),
            {"cid": str(cid)})).scalar_one()),
        "registerOut": _num((await db.execute(text(
            "SELECT coalesce(sum(amount), 0) FROM gl_entries "
            "WHERE company_id = :cid AND (account_kt = '51' OR account_kt LIKE '51.%')"),
            {"cid": str(cid)})).scalar_one()),
    }


# ── Движение денег по статьям ────────────────────────────────────────────────
# «Денежный поток» отвечает, сколько пришло и ушло. Этот экран — за что: статья
# движения размечена в самих документах (`details->'Статья ДДС'`), справочник статей
# приехал вместе с выгрузкой.
#
# Деление на три вида деятельности — канон отчёта о движении денежных средств:
# операционная (текущая) даёт понять, кормит ли себя бизнес; инвестиционная — во что
# вкладывается; финансовая — чем закрывает разрыв. Сумма всех трёх равна изменению
# остатка денег, и это единственная проверка, которую здесь можно сделать честно.

# Отнесение статьи к виду деятельности. Ключ — фрагмент названия статьи в нижнем
# регистре: справочник 1С у каждой компании свой, и жёсткий список кодов не подойдёт.
CF_KINDS: list[tuple[str, tuple[str, ...]]] = [
    ("investing", ("приобретение основных", "приобретение внеоборот", "покупка оборудован",
                   "капитальн", "приобретение нематериальн")),
    ("financing", ("кредит", "заём", "заем", "займ", "дивиденд", "вклад в уставный",
                   "лизинг")),
]


def _cf_kind(item: str) -> str:
    """Вид деятельности по названию статьи; всё неопознанное — операционная."""
    low = (item or "").lower()
    for kind, keys in CF_KINDS:
        if any(k in low for k in keys):
            return kind
    return "operating"


CF_KIND_LABEL = {
    "operating": "Текущая деятельность",
    "investing": "Инвестиционная",
    "financing": "Финансовая",
}


@router.get("/cashflow-items")
async def cashflow_items(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Куда и откуда двигались деньги: статьи, виды деятельности, помесячно."""
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid)}
    where = ""
    if date_from:
        where += " AND date >= :df"
        p["df"] = date_from
    if date_to:
        where += " AND date <= :dt"
        p["dt"] = date_to

    rows = [{
        "item": r[0] or "Без статьи",
        "inflow": _num(r[1]), "outflow": _num(r[2]),
        "inDocs": r[3], "outDocs": r[4],
        "first": r[5], "last": r[6],
    } for r in (await db.execute(text(f"""
        SELECT coalesce(nullif(details->>'Статья ДДС', ''), 'Без статьи') AS item,
               coalesce(sum(amount) FILTER (WHERE doc_type = 'bank_in'), 0),
               coalesce(sum(amount) FILTER (WHERE doc_type = 'bank_out'), 0),
               count(*) FILTER (WHERE doc_type = 'bank_in'),
               count(*) FILTER (WHERE doc_type = 'bank_out'),
               min(date), max(date)
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type IN ('bank_in', 'bank_out'){where}
         GROUP BY 1 ORDER BY 2 + 3 DESC
    """), p)).all()]

    for r in rows:
        r["kind"] = _cf_kind(r["item"])
        r["net"] = round(r["inflow"] - r["outflow"], 2)

    months = [{
        "month": r[0], "inflow": _num(r[1]), "outflow": _num(r[2]),
    } for r in (await db.execute(text(f"""
        SELECT substr(date, 1, 7) AS month,
               coalesce(sum(amount) FILTER (WHERE doc_type = 'bank_in'), 0),
               coalesce(sum(amount) FILTER (WHERE doc_type = 'bank_out'), 0)
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type IN ('bank_in', 'bank_out'){where}
         GROUP BY 1 ORDER BY 1
    """), p)).all()]

    kinds = [{
        "kind": k, "label": CF_KIND_LABEL[k],
        "inflow": round(sum(r["inflow"] for r in rows if r["kind"] == k), 2),
        "outflow": round(sum(r["outflow"] for r in rows if r["kind"] == k), 2),
        "net": round(sum(r["net"] for r in rows if r["kind"] == k), 2),
        "items": sum(1 for r in rows if r["kind"] == k),
    } for k in ("operating", "investing", "financing")]

    no_item = next((r for r in rows if r["item"] == "Без статьи"), None)
    return {
        "rows": rows,
        "months": months,
        "kinds": kinds,
        "inflow": round(sum(r["inflow"] for r in rows), 2),
        "outflow": round(sum(r["outflow"] for r in rows), 2),
        # Документы без статьи: они не попадают ни в один вид деятельности, и пока их
        # много, разрез неполон — это вопрос к бухгалтерии, а не к витрине.
        "noItemDocs": (no_item["inDocs"] + no_item["outDocs"]) if no_item else 0,
        "noItemAmount": round((no_item["inflow"] + no_item["outflow"]) if no_item else 0, 2),
    }


@router.get("/contract-sales")
async def contract_sales(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Продажи в разрезе договоров: отгрузки, счета, условия расчётов.

    Договор — основание сделки, и вопрос «сколько прошло по этому договору» до сих
    пор не имел ответа: документ ссылку на него получил (`contract_id`), но ни один
    экран по ней не собирал. Документы без договора идут отдельной строкой — их
    больше половины, и прятать это нельзя.
    """
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid)}
    where = ""
    if date_from:
        where += " AND d.date >= :df"
        p["df"] = date_from
    if date_to:
        where += " AND d.date <= :dt"
        p["dt"] = date_to

    rows = [{
        "id": str(r[0]) if r[0] else None,
        "number": r[1], "date": r[2], "kind": r[3], "settlementKind": r[4],
        # У группы «без договора» контрагент не один: `max(name)` выбирал случайное
        # имя из сотен, и строка читалась как «этот покупатель отгрузился на N млн
        # без договора». Для неё отдаём число контрагентов вместо имени.
        "counterparty": r[5] if r[0] else None,
        "counterparties": r[12],
        "sales": _num(r[6]), "salesDocs": r[7],
        "invoices": _num(r[8]), "invoiceDocs": r[9],
        "first": r[10], "last": r[11],
    } for r in (await db.execute(text(f"""
        SELECT d.contract_id, max(c.number), max(c.date), max(c.type),
               max(c.settlement_kind), max(d.counterparty_name),
               sum(d.amount) FILTER (WHERE d.doc_type = 'sale'),
               count(*)      FILTER (WHERE d.doc_type = 'sale'),
               sum(d.amount) FILTER (WHERE d.doc_type = 'invoice_out'),
               count(*)      FILTER (WHERE d.doc_type = 'invoice_out'),
               min(d.date), max(d.date),
               count(DISTINCT coalesce(d.counterparty_id::text, d.counterparty_name))
          FROM accounting_docs d
          LEFT JOIN contracts c ON c.id = d.contract_id
         WHERE d.company_id = :cid
           AND d.doc_type IN ('sale', 'invoice_out'){where}
         GROUP BY d.contract_id
         ORDER BY sum(d.amount) FILTER (WHERE d.doc_type = 'sale') DESC NULLS LAST
    """), p)).all()]

    linked = [r for r in rows if r["id"]]
    # «Договоров с продажами» — именно с ОТГРУЗКАМИ. Раньше сюда попадали и договоры,
    # по которым выставлены только счета: на пилоте 109 против фактических 56.
    with_sales = [r for r in linked if r["salesDocs"]]
    return {
        "rows": rows,
        "withContract": len(with_sales),
        "withInvoicesOnly": len(linked) - len(with_sales),
        "salesWithContract": round(sum(r["sales"] for r in linked), 2),
        "salesTotal": round(sum(r["sales"] for r in rows), 2),
    }


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
          -- Одна формула на все экраны: долг БРУТТО, аванс отдельной цифрой.
          -- Свёртка «дебет минус кредит» прятала покупателя, у которого есть и долг,
          -- и предоплата: в списке он выглядел ничего не должным, а в своей карточке
          -- должен. Аванс — не отрицательный долг, это другое обязательство.
          -- Счета 76, 58, 66/67 и 71 раньше не смотрели вовсе: у ТСМ ООО «мы должны»
          -- показывало 295 800 при фактических 673 625.
          SELECT b.counterparty_id,
                 sum(CASE WHEN b.account LIKE '62.01%' OR b.account LIKE '62.21%'
                          THEN b.debit ELSE 0 END) AS ar,
                 sum(CASE WHEN b.account LIKE '60.01%' OR b.account LIKE '60.21%'
                          THEN b.credit ELSE 0 END) AS ap,
                 sum(CASE WHEN b.account LIKE '62.02%' OR b.account LIKE '62.22%'
                          THEN b.credit ELSE 0 END) AS adv_in,
                 sum(CASE WHEN b.account LIKE '60.02%' OR b.account LIKE '60.22%'
                          THEN b.debit ELSE 0 END) AS adv_out,
                 sum(CASE WHEN b.account LIKE '76%' THEN b.debit ELSE 0 END) AS other_dt,
                 sum(CASE WHEN b.account LIKE '76%' THEN b.credit ELSE 0 END) AS other_kt,
                 sum(CASE WHEN b.account LIKE '58%' THEN b.debit ELSE 0 END) AS loan_out,
                 sum(CASE WHEN b.account LIKE '66%' OR b.account LIKE '67%'
                          THEN b.credit ELSE 0 END) AS loan_in,
                 sum(CASE WHEN b.account LIKE '71%' THEN b.credit - b.debit ELSE 0 END) AS accountable
            FROM gl_balances b
           WHERE b.company_id = :cid AND b.counterparty_id IS NOT NULL
             AND b.as_of = (SELECT max(as_of) FROM gl_balances WHERE company_id = :cid)
           GROUP BY 1
        )
        SELECT k.id, k.name, k.inn, k.kind,
               coalesce(a.sales, 0), coalesce(a.purchases, 0),
               coalesce(a.paid_in, 0), coalesce(a.paid_out, 0),
               coalesce(a.docs, 0), a.last_doc,
               coalesce(b.ar, 0), coalesce(b.ap, 0),
               coalesce(b.adv_in, 0), coalesce(b.adv_out, 0),
               coalesce(b.other_dt, 0), coalesce(b.other_kt, 0),
               coalesce(b.loan_out, 0), coalesce(b.loan_in, 0), coalesce(b.accountable, 0),
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
        "advanceIn": _num(r[12]), "advanceOut": _num(r[13]),
        # Прочие расчёты и займы: складывать их с долгом нельзя — это разные
        # обязательства, но и молчать о них нельзя, они меняют картину вдвое.
        "otherDebit": _num(r[14]), "otherCredit": _num(r[15]),
        "loanOut": _num(r[16]), "loanIn": _num(r[17]), "accountable": _num(r[18]),
        "contracts": r[19],
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
        raise HTTPException(status_code=404, detail="Контрагент не найден")

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
          SELECT doc, btrim(ln->>'code') code, ln->>'name' name,
                 (ln->>'qty')::numeric qty, (ln->>'amount')::numeric amount
            FROM l
        )
        SELECT x.code, max(x.name), sum(x.qty), sum(x.amount), count(DISTINCT x.doc),
               max(n.unit_label)
          FROM x LEFT JOIN nomenclature n
            ON n.company_id = :cid AND btrim(n.code) = x.code
         GROUP BY x.code ORDER BY 4 DESC LIMIT 50
    """), params)).all()]

    # Долг и авансы — ИЗ САЛЬДО ИСТОЧНИКА с субконто (тот же источник, что у
    # «Взаиморасчётов», см. `/books/settlements`). Расчёт по нашим проводкам врал
    # дважды: остаток накоплен всей историей регистра, включая периоды до выгрузки,
    # а долг и аванс схлопывались в одну разницу — у покупателя с предоплатой
    # получался «минусовой долг», которого в сальдо нет.
    debt = (await db.execute(text("""
        SELECT sum(b.debit)  FILTER (WHERE b.account LIKE '62%'),
               sum(b.credit) FILTER (WHERE b.account LIKE '60%'),
               sum(b.credit) FILTER (WHERE b.account LIKE '62%'),
               sum(b.debit)  FILTER (WHERE b.account LIKE '60%'),
               max(b.as_of),
               -- Прочие расчёты, займы и подотчёт: раньше карточка их не смотрела,
               -- и у ТСМ ООО «мы должны» показывало 295 800 вместо 673 625 — разница
               -- висела на 76.09. Складывать их с долгом нельзя: другое обязательство.
               sum(b.debit)  FILTER (WHERE b.account LIKE '76%'),
               sum(b.credit) FILTER (WHERE b.account LIKE '76%'),
               sum(b.debit)  FILTER (WHERE b.account LIKE '58%'),
               sum(b.credit) FILTER (WHERE b.account LIKE '66%' OR b.account LIKE '67%'),
               sum(b.credit - b.debit) FILTER (WHERE b.account LIKE '71%')
          FROM gl_balances b
         WHERE b.company_id = :cid AND b.counterparty_id::text = :kid
           AND b.as_of = (SELECT max(as_of) FROM gl_balances WHERE company_id = :cid)
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
        # Аванс — не «отрицательный долг»: покупатель заплатил вперёд, поставщику
        # заплатили вперёд мы. Это разные вопросы, поэтому и цифры разные.
        "advanceIn": _num(debt[2]), "advanceOut": _num(debt[3]),
        "otherDebit": _num(debt[5]), "otherCredit": _num(debt[6]),
        "loanOut": _num(debt[7]), "loanIn": _num(debt[8]), "accountable": _num(debt[9]),
        "debtAsOf": debt[4].isoformat() if debt[4] else None,
        "byType": by_type, "months": months, "items": items,
        "contracts": contracts, "docs": docs,
    }


# ── Акт сверки взаиморасчётов ────────────────────────────────────────────────
# Документ, который просят чаще любого другого: «пришлите сверку».
#
# ⚠ Итоги считаются ПО СУБКОНТО (`gl_turnovers`), а не по проводкам документов.
# Субконто в основной таблице регистра через COM недоступно, и «проводки
# документов контрагента» — это не то же самое, что «обороты по его расчётам»:
# зачёт аванса 62.02 → 62.01 идёт внутри счёта и в обороте по контрагенту
# схлопывается, а в перечне проводок считается дважды. На ТСМ ООО такой акт
# показывал 2 026 576,32 ₽ вместо 625 373,12 ₽ дебиторки.
#
# Обороты по субконто сходятся с сальдо среза (`gl_balances`) копейка в копейку —
# это тот же источник, на котором стоят «Взаиморасчёты». Документы остаются
# РАСШИФРОВКОЙ строк, а расхождение расшифровки с итогом показывается отдельной
# строкой «прочие движения», а не прячется.
#
# ⚠ Субконто приходит ПРЕДСТАВЛЕНИЕМ (имя контрагента), ссылки в нём нет — отсюда
# сопоставление по имени карточки.

# Виды документов своей стороны: в расшифровку расчётов с покупателем не должны
# попадать наши закупки у него же, иначе «162 документа на 32,7 млн» стоят под
# обеими секциями и расшифровкой быть перестают.
_ACT_SIDES = [
    ("receivable", "62", "Расчёты с покупателем (счёт 62)",
     ("sale", "invoice_out", "vat_invoice_out", "bank_in", "act_recon")),
    ("payable", "60", "Расчёты с поставщиком (счёт 60)",
     ("purchase", "invoice_in", "vat_invoice_in", "bank_out", "purchase_correction")),
]


@router.get("/act")
async def reconciliation_act(
    company_id: str,
    counterparty_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Акт сверки: обороты по расчётам с нарастающим сальдо и расшифровкой."""
    cid = await assert_company_member(company_id, current_user, db)

    k = (await db.execute(select(Counterparty).where(
        Counterparty.company_id == cid,
        Counterparty.id == counterparty_id))).scalar_one_or_none()
    if k is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    # Границы периода в месяцах: обороты приходят свёрнутыми по месяцу, и день
    # внутри месяца в них не различить (ограничение источника, а не решение).
    def ym(iso: str | None) -> tuple[int, int] | None:
        d = _day(iso)
        return (d.year, d.month) if d else None

    m_from, m_to = ym(date_from), ym(date_to)

    sections = []
    for kind, prefix, title, doc_types in _ACT_SIDES:
        params: dict[str, Any] = {"cid": str(cid), "name": k.name, "p": f"{prefix}%"}
        rows = (await db.execute(text("""
            SELECT period_year, period_month,
                   coalesce(sum(amount) FILTER (WHERE account_dt LIKE :p AND dt1 = :name), 0) dt,
                   coalesce(sum(amount) FILTER (WHERE account_kt LIKE :p AND kt1 = :name), 0) kt
              FROM gl_turnovers
             WHERE company_id = :cid
               AND ((account_dt LIKE :p AND dt1 = :name) OR (account_kt LIKE :p AND kt1 = :name))
             GROUP BY 1, 2 ORDER BY 1, 2
        """), params)).all()
        if not rows:
            continue

        sign = 1 if prefix == "62" else -1
        opening = 0.0
        months, saldo = [], 0.0
        debit_total = credit_total = 0.0
        for y, mm, dt, kt in rows:
            before = m_from is not None and (y, mm) < m_from
            after = m_to is not None and (y, mm) > m_to
            move = sign * (_num(dt) - _num(kt))
            if before:
                opening += move
                saldo = opening
                continue
            if after:
                continue
            saldo += move
            debit_total += _num(dt)
            credit_total += _num(kt)
            months.append({"month": f"{y}-{mm:02d}", "debit": _num(dt), "credit": _num(kt),
                           "saldo": round(saldo, 2)})

        # Расшифровка: документы контрагента за тот же период. Она может не покрыть
        # оборот целиком (зачёты и корректировки приходят проводками без документа) —
        # разницу показываем строкой, а не подгоняем.
        docs = [{
            "id": str(r[0]), "date": r[1], "type": r[2],
            "label": DOC_LABELS.get(r[2], r[2]), "number": r[3], "amount": _num(r[4]),
        } for r in (await db.execute(text("""
            SELECT d.id, d.date, d.doc_type, d.number, d.amount
              FROM accounting_docs d
             WHERE d.company_id = :cid AND d.counterparty_id::text = :kid
               AND d.doc_type = ANY(:types)
               AND (CAST(:df AS text) IS NULL OR d.date >= :df)
               AND (CAST(:dt AS text) IS NULL OR d.date <= :dt)
             ORDER BY d.date
        """), {"cid": str(cid), "kid": counterparty_id, "types": list(doc_types),
               "df": date_from, "dt": date_to})).all()]

        sections.append({
            "kind": kind, "account": prefix, "title": title,
            "opening": round(opening, 2), "closing": round(saldo, 2),
            "debitTotal": round(debit_total, 2), "creditTotal": round(credit_total, 2),
            "months": months, "docs": docs,
        })

    return {
        "counterparty": {"id": str(k.id), "name": k.name, "inn": k.inn, "kpp": k.kpp},
        "periodFrom": date_from, "periodTo": date_to,
        "sections": sections,
        # Честная подпись под документом: откуда цифры и почему день внутри месяца
        # в оборотах не различается.
        "note": "Итоги — по оборотам с субконто из бухгалтерии (свёрнуты по месяцам); "
                "документы приведены как расшифровка.",
    }


# ── Качество справочника контрагентов ───────────────────────────────────────
# Справочник приезжает из 1С как есть, со всеми его болезнями: одно юрлицо двумя
# карточками, карточка без ИНН, документы, которые ни с кем не связались. Пока это
# не показано, цифры разреза тихо делятся между дублями, а «его документы» находят
# половину. Экран отвечает не «всё плохо», а «вот конкретные строки и что с ними
# делать»: сведение документов — здесь же, одной кнопкой.

@router.get("/counterparty-quality")
async def counterparty_quality(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Болезни справочника: дубли, карточки без ИНН, несведённые документы."""
    cid = await assert_company_member(company_id, current_user, db)
    p = {"cid": str(cid)}

    # Дубли по ИНН — самый жёсткий случай: это заведомо одно юрлицо, и обороты
    # разделены между карточками пополам.
    by_inn = [{
        "key": r[0], "cards": r[1],
    } for r in (await db.execute(text("""
        SELECT k.inn, json_agg(json_build_object(
                 'id', k.id, 'name', k.name, 'kpp', k.kpp,
                 'docs', (SELECT count(*) FROM accounting_docs d
                           WHERE d.company_id = :cid AND d.counterparty_id = k.id),
                 'contracts', (SELECT count(*) FROM contracts c
                                WHERE c.company_id = :cid AND c.counterparty_id::text = k.id::text))
               ORDER BY k.name)
          FROM counterparties k
         WHERE k.company_id = :cid AND coalesce(k.inn, '') <> ''
         GROUP BY k.inn HAVING count(*) > 1
         ORDER BY count(*) DESC
    """), p)).all()]

    # Дубли по имени — та же нормализация, что при сведении документов: «ООО
    # «Ромашка»» и «Ромашка ООО» это одна карточка, а ИНН у одной из них может
    # не быть вовсе.
    norm = (r"lower(regexp_replace(regexp_replace(k.name, '[«»\"''`]', '', 'g'), "
            r"'\s+', ' ', 'g'))")
    by_name = [{
        "key": r[0], "cards": r[1],
    } for r in (await db.execute(text(rf"""
        SELECT {norm} nm, json_agg(json_build_object(
                 'id', k.id, 'name', k.name, 'inn', k.inn,
                 'docs', (SELECT count(*) FROM accounting_docs d
                           WHERE d.company_id = :cid AND d.counterparty_id = k.id))
               ORDER BY k.name)
          FROM counterparties k
         WHERE k.company_id = :cid
         GROUP BY {norm} HAVING count(*) > 1
         ORDER BY count(*) DESC LIMIT 100
    """), p)).all()]

    no_inn = [{
        "id": str(r[0]), "name": r[1], "docs": r[2], "amount": _num(r[3]),
    } for r in (await db.execute(text("""
        SELECT k.id, k.name,
               (SELECT count(*) FROM accounting_docs d
                 WHERE d.company_id = :cid AND d.counterparty_id = k.id),
               (SELECT coalesce(sum(d.amount), 0) FROM accounting_docs d
                 WHERE d.company_id = :cid AND d.counterparty_id = k.id)
          FROM counterparties k
         WHERE k.company_id = :cid AND coalesce(k.inn, '') = ''
         ORDER BY 3 DESC LIMIT 200
    """), p)).all()]

    # Несведённые документы: группируем по тому, как контрагент назван в документе,
    # и сразу ищем кандидата — карточку с тем же ИНН или похожим именем.
    unlinked = [{
        "name": r[0], "inn": r[1], "docs": r[2], "amount": _num(r[3]),
        "candidateId": str(r[4]) if r[4] else None, "candidateName": r[5],
    } for r in (await db.execute(text(rf"""
        WITH u AS (
          SELECT d.counterparty_name nm, d.counterparty_inn inn,
                 count(*) n, sum(d.amount) amt
            FROM accounting_docs d
           WHERE d.company_id = :cid AND d.counterparty_id IS NULL
             AND coalesce(d.counterparty_name, '') <> ''
           GROUP BY 1, 2
        )
        SELECT u.nm, u.inn, u.n, u.amt, k.id, k.name
          FROM u
          LEFT JOIN LATERAL (
            SELECT k.id, k.name FROM counterparties k
             WHERE k.company_id = :cid
               AND (
                 (coalesce(u.inn, '') <> '' AND k.inn = u.inn)
                 OR {norm} = lower(regexp_replace(regexp_replace(u.nm, '[«»\"''`]', '', 'g'), '\s+', ' ', 'g'))
               )
             LIMIT 1
          ) k ON true
         ORDER BY u.n DESC LIMIT 100
    """), p)).all()]

    # Карточки-пустышки: ни документов, ни договоров. Их не удаляют вслепую —
    # справочник ведут в 1С, — но знать про них надо: это шум в поиске.
    empty = (await db.execute(text("""
        SELECT count(*) FROM counterparties k
         WHERE k.company_id = :cid
           AND NOT EXISTS (SELECT 1 FROM accounting_docs d
                            WHERE d.company_id = :cid AND d.counterparty_id = k.id)
           AND NOT EXISTS (SELECT 1 FROM contracts c
                            WHERE c.company_id = :cid AND c.counterparty_id::text = k.id::text)
    """), p)).scalar_one()

    total, linked = (await db.execute(text("""
        SELECT count(*), count(counterparty_id) FROM accounting_docs
         WHERE company_id = :cid AND coalesce(counterparty_name, '') <> ''
    """), p)).one()

    return {
        "duplicatesByInn": by_inn,
        "duplicatesByName": by_name,
        "withoutInn": no_inn,
        "unlinkedDocs": unlinked,
        "emptyCards": empty,
        "docsWithName": total,
        "docsLinked": linked,
    }


@router.post("/link-docs")
async def link_docs(
    company_id: str,
    counterparty_id: str,
    name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Привязать несведённые документы с таким именем к выбранной карточке.

    Ручное решение там, где машинное не сработало: имя в документе написано иначе,
    ИНН не приехал. Трогаем только документы БЕЗ ссылки — уже сведённые остаются
    как есть, поэтому повторный вызов безопасен.
    """
    cid = await assert_company_member(company_id, current_user, db)
    res = await db.execute(text("""
        UPDATE accounting_docs SET counterparty_id = CAST(:kid AS uuid)
         WHERE company_id = :cid AND counterparty_id IS NULL AND counterparty_name = :name
    """), {"cid": str(cid), "kid": counterparty_id, "name": name})
    await db.commit()
    return {"linked": res.rowcount or 0}


# ── Просмотрщик документа ────────────────────────────────────────────────────
# Реестр отвечает «какие документы есть», карточка контрагента — «что у нас с
# ним». Оба заканчиваются строкой таблицы, а дальше человеку нужен САМ документ:
# из чего сложилась сумма и какими проводками он лёг в учёт. Иначе следующий шаг —
# открыть 1С и искать документ там.

@router.get("/document")
async def document_card(
    company_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Документ целиком: шапка, строки и его проводки."""
    cid = await assert_company_member(company_id, current_user, db)

    d = (await db.execute(select(AccountingDoc).where(
        AccountingDoc.company_id == cid,
        AccountingDoc.id == doc_id))).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    entries = [{
        "date": e.entry_date.isoformat(), "accountDt": e.account_dt,
        "accountKt": e.account_kt, "amount": _num(e.amount), "content": e.content,
    } for e in (await db.execute(select(GlEntry).where(
        GlEntry.company_id == cid, GlEntry.doc_id == d.id)
        .order_by(GlEntry.entry_date, GlEntry.id))).scalars().all()]

    counterparty = None
    if d.counterparty_id:
        k = (await db.execute(select(Counterparty).where(
            Counterparty.id == d.counterparty_id))).scalar_one_or_none()
        if k:
            counterparty = {"id": str(k.id), "name": k.name, "inn": k.inn}

    contract = None
    if d.contract_id:
        c = (await db.execute(text(
            "SELECT number, date, type FROM contracts WHERE id = :id"),
            {"id": str(d.contract_id)})).first()
        if c:
            contract = {"number": c[0], "date": c[1], "type": c[2]}

    # Реквизиты, за которыми не заводят колонку (время, автор, назначение платежа,
    # комментарий): для документа они и есть ответ на «что это было».
    meta = {k: v for k, v in (d.doc_meta or {}).items() if v not in (None, "", [], {})}
    return {
        "id": str(d.id), "type": d.doc_type, "label": DOC_LABELS.get(d.doc_type, d.doc_type),
        "number": d.number, "date": d.date, "amount": _num(d.amount),
        "vat": _num(d.vat_amount), "status": d.status_1c,
        "periodStatus": _period_status(d.date, await _closed_months(db, cid)), "operation": d.operation_type,
        "counterpartyName": d.counterparty_name, "counterpartyInn": d.counterparty_inn,
        "counterparty": counterparty, "contract": contract,
        "externalNumber": d.external_number, "externalDate": d.external_date,
        "lines": [{
            "code": (ln.get("code") or "").strip() or None,
            "name": ln.get("name"), "kind": ln.get("kind") or "goods",
            "qty": _num(ln.get("qty")), "price": _num(ln.get("price")),
            "amount": _num(ln.get("amount")), "vat": _num(ln.get("vat")),
        } for ln in (d.lines or [])],
        "entries": entries,
        "meta": meta,
    }


# ── Нормализованный слой: карточка позиции ───────────────────────────────────
# Разрез отвечает «что продаём», карточка — «что с этой позицией»: по какой цене
# уходит и приходит, сколько на ней зарабатываем, кто её берёт и когда брали в
# последний раз. Ключ — КОД номенклатуры: имя в строке документа пишется как
# угодно, а код тот же, что в справочнике.

@router.get("/nomenclature")
async def nomenclature_card(
    company_id: str,
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Карточка позиции: продажи и закупки, цены по датам, покупатели, наценка."""
    cid = await assert_company_member(company_id, current_user, db)
    # Код нормализуем на входе: и строки документов, и справочник сравниваются
    # обрезанными — иначе «ТКС003498  » и «ТКС003498» это две разные позиции.
    code = code.strip()
    params = {"cid": str(cid), "code": code}

    # Код из строки документа приезжает с хвостовыми пробелами («ТКС003498  »), а в
    # справочнике лежит без них: без btrim карточка честно сообщает «кода нет в
    # справочнике» о позиции, которая там есть.
    item = (await db.execute(select(NomenclatureItem).where(
        NomenclatureItem.company_id == cid,
        func.btrim(NomenclatureItem.code) == code))).scalars().first()

    # Одна выборка строк на всё: разворачиваем JSONB в колонки и дальше считаем
    # по ней — и итоги, и цены, и покупателей (Postgres не даёт агрегировать
    # `jsonb_array_elements` в том же запросе, где он вызван).
    lines_cte = """
        WITH l AS (
          SELECT d.id doc, d.doc_type, d.date, d.counterparty_id, d.counterparty_name,
                 jsonb_array_elements(d.lines) ln
            FROM accounting_docs d
           WHERE d.company_id = :cid AND d.doc_type IN ('sale', 'purchase')
        ), x AS (
          SELECT doc, doc_type, date, counterparty_id, counterparty_name,
                 btrim(ln->>'code') code, ln->>'name' name, ln->>'kind' kind,
                 (ln->>'qty')::numeric qty, (ln->>'amount')::numeric amount,
                 (ln->>'price')::numeric price
            FROM l
        )
    """

    totals = (await db.execute(text(lines_cte + """
        SELECT doc_type, count(DISTINCT doc), sum(qty), sum(amount),
               min(date), max(date)
          FROM x WHERE code = :code GROUP BY doc_type
    """), params)).all()
    agg = {r[0]: {"docs": r[1], "qty": _num(r[2]), "amount": _num(r[3]),
                  "first": r[4], "last": r[5]} for r in totals}

    prices = [{"date": r[0], "kind": r[1], "price": _num(r[2]), "qty": _num(r[3]),
               "counterparty": r[4]} for r in (await db.execute(text(lines_cte + """
        SELECT date, doc_type, price, qty, counterparty_name
          FROM x WHERE code = :code AND price IS NOT NULL
         ORDER BY date DESC LIMIT 100
    """), params)).all()]

    clients = [{"id": str(r[0]) if r[0] else None, "name": r[1], "qty": _num(r[2]),
                "amount": _num(r[3]), "docs": r[4], "last": r[5]}
               for r in (await db.execute(text(lines_cte + """
        SELECT counterparty_id, max(counterparty_name), sum(qty), sum(amount),
               count(DISTINCT doc), max(date)
          FROM x WHERE code = :code AND doc_type = 'sale'
         GROUP BY counterparty_id ORDER BY 4 DESC LIMIT 30
    """), params)).all()]

    suppliers = [{"id": str(r[0]) if r[0] else None, "name": r[1], "qty": _num(r[2]),
                  "amount": _num(r[3]), "docs": r[4], "last": r[5]}
                 for r in (await db.execute(text(lines_cte + """
        SELECT counterparty_id, max(counterparty_name), sum(qty), sum(amount),
               count(DISTINCT doc), max(date)
          FROM x WHERE code = :code AND doc_type = 'purchase'
         GROUP BY counterparty_id ORDER BY 4 DESC LIMIT 30
    """), params)).all()]

    months = [{"month": r[0], "soldQty": _num(r[1]), "soldAmount": _num(r[2]),
               "boughtQty": _num(r[3]), "boughtAmount": _num(r[4])}
              for r in (await db.execute(text(lines_cte + """
        SELECT substr(date, 1, 7) m,
               sum(qty)    FILTER (WHERE doc_type = 'sale'),
               sum(amount) FILTER (WHERE doc_type = 'sale'),
               sum(qty)    FILTER (WHERE doc_type = 'purchase'),
               sum(amount) FILTER (WHERE doc_type = 'purchase')
          FROM x WHERE code = :code GROUP BY 1 ORDER BY 1
    """), params)).all()]

    sale, purchase = agg.get("sale", {}), agg.get("purchase", {})
    # Средняя цена — сумма / количество, а не среднее из цен строк: строка на 100
    # штук весит столько же, сколько строка на одну, и «среднее из средних» врёт.
    avg_sale = (sale.get("amount", 0) / sale["qty"]) if sale.get("qty") else 0.0
    avg_buy = (purchase.get("amount", 0) / purchase["qty"]) if purchase.get("qty") else 0.0
    # Имя берём из справочника; если карточки в нём нет (674 строки пилота ссылаются
    # на коды, которых в номенклатуре не оказалось) — из самих строк документов.
    doc_name = (await db.execute(text(lines_cte + """
        SELECT max(name) FROM x WHERE code = :code
    """), params)).scalar_one_or_none()
    return {
        "code": code,
        "name": (item.name if item else None) or doc_name or code,
        "unit": item.unit_label if item else None,
        "vatRate": item.vat_rate if item else None,
        "inCatalog": item is not None,
        "sale": sale, "purchase": purchase,
        "avgSalePrice": round(avg_sale, 2),
        "avgBuyPrice": round(avg_buy, 2),
        # Наценка — от закупочной цены: «сколько добавили к тому, за что купили».
        "markupPct": round((avg_sale / avg_buy - 1) * 100, 1) if avg_buy else None,
        "prices": prices, "clients": clients, "suppliers": suppliers, "months": months,
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
    # Проверки, которых экрану не хватало: эти дефекты ревизия нашла запросами, а
    # экран качества их не ловил — значит в следующий раз найдёт снова человек.
    async def _count(sql: str) -> int:
        return int((await db.execute(text(sql), {"cid": str(cid)})).scalar_one() or 0)

    dup_inn = await _count("""
        SELECT count(*) FROM (SELECT inn FROM counterparties
         WHERE company_id = :cid AND coalesce(inn,'') <> '' AND NOT is_group
         GROUP BY inn HAVING count(*) > 1) t""")
    add("dup_counterparty_inn", "Один ИНН — одна карточка",
        "ok" if not dup_inn else "error", dup_inn,
        "Дубль режет историю юрлица: документы на одной карточке, договоры на другой")

    dup_code = await _count("""
        SELECT count(*) FROM (SELECT external_ref FROM nomenclature
         WHERE company_id = :cid AND external_ref IS NOT NULL
         GROUP BY external_ref HAVING count(*) > 1) t""")
    add("dup_nomenclature_code", "Код номенклатуры уникален",
        "ok" if not dup_code else "warn", dup_code,
        "Один код на две позиции: сопоставление строк документов промахнётся")

    head_vs_lines = await _count("""
        SELECT count(*) FROM accounting_docs d
         WHERE d.company_id = :cid AND jsonb_array_length(coalesce(d.lines,'[]'::jsonb)) > 0
           AND d.doc_type <> 'payroll_accrual'
           AND abs(d.amount - (SELECT coalesce(sum((l->>'amount')::numeric),0)
                                 FROM jsonb_array_elements(d.lines) l)) > 0.01""")
    add("head_vs_lines", "Шапка документа = сумма строк",
        "ok" if not head_vs_lines else "warn", head_vs_lines,
        "Расхождение бывает дефектом источника: НДС начислен сверху, а шапка без налога")

    bad_inn = await _count("""
        SELECT count(*) FROM counterparties
         WHERE company_id = :cid AND coalesce(inn,'') <> ''
           AND inn !~ '^[0-9]{10}$' AND inn !~ '^[0-9]{12}$'""")
    add("inn_format", "ИНН правильной длины", "ok" if not bad_inn else "warn", bad_inn,
        "10 цифр у юрлица, 12 у предпринимателя — иначе карточка не сверится с реестром")

    not_posted = await _count("""
        SELECT count(*) FROM accounting_docs
         WHERE company_id = :cid AND status_1c = 'Не проведён'""")
    add("not_posted", "Непроведённые документы", "info", not_posted,
        "Документ записан, но в учёт не попал: в книгу и в обороты он не входит")

    orphan = await _count("""
        SELECT count(*) FROM gl_entries WHERE company_id = :cid AND doc_id IS NULL""")
    add("entries_without_doc", "Проводки без документа",
        "ok" if not orphan else "warn", orphan,
        "Проводка есть, первички под ней нет: документ не загружен или не сведён")

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
    # Только приёмы данных: вложения переписки лежат в той же таблице, и без
    # фильтра отчёт, отправленный в чат, считался очередной загрузкой источника.
    intakes = (await db.execute(select(func.count()).select_from(SourceFile)
                                .where(SourceFile.company_id == cid,
                                       SourceFile.purpose == "data"))).scalar_one()
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


@router.get("/doc")
async def doc_card(
    company_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Документ целиком: шапка, состав, чем оплачен и какие проводки породил.

    Реестр отвечает «что есть», а вопрос аудитора всегда следующий — «что внутри
    и чем подтверждено». Всё, что для этого нужно, уже лежит в слое: строки — в
    самом документе, оплата — в регистре оплат, проводки — в регистре бухгалтерии
    (связь `doc_id` проставляет `books_links`).
    """
    cid = await assert_company_member(company_id, current_user, db)
    try:
        uid = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Документ не найден")

    d = (await db.execute(select(AccountingDoc).where(
        AccountingDoc.company_id == cid, AccountingDoc.id == uid))).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    payments = (await db.execute(
        select(InvoicePayment.paid_at, InvoicePayment.payment_title,
               InvoicePayment.amount, InvoicePayment.vat)
        .where(InvoicePayment.company_id == cid, InvoicePayment.invoice_doc_id == uid)
        .order_by(InvoicePayment.paid_at))).all()

    entries = (await db.execute(
        select(GlEntry.entry_date, GlEntry.account_dt, GlEntry.account_kt,
               GlEntry.amount, GlEntry.content)
        .where(GlEntry.company_id == cid, GlEntry.doc_id == uid)
        .order_by(GlEntry.entry_date))).all()

    contract = None
    if d.contract_id:
        contract = (await db.execute(
            select(Contract.number, Contract.date, Contract.kind)
            .where(Contract.id == d.contract_id))).first()

    return {
        "id": str(d.id),
        "type": d.doc_type, "label": DOC_LABELS.get(d.doc_type, d.doc_type),
        "section": SECTION_OF.get(d.doc_type),
        "number": d.number, "date": d.date,
        "counterparty": d.counterparty_name, "inn": d.counterparty_inn,
        "counterpartyId": str(d.counterparty_id) if d.counterparty_id else None,
        "contract": ({"number": contract[0], "date": contract[1], "type": contract[2]}
                     if contract else None),
        "organization": d.organization_name,
        "amount": _num(d.amount), "vat": _num(d.vat_amount),
        "operation": d.operation_type, "status": d.status_1c,
        "periodStatus": _period_status(d.date, await _closed_months(db, cid)),
        "externalId": d.external_id,
        "warehouse": d.warehouse_code,
        # Входящий документ поставщика и реквизиты, обязательные для вида: у платежа
        # назначение и счёт организации, у счёта-фактуры основание и код операции.
        "externalNumber": d.external_number,
        "externalDate": d.external_date,
        "details": d.details or {},
        # Строки как они приехали: у разных видов свой набор полей, поэтому отдаём
        # как есть — просмотрщик показывает то, что в строке действительно было.
        "lines": d.lines or [],
        "payments": [{"date": p[0], "title": p[1], "amount": _num(p[2]), "vat": _num(p[3])}
                     for p in payments],
        "paid": sum(_num(p[2]) for p in payments) if payments else 0.0,
        "entries": [{"date": e[0].isoformat() if e[0] else None,
                     "accountDt": e[1], "accountKt": e[2],
                     "amount": _num(e[3]), "content": e[4]} for e in entries],
    }


@router.get("/payroll")
async def payroll(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Расчёт с персоналом: начислено, удержано, взносы, выплачено — по месяцам и людям.

    Считается по `payroll_entries`, а не по документам: месяц расчёта и дата документа
    расходятся (зарплату за декабрь считают в декабре, платят в январе), и по дате
    документа картина съезжает на месяц.

    ⚠ Персональные данные: экран показывает ФИО сотрудников клиента.
    """
    cid = await assert_company_member(company_id, current_user, db)
    p = {"cid": str(cid)}

    totals = (await db.execute(text("""
        SELECT
          coalesce(sum(amount) FILTER (WHERE kind = 'accrual'), 0),
          coalesce(sum(amount) FILTER (WHERE kind = 'ndfl'), 0),
          coalesce(sum(amount) FILTER (WHERE kind = 'contribution'), 0),
          coalesce(sum(amount) FILTER (WHERE kind = 'payment'), 0),
          count(DISTINCT employee_id)
          FROM payroll_entries WHERE company_id = :cid"""), p)).one()

    # Долг перед сотрудниками — сальдо 70, а не «начислено минус выплачено»: в
    # разнице не учтён НДФЛ, который удержан, но сотруднику не причитается.
    debt = _num((await db.execute(text("""
        SELECT coalesce(sum(credit - debit), 0) FROM gl_balances
         WHERE company_id = :cid AND account LIKE '70%'
           AND as_of = (SELECT max(as_of) FROM gl_balances WHERE company_id = :cid)"""),
        p)).scalar_one())

    months = [{
        "month": r[0], "accrued": _num(r[1]), "ndfl": _num(r[2]),
        "contributions": _num(r[3]), "paid": _num(r[4]),
    } for r in (await db.execute(text("""
        SELECT period_month,
               coalesce(sum(amount) FILTER (WHERE kind = 'accrual'), 0),
               coalesce(sum(amount) FILTER (WHERE kind = 'ndfl'), 0),
               coalesce(sum(amount) FILTER (WHERE kind = 'contribution'), 0),
               coalesce(sum(amount) FILTER (WHERE kind = 'payment'), 0)
          FROM payroll_entries
         WHERE company_id = :cid AND period_month IS NOT NULL
         GROUP BY 1 ORDER BY 1"""), p)).all()]

    employees = [{
        "id": str(r[0]) if r[0] else None, "name": r[1], "inn": r[2], "snils": r[3],
        "accrued": _num(r[4]), "ndfl": _num(r[5]), "paid": _num(r[6]),
        "contributions": _num(r[7]), "months": r[8],
    } for r in (await db.execute(text("""
        SELECT e.id, coalesce(e.name, p.employee_name), e.inn, e.snils,
               coalesce(sum(p.amount) FILTER (WHERE p.kind = 'accrual'), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.kind = 'ndfl'), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.kind = 'payment'), 0),
               coalesce(sum(p.amount) FILTER (WHERE p.kind = 'contribution'), 0),
               count(DISTINCT p.period_month)
          FROM payroll_entries p
          LEFT JOIN employees e ON e.id = p.employee_id
         WHERE p.company_id = :cid
         GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC"""), p)).all()]

    # Виды начислений и удержаний: «из чего сложилась сумма» — первый вопрос к расчёту.
    kinds = [{"kind": r[0], "name": r[1], "amount": _num(r[2]), "rows": r[3]}
             for r in (await db.execute(text("""
        SELECT kind, coalesce(name, '—'), sum(amount), count(*)
          FROM payroll_entries WHERE company_id = :cid
         GROUP BY 1, 2 ORDER BY 3 DESC"""), p)).all()]

    # Документы блока: аванс за первую половину месяца проводок не делает, и без
    # пометки его сумма читается как расхождение с регистром.
    docs = [{
        "id": str(r[0]), "type": r[1], "label": DOC_LABELS.get(r[1], r[1]),
        "number": r[2], "date": r[3], "amount": _num(r[4]), "status": r[5],
        "advance": bool(r[6]), "month": r[7],
    } for r in (await db.execute(text("""
        SELECT id, doc_type, number, date, amount, status_1c,
               (details->>'Расчёт') IS NOT NULL, details->>'Месяц начисления'
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type IN ('payroll_accrual', 'payroll_payment')
         ORDER BY date DESC"""), p)).all()]

    advance = sum(d["amount"] for d in docs
                  if d["advance"] and d["type"] == "payroll_accrual")

    return {
        "totals": {
            "accrued": _num(totals[0]), "ndfl": _num(totals[1]),
            "contributions": _num(totals[2]), "paid": _num(totals[3]),
            "employees": totals[4], "debt": debt,
            # Аванс отдельной цифрой: он входит в «начислено», но проводок не делает,
            # и без пояснения экран расходится с оборотами регистра.
            "advance": advance,
        },
        "months": months, "employees": employees, "kinds": kinds, "docs": docs,
    }


# ── Закрытие периода: что собрано и чего не хватает ──────────────────────────
# Ядро приложения-прослойки. Правила те же, что у закрытия месяца в «Эксплуатации»
# (`services/ops_closing.py`): период закрывается тем, что есть, закрытый месяц не
# переписывается, а недостающее видно поимённо — иначе «не пришло» неотличимо от
# «не смотрели».

# Чего ждём, если операция была. Правило → как читать находку.
_GAP_RULES = [
    ("purchase_no_vat_invoice", "Поступление без счёта-фактуры",
     "Вычет НДС заявить нечем: поставщик документ не прислал или он не проведён"),
    ("sale_no_vat_invoice", "Реализация без счёта-фактуры",
     "Покупателю не выставлен счёт-фактура — он не примет НДС к вычету и попросит"),
    ("payment_no_document", "Оплата без закрывающего документа",
     "Деньги ушли поставщику, поступления в периоде нет: аванс висит на 60.02"),
    ("invoice_paid_no_sale", "Счёт оплачен, отгрузки нет",
     "Покупатель заплатил, реализации нет: аванс на 62.02 и НДС с аванса"),
    ("not_posted", "Документ не проведён",
     "Документ есть, но в учёт не попал: в обороты и в книгу он не входит"),
]


@router.get("/closing")
async def closing(
    company_id: str,
    period: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Состояние периодов и недостающие документы.

    `period` — «ГГГГ-ММ»; без него отдаётся сводка по всем месяцам, с ним — разбор
    одного: чего не хватает, по кому и на какую сумму.
    """
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid), "period": period}

    months = [{
        "month": r[0], "status": r[1], "docs": r[2], "amount": _num(r[3]),
        "entries": r[4], "turnover": _num(r[5]),
        "closedAt": r[6].isoformat() if r[6] else None, "closureSource": r[7],
    } for r in (await db.execute(text("""
        WITH d AS (
          SELECT substr(date, 1, 7) AS m, count(*) AS docs, sum(amount) AS amount
            FROM accounting_docs WHERE company_id = :cid GROUP BY 1
        ), e AS (
          SELECT to_char(entry_date, 'YYYY-MM') AS m, count(*) AS cnt, sum(amount) AS turnover
            FROM gl_entries WHERE company_id = :cid GROUP BY 1
        )
        SELECT coalesce(d.m, e.m) AS m,
               coalesce(p.status, 'open'), coalesce(d.docs, 0), coalesce(d.amount, 0),
               coalesce(e.cnt, 0), coalesce(e.turnover, 0), p.closed_at, p.closure_source
          FROM d
          FULL JOIN e ON e.m = d.m
          LEFT JOIN periods p ON p.company_id = :cid
               AND p.year = substr(coalesce(d.m, e.m), 1, 4)::int
               AND p.month = substr(coalesce(d.m, e.m), 6, 2)::int
         WHERE coalesce(d.m, e.m) IS NOT NULL
         ORDER BY 1 DESC"""), p)).all()]

    where_period = "AND substr(d.date, 1, 7) = :period" if period else ""
    gaps: list[dict[str, Any]] = []

    async def collect(key: str, sql: str) -> None:
        rows = (await db.execute(text(sql), p)).all()
        title, why = next((t, w) for k, t, w in _GAP_RULES if k == key)
        gaps.append({
            "key": key, "title": title, "why": why,
            "count": len(rows), "amount": round(sum(_num(r[4]) for r in rows), 2),
            "rows": [{"id": str(r[0]), "date": r[1], "number": r[2],
                      "counterparty": r[3], "amount": _num(r[4]),
                      "period": (r[1] or "")[:7]} for r in rows[:200]],
        })

    # 1. Поступление, у которого нет счёта-фактуры того же контрагента в ±31 день.
    await collect("purchase_no_vat_invoice", """
        SELECT d.id, d.date, d.number, d.counterparty_name, d.amount
          FROM accounting_docs d
         WHERE d.company_id = :cid AND d.doc_type = 'purchase' """ + where_period + """
           AND coalesce(d.vat_amount, 0) > 0
           AND NOT EXISTS (
             SELECT 1 FROM accounting_docs v
              WHERE v.company_id = d.company_id AND v.doc_type = 'vat_invoice_in'
                AND coalesce(v.counterparty_inn, '') = coalesce(d.counterparty_inn, '')
                AND abs(v.date::date - d.date::date) <= 31)
         ORDER BY d.date DESC""")

    # 2. Реализация без выданного счёта-фактуры.
    await collect("sale_no_vat_invoice", """
        SELECT d.id, d.date, d.number, d.counterparty_name, d.amount
          FROM accounting_docs d
         WHERE d.company_id = :cid AND d.doc_type = 'sale' """ + where_period + """
           AND coalesce(d.vat_amount, 0) > 0
           AND NOT EXISTS (
             SELECT 1 FROM accounting_docs v
              WHERE v.company_id = d.company_id AND v.doc_type = 'vat_invoice_out'
                AND coalesce(v.counterparty_inn, '') = coalesce(d.counterparty_inn, '')
                AND abs(v.date::date - d.date::date) <= 31)
         ORDER BY d.date DESC""")

    # 3. Заплатили поставщику, а поступления в том же месяце нет. Налоги, зарплату и
    #    займы исключаем: там закрывающего документа не бывает по природе.
    await collect("payment_no_document", """
        SELECT d.id, d.date, d.number, d.counterparty_name, d.amount
          FROM accounting_docs d
         WHERE d.company_id = :cid AND d.doc_type = 'bank_out' """ + where_period + """
           AND coalesce(d.counterparty_inn, '') <> ''
           AND NOT EXISTS (
             SELECT 1 FROM accounting_docs x
              WHERE x.company_id = d.company_id
                AND x.doc_type IN ('purchase', 'advance_report', 'invoice_in')
                AND x.counterparty_inn = d.counterparty_inn
                AND substr(x.date, 1, 7) = substr(d.date, 1, 7))
           AND NOT EXISTS (
             SELECT 1 FROM gl_entries g
              WHERE g.doc_id = d.id
                AND (g.account_dt LIKE '68%' OR g.account_dt LIKE '69%'
                     OR g.account_dt LIKE '70%' OR g.account_dt LIKE '66%'
                     OR g.account_dt LIKE '67%' OR g.account_dt LIKE '58%'))
         ORDER BY d.date DESC""")

    # 4. Счёт покупателю оплачен, отгрузки нет.
    await collect("invoice_paid_no_sale", """
        SELECT d.id, d.date, d.number, d.counterparty_name, d.amount
          FROM accounting_docs d
         WHERE d.company_id = :cid AND d.doc_type = 'invoice_out' """ + where_period + """
           AND EXISTS (SELECT 1 FROM invoice_payments ip WHERE ip.invoice_doc_id = d.id)
           AND NOT EXISTS (
             SELECT 1 FROM accounting_docs s
              WHERE s.company_id = d.company_id AND s.doc_type = 'sale'
                AND s.counterparty_inn = d.counterparty_inn
                AND s.date >= d.date)
         ORDER BY d.date DESC""")

    # 5. Непроведённые документы: записаны, но в учёт не попали.
    await collect("not_posted", """
        SELECT d.id, d.date, d.number, d.counterparty_name, d.amount
          FROM accounting_docs d
         WHERE d.company_id = :cid AND d.status_1c = 'Не проведён' """ + where_period + """
         ORDER BY d.date DESC""")

    # Кто задолжал документы — тот же список, свёрнутый по контрагенту: работа идёт
    # не с документом, а с человеком на той стороне.
    by_party: dict[str, dict[str, Any]] = {}
    for gap in gaps:
        if gap["key"] == "not_posted":
            continue      # это наш недочёт, а не долг контрагента
        for row in gap["rows"]:
            name = row["counterparty"] or "—"
            slot = by_party.setdefault(name, {"counterparty": name, "count": 0,
                                              "amount": 0.0, "kinds": []})
            slot["count"] += 1
            slot["amount"] = round(slot["amount"] + row["amount"], 2)
            if gap["title"] not in slot["kinds"]:
                slot["kinds"].append(gap["title"])

    # До какой даты недостающий документ ещё можно оформить. Ответ зависит от способа
    # получения: бумагу подписывают датой события хоть сегодня, электронный документ
    # уходит через оператора и получает его отметку времени — задним числом не выйдет.
    # Способ берём из самой базы: если контур ЭДО пуст, у клиента вся первичка бумажная.
    lock = (await db.execute(
        select(func.max(GlReference.code))
        .where(GlReference.company_id == cid, GlReference.kind == "period_locks"))).scalar_one()
    edo_docs = (await db.execute(
        select(func.count()).select_from(AccountingDoc).where(
            AccountingDoc.company_id == cid,
            AccountingDoc.details["Способ получения"].astext == "ЭДО"))).scalar_one()

    return {
        "period": period,
        "months": months,
        "gaps": gaps,
        "byCounterparty": sorted(by_party.values(), key=lambda x: -x["amount"])[:100],
        "docFlow": {
            "lock": lock,
            "edoDocs": edo_docs,
            "note": ("Часть первички приходит по ЭДО: такие документы оператор датирует "
                     "моментом отправки, задним числом их не оформить — просить нужно сразу."
                     if edo_docs else
                     "Электронного документооборота в базе нет: вся первичка бумажная, "
                     "недостающее можно дооформить датой события — но только до даты запрета.")
                    + (f" Запрет изменений стоит на {lock}." if lock else
                       " Дата запрета изменений не установлена — закрытый месяц могут переписать."),
        },
    }


# ── Проверки учёта: аналог экспресс-проверки 1С на наших данных ──────────────
# Бухгалтер знает этот жанр: правила сгруппированы по разделам учёта, у каждого
# понятно, что нашли и где смотреть. Отличие от `/quality` (там про КАЧЕСТВО
# ЗАГРУЗКИ — доехали ли данные) в том, что здесь про САМ УЧЁТ: что в нём не так,
# независимо от того, как он к нам попал.
#
# Каждая проверка обязана отвечать на три вопроса: что нашли, чем это грозит и
# какие именно документы смотреть. Проверка без списка нарушителей бесполезна —
# человек всё равно пойдёт искать их руками.

_CHECK_GROUPS = [
    ("policy", "Учётная политика"),
    ("books", "Состояние учёта"),
    ("money", "Касса и банк"),
    ("vat_out", "Книга продаж"),
    ("vat_in", "Книга покупок"),
    ("payroll", "Расчёты с персоналом"),
    ("goods", "Номенклатура и склад"),
    ("periods", "Периоды и закрытие"),
]

# key, группа, заголовок, чем грозит, SQL списка нарушителей (5 колонок:
# id, дата, номер, кто/что, сумма) либо None для проверок-сверок.
_CHECKS: list[tuple] = [
    ("policy_lock", "policy", "Дата запрета изменения данных установлена",
     "Без запрета закрытый период может быть переписан задним числом, и отчётность разъедется", """
        SELECT id::text, '', code, name, 0 FROM gl_references
         WHERE company_id = :cid AND kind = 'period_locks'"""),
    ("policy_mpz", "policy", "Метод оценки МПЗ задан",
     "От метода зависит себестоимость: без него нечем обосновать списание", """
        SELECT id::text, '', kind, name, 0 FROM gl_references
         WHERE company_id = :cid AND kind = 'accounting_policy'"""),

    # Соответствие политике проверяем ПО ДАННЫМ, а не по декларации: политика
    # сказала «ПБУ 18 не ведём» — значит счетов 09 и 77 в проводках быть не может.
    # Условие в SQL сверяется с самой политикой, поэтому у клиента с другой
    # политикой проверка просто не сработает, а не выдаст ложную тревогу.
    ("policy_pbu18", "policy", "Счета ПБУ 18/02 при отключённом ПБУ 18",
     "Политика говорит, что отложенные налоги не ведутся, а проводки по 09 и 77 есть", """
        SELECT e.id::text, e.entry_date::text,
               e.account_dt || '/' || e.account_kt, coalesce(e.doc_title, ''), e.amount
          FROM gl_entries e
         WHERE e.company_id = :cid
           AND (e.account_dt LIKE '09%' OR e.account_kt LIKE '09%'
             OR e.account_dt LIKE '77%' OR e.account_kt LIKE '77%')
           AND EXISTS (SELECT 1 FROM gl_references r WHERE r.company_id = :cid
                        AND r.kind = 'accounting_policy'
                        AND r.meta->>'ПБУ 18/02' = 'не ведётся')
         ORDER BY e.entry_date DESC"""),
    ("policy_reserves", "policy", "Резерв по сомнительным долгам при отключённом резерве",
     "Счёт 63 работает, хотя политика резервы не предусматривает — расход не обоснован", """
        SELECT e.id::text, e.entry_date::text,
               e.account_dt || '/' || e.account_kt, coalesce(e.doc_title, ''), e.amount
          FROM gl_entries e
         WHERE e.company_id = :cid
           AND (e.account_dt LIKE '63%' OR e.account_kt LIKE '63%')
           AND EXISTS (SELECT 1 FROM gl_references r WHERE r.company_id = :cid
                        AND r.kind = 'accounting_policy'
                        AND r.meta->>'Резервы по сомнительным долгам' = 'не формируются')
         ORDER BY e.entry_date DESC"""),
    ("policy_transit", "policy", "Переводы в пути при отключённом счёте 57",
     "Политика переводы в пути не использует, а счёт 57 в проводках есть", """
        SELECT e.id::text, e.entry_date::text,
               e.account_dt || '/' || e.account_kt, coalesce(e.doc_title, ''), e.amount
          FROM gl_entries e
         WHERE e.company_id = :cid
           AND (e.account_dt LIKE '57%' OR e.account_kt LIKE '57%')
           AND EXISTS (SELECT 1 FROM gl_references r WHERE r.company_id = :cid
                        AND r.kind = 'accounting_policy'
                        AND r.meta->>'Переводы в пути при перемещении денег' = 'не используются')
         ORDER BY e.entry_date DESC"""),
    ("policy_tax_mode", "policy", "Счета спецрежима при общей системе",
     "Режим общий, а в учёте работают счета УСН (68.12) — налог считается не тем способом", """
        SELECT e.id::text, e.entry_date::text,
               e.account_dt || '/' || e.account_kt, coalesce(e.doc_title, ''), e.amount
          FROM gl_entries e
         WHERE e.company_id = :cid
           AND (e.account_dt LIKE '68.12%' OR e.account_kt LIKE '68.12%')
           AND EXISTS (SELECT 1 FROM gl_references r WHERE r.company_id = :cid
                        AND r.kind = 'tax_mode'
                        AND r.meta->>'Система налогообложения' = 'Общая')
         ORDER BY e.entry_date DESC"""),
    ("policy_vat_payer", "policy", "Реализация без НДС у плательщика НДС",
     "Компания платит НДС, но у части реализаций налог не выделен — вычет и книга продаж поедут", """
        SELECT d.id::text, d.date, d.number, coalesce(d.counterparty_name, ''), d.amount
          FROM accounting_docs d
         WHERE d.company_id = :cid AND d.doc_type = 'sale'
           AND coalesce(d.vat_amount, 0) = 0 AND d.amount > 0
           AND EXISTS (SELECT 1 FROM gl_references r WHERE r.company_id = :cid
                        AND r.kind = 'tax_mode' AND r.meta->>'Плательщик НДС' = 'да')
         ORDER BY d.amount DESC"""),

    ("entries_no_doc", "books", "Проводки без первичного документа",
     "Проводка есть, документа под ней нет: обосновать запись нечем", """
        SELECT id::text, entry_date::text, coalesce(doc_kind, ''), coalesce(doc_title, ''), amount
          FROM gl_entries WHERE company_id = :cid AND doc_id IS NULL
         ORDER BY entry_date DESC"""),
    ("head_vs_lines", "books", "Сумма документа не сходится со строками",
     "Итог документа расходится с его же составом: обычно НДС начислен сверху", """
        SELECT d.id::text, d.date, d.number, d.counterparty_name, d.amount
          FROM accounting_docs d
         WHERE d.company_id = :cid AND jsonb_array_length(coalesce(d.lines,'[]'::jsonb)) > 0
           AND d.doc_type <> 'payroll_accrual'
           AND abs(d.amount - (SELECT coalesce(sum((l->>'amount')::numeric),0)
                                 FROM jsonb_array_elements(d.lines) l)) > 0.01
         ORDER BY d.date DESC"""),
    ("zero_amount", "books", "Документы с нулевой суммой",
     "Нулевая сумма у первички — обычно недозаполненный документ", """
        SELECT id::text, date, number, counterparty_name, amount
          FROM accounting_docs
         WHERE company_id = :cid AND amount = 0
           AND doc_type NOT IN ('closing_op', 'manual_entry', 'act_recon', 'vat_book_in',
                                'vat_book_out', 'tax_notice', 'payroll_accrual')
         ORDER BY date DESC"""),
    ("no_counterparty", "books", "Документы без контрагента",
     "Контрагент не сведён со справочником: документ не попадёт в его карточку и в акт сверки", """
        SELECT id::text, date, number, coalesce(counterparty_name, ''), amount
          FROM accounting_docs
         WHERE company_id = :cid AND counterparty_id IS NULL
           AND coalesce(counterparty_name, '') <> ''
         ORDER BY date DESC"""),

    ("payment_no_purpose", "money", "Платежи без назначения",
     "Назначение платежа — главный реквизит банковской операции: без него платёж не опознать", """
        SELECT id::text, date, number, counterparty_name, amount
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type IN ('bank_in', 'bank_out')
           AND coalesce(details->>'Назначение платежа', '') = ''
         ORDER BY date DESC"""),
    ("bank_no_article", "money", "Платежи без статьи движения денежных средств",
     "Без статьи ДДС платёж не встанет ни в один отчёт о движении денег", """
        SELECT id::text, date, number, counterparty_name, amount
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type IN ('bank_in', 'bank_out')
           AND coalesce(details->>'Статья ДДС', '') = ''
         ORDER BY date DESC"""),

    ("sale_no_sf", "vat_out", "Реализация без счёта-фактуры",
     "Покупатель не получит вычет и потребует документ; у нас — риск по книге продаж", """
        SELECT d.id::text, d.date, d.number, d.counterparty_name, d.amount
          FROM accounting_docs d
         WHERE d.company_id = :cid AND d.doc_type = 'sale' AND coalesce(d.vat_amount,0) > 0
           AND NOT EXISTS (SELECT 1 FROM accounting_docs v
                 WHERE v.company_id = d.company_id AND v.doc_type = 'vat_invoice_out'
                   AND coalesce(v.counterparty_inn,'') = coalesce(d.counterparty_inn,'')
                   AND abs(v.date::date - d.date::date) <= 31)
         ORDER BY d.date DESC"""),
    ("sf_out_no_base", "vat_out", "Счёт-фактура без документа-основания",
     "Не видно, чем подтверждена отгрузка: счёт-фактура сам по себе не первичка", """
        SELECT id::text, date, number, counterparty_name, amount
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type = 'vat_invoice_out'
           AND coalesce(details->>'Основание', '') = ''
         ORDER BY date DESC"""),

    ("purchase_no_sf", "vat_in", "Поступление без счёта-фактуры поставщика",
     "Вычет НДС заявить нечем — налог придётся заплатить полностью", """
        SELECT d.id::text, d.date, d.number, d.counterparty_name, d.amount
          FROM accounting_docs d
         WHERE d.company_id = :cid AND d.doc_type = 'purchase' AND coalesce(d.vat_amount,0) > 0
           AND NOT EXISTS (SELECT 1 FROM accounting_docs v
                 WHERE v.company_id = d.company_id AND v.doc_type = 'vat_invoice_in'
                   AND coalesce(v.counterparty_inn,'') = coalesce(d.counterparty_inn,'')
                   AND abs(v.date::date - d.date::date) <= 31)
         ORDER BY d.date DESC"""),
    ("sf_in_no_number", "vat_in", "Счёт-фактура поставщика без входящего номера",
     "В книге покупок нужен номер продавца, а не наш внутренний", """
        SELECT id::text, date, number, counterparty_name, amount
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type = 'vat_invoice_in'
           AND coalesce(external_number, '') = ''
         ORDER BY date DESC"""),

    ("payroll_unpaid", "payroll", "Начислено, но не выплачено",
     "Долг перед сотрудниками: сальдо 70 кредитом", None),
    ("ndfl_debt", "payroll", "НДФЛ удержан, но не перечислен",
     "Сальдо 68.01 кредитом — налог удержали у людей, в бюджет не отправили", None),

    ("nomenclature_dup", "goods", "Один код номенклатуры на две позиции",
     "Сопоставление строк документов промахнётся: код перестал быть ключом", """
        SELECT min(id::text), '', external_ref, string_agg(name, ' / '), 0
          FROM nomenclature WHERE company_id = :cid AND external_ref IS NOT NULL
         GROUP BY external_ref HAVING count(*) > 1"""),
    ("negative_stock", "goods", "Отрицательный остаток на складе",
     "Списали больше, чем приняли: либо не хватает поступления, либо ошибка в количестве", """
        SELECT id::text, as_of::text, account, coalesce(sub1, ''), credit - debit
          FROM gl_balances
         WHERE company_id = :cid AND account LIKE '41%' AND credit > debit
           AND as_of = (SELECT max(as_of) FROM gl_balances WHERE company_id = :cid)"""),

    ("closed_not_posted", "periods", "Непроведённые документы в закрытом периоде",
     "Период закрыт, а документ в учёт не попал: его сумма нигде не участвует", """
        SELECT d.id::text, d.date, d.number, d.counterparty_name, d.amount
          FROM accounting_docs d
          JOIN periods p ON p.company_id = d.company_id
               AND p.year = substr(d.date,1,4)::int AND p.month = substr(d.date,6,2)::int
         WHERE d.company_id = :cid AND d.status_1c = 'Не проведён' AND p.status = 'closed'
         ORDER BY d.date DESC"""),
    ("open_old", "periods", "Открытые периоды старше двух месяцев",
     "Месяц давно прошёл, а не закрыт: отчётность по нему ещё может поехать", """
        SELECT id::text, make_date(year, month, 1)::text, '', status, 0
          FROM periods
         WHERE company_id = :cid AND status <> 'closed'
           AND make_date(year, month, 1) < (CURRENT_DATE - INTERVAL '2 months')
         ORDER BY year DESC, month DESC"""),
]


@router.get("/checks")
async def checks(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Проверки состояния учёта, сгруппированные как экспресс-проверка в 1С."""
    cid = await assert_company_member(company_id, current_user, db)
    p = {"cid": str(cid)}
    out: list[dict[str, Any]] = []

    for key, group, title, risk, sql in _CHECKS:
        rows: list[dict[str, Any]] = []
        count = 0
        amount = 0.0
        if sql:
            found = (await db.execute(text(sql), p)).all()
            count = len(found)
            amount = round(sum(_num(r[4]) for r in found), 2)
            rows = [{"id": r[0], "date": r[1], "number": r[2],
                     "subject": r[3], "amount": _num(r[4])} for r in found[:50]]

        # Проверки-сверки: у них не список нарушителей, а цифра из регистра.
        if key == "payroll_unpaid":
            amount = _num((await db.execute(text("""
                SELECT coalesce(sum(credit - debit), 0) FROM gl_balances
                 WHERE company_id = :cid AND account LIKE '70%'
                   AND as_of = (SELECT max(as_of) FROM gl_balances WHERE company_id = :cid)"""),
                p)).scalar_one())
            count = 1 if amount > 0.004 else 0
        if key == "ndfl_debt":
            amount = _num((await db.execute(text("""
                SELECT coalesce(sum(credit - debit), 0) FROM gl_balances
                 WHERE company_id = :cid AND account LIKE '68.01%'
                   AND as_of = (SELECT max(as_of) FROM gl_balances WHERE company_id = :cid)"""),
                p)).scalar_one())
            count = 1 if amount > 0.004 else 0

        # Учётная политика: проверка на НАЛИЧИЕ, а не на отсутствие — там пусто плохо.
        if key in ("policy_lock", "policy_mpz"):
            status = "ok" if count else "warn"
            value = f"{count} записей" if count else "не задано"
        elif key in ("payroll_unpaid", "ndfl_debt"):
            status = "ok" if not count else "info"
            value = f"{amount:,.2f} ₽".replace(",", " ") if count else "нет долга"
        else:
            status = "ok" if not count else ("error" if key in (
                "purchase_no_sf", "sale_no_sf", "closed_not_posted", "negative_stock")
                else "warn")
            value = str(count) if count else "нет"

        out.append({"key": key, "group": group, "title": title, "risk": risk,
                    "status": status, "count": count, "amount": amount,
                    "value": value, "rows": rows})

    groups = [{
        "key": g, "title": t,
        "checks": [c for c in out if c["group"] == g],
        "errors": sum(1 for c in out if c["group"] == g and c["status"] == "error"),
        "warnings": sum(1 for c in out if c["group"] == g and c["status"] == "warn"),
    } for g, t in _CHECK_GROUPS]

    # Сама политика — рядом с проверками: сверять учёт с ней, не показывая её,
    # значит требовать от бухгалтера помнить настройки наизусть.
    policy = [{"kind": r[0], "title": r[1], "settings": r[2] or {}}
              for r in (await db.execute(text("""
        SELECT kind, name, meta FROM gl_references
         WHERE company_id = :cid AND kind IN ('accounting_policy', 'tax_mode')
         ORDER BY kind DESC"""), p)).all()]

    return {
        "groups": groups,
        "policy": policy,
        "errors": sum(1 for c in out if c["status"] == "error"),
        "warnings": sum(1 for c in out if c["status"] == "warn"),
        "ok": sum(1 for c in out if c["status"] == "ok"),
    }


# ── Реестр требований: что ждём от контрагентов и что для этого делали ───────
# Находка живёт до следующей перезагрузки данных. Требование — находка, взятая
# человеком под контроль: со сроком, ответственным, историей обращений и итогом.
# Реестр внутри «Бухгалтерии», а не в «Задачах» (решение МАГа): работа идёт от
# периода и контрагента, и требование обязано пересчитываться вместе с данными.

_REQUEST_STATUS = {
    "open": "На контроле", "requested": "Запрошен", "promised": "Обещан",
    "received": "Получен", "disputed": "Спорный", "dropped": "Не ждём",
}

# Чего ждём по каждому правилу и в каком виде документа это придёт.
_RULE_DOC_KIND = {
    "purchase_no_vat_invoice": "Счёт-фактура поставщика",
    "sale_no_vat_invoice": "Счёт-фактура покупателю (наш)",
    "payment_no_document": "Закрывающий документ (акт, накладная, УПД)",
    "invoice_paid_no_sale": "Отгрузка по оплаченному счёту (наша)",
    "not_posted": "Проведение документа (наше действие)",
}


@router.get("/requests")
async def doc_requests(
    company_id: str,
    period: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Реестр требований документов: по периоду, статусу и контрагенту."""
    cid = await assert_company_member(company_id, current_user, db)

    q = select(DocRequest).where(DocRequest.company_id == cid)
    if period:
        q = q.where(DocRequest.period == period)
    if status:
        q = q.where(DocRequest.status == status)
    rows = (await db.execute(q.order_by(DocRequest.period.desc(),
                                        DocRequest.amount.desc()))).scalars().all()

    today = date.today().isoformat()
    items = [{
        "id": str(r.id), "period": r.period, "rule": r.rule,
        "counterparty": r.counterparty_name,
        "counterpartyId": str(r.counterparty_id) if r.counterparty_id else None,
        "docKind": r.doc_kind, "amount": _num(r.amount),
        "status": r.status, "statusLabel": _REQUEST_STATUS.get(r.status, r.status),
        "channel": r.channel, "dueDate": r.due_date, "assignee": r.assignee,
        "contact": r.contact, "note": r.note,
        "escalations": r.escalations or [],
        # Просрочка — не отдельный статус, а состояние срока: статус говорит, что
        # сделали, срок — успели ли.
        "overdue": bool(r.due_date and r.due_date < today
                        and r.status in ("open", "requested", "promised")),
        "sourceDocId": str(r.source_doc_id) if r.source_doc_id else None,
        "resolvedAt": r.resolved_at.isoformat() if r.resolved_at else None,
    } for r in rows]

    by_status: dict[str, int] = {}
    for it in items:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1

    return {
        "items": items,
        "total": len(items),
        "open": sum(1 for i in items if i["status"] in ("open", "requested", "promised")),
        "overdue": sum(1 for i in items if i["overdue"]),
        "amount": round(sum(i["amount"] for i in items
                            if i["status"] in ("open", "requested", "promised")), 2),
        "byStatus": [{"status": k, "label": _REQUEST_STATUS.get(k, k), "count": v}
                     for k, v in sorted(by_status.items())],
    }


@router.post("/requests/from-gaps")
async def create_requests_from_gaps(
    company_id: str,
    rule: str,
    period: str | None = None,
    due_days: int = Query(14, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Поставить находки правила на контроль — по всему периоду разом.

    Повторный вызов безопасен: требование по той же находке не заводится второй раз,
    иначе история обращений расщепилась бы между дублями.
    """
    cid = await assert_company_member(company_id, current_user, db)
    data = await closing(company_id=company_id, period=period, db=db, current_user=current_user)
    gap = next((g for g in data["gaps"] if g["key"] == rule), None)
    if gap is None:
        raise HTTPException(status_code=404, detail="Правило не найдено")

    known = {str(r) for r in (await db.execute(
        select(DocRequest.source_doc_id).where(
            DocRequest.company_id == cid, DocRequest.rule == rule))).scalars() if r}

    created = 0
    due = (date.today() + timedelta(days=due_days)).isoformat()
    for row in gap["rows"]:
        if row["id"] in known:
            continue
        db.add(DocRequest(
            company_id=cid, period=row["period"] or (period or ""), rule=rule,
            counterparty_name=row["counterparty"] or "",
            source_doc_id=uuid.UUID(row["id"]),
            doc_kind=_RULE_DOC_KIND.get(rule, gap["title"]),
            amount=row["amount"], status="open", due_date=due,
            created_by=current_user.email,
        ))
        created += 1

    await db.commit()
    return {"created": created, "skipped": len(gap["rows"]) - created, "rule": rule,
            "title": gap["title"], "dueDate": due}


@router.patch("/requests/{request_id}")
async def update_request(
    request_id: str,
    company_id: str,
    status: str | None = None,
    channel: str | None = None,
    due_date: str | None = None,
    assignee: str | None = None,
    contact: str | None = None,
    note: str | None = None,
    escalation: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Изменить требование или дописать обращение в его ленту."""
    cid = await assert_company_member(company_id, current_user, db)
    try:
        uid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Требование не найдено")
    r = (await db.execute(select(DocRequest).where(
        DocRequest.company_id == cid, DocRequest.id == uid))).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Требование не найдено")

    if status:
        if status not in _REQUEST_STATUS:
            raise HTTPException(status_code=400, detail="Неизвестный статус")
        r.status = status
        if status in ("received", "dropped"):
            r.resolved_at = datetime.now(timezone.utc)
    if channel is not None:
        r.channel = channel or None
    if due_date is not None:
        r.due_date = due_date or None
    if assignee is not None:
        r.assignee = assignee or None
    if contact is not None:
        r.contact = contact or None
    if note is not None:
        r.note = note or None
    if escalation:
        # Обращение — запись в ленте, а не перезапись поля: важно, сколько раз и
        # каким каналом просили, а не только последний факт.
        r.escalations = [*(r.escalations or []), {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "who": current_user.email, "channel": channel or r.channel or "",
            "text": escalation,
        }]
        if r.status == "open":
            r.status = "requested"

    await db.commit()
    return {"id": str(r.id), "status": r.status,
            "statusLabel": _REQUEST_STATUS.get(r.status, r.status),
            "escalations": r.escalations or []}


@router.post("/requests/resolve")
async def resolve_requests(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Закрыть требования, по которым документ уже появился в слое.

    Требование закрывается ПОЯВЛЕНИЕМ ДОКУМЕНТА, а не кнопкой «сделано»: иначе реестр
    расходится с данными, и человек отчитывается о том, чего в учёте нет.
    """
    cid = await assert_company_member(company_id, current_user, db)
    rows = (await db.execute(select(DocRequest).where(
        DocRequest.company_id == cid,
        DocRequest.status.in_(("open", "requested", "promised"))))).scalars().all()

    # Какой вид документа закрывает какое правило.
    closes = {
        "purchase_no_vat_invoice": ("vat_invoice_in",),
        "sale_no_vat_invoice": ("vat_invoice_out",),
        "payment_no_document": ("purchase", "advance_report", "invoice_in"),
        "invoice_paid_no_sale": ("sale",),
    }

    resolved = 0
    for r in rows:
        types = closes.get(r.rule)
        if r.rule == "not_posted":
            # Наше действие: закрывается сменой статуса самого документа.
            doc = (await db.execute(select(AccountingDoc).where(
                AccountingDoc.id == r.source_doc_id))).scalar_one_or_none()
            if doc is not None and doc.status_1c == "Проведён":
                r.status, r.resolved_at = "received", datetime.now(timezone.utc)
                r.resolved_doc_id = doc.id
                resolved += 1
            continue
        if not types:
            continue
        found = (await db.execute(text("""
            SELECT d.id FROM accounting_docs d
             WHERE d.company_id = :cid AND d.doc_type = ANY(:types)
               AND substr(d.date, 1, 7) >= :period
               AND lower(coalesce(d.counterparty_name, '')) = lower(:name)
             ORDER BY d.date LIMIT 1"""),
            {"cid": str(cid), "types": list(types), "period": r.period,
             "name": r.counterparty_name})).scalar_one_or_none()
        if found:
            r.status, r.resolved_at = "received", datetime.now(timezone.utc)
            r.resolved_doc_id = found
            resolved += 1

    await db.commit()
    return {"checked": len(rows), "resolved": resolved}


# ── Налоги заранее: сколько заплатим, если закрыть период как есть ───────────
# Смысл раздела в том, что цифра нужна ДО закрытия, пока документы ещё можно
# собрать. Поэтому рядом с «как есть» всегда стоит второй сценарий: сколько
# станет, если недостающие документы придут. Разница между ними — цена работы
# по сбору первички, и она измеряется в рублях налога, а не в числе строк.
#
# Считаем ПО НАШИМ ДАННЫМ и честно называем это оценкой: декларацию формирует
# бухгалтерия, а здесь оперативный минимум, чтобы понимать порядок суммы.

_PROFIT_RATE = 0.20      # ставка налога на прибыль
_VAT_CALC = 20.0 / 120   # расчётная ставка НДС для сумм с налогом


@router.get("/tax-forecast")
async def tax_forecast(
    company_id: str,
    year: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Оценка НДС и налога на прибыль по кварталам плюс сценарий сбора документов."""
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid)}

    # НДС по книгам: продажи — начисленный, покупки — вычет. Берём журнал учёта
    # счетов-фактур, а не проводки: в декларацию идёт именно он.
    vat_rows = (await db.execute(text("""
        SELECT substr(doc_date, 1, 4) || '-Q' ||
               to_char(ceil(substr(doc_date, 6, 2)::numeric / 3), 'FM9') AS q,
               kind, sum(vat), count(*)
          FROM vat_entries
         WHERE company_id = :cid AND doc_date IS NOT NULL
         GROUP BY 1, 2"""), p)).all()

    quarters: dict[str, dict[str, Any]] = {}

    def slot(q: str) -> dict[str, Any]:
        return quarters.setdefault(q, {
            "quarter": q, "vatOut": 0.0, "vatIn": 0.0, "vatDue": 0.0,
            "income": 0.0, "expense": 0.0, "profit": 0.0, "profitTax": 0.0,
            "docsIssued": 0, "docsReceived": 0,
            "pendingVat": 0.0, "pendingExpense": 0.0,
        })

    for q, kind, vat, cnt in vat_rows:
        s = slot(q)
        if kind == "issued":
            s["vatOut"] += _num(vat)
            s["docsIssued"] += cnt
        elif kind == "received":
            s["vatIn"] += _num(vat)
            s["docsReceived"] += cnt

    # Прибыль: доходы без НДС против расходов — по оборотам регистра, а не по
    # документам: в расходы входит и то, у чего документа-первички нет (амортизация,
    # начисления), и брать их из документов было бы неверно.
    pl_rows = (await db.execute(text("""
        SELECT period_year || '-Q' || to_char(ceil(period_month::numeric / 3), 'FM9') AS q,
               sum(amount) FILTER (WHERE account_kt LIKE '90.01%')                       AS revenue,
               sum(amount) FILTER (WHERE account_dt LIKE '90.03%' OR account_dt LIKE '90.04%') AS vat_sales,
               sum(amount) FILTER (WHERE account_dt LIKE '90.02%' OR account_dt LIKE '90.07%'
                                      OR account_dt LIKE '90.08%')                       AS cost,
               sum(amount) FILTER (WHERE account_kt LIKE '91.01%')                       AS other_income,
               sum(amount) FILTER (WHERE account_dt LIKE '91.02%')                       AS other_expense
          FROM gl_entries WHERE company_id = :cid
         GROUP BY 1"""), p)).all()

    for q, revenue, vat_sales, cost, oth_in, oth_exp in pl_rows:
        s = slot(q)
        # Выручка приходит с НДС: налог с продаж списывается отдельной проводкой на
        # 90.03, поэтому вычитаем именно её, а не считаем расчётную ставку.
        s["income"] = round(_num(revenue) - _num(vat_sales) + _num(oth_in), 2)
        s["expense"] = round(_num(cost) + _num(oth_exp), 2)

    # Что даст сбор недостающих документов. Требования в работе — это будущие вычеты
    # (счёт-фактура поставщика) и будущие расходы (закрывающий документ по оплате).
    pending = (await db.execute(text("""
        SELECT substr(period, 1, 4) || '-Q' ||
               to_char(ceil(substr(period, 6, 2)::numeric / 3), 'FM9') AS q,
               rule, sum(amount), count(*)
          FROM doc_requests
         WHERE company_id = :cid AND status IN ('open', 'requested', 'promised')
         GROUP BY 1, 2"""), p)).all()

    for q, rule, amount, cnt in pending:
        s = slot(q)
        if rule == "purchase_no_vat_invoice":
            # Документ на руках, счёта-фактуры нет: придёт — появится вычет.
            s["pendingVat"] += round(_num(amount) * _VAT_CALC, 2)
        elif rule == "payment_no_document":
            # Оплата без закрывающего: придёт — вырастут расходы и появится вычет.
            s["pendingExpense"] += round(_num(amount) / 1.2, 2)
            s["pendingVat"] += round(_num(amount) * _VAT_CALC, 2)

    for s in quarters.values():
        s["vatDue"] = round(s["vatOut"] - s["vatIn"], 2)
        s["profit"] = round(s["income"] - s["expense"], 2)
        s["profitTax"] = round(max(s["profit"], 0) * _PROFIT_RATE, 2)
        # Сценарий «документы собраны»: вычет растёт, расходы растут, налог падает.
        s["vatDueIfCollected"] = round(s["vatDue"] - s["pendingVat"], 2)
        s["profitIfCollected"] = round(s["profit"] - s["pendingExpense"], 2)
        s["profitTaxIfCollected"] = round(max(s["profitIfCollected"], 0) * _PROFIT_RATE, 2)
        s["saving"] = round((s["vatDue"] - s["vatDueIfCollected"])
                            + (s["profitTax"] - s["profitTaxIfCollected"]), 2)

    rows = sorted(quarters.values(), key=lambda x: x["quarter"], reverse=True)
    if year:
        rows = [r for r in rows if r["quarter"].startswith(str(year))]

    # Налоги с зарплаты — оперативная справка: НДФЛ удержан и взносы начислены.
    payroll = (await db.execute(text("""
        SELECT coalesce(sum(amount) FILTER (WHERE kind = 'ndfl'), 0),
               coalesce(sum(amount) FILTER (WHERE kind = 'contribution'), 0)
          FROM payroll_entries WHERE company_id = :cid"""), p)).one()

    # Долги перед бюджетом на дату среза: что уже начислено и не уплачено.
    budget = [{"account": r[0], "name": r[1], "debt": _num(r[2])}
              for r in (await db.execute(text("""
        SELECT account, max(coalesce(account_name, '')), sum(credit - debit)
          FROM gl_balances
         WHERE company_id = :cid AND (account LIKE '68%' OR account LIKE '69%')
           AND as_of = (SELECT max(as_of) FROM gl_balances WHERE company_id = :cid)
         GROUP BY account HAVING abs(sum(credit - debit)) > 0.004
         ORDER BY 3 DESC"""), p)).all()]

    return {
        "quarters": rows,
        "totals": {
            "vatDue": round(sum(r["vatDue"] for r in rows), 2),
            "vatDueIfCollected": round(sum(r["vatDueIfCollected"] for r in rows), 2),
            "profitTax": round(sum(r["profitTax"] for r in rows), 2),
            "profitTaxIfCollected": round(sum(r["profitTaxIfCollected"] for r in rows), 2),
            "saving": round(sum(r["saving"] for r in rows), 2),
            "ndfl": _num(payroll[0]), "contributions": _num(payroll[1]),
        },
        "budget": budget,
        # Оценка, а не декларация: считаем по своим данным и говорим об этом прямо.
        "disclaimer": "Оценка по данным пространства. Декларацию формирует бухгалтерия: "
                      "здесь оперативный минимум, чтобы понимать порядок суммы заранее.",
    }


# ── Слой выгрузки: чем то, что уйдёт в 1С, отличается от слоя ────────────────
# Нормализованный слой — копия учёта клиента, «что есть». Выгрузка — «что мы
# предлагаем провести». Разделены намеренно: правка прямо в слое стёрла бы
# исходник, и через месяц данные 1С стало бы не отличить от нашей интерпретации.

_ADJ_FIELDS = {
    "amount": "Сумма документа",
    "vat_amount": "НДС документа",
    "date": "Дата документа",
    "cost_account": "Счёт затрат",
    "article": "Статья затрат",
    "contract": "Договор",
    "counterparty": "Контрагент",
    "status": "Проведение",
}
_ADJ_STATUS = {"draft": "Черновик", "approved": "Утверждена",
               "exported": "Выгружена", "rejected": "Отклонена"}


@router.get("/export-layer")
async def export_layer(
    company_id: str,
    period: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Что уйдёт в бухгалтерию и чем это отличается от слоя.

    Отдаёт корректировки с документами, их эффект на суммы и налог, а также правила,
    по которым корректировки повторяются в следующих периодах.
    """
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid), "period": period}

    q = select(ExportAdjustment).where(ExportAdjustment.company_id == cid)
    if period:
        q = q.where(ExportAdjustment.period == period)
    adjustments = (await db.execute(
        q.order_by(ExportAdjustment.created_at.desc()))).scalars().all()

    doc_ids = [a.doc_id for a in adjustments if a.doc_id]
    docs = {d.id: d for d in (await db.execute(select(AccountingDoc).where(
        AccountingDoc.id.in_(doc_ids)))).scalars()} if doc_ids else {}

    def num_or_none(v: str | None) -> float | None:
        try:
            return float(v) if v not in (None, "") else None
        except ValueError:
            return None

    items = []
    delta_amount = delta_vat = 0.0
    for a in adjustments:
        doc = docs.get(a.doc_id) if a.doc_id else None
        old_n, new_n = num_or_none(a.old_value), num_or_none(a.new_value)
        # Эффект считаем только по утверждённым: черновик — это предложение, и
        # налог по нему считать нельзя, иначе прогноз поедет от чужих раздумий.
        if a.status == "approved" and old_n is not None and new_n is not None:
            if a.field == "amount":
                delta_amount += new_n - old_n
            elif a.field == "vat_amount":
                delta_vat += new_n - old_n
        items.append({
            "id": str(a.id), "period": a.period, "field": a.field,
            "fieldLabel": _ADJ_FIELDS.get(a.field, a.field),
            "oldValue": a.old_value, "newValue": a.new_value,
            "reason": a.reason, "status": a.status,
            "statusLabel": _ADJ_STATUS.get(a.status, a.status),
            "createdBy": a.created_by, "approvedBy": a.approved_by,
            "ruleId": str(a.rule_id) if a.rule_id else None,
            "doc": ({"id": str(doc.id), "type": doc.doc_type,
                     "label": DOC_LABELS.get(doc.doc_type, doc.doc_type),
                     "number": doc.number, "date": doc.date,
                     "counterparty": doc.counterparty_name,
                     "amount": _num(doc.amount), "vat": _num(doc.vat_amount)}
                    if doc else None),
        })

    rules = [{
        "id": str(r.id), "name": r.name, "docType": r.doc_type,
        "docTypeLabel": DOC_LABELS.get(r.doc_type or "", r.doc_type or "любой"),
        "matchText": r.match_text, "field": r.field,
        "fieldLabel": _ADJ_FIELDS.get(r.field, r.field),
        "newValue": r.new_value, "reason": r.reason,
        "active": r.active, "validFrom": r.valid_from,
        "applied": 0,
    } for r in (await db.execute(select(ExportRule).where(
        ExportRule.company_id == cid).order_by(ExportRule.created_at.desc()))).scalars()]

    for r in rules:
        r["applied"] = sum(1 for a in adjustments if a.rule_id and str(a.rule_id) == r["id"])

    by_status: dict[str, int] = {}
    for it in items:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1

    return {
        "period": period,
        "adjustments": items,
        "rules": rules,
        "byStatus": [{"status": k, "label": _ADJ_STATUS.get(k, k), "count": v}
                     for k, v in sorted(by_status.items())],
        "effect": {
            # Что изменится в выгрузке против слоя, если провести утверждённое.
            "amount": round(delta_amount, 2),
            "vat": round(delta_vat, 2),
            "profitTax": round(-delta_amount * _PROFIT_RATE, 2),
            "docs": len({i["doc"]["id"] for i in items if i["doc"]}),
        },
    }


@router.post("/export-layer/adjustments")
async def create_adjustment(
    company_id: str,
    doc_id: str,
    field: str,
    new_value: str,
    reason: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Завести корректировку к документу. Слой при этом не меняется."""
    cid = await assert_company_member(company_id, current_user, db)
    if field not in _ADJ_FIELDS:
        raise HTTPException(status_code=400, detail="Это поле не корректируется")
    if not reason.strip():
        # Без причины корректировка неотличима от ошибки — и защитить её перед
        # проверяющим будет нечем.
        raise HTTPException(status_code=400, detail="Нужна причина корректировки")
    try:
        uid = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Документ не найден")

    doc = (await db.execute(select(AccountingDoc).where(
        AccountingDoc.company_id == cid, AccountingDoc.id == uid))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    old = {"amount": str(_num(doc.amount)), "vat_amount": str(_num(doc.vat_amount)),
           "date": doc.date, "status": doc.status_1c,
           "counterparty": doc.counterparty_name,
           "cost_account": (doc.details or {}).get("Счёт затрат"),
           "article": (doc.details or {}).get("Статья затрат"),
           "contract": (doc.details or {}).get("Договор")}.get(field)

    row = ExportAdjustment(
        company_id=cid, period=(doc.date or "")[:7], doc_id=doc.id, field=field,
        old_value=old, new_value=new_value, reason=reason.strip(),
        status="draft", created_by=current_user.email)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "period": row.period, "field": field,
            "oldValue": old, "newValue": new_value, "status": "draft"}


@router.patch("/export-layer/adjustments/{adj_id}")
async def update_adjustment(
    adj_id: str,
    company_id: str,
    status: str | None = None,
    new_value: str | None = None,
    reason: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Утвердить, отклонить или поправить корректировку."""
    cid = await assert_company_member(company_id, current_user, db)
    try:
        uid = uuid.UUID(adj_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Корректировка не найдена")
    a = (await db.execute(select(ExportAdjustment).where(
        ExportAdjustment.company_id == cid, ExportAdjustment.id == uid))).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Корректировка не найдена")
    if a.status == "exported":
        # Выгруженное не переписывается: изменение делается новой корректировкой,
        # иначе история того, что ушло в бухгалтерию, поедет задним числом.
        raise HTTPException(status_code=409, detail="Корректировка уже выгружена")

    if status:
        if status not in _ADJ_STATUS:
            raise HTTPException(status_code=400, detail="Неизвестный статус")
        a.status = status
        if status == "approved":
            a.approved_by = current_user.email
    if new_value is not None:
        a.new_value = new_value
    if reason is not None:
        a.reason = reason

    await db.commit()
    return {"id": str(a.id), "status": a.status,
            "statusLabel": _ADJ_STATUS.get(a.status, a.status)}


@router.post("/export-layer/rules")
async def create_rule(
    company_id: str,
    name: str,
    field: str,
    new_value: str,
    reason: str,
    doc_type: str | None = None,
    match_text: str | None = None,
    valid_from: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Запомнить решение на будущие периоды.

    Правило только ПРЕДЛАГАЕТ корректировки — утверждает их человек. Иначе через
    полгода в выгрузке живут решения, которых никто не помнит.
    """
    cid = await assert_company_member(company_id, current_user, db)
    if field not in _ADJ_FIELDS:
        raise HTTPException(status_code=400, detail="Это поле не корректируется")
    row = ExportRule(
        company_id=cid, name=name, doc_type=doc_type or None,
        match_text=match_text or None, field=field, new_value=new_value,
        reason=reason, valid_from=valid_from or None, created_by=current_user.email)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "name": row.name}


@router.post("/export-layer/apply-rules")
async def apply_rules(
    company_id: str,
    period: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Применить правила к периоду: завести корректировки-черновики.

    Черновики, а не готовые правки: решение прошлого квартала может не подойти
    этому, и человек обязан его увидеть до выгрузки.
    """
    cid = await assert_company_member(company_id, current_user, db)
    rules = (await db.execute(select(ExportRule).where(
        ExportRule.company_id == cid, ExportRule.active.is_(True)))).scalars().all()
    if not rules:
        return {"created": 0, "rules": 0}

    docs = (await db.execute(select(AccountingDoc).where(
        AccountingDoc.company_id == cid,
        func.substr(AccountingDoc.date, 1, 7) == period))).scalars().all()
    known = {(str(a.doc_id), a.field) for a in (await db.execute(select(ExportAdjustment).where(
        ExportAdjustment.company_id == cid, ExportAdjustment.period == period))).scalars()}

    created = 0
    for rule in rules:
        if rule.valid_from and period < rule.valid_from:
            continue
        for doc in docs:
            if rule.doc_type and doc.doc_type != rule.doc_type:
                continue
            if rule.counterparty_id and doc.counterparty_id != rule.counterparty_id:
                continue
            if rule.match_text:
                hay = " ".join(filter(None, [doc.counterparty_name, doc.number,
                                             doc.operation_type or ""])).lower()
                if rule.match_text.lower() not in hay:
                    continue
            if (str(doc.id), rule.field) in known:
                continue
            old = {"amount": str(_num(doc.amount)), "vat_amount": str(_num(doc.vat_amount)),
                   "date": doc.date, "status": doc.status_1c,
                   "counterparty": doc.counterparty_name,
                   "cost_account": (doc.details or {}).get("Счёт затрат"),
                   "article": (doc.details or {}).get("Статья затрат"),
                   "contract": (doc.details or {}).get("Договор")}.get(rule.field)
            if old == rule.new_value:
                continue      # уже такое, править нечего
            db.add(ExportAdjustment(
                company_id=cid, period=period, doc_id=doc.id, field=rule.field,
                old_value=old, new_value=rule.new_value,
                reason=f"{rule.reason} (правило «{rule.name}»)",
                status="draft", rule_id=rule.id, created_by=current_user.email))
            created += 1

    await db.commit()
    return {"created": created, "rules": len(rules), "period": period}


# ── Тенденции: на что бухгалтеру посмотреть ──────────────────────────────────
# Проверки ловят нарушенное правило. Здесь другое: правило не нарушено, но цифра
# ведёт себя необычно — расход вырос вдвое, документ проведён задним числом,
# контрагент появился и исчез. Это не ошибки, это поводы посмотреть, и подавать
# их надо именно так, иначе экран превращается в генератор ложных тревог.


@router.get("/trends")
async def trends(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Динамика по месяцам и находки, которые стоит объяснить."""
    cid = await assert_company_member(company_id, current_user, db)
    p: dict[str, Any] = {"cid": str(cid)}

    months = [{
        "month": r[0], "revenue": _num(r[1]), "cost": _num(r[2]),
        "expense": _num(r[3]), "profit": round(_num(r[1]) - _num(r[2]) - _num(r[3]), 2),
        "docs": r[4],
    } for r in (await db.execute(text("""
        WITH e AS (
          SELECT period_year || '-' || lpad(period_month::text, 2, '0') AS m,
                 sum(amount) FILTER (WHERE account_kt LIKE '90.01%')
               - sum(amount) FILTER (WHERE account_dt LIKE '90.03%') AS revenue,
                 sum(amount) FILTER (WHERE account_dt LIKE '90.02%') AS cost,
                 sum(amount) FILTER (WHERE account_dt LIKE '44%' OR account_dt LIKE '26%') AS expense
            FROM gl_entries WHERE company_id = :cid GROUP BY 1
        ), d AS (
          SELECT substr(date, 1, 7) AS m, count(*) AS docs
            FROM accounting_docs WHERE company_id = :cid GROUP BY 1
        )
        SELECT e.m, coalesce(e.revenue, 0), coalesce(e.cost, 0), coalesce(e.expense, 0),
               coalesce(d.docs, 0)
          FROM e LEFT JOIN d ON d.m = e.m
         ORDER BY e.m"""), p)).all()]

    findings: list[dict[str, Any]] = []

    def add(key: str, title: str, why: str, rows: list[dict[str, Any]]) -> None:
        if rows:
            findings.append({"key": key, "title": title, "why": why,
                             "count": len(rows), "rows": rows[:30]})

    # 1. Резкий скачок расходов против среднего за три предыдущих месяца.
    jumps = []
    for i, m in enumerate(months):
        if i < 3:
            continue
        base = [x["expense"] for x in months[i - 3:i] if x["expense"]]
        if len(base) < 3:
            continue
        avg = sum(base) / len(base)
        if avg > 0 and m["expense"] > avg * 2 and m["expense"] - avg > 50_000:
            jumps.append({"period": m["month"], "subject": "Расходы периода",
                          "amount": m["expense"],
                          "note": f"среднее за три месяца до этого {avg:,.0f} ₽".replace(",", " ")})
    add("expense_jump", "Расходы выросли вдвое к среднему",
        "Не ошибка, но такой скачок объясняют: разовая закупка, годовая оплата или чужой документ",
        jumps)

    # 2. Документы, датированные будущим. Проверка «изменён после закрытия периода»
    #    невозможна: `created_at` — это время НАШЕЙ загрузки, а не правки в 1С, и
    #    сравнение с закрытием периода дало бы сто ложных тревог подряд.
    future = [{"period": (r[1] or "")[:7],
               "subject": f"{DOC_LABELS.get(r[2], r[2])} № {r[3]} · {r[4]}",
               "amount": _num(r[0]), "note": f"дата документа {r[1]}"}
              for r in (await db.execute(text("""
        SELECT amount, date, doc_type, number, coalesce(counterparty_name, '')
          FROM accounting_docs
         WHERE company_id = :cid AND date > to_char(CURRENT_DATE, 'YYYY-MM-DD')
         ORDER BY date DESC LIMIT 50"""), p)).all()]
    add("future_dated", "Документы датированы будущим",
        "Дата позже сегодняшней: обычно опечатка в дате, но в закрытом периоде это уже расхождение",
        future)

    # 3. Контрагент с одной-двумя операциями на крупную сумму: разовые поставщики —
    #    первое, что смотрят при проверке обоснованности расходов.
    once = [{"period": r[2], "subject": r[0], "amount": _num(r[1]),
             "note": f"операций всего {r[3]}"}
            for r in (await db.execute(text("""
        SELECT counterparty_name, sum(amount), max(substr(date, 1, 7)), count(*)
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type IN ('purchase', 'invoice_in')
           AND coalesce(counterparty_name, '') <> ''
         GROUP BY 1 HAVING count(*) <= 2 AND sum(amount) > 300000
         ORDER BY 2 DESC LIMIT 50"""), p)).all()]
    add("one_off_supplier", "Разовый поставщик на крупную сумму",
        "Одна-две операции на сотни тысяч — обычный повод показать договор и деловую цель",
        once)

    # 4. Круглые суммы у расходных документов: не нарушение, но признак, на который
    #    смотрит проверяющий.
    round_docs = [{"period": (r[1] or "")[:7],
                   "subject": f"{DOC_LABELS.get(r[3], r[3])} № {r[2]} · {r[4]}",
                   "amount": _num(r[0]), "note": "сумма без копеек и кратна 10 000"}
                  for r in (await db.execute(text("""
        SELECT amount, date, number, doc_type, coalesce(counterparty_name, '')
          FROM accounting_docs
         WHERE company_id = :cid AND doc_type IN ('purchase', 'invoice_in')
           AND amount >= 100000 AND amount = round(amount) AND (amount::numeric % 10000) = 0
         ORDER BY amount DESC LIMIT 50"""), p)).all()]
    add("round_amounts", "Круглые суммы в расходах",
        "Само по себе не нарушение, но проверяющий смотрит на них первыми — держите обоснование",
        round_docs)

    # 5. Контрагенты, у которых мы покупаем и которым продаём одновременно.
    both = [{"period": "", "subject": r[0], "amount": _num(r[1]) + _num(r[2]),
             "note": f"продали на {_num(r[1]):,.0f}, купили на {_num(r[2]):,.0f}".replace(",", " ")}
            for r in (await db.execute(text("""
        SELECT counterparty_name,
               sum(amount) FILTER (WHERE doc_type = 'sale'),
               sum(amount) FILTER (WHERE doc_type = 'purchase')
          FROM accounting_docs
         WHERE company_id = :cid AND coalesce(counterparty_name, '') <> ''
         GROUP BY 1
        HAVING sum(amount) FILTER (WHERE doc_type = 'sale') > 0
           AND sum(amount) FILTER (WHERE doc_type = 'purchase') > 0
         ORDER BY 2 DESC LIMIT 30"""), p)).all()]
    add("mutual_trade", "И покупаем, и продаём одному контрагенту",
        "Встречные операции — нормальная практика, но взаимозачёт и НДС по ним проверяют внимательнее",
        both)

    # 6. Месяцы, где расход есть, а выручки нет вовсе.
    idle = [{"period": m["month"], "subject": "Месяц без выручки",
             "amount": m["expense"], "note": "расходы есть, продаж нет"}
            for m in months if m["expense"] > 50_000 and m["revenue"] <= 0]
    add("expense_no_revenue", "Расходы без выручки в месяце",
        "Для налоговой это повод спросить о деловой цели: расход есть, дохода нет",
        idle)

    return {
        "months": months[-36:],
        "findings": findings,
        "summary": {
            "months": len(months),
            "findings": sum(f["count"] for f in findings),
            "kinds": len(findings),
        },
    }
