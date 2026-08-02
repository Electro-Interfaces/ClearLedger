"""Разворот ожиданий: что мы должны собрать по договорам за каждый период.

ЗАЧЕМ. Контрагенты обязаны сами выставлять закрывающие документы и делают это
не всегда — в рабочем файле заказчика 54 пометки «Нет расчёта», ежемесячно 3–6
станций закрываются без первички, а дыра перекрывается через месяц записью
«за период янв–апр». Пока список ожиданий держит человек в голове и в колонках
Excel, «не пришло» неотличимо от «не смотрели».

Ожидание разворачивается ИЗ УСЛОВИЯ ДОГОВОРА автоматически: раз договор
действует и говорит «5000 ₽ в месяц до 10-го числа», строка появляется сама.

ДОГОВОРЫ ПЕРЕХОДЯЩИЕ, И ЭТО ГЛАВНОЕ. Объект работает не только в этом месяце, и
документы по нему нужны каждый месяц или каждый квартал — в зависимости от
условия. Значит ожидания на год вперёд известны заранее, и разворачивать их
надо диапазоном, а не по одному месяцу: только тогда видно, где дыры в прошлом
и что предстоит собрать в ближайшие недели.

Идемпотентность. Повтор безопасен: строки, которые уже ведёт человек (пришёл
документ, поставлена ручная сумма, оспорено), не трогаем — обновляем только те,
что всё ещё ждут.
"""
from __future__ import annotations

import calendar
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contract,
    ContractLocation,
    OpsContractTerm,
    OpsCostItem,
    OpsPeriodCharge,
    StationEnergyPeriod,
)

# Сколько закрытых периодов берём в среднее. Три — компромисс: одного мало
# (сезонность), год размывает свежее изменение ставки.
AVERAGE_WINDOW = 3
# До какого числа следующего месяца ждём документ, если в условии не задано.
DEFAULT_DOC_DUE_DAY = 10
# Виды договоров, по которым отсутствие условия — это дырка, а не норма.
COST_CONTRACT_TYPES = ("rent", "energy_supply")


# ── Периоды ────────────────────────────────────────────────────────────────

def month_bounds(period: str) -> tuple[str, str]:
    """Первое и последнее число месяца ISO-строками ('2026-07-01' → …-07-31)."""
    y, m = int(period[0:4]), int(period[5:7])
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def shift_month(period: str, delta: int) -> str:
    """Сдвиг периода на delta месяцев ('2026-01-01', -1) → '2025-12-01'."""
    y, m = int(period[0:4]), int(period[5:7])
    total = y * 12 + (m - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}-01"


def month_range(date_from: str, date_to: str) -> list[str]:
    """Список месяцев от и до включительно."""
    out, cur = [], f"{date_from[:7]}-01"
    last = f"{date_to[:7]}-01"
    while cur <= last and len(out) < 120:
        out.append(cur)
        cur = shift_month(cur, 1)
    return out


def _due_on(period: str, day: int | None) -> str:
    """Срок предоставления документа: N-е число СЛЕДУЮЩЕГО месяца.

    День больше длины месяца (31 в феврале) сдвигаем на последний — иначе
    получилась бы несуществующая дата, по которой просрочка не считается.
    """
    nxt = shift_month(period, 1)
    y, m = int(nxt[0:4]), int(nxt[5:7])
    d = min(int(day or DEFAULT_DOC_DUE_DAY), calendar.monthrange(y, m)[1])
    return f"{y:04d}-{m:02d}-{d:02d}"


def _due_in_period(term: OpsContractTerm, period: str) -> bool:
    """Есть ли по этому условию ожидание именно в этом месяце.

    Квартальный договор даёт одну строку в квартал, а не три: иначе реестр
    показал бы тройную сумму, а сотрудник три месяца искал бы два недостающих
    документа, которых не существует.
    """
    kind = (term.periodicity or "monthly").lower()
    if kind == "monthly":
        return True
    start_m = int(term.valid_from[5:7])
    cur_m = int(period[5:7])
    if kind == "quarterly":
        return (cur_m - start_m) % 3 == 0
    if kind == "annual":
        return cur_m == start_m
    if kind == "one_time":
        return period[:7] == term.valid_from[:7]
    return True


