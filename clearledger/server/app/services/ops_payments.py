"""Кассовый факт «Хозяйства»: приём выгрузки списаний и сверка с ожиданиями.

ЗАЧЕМ. «Хозяйство» знало, сколько по договорам ДОЛЖНО быть начислено, и не знало,
сколько заплачено. Вопрос «мы платим больше, чем должны, или меньше» оставался без
ответа, а история до августа 2025 года — вне пространства вовсе.

ЧТО ПРИНИМАЕМ. Сводную выгрузку казначейства заказчика: строка — контрагент, под ним
статьи расходов, справа годы и месяцы. Годовые колонки старых лет кладём на январь
своего года с пометкой `granularity='year'` — смешивать их с месяцами нельзя, но и
терять историю незачем.

ЧЕГО НЕ ДЕЛАЕМ. Не раскладываем сумму по объектам: в счёте энергосбыта на сорок
площадок распределения нет, и выдумывать его — значит выдать догадку за факт. Номера
объектов сохраняются перечнем, а разложить сумму сможет только документ, который это
распределение содержит.

ЗАКРЫТЫЙ МЕСЯЦ НЕ ТРОГАЕМ. Факт живёт рядом с начислениями и не правит их: цифра,
отданная в бухгалтерию, задним числом не меняется (см. `ops_closing`).
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Counterparty, OpsPayment, OpsPeriodCharge

log = logging.getLogger("clearledger.ops.payments")


class PaymentsImportError(ValueError):
    """Выгрузку разобрать нельзя — с причиной, понятной тому, кто её принёс."""


# Статьи выгрузки заказчика → наши коды. Ключ ищется по началу строки: заказчик
# уточняет формулировки («…в рамках инвестиционной деятельности»), и жёсткое
# равенство ломалось бы на каждой правке его отчёта.
COST_ITEM_MAP: tuple[tuple[str, str, bool], ...] = (
    # (начало строки выгрузки, наш код статьи, капитальные ли вложения)
    ("оплата по договорам аренды земли в рамках", "rent", True),
    ("оплата по договорам аренды земли", "rent", False),
    ("оплата по договорам аренды помещений в рамках", "rent_other", True),
    ("оплата по договорам аренды помещений", "rent_other", False),
    ("оплата по договорам аренды прочего имущества", "rent_other", False),
    ("арендная плата по направлениям", "rent", False),
    ("платежи по договорам аренды", "rent", False),
    ("покупка электроэнергии", "energy", False),
    ("оплата за коммунальные услуги", "utilities", False),
    ("оплата поставщикам (подрядчикам) инвестиции", "contractors", True),
    ("оплата поставщикам (подрядчикам) по инвест", "contractors", True),
    ("оплата поставщикам (подрядчикам)", "contractors", False),
    ("оплата товаров, работ, услуг", "contractors", False),
    ("оплата по договорам по техническому обслуживанию", "maintenance", False),
    ("платежи по договорам на информационные", "contractors", False),
    ("приобретение объектов основных средств", "assets", True),
    ("приобретение основных средств", "assets", True),
    ("выплаты штрафов", "penalty", False),
    ("пени, штрафы, неустойки", "penalty", False),
    ("обеспечительные платежи", "deposit", False),
)


def classify(label: str) -> tuple[str, bool]:
    """Статья выгрузки → (наш код, капитальные ли вложения).

    Неизвестная формулировка не отбрасывается, а падает в «прочие расходы»: потерять
    деньги из-за незнакомого слова хуже, чем показать их в общей строке. Незнакомые
    формулировки видны в результате загрузки — по ним и уточняется карта.
    """
    clean = re.sub(r"\s+", " ", (label or "")).strip().lower()
    for prefix, code, capital in COST_ITEM_MAP:
        if clean.startswith(prefix):
            return code, capital
    return "other", False


def parse_period(header: Any, year_hint: int | None = None) -> tuple[str, str] | None:
    """Заголовок колонки → (период ISO, гранулярность).

    Понимает и год («2024»), и месяц года («1_2026»). Итоговые колонки («Общий итог»)
    сознательно не понимает: сумма итога уже разложена по своим колонкам, и приняв
    её, мы удвоили бы расход.
    """
    raw = str(header or "").strip()
    if not raw or "итог" in raw.lower():
        return None
    if re.fullmatch(r"\d{4}", raw):
        return f"{raw}-01-01", "year"
    m = re.fullmatch(r"(\d{1,2})[_./-](\d{4})", raw)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            return f"{year}-{month:02d}-01", "month"
    return None


def _key(period: str, item: str, capital: bool, counterparty: str) -> str:
    """Ключ идемпотентности: повтор той же выгрузки не задваивает суммы."""
    base = f"{period}|{item}|{int(capital)}|{counterparty.strip().lower()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:40]


def read_rows(sheet: Iterable[tuple], *, source_label: str | None = None) -> dict[str, Any]:
    """Разобрать лист сводной выгрузки в строки платежей.

    Формат такой: слева служебные колонки заказчика (статус объекта и перечень его
    бухгалтерских номеров), в середине — «Названия строк» со статьями, справа —
    периоды. Контрагент выделяется тем, что у его итоговой строки заполнен статус;
    статьи идут выше своего итога.
    """
    rows = list(sheet)
    if not rows:
        raise PaymentsImportError("Пустой лист выгрузки")

    header_idx = next((i for i, r in enumerate(rows[:12])
                       if any(parse_period(c) for c in r)), None)
    if header_idx is None:
        raise PaymentsImportError(
            "В выгрузке не нашлось колонок периодов — ожидались «2024» или «1_2026»")
    header = rows[header_idx]
    periods = {i: parse_period(c) for i, c in enumerate(header) if parse_period(c)}
    label_idx = next((i for i, c in enumerate(header)
                      if str(c or "").strip().lower().startswith("названия строк")), None)
    if label_idx is None:
        raise PaymentsImportError("В выгрузке нет колонки «Названия строк»")
    status_idx, numbers_idx = 0, _numbers_column(rows[:header_idx])

    payments: list[dict[str, Any]] = []
    unknown: set[str] = set()
    pending: list[dict[str, Any]] = []
    for row in rows[header_idx + 1:]:
        label = str(row[label_idx] or "").strip() if label_idx < len(row) else ""
        status = str(row[status_idx] or "").strip() if row and status_idx < len(row) else ""
        if status:
            # Итоговая строка контрагента: закрывает его блок и приносит объекты.
            name = re.sub(r"\s+Итог$", "", label).strip() or "—"
            numbers = _numbers(row[numbers_idx] if numbers_idx is not None
                               and numbers_idx < len(row) else None)
            for item in pending:
                item.update({"counterparty_name": name[:300], "status": status,
                             "object_numbers": numbers, "source_label": source_label})
                item["external_key"] = _key(item["period"], item["cost_item"],
                                            item["is_capital"], name)
                payments.append(item)
            pending = []
            continue
        if not label:
            continue
        code, capital = classify(label)
        # В список незнакомых попадает только то, что принесло деньги: строка без
        # сумм — это шапка группы (имя контрагента), а не статья, и жаловаться на
        # неё значит топить настоящие находки в трёхстах именах.
        brought_money = False
        for idx, (period, granularity) in periods.items():
            value = row[idx] if idx < len(row) else None
            if isinstance(value, (int, float)) and value:
                brought_money = True
                pending.append({
                    "period": period, "granularity": granularity, "cost_item": code,
                    "is_capital": capital, "amount": float(value),
                })
        if brought_money and code == "other":
            unknown.add(label[:120])

    return {"payments": payments, "unknown_items": sorted(unknown)}


def _numbers_column(head_rows: list[tuple]) -> int | None:
    """Колонка с бухгалтерскими номерами объектов — по подписи в шапке выгрузки."""
    for row in head_rows:
        for i, cell in enumerate(row):
            if str(cell or "").strip().lower().startswith("№ бух"):
                return i
    return None


def _numbers(cell: Any) -> list[str]:
    """Перечень номеров объектов: в одной ячейке их бывает несколько через «;»."""
    return [n.strip() for n in re.split(r"[;,]", str(cell or "")) if n.strip()][:200]


async def store(db: AsyncSession, company_id: uuid.UUID, parsed: dict[str, Any],
                *, batch_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Записать разобранные платежи. Повтор той же выгрузки обновляет, а не двоит."""
    batch = batch_id or uuid.uuid4()
    known = await _counterparty_index(db, company_id)
    saved, matched = 0, 0
    for item in _fold(parsed["payments"]):
        cp_id = known.get(_norm_name(item["counterparty_name"]))
        if cp_id:
            matched += 1
        await db.execute(pg_insert(OpsPayment).values(
            company_id=company_id, period=item["period"], granularity=item["granularity"],
            cost_item=item["cost_item"], is_capital=item["is_capital"],
            counterparty_id=cp_id, counterparty_name=item["counterparty_name"],
            amount=item["amount"], object_numbers=item.get("object_numbers") or None,
            source_label=item.get("source_label"), batch_id=batch,
            external_key=item["external_key"], loaded_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=[OpsPayment.company_id, OpsPayment.external_key],
            set_={"amount": item["amount"], "counterparty_id": cp_id,
                  "object_numbers": item.get("object_numbers") or None,
                  "batch_id": batch, "loaded_at": datetime.now(timezone.utc)},
        ))
        saved += 1
    await db.flush()
    return {
        "batch_id": str(batch),
        "saved": saved,
        "counterparties_matched": matched,
        "unknown_items": parsed.get("unknown_items") or [],
    }


