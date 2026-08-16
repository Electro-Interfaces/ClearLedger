"""Системы налогообложения: какой налог считать организации и по какой ставке.

Один модуль на всё пространство. До него налог считался в двух местах и обоими
способами одинаково — как ОСНО: НДС по счёту 68.02 плюс налог на прибыль по
зашитой в код ставке. На пилоте это уже врало: РТИ работает на УСН «Доходы минус
расходы» (счёт 68.12, КУДиР в выгрузке), а ей показывали налог на прибыль,
которого она не платит вовсе.

Два правила, которые здесь соблюдаются:

1. **Ставка — данные, а не константа.** Ставки и пороги лежат в `tax_regime_rates`
   с периодом действия и выбираются на дату ПЕРИОДА, за который считаем. Налог на
   прибыль вырос с 20 до 25 % в 2025-м, НДС — с 20 до 22 % в 2026-м; зашитый в код
   процент пересчитал бы задним числом уже сданную отчётность.

2. **Режим берётся из учёта организации, а не из настроек компании.** В одном
   пространстве соседствуют ОСНО и УСН, а ИП вдобавок совмещает УСН с патентом.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class Regime:
    """Действующий режим организации со ставками на нужную дату."""

    code: str
    name: str
    short_name: str
    object: str | None
    pays_vat: bool
    pays_profit_tax: bool
    tax_account: str | None
    rate: float | None                       # основная ставка, %
    rate_minimum_tax: float | None           # минимальный налог УСН/АУСН, % от доходов
    vat_rate: float | None                   # ставка НДС на дату, %
    vat_threshold: float | None              # доход, выше которого возникает НДС
    limit_income: float | None
    source: str | None
    note: str | None
    # Совмещаемые режимы (патент рядом с УСН) — отдельными записями.
    combined: list[str] = field(default_factory=list)


async def regime_of(db: AsyncSession, company_id: str, organization_id: str | None,
                    on: date | None = None) -> Regime | None:
    """Режим организации на дату. `None` — режим не заведён (а не «ОСНО по умолчанию»).

    Молча подставлять ОСНО нельзя: экран покажет НДС и прибыль тому, кто их не
    платит, и человек будет считать это правдой. Пусть лучше честно скажет, что
    режим не указан.
    """
    on = on or date.today()
    if not organization_id:
        return None

    row = (await db.execute(text("""
        SELECT t.regime_code, t.rate AS own_rate, t.source, t.note, t.vat_payer,
               r.name, r.short_name, r.object, r.pays_vat, r.pays_profit_tax,
               r.tax_account
          FROM organization_tax_regimes t
          JOIN tax_regimes r ON r.code = t.regime_code
         WHERE t.company_id = CAST(:cid AS uuid)
           AND t.organization_id = CAST(:oid AS uuid)
           AND t.is_primary
           AND t.valid_from <= CAST(:on AS date)
           AND (t.valid_to IS NULL OR t.valid_to >= CAST(:on AS date))
         ORDER BY t.valid_from DESC, t.created_at DESC LIMIT 1"""),
        {"cid": company_id, "oid": organization_id, "on": on})).first()
    if row is None:
        return None

    rates = {k: float(v) for k, v in (await db.execute(text("""
        SELECT kind, value FROM tax_regime_rates
         WHERE regime_code = :code
           AND valid_from <= CAST(:on AS date)
           AND (valid_to IS NULL OR valid_to >= CAST(:on AS date))"""),
        {"code": row.regime_code, "on": on})).all()}

    combined = [c for (c,) in (await db.execute(text("""
        SELECT regime_code FROM organization_tax_regimes
         WHERE organization_id = CAST(:oid AS uuid) AND NOT is_primary
           AND valid_from <= CAST(:on AS date)
           AND (valid_to IS NULL OR valid_to >= CAST(:on AS date))"""),
        {"oid": organization_id, "on": on})).all()]

    return Regime(
        code=row.regime_code, name=row.name, short_name=row.short_name,
        object=row.object,
        # Признак плательщика НДС может быть переопределён по факту: на УСН он
        # следует из оборота, и решает это бухгалтер, а не справочник.
        pays_vat=row.vat_payer if row.vat_payer is not None else row.pays_vat,
        pays_profit_tax=row.pays_profit_tax, tax_account=row.tax_account,
        rate=row.own_rate if row.own_rate is not None else rates.get("rate"),
        rate_minimum_tax=rates.get("rate_minimum_tax"),
        vat_rate=rates.get("vat_rate"), vat_threshold=rates.get("vat_threshold"),
        limit_income=rates.get("limit_income"),
        source=row.source, note=row.note, combined=combined)


async def usn_base(db: AsyncSession, organization_id: str,
                   since: date, till: date) -> tuple[float, float] | None:
    """База УСН за период по КУДиР: учитываемые доходы и расходы.

    Считать базу УСН по счетам 90-х нельзя. На упрощёнке доходы признаются по
    оплате, а расходы — только из закрытого перечня НК и лишь после оплаты; в
    оборотах 90.02/90.07 их может не быть вовсе. На пилоте так и вышло: у РТИ
    расход по счетам 0 ₽, и налог считался со всей выручки, завышая его вчетверо.

    Книга ведётся в 1С и приезжает выгрузкой (`gl_references.kind = 'kudir'`).
    Организация в книге записана ИМЕНЕМ 1С — связываем по нему: своего ключа у
    строк книги нет.
    """
    rows = (await db.execute(text("""
        SELECT r.meta FROM gl_references r
          JOIN organizations o ON o.id = CAST(:oid AS uuid)
         WHERE r.kind = 'kudir'
           AND r.meta->>'Организация1С' IS NOT NULL
           AND replace(replace(lower(r.meta->>'Организация1С'), '«', ''), '»', '')
               LIKE '%' || lower(split_part(replace(replace(o.name, '«', ''), '»', ''), ' ', 1)) || '%'
           AND (r.meta->>'Период')::date BETWEEN CAST(:a AS date) AND CAST(:b AS date)"""),
        {"oid": organization_id, "a": since, "b": till})).scalars().all()
    if not rows:
        return None

    income = expense = 0.0
    for raw in rows:
        m = raw if isinstance(raw, dict) else json.loads(raw)
        income += float(m.get("ДоходыУчитываемые") or 0)
        expense += float(m.get("РасходыУчитываемые") or 0)
    return income, expense


async def contributions_of(db: AsyncSession, company_id: str, organization_id: str,
                           year: int, income: float) -> dict[str, Any]:
    """Взносы ИП за год: сколько должен, сколько уплатил, чем можно уменьшить налог.

    Взносы платит предприниматель за себя независимо от режима, но на налог они
    влияют по-разному: УСН «Доходы» и патент уменьшаются на уплаченные взносы (ИП
    без работников — до нуля), а на УСН «Доходы минус расходы» взносы просто
    входят в расходы.

    Считается по УПЛАЧЕННЫМ, а не начисленным: уменьшить налог можно только на то,
    что фактически перечислено.
    """
    ref = (await db.execute(text("""
        SELECT fixed_amount, extra_rate, extra_threshold, extra_max, confidence, note
          FROM ip_contributions WHERE year = :y"""), {"y": year})).first()
    if ref is None:
        return {"known": False,
                "note": f"Суммы взносов за {year} год в справочнике нет."}

    extra = max(income - float(ref.extra_threshold), 0) * float(ref.extra_rate) / 100
    if ref.extra_max is not None:
        extra = min(extra, float(ref.extra_max))

    paid = float((await db.execute(text("""
        SELECT coalesce(sum(amount), 0) FROM ip_contribution_payments
         WHERE organization_id = CAST(:oid AS uuid) AND year = :y"""),
        {"oid": organization_id, "y": year})).scalar() or 0)

    return {
        "known": True,
        "year": year,
        "fixed": float(ref.fixed_amount),
        "extra": round(extra, 2),
        "total": round(float(ref.fixed_amount) + extra, 2),
        "paid": paid,
        # Цифра будущего года публикуется заранее, но правится: об этом честнее
        # сказать, чем выдать её за окончательную.
        "confidence": ref.confidence,
        "note": ref.note,
    }


# Счёт фиксированных взносов ИП за себя в типовой 1С. Взносы за СОТРУДНИКОВ идут по
# 69.01–69.03 и 69.09 — их сюда брать нельзя: налог они не уменьшают тем же образом.
IP_CONTRIB_ACCOUNT = "69.06"


async def sync_contributions(db: AsyncSession, company_id: str, organization_id: str,
                             year: int) -> dict[str, Any]:
    """Забрать уплаченные взносы ИП из проводок за год.

    Уплатой считается списание со счёта взносов в кредит денег (51) или ЕНС
    (68.90): начисление налог не уменьшает, уменьшает только платёж.
    """
    rows = (await db.execute(text("""
        SELECT e.entry_date::date AS paid_on, e.amount, e.account_dt
          FROM gl_entries e
         WHERE e.company_id = CAST(:cid AS uuid)
           AND e.organization_id = CAST(:oid AS uuid)
           AND e.period_year = :y
           AND e.account_dt LIKE :acc || '%'
           AND (e.account_kt LIKE '51%' OR e.account_kt LIKE '68.90%')"""),
        {"cid": company_id, "oid": organization_id, "y": year,
         "acc": IP_CONTRIB_ACCOUNT})).all()

    added = 0
    for r in rows:
        exists = (await db.execute(text("""
            SELECT 1 FROM ip_contribution_payments
             WHERE organization_id = CAST(:oid AS uuid)
               AND paid_on = CAST(:paid AS date) AND amount = :amt"""),
            {"oid": organization_id, "paid": r.paid_on, "amt": r.amount})).first()
        if exists:
            continue
        # Однопроцентную часть в типовой 1С ведут отдельным субсчётом; если его нет,
        # платёж считается фиксированным — бухгалтер поправит вид, если нужно.
        kind = "extra" if str(r.account_dt).startswith("69.06.5") else "fixed"
        await db.execute(text("""
            INSERT INTO ip_contribution_payments
                (company_id, organization_id, kind, amount, paid_on, year, note)
            VALUES (CAST(:cid AS uuid), CAST(:oid AS uuid), :kind, :amt,
                    CAST(:paid AS date), :y, 'из проводок по счёту ' || :acc)"""),
            {"cid": company_id, "oid": organization_id, "kind": kind,
             "amt": r.amount, "paid": r.paid_on, "y": year, "acc": r.account_dt})
        added += 1

    await db.commit()
    return {"found": len(rows), "added": added,
            "note": ("Взносы за сотрудников (69.01–69.09) не берутся: налог по УСН "
                     "и патенту уменьшают взносы предпринимателя за себя."
                     if rows else
                     f"Проводок по счёту {IP_CONTRIB_ACCOUNT} за {year} год нет.")}


async def estimate_tax(db: AsyncSession, company_id: str, organization_id: str | None,
                       since: date, till: date, *, income: float, expense: float,
                       vat_accrued: float) -> dict[str, Any]:
    """Оценка налогов периода по режиму организации.

    `income`/`expense` — выручка и расход периода как их считает «Бухгалтерия»
    (списанное на финрезультат, а не обороты затратных счетов). `vat_accrued` —
    НДС по счёту 68.02, то есть факт начисления, а не расчёт от выручки.

    Возвращает список строк «что платим» — по одной на налог, с основанием. Без
    основания цифра налога бесполезна: её нельзя ни проверить, ни оспорить.
    """
    r = await regime_of(db, company_id, organization_id, till)
    if r is None:
        return {"regime": None, "lines": [],
                "note": "Система налогообложения не указана — налоги не считаются. "
                        "Укажите режим в карточке организации."}

    lines: list[dict[str, Any]] = []
    profit = income - expense
    basis_note = "по данным учёта"

    # У спецрежимов своя база: КУДиР ведётся именно для неё, и она точнее
    # оборотов по счетам 90-х (см. `usn_base`).
    if r.object in ("income", "income_minus_expense") and r.code != "eshn":
        book = await usn_base(db, organization_id, since, till)
        if book is not None:
            income, expense = book
            profit = income - expense
            basis_note = "по КУДиР"


    if r.pays_vat and vat_accrued:
        lines.append({
            "key": "vat", "title": "НДС",
            "amount": round(vat_accrued, 2),
            "basis": "начислено по счёту 68.02 за период"
                     + (f" · ставка {r.vat_rate:.0f} %" if r.vat_rate else ""),
        })

    if r.code == "osno" and r.pays_profit_tax:
        rate = r.rate or 0
        lines.append({
            "key": "profit", "title": "Налог на прибыль",
            "amount": round(max(profit, 0) * rate / 100, 2),
            "basis": f"{rate:.0f} % от прибыли {profit:,.0f} ₽".replace(",", " "),
        })

    elif r.object == "income":
        rate = r.rate or 0
        lines.append({
            "key": "usn", "title": r.short_name or "Налог по режиму",
            "amount": round(max(income, 0) * rate / 100, 2),
            "basis": (f"{rate:.0f} % от доходов {income:,.0f} ₽ "
                      f"({basis_note})").replace(",", " "),
        })

    elif r.object == "income_minus_expense":
        rate = r.rate or 0
        main = max(profit, 0) * rate / 100
        # Минимальный налог: на УСН 15 % платят не меньше 1 % от доходов, даже в
        # убыток. Без этого правила система обещала бы ноль там, где платить надо.
        minimum = max(income, 0) * (r.rate_minimum_tax or 0) / 100
        pay_min = minimum > main
        lines.append({
            "key": "usn", "title": r.short_name or "Налог по режиму",
            "amount": round(max(main, minimum), 2),
            "basis": (f"минимальный налог {r.rate_minimum_tax:.0f} % от доходов "
                      f"{income:,.0f} ₽ — он больше расчётного".replace(",", " ")
                      if pay_min else
                      (f"{rate:.0f} % от разницы {profit:,.0f} ₽ "
                       f"({basis_note})").replace(",", " ")),
        })

    elif r.object == "patent":
        cost = float((await db.execute(text("""
            SELECT coalesce(sum(cost), 0) FROM tax_patents
             WHERE organization_id = CAST(:oid AS uuid)
               AND valid_from <= CAST(:till AS date) AND valid_to >= CAST(:since AS date)"""),
            {"oid": organization_id, "since": since, "till": till})).scalar() or 0)
        lines.append({
            "key": "psn", "title": "Патент",
            "amount": round(cost, 2),
            "basis": "стоимость патентов, действующих в периоде"
                     if cost else "патенты за период не заведены",
        })

    # ── Уменьшение налога на взносы ────────────────────────────────────────
    # Только у ИП и только там, где это предусмотрено: УСН «Доходы» и патент
    # уменьшаются на уплаченные взносы, «Доходы минус расходы» — нет, там взносы
    # уже сидят в расходах, и вычесть их второй раз значит занизить налог.
    contrib: dict[str, Any] | None = None
    form = (await db.execute(text(
        "SELECT legal_form FROM organizations WHERE id = CAST(:oid AS uuid)"),
        {"oid": organization_id})).scalar() if organization_id else None

    if form == "ip" and r.code in ("usn_income", "psn"):
        contrib = await contributions_of(db, company_id, organization_id,
                                         till.year, income)
        if contrib.get("known") and contrib["paid"] > 0 and lines:
            main = lines[-1]
            before = main["amount"]
            main["amount"] = round(max(before - contrib["paid"], 0), 2)
            main["basis"] += (
                f" − уплаченные взносы {contrib['paid']:,.0f} ₽".replace(",", " "))
            if main["amount"] == 0:
                main["basis"] += " (налог погашен взносами полностью)"

    # Порог НДС на спецрежиме — предупреждение, а не налог: превысив его, компания
    # становится плательщиком НДС, и узнать об этом лучше заранее.
    warn = None
    if r.vat_threshold and income > r.vat_threshold and not r.pays_vat:
        warn = (f"Доход {income:,.0f} ₽ превысил порог {r.vat_threshold:,.0f} ₽ — "
                f"на этом режиме возникает обязанность по НДС.").replace(",", " ")
    if r.limit_income and income > r.limit_income:
        warn = (f"Доход {income:,.0f} ₽ выше предела {r.limit_income:,.0f} ₽ — "
                f"право на режим утрачивается.").replace(",", " ")

    return {
        "regime": {"code": r.code, "name": r.name, "short": r.short_name,
                   "source": r.source, "combined": r.combined},
        "lines": lines,
        "total": round(sum(x["amount"] for x in lines), 2),
        "warning": warn,
        "note": r.note,
        "contributions": contrib,
    }