# ── Контекст разворота ─────────────────────────────────────────────────────

class ExpandCtx:
    """Всё, что нужно разворотy, загруженное разом.

    Без него каждое условие тянуло бы три отдельных запроса (охват договора,
    объём по счётчику, история начислений), и разворот года на 778 условиях
    превращался в тысячи обращений к базе. Шкала периодов, ради которой всё
    и делается, при таком раскладе не открывалась бы вовсе.
    """

    def __init__(self) -> None:
        self.locations: dict[uuid.UUID, list[str]] = {}
        self.counterparty: dict[uuid.UUID, str | None] = {}
        # location_id → строки энергии, отсортированные по периоду УБЫВАЮЩЕ:
        # поиск «последнего известного» идёт с начала списка.
        self.energy: dict[str, list[StationEnergyPeriod]] = {}
        self.items: dict[str, OpsCostItem] = {}
        # (term_id, location_id) → [(period, gross)] закрытых, по убыванию периода
        self.history: dict[tuple[uuid.UUID, str | None], list[tuple[str, float]]] = {}

    def scope(self, term: OpsContractTerm) -> list[str | None]:
        """Объекты, на которые разворачивается условие.

        `None` в списке — общая затрата компании (офис, услуги на всю сеть).
        Это штатный разрез, а не пропуск.
        """
        if (term.scope_type or "location") == "company":
            return [None]
        if term.location_id:
            return [term.location_id]
        return list(self.locations.get(term.contract_id, []))

    def energy_at(self, location_id: str, period: str) -> StationEnergyPeriod | None:
        for row in self.energy.get(location_id, []):
            if row.period == period:
                return row
        return None

    def last_tariff(self, location_id: str, period: str) -> float | None:
        """Последний известный входящий тариф на дату не позже периода.

        Тариф ведётся отдельным файлом и заполнен не за все месяцы: без отката
        строка осталась бы без суммы там, где цена давно известна.
        """
        for row in self.energy.get(location_id, []):
            if row.period <= period and row.tariff_rub_kwh is not None:
                return float(row.tariff_rub_kwh)
        return None

    def last_volume(self, location_id: str, period: str) -> tuple[float | None, str | None]:
        """Последний известный объём и месяц, из которого он взят.

        Месяц возвращаем не для красоты: в подсказке к сумме человек должен
        видеть, что оценка сделана по апрелю, а не по прошлой неделе.
        """
        for row in self.energy.get(location_id, []):
            if row.period >= period:
                continue
            qty = _metered_volume(row)
            if qty is not None:
                return qty, row.period
        return None, None

    def prior(self, term_id: uuid.UUID, location_id: str | None,
              period: str, limit: int) -> list[float]:
        """Суммы последних закрытых начислений того же обязательства."""
        out: list[float] = []
        for p, gross in self.history.get((term_id, location_id), []):
            if p >= period:
                continue
            out.append(gross)
            if len(out) >= limit:
                break
        return out