def _fold(payments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Свернуть строки по ключу ДО записи.

    Разные формулировки заказчика ложатся на один наш код — «оплата поставщикам» и
    «оплата товаров, работ, услуг» обе про подрядчиков. Если писать их по очереди,
    вторая затрёт первую (запись идёт `on conflict do update`), а если складывать в
    базе — повторная загрузка того же файла удвоит суммы. Складываем здесь: тогда
    и слагаемые целы, и повтор даёт ту же цифру.
    """
    folded: dict[str, dict[str, Any]] = {}
    for item in payments:
        key = item["external_key"]
        if key in folded:
            folded[key]["amount"] += item["amount"]
            numbers = set(folded[key].get("object_numbers") or [])
            numbers.update(item.get("object_numbers") or [])
            folded[key]["object_numbers"] = sorted(numbers)
        else:
            folded[key] = dict(item)
    return list(folded.values())


def _norm_name(name: str) -> str:
    """Имя контрагента для сопоставления: без формы собственности и кавычек.

    Заказчик пишет «АВТО ПЕРЕКРЕСТОК ООО», мы — «ООО "Авто Перекресток"». Ключом
    сопоставления это делать нельзя, подсказкой — можно: опознанного контрагента
    видно рядом с исходным именем, и ошибку человек заметит.
    """
    clean = re.sub(r"[\"«»'()\-,.]", " ", (name or "").lower().replace("ё", "е"))
    clean = re.sub(r"\b(ооо|оао|зао|ао|ип|пао|нао|тсж|снт|филиал)\b", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


async def _counterparty_index(db: AsyncSession, company_id: uuid.UUID) -> dict[str, uuid.UUID]:
    rows = (await db.execute(select(Counterparty.id, Counterparty.name).where(
        Counterparty.company_id == company_id))).all()
    return {_norm_name(name): cid for cid, name in rows if name}


async def summary(db: AsyncSession, company_id: uuid.UUID, *,
                  date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    """Факт против ожидания: сколько заплатили и сколько должны были начислить.

    Расхождение считается на чтении и только по месяцам: годовые строки старых лет
    сравнивать не с чем — начислений за те годы в пространстве нет.
    """
    q = select(OpsPayment.period, OpsPayment.cost_item, OpsPayment.granularity,
               OpsPayment.is_capital, func.sum(OpsPayment.amount).label("amount"),
               func.count().label("rows")).where(OpsPayment.company_id == company_id)
    if date_from:
        q = q.where(OpsPayment.period >= date_from)
    if date_to:
        q = q.where(OpsPayment.period <= date_to)
    paid = (await db.execute(q.group_by(
        OpsPayment.period, OpsPayment.cost_item, OpsPayment.granularity,
        OpsPayment.is_capital).order_by(OpsPayment.period))).all()

    charged = dict(((row.period, row.cost_item), float(row.total or 0)) for row in (
        await db.execute(select(
            OpsPeriodCharge.period, OpsPeriodCharge.cost_item,
            func.sum(OpsPeriodCharge.expected_gross).label("total"),
        ).where(OpsPeriodCharge.company_id == company_id).group_by(
            OpsPeriodCharge.period, OpsPeriodCharge.cost_item))).all())

    periods: dict[str, dict[str, Any]] = {}
    for row in paid:
        bucket = periods.setdefault(row.period, {
            "period": row.period, "granularity": row.granularity,
            "paid": 0.0, "capital": 0.0, "expected": 0.0, "items": {},
        })
        bucket["paid"] += float(row.amount or 0)
        if row.is_capital:
            bucket["capital"] += float(row.amount or 0)
        item = bucket["items"].setdefault(row.cost_item, {"paid": 0.0, "expected": 0.0})
        item["paid"] += float(row.amount or 0)
        if row.granularity == "month":
            expected = charged.get((row.period, row.cost_item), 0.0)
            item["expected"] = expected
    for bucket in periods.values():
        bucket["expected"] = sum(i["expected"] for i in bucket["items"].values())
        bucket["diff"] = round(bucket["paid"] - bucket["expected"], 2)
    return {
        "periods": sorted(periods.values(), key=lambda b: b["period"]),
        "total_paid": round(sum(b["paid"] for b in periods.values()), 2),
        "total_capital": round(sum(b["capital"] for b in periods.values()), 2),
    }


async def objects_coverage(db: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Сколько бухгалтерских номеров из выгрузки мы умеем связать с объектами сети.

    Пока — ни одного: бухгалтерский номер заказчика в реестре соответствий не ведётся
    (СТО, п. 6.2: внешние идентификаторы живут связями, а не полями объекта). Честная
    нулевая цифра нужнее умолчания: она показывает, чего не хватает для разложения
    расходов по площадкам.
    """
    rows = (await db.execute(select(OpsPayment.object_numbers).where(
        OpsPayment.company_id == company_id))).scalars().all()
    numbers: set[str] = set()
    for chunk in rows:
        numbers.update(chunk or [])
    return {"numbers_total": len(numbers), "numbers_linked": 0,
            "hint": "бухгалтерский номер объекта в реестре соответствий пока не ведётся"}