async def build_ctx(db: AsyncSession, company_id: uuid.UUID) -> ExpandCtx:
    """Собрать контекст одним заходом: пять запросов вместо тысяч."""
    ctx = ExpandCtx()

    for contract_id, location_id in (await db.execute(
        select(ContractLocation.contract_id, ContractLocation.location_id)
        .where(ContractLocation.company_id == company_id))).all():
        ctx.locations.setdefault(contract_id, []).append(location_id)

    for cid, cp in (await db.execute(
        select(Contract.id, Contract.counterparty_id)
        .where(Contract.company_id == company_id))).all():
        ctx.counterparty[cid] = cp

    rows = (await db.execute(
        select(StationEnergyPeriod)
        .where(StationEnergyPeriod.company_id == company_id)
        .order_by(StationEnergyPeriod.location_id, StationEnergyPeriod.period.desc())
    )).scalars().all()
    for row in rows:
        ctx.energy.setdefault(row.location_id, []).append(row)

    ctx.items = {c.code: c for c in (await db.execute(select(OpsCostItem))).scalars().all()}

    # Корректировки (`seq > 0`) в базу оценки не входят: они относятся к чужому
    # месяцу и удвоили бы его вклад.
    for term_id, location_id, period, actual, expected in (await db.execute(
        select(OpsPeriodCharge.term_id, OpsPeriodCharge.location_id,
               OpsPeriodCharge.period, OpsPeriodCharge.actual_gross,
               OpsPeriodCharge.expected_gross)
        .where(OpsPeriodCharge.company_id == company_id,
               OpsPeriodCharge.seq == 0,
               OpsPeriodCharge.term_id.isnot(None),
               OpsPeriodCharge.status.in_(("matched", "accrued", "corrected")))
        .order_by(OpsPeriodCharge.period.desc()))).all():
        value = actual if actual is not None else expected
        if value is not None:
            ctx.history.setdefault((term_id, location_id), []).append((period, float(value)))

    return ctx


# ── Оценка суммы ───────────────────────────────────────────────────────────

def _net_gross(gross: float | None, net: float | None,
               vat_pct: float | None) -> tuple[float | None, float | None]:
    """Достроить недостающую половину пары «с НДС / без НДС».

    Ведущая величина — с НДС: её видит бухгалтерия и её пишут в договорах
    заказчика. Ставку из текста не выводим — только из явного `vat_pct`.
    """
    if gross is None and net is not None and vat_pct is not None:
        gross = round(float(net) * (1 + float(vat_pct) / 100), 2)
    if net is None and gross is not None and vat_pct is not None:
        net = round(float(gross) / (1 + float(vat_pct) / 100), 2)
    return gross, net


def _metered_volume(row: StationEnergyPeriod | None) -> float | None:
    """Объём кВт·ч за месяц: готовое значение либо разность показаний × КТ.

    Заказчик считает объём именно так, руками в ячейке: в исходном файле лежат
    формулы `=46*30`, `=6.61*40` и пометка `198 - ПУ | К/Т = 50`. Без учёта
    коэффициента трансформации цифра занижена в 30–60 раз.
    """
    if row is None:
        return None
    if row.intake_kwh is not None:
        return float(row.intake_kwh)
    if row.meter_curr is not None and row.meter_prev is not None:
        return (float(row.meter_curr) - float(row.meter_prev)) * float(row.ktrans or 1)
    return None


def estimate(ctx: ExpandCtx, term: OpsContractTerm, period: str,
             location_id: str | None) -> dict[str, Any]:
    """Чем закрыть строку: сумма, объём и КАКИМ МЕТОДОМ она получена.

    Метод возвращается всегда и показывается человеку рядом с цифрой. Сумма без
    пометки происхождения врёт: расчётная выглядит как подтверждённая, и
    расхождение всплывает, когда период уже отдан в бухгалтерию.

    Каскад: явный метод условия → метод статьи → договорная сумма → прошлый
    месяц → среднее → «нет базы». Последнее — не ошибка, а честный ответ:
    строка попадает в рабочий список, а не закрывается тихим нулём.
    """
    item = ctx.items.get(term.cost_item)
    order: list[str] = []
    for basis in (term.estimate_basis, item.default_estimate_basis if item else None):
        if basis and basis not in order:
            order.append(basis)
    for basis in ("contract", "prev_period", "average"):
        if basis not in order:
            order.append(basis)

    vat = float(term.vat_pct) if term.vat_pct else None

    # Переменная часть по счётчику идёт первой независимо от порядка: если объём
    # за месяц известен, любая оценка по истории будет хуже факта.
    if (term.variable_kind or "") == "metered_kwh" and location_id:
        row = ctx.energy_at(location_id, period)
        qty = _metered_volume(row)
        tariff = (float(row.tariff_rub_kwh) if row and row.tariff_rub_kwh is not None
                  else (float(term.tariff_rub) if term.tariff_rub else None))
        if tariff is None:
            tariff = ctx.last_tariff(location_id, period)
        if qty is not None and tariff is not None:
            gross, net = _net_gross(round(qty * tariff, 2), None, vat)
            return {"gross": gross, "net": net, "qty": qty, "basis": "metered"}

        # Объёма за месяц ещё нет — обычное дело: реестр закупки заполняется с
        # лагом в два-три месяца, а тариф приходит отдельным файлом и раньше.
        # Берём последний известный объём этой станции. Это оценка, и она честно
        # помечена: «нет базы» вместо неё означало бы, что мы за месяц вообще
        # ничего не ждём от поставщика — а мы ждём.
        if tariff is not None:
            prev_qty, prev_period = ctx.last_volume(location_id, period)
            if prev_qty is not None:
                gross, net = _net_gross(round(prev_qty * tariff, 2), None, vat)
                return {"gross": gross, "net": net, "qty": prev_qty,
                        "basis": "metered_prev", "qtyFrom": prev_period}

    for basis in order:
        if basis == "contract":
            gross, net = _net_gross(
                float(term.amount_gross) if term.amount_gross else None,
                float(term.amount_net) if term.amount_net else None, vat)
            # Метку «по договору» ставим, только когда сумма ДЕЙСТВИТЕЛЬНО вышла.
            # Иначе строка врёт дважды: подпись обещает договорную величину, а
            # цифры нет. Ноль тоже не годится — в реестре заказчика пустая графа
            # импортировалась нулём (`amount_net = 0.00` у 115 условий аренды),
            # и «0 ₽ по договору» неотличимо от «аренда бесплатная».
            if gross:
                return {"gross": gross, "net": net, "qty": None, "basis": "contract"}

        if basis in ("prev_period", "average"):
            history = ctx.prior(term.id, location_id, period,
                                1 if basis == "prev_period" else AVERAGE_WINDOW)
            if any(history):
                gross, net = _net_gross(round(sum(history) / len(history), 2), None, vat)
                return {"gross": gross, "net": net, "qty": None, "basis": basis}

    return {"gross": None, "net": None, "qty": None, "basis": "none"}


# ── Разворот ───────────────────────────────────────────────────────────────

async def expand(db: AsyncSession, company_id: uuid.UUID, period: str,
                 ctx: ExpandCtx | None = None,
                 terms: list[OpsContractTerm] | None = None) -> dict[str, Any]:
    """Развернуть ожидания месяца. Повтор безопасен.

    Возвращает счётчики и список условий, которые развернуть не удалось — он же
    и есть рабочее задание: без охвата строка реестра была бы пустым местом.
    """
    ctx = ctx or await build_ctx(db, company_id)
    first, last = month_bounds(period)
    if terms is None:
        terms = (await db.execute(select(OpsContractTerm).where(
            OpsContractTerm.company_id == company_id,
            OpsContractTerm.valid_from <= last,
        ))).scalars().all()

    # Уже развёрнутое этого месяца — чтобы не задваивать и не затирать чужую работу.
    existing = {
        (r.term_id, r.location_id): r
        for r in (await db.execute(select(OpsPeriodCharge).where(
            OpsPeriodCharge.company_id == company_id,
            OpsPeriodCharge.period == period,
            OpsPeriodCharge.seq == 0,
            OpsPeriodCharge.term_id.isnot(None),
        ))).scalars().all()
    }

    created = updated = skipped = 0
    blocked: list[dict[str, Any]] = []

    for term in terms:
        # Действие условия задаётся только горизонтом версии: закончилось —
        # значит и ожиданий по нему больше нет. Отдельного флага «активно» не
        # заводим, иначе появилось бы два источника правды об одном и том же.
        if term.valid_from > last or (term.valid_to and term.valid_to < first):
            continue
        if not _due_in_period(term, period):
            continue
        item = ctx.items.get(term.cost_item)
        if item is not None and not item.is_active:
            continue

        locations = ctx.scope(term)
        if not locations:
            blocked.append({"termId": str(term.id), "contractId": str(term.contract_id),
                            "costItem": term.cost_item,
                            "reason": "у договора не заполнен охват по объектам"})
            continue

        for location_id in locations:
            row = existing.get((term.id, location_id))
            # Строку, которую уже ведёт человек, разворот не трогает: документ
            # привязан, сумма поставлена руками или расхождение оспаривается.
            if row is not None and (row.status != "expected" or row.doc_id is not None):
                skipped += 1
                continue

            est = estimate(ctx, term, period, location_id)
            note = f"объём взят за {est['qtyFrom'][:7]}" if est.get("qtyFrom") else None
            due = _due_on(period, term.doc_due_day)

            if row is None:
                db.add(OpsPeriodCharge(
                    company_id=company_id, period=period, cost_item=term.cost_item,
                    term_id=term.id, contract_id=term.contract_id,
                    counterparty_id=ctx.counterparty.get(term.contract_id),
                    location_id=location_id, seq=0,
                    expected_gross=est["gross"], expected_net=est["net"],
                    expected_qty=est["qty"], vat_pct=term.vat_pct,
                    expected_basis=est["basis"], doc_due_on=due, status="expected",
                    note=note,
                ))
                created += 1
            else:
                row.expected_gross = est["gross"]
                row.expected_net = est["net"]
                row.expected_qty = est["qty"]
                row.expected_basis = est["basis"]
                row.vat_pct = term.vat_pct
                row.doc_due_on = due
                if note:
                    row.note = note
                updated += 1

    await db.flush()
    return {"period": period, "created": created, "updated": updated,
            "skipped": skipped, "blocked": blocked}


async def expand_range(db: AsyncSession, company_id: uuid.UUID,
                       date_from: str, date_to: str) -> dict[str, Any]:
    """Развернуть ожидания за диапазон месяцев одним заходом.

    Договоры переходящие: объект работает и в этом месяце, и в следующем, значит
    и документы по нему нужны каждый период. Разворот диапазоном — то, что
    превращает набор отдельных месяцев в календарь: видно и дыры позади, и что
    предстоит собрать впереди.
    """
    ctx = await build_ctx(db, company_id)
    last = month_bounds(date_to)[1]
    terms = (await db.execute(select(OpsContractTerm).where(
        OpsContractTerm.company_id == company_id,
        OpsContractTerm.valid_from <= last,
    ))).scalars().all()

    total = {"created": 0, "updated": 0, "skipped": 0}
    blocked: dict[str, dict[str, Any]] = {}
    for period in month_range(date_from, date_to):
        res = await expand(db, company_id, period, ctx=ctx, terms=terms)
        for k in total:
            total[k] += res[k]
        # Условие без охвата не развернётся ни в одном месяце — показываем один раз.
        for b in res["blocked"]:
            blocked.setdefault(b["termId"], b)
    return {**total, "periods": month_range(date_from, date_to),
            "blocked": list(blocked.values())}


async def contracts_without_terms(db: AsyncSession, company_id: uuid.UUID,
                                  period: str) -> list[dict[str, Any]]:
    """Договоры аренды и энергоснабжения, по которым условий нет вовсе.

    Это вторая половина правды о месяце. Реестр показывает, чего не прислали по
    известным обязательствам; этот список — обязательства, о которых система
    ещё не знает, и потому молчит о них вдвойне.
    """
    _, last = month_bounds(period)
    known = select(OpsContractTerm.contract_id).where(
        OpsContractTerm.company_id == company_id,
        OpsContractTerm.valid_from <= last,
    ).scalar_subquery()

    rows = (await db.execute(select(Contract).where(
        Contract.company_id == company_id,
        Contract.type_code.in_(COST_CONTRACT_TYPES),
        Contract.is_closed.is_(False),
        Contract.id.notin_(known),
    ).limit(500))).scalars().all()

    return [{"contractId": str(c.id), "number": c.number, "date": c.date,
             "typeCode": c.type_code, "counterpartyId": c.counterparty_id,
             "reason": "договор действует, но условий начисления нет"} for c in rows]
